# ADR-0002 — The deployment target is a shared DGX, and soft unload moves into v1

- **Status:** Accepted
- **Date:** 2026-08-11
- **Amends:** **D9** (hard TTL first, soft TTL later), **D7** (pinned devices and groups), **D17** (preflight severity for stage 8)
- **Depends on:** [ADR-0001](0001-build-our-own-router.md) — we own the scheduler, so we are free to make this change
- **Affects:** [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../06_LIFECYCLE_TTL_AND_SCHEDULING.md), [`05_RUNTIME_AND_BATCHING.md`](../05_RUNTIME_AND_BATCHING.md), [`04_API_CONTRACT.md`](../04_API_CONTRACT.md), [`03_TOOL_AUTHORING.md`](../03_TOOL_AUTHORING.md), [`09_IMPLEMENTATION_PLAN.md`](../09_IMPLEMENTATION_PLAN.md)

---

## Context

Two facts arrived during the M−1 gate discussion that the plan had assumed away.

**Fact 1 — preemption is required.**

> *"We don't want to wait for TTL as it could take quite some time, if another process is not being used right now we want to stop it and warm up any process that has a request."*

**Fact 2 — the node is a shared DGX.**

> *"we don't need to kill the container if the GPU resources are freed as this is running on a node that is a shared DGX, however when called again it has to reclaim that memory and thus require some memory management"*

The second fact invalidates the reasoning behind **D9**. That decision deferred soft TTL to phase 2 on three grounds ([`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../06_LIFECYCLE_TTL_AND_SCHEDULING.md) §3), of which the second was decisive:

> *"It holds the group slot, so it does **not** help the contended-GPU case at all — and that case is the primary motivation for the project."*

That is sound **when we own the whole box**, because then the group slot and the VRAM are the same scarce thing. On a shared DGX they come apart:

- the genuinely contended resource is **node VRAM, shared with tenants we do not control**;
- a "group slot" is a row in a table we invented, and holding one costs nothing physical;
- an idle container with its weights released costs a few hundred megabytes of host RAM and **zero VRAM**.

So the argument that made soft TTL a phase-2 item was an artefact of an assumption about the deployment that turned out to be wrong. The decision is reversed on evidence, which is what the decision log exists to permit.

## Decision

### 1. Soft unload is promoted into v1, as the default reclamation mechanism

A tool idle for `soft_ttl` receives `POST /unload`: the handler releases its weights, the container stays alive. This becomes the **normal** way VRAM is reclaimed.

### 2. Hard stop is retained as a backstop, in two roles

- **After a longer idle** (`ttl > soft_ttl`), reclaiming host RAM, the container and the CPU.
- **As a forced fallback** when a handler's `unload()` demonstrably fails to release VRAM (see 5).

Keeping both is deliberate. Soft unload depends on handler cooperation, and handlers are user-authored (**D6**); a mechanism that assumes every author's `unload()` is correct has no answer when one is not. Hard stop always works, because the OS reclaims on process exit.

### 3. Preemption is a requirement, and soft unload is what makes it cheap

A request for tool B **must be able to displace an idle incumbent A immediately**, rather than waiting out A's remaining TTL. `Decision.WAIT` remains only where the config asks for it (`eviction: none`) or where no candidate is evictable.

Displacement is now cheap. [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../06_LIFECYCLE_TTL_AND_SCHEDULING.md) §6.1 budgets container start, Python import and CUDA context init at roughly 5–18 s *before a single weight is read*; soft displacement skips all of it and pays only `load()`. Two consequences follow:

- the scheduler should **prefer soft-unloading an incumbent over stopping it**;
- **being wrong about an eviction costs an order of magnitude less**, which materially reduces the damage from the thrashing scenario in §5.3. `min_residency` remains, but it is protecting against a cheaper mistake.

### 4. Reload under contention is a first-class failure mode, distinct from tool failure

This is the substance of *"requires some memory management"*, and it is the real cost of the shared node.

While a tool is `IDLE_SOFT`, **another tenant may take the VRAM**. The reload then fails with an out-of-memory error that is nobody's fault and not fixable by retrying immediately. The plan currently has no representation for this: every failure path leads to `FAILED`, which means "this tool is broken".

Required behaviour:

- a **distinct reason** — VRAM unavailable — separate from a handler that raised;
- **excluded from the `max_consecutive_failures` budget** ([`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../06_LIFECYCLE_TTL_AND_SCHEDULING.md) §8.5). A tool must never be marked permanently broken because a neighbour was using the GPU.
- **the tool returns to `IDLE_SOFT`**, not `FAILED`. It is intact; it simply could not get memory.
- a caller-facing **503 saying the GPU is full**, with `Retry-After` — never a message implying the tool is broken. This is guardrail 6 (honest status codes) applied to a case the plan had not anticipated.
- **logged distinctly**, because a rising rate of these is an operational signal about the *node*, not about our tools, and it is the number an operator needs when negotiating for capacity.

### 5. `unload()` becomes mandatory for GPU tools, and its verification a hard FAIL

Under **D9** as written, `unload()` was optional and preflight stage 8 was an advisory GPU-only check landing in M6 ([`13_OPEN_QUESTIONS.md`](../13_OPEN_QUESTIONS.md) D9, [`03_TOOL_AUTHORING.md`](../03_TOOL_AUTHORING.md) §10.1). That was proportionate when soft unload was a phase-2 latency optimisation. It is not proportionate now.

If soft unload is the primary reclamation path, a handler whose `unload()` silently fails to release produces the worst available outcome: **we believe we freed the memory, we tell the scheduler so, and we hold it anyway** — degrading the entire shared node, including other tenants, with no error raised anywhere. The failure is silent and its blast radius extends beyond our own deployment.

Therefore:

- **`unload()` is required in the handler contract for any tool with `devices`**, rather than optional;
- **preflight stage 8 becomes a hard `FAIL`** for GPU tools, measured with `nvidia-smi` before and after;
- a tool that cannot release is **not rejected** — it is marked as requiring hard stop only, and the scheduler never soft-unloads it. Keras/TensorFlow tools are the expected members of this class, and R8's own code contains the confession that clearing a Keras session is *"process-wide, not scoped to this model alone"*.

That last point matters for **D17**'s severity principle: *"a gate that refuses everything imperfect gets bypassed, and a bypassed gate protects nobody."* The tool still deploys; it just loses access to the fast path, and the author is told exactly why.

### 6. Measuring free VRAM is permitted; predicting a model's consumption is still not

**D7** rejected VRAM-aware scheduling because *"we cannot reliably predict a model's VRAM: it depends on batch size, sequence length, activation memory and allocator behaviour. A number in a config file would be a comforting fiction."*

That objection is about **prediction**, and it stands. Reading `nvidia-smi` for currently free memory is **measurement**, which D7 never rejected, and on a shared node it is the only way to know anything about what neighbours are doing.

Narrow permission granted, with the boundary drawn explicitly:

- the router **may read live free VRAM immediately before a reload**, to fail fast with the reason from (4) rather than attempting a load that will OOM;
- it **must not** use `vram_gb` from config to decide placement, pack models by predicted size, or admit on the basis of a predicted fit. `vram_gb` stays advisory.

The distinction to hold on to: *"is there memory right now"* is a fact; *"will this model fit"* is a guess. We are allowed the first and still refuse the second. **This must not become a scheduling input** — D9's existing prohibition survives intact.

## Consequences

### The state machine gains a load-bearing state

`IDLE_SOFT` moves from phase-2 sketch to v1 requirement, with `RELOADING` and a reload-failure path that returns to `IDLE_SOFT` rather than `FAILED`. The scheduler must now distinguish **resident in the group** from **resident in VRAM** — the complexity D9 named as its third reason for deferring. That cost is now paid deliberately, in exchange for a mechanism that fits the actual deployment.

### Milestones move

- **M4** gains `POST /unload` and the reload path in the runtime contract.
- **M6** gains the soft sweep, the VRAM-versus-slot distinction, eviction ranking that prefers `IDLE_SOFT` victims, and the reload-contention path.
- **M5.5/M6**: preflight stage 8 becomes a hard FAIL and gains the "cannot release, hard-stop only" classification.
- **Phase 2 item 1** is consumed; what remains there is only the further optimisation work.

### What does not change

- **Groups and pinned devices remain the scheduling primitive** (**D7**). We cap our own residency; we do not attempt to model the node.
- **No database** (guardrail 8). All new state is in memory.
- **The scheduler stays pure** (guardrail 2). Reading `nvidia-smi` happens in the caller and enters the policy as a plain value in the snapshot — never as I/O inside `request_slot`.
- **Hard TTL is still implemented first** in TDD order. Soft unload builds on it; it does not replace it.

## Risks

| Risk | Mitigation |
|---|---|
| A handler's `unload()` lies and VRAM is silently retained | Preflight stage 8 as a hard FAIL; the tool is classified hard-stop-only rather than trusted |
| Reload contention becomes the dominant failure and callers see frequent 503s | Distinct reason and dedicated logging make the rate visible from day one; the escalation is `keep_warm` on the affected tool, or fewer soft-idle tools |
| The soft/hard distinction confuses operators | `/status` must show both states plainly, with the two countdowns separate |
| We drift toward VRAM-aware scheduling by increments | The boundary in (6) is written down: measure the present, never predict the future |

## Revisit if

- the DGX stops being shared, in which case D9's original reasoning becomes valid again and soft TTL could revert to an optimisation rather than the default;
- reload contention proves frequent enough that holding VRAM continuously is cheaper than releasing it, which would be evidence that our share of the node is genuinely reserved rather than shared;
- a majority of tools turn out to be unable to release, making the soft path the exception and not the rule.

## Notes

Worth recording plainly: **D9 was not wrong when it was written.** It reasoned correctly from an assumption about the deployment that nobody had yet stated. The lesson is the one [`HANDOFF.md`](../HANDOFF.md) §5 asks for — *"a decision's stated rationale does not match what you find in practice"* is exactly the kind of pushback the reasoning was recorded to enable. Here the rationale was intact and the premise moved.

# ADR-0004 — v1 reclaims resources by stopping containers; soft unload is deferred

- **Status:** Accepted
- **Date:** 2026-08-13
- **Supersedes:** [ADR-0002](0002-shared-node-soft-unload.md) §1, §3 (the "displacement must be cheap" half), §5 and §6. ADR-0002's §2 and §4 survive in modified form.
- **Amends:** **D9**, **D25**, **D26**, **D27**, **D28**, and guardrails 5b/5c in [`13_OPEN_QUESTIONS.md`](../13_OPEN_QUESTIONS.md) Part D
- **Affects:** [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../06_LIFECYCLE_TTL_AND_SCHEDULING.md), [`05_RUNTIME_AND_BATCHING.md`](../05_RUNTIME_AND_BATCHING.md), [`04_API_CONTRACT.md`](../04_API_CONTRACT.md), [`03_TOOL_AUTHORING.md`](../03_TOOL_AUTHORING.md), [`02_CONFIGURATION.md`](../02_CONFIGURATION.md), [`09_IMPLEMENTATION_PLAN.md`](../09_IMPLEMENTATION_PLAN.md)
- **Does not affect:** [ADR-0001](0001-build-our-own-router.md). We still own the router; this ADR makes it smaller.

---

## Context

[ADR-0002](0002-shared-node-soft-unload.md) promoted soft unload from a phase-2 optimisation to **the default reclamation mechanism in v1**, on the premise that a shared DGX makes prompt VRAM release close to mandatory. That premise was inferred from one sentence about the deployment, and it was never checked with the person who wrote it.

It has now been checked, and it was **stronger than intended**:

> *"Unloading on the shared DGX is not 'so' critical, in the sense that we can provide a timer for soft unload and a larger timer for hard unload for example. **We do not have any mechanism to quickly unload a model on demand, we just don't want to block all the resources indefinitely.** If soft unload is not possible let's just not use it and do hard unloads and find out if it becomes a problem later by implementing more complexity in the system."*

Three things follow, and each one removes a load-bearing assumption from ADR-0002:

1. **The requirement is "do not hold resources indefinitely", not "release VRAM promptly".** A timer satisfies it. ADR-0002 read a latency requirement into a liveness requirement.
2. **Nobody is waiting on a fast release.** ADR-0002 §3 justified soft unload by the 5–18 s of fixed cost it skips. That saving is real, and on this workload it is an optimisation rather than a necessity.
3. **The instruction on how to proceed under uncertainty is explicit:** ship the simple mechanism, and add complexity only when a measurement demands it.

**This ADR therefore reverses ADR-0002 on the axis that matters and keeps it on the axis that does not.** ADR-0002 was correct that the deployment is shared and that a neighbour can take memory from us; it was wrong that this obliges us to build an alive-but-unloaded state in v1.

## Decision

### 1. v1 reclaims resources by **stopping the container**. There is no soft unload.

A tool idle for `ttl` is **stopped**. The OS reclaims VRAM, host RAM, the container and the group slot in one action, and it works for every tool regardless of what its handler does.

**There is no `IDLE_SOFT` state, no `POST /unload`, no `RELOADING`, and no reload path** in v1.

### 2. Preemption survives unchanged in intent, and is satisfied by hard stop

**D25** stands: a request for tool B displaces an idle incumbent A rather than waiting out A's remaining TTL, subject to `min_residency` and in-flight immunity. What changes is only the *mechanism* — `EVICT_THEN_GRANT` in every case, never `SOFT_UNLOAD_THEN_GRANT`.

This costs the displaced tool a full cold start on its next request instead of a weight load. **That is the accepted cost of this ADR, and it is the only one.**

Worth stating plainly, because it is the reason this descope is nearly free: **preemption is not extra machinery.** The scheduler already has to pick and evict a victim when a group is full; preemption is that same code path triggered by a request rather than by a timer. Removing soft unload removes a *mechanism*, not the *policy*.

### 3. One idle timer, not two

`ttl` is the only idle timer in v1. **`soft_ttl` is reserved in the config schema and rejected with a message pointing at this ADR** — reserving the key now means re-promoting soft unload later is additive rather than a config break, and rejecting it loudly means nobody sets it believing it does something.

This is the rare descope that makes the config surface *smaller*, which is guardrail 10 working as intended.

### 4. `unload()` returns to advisory

**D26** made `unload()` mandatory for GPU tools and preflight stage 8 a hard `FAIL`, because a handler that lied about releasing VRAM would silently degrade a shared node. **With no soft unload, nothing ever calls `unload()` on the reclamation path**, so the lie has no victim: the container is stopped and the OS reclaims regardless.

- `unload()` becomes **optional** in the handler contract, documented as good hygiene and as the hook soft unload will use when it returns.
- **Preflight stage 8 is removed from v1.** It was the only preflight stage requiring a GPU, so preflight becomes fully runnable on a laptop — which is what guardrail 12 asks for anyway.
- **The "hard-stop-only" tool class disappears**, along with `can_soft_unload` in the scheduler snapshot. Every tool is hard-stop-only now, so the distinction carries no information.

**The TensorFlow/Keras problem dissolves rather than being solved.** Those handlers could not reliably release VRAM in-process; under this ADR nobody asks them to. R8's confession — that clearing a Keras session is *"process-wide, not scoped to this model alone"* — stops being a constraint we design around.

### 5. VRAM contention moves from the reload path to the cold-start path, and stays a first-class failure mode

This is the part of ADR-0002 that **survives**, and it must not be discarded with the rest.

A neighbour can take VRAM at any time. Under ADR-0002 the exposure was a failed *reload* from `IDLE_SOFT`; under this ADR it is a failed *cold start* from `STOPPED`. The exposure is the same, the trigger is different, and the required behaviour is nearly identical:

| Aspect | Rule |
|---|---|
| Resulting state | Return to **`STOPPED`** (was: `IDLE_SOFT`), never `FAILED`. The tool is intact; it could not get memory. |
| Failure budget | **Excluded from `max_consecutive_failures`.** A neighbour's usage must never permanently disable our tool. |
| Caller response | **503 with `Retry-After`** and `reason: vram_unavailable` — never a message implying the tool is broken. |
| Logging | **Logged under its own reason.** A rising rate describes the *node*, not our tools. |

**D28** is therefore retained in full, with `IDLE_SOFT` replaced by `STOPPED`. Guardrail 5b — *a neighbour's VRAM usage must never mark our tool `FAILED`* — is retained **verbatim**.

### 6. Measuring free VRAM stays permitted; predicting consumption stays refused

**D27** and ADR-0002 §6 are retained unchanged in substance. The router may read live free VRAM immediately before a container start, to fail fast with the reason in (5) rather than paying a container start that will OOM. It still must not use `vram_gb` to decide placement, and the measurement still enters the policy as a plain value on the snapshot rather than as I/O inside `request_slot` (guardrail 2).

The line holds exactly as before: **"is there memory right now" is a fact; "will this model fit" is a guess.**

## What this removes

Traced in full, because the value of this ADR is the size of this list.

| Artefact | Status in v1 |
|---|---|
| `IDLE_SOFT` state | **Removed** from the state machine |
| `RELOADING` state and the reload-failure edge back to `IDLE_SOFT` | **Removed** |
| `POST /unload` on the runtime contract, and the reload path | **Removed** from the runtime ([`05_RUNTIME_AND_BATCHING.md`](../05_RUNTIME_AND_BATCHING.md)) |
| `/ready` answering 503-with-reason after an unload | **Removed** — `/ready` reverts to the single question "are the weights loaded" |
| `POST /admin/tools/{tool}/unload` and `tswap unload` | **Removed** from the API and CLI surfaces |
| `Decision.SOFT_UNLOAD_THEN_GRANT` | **Removed** from the scheduler |
| `can_soft_unload` on the snapshot, and the hard-stop-only tool class | **Removed** |
| The slot-versus-VRAM residency split ([`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../06_LIFECYCLE_TTL_AND_SCHEDULING.md) §5.1.1) | **Removed** — one residency question again, which is what **D9** originally deferred this work to avoid |
| Eviction ranking preferring `IDLE_SOFT` victims | **Removed** — ranking is `last_used` plus a deterministic tie-break |
| The soft sweep in the watchdog | **Removed** — the tick loses a job |
| Preflight stage 8 (`nvidia-smi` before/after) | **Removed from v1**; preflight becomes GPU-free end to end |
| `soft_ttl` as a live config key | **Reserved and rejected**, not silently ignored |
| Scenarios §8.1b and §8.1c | **Removed** from the test corpus |

**Milestones shrink accordingly:** M4 loses the unload/reload cycle and its five contract tests, M5.5 loses its only GPU-dependent stage, and M6 loses the soft sweep, `SOFT_UNLOAD_THEN_GRANT`, the residency split and two worked scenarios. Nothing is added anywhere.

## What this costs

Stated without minimisation, because a descope that claims to cost nothing is usually hiding something.

1. **Every displacement now costs a full cold start** on the victim's next request — the 5–18 s of container start, Python import and CUDA init that [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../06_LIFECYCLE_TTL_AND_SCHEDULING.md) §6.1 budgets, plus weight load. Under ADR-0002 that would have been a weight load alone.
2. **Thrashing is more expensive when it happens.** ADR-0002 §3 observed that cheap displacement defuses the alternating-request pathology in §5.3. Without it, `min_residency` goes back to being the primary defence rather than a secondary one. **It is therefore more important, not less** — and thrash detection (§5.3 item 3) becomes the observability that tells us whether this ADR was wrong.
3. **VRAM returns to the node more slowly**, bounded by `ttl` rather than by `soft_ttl`. This is precisely the trade the requester authorised: *"we just don't want to block all the resources indefinitely."* A timer bounds it; that is what was asked for.

**The mitigation for all three is a config value, not code:** tune `ttl` down for tools that contend, and set `keep_warm: true` for the one or two that dominate traffic. Both already exist.

## Re-promote soft unload when — and these are measurements, not feelings

The point of deferring is to let evidence decide. Any **one** of these is sufficient:

| Trigger | How we would know | Where the number comes from |
|---|---|---|
| **Cold starts dominate latency.** Time spent in cold start exceeds ~20% of total request time for a frequently-used tool | `avg_cold_start_s` × `cold_starts` against total served time | `/status` (M7) |
| **Thrash warnings appear in normal operation** rather than under a synthetic burst | The thrash detector names competing tools | `/status` `warnings[]` (M6) |
| **A neighbour complains, or we are asked to release VRAM faster than `ttl` allows** | Somebody tells us | The DGX's other tenants |
| **Cold-start failures for `vram_unavailable` become common**, indicating we are repeatedly re-acquiring memory we just released | The distinct log reason from (5) | Router logs (M7) |

**When it returns, it returns as specified** — [ADR-0002](0002-shared-node-soft-unload.md) and this repository's history contain a complete design for it. Re-promotion is implementing a known design, not rediscovering one, and the `RuntimeBackend` contract, the `soft_ttl` reserved key and the `Policy` seam are all shaped to accept it.

## Consequences for the Ray Serve question

Not the motivation for this ADR, but a direct consequence worth recording.

[`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md) §4.5 and [ADR-0003](0003-ray-serve-not-adopted.md) identify **one hinge**: can a Serve replica's `reconfigure()` genuinely release VRAM, giving Ray an equivalent of `IDLE_SOFT`? Spike D step 7 exists to answer it, and the evaluation calls it *"the single most valuable open question in this document"*.

**With soft unload out of v1, that question no longer bears on the decision.** We are not building `IDLE_SOFT`, so a framework's ability to express it cannot be a reason to adopt that framework. **D9 is removed from the Ray scorecard entirely**, and the comparison reduces to what was always the stronger argument: operational surface, dependency coupling and failure recovery. [`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md) v3 is rewritten on that basis, and Spike D is retired rather than rescoped.

## Notes

**ADR-0002 was not careless, and this is the second time this plan has moved on a premise rather than on reasoning.** ADR-0002 itself opened by observing that D9 *"reasoned correctly from an assumption about the deployment that nobody had yet stated"*. It then did the same thing: it inferred urgency from *"this is a shared DGX"* and built a state machine on the inference. The reasoning was sound both times; the premise moved both times.

**The generalisable lesson, and it is worth acting on rather than admiring:** when a decision is justified by a fact about the deployment, that fact should be quoted from someone who knows it and marked as verified or inferred. [`HANDOFF.md`](../HANDOFF.md) §6 already lists the DGX tenancy split as something we would have to ask about — and ADR-0002 shipped a v1 feature on it anyway, without asking.

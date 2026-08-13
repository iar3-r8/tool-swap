# 06 — Lifecycle, TTL and Scheduling

> **⚠ This document has not yet been rewritten for [ADR-0004](adr/0004-hard-stop-only-in-v1.md), and §3, §5.1, §5.1.1, §5.2, §7 and §8.1b–8.1c currently describe a design we are not building. The ADR is authoritative; where they disagree, follow the ADR.** A rewrite is pending.
>
> **Decision D9, as amended by [ADR-0004](adr/0004-hard-stop-only-in-v1.md): v1 has one idle timer and reclaims by stopping the container.** There is no soft unload, no `IDLE_SOFT` and no `POST /unload`. [ADR-0002](adr/0002-shared-node-soft-unload.md) had promoted soft unload into v1; the requester clarified that a timer suffices — *"we just don't want to block all the resources indefinitely"*.
> **Decision D7**, as amended by [ADR-0002](adr/0002-shared-node-soft-unload.md) §6 (**retained**): pinned devices and groups remain the scheduling primitive. Free VRAM may be **measured** before a start; a model's consumption is still never **predicted**.
>
> This is the heart of the product. Everything else is plumbing around it.

---

## 0. The deployment that shapes this document

**tool-swap runs on a shared DGX node.** Other tenants, whom we do not control and cannot see, use the same GPUs. Two consequences run through everything below:

1. **We must not hold resources indefinitely**, which is what the idle timer is for. Note the requirement is *bounded* holding, **not** prompt release — [ADR-0002](adr/0002-shared-node-soft-unload.md) inferred the latter and built a state machine on it, and [ADR-0004](adr/0004-hard-stop-only-in-v1.md) reversed that.
2. **Memory we release may be taken by someone else.** A cold start can therefore fail through nobody's fault, and that case must be distinguishable from a broken tool (**D28**).

**Preemption is a requirement.** A request for tool B must be able to displace an idle incumbent A *immediately*, rather than waiting out A's remaining TTL. This is the requirement that ruled out Kubernetes at the M−1 gate ([ADR-0001](adr/0001-build-our-own-router.md)), because Kubernetes allocates devices and leaves the second pod `Pending` rather than evicting an incumbent. **The mechanism is a container stop**, so the displaced tool pays a cold start on its next request — which makes `min_residency` and thrash detection (§5.3) more important, not less.

---

## 1. The problem in one paragraph

We have (say) 4 GPUs and 20 models, on a node we share with other tenants. Total VRAM demand far exceeds capacity, but at any instant only a few models are actually in use, and usage is bursty and unpredictable. We want each model to *appear* permanently available while only the working set actually occupies memory. This is caching, with GPUs as the cache and containers as the entries — which means the design questions are the classic ones: admission, eviction, and what to do on a miss. The shared node adds a fourth: what to do when the cache entry you were promised has been taken by somebody else.

---

## 2. Hard TTL

**Rule:** a tool in `READY` with `inflight == 0` and `now - last_used >= ttl` is **stopped**.

- `last_used` updates on request **completion** (not arrival), so a long-running request cannot expire mid-flight.
- `inflight > 0` makes a model immune (§5).
- **Sentinel discipline, stated explicitly** (copied from llama-swap, which names all three in its schema): **`-1` inherits `defaults.ttl`**, **`0` never expires**, **`>0` is a number of idle seconds**. `keep_warm: true` implies exemption from TTL regardless.
- The watchdog runs on a tick (default 5 s) and processes expiries; it does not need to be precise, and TTL is documented as "at least `ttl` seconds of idleness", never an exact deadline.

Stopping frees everything: VRAM, host RAM, the group slot, the CPU. Cost: the next request pays a full cold start.

**Stopping is the only reclamation path in v1** ([ADR-0004](adr/0004-hard-stop-only-in-v1.md)), and it always works — the OS reclaims on process exit, whatever the handler believes.

### 2.1 The grace period before a force-kill

A tool being stopped is given time to finish, in three steps ([`01_ARCHITECTURE.md`](01_ARCHITECTURE.md) §5.1–5.2, restated here because this is where a reader looks for it):

1. **In-flight requests block eviction entirely.** A tool with `inflight > 0` is never evicted and never TTL-stopped — so the mid-inference force-kill does not arise for us at all.
2. Wait up to **`drain_timeout`** (default 30 s) for in-flight work to finish, then **SIGTERM**.
3. **SIGKILL** after **`stop_timeout`** (default 30 s).

**Confirmed compatible with [ADR-0004](adr/0004-hard-stop-only-in-v1.md).** That ADR rewrote the reclamation path around hard stop while these rules predate it; nothing in it changes them, and this sentence exists so nobody has to re-derive that.

> **A default worth checking against your slowest tool.** llama-swap force-kills after a flat **10 s** `unloadTimeout` — reasonable for servers that stream tokens continuously. **Ours must cover one long, atomic call**: a CT segmenter whose single inference takes 90 s will exceed `drain_timeout: 30` and be SIGTERMed mid-request. Rule 1 protects it only while the request is counted as in-flight. **Set `drain_timeout` above the p99 inference time for such tools**, and let `tswap preflight`'s measured inference time inform it.

### Choosing TTL values

The trade-off is entirely about the cost of a cold start versus the cost of holding resources.

| Model profile | Cold start | Suggested TTL |
|---|---|---|
| Small CPU model (text cleanup) | < 2 s | `keep_warm: true` — never stop it, it costs nothing |
| Medium GPU encoder (RAD-DINO, ~1 GB) | 10–30 s | 300–900 s |
| Large 3D model (CT segmenter, TotalSegmentator-class) | 60–180 s | 1800–3600 s, or `keep_warm` if it is the primary workload |
| Rarely used specialist (a segmenter run twice a week) | 60 s | 120 s — reclaim aggressively |

Rule of thumb worth documenting: **TTL ≈ 20–50× the cold start**, then adjust from the observed `cold_starts` and `avg_cold_start_s` in `/status`. If a model's cold starts are climbing, its TTL is too short for its actual traffic pattern.

---

## 3. ~~Soft TTL~~ — **removed from v1**

> **This section previously specified soft unload as "the default reclamation mechanism (v1)", with an `IDLE_SOFT` state, a `RELOADING` state and a soft sweep. [ADR-0004](adr/0004-hard-stop-only-in-v1.md) removed all of it, and the specification survived here by oversight** — a live contradiction with this document's own header. It is deleted rather than preserved, because [ADR-0002](adr/0002-shared-node-soft-unload.md) already holds the complete design should the triggers ever fire.

**v1 has one idle timer (§2) and one reclamation mechanism: stop the container.** There is no `soft_ttl`, no `IDLE_SOFT`, no `RELOADING`, no `POST /unload`, and no soft sweep in the watchdog.

**What survives from the old §3, and it is important:** the shared node can still take VRAM out from under us. That exposure has simply moved from a failed *reload* to a failed *cold start*, and it is specified in §3.3 below.

### 3.1 Why the fast path was given up

The saving was real — importing torch, initialising a CUDA context and JIT-warming kernels is 10–20 s before a single weight is read, and soft unload skipped all of it. It was given up because the requirement turned out to be *"we just don't want to block all the resources indefinitely"*, which a timer satisfies. **[ADR-0004](adr/0004-hard-stop-only-in-v1.md) names the four measurements that would bring it back**; the strongest is cold starts exceeding ~20% of total request time for a frequently-used tool.

### 3.2 What this costs preemption

Displacement (**D25**) now costs the victim a **full cold start** rather than a weight load. Two consequences, and both make §5.3 more important rather than less:

- **`min_residency` is the primary defence against thrashing, not a secondary one.**
- **Thrash detection is the instrumentation that tells us whether ADR-0004 was the wrong call.**

### 3.3 Cold start under contention — a failure that is nobody's fault

**This is the "memory management" the shared node forces on us, and it is a first-class failure mode.**

A neighbour may hold the VRAM when we try to start. The start then fails with an out-of-memory error that no retry will immediately fix and that no change to our tool would have prevented.

The trap to avoid: treating this as a tool failure. Every other failure path leads to `FAILED`, which means *"this tool is broken"* — and a tool marked broken because a neighbour was using the GPU is both wrong and actively misleading during an incident.

Required behaviour:

| Aspect | Rule |
|---|---|
| Resulting state | Return to **`STOPPED`**, never `FAILED`. The tool is intact; it could not get memory. |
| Failure budget | **Excluded from `max_consecutive_failures`** (§8.5). A neighbour's usage must never permanently disable our tool. |
| Caller response | **503 with `Retry-After`** and a reason meaning *the GPU is full*, never one implying the tool is broken. Guardrail 6 (honest status codes), applied to a case the first draft did not anticipate. |
| Logging | **Logged distinctly.** A rising rate of these describes the *node*, not our tools, and it is the number an operator needs when negotiating for capacity. |

**Fail fast where possible.** The router may read live free VRAM immediately before attempting a start, and return the above rather than paying a container start it can predict will OOM. This is *measurement*, explicitly permitted by **D27** — as distinct from *predicting* how much a model will consume, which **D7** rejects and which remains rejected. The line: **"is there memory right now" is a fact; "will this model fit" is a guess.** We take the first and still refuse the second, and neither ever becomes an input to `request_slot` (§9).

### 3.4 Handlers that cannot release — no longer our problem

Under soft unload, a handler whose `unload()` silently failed to release was the worst case available: we would believe the VRAM was free, tell the scheduler so, and hold it anyway. **With nothing calling `unload()` on the reclamation path, that failure has no victim** — the container stops and the OS reclaims regardless ([ADR-0004](adr/0004-hard-stop-only-in-v1.md) §4).

Consequently: `unload()` is **advisory**, preflight stage 8 is **removed**, and the **hard-stop-only tool class disappears** — every tool is hard-stop-only now, so the distinction carries no information. **The TensorFlow/Keras problem dissolves rather than being solved**: those handlers could not reliably release in-process, and nobody asks them to.

---

## 4. Groups: the scheduling primitive

A **group** caps how many of its members may be resident simultaneously.

```yaml
groups:
  gpu0: { max_resident: 1, devices: [0], eviction: lru }   # strict swapping on GPU 0
  gpu1: { max_resident: 2, devices: [1] }                  # two small models share GPU 1
  llm:  { max_resident: 1, devices: [2,3], eviction: none } # never evict; requests wait
  cpu:  { max_resident: 8 }                                 # CPU models, generous
```

Why groups rather than modelling VRAM directly (**D7**):

- **Simple to reason about.** "One model on GPU 0 at a time" is a sentence anyone understands; "sum of estimated VRAM ≤ 22 GB with fragmentation headroom" is not.
- **Honest.** We cannot reliably predict a model's VRAM: it depends on batch size, sequence length, activation memory and allocator behaviour. A number in a config file would be a comforting fiction.
- **Sufficient.** Most real deployments are "these three big models take turns on this GPU".
- **Extensible.** `vram_gb` is already in the schema as advisory; a future scheduler can use it *in addition* to groups without any config break.

**What groups cannot do, stated plainly:** they cap **our own** residency and are blind to other tenants on the shared node. `max_resident: 1` guarantees we run one model on that GPU; it guarantees nothing about how much VRAM is actually free, because a neighbour may be using most of it. That gap is handled at reload time (§3.3), not by making groups cleverer — the alternative is predicting VRAM, which **D7** rejects and [ADR-0002](adr/0002-shared-node-soft-unload.md) §6 continues to reject.

Semantics:
- Every model belongs to exactly one group (`default` if unspecified).
- `max_resident` counts tools in `STARTING`, `LOADING` and `READY` — i.e. anything holding or about to hold resources. Not `STOPPED` or `FAILED`.
- A group may declare `devices`, which members inherit unless they override.
- Groups are independent: a full `gpu0` never blocks `gpu1`.
- Multiple groups *may* be configured onto the same physical device. That is the user's choice and their responsibility; we warn at validation but do not forbid it (someone will legitimately want two 3 GB models on a 24 GB card).

---

## 5. Admission and eviction

### 5.1 The algorithm (pure, synchronous, unit-testable)

```
request_slot(tool) -> Decision:
    group = groups[tool.group]
    resident = [t for t in group.members if t.state in HOLDING_STATES]

    if tool in resident:                        return Decision.ALREADY_RESIDENT
    if len(resident) < group.max_resident:      return Decision.GRANT(device=assign_device(tool, group))

    # group is full: consider displacing an incumbent
    if group.eviction == "none":                return Decision.WAIT
    candidates = [t for t in resident
                  if t.inflight == 0
                  and not t.keep_warm
                  and t.state in EVICTABLE_STATES]
    if not candidates:                          return Decision.WAIT
    victim = rank(candidates, group.eviction)[0]
    return Decision.EVICT_THEN_GRANT(victim)
```

**There is exactly one displacement decision** ([ADR-0004](adr/0004-hard-stop-only-in-v1.md)). `SOFT_UNLOAD_THEN_GRANT` and `can_soft_unload` are gone, and with them the slot-versus-VRAM residency split — one residency question again.

### 5.1.1 Victim selection: LRU, with an optional eviction weight

**LRU alone assumes cold starts are comparable. Ours are not** — a CPU function restarts in under a second, a large segmenter takes ninety — so evicting the expensive tool because it idled marginally longer is a bad trade, and on a zoo with this spread it will happen routinely.

**The remedy is one optional per-tool integer**, breaking ties in an otherwise-LRU comparator:

```yaml
tools:
  ct_segmenter:
    evict_cost: 10        # optional, default 1; higher = prefer to keep resident
```

`rank()` orders by `(evict_cost, last_used)` rather than `last_used` alone, so a cheap-to-restart tool is displaced first and LRU decides among equals. **It stays pure and stays testable** (guardrail 2).

> **What we deliberately refuse.** llama-swap generalises this into `matrix` — a constraint solver over declared legal combinations, with a DSL (`&`, `|`, `()`, `+ref`) and a `vars` indirection table of 8-character names — *"the solver minimizes eviction cost when swapping"*. **That is the clearest illustration in the whole llama-swap capture of what R4 costs when scheduling expressiveness wins.** One integer captures nearly all the benefit; we take the integer and leave the solver.

### 5.1.2 The queue policy is a seam, even with one implementation

Our queue (**D22**) is FIFO, and **v1 keeps it that way deliberately** — priority is where schedulers acquire starvation bugs, and [`16_COMPLEXITY_AUDIT.md`](16_COMPLEXITY_AUDIT.md) §5 names scheduler purity as never-trim.

**What we copy from llama-swap is the *shape*, not the feature.** Their `routing.scheduler.use` is an enum whose only current value is `fifo`, with per-model `priority` available underneath it. Declaring the seam now means a second policy is **a new implementation rather than a rewrite** — the same reasoning as `ContainerBackend` and `RuntimeBackend`. **Cost: an interface boundary and no feature.** Do this before M2, when there is no code to retrofit.

`Decision` is one of `ALREADY_RESIDENT | GRANT(device) | EVICT_THEN_GRANT(victim) | WAIT` — **four kinds, not five** ([ADR-0004](adr/0004-hard-stop-only-in-v1.md)). Being a pure function of a state snapshot means the entire policy surface — the whole reason this project exists — is testable in milliseconds with no Docker, no GPU and no sleeping. Do not let this function acquire I/O.

**Two things this function must never do**, both consequences of the shared node:

- **Read `nvidia-smi`.** Free-VRAM measurement (§3.3) happens in the *caller* and enters the policy as a plain value on the snapshot, if at all. Guardrail 2 holds: the scheduler is pure.
- **Use `vram_gb` to decide anything.** It stays advisory. Measuring the present is permitted; predicting a model's consumption is not (**D7**, [ADR-0002](adr/0002-shared-node-soft-unload.md) §6).

*(The `can_soft_unload` flag and the tool classification behind it are gone — [ADR-0004](adr/0004-hard-stop-only-in-v1.md) §4. Every tool is displaced the same way: the container stops.)*

### 5.1.1 Residency is now two questions, not one

*(The slot-versus-VRAM residency split is removed — [ADR-0004](adr/0004-hard-stop-only-in-v1.md). With no alive-but-unloaded state, holding a group slot and holding VRAM are the same fact again, which is the complexity **D9** originally deferred this work to avoid.)*

### 5.2 Eviction ranking

For `eviction: lru`, rank candidates by:

1. **`evict_cost` ascending** — displace the cheapest-to-restart tool first (§5.1.1).
2. Then by `last_used` ascending (least recently used).
3. Tie-break on lower `vram_gb` if declared, else name (deterministic ordering matters for reproducible tests).

**The ranking picks the victim; there is only one mechanism** ([ADR-0004](adr/0004-hard-stop-only-in-v1.md)). Ties must break deterministically — by tool name — so the policy is reproducible in tests.

Other policies: `lifo` (evict the most recently started — occasionally useful to protect a long-running warm model from a burst of one-off requests) and `none` (never evict; `WAIT` instead).

### 5.3 Fairness and the thundering-herd problem

The pathological case for any swapping system: two clients alternately requesting models A and B in a `max_resident: 1` group. Each request evicts the other's model, so both clients see nothing but cold starts and the GPU spends all its time loading weights and none doing inference. This will happen in production; plan for it.

Mitigations to implement:

1. **`min_residency` (default 30 s).** A model that just became `READY` cannot be evicted for at least this long. This is the single most effective guard: it forces the thrashing pair into alternating batches instead of alternating requests, converting a pathological pattern into a merely slow one. Requests for the other model wait, which is *strictly better* than both thrashing.
2. **Queue coalescing.** All pending requests for the same model share one start and are served in a burst once ready. Already required by [`01_ARCHITECTURE.md`](01_ARCHITECTURE.md) §5.1, and it is what makes `min_residency` effective.
3. **Thrash detection.** Track evictions per model per minute; if it exceeds a threshold, log a prominent warning naming the competing models and suggesting a config fix (raise `max_resident`, separate the groups, or add a GPU). Surface it in `/status` as a `warnings` array. Diagnosing this without help is genuinely hard, so the tool should say it out loud.
4. **Optional `swap_cooldown`** per group: a minimum interval between swaps in that group. Blunt but effective for a pathological workload.

### 5.4 Device assignment

v1 is deliberately simple:
- `devices` explicit on the model → use exactly those.
- Else inherit the group's `devices`.
- Else CPU.

No dynamic device selection, no packing, no VRAM accounting. Translation to Docker: pass the device list as device requests / `NVIDIA_VISIBLE_DEVICES` so the container sees them as `cuda:0..n-1`. **The handler therefore never does device arithmetic** — a deliberate simplification over R8, where tools carried `device`/`gpu_id` parameters and the BentoML service computed `gpu_id = max(0, worker_index - 1)`, an easy source of off-by-one bugs.

Documented growth path (do not build now): a `bin-packing` mode using `vram_gb` plus live `nvidia-smi` free memory, where a group declares total VRAM rather than a model count. Design the scheduler interface so this is a new `Policy` implementation, not a rewrite.

---

## 6. Cold starts

Cold start is the entire cost of this design, so it deserves first-class treatment.

### 6.1 The budget

```
container create+start   0.5–3 s     (image is local; add minutes if pulling)
python + import torch    3–10 s
CUDA context init        1–5 s
weight load from cache   2–60 s      (size and disk dependent)
weight DOWNLOAD          0–1800 s    (first run only — the killer)
warmup / JIT             0–10 s
```

### 6.2 Mitigations (implement all of these)

| Mitigation | Effect |
|---|---|
| **Shared weight cache mount** (mandatory default) | Removes the download from every start after the first. R8's compose already mounted `${HF_HOME}` into containers; do the same for every model by default. |
| **`tswap warm <model>` / `--all`** | Pre-pull weights and pre-build images outside the request path. Run it after deployment and in a cron. |
| **`keep_warm: true`** | For the hot path. The right answer for the one or two models that dominate traffic. |
| **`tswap preload` at boot** | Start `keep_warm` models during `tswap up` so the first user is not the one who waits. |
| **Bake weights into the image** (`post_install` download) | Fastest cold start, largest image. Offer it as a documented trade-off, not a default. |
| **Soft TTL** (v1, and the default) | Removes container start + import + CUDA init from the recovery path, leaving only `load()`. On the shared node this is the primary mechanism, not an optimisation (§3). |
| **Honest reporting** | `cold_start: true` and `queue_ms` in every response's `meta`, plus `avg_cold_start_s` in `/status`. Users tolerate a slow first request they were told about; they do not tolerate mysterious latency. |

### 6.3 Client-visible behaviour during a cold start

The request **blocks** until ready or `queue_timeout`. No 202-and-poll in v1 (it would force every client to implement a state machine). Requirements:

- Bounded by `queue_timeout`; on expiry return 503 with `Retry-After` and a message stating what it was waiting for (`"still LOADING, started 240s ago"`).
- Bounded by `max_queue_depth` → 429.
- Log at INFO on every cold start with the model, the trigger, and the eventual duration. These lines are what make TTL tuning possible.

---

## 7. The watchdog

One periodic task, tick default 5 s:

1. **TTL sweep** — expire `READY` tools past their deadline (skipping `inflight > 0` and `keep_warm`).
3. **Liveness** — verify containers believed to be running still exist; mark vanished ones `FAILED` (a container can die from an OOM kill or a host restart without anyone noticing otherwise).
4. **Readiness re-check** — occasionally re-probe `/ready` for `READY` models to catch a model that silently unloaded itself.
5. **Retry** — retry `FAILED` models whose backoff has elapsed, but only if `keep_warm` (do not spontaneously resurrect on-demand models; wait for a request).
6. **Reconcile** — periodically list managed containers and adopt/stop orphans.

Requirements: the tick must never block (all I/O concurrent with timeouts), must never crash the router (catch and log per-model), and must be driven by the injectable `Clock` so tests advance time instantly. A watchdog that dies silently leaves models resident forever — a failure that is invisible until the GPUs are full, so log a heartbeat line at DEBUG and expose `last_tick_age_s` in `/status`.

---

## 8. Worked scenarios (these become the integration tests)

### 8.1 Simple swap

```
groups: gpu0 { max_resident: 1 }, models A and B both in gpu0

t=0    request A     -> A STOPPED, slot free       -> start A (cold 20s) -> serve
t=25   request B     -> group full, A idle 5s
                        min_residency 30s not met  -> WAIT
t=31   (retry)                                     -> evict A, start B -> serve
t=60   request A                                   -> evict B, start A -> serve
```

Assertions: exactly one model resident at any time; no request lost; `min_residency` respected; `TOOL_UNAVAILABLE` with `reason: evicted` is never returned to a client (the wait absorbed it).

### ~~8.1b Soft swap~~ · ~~8.1c Hard-stop-only tool~~ — **both removed**

Both scenarios tested soft unload, which [ADR-0004](adr/0004-hard-stop-only-in-v1.md) removed from v1. They are struck out rather than deleted so that a reader of the ADR's *"Scenarios §8.1b and §8.1c are removed"* line can see what was here — and so they can be restored verbatim if the ADR's triggers ever fire.

### 8.1d Eviction prefers the cheap-to-restart victim

```
groups: gpu0 { max_resident: 1 }
A = cpu_helper     evict_cost: 1   last_used: t-100
B = ct_segmenter   evict_cost: 10  last_used: t-120   (idle LONGER, but 90s cold start)
C requests the slot
```

Assertion: the victim is **A**, not B, even though B is less recently used. Under plain LRU B would be evicted and the zoo would pay a 90-second cold start to save a one-second one (§5.1.1). With `evict_cost` equal, ranking falls back to LRU and is deterministic on ties.

### 8.2 TTL expiry

```
ttl=300, request at t=0 completes at t=2
t=302  watchdog stops the model
t=400  request        -> cold start
```

Assertion: stop happens once, in the tick after the deadline; `ttl_expires_in_s` in `/status` counts down correctly.

### 8.3 In-flight protection

```
long request on A (60s), ttl=10, B requests a slot at t=5
```

Assertion: A is **not** evicted while in-flight; B waits; A is stopped only after A's request completes and its TTL elapses. Verify the in-flight counter returns to zero even when the client disconnects mid-request (the `finally` must run).

### 8.4 Thundering herd

```
20 concurrent requests for a STOPPED model
```

Assertion: exactly **one** container start; all 20 served; `cold_start: true` on all of them (they all waited for the same start); queue depth peaks at 20 and drains.

### 8.5 Failure and backoff

```
model whose load() raises
```

Assertion: `FAILED` with the traceback available in logs and `last_error` in `/status`; three retries with backoff `[1,5,15]`; then no further automatic retries; `/run` returns 503 `TOOL_UNAVAILABLE` with `reason: failed` immediately (no pointless 600 s wait per request); `POST /admin/tools/{tool}/start` clears the state and the failure counter.

### 8.5b Reload under contention — the shared-node case

```
A is STOPPED. Another tenant takes the GPU's free VRAM.
t=0    request A     -> STARTING -> load() raises OOM
```

Assertions, each of which is a distinct way this could be got wrong (§3.3):

- A returns to **`STOPPED`**, *not* `FAILED`;
- `consecutive_failures` is **unchanged** — a neighbour must never exhaust our failure budget;
- the caller gets **503** with a reason meaning *the GPU is full* and a `Retry-After`, never a message implying the tool is broken;
- the event is logged under its own reason, separable from handler failures when someone greps the logs during an incident;
- a later request, once the neighbour releases, reloads normally with no operator intervention.

The regression this prevents is subtle and expensive: a tool that quietly marks itself broken every time the node is busy, and stays broken until someone notices and restarts it.

### 8.6 Router restart

```
two models READY, router restarted
```

Assertion: containers survive; the router adopts them as `READY`; TTL bookkeeping restarts from `now` (documented: TTL is not preserved across a router restart); orphans (models removed from the config) are stopped per the `orphans` policy.

### 8.7 Group isolation

```
gpu0 full and thrashing; a request arrives for a model in gpu1
```

Assertion: the gpu1 model starts immediately, entirely unaffected. Trivial-sounding, but a shared global lock held during a start would break it — hence a dedicated test.

---

## 9. Testability requirements (non-negotiable)

The failure mode to avoid: TTL/eviction tests that `sleep(31)`, so the suite takes minutes and nobody runs it. The design already accommodates this — enforce it.

```python
@dataclass
class ModelRuntimeState:
    """Everything the scheduler is allowed to see. Plain data, no I/O."""
    name: str
    group: str
    state: ModelState
    last_used: float
    became_ready_at: float | None
    inflight: int
    queued: int
    keep_warm: bool
    ttl: float
    evict_cost: int                # default 1; higher = prefer to keep resident (§5.1.1)
    vram_gb: float | None          # advisory only; never an input to a decision
    consecutive_failures: int      # vram_unavailable failures never increment this


def request_slot(snapshot: SchedulerSnapshot, tool: str, now: float) -> Decision:
    """Pure. No I/O, no clock access, no logging side effects."""


def find_expired(snapshot: SchedulerSnapshot, now: float) -> list[Expiry]:
    """Pure. Returns the tools whose TTL has elapsed."""
```

**`soft_ttl` and `can_soft_unload` are gone from the snapshot** ([ADR-0004](adr/0004-hard-stop-only-in-v1.md)); `evict_cost` replaces them as the only addition. **One residency question, one idle timer, one eviction mechanism.**

With `ManualClock`, §8's scenarios are all sub-millisecond unit tests. Docker-backed integration tests then verify only that the *effects* happen (a container really starts, really stops, really frees VRAM) — a handful of slow tests behind `@pytest.mark.docker`, not the primary safety net.

---

## 10. Back-pressure on a tool that is `READY` but saturated

**`max_queue_depth` bounds the cold-start queue and never engages here.** A tool that is already `READY` and receiving more than it can serve is not queued for a start, so a third case exists that **D22** does not cover.

Three layers could own it, and the decision is deliberate:

| Layer | Mechanism | Verdict |
|---|---|---|
| **The runtime** | BentoML's dispatcher raises `ServiceUnavailable("process is overloaded")` when it cannot meet the latency budget | **It will happen whether we plan for it or not.** The adapter **must** catch it and give it a distinct saturation reason ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §4.5), or the cause is stripped from the body and the caller sees a bare 503 |
| **The router** | An optional per-tool in-flight cap, returning **429** beyond it — llama-swap's `concurrencyLimit`, default 10 | **Optional, off by default in v1.** The config key exists; unset means uncapped and the runtime's answer applies |
| Nobody | — | ❌ **Rejected.** A saturated tool and a starting tool would both answer 503, and **D28** is precisely about not misattributing a failure |

**Why the router cap is optional rather than default:** the tool knows its own latency budget and we do not. A fixed router-side number would be a guess that overrides a measurement. The cap exists for tools where queueing at the router is genuinely preferable to queueing at the container — and for the operator who wants a hard bound.

# The tool state machine

The router runs each tool inside its own container, and that
container's life has a long ramp-up: creating and starting the
container takes a moment, and loading the model weights inside it
takes longer still. So there is a long window in which the container
is running but cannot answer anything, and then a point — and only a
point — at which the tool is ready to serve. This page documents the
part of the router that tracks where each tool is in that journey:
the six states, the ten legal moves between them, the per-tool
runtime facts the moves read, and the single function that moves a
tool from one state to another —
[`ToolState`](../src/tool_swap/lifecycle/states.py:35),
[`ModelRuntimeState`](../src/tool_swap/lifecycle/states.py:53) and
[`apply_transition`](../src/tool_swap/lifecycle/states.py:104) in
[`states.py`](../src/tool_swap/lifecycle/states.py). The machine
exists so the router has a typed, testable answer to *may a request
go to this tool*: exactly one of its states means *ready to serve*,
and every other state is a reason to queue or refuse.

Without it, the router has no way to tell `LOADING` from `READY` —
to Docker they are the same thing, a container that is `running` —
and a router that routed on container liveness alone would send
requests into a process that is still loading weights, and be
refused by it or made to hang until the load finishes. The machine
is also the single place in the tree that records which states a
tool may occupy and which moves are legal, so the component that
will drive it — the `LifecycleManager`, planned but not built —
never has to re-derive that knowledge by hand.

**Where it sits:** the [spec builder
page](spec-builder.md) documents the layer that decides *what* a
tool's container should look like (the `ContainerSpec`); the
[backend seam page](backend-seam.md) documents the layer that
*starts* that container and reports whether its process is alive;
this page documents the layer that decides *when* a container
should exist at all. The other two pages are each about one
container; this page is about one tool's journey through a sequence
of them.

One honest caveat before the detail: **nothing in the shipped tree
drives this machine yet.** There is no `LifecycleManager`, no probe
advancing the states, and no container has been started through
this path. The machine — the states, the table, the holder, the
transition function — is shipped and fully tested; its driver is
not. The rest of the page documents the machine in full, and says
explicitly where it stops.

## Status and design sources

**Status: slice B of M2b, shipped — the machine, not its driver.**
M2b is the project plan's milestone for the lifecycle layer, and
"slice B" is this branch's share of it. All four slice B behaviours
(entries 5–8 of the plan's ledger) are in the tree on
`feature/m2b-state-machine`, stacked on slice A. The module is pure:
no daemon, no event loop, no I/O. It has **no caller yet**: the
`LifecycleManager` that will drive it arrives in slice D, and
nothing in the shipped tree calls `apply_transition` today. The
trigger column of the transition table below records what the table
*accepts*, not what currently fires.

The design is in
[`plans/m2b-lifecycle-manager.md`](../plans/m2b-lifecycle-manager.md):
[§1.1](../plans/m2b-lifecycle-manager.md:130) for the state machine,
[§1.2](../plans/m2b-lifecycle-manager.md:184) for
`ModelRuntimeState`, [§3 slice B](../plans/m2b-lifecycle-manager.md:554)
for the behaviours, and [§6.10](../plans/m2b-lifecycle-manager.md:1285)
for the field arithmetic.

## `ToolState`: six states, one of which serves

A **tool state** answers one question about one tool: *can it serve
a request right now?* The six answers, in journey order, are:

```python
class ToolState(StrEnum):
    STOPPED = "stopped"
    STARTING = "starting"
    LOADING = "loading"
    READY = "ready"
    STOPPING = "stopping"
    FAILED = "failed"
```

- **`STOPPED`** — no container. Every tool begins life here, and it
  is the state the machine returns to after a stop.
- **`STARTING`** — a start has been requested; the container has not
  yet confirmed its health.
- **`LOADING`** — the container is up and answering its health
  check, but the model weights are still loading and it is serving
  nothing.
- **`READY`** — the only state that can serve traffic.
- **`STOPPING`** — a `stop` has been requested; the backend has not
  yet confirmed it.
- **`FAILED`** — the start, the readiness wait, or the container the
  tool was relying on failed; the reason is carried in
  [`ModelRuntimeState.last_error`](#modelruntimestate-seven-fields-no-invariants).

[`ToolState`](../src/tool_swap/lifecycle/states.py:35) is
deliberately a different enum from
[`ContainerState`](../src/tool_swap/backend/base.py:129), because
the two ask different questions:

| | `ContainerState` | `ToolState` |
|---|---|---|
| Members | 4: `created`, `running`, `exited`, `gone` | 6: `stopped`, `starting`, `loading`, `ready`, `stopping`, `failed` |
| Question | does a process exist | can this tool serve traffic |
| Serving member | none — `running` does not mean serving | `READY` only |

A container is `running` from the moment it is up — including the
whole `LOADING` stretch in which it is serving nothing — so "does a
process exist" and "can this tool serve traffic" have different
answers at exactly the moment a router most needs to tell them
apart. That is why a tool's state is not just its container's
state, and why they are two enums. Both carry an **exact-set pin**
([`test_states.py`](../tests/unit/lifecycle/test_states.py),
[`test_container_handle_state_status.py`](../tests/unit/backend/test_container_handle_state_status.py)),
so a member added to the wrong enum fails a test: the six-member set
is closed, and the value strings are **disjoint** between the two
enums, so a readiness concept can never be smuggled into the backend
seam. `ToolState` is a `StrEnum` so members compare equal to the
bare strings used in CLI output and persisted state.

`STARTING` and `LOADING` are distinct because cold start is
dominated by weight loading, not container start —
[`plan/01`](../plan/01_ARCHITECTURE.md:209)
§4 keeps the `/health` versus `/ready` split and names it in the
machine.

## The transition table: ten edges out of thirty-six

The table is data, not a chain of branches
([`_LEGAL_TRANSITIONS`](../src/tool_swap/lifecycle/states.py:75)),
transcribed from [plan §1.1](../plans/m2b-lifecycle-manager.md:130):

| From | To | Trigger |
|---|---|---|
| `STOPPED` | `STARTING` | `ensure_ready` on a stopped tool |
| `STARTING` | `LOADING` | the health probe answers true |
| `STARTING` | `FAILED` | backend `start` raised, or `start_timeout` elapsed |
| `LOADING` | `READY` | the ready probe answers true |
| `LOADING` | `FAILED` | `ready_timeout` elapsed |
| `READY` | `STOPPING` | `stop` requested |
| `READY` | `FAILED` | the liveness sweep finds the container gone |
| `STOPPING` | `STOPPED` | the backend `stop` returned |
| `FAILED` | `STARTING` | `ensure_ready` retries |
| `FAILED` | `STOPPED` | manual reset |

```mermaid
stateDiagram-v2
    [*] --> STOPPED
    STOPPED --> STARTING: request arrives or manual start
    STARTING --> LOADING: container up, health OK
    LOADING --> READY: ready OK
    READY --> STOPPING: TTL expiry, eviction or manual stop
    STOPPING --> STOPPED
    STARTING --> FAILED: start error or timeout
    LOADING --> FAILED: readiness timeout or crash
    READY --> FAILED: container exited unexpectedly
    FAILED --> STARTING: retry
    FAILED --> STOPPED: manual reset
```

**The diagram above carries eleven arrows, but the machine has ten
edges** — and if you count the arrows, you will be wrong.
`[*] --> STOPPED` is mermaid's **initial pseudo-state marker**, not a
transition: it says a tool begins life `STOPPED`, which is an initial
condition rather than something the transition function can perform.
The plan carried the miscount until behaviour 7's red step counted
the table (commit `4d4c524` corrected six occurrences of "eleven").

The count is load-bearing because behaviour 7's test is arithmetic
and **exhaustive over all 36 ordered pairs**
([`test_transition_table.py`](../tests/unit/lifecycle/test_transition_table.py)):
ten legal, twenty-six illegal. A table with a missing edge and a
table with a spurious one are both silently wrong under any sampled
test, so the pair space is derived with `itertools.product` rather
than hand-listed.

Two absences are decisions, not oversights:

- **Self-transitions are all six illegal.** `READY → READY` is the
  dangerous one: a re-ready must never silently reset a serving
  tool's timers.
- **`STARTING → STOPPED` is illegal, and
  [`plan/06` §8.5b](../plan/06_LIFECYCLE_TTL_AND_SCHEDULING.md:357)
  actually wants it.** That is the shared-node `vram_unavailable`
  path — a neighbour took the VRAM, so the start must return to
  `STOPPED` rather than `FAILED` — and it needs the failure
  classification M6 owns, so it is deferred there rather than
  half-built here.

**No edge reaches `READY` without a probe answer.** The single edge
into `READY` is `LOADING → READY`, triggered by the ready probe.
Reconciliation (behaviour 23, slice F) therefore adopts a surviving
container by walking `STOPPED → STARTING → LOADING → READY` rather
than assigning `READY` directly: an adoption path that could write
`READY` without a probe answer would be a second, untested way to
reach the only state that serves traffic.

## `ModelRuntimeState`: seven fields, no invariants

```python
@dataclass
class ModelRuntimeState:
    tool: str
    state: ToolState
    handle: ContainerHandle | None
    last_used: float
    became_ready_at: float | None
    inflight: int
    last_error: str | None
```

[`ModelRuntimeState`](../src/tool_swap/lifecycle/states.py:53) holds
the per-tool runtime facts the transitions read. The seven fields are
**not a subset** of the
[full sketch in `plan/06` §9](../plan/06_LIFECYCLE_TTL_AND_SCHEDULING.md:396)
(12 fields); the relationship is:

- **five kept** — `name` renamed to `tool`, `state` retyped from
  `ModelState` to `ToolState`, plus `last_used`, `became_ready_at`
  and `inflight`;
- **seven deferred to M6** with the features that read them —
  `group`, `queued`, `keep_warm`, `ttl`, `evict_cost`, `vram_gb`,
  `consecutive_failures`;
- **two added that the sketch never had** — `handle`, because
  something must hold the `ContainerHandle` the backend returns, and
  `last_error`, because `FAILED` carries a reason. Five kept plus two
  added is the seven shipped ([plan §6.10](../plans/m2b-lifecycle-manager.md:1285)).

The deferral is pinned in **both directions**
([`test_model_runtime_state.py`](../tests/unit/lifecycle/test_model_runtime_state.py)):
the exact seven-field set fails on an extra field, and a named set of
the seven M6 fields fails on an early one — so the omission stays
visible rather than forgotten, and adding a deferred field later is
a behaviour with a test, not a quiet edit. A field no behaviour reads
is a field whose meaning is guessed.

Two properties depart from convention and are pinned for that reason:

- **It is mutable**, where every M2a data type is frozen
  (`MountSpec`, `ContainerSpec`, `ContainerHandle`, `ContainerStatus`
  are all `frozen=True, slots=True`). Slice D's manager updates the
  state **in place** on every request completion; freezing it would
  mean reallocating on each completion. A named test mutates a field
  and would fail under a frozen refactor.
- **`last_error` holds the taxonomy member's `message`, not
  `str(err)`** — [`BackendError.__str__`](../src/tool_swap/backend/errors.py:61)
  appends the remedy, and the remedy belongs to `/status`, not to the
  `FAILED` reason (M2a plan §6 item 6: "M2b formats it, it does not
  invent it"). A test asserts `last_error != str(err)` for a real
  taxonomy member.

**It enforces no invariants.** There is no `__post_init__`: a
`STOPPED` state carrying a non-`None` handle is stored without
complaint. The no-container-no-handle invariant belongs to the
transitions, and a constructor check would have been
half-enforcement the manager could immediately break by mutating the
same object — worse than no check, because the next reader trusts it.
The plan originally claimed the rejection; commit `865f459` removed
the claim, and the shipped test pins the actual behaviour — that
construction **stores what it is given** — under a name that says so.

## Moving a state: `apply_transition`

[`apply_transition(state, to_state, *, reason)`](../src/tool_swap/lifecycle/states.py:104)
is the single entry point that moves a holder. The from-state is read
**from** `state.state`, so the pair can never be inconsistent with
the holder; a legal pair updates the holder in place and returns the
new state, leaving the fields the manager owns (`handle`, timestamps,
`inflight`, `last_error`) untouched.

A pair outside the table raises
[`IllegalTransitionError`](../src/tool_swap/lifecycle/states.py:96),
which names **both** states and leaves the holder exactly where it
was. It subclasses `ValueError` rather than an operational error: the
fault is the pair the caller supplied, not a failure of the process —
raising is the loud default, because a silently ignored transition
would leave a tool in a state its caller does not expect.
[`is_legal_transition`](../src/tool_swap/lifecycle/states.py:91) is
the pure predicate over the same data, for callers that need to ask
without moving.

## Logging: validate first, log second

Every **applied** transition logs exactly one `INFO` record on the
module logger `tool_swap.lifecycle.states`, carrying `tool`,
`from_state`, `to_state` and `reason` as structured fields via
`extra=` — the tests read them off the `LogRecord` attributes, never
out of the formatted message, so a wording change cannot mask a
missing or swapped value.

A **refused** transition logs nothing. That is the sharpest contract
in the slice: logging before validating would leave a record for a
state change that never happened, and a log reader would believe the
tool had moved. The guard was not taken on trust — moving the log
call above the legality check turns **all 37 cases** in
[`test_transition_logging.py`](../tests/unit/lifecycle/test_transition_logging.py)
red, including the 26 that assert a refused transition leaves no
record.

The log call is **best-effort**: it is wrapped in
`suppress(Exception)`, so a broken handler cannot raise out of
`apply_transition` and cannot undo the state change that has already
been made. The order is validate, mutate, log — and only the first
step can refuse.

## What this page does not claim

- **There is no `LifecycleManager`.** Nothing calls
  `apply_transition`; the manager is slice D, and it is what will own
  coalescing, timeouts and the liveness sweep. This slice ships the
  machine, not its driver.
- **No probe exists.** That is slice C. The
  `STARTING → LOADING → READY` progression is *expressible* by the
  table, but nothing drives it yet — the trigger column above is what
  the table accepts, not what currently fires.
- **No container has been started.** Every test in the slice is pure:
  no daemon, no event loop; time is a `ManualClock` value, not a
  running clock.
- **`ModelRuntimeState` enforces no invariants** — see
  [the section above](#modelruntimestate-seven-fields-no-invariants).
  Consistency between `state` and `handle` is the manager's
  responsibility, exercised through the transitions.

## Where to go deeper

- [`docs/backend-seam.md`](backend-seam.md) — the `ContainerHandle`
  this machine holds, the `ContainerState` that answers a different
  question, and the error taxonomy whose `message` feeds
  `last_error`.
- [`docs/spec-builder.md`](spec-builder.md) — slice A of the same
  milestone: how the `ContainerSpec` the machine will eventually start
  is built.
- [`plans/m2b-lifecycle-manager.md`](../plans/m2b-lifecycle-manager.md)
  — [§1.1](../plans/m2b-lifecycle-manager.md:130) and
  [§1.2](../plans/m2b-lifecycle-manager.md:184) for the design,
  [§3 slice B](../plans/m2b-lifecycle-manager.md:554) for the
  behaviour ledger, and [§6.10](../plans/m2b-lifecycle-manager.md:1285)
  for the field arithmetic and its correction.
- [`plan/01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md) §4 — the
  state machine's source of transcription, and why `STARTING` and
  `LOADING` are distinct.

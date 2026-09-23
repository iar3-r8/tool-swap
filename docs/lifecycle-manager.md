# The lifecycle manager

The router does not serve a tool until that tool is ready, and a
stopped tool takes a while to become ready: starting its container
is one delay, loading the model weights inside it is a longer one.
The [`LifecycleManager`](../src/tool_swap/lifecycle/manager.py:154) is
the object that performs that work for one tool at a time. You hand it
the pieces it must use — the container backend, the readiness probe,
the clock, the `backend:` config block — and it can then be asked to
bring a registered tool to `READY` and return the handle of the
container that serves it. If ten requests arrive for the same
not-yet-started tool at once, it starts the container exactly once and
lets all ten awaiters share that one start.

**Where it sits:** the [spec builder
page](spec-builder.md) documents the layer that decides *what* a
tool's container should look like; the [backend seam
page](backend-seam.md) documents the layer that *starts* that
container; the [readiness probe
page](readiness-probe.md) documents the seam whose `health` and
`ready` answers move a tool through its states; the [tool state
machine page](tool-state-machine.md) documents the states and the
legal moves between them. This page documents the object that puts
them together: it builds the spec, asks the backend to start it, drives
the probe, and hands back the handle — or ends the tool `FAILED` with
a reason when it cannot.

## A cold start, end to end

The smallest drive of a manager is the one the test suite runs:

```python
from tool_swap.backend.fake_backend import FakeBackend
from tool_swap.config.defaults import BUILT_IN_DEFAULTS
from tool_swap.config.resolver import resolve_tool
from tool_swap.config.schema import BackendConfig
from tool_swap.lifecycle.manager import LifecycleManager
from tool_swap.proxy.probes import FakeProbe
from tool_swap.utils.clock import ManualClock

backend = FakeBackend()
probe = FakeProbe()               # unscripted: both phases answer true
clock = ManualClock(start=100.0)
resolved = resolve_tool("summarizer", inline={})

manager = LifecycleManager(
    backend,
    probe=probe,
    clock=clock,
    backend_config=BackendConfig(),
)
manager.register_tool(
    "summarizer", resolved, image="tool-swap/summarizer:1.0"
)
handle = asyncio.run(manager.ensure_ready("summarizer"))
```

After that call: the tool is `READY`, `handle` is the
`ContainerHandle` the backend produced, the backend's journal shows
exactly one `start` and no `stop`, and the state journal shows the
tool walking `STOPPED → STARTING → LOADING → READY`. The probe
answered true on its first call of each phase, so the readiness
wait cost no simulated time at all; a real tool's `LOADING` window
would advance the clock by whole `probe_interval`s.

## What this page stops at

The manager can bring a stopped or failed tool to `READY` and return
its handle. It cannot yet do the rest of a tool's life: it does not
stop a running tool, it does not count in-flight requests, it does not
drain, it does not notice a container that dies on its own, and it does
not reconcile containers left running by a previous router. Those
behaviours are not yet built, and the [state machine page's
transition table](tool-state-machine.md#the-transition-table-ten-edges-out-of-thirty-six)
shows exactly which of its ten edges no code in the tree fires yet.
Concretely:

- `ensure_ready` serves only `STOPPED`, `READY` and `FAILED` tools.
  Anything else — a tool already mid-start, mid-load or mid-stop —
  raises `ValueError` naming the state.
- A registered tool cannot be re-registered; a second
  `register_tool` for the same name raises `ValueError`, because
  re-registering would drop the state of a tool that may be serving.
- The backend's `is_running`, `inspect` and `logs` have no caller in
  the manager yet. The seam exposes them (the [backend seam
  page](backend-seam.md) documents the contract), and the liveness
  sweep that would read them is not built.
- There is no real probe: the manager polls the
  [`Probe`](../src/tool_swap/proxy/probes.py:23) seam, and only the
  scripted [`FakeProbe`](../src/tool_swap/proxy/probes.py:55)
  implements it so far — see the [readiness probe
  page](readiness-probe.md).

The design and its reasoning are in
[`plans/m2b-lifecycle-manager.md`](../plans/m2b-lifecycle-manager.md)
— [§1.4](../plans/m2b-lifecycle-manager.md:409) for the coalescing
mechanism and what `run_in_executor` can and cannot do, and
the `ensure_ready` entries of the
behaviour ledger ([§3](../plans/m2b-lifecycle-manager.md:863)) for
the contract.

## The public surface

Four members, nothing else:

```python
class LifecycleManager:
    def __init__(
        self,
        backend: ContainerBackend,
        *,
        probe: Probe,
        clock: Clock,
        backend_config: BackendConfig,
        start_timeout: float = 120.0,
        ready_timeout: float = 600.0,
        probe_interval: float = 1.0,
        stop_timeout: float = 30.0,
    ) -> None: ...

    def register_tool(self, tool: str, resolved: ResolvedTool, *, image: str) -> None: ...
    def state_of(self, tool: str) -> ModelRuntimeState: ...
    async def ensure_ready(self, tool: str) -> ContainerHandle: ...
```

- **Construction stores, nothing more.** The backend, probe, clock and
  `backend_config` are held by identity — the manager uses exactly the
  objects it was given, so a `FakeBackend` keeps it fully usable in an
  environment where the docker SDK is not importable, and a caller that
  does not use the config layer can still construct it. The four
  timeout values are held by value as plain scalars, defaulting from
  [`BUILT_IN_DEFAULTS`](../src/tool_swap/config/defaults.py:20) — read
  from that named source at module level, so the signature cannot drift
  from the config layer. A `None` backend or probe is refused with
  `TypeError` at construction rather than at the first call.
  Construction performs no backend work and moves no clock.
- **`register_tool`** is the seam that feeds tools in: the manager
  needs the tool's [`ResolvedTool`](../src/tool_swap/config/resolver.py:82)
  and an image reference before it can build a
  [`ContainerSpec`](../src/tool_swap/backend/base.py:49), and nothing
  else supplies them. It records them under a fresh `STOPPED`
  [`ModelRuntimeState`](../src/tool_swap/lifecycle/states.py:53) — no
  container, `handle` `None`. Two refusals: the name argument must
  match `resolved.name`, and a name that is already registered raises,
  as noted above.
- **`state_of`** returns the tool's runtime state holder, for
  read-back; an unregistered name raises `KeyError`.
- **`ensure_ready`** is the cold start. The rest of this page is what
  it does.

## `ensure_ready`: one start, shared by every awaiter

A `STOPPED` tool walks `STOPPED → STARTING → LOADING → READY`. The
manager moves it to `STARTING`, starts its container once, then
delegates the probe progression to
[`drive_readiness`](../src/tool_swap/lifecycle/manager.py:93), which
the [state machine
page](tool-state-machine.md#the-first-driver-drive_readiness)
documents: `STARTING → LOADING` when `health` answers true,
`LOADING → READY` when `ready` answers, each move through
`apply_transition` so the table's legality check and its `INFO` log are
inherited. On the way to the end, `became_ready_at` is stamped with
`clock.now()`. `last_used` is never touched by `ensure_ready` — that
field belongs to request completion, not to readiness.

A tool already `READY` returns the handle it holds: nothing starts,
nothing is re-stamped. A `FAILED` tool is retried through the legal
`FAILED → STARTING` edge, so a refused start never strands the tool —
the next `ensure_ready` is the retry, and the transition table's
`FAILED → STOPPED` manual-reset edge stays available beside it.

### Coalescing: the lock decides, the task runs

Ten concurrent callers of `ensure_ready("summarizer")` must produce
exactly one container start, and the mechanism has three parts, each
pinned by the journal's "exactly one `start`" count:

1. **A per-tool lock, held only while deciding.** Holding it across
   the cold start would serialise every caller behind the start —
   nine followers waiting behind a 120-second operation instead of
   sharing it. The lock exists so that exactly one caller makes the
   decision to start, and the decision and the holder's move to
   `STARTING` happen under the same lock: a `STARTING` mutation made
   before any await would let a caller arriving in between miss the
   pending task and race a second start.
2. **A per-tool pending task.** The caller who decides to start creates
   the cold-start task and stores it; every later caller finds the
   stored task under the lock and awaits the same one.
3. **Every awaiter behind `asyncio.shield`.** See
   [Cancellation](#cancellation-a-walker-leaving-changes-nothing)
   below for why the await, not the task, is what a cancellation
   reaches.

### A refused start: `FAILED` with the reason, nothing resident

When `backend.start` raises a member of the backend's
[error taxonomy](backend-seam.md), the cold start ends the tool
`FAILED`. Two details are load-bearing:

- **The recorded reason is the taxonomy member's `message`,
  verbatim.** [`BackendError.__str__`](../src/tool_swap/backend/errors.py:61)
  appends the remedy, and the remedy belongs in `/status`, not in the
  `FAILED` reason an operator sorts by. The state machine page
  documents the rule for the holder's field; the manager is the first
  code that fills it.
- **No handle is stored.** The refusal created no container, so the
  holder's `handle` stays `None`, and the error is re-raised — the
  caller's error path stays on the taxonomy member, with its remedy.

The failure is recorded once, on the cold-start task, not once per
waiter: the transition table has no `FAILED → FAILED` self-edge, so ten
waiters each applying it would raise nine `IllegalTransitionError`s on
top of the real failure.

### A readiness timeout: the container is stopped before the tool fails

The two deadlines are independent — `start_timeout` covers
container-up-to-health, `ready_timeout` covers health-to-ready and
starts when `health` answered — and the [state machine
page](tool-state-machine.md#two-independent-deadlines) documents the
arithmetic. When one elapses, `drive_readiness` raises and the cold
start does three things before the error reaches the callers:

1. **Stops the container.** A start refusal leaves nothing resident,
   but a timeout leaves a running container that is serving nothing;
   stopping it is part of failing the tool, so a failed cold start
   never leaves a container occupying a slot. The stop runs on the
   loop's default executor with `stop_timeout` as the deadline — see
   [Backend calls run in an executor](#backend-calls-run-in-an-executor).
2. **Ends the tool `FAILED`**, recording the timeout's own rendering as
   the reason: it names which deadline ran and the simulated seconds it
   ran, which is what an operator needs to tell a hung start from a
   hung ready.
3. **Clears the handle.** The tool no longer claims a running
   container.

A stop that itself raises is logged and not allowed to replace the
timeout — the callers are owed the timeout — but the tool still ends
`FAILED` and the handle is still cleared.

### Cancellation: a walker leaving changes nothing

Every awaiter reaches the cold-start task through
[`asyncio.shield`](https://docs.python.org/3/library/asyncio.html#asyncio.shield),
so a caller cancelled while awaiting raises `CancelledError` and
affects nobody else. The shield matters in the opposite direction too,
and it rests on a verified property rather than an assumption:
`shield`'s own contract is that cancelling the awaiter does not cancel
the inner task. So the cold start runs to completion and records its
outcome — `READY` with a handle, or `FAILED` with a reason — even if
every waiter has gone. That is the guarantee that keeps a started
container from ever becoming an orphan the router does not know about:
one failed start is one shared failure, and one finished start is one
recorded container.

### Backend calls run in an executor

The [backend seam](backend-seam.md#the-protocol) is synchronous, and a
round-trip to the container daemon can block. The manager therefore
runs `backend.start` and the timeout path's `backend.stop` on the
event loop's default executor:

```python
handle = await asyncio.get_running_loop().run_in_executor(
    None, self.backend.start, spec
)
```

Without the hop, one tool's slow container start would stall the
event loop — and with it every other tool's cold start, readiness
poll and request handling — for the whole duration of the daemon
round-trip. The seam itself stays synchronous; making it async would
hide the off-load inside the driver, and the seam's page records that
the driver is the async layer.

One limit is worth stating because it bounds the cancellation
contract: **cancelling a caller does not stop a backend call that is
already in flight.** `run_in_executor` cannot recall a thread once the
call has started, so an in-flight `backend.start` always runs to
completion — which is exactly why the cold-start task must be allowed
to finish and record its outcome even when every waiter has gone.

## The import boundary

The manager must be usable where the docker SDK cannot be imported,
because the backend is an injection and a `FakeBackend` satisfies the
protocol. That is enforced, not hoped for: the sixth contract in
[`.importlinter`](../.importlinter:46) forbids
`tool_swap.lifecycle` and `tool_swap.proxy` from importing
`tool_swap.backend.docker_backend`, and `lint-imports` reports
**6 kept, 0 broken**. The [backend seam
page](backend-seam.md#the-import-boundary) documents the SDK
containment contract that sits beside it; the two together mean the
lifecycle layer can only ever meet the backend through the
[`ContainerBackend`](../src/tool_swap/backend/base.py:171) protocol.

## Where to go deeper

- [`docs/tool-state-machine.md`](tool-state-machine.md) — the six
  states, the ten-edge table the manager moves the holder through,
  `ModelRuntimeState`'s fields, `apply_transition` and
  `drive_readiness`.
- [`docs/spec-builder.md`](spec-builder.md) — how the
  `ContainerSpec` the manager builds for its start is assembled from
  the registered tool's resolved config and the `backend:` block.
- [`docs/backend-seam.md`](backend-seam.md) — the protocol the manager
  calls, the error taxonomy whose `message` feeds the `FAILED` reason,
  and the import boundary that keeps the docker SDK out of this layer.
- [`docs/readiness-probe.md`](readiness-probe.md) — the `Probe` seam
  the manager polls, and the `FakeProbe` that stands in for the real
  probe.
- [`plans/m2b-lifecycle-manager.md`](../plans/m2b-lifecycle-manager.md)
  — [§1.4](../plans/m2b-lifecycle-manager.md:409) for the coalescing
  design and the `run_in_executor` limit, and the `ensure_ready`
  entries of the behaviour ledger
  ([§3](../plans/m2b-lifecycle-manager.md:863)) for the contract.

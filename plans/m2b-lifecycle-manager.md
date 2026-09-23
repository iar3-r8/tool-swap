# M2b — LifecycleManager, the readiness probe seam and reconciliation

Implementation plan for the lifecycle half of milestone M2, intake
[GitHub issue iar3-r8/tool-swap#3](https://github.com/iar3-r8/tool-swap/issues/3).

- **Branch:** `feature/m2b-lifecycle-manager` (already created from `main` at `ff2428f`).
  A *feature* branch is correct — this is new capability, not a correction to shipped
  behaviour. See [§2](#2-the-slice-plan) for why this branch carries slice A only.
- **Test command:** `make test` (runs `.venv/bin/python -m pytest`, whose `addopts`
  deselect the `docker`, `gpu` and `slow` markers — [`pyproject.toml`](../pyproject.toml:75)).
- **Ledger:** 26 numbered behaviours, one red/green cycle each, in six pull-request slices.
- **Predecessor:** M2a shipped the container backend seam across five pull requests
  (#9, #10, #11, #12, #13). Its plan is
  [`plans/m2a-container-backend-seam.md`](m2a-container-backend-seam.md); §6 of it lists
  what this milestone needs from the seam, and this plan is written so M2b is **additive
  to that seam rather than a refactor of it**.
- **Validation gate:** the 26-behaviour list, the section-8 scope and the no-new-package
  finding were confirmed by the user before this plan was written. See
  [§6.1](#61-what-the-user-confirmed).

---

## 0. What M2b delivers, and what it deliberately does not

M2b is the layer **above** the backend seam: the tool state machine, the coalesced
`ensure_ready`, the readiness probe seam, in-flight counting, drain-then-stop, and
reconciliation on boot. It adds five modules and changes none of M2a's:

| Module | Contents |
|---|---|
| `src/tool_swap/lifecycle/spec_builder.py` | `build_container_spec` — the config → `ContainerSpec` conversion M2a left unowned |
| `src/tool_swap/lifecycle/states.py` | `ToolState`, `ModelRuntimeState`, the transition table |
| `src/tool_swap/proxy/probes.py` | The `Probe` protocol and `FakeProbe` |
| `src/tool_swap/lifecycle/manager.py` | `LifecycleManager` |
| `src/tool_swap/lifecycle/reconcile.py` | Boot-time adopt-or-stop |

### 0.1 Explicitly out of scope

| Deferred to | What, and why |
|---|---|
| **M3** | The real HTTP probe. M2b ships the `Probe` protocol and `FakeProbe` only; no socket is opened and no HTTP client is declared ([D-B](#5-settled-decisions)). |
| **M3** | The queue-policy seam and shutdown ordering ([D-C](#5-settled-decisions)). Both concern *queued* requests, and nothing queues until M3's proxy exists. |
| **M6** | Groups, `max_resident`, `min_residency`, `evict_cost`, the TTL watchdog, eviction, `restart_backoff`, `consecutive_failures` and the `vram_unavailable` classification — [`plan/09_IMPLEMENTATION_PLAN.md`](../plan/09_IMPLEMENTATION_PLAN.md:228) places all of them in M6. Six of `plan/06` §8's nine scenarios need them; see [§6.2](#62-issue-3s-section-8-requirement-is-mostly-m6s). |
| **A separate follow-up issue** | The three `@pytest.mark.docker` daemon tests and the DinD harness (M2a §7 item 7, still unfiled). **M2b claims no daemon verification**: the `docker` marker stays registered and deselected, no test carries it, and `TSWAP_TEST_DOCKER_HOST` appears only in documentation. |
| **The config layer** | A `backend:` layer in the resolver ([§6.3](#63-the-backend-block-is-not-a-resolver-layer)), a `container_prefix` rule and a size-string rule (M2a §7 items 10–11). |
| **A separate task** | Retrofitting M2a's test files to the docstring and test-string rules of [§4](#4-discipline). |

**Every behaviour below is verifiable with no Docker daemon and no network**, by
construction: the backend is `FakeBackend`, the probe is `FakeProbe`, and time is
`ManualClock`.

---

## 0.2 Progress ledger — the durable loop state

Updated as each behaviour completes, so the loop survives a context reset. The branch for
slice A is **`feature/m2b-spec-builder`**, renamed from `feature/m2b-lifecycle-manager`
per [§2.2](#22-is-featurem2b-lifecycle-manager-the-right-name-for-slice-a) before anything
was pushed; the milestone name is kept for pull-request titles.

Baseline re-measured at `main` (`ff2428f`) rather than trusted: **1524 passed, 2 skipped**,
`make lint` clean with mypy strict over 38 source files, `lint-imports` 5 kept, 0 broken.

**Slice A** — `feature/m2b-spec-builder`:

| # | Behaviour | Red | Green | Suite at green |
|---|---|---|---|---|
| 1 | `build_container_spec` core assembly | `fc2772e` | `e73071b` | 1530 passed, 2 skipped |
| 2 | `ParsedMount` → `MountSpec` | `03b3b00` | `c979b2a` | 1546 passed, 2 skipped |
| 3 | Resource, env and port passthrough | `d6a2d99` | `325bb3d` | 1555 passed, 2 skipped |
| 4 | The builder's two guards | `ada2dea` | `7478dc9` | 1570 passed, 2 skipped |

**Slice B** — `feature/m2b-state-machine`, stacked on slice A's tip `af00e89`:

| # | Behaviour | Red | Green | Suite at green |
|---|---|---|---|---|
| 5 | `ToolState` — six members | `9d10ee2` | `b070cc2` | 1579 passed, 2 skipped |
| 6 | `ModelRuntimeState` — seven fields | `7ce868b` | `87a1cef` | 1586 passed, 2 skipped |
| 7 | The transition table | `a5a6dfe` | `d5e1079` | 1661 passed, 2 skipped |
| 8 | Transitions are logged | `1a6b4ff` | `ac5c39c` | 1698 passed, 2 skipped |

**Slice B is complete and shipped as
[#15](https://github.com/iar3-r8/tool-swap/pull/15)**, stacked on #14 and based on
`feature/m2b-spec-builder` rather than `main`, so its diff shows only behaviours 5–8.
Head `2ed0859`, documentation commit `2ed0859` preceding the pull request.

**#15 ran no CI until it was retargeted to `main`**, which happened when #14 merged. The
workflow triggers on `branches: [main]` only, so the absence of a check was configuration
rather than failure — and retargeting is what makes CI run, so it should happen before
approval rather than after.

**Slice C branches from `main` at `b3fafef`**, superseding this section's earlier
instruction to branch from `2ed0859`. That instruction was correct while #15 was open and
slice C would otherwise have been absorbed into it; both slices have since merged, so
`main` now carries behaviours 1–8 and is the right base. Because slice C branches from
`main` rather than from another branch, **its pull request runs CI normally** and needs no
retargeting.

**Verify that by tree, not by ancestry.** The GitHub API reports `mergeable_state:
unknown` for #14 and #15, and `git merge-base --is-ancestor feature/m2b-state-machine
origin/main` answers *no*, because a squash merge rewrites the commits and leaves no
ancestry link. Both readings are misleading. The tree is what matters:
`git diff origin/main feature/m2b-state-machine` is empty but for later commits, which is
what proves the work landed. M2a set the identical trap and it cost time to unpick.

**Slice C** — `feature/m2b-probe-seam`, branched from `main` at `b3fafef`:

| # | Behaviour | Red | Green | Suite at green |
|---|---|---|---|---|
| 9 | `Probe` protocol and `ProbeTarget` | `1de9832`, repaired by `dd10933` | `e057cdd` | 1713 passed, 2 skipped |
| 10 | `FakeProbe` — three scripts, call journal | `a22c323` | `1ca3684` | 1737 passed, 2 skipped |
| 11 | `STARTING → LOADING → READY` | `9c23f1b` | `907a1fb` | 1744 passed, 2 skipped |

Baseline re-measured at `b3fafef` before branching: **1698 passed, 2 skipped**, `make lint`
clean with mypy strict over 40 source files, `lint-imports` 5 kept, 0 broken.

**Slice C is complete and merged as
[#17](https://github.com/iar3-r8/tool-swap/pull/17)**, squashed onto `main` as `605c4b0`.
Head was `90d51d4`, ten commits, documentation commit `90d51d4` preceding the pull request.
At the tip: 1744 passed, 2 skipped, mypy strict over 42 source files, `lint-imports` 5
kept, 0 broken. Because it branched from `main`, CI ran without retargeting.

**Slice D** — `feature/m2b-ensure-ready`, branched from `main` at `605c4b0`:

Baseline re-measured at `605c4b0` before branching rather than trusted: **1744 passed, 2
skipped**, `make lint` clean with mypy strict over 42 source files, `lint-imports` 5 kept,
0 broken. Slice C's merge was confirmed **by tree** — `git diff origin/main
feature/m2b-probe-seam` is empty while `git merge-base --is-ancestor` still answers *no*,
the squash-merge trap this section already warns about.

| # | Behaviour | Red | Green | Suite at green |
|---|---|---|---|---|
| 12 | Construction, injection, sixth contract | — | — | — |
| 13 | `ensure_ready` cold-start happy path | — | — | — |
| 14 | Ten concurrent `ensure_ready`, one start | — | — | — |
| 15 | Start failure yields `FAILED` with reason | — | — | — |
| 16 | Readiness timeout yields `FAILED` | — | — | — |
| 17 | Cancellation neither kills nor orphans | — | — | — |
| 18 | Backend calls run in an executor | — | — | — |

The push used the `.roo/mcp.json` token, as §0.2 of the M2a plan records — but **the
one-shot `http.extraheader` did not work here** and the method note should be corrected
before slice D repeats it. VS Code's credential helper is consulted first and fails with
"terminal prompts disabled" before the header is offered, and adding
`-c credential.helper=` to disable it does not help, because the header alone leaves git
with no username to send. What worked was putting the token in the push URL for that one
invocation, `https://x-access-token:${TOKEN}@github.com/...`, which writes nothing to
`.git/config` and leaves the `origin` remote unchanged — both verified after the push.

Behaviour 9 needed **two** red commits, and the reason is the most useful thing this slice
learned. Its no-HTTP guard passed the bare `probes_source` *function* to `ast.parse`
instead of calling it, so the scan raised `TypeError: compile() arg 1 must be a string`
and never walked a tree. At the red step the subject-exists gate failed first and hid it,
so the guard was **neither honestly red nor honestly green — it was erroring in both
states**. Planting `import requests` would have produced the same `TypeError` as a clean
tree, so the injection discipline alone would *not* have caught it. What caught it was the
coder refusing to edit a test to reach green and reporting it instead. The repair is
`dd10933`; the helper's return type went from `tuple[Path, Any, Any]` to named `Callable`
aliases, so the same mistake now fails type checking rather than at runtime.

Guards were then verified against the real file rather than only against decoys:
`import requests` at line 14 and `from httpx import AsyncClient` at line 16 each fail
naming their line, and `probes.py` is byte-identical after revert. Behaviour 11's green
was checked by mutation for the same reason — making the ready window share the start
clock turns `test_ready_timeout` red at the 720.0 the plan warns of, and replacing the
`LOADING` transition with a direct field assignment turns three tests red.

Behaviour 11's arithmetic claim was checked against source before delegating, as §0.2's
precedent requires: `start_timeout` 120, `ready_timeout` 600 and `probe_interval` 1.0 are
all real at [`defaults.py`](../src/tool_swap/config/defaults.py:42). The claim held.

Two open decisions were reported rather than absorbed, both left as the plan has them: a
probe that **raises** stays unmodelled, since a transport failure is M3's real probe's
concern; and a flapping true-then-false script was considered and not added. One API the
plan left open was decided — behaviour 11 lives as a module-level `drive_readiness` in
`manager.py`, because `LifecycleManager` is behaviour 12's and slice C must ship without
it; the class can delegate to the coroutine when slice D builds it.

Two tests in slice B assert an *absence* and therefore pass before their feature exists,
which would normally make them worthless as red steps. Both were checked by injecting the
mistake they target rather than trusting the green result: moving the log call above the
legality check turns all 37 cases in
[`test_transition_logging.py`](../tests/unit/lifecycle/test_transition_logging.py) red,
including the 26 that assert a refused transition leaves no record. The same technique
verified slice A's two guards.

Two plan errors were found by subtasks checking this document against the source rather
than trusting it, and both are corrected above: §6.10's field arithmetic (`2a832e9`), and
behaviour 6's claim that the dataclass rejects an inconsistent handle, which contradicted
its own error-behaviour line.

**Slice A is complete and shipped as
[#14](https://github.com/iar3-r8/tool-swap/pull/14)**, open against `main`. Head
`6d17990`, documentation commit `6d17990` preceding the pull request as behaviour 26
requires. Every behaviour has both a red and a green commit, and the suite is green at
the branch tip.

The push used the `.roo/mcp.json` token through a one-shot `http.extraheader`, for the
reason M2a §0.2 records: `GITHUB_TOKEN` is set-but-empty in this dev container, git's
only credential helper is VS Code's interactive one, terminal prompts are disabled and
there is no `gh` CLI. The token is written into no config file.

**Slice B branches from slice A's tip, not from `main`.** Pull request #14's head *is*
`feature/m2b-spec-builder`, so continuing to commit there would absorb slice B into the
open pull request and destroy the split — the mistake M2a's §0.1.2 nearly made. Slice B
is stacked, and a stacked pull request runs no CI until it is retargeted to `main` on its
parent's merge ([§2.1](#21-branch-and-stacking-mechanics)).

The guards were not taken on trust. A green guard and a blind guard are
indistinguishable from the test output, so both were driven against a violation
**injected into the real source tree** and confirmed to catch it — a backend-named key
read at line 35, and a second `parse_mount` with its split at lines 236 and 238 — before
the tree was restored. The decoys prove the detectors discriminate; the injection proves
the walk reaches the file that matters.

Plan commit: `76de92e`. Behaviour 1's green step corrected this plan's `container_port`
claim (see behaviour 1's outputs); no test was weakened to reach green, and no red step
has been amended into its green.

---

## 1. Design

### 1.1 The tool state machine — six states, ten edges

Transcribed from [`plan/01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md:183) §4. This is
**not** `ContainerState`, which has four members and answers only "does a process
exist" ([`base.py`](../src/tool_swap/backend/base.py:129)). The two are separate on
purpose, and M2a pinned its four-member set so they cannot blur.

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

**Ten edges, and the count matters** because behaviour 7's test is arithmetic: ten legal
pairs and twenty-six illegal ones out of thirty-six. This section said "eleven" until
behaviour 7's red step was delegated, when the table was counted and found to hold ten
rows. The miscount came from the diagram above, which carries eleven arrows — but
`[*] --> STOPPED` is mermaid's **initial pseudo-state marker**, not a transition: it says
a tool begins life `STOPPED`, which is an initial condition rather than something the
transition function can be asked to perform. Counting it would have made the test expect
eleven legal pairs and twenty-five illegal, and the missing pair would have been
whichever one the implementer happened to add.

Everything else is illegal and raises. **There is no edge into `READY` that bypasses the
probe**, which is why reconciliation adopts a container by walking
`STOPPED → STARTING → LOADING → READY` rather than assigning `READY` directly
(behaviour 23). An adoption path that could write `READY` without a probe answer would be
a second, untested way to reach the only state that serves traffic.

`STARTING → STOPPED` is deliberately absent, though `plan/06` §8.5b wants it: that is the
shared-node `vram_unavailable` path, and it needs the failure classification M6 owns.

### 1.2 `ModelRuntimeState` — the M2b subset

[`plan/06`](../plan/06_LIFECYCLE_TTL_AND_SCHEDULING.md:396) §9 sketches the full
dataclass. M2b ships **only the fields its own behaviours read**, because a field no
behaviour exercises is a field whose meaning is guessed:

```python
@dataclass
class ModelRuntimeState:
    tool: str
    state: ToolState
    handle: ContainerHandle | None       # None unless a container exists
    last_used: float                     # clock.now() on request completion
    became_ready_at: float | None
    inflight: int
    last_error: str | None               # the taxonomy member's message, verbatim
```

Deferred to M6 with their features: `group`, `queued`, `keep_warm`, `ttl`, `evict_cost`,
`vram_gb`, `consecutive_failures`. §9's `request_slot` and `find_expired` are M6's too —
M2b adds no scheduler.

`last_error` holds the backend error's `message` **verbatim**, per M2a §6 item 6: "M2b
formats it, it does not invent it". [`errors.py`](../src/tool_swap/backend/errors.py:11)
was written for exactly this consumer.

### 1.3 How async waiting composes with `ManualClock` — the load-bearing design answer

This is the question [D-A](#5-settled-decisions) flagged as genuine, and the answer is
**not** to design a new clock. [`utils/clock.py`](../src/tool_swap/utils/clock.py:78)
already solves it, and the solution constrains the manager's shape in two ways that must
be stated before any test is written.

**Rule 1 — all waiting goes through `Clock.sleep`, never `asyncio.sleep` and never
`asyncio.wait_for`.** [`ManualClock.sleep`](../src/tool_swap/utils/clock.py:130) advances
the simulated scalar and then yields with `await asyncio.sleep(0)`, so a poll loop written
as `await self._clock.sleep(probe_interval)` is simultaneously async and fake-clock-driven,
and `plan/06` §9's "all of §8's scenarios are sub-millisecond" holds. A bare
`asyncio.sleep(1.0)` would cost a real second; `asyncio.wait_for` is worse, because its
deadline is the **event loop's** clock, which `ManualClock` does not control — a
`wait_for(timeout=600)` under a manual clock waits ten real minutes. **Timeouts are
therefore expressed as a deadline compared against `clock.now()` inside the poll loop**,
never as a `wait_for` wrapper.

**Rule 2 — exactly one coroutine may sleep per cold start.** A shipped test pins that
concurrent `ManualClock` sleeps **sum** rather than overlap
([`test_clock.py`](../tests/unit/test_clock.py:547): two tasks sleeping 10 and 20 leave
`now() == 30`), because simulated time is one shared scalar. Ten waiters each polling
would advance time tenfold and trip their own `ready_timeout` — a test failure caused
entirely by the test's shape. The coalescing design in §1.4 makes the **leader** the only
sleeper and gives the nine followers nothing to await but a future, which is what makes
behaviour 14 honest rather than lucky.

### 1.4 `ensure_ready` — coalescing, and what `run_in_executor` means for it

```python
class LifecycleManager:
    def __init__(
        self,
        backend: ContainerBackend,
        *,
        probe: Probe,
        clock: Clock,
        backend_config: BackendConfig,
        timeouts: Timeouts,
    ) -> None: ...

    async def ensure_ready(self, tool: str) -> ContainerHandle: ...
    async def stop(self, tool: str, *, reason: str) -> None: ...
    async def sweep_liveness(self) -> None: ...
    def state_of(self, tool: str) -> ModelRuntimeState: ...
    def begin_request(self, tool: str) -> None: ...
    def end_request(self, tool: str) -> None: ...
```

The coalescing mechanism, and why each part is there:

1. **One `asyncio.Lock` per tool**, held only while *deciding*, never while starting. A
   lock held across the cold start would serialise the nine followers behind a 120-second
   operation and make `plan/06` §8.7's group isolation impossible later.
2. **A per-tool pending future.** The first caller to find the tool `STOPPED` creates the
   cold-start task, stores it, releases the lock and awaits it. Every later caller finds
   the stored task under the lock and awaits the same one. So exactly one task runs,
   which is what "exactly one start" means.
3. **Followers await `asyncio.shield(task)`.** This is the cancellation answer, and it
   rests on a verified fact rather than a remembered one. `shield`'s own docstring
   ([`/usr/lib/python3.11/asyncio/tasks.py:841`](file:///usr/lib/python3.11/asyncio/tasks.py))
   states that if the coroutine containing it is cancelled, the inner task is not — the
   caller still raises `CancelledError`, but the start continues for everyone else.
   Without the shield, the first caller to walk away would cancel a container start that
   nine other callers are waiting on.
4. **Backend calls go through `loop.run_in_executor`**, because the seam is synchronous
   and must stay so — M2a §7 item 4 makes changing it "a change to behaviour 8 and a
   re-review, not a quiet adaptation". A direct `backend.start(spec)` on the loop would
   stall every other tool's cold start for the duration of a Docker round-trip.

**What `run_in_executor` cannot do, verified from source and stated because it bounds the
contract:** cancelling the awaitable does **not** stop the thread.
`concurrent.futures.Future.cancel` returns `False` outright once the state is `RUNNING`
([`/usr/lib/python3.11/concurrent/futures/_base.py:364`](file:///usr/lib/python3.11/concurrent/futures/_base.py)),
and `asyncio`'s bridge only *attempts* `source.cancel()` when the destination is cancelled
([`_chain_future`](file:///usr/lib/python3.11/asyncio/futures.py) at `futures.py:387`).
So an in-flight `backend.start` always runs to completion. **Consequence for the design:**
the cold-start task must be allowed to finish and record its outcome even when every
waiter has gone, or a started container becomes an orphan the router does not know about.
Behaviour 17 pins exactly that.

### 1.5 The probe seam — a protocol, `FakeProbe`, and no client

```python
@runtime_checkable
class Probe(Protocol):
    async def health(self, target: ProbeTarget) -> bool: ...
    async def ready(self, target: ProbeTarget) -> bool: ...


@dataclass(frozen=True, slots=True)
class ProbeTarget:
    tool: str
    host: str          # the container name — tools are reached by name (D21)
    port: int          # spec.container_port
    health_path: str   # resolved from config, default "/health"
    ready_path: str    # resolved from config, default "/ready"
```

Four decisions, each so M3's real probe is an implementation rather than a redesign:

- **Two methods, not one.** `plan/01` §4 explains why `STARTING` and `LOADING` are
  distinct: cold start is dominated by weight loading, and "90 seconds in LOADING" is a
  different problem from "90 seconds in STARTING". One `is_ready` method would collapse
  the distinction the state machine exists to express.
- **Async.** This is a new seam of ours, not M2a's synchronous one, and M3's probe will be
  async HTTP. Declaring it async now means no executor hop and no later signature change.
  It does **not** contradict D-A: the *container backend* seam stays synchronous.
- **`bool`, not a status object.** The manager decides what a false answer means — it owns
  the deadlines. A probe returning a state would be a second state machine.
- **`ProbeTarget` carries the address**, so the probe needs no config access and no
  container knowledge. `host` is the container name because tools are addressed by name on
  the shared network (**D21**, [`plan/01`](../plan/01_ARCHITECTURE.md:365) §7).

`FakeProbe` is scripted per tool and per phase: answer true immediately, answer true after
N calls (a real `LOADING` window), or **never answer true** — which is the "never ready"
failure mode M2a deliberately excluded from `FakeBackend` because readiness is the probe's
concern (M2a §4.4). It lands here, where it belongs.

**No HTTP client is declared.** The repository's dependencies are `typer`, `pydantic`,
`pyyaml`, `python-dotenv`, `jsonschema` and `docker`
([`pyproject.toml`](../pyproject.toml:24)); `requests` exists only transitively under
`docker`, and importing it directly would be an undeclared dependency — the exact defect
pull request #9 existed to fix.

### 1.6 Reconciliation — the adopt-or-stop rule

From [`plan/01`](../plan/01_ARCHITECTURE.md:365) §7. Input is
`backend.list_managed()`, which returns stopped containers too and recovers `tool` from
the `{namespace}.model` label rather than parsing the name (M2a §6 item 5).

| Container found | In the config? | Decision |
|---|---|---|
| running | yes | **adopt**: walk the probe progression; `READY` if it answers, else `FAILED` |
| running | no | **orphan**: apply the `orphans` policy — `stop` (default), `adopt` or `ignore` |
| exited | yes | leave it; the tool stays `STOPPED`. Nothing starts a container on boot |
| exited | no | orphan by the same policy; stopping an already-exited container is a no-op |

Three properties the behaviours pin: it is **safe to run repeatedly** (a second pass over
an already-adopted tool changes nothing and starts nothing); it **never stops a container
that is serving** (`inflight > 0` is immune, as it is for every stop path); and **there is
no port state to reconcile** (**D21**) — a restarted router rediscovers a container by
label and name, which is the structural fix for the originating system's `BASE_PORT + i`
flaw.

### 1.7 Drain-then-stop

From [`plan/01`](../plan/01_ARCHITECTURE.md:308) §5.1 rule 4 and
[`plan/06`](../plan/06_LIFECYCLE_TTL_AND_SCHEDULING.md:42) §2.1: stop accepting new work
for the tool, wait up to `drain_timeout` for in-flight requests, then stop the container
with `stop_timeout` as the backend's kill deadline. The `SIGTERM → SIGKILL` escalation
itself is **the runtime's**, not ours — `backend.stop(handle, timeout_s=...)` already
carries it, and M2a's behaviour 22 passes the timeout unconditionally so a zero is not
silently dropped. M2b therefore asserts the *decision* to stop and the timeout it passes,
never the signals; signal behaviour is deferred daemon test 2 and is **not claimed here**.

---

## 2. The slice plan

M2a needed five pull requests and cut its splits three times, because a large pull request
is not reviewable. M2b is at least as big, so the cut is decided **now**. Each boundary is
justified by what makes it one coherent review.

| Slice | Branch | Behaviours | What makes it one reviewable unit |
|---|---|---|---|
| **A** | `feature/m2b-spec-builder` | 1–4 | **The config → spec builder. Pure, and no manager.** A function over two config objects returning a `ContainerSpec`; a reviewer needs the config layer and M2a's data types, and nothing about state or async. It also unblocks every later slice, which needs specs to start. |
| **B** | `feature/m2b-state-machine` | 5–8 | **The state machine. Pure, and no I/O.** An enum, a dataclass, a transition table and a logging rule — exhaustively table-testable, with no backend, no probe and no event loop. |
| **C** | `feature/m2b-probe-seam` | 9–11 | **The probe seam and the readiness progression.** A protocol, a scripted double, and the deadline logic that turns probe answers into `STARTING → LOADING → READY`. A reviewer checks the progression and the two deadlines without meeting the coalescing machinery. |
| **D** | `feature/m2b-ensure-ready` | 12–18 | **`ensure_ready` and coalescing.** The concurrency core: one lock, one future, `shield`, `run_in_executor`. The hardest slice to review, and it is alone in its pull request for exactly that reason. |
| **E** | `feature/m2b-drain-and-liveness` | 19–22 | **In-flight counting, drain-then-stop, liveness.** The stop path, which is only reviewable once the start path is merged: draining is defined against the in-flight counter that behaviour 19 introduces. |
| **F** | `feature/m2b-reconcile` | 23–26 | **Reconciliation and documentation.** Boot-time adopt-or-stop, which consumes the whole machine above it and adds no new mechanism — it composes `list_managed`, the probe progression and `stop`. |

**Why the boundaries fall here.** M2a cut at *purity*, and that quality still does most of
the work: slices A and B are pure functions and data, testable with no event loop at all,
while C, D, E and F each add exactly one mechanism (a probe, coalescing, draining,
adoption). The second criterion is **dependency direction**: a reviewer of slice N never
needs slice N+1. A reads nothing; B reads nothing; C reads B's states; D reads A, B and C;
E reads D's manager; F composes all of them. Landing in that order also means each slice's
tests assert against *merged, reviewed* code rather than against a fixture invented in the
same diff — the property M2a's §0.1.2 called out as the reason to land the pure layer
first.

**Why slice D is not split further.** Seven behaviours is the largest slice here, and
splitting the concurrency core would be worse than leaving it whole: behaviours 13–18 are
six assertions about *one* method, and a pull request containing half of `ensure_ready`'s
contract cannot be reviewed for correctness at all.

### 2.1 Branch and stacking mechanics

- **Each slice needs its own branch, stacked on the previous slice's tip.** If a pull
  request is open from a branch and work continues on that same branch, the new commits
  are absorbed into the open pull request and the split is destroyed. M2a nearly lost a
  split to exactly this (§0.1.2: "Two pull requests need two branches, and that was nearly
  missed").
- **A stacked pull request runs no CI.** [`.github/workflows/ci.yml`](../.github/workflows/ci.yml)
  triggers on `branches: [main]` only, so a pull request based on another branch runs
  nothing. **The absence is configuration, not failure**, and a reviewer must not read it
  as red. Retarget each slice to `main` when its parent merges; that is what triggers its
  CI run, and it should happen before approval.
- **Verify the suite locally at each branch tip** and record the count, since CI will not.
- **Documentation is split to match**, as M2a's behaviour 28 was across four slices: each
  slice documents what it delivered, extending `docs/` rather than duplicating it.

### 2.2 Is `feature/m2b-lifecycle-manager` the right name for slice A?

**No — and it is worth fixing before the first commit.** The branch already exists and
this plan sits on it, but slice A delivers the **config → `ContainerSpec` builder**: no
`LifecycleManager`, no state machine, no probe. A pull request titled after the lifecycle
manager whose diff contains a spec builder misleads a reviewer about what to check, and
the name is then wrong for the remaining five slices too — the manager itself arrives in
slice D.

Two workable options:

1. **Rename slice A's branch to `feature/m2b-spec-builder`** and keep
   `m2b-lifecycle-manager` unused, or as the milestone's umbrella name in pull-request
   titles. Costs one `git branch -m` before anything is pushed.
2. **Keep the branch, and land behaviours 1–4 on it** while naming the pull request
   accurately ("M2b part 1 — the config to ContainerSpec builder"). Slices B–F then carry
   their own accurate names.

**Option 1 is cleaner** and the cost is one command, since nothing is pushed yet. Either
way, **this plan's `plans/` commit is the only thing that should land on a branch named
after the whole milestone** — the behaviour commits belong on accurately named slices.

---

## 3. Behaviour ledger

One red/green cycle per behaviour. Each states inputs, outputs, edge cases, error
behaviour, files, and the reasoning behind the choice — rationale lives here now, because
the docstring rule of [§4](#4-discipline) moved it out of the code.

### Slice A — the config → `ContainerSpec` builder

M2a §6 item 7 left this function unowned and said it should be M2b's or M3's first
behaviour. It is M2b's first, and §4.2 of that plan makes it **load-bearing**: it is the
single place a `ParsedMount` becomes a `MountSpec`, so it is the only place the
`mode → read_only` normalisation can live.

#### 1. `build_container_spec` — core assembly from both config blocks

- **Inputs:** a `ResolvedTool` ([`resolver.py`](../src/tool_swap/config/resolver.py:82)),
  a `BackendConfig` ([`schema.py`](../src/tool_swap/config/schema.py:95)), and the
  resolved image reference. `BackendConfig` is a **separate required argument**, not read
  out of `ResolvedTool.values` — see the edge case below, which is the whole reason this
  behaviour exists rather than being an incidental constructor call.
- **Outputs:** a `ContainerSpec` with `tool` from `ResolvedTool.name`, `name` from
  `container_name(cfg.container_prefix, tool)`, `image` as given, `network` from
  `cfg.network`, and the four values M2a's behaviours 4, 6 and 7 deliberately refuse to
  default — `gpu_runtime` and `container_port` passed into the spec, `label_namespace` and
  `container_prefix` consumed here.
  **Corrected during behaviour 1's green step:** only three of those four come from
  `BackendConfig`. `container_port` comes from `ResolvedTool.values`, because
  `BackendConfig` has **no `container_port` field** — its fields are `type`, `network`,
  `container_prefix`, `label_namespace`, `gpu_runtime`, `orphans`, `port_range` and
  `registry_prefix` — and `container_port` is a tool-level default carried in
  [`BUILT_IN_DEFAULTS`](../src/tool_swap/config/defaults.py:54) at `8000`. The original
  wording conflated "the values M2a refuses to default" (a `ContainerSpec` property:
  `gpu_runtime` and `container_port` are required keyword-only fields) with "the values
  the `backend:` block owns" (a `BackendConfig` property). The tester raised it before
  writing the red step rather than resolving it silently, and behaviour 3's own inputs
  list already had `container_port` under `values`, so the two entries now agree.
- **Edge cases:** the four backend-named keys are **also present in
  `ResolvedTool.values`**, always carrying the *built-in* value, because the `backend:`
  block is not a resolver layer ([§6.3](#63-the-backend-block-is-not-a-resolver-layer)). A
  builder reading `values["label_namespace"]` would look correct and silently ignore an
  authored namespace — so the argument is `BackendConfig` and behaviour 4 guards it.
  Also: a tool name or prefix that `container_name` rejects propagates that `ValueError`
  rather than swallowing it.
- **Error behaviour:** `ValueError` from `container_name` propagates unchanged — it already
  names the prefix, the tool and the rule
  ([`labels.py`](../src/tool_swap/backend/labels.py:145)). An empty image raises
  `ValueError` here rather than reaching `build_run_kwargs`, so the message names the tool.
- **Files:** `src/tool_swap/lifecycle/spec_builder.py`.
- **Verified:** construction test over a hand-built `ResolvedTool` and `BackendConfig`.
  Pure function; no daemon, no filesystem.

#### 2. `ParsedMount` → `MountSpec`, and the mode that is neither `ro` nor `rw`

- **Inputs:** `ResolvedTool.values["mounts"]` (authored strings) plus the `config_dir`
  needed to parse them, and the resulting
  [`ParsedMount`](../src/tool_swap/config/validate.py:2436) values.
- **Outputs:** one `MountSpec` per entry, in declaration order, with
  `source = str(parsed.resolved_host)` and `target = parsed.container` — the **resolved**
  host, since `MountSpec` performs no resolution — and `read_only = (parsed.mode == "ro")`.
  The two-part defaulted form (`mode_defaulted=True`, `mode="ro"`) yields
  `read_only=True`, matching `plan/01` §10's "read-only by default".
- **Edge cases:** `mounts` concatenate defaults-then-tool rather than replacing
  ([`resolver.py`](../src/tool_swap/config/resolver.py:173)), and the order must survive
  into the spec; the same target twice keeps both entries, since de-duplication is config
  validation's job; an empty list yields `()`.
- **Error behaviour — a mode that is neither `ro` nor `rw` raises**
  ([D-D](#5-settled-decisions)). Unreachable unless config validation was bypassed, since
  [`TSWAP-C541`](../src/tool_swap/config/validate.py:2736) rejects it case-sensitively,
  `"RO"` included. The error names the tool, the entry and the offending mode.
- **Files:** `src/tool_swap/lifecycle/spec_builder.py`.
- **Verified:** table test over parsed mounts including the defaulted form, an explicit
  `rw`, and the illegal `"RO"`. The builder **calls
  [`parse_mount`](../src/tool_swap/config/validate.py:2488)** rather than splitting a
  string itself — M2a's boundary guard walks `src/tool_swap/backend/` only, so nothing
  mechanically stops a second parser appearing here; behaviour 4 extends the guard.

#### 3. Resource, environment and port passthrough

- **Inputs:** `ResolvedTool.values` for `env`, `devices`, `cpus`, `memory`, `shm_size`,
  `container_port`, `expose_host_port`.
- **Outputs:** `env` as a plain dict of `str → str`; `devices` as a tuple of ints in
  authored order; `cpus`, `memory` and `shm_size` passed through **verbatim**;
  `published_port` derived from `expose_host_port`.
- **Edge cases:** `expose_host_port` is typed `bool | int | None`
  ([`schema.py`](../src/tool_swap/config/schema.py:447)), so three forms need pinning:
  `False` (the built-in default) publishes nothing; an `int` publishes that host port;
  `True` means "publish" with no port named, and **nothing in the config layer allocates
  one** — `port_range` exists but no allocator does. `True` therefore raises a clear
  error naming the gap ([§6.4](#64-expose_host_port-true-has-no-allocator)), rather than
  inventing an allocation policy in a spec builder.
- **Error behaviour:** a size string is **not** validated here — the SDK's `parse_bytes`
  owns that message and M2a behaviour 17 deliberately ships no second parser (M2a §7
  item 11). An `env` value that is not a string is coerced with `str()`, since
  `DefaultsConfig.env` is typed `dict[str, Any]`.
- **Files:** `src/tool_swap/lifecycle/spec_builder.py`.
- **Verified:** table test per field, including each `expose_host_port` form. Pure.

#### 4. The builder is the only `ParsedMount → MountSpec` converter, and reads no backend value from `values`

- **Inputs:** the shipped source tree.
- **Outputs:** two guards. First, a **source-level guard** asserting that
  `src/tool_swap/lifecycle/` contains no mount-string splitting and no second
  `parse_mount` — M2a's existing guard covers `backend/` only, and the conversion has now
  moved into a directory nothing polices. Second, a guard asserting the builder does not
  read `label_namespace`, `container_prefix`, `network` or `gpu_runtime` out of
  `ResolvedTool.values`, because those keys are present-but-wrong there
  ([§6.3](#63-the-backend-block-is-not-a-resolver-layer)).
- **Edge cases:** the guards must be **proven non-vacuous** with in-memory decoys covering
  reach, precision and name detection, and must **write nothing under `src/`** — M2a's
  behaviour 3 got both wrong on its first attempt, and its rework is the precedent.
- **Error behaviour:** the guard fails loudly, naming the offending file and line.
- **Files:** `tests/unit/lifecycle/`.
- **Verified:** AST or source inspection over the package directory, plus the decoys. The
  second guard is the one that earns its place: a wrong namespace is invisible until a
  container is labelled and reconciliation stops adopting it.

### Slice B — the state machine

#### 5. `ToolState` — six members, distinct from `ContainerState`

- **Inputs:** none; a `StrEnum` declaration.
- **Outputs:** exactly `STOPPED`, `STARTING`, `LOADING`, `READY`, `STOPPING`, `FAILED`,
  with the lowercase values `plan/01` §4's table implies.
- **Edge cases:** a test pins the **exact six-member set**, mirroring M2a's four-member
  pin on `ContainerState` — the two enums must not drift toward each other. A second test
  asserts the member sets are disjoint in meaning by checking no `ContainerState` value
  string appears in `ToolState` and vice versa, so a later `RUNNING` added to the wrong
  enum fails a test.
- **Error behaviour:** n/a.
- **Files:** `src/tool_swap/lifecycle/states.py`.
- **Verified:** exact-set test. Pure.

#### 6. `ModelRuntimeState` — the M2b subset of `plan/06` §9

- **Inputs:** keyword construction.
- **Outputs:** the seven fields of [§1.2](#12-modelruntimestate--the-m2b-subset). A fresh
  state for an unknown tool is `STOPPED` with `handle=None`, `inflight=0`,
  `became_ready_at=None`, `last_error=None`.
- **Edge cases:** it is **mutable** (`plan/06` §9's sketch is a plain `@dataclass`,
  unfrozen), unlike every M2a type — the manager updates it in place, and freezing it
  would mean reallocating on every request completion. `handle` is `None` exactly when no
  container exists, and **that invariant belongs to the transitions, not to this class.**
  This line previously said a test asserts `STOPPED` with a non-`None` handle "is
  rejected", which contradicted the *"Error behaviour: n/a — a data holder"* line below
  it, and the enforcement would have been illusory: the manager mutates these objects in
  place, so a `__post_init__` check would pass construction and the invariant could break
  immediately afterwards. A half-enforced invariant is worse than an unenforced one,
  because the next reader trusts it. The shipped test therefore pins that construction
  **stores what it is given**, and is named for that, so it fails if someone later adds
  the validator this line used to imply. Behaviours 7 and 8 own the consistency.
- **Error behaviour:** n/a — a data holder.
- **Files:** `src/tool_swap/lifecycle/states.py`.
- **Verified:** construction and default test, plus the field-set pin recording that
  `group`, `ttl`, `keep_warm`, `evict_cost`, `queued`, `vram_gb` and
  `consecutive_failures` are **absent by decision**, deferred to M6 with the features that
  read them. The pin is what makes the deferral visible rather than forgotten.

#### 7. The transition table, and illegal transitions raise

- **Inputs:** a from-state and a to-state.
- **Outputs:** a pure predicate over the ten edges of
  [§1.1](#11-the-tool-state-machine--six-states-ten-edges), plus an `apply` that
  returns the new state.
- **Edge cases:** the test is **exhaustive over all 36 ordered pairs** — ten legal,
  twenty-six illegal — because a table with a missing edge and a table with a spurious
  one are both silently wrong under any sampled test. Self-transitions are illegal
  (`READY → READY` must not silently re-ready a tool); `STARTING → STOPPED` is illegal and
  the test notes it as M6's `vram_unavailable` path rather than an oversight.
- **Error behaviour:** an illegal transition raises, naming both states. It is a
  programming error, not an operational one — raising is the loud default, and a silently
  ignored transition would leave a tool in a state its caller does not expect.
- **Files:** `src/tool_swap/lifecycle/states.py`.
- **Verified:** 36-pair table test. Pure; the state machine needs no clock and no backend.

#### 8. Every transition is logged with from, to and reason

- **Inputs:** a transition plus a reason string.
- **Outputs:** one log record per transition at INFO, carrying the tool, the from-state,
  the to-state and the reason.
- **Edge cases:** a transition into `FAILED` carries the taxonomy member's message as its
  reason, **verbatim** (M2a §6 item 6); a refused illegal transition logs nothing, since
  it did not happen. The assertion is on the record's **structured fields**, not on a
  formatted string — the qna-tester rule "assert on data structures, not formatted
  output" applies, and a message-text assertion would break on any wording change.
- **Error behaviour:** logging never raises and never swallows the transition.
- **Files:** `src/tool_swap/lifecycle/states.py`.
- **Verified:** `caplog` over the transition function. This is the issue's "state
  transitions are logged" checkbox, and it is pinned at the state machine rather than in
  the manager so every caller inherits it.

### Slice C — the probe seam

#### 9. The `Probe` protocol and `ProbeTarget`

- **Inputs:** the two async method signatures of
  [§1.5](#15-the-probe-seam--a-protocol-fakeprobe-and-no-client).
- **Outputs:** a `@runtime_checkable` `Protocol` with `health` and `ready`, and the frozen
  `ProbeTarget`.
- **Edge cases:** a signature-pin test over `inspect.signature` for both methods —
  name, order, kind, annotation — plus `inspect.iscoroutinefunction`, which is the
  anti-drift test for the seam M3 must implement. A test asserts `ProbeTarget` carries no
  URL: the probe composes one, and a pre-composed URL would put HTTP vocabulary in a type
  that has no client.
- **Error behaviour:** n/a — a declaration.
- **Files:** `src/tool_swap/proxy/probes.py`.
- **Verified:** introspection. **A guard asserts `probes.py` imports no HTTP library**
  (`requests`, `httpx`, `urllib3`, `aiohttp`) — D-B's rule made executable, so an M3
  implementer cannot quietly satisfy the protocol with an undeclared dependency.

#### 10. `FakeProbe` — scriptable answers, including never ready

- **Inputs:** a per-tool script: `health` and `ready` each as "true immediately", "true
  after N calls" or "never true".
- **Outputs:** the scripted booleans, plus a call journal of `(method, tool)` in order —
  the same instrument `FakeBackend.calls` provides, for the same reason: a count is
  assertable where a side effect is not.
- **Edge cases:** "true after N calls" is what makes a real `LOADING` window observable;
  "never true" drives behaviours 16 and 11's timeout paths and is **the "never ready"
  failure the issue asked of `FakeBackend`**, landing where readiness actually lives (M2a
  §4.4 and §7 item 5); an unscripted tool answers true immediately, so a test that does
  not care about probing need not script one.
- **Error behaviour:** `FakeProbe` never raises. A probe that raises is a distinct
  scenario and is **not** modelled in M2b — a transport failure is M3's real probe's
  concern, and inventing its shape here would be an unverified claim about an HTTP client
  that does not exist.
- **Files:** `src/tool_swap/proxy/probes.py`.
- **Verified:** in-memory. `isinstance(FakeProbe(), Probe)` is `True`.

#### 11. `STARTING → LOADING → READY`, driven by probe answers on the injected clock

- **Inputs:** a `FakeProbe` script, a `ManualClock`, and `start_timeout` / `ready_timeout`
  / `probe_interval` (`120`, `600`, `1.0` by default —
  [`defaults.py`](../src/tool_swap/config/defaults.py:42)).
- **Outputs:** the progression as a coroutine: poll `health` every `probe_interval` until
  it answers, transition to `LOADING`, then poll `ready` until it answers, transition to
  `READY`. Each wait is `await clock.sleep(probe_interval)`; each deadline is a comparison
  against `clock.now()` — **never `asyncio.wait_for`**, whose deadline is the loop's clock
  and not the manual one ([§1.3](#13-how-async-waiting-composes-with-manualclock--the-load-bearing-design-answer)).
- **Edge cases:** a probe answering true on the first call skips the sleep entirely, so a
  warm tool costs no simulated time; the two deadlines are **independent** —
  `start_timeout` covers container-up-to-health and `ready_timeout` covers
  health-to-ready, which is the whole point of separating the states (`plan/01` §4:
  "90s in LOADING is a very different problem from 90s in STARTING"); a clock that never
  advances cannot loop forever, because every iteration sleeps.
- **Error behaviour:** either deadline elapsing raises an internal timeout carrying
  **which** deadline and how long elapsed; behaviour 16 turns that into `FAILED`. Two
  distinguishable timeouts, because an operator diagnosing a slow cold start needs to know
  which phase hung.
- **Files:** `src/tool_swap/lifecycle/manager.py` (the progression) with the probe from
  `proxy/probes.py`.
- **Verified:** `@pytest.mark.asyncio` tests with `ManualClock` + `FakeProbe`, asserting
  the state sequence and the simulated elapsed time. Sub-millisecond, no daemon.

### Slice D — `ensure_ready` and coalescing

#### 12. Construction and injection; the manager never imports `docker_backend`

- **Inputs:** `LifecycleManager(backend, probe=..., clock=..., backend_config=...,
  timeouts=...)`.
- **Outputs:** a manager holding exactly the injected objects — identity-wise, the way
  M2a's behaviour 20 pinned `DockerBackend`'s client. No object is constructed internally.
- **Edge cases:** the named guard — **the manager must be fully usable with the docker SDK
  blocked from the import system**, driven by `FakeBackend`. M2a §6 item 1 states the rule
  ("it must never import `docker_backend` directly — only `base`") and behaviour 27's
  import-linter contract already enforces the SDK boundary, but nothing yet enforces the
  *lifecycle → docker_backend* direction. This behaviour adds a **sixth `.importlinter`
  contract** forbidding `tool_swap.lifecycle` and `tool_swap.proxy` from importing
  `tool_swap.backend.docker_backend`, so the manager is structurally prevented from
  reaching past the seam.
- **Error behaviour:** constructing with `None` as the backend or the probe raises
  `TypeError` — a programming error refused loudly rather than at the first call.
- **Files:** `src/tool_swap/lifecycle/manager.py`, `.importlinter`.
- **Verified:** a `sys.meta_path` blocker, the same mechanism
  [`test_docker_sdk_boundary.py`](../tests/unit/test_docker_sdk_boundary.py) uses — a
  `sys.modules` deletion is not enough, since a fresh import would find the SDK again on
  the path. Plus `lint-imports`, and a **non-vacuity proof** that the new contract breaks
  when the forbidden import is added in memory. **Note:** M1 ships anti-drift pins
  asserting the exact contract count; adding a sixth will break them, and they must be
  **updated to six and kept exact**, not weakened to a subset check — M2a's behaviour 27
  hit this and the exact-set pin is meant to fail so someone looks.

#### 13. `ensure_ready` — the cold-start happy path

- **Inputs:** a `FakeBackend`, a `FakeProbe` answering true immediately, a `ManualClock`,
  and a tool in `STOPPED`.
- **Outputs:** the tool ends `READY`; the returned `ContainerHandle` is the one
  `FakeBackend.start` produced; `became_ready_at == clock.now()`; the journal shows
  exactly one `start`; the state sequence is `STOPPED → STARTING → LOADING → READY` with
  no skipped state.
- **Edge cases:** a second `ensure_ready` on an already-`READY` tool **starts nothing** and
  returns the same handle — the journal still shows one `start`. That is the idempotence
  half of `plan/01` §5.1 rule 1, and it is the common case in production, not an edge.
  `ensure_ready` on a `READY` tool also **touches nothing about `last_used`**: `plan/06`
  §2 is explicit that `last_used` updates on request **completion**, not arrival, and
  behaviour 19 owns it.
- **Error behaviour:** none on this path.
- **Files:** `src/tool_swap/lifecycle/manager.py`.
- **Verified:** `@pytest.mark.asyncio`, `ManualClock`, `FakeBackend`, `FakeProbe`.

#### 14. Ten concurrent `ensure_ready` produce exactly one start

- **Inputs:** ten coroutines via `asyncio.gather` against one `STOPPED` tool, with a probe
  that needs at least one poll so the cold start is genuinely concurrent rather than
  completing inside the first caller's first step.
- **Outputs:** **exactly one `("start", ...)` entry in `fake.calls`**, counted from the
  journal rather than inferred from `list_managed` — the journal records on entry and so
  captures a call that raises, which is why M2a built it (§0.1.1). All ten coroutines
  return, and all ten return the **same handle**.
- **Edge cases:** ten waiters must not each advance the manual clock —
  [§1.3](#13-how-async-waiting-composes-with-manualclock--the-load-bearing-design-answer)
  rule 2, pinned by [`test_clock.py`](../tests/unit/test_clock.py:547): concurrent
  `ManualClock` sleeps **sum**, so ten pollers would advance time tenfold and trip their
  own `ready_timeout`. The test therefore also asserts the **simulated elapsed time is
  what one cold start costs**, which is what proves the followers are awaiting a future
  rather than polling. A second round after the tool goes `READY` adds no `start`.
- **Error behaviour:** if the single start fails, **all ten** receive the same failure and
  the tool is `FAILED` once — not ten times, and not ten different errors.
- **Files:** `src/tool_swap/lifecycle/manager.py`.
- **Verified:** `asyncio.gather` of ten calls. **This test must be re-run repeatedly
  before its green is accepted** — M2a re-ran its concurrency test 25 times consecutively,
  because a flaky green is not a green.

#### 15. A backend start failure yields `FAILED` carrying the taxonomy member's reason

- **Inputs:** `FakeBackend(script={"t1": FailureMode.FAIL_TO_START})`.
- **Outputs:** the tool is `FAILED`; `last_error` is the `ContainerStartError`'s
  `message`, **verbatim** (M2a §6 item 6: "M2b formats it, it does not invent it");
  `handle` is `None`, since no container exists; the transition is logged with the reason.
- **Edge cases:** the failure **repeats** — the script is not one-shot, so a retry loop
  cannot silently succeed; a name conflict (`ContainerNameConflictError`) is a *different*
  taxonomy member and must reach `last_error` unaltered too, so the test covers both
  rather than only the scripted one; `ensure_ready` on a `FAILED` tool retries via the
  legal `FAILED → STARTING` edge.
- **Error behaviour:** `ensure_ready` **re-raises** to its caller after recording
  `FAILED`. Returning a sentinel would make the proxy's error path guesswork; M3 maps the
  exception to a 503 with the reason.
- **Files:** `src/tool_swap/lifecycle/manager.py`.
- **Verified:** in-memory. This is the issue's "failure paths give `FAILED` with the
  reason" checkbox.

#### 16. A readiness timeout yields `FAILED` naming which deadline elapsed

- **Inputs:** a `FakeProbe` whose `health` answers true but whose `ready` **never** does,
  plus the mirror case where `health` never answers.
- **Outputs:** the never-ready case ends `FAILED` with a `last_error` naming
  `ready_timeout` and the elapsed simulated seconds; the never-healthy case ends `FAILED`
  naming `start_timeout`. The container **is stopped** on the way to `FAILED` — a tool
  that never became ready must not leave a container resident, or a failed cold start
  leaks a slot.
- **Edge cases:** the two timeouts are independently configurable and independently
  reported; simulated elapsed time equals the relevant timeout, not their sum, which
  proves the deadlines are not accidentally chained; `FakeBackend.calls` shows one `start`
  and one `stop`.
- **Error behaviour:** the raised error is distinguishable from a start failure, since
  "never became ready" and "refused to start" have different remedies.
- **Files:** `src/tool_swap/lifecycle/manager.py`.
- **Verified:** `ManualClock` + `FakeProbe`; sub-millisecond despite a 600-second
  simulated `ready_timeout`, which is the whole value of `plan/06` §9.

#### 17. A caller cancelled mid-cold-start neither kills the start nor orphans the container

- **Inputs:** two callers; the first is cancelled while the cold start is in progress.
- **Outputs:** the **second caller still gets a `READY` tool**, because followers await
  `asyncio.shield(task)` — verified from `shield`'s own docstring at
  [`tasks.py:841`](file:///usr/lib/python3.11/asyncio/tasks.py), which states the inner
  task is not cancelled when the containing coroutine is. The cancelled caller raises
  `CancelledError`. Exactly one `start` in the journal.
- **Edge cases:** the harder case — **every** waiter is cancelled. The cold start must
  still run to completion and record its outcome, because an in-flight
  `run_in_executor` call cannot be stopped:
  `concurrent.futures.Future.cancel` returns `False` once `RUNNING`
  ([`_base.py:364`](file:///usr/lib/python3.11/concurrent/futures/_base.py)), and
  `asyncio`'s bridge only *attempts* cancellation
  ([`futures.py:387`](file:///usr/lib/python3.11/asyncio/futures.py)). A container that
  started with nobody recording its handle is an orphan only reconciliation could find, so
  the test asserts the tool reaches a terminal state and the handle is recorded even with
  no waiters left.
- **Error behaviour:** `CancelledError` propagates to the cancelled caller and to nobody
  else.
- **Files:** `src/tool_swap/lifecycle/manager.py`.
- **Verified:** `asyncio.Task.cancel` against a probe that needs several polls. No daemon.

#### 18. Backend calls run in an executor; no blocking call runs on the event loop

- **Inputs:** a backend whose `start` blocks on a `threading.Event` until released.
- **Outputs:** while `start` is blocked, **the event loop still runs other tasks** — a
  concurrently spawned task makes progress, which is the assertion that distinguishes
  `run_in_executor` from a direct call. Released, the cold start completes normally.
- **Edge cases:** a second tool's `ensure_ready` progresses while the first tool's start
  is blocked, which is `plan/06` §8.7's group-isolation property in the only form M2b can
  test (no groups yet) — a global lock held across a start would fail it. `stop` and
  `is_running` are off-loaded too, not just `start`; a blocking `stop` must not stall the
  loop either.
- **Error behaviour:** an exception raised inside the executor surfaces at the `await`
  with its type intact, so behaviour 15's taxonomy mapping still works across the hop.
- **Files:** `src/tool_swap/lifecycle/manager.py`.
- **Verified:** a blocking fake plus a progress-observer task. **The blocking fake is a
  test double in the test file, not a `FakeBackend` failure mode** — `FakeBackend` spawns
  no threads by construction (M2a §0.1.1), and giving it blocking behaviour would make
  every other test's timing dependent on it.

### Slice E — in-flight counting, drain-then-stop, liveness

#### 19. In-flight counting, with the counter returning to zero on an abandoned request

- **Inputs:** `begin_request` / `end_request` around a simulated proxied call.
- **Outputs:** `inflight` increments before the call and decrements after; `last_used` is
  set from `clock.now()` on **completion**, not arrival — `plan/06` §2 is explicit, and
  arrival-based TTL would let a long request expire mid-flight.
- **Edge cases:** the decrement must happen in a `finally`, so an exception or a
  disconnect mid-request still returns the counter to zero. `plan/06` §8.3 names this
  precisely: "verify the in-flight counter returns to zero even when the client
  disconnects mid-request (the `finally` must run)". A counter that leaks upward makes a
  tool permanently immune to stopping — resident forever, invisible until the GPUs are
  full. Nested requests count independently; `end_request` on a tool with `inflight == 0`
  is a programming error and raises rather than going negative.
- **Error behaviour:** as above.
- **Files:** `src/tool_swap/lifecycle/manager.py`.
- **Verified:** synchronous counter tests plus an async one that cancels mid-request. The
  cancellation case is the one that matters; the happy path is nearly trivial.

#### 20. `stop` drains in-flight work, then stops the container

- **Inputs:** a `READY` tool with `inflight > 0`, then the in-flight work completing.
- **Outputs:** `stop` does **not** call the backend while `inflight > 0`; once the counter
  reaches zero it transitions `READY → STOPPING`, calls `backend.stop(handle,
  timeout_s=stop_timeout)`, then `STOPPING → STOPPED` with `handle=None`.
- **Edge cases:** a tool with `inflight == 0` stops immediately with no waiting; new
  `ensure_ready` calls arriving **during** `STOPPING` must not be served by the dying
  container — they wait and then trigger a fresh start, since `STOPPING → STARTING` is not
  a legal edge; `stop` on an already-`STOPPED` tool is a no-op; the drain wait uses
  `clock.sleep`, so a 30-second `drain_timeout` costs no real time.
- **Error behaviour:** `timeout_s` is passed **unconditionally**, zero included — M2a's
  behaviour 22 records the trap: the SDK drops the parameter only on a strict `is None`
  check, so a falsy drop of `0` would substitute the daemon's own default. M2b asserts the
  value passed, never the signals, which are deferred daemon test 2.
- **Files:** `src/tool_swap/lifecycle/manager.py`.
- **Verified:** `ManualClock` + `FakeBackend`, asserting call order and absence. This is
  the issue's "drain waits for in-flight then stops" checkbox, and `plan/06` §8.3's
  in-flight half.

#### 21. `FailureMode.STOP_HANGS` and the drain-timeout path, in one cycle

- **Inputs:** `FakeBackend(script={"t1": FailureMode.STOP_HANGS})`, plus a tool whose
  in-flight work never completes.
- **Outputs:** two paths. First, in-flight work that outlasts `drain_timeout`: the manager
  stops waiting at the deadline and proceeds to stop the container anyway, logging that
  the drain timed out — `plan/06` §2.1 note is explicit that a 90-second inference will
  exceed a 30-second `drain_timeout`, and hanging forever instead would leak the slot
  permanently. Second, a backend `stop` that hangs: bounded, and the tool ends `FAILED`
  rather than stuck in `STOPPING` forever.
- **Edge cases:** **this behaviour adds the third `FailureMode` member**, deferred from
  M2a precisely so it arrives in the same red/green cycle as the test that needs it (M2a
  §7 item 5). The member and its test land together; a member shipped ahead of its proof
  is dead code. `FakeBackend` must express "hangs" **without a real thread or sleep** —
  blocking on the manual clock's cooperation, not on wall time, since the fake spawns no
  threads.
- **Error behaviour:** the escalation is bounded by the clock, never by wall time, so this
  test is sub-millisecond too.
- **Files:** `src/tool_swap/backend/fake_backend.py` (the member),
  `src/tool_swap/lifecycle/manager.py`.
- **Verified:** `ManualClock`. **Note this is the one behaviour that edits an M2a
  module** — deliberately, by M2a's own plan, and the `FailureMode` exact-member-set test
  M2a shipped will fail and must be **updated to three members, kept exact**.

#### 22. The liveness sweep marks a vanished container `FAILED`

- **Inputs:** a `READY` tool, then `fake.vanish(handle)` behind the manager's back, then
  `sweep_liveness()`.
- **Outputs:** the tool becomes `FAILED` with a `last_error` saying the container
  disappeared out of band; `handle` is cleared. Relies on `is_running` returning **`False`
  rather than raising** for a missing container (M2a §6 item 4) — without it the sweep
  would be an unhandled traceback in a watchdog, and a watchdog that dies silently leaves
  models resident forever (`plan/06` §7).
- **Edge cases:** a `DIE_AFTER_START` container is dead by first observation and is caught
  by the same sweep; the sweep is **per-tool fault-isolated** — one tool raising must not
  abort the others, which `plan/06` §7's "must never crash the router (catch and log
  per-model)" demands; a `STOPPED` tool is skipped, not probed; a tool with `inflight > 0`
  whose container vanished still goes `FAILED` (the container is genuinely gone — immunity
  protects from *eviction*, not from reality).
- **Error behaviour:** the sweep never raises to its caller and logs per tool.
- **Files:** `src/tool_swap/lifecycle/manager.py`.
- **Verified:** `vanish()` + `DIE_AFTER_START`, no daemon — the two affordances M2a built
  for this exact test (§0.1.1). This is the issue's "a vanished container becomes
  `FAILED`" checkbox. **The sweep is a method, not a scheduled task**: the periodic
  watchdog that calls it on a tick is M6's (`plan/06` §7), and M2b ships the sweep a
  caller can invoke.

### Slice F — reconciliation and documentation

#### 23. Reconciliation adopts a labelled, running container

- **Inputs:** a `FakeBackend` pre-populated with a running container whose tool is in the
  config, plus the probe.
- **Outputs:** the tool ends `READY` with the discovered handle and
  `last_used = clock.now()`; **`plan/06` §8.6's documented consequence is asserted** — TTL
  bookkeeping restarts from now and is not preserved across a router restart. **No
  container is started**: the journal shows zero `start` calls, which is the property that
  makes adoption adoption rather than a restart.
- **Edge cases:** adoption **goes through the probe progression** rather than assigning
  `READY` directly ([§1.1](#11-the-tool-state-machine--six-states-ten-edges)) — a
  container that is running but not ready must end `LOADING` or `FAILED`, never `READY`,
  because a router that adopts a still-loading container as ready proxies into a 503. An
  adopted container that fails its probe ends `FAILED` and is **not** stopped: it may be
  mid-load, and stopping it would destroy work a restart should have preserved.
- **Error behaviour:** a container carrying the managed-by label but no model label is
  already skipped with a warning by `list_managed` (M2a behaviour 25), so it never reaches
  here.
- **Files:** `src/tool_swap/lifecycle/reconcile.py`.
- **Verified:** in-memory. This is half the issue's "reconciliation adopts a ready
  container and stops an orphan" checkbox.

#### 24. Reconciliation applies the `orphans` policy to a container whose tool left the config

- **Inputs:** a running container whose tool is **not** in the config, under each of
  `orphans: stop` (the built-in default,
  [`defaults.py`](../src/tool_swap/config/defaults.py:75)), `adopt` and `ignore`.
- **Outputs:** `stop` calls `backend.stop` once and logs a warning naming the container;
  `ignore` leaves it running and calls nothing; `adopt` keeps it and tracks it. All three
  are pinned, because the default being `stop` means a misconfiguration **destroys a
  running container**, and that is exactly the behaviour a test must nail down.
- **Edge cases:** an **exited** orphan is stopped as a no-op rather than skipped, so the
  policy needs no special case; `adopt` on a tool with no config has no TTL or resources
  to apply, and the test records that it is tracked but ungoverned — which is why `stop`
  is the default; an unrecognised `orphans` value raises rather than silently choosing.
- **Error behaviour:** a failure stopping one orphan must not abort the rest of
  reconciliation — boot must complete.
- **Files:** `src/tool_swap/lifecycle/reconcile.py`.
- **Verified:** in-memory, table-driven over the three policies.

#### 25. Reconciliation is repeat-safe and never stops a serving container

- **Inputs:** reconciliation run twice over the same backend state; and a run against a
  tool with `inflight > 0`.
- **Outputs:** the second run changes no state, starts nothing and stops nothing — the
  journal after run two shows no new mutating call. A container with in-flight work is
  **never stopped**, even when it looks like an orphan.
- **Edge cases:** `plan/01` §7 states both requirements ("safe to run repeatedly", "must
  never kill a container that is currently serving"), and they matter because `plan/06` §7
  item 6 has the watchdog calling reconciliation **periodically** — so the boot-time path
  is really a recurring one, and a non-idempotent version would thrash containers every
  tick. A tool already `READY` from a previous run is not re-probed into `STARTING`.
- **Error behaviour:** as above.
- **Files:** `src/tool_swap/lifecycle/reconcile.py`.
- **Verified:** two consecutive runs with journal comparison. The in-flight case is the
  safety-critical one: stopping a serving container fails a live request.

#### 26. Documentation

- **Inputs:** the modules delivered above.
- **Outputs:** Google-style module docstrings for `spec_builder.py`, `states.py`,
  `probes.py`, `manager.py` and `reconcile.py`, each stating the module's responsibility
  and its boundary; a `docs/lifecycle.md` with the **mermaid state diagram** of
  [§1.1](#11-the-tool-state-machine--six-states-ten-edges); a troubleshooting section
  covering container start failures, probe timeouts and reconciliation edge cases; and the
  docker-testing note, which must say plainly that **M2b runs no daemon tests** and name
  `TSWAP_TEST_DOCKER_HOST` as the future switch.
- **Edge cases:** no flag or command may be documented from memory — each is checked
  against the code first; the docs must not claim daemon verification, TTL behaviour,
  eviction or groups, none of which M2b ships. `docs/backend-seam.md` says "what this page
  does **not** contain is the M2b tool state machine"; that sentence must be updated to
  point at the new page rather than left stale.
- **Error behaviour:** n/a.
- **Files:** `src/tool_swap/lifecycle/*.py`, `src/tool_swap/proxy/probes.py`, `docs/`.
- **Verified:** the existing docstring checks in
  [`tests/unit/test_repo_layout.py`](../tests/unit/test_repo_layout.py:113), a link check,
  and review. **Split across the six slices**, as M2a's behaviour 28 was: each slice
  documents what it delivered.

---

## 4. Discipline

Each item below cost something on M2a, and each binds this milestone.

**Never assert a third-party fact from memory.** M2a §3 records the rule, and it caught a
wrong `CancellableStream` module path that would have failed at import, plus a `nano_cpus`
conversion a recollection would have got wrong by a factor of 1e9. M2b is mostly stdlib,
and the rule applies unchanged. Every asyncio claim in this plan was read from the
installed interpreter's own source and is cited to its file and line:

| Claim | Source | Status |
|---|---|---|
| `shield` leaves the inner task running when the containing coroutine is cancelled | [`asyncio/tasks.py:841`](file:///usr/lib/python3.11/asyncio/tasks.py) docstring | **[READ]** |
| A `concurrent.futures.Future` cannot be cancelled once `RUNNING` | [`concurrent/futures/_base.py:364`](file:///usr/lib/python3.11/concurrent/futures/_base.py) | **[READ]** |
| Cancelling the asyncio side only *attempts* `source.cancel()` | [`asyncio/futures.py:387`](file:///usr/lib/python3.11/asyncio/futures.py) `_chain_future` | **[READ]** |
| `ManualClock.sleep` advances simulated time and yields | [`utils/clock.py:130`](../src/tool_swap/utils/clock.py:130) | **[READ]** |
| Concurrent `ManualClock` sleeps **sum** rather than overlap | [`tests/unit/test_clock.py:547`](../tests/unit/test_clock.py:547), a shipped passing test | **[READ]** |
| `asyncio_mode = "strict"`, so every async test needs `@pytest.mark.asyncio` | [`pyproject.toml:67`](../pyproject.toml:67) plus 15 existing marked tests in `test_clock.py` | **[READ]** |
| `asyncio.wait_for` uses the event loop's clock, not an injected one | **not verified from source** — inferred from the loop owning its own timer | **[INFERRED]** |

That last row is marked rather than stated as fact. It does not weaken the design: rule 1
of [§1.3](#13-how-async-waiting-composes-with-manualclock--the-load-bearing-design-answer)
avoids `wait_for` regardless, and a deadline compared against `clock.now()` is correct
whichever clock `wait_for` would have used. **An unverified claim stated as fact is the
failure mode; an unverified claim labelled as such is fine.**

**A red step that aborts pytest collection is not a red step.** M2a's behaviour 3 imported
a missing name at module scope, so none of the 1128 tests ran and the output proved
nothing. Every M2b test file must use a **per-test deferred-import gate**, because
`spec_builder.py`, `states.py`, `probes.py`, `manager.py` and `reconcile.py` will not exist
when their tests are written. The ledger's ordering helps — a behaviour needing a module
follows the one that creates it — but the gate is what makes each red an assertion failure
rather than an `ImportError`.

**Guards must be proven non-vacuous and must never write into `src/`.** Behaviours 4, 9
and 12 each ship a guard, and each must demonstrate with in-memory decoys that it catches
what it claims to. M2a's first boundary guard wrote decoy modules into the real package
*and* excluded them from its own walk — all of the risk, none of the verification.

**Plan for the coder's escalation route.** On M2a the coder claimed a test was wrong seven
times across two branches; every claim was verified independently and **every one was
upheld**. That is the pipeline working. These behaviours are written to be decidable by
reading the plan: where a contract is a judgement call (the raise in behaviour 2, the
`True` rejection in behaviour 3, the non-cancellable executor call in behaviour 17), the
reasoning is here so a disagreement resolves against the text rather than against memory.

**Two rules changed after M2a's review and they bind this milestone:**

1. **A docstring says what the code pins and why it could fail, in one to three lines.**
   Rationale belongs in the commit message and in this plan — which is why every behaviour
   above carries its reasoning. A docstring approaching the length of the code it
   documents is narrating a decision that belongs here.
2. **Process vocabulary never appears in a string a developer reads on failure.** No "RED
   step", no "GREEN step", no behaviour numbers as workflow markers in assertion messages,
   `pytest.fail` text or skip reasons. Those strings are read by someone debugging a
   failure: they state what is missing and where.

**M2a's own test files have not been retrofitted to these two rules, and their density is
not the model.** A retrofit is a separate task and is not M2b's.

---

## 5. Settled decisions

Four decisions were settled with the user before this plan was written. They are fixed
inputs, recorded here with their rationale.

### D-A. `ensure_ready` is asyncio, not threads

The user's words: *"Asyncio: `ensure_ready` is a coroutine with an `asyncio.Lock`, backend
calls go through `run_in_executor`. The synchronous seam stays as-is — M3's proxy is the
real caller and the event loop must not stall."*

This matches [`plan/01`](../plan/01_ARCHITECTURE.md:308) §5.1 rule 1, which already
specified "a per-model `asyncio.Lock` + a stored pending readiness awaitable". Consequences
are worked through in [§1.3](#13-how-async-waiting-composes-with-manualclock--the-load-bearing-design-answer)
and [§1.4](#14-ensure_ready--coalescing-and-what-run_in_executor-means-for-it): the
container backend seam **stays synchronous** (changing it would be "a change to behaviour 8
and a re-review, not a quiet adaptation" — M2a §7 item 4); the coalescing test becomes ten
coroutines via `asyncio.gather` counted from the journal; and waiting goes through
`Clock.sleep` so it is both async and fake-clock-driven.

### D-B. The probe is a seam only; no HTTP client is declared

The user's words: *"Seam only. `Probe` protocol + `FakeProbe` + the state progression; no
HTTP client declared in M2b. The real probe lands in M3 with the proxy's client."*

Rationale: the repository has **no declared HTTP client**, and `requests` exists only
transitively under `docker`. Importing it directly would be an undeclared dependency — the
exact defect pull request #9 existed to fix. Behaviour 9 makes the rule executable with a
guard asserting `probes.py` imports no HTTP library, so an M3 implementer cannot satisfy
the protocol with an undeclared dependency by accident.

### D-C. The queue-policy seam and shutdown ordering are out of scope

[`plan/09_IMPLEMENTATION_PLAN.md`](../plan/09_IMPLEMENTATION_PLAN.md:92) §M2 lists both,
and issue #3's Scope does not. Both concern **queued** requests, and nothing queues until
M3's proxy exists — the same reasoning that kept `FailureMode.STOP_HANGS` out of M2a. This
is a deliberate, user-confirmed departure from `plan/09` §M2, recorded again in
[§6.5](#65-the-queue-policy-seam-and-shutdown-ordering-depart-from-plan09-m2).

**Drain-then-stop stays in scope** — the Definition of Done names it, and behaviours 19–21
deliver it. Note that [`plan/01`](../plan/01_ARCHITECTURE.md:374) §7.1's shutdown ordering
puts *"drain in-flight requests"* as step 3 of four; M2b ships that step's mechanism
without the router-level steps 1 and 2 around it, and **nothing in this plan contradicts
§7.1** — the ordering is simply M3's to impose.

### D-D. A mount mode that is neither `ro` nor `rw` raises

M2a §6 item 7 left this deliberately unowned, and it now belongs to the spec builder. The
user chose **the loud default over the safe one: raise**, rather than silently downgrading
to read-only, because a silent downgrade hides a broken upstream invariant and yields a
container whose mounts do not match its config. Unreachable unless config validation was
bypassed — [`TSWAP-C541`](../src/tool_swap/config/validate.py:2736) rejects it
case-sensitively, `"RO"` included. Behaviour 2 owns it.

### D-E. `expose_host_port: null` publishes nothing; only `true` raises

Settled by the user **during behaviour 3's red step**, which is why it is numbered after
D-D rather than alongside it. The plan named three forms and left `null` — the fourth,
reachable because the field is typed `bool | int | None` — unspecified.

The qna-tester's first version raised on `null`, reasoning by analogy with `true`, and
flagged it for confirmation rather than settling it alone. The user overruled it: **`null`
publishes nothing, exactly like `false`.** Two reasons:

1. **It matches this schema's convention for every other nullable field.** `cpus` and
   `memory` both document *"null leaves it unlimited"*, and the auth token *"null disables
   authentication"* — so an authored null in this configuration language means "no
   opinion, take the benign default", never "error".
2. **Raising would turn valid config into a runtime crash.** `TSWAP-C530` and
   `TSWAP-C531` both skip non-`int` values
   ([`validate.py`](../src/tool_swap/config/validate.py:2174)), so
   `expose_host_port: null` passes validation. A builder that raised would let the router
   start, load its config, resolve a tool, and only then fail — long after the point where
   a configuration error should have been reported.

**`true` still raises, and the asymmetry is the point.** There the schema promises
something no code can deliver: it advertises an auto-allocation from `backend.port_range`,
and nothing allocates — `port_range` is read only by `schema.py`, `defaults.py` and the
validation rules ([§6.4](#64-expose_host_port-true-has-no-allocator)). Raising surfaces a
genuine gap. For `null` there is an obvious, safe, convention-consistent reading, so there
is no gap to surface.

The two forms are now one parametrized test, since they pin a single contract.

---

## 6. Open assumptions

In the style of M2a §7, whose items 10, 11 and 12 were all real gaps found during the
work. Every departure from issue #3 or `plan/09` §M2, every unverified claim, and every
gap found in a neighbouring layer.

### 6.1 What the user confirmed

The 26-behaviour list, the six-slice cut, the section-8 scope of §6.2 and the no-new-package
finding of §6.6 were **presented to the user and approved before this plan was written**,
as the architect's validation gate requires. D-A through D-D were settled earlier, in the
session that delegated this plan.

### 6.2 Issue #3's section-8 requirement is mostly M6's

Issue #3 requires *"every scenario from `plan/06_LIFECYCLE_TTL_AND_SCHEDULING.md` §8 tested
with `ManualClock` + `FakeBackend`"*. **M2b covers three of nine, and the departure is
deliberate:**

| Scenario | Status in M2b | What it needs |
|---|---|---|
| 8.4 thundering herd | **covered** — behaviour 14 | — |
| 8.6 router restart | **covered** — behaviours 23–25 | — |
| 8.3 in-flight protection | **covered in part** — behaviours 19–20 do the in-flight immunity; the TTL half is not | a TTL sweep |
| 8.1 simple swap | deferred | groups, `max_resident`, `min_residency`, eviction |
| 8.1d cheap victim | deferred | `evict_cost`, victim ranking |
| 8.2 TTL expiry | deferred | the TTL watchdog |
| 8.5 failure and backoff | deferred | `restart_backoff`, `consecutive_failures` |
| 8.5b reload under contention | deferred | the `vram_unavailable` classification (**D28**) |
| 8.7 group isolation | deferred | groups |

[`plan/09_IMPLEMENTATION_PLAN.md`](../plan/09_IMPLEMENTATION_PLAN.md:228) places every one
of those in **M6** (`scheduler/policy.py`, the TTL watchdog, LRU eviction, `min_residency`,
D28). Nothing in M2b's scope has a group, a TTL sweep or a failure counter to test against,
so writing those tests now would mean either inventing M6's design or asserting against
stubs. **Behaviour 18 does capture 8.7's underlying property** in the only form available
without groups: one tool's blocked start must not stall another's. The issue was not
amended, so this entry is the record.

### 6.3 The `backend:` block is not a resolver layer — a real gap, found while planning

[`resolve_tool`](../src/tool_swap/config/resolver.py:158) builds its layers from `inline`,
`tool_yaml`, `defaults`, the group and the built-ins. **The `backend:` block is never a
layer.** But `values` is populated by iterating all 47 `BUILT_IN_DEFAULTS` keys
([`resolver.py:239`](../src/tool_swap/config/resolver.py:239)), and eight of those are
backend keys — so `values["label_namespace"]`, `values["container_prefix"]`,
`values["network"]` and `values["gpu_runtime"]` are **always present and always the
built-in value**, silently ignoring an authored `backend:` block.

This is a trap of exactly the shape M2a's §7 item 10 described: a builder reading
`values["label_namespace"]` compiles, type-checks, passes a naive test, and stamps
`com.tool-swap` on every container whatever the operator configured. The failure surfaces
much later, as reconciliation failing to adopt containers it cannot see.

**M2b's mitigation is local:** behaviour 1 takes `BackendConfig` as a separate required
argument and behaviour 4 guards against reading those four keys from `values`. **The real
fix belongs to the config layer** — either a `backend:` layer in the resolver, or removing
the eight backend keys from the tool-level `values` key set so the wrong value is
unreachable rather than merely unused. Whether tool-level resolution should carry backend
keys at all is a config-layer design question, and **not filed by this task**.

### 6.4 `expose_host_port: true` has no allocator

[`ToolConfig.expose_host_port`](../src/tool_swap/config/schema.py:447) is typed
`bool | int | None`, and `BackendConfig.port_range` exists with a `[7000, 7999]` default —
but **nothing in the repository allocates a port from that range** (searched: no allocator,
no port-assignment code). `True` therefore means "publish a port" with no way to choose
one. Behaviour 3 raises for that form rather than inventing an allocation policy inside a
spec builder.

This is benign today: **D21** means tools are reached by container name on the shared
network and nothing needs a published port, so `expose_host_port` is a debugging
affordance. But the config accepts a value the system cannot honour, which is the same
shape of gap as M2a §7 items 10 and 11. Either an allocator or a `TSWAP-C5xx` rule
rejecting `true` would be the right fix, in the config layer. **Not filed by this task.**

### 6.5 The queue-policy seam and shutdown ordering depart from `plan/09` §M2

Recorded per D-C. `plan/09` §M2 lists both as M2 work, and calls declaring the queue-policy
seam *"cheapest before any code exists; an awkward retrofit after"* — a real argument
against deferring it. It is deferred anyway, because issue #3's Scope omits both and
neither has a caller until M3's proxy queues a request. **If `plan/09` §M2 is read as
binding, this is a contradiction and the issue was not amended** — this entry is the
record, and the retrofit cost is accepted knowingly.

### 6.6 An existing package was evaluated and rejected

My rules require searching the registries before planning bespoke code. I did:
[`transitions`](https://pypi.org/project/transitions/) 0.9.3 is MIT-licensed,
actively maintained, carries **no security advisories**, and has an `AsyncMachine`
extension. It genuinely solves behaviours 7–8.

**It is not planned in**, for three reasons: D-B forbids a new package in M2b; it depends
on `six`, adding a transitive dependency to a project with six declared ones; and the
machine here is six states and ten edges, so a dict of legal transitions is smaller than
the adapter layer would be. Recorded rather than left unmentioned, so a later reviewer sees
the reuse question was asked and answered. **No behaviour in this plan needs a package
beyond the declared set.**

### 6.7 M2b claims no daemon verification, and the issue's docker table is not M2b's

Issue #3's "Tests — docker" table and its *"All three docker tests pass against a
disposable daemon"* checkbox are **not M2b's**. The three deferred daemon tests and the
DinD harness remain unfiled (M2a §7 item 7). The `docker` marker stays registered and
deselected by default, **no test carries it**, and `TSWAP_TEST_DOCKER_HOST` appears only in
documentation. This is a visible departure from the Definition of Done and it is
deliberate: this environment has no reachable daemon, and an unverified test is not
evidence.

### 6.8 The watchdog is not shipped; the sweep is a method

`plan/06` §7's periodic watchdog — the tick, the heartbeat line, `last_tick_age_s` in
`/status` — is **not** in M2b. Behaviour 22 ships `sweep_liveness()` as a method a caller
invokes; nothing schedules it. The scheduled watchdog belongs with the TTL sweep, the
retry-with-backoff and the periodic reconciliation it also drives, all of which are M6's.
Issue #3 does not ask for the watchdog, so this agrees with the issue and departs only from
a reading of `plan/06` §7 as M2 work.

### 6.9 Two M2a pins will break, and must be tightened rather than weakened

Behaviour 21 adds `FailureMode.STOP_HANGS`, and behaviour 12 adds a sixth `.importlinter`
contract. Both break exact-set pins M2a shipped deliberately — the `FailureMode`
two-member test, and M1's contract-count pins that assert exactly five contracts and
`5 kept, 0 broken`. **Neither is buggy: an exact-set pin is meant to fail when the set
changes, so that someone looks.** They must be updated to three members and six contracts,
**kept exact**, never relaxed to a subset check. M2a's behaviour 27 hit this same situation
and set the precedent.

### 6.10 `plan/06` §9's `ModelRuntimeState` is shipped incomplete, by decision

**Corrected during behaviour 6's red step**, where the qna-tester checked this paragraph
against the source instead of taking it on trust. It read "seven of the sketch's thirteen
fields. The six omitted", and both numbers were wrong: the sketch has **twelve** fields,
and the list that followed named **seven**, not six. Verified by counting
[`plan/06` §9](../plan/06_LIFECYCLE_TTL_AND_SCHEDULING.md:396).

The arithmetic never worked because the relationship is not a subset. Of the sketch's
twelve fields M2b **keeps five** — `name` renamed to `tool`, `state` retyped from
`ModelState` to `ToolState`, plus `last_used`, `became_ready_at` and `inflight` — and
**defers seven**: `group`, `queued`, `keep_warm`, `ttl`, `evict_cost`, `vram_gb`,
`consecutive_failures`. It then **adds two the sketch never had**: `handle`, because
something must hold the `ContainerHandle` the backend returns, and `last_error`, because
`FAILED` carries a reason. Five kept plus two added is the seven M2b ships.

The seven deferred fields belong to features M2b does not have, and a field no behaviour
reads is a field whose semantics are guessed. The field-set pin makes the omission
visible. **If M3 or M6 needs one of them, adding it is a behaviour with a test, not a
quiet edit.**

### 6.11 `FakeProbe` models no transport failure

Behaviour 10 states it: `FakeProbe` never raises. A probe that fails at the transport level
— connection refused, TLS error, a malformed response — is a real scenario, and it is
**not modelled here**, because its shape depends on the HTTP client M3 declares. Inventing
it now would be an unverified claim about a dependency that does not exist. **M3 must add
that failure mode to `FakeProbe` alongside the real probe**, and behaviour 11's deadline
logic is the seam where it will land.

### 6.12 Docker versus Podman is unchanged

`plan/third-party-docs/podman/` exists and `BackendConfig.type` admits other values, but
M2b is backend-agnostic by construction: `LifecycleManager` is written against the
`ContainerBackend` protocol and never names a runtime. Nothing in this milestone makes the
Podman question harder or easier.
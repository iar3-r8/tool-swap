# The readiness probe seam

When a tool's container starts, there is a window in which the process
is not yet up, and a longer window in which the process is up but the
model weights are still loading and it cannot serve anything. During
that whole ramp-up, the router needs to be able to ask the tool two
separate questions: *is your process running yet?* and *are you
ready to take traffic yet?* This page documents the seam that makes
those two questions possible: the
[`Probe`](../src/tool_swap/proxy/probes.py:22) protocol, the
[`ProbeTarget`](../src/tool_swap/proxy/probes.py:37) address a probe
receives, and
[`FakeProbe`](../src/tool_swap/proxy/probes.py:53), the scripted
stand-in the tests drive instead of a real probe — all in
[`probes.py`](../src/tool_swap/proxy/probes.py).

Without a probe, the router has no way to move a tool past `STARTING`
or `LOADING`: to Docker the container is `running` the whole time, and
routing on container liveness alone would send requests into a process
that is still loading weights. The probe is what turns "the container
exists" into "the tool can serve". It is also a **seam, not an
implementation**: the protocol is the shape M3's real HTTP probe must
fit, and the tests pin that shape so M3 cannot redesign it.

**Where it sits:** the [backend seam
page](backend-seam.md) documents the layer that *starts* the
container; [the tool state machine page](tool-state-machine.md)
documents the six states the probe answers exist to move between.
The probe sits between the two: it is consumed by
[`drive_readiness`](../src/tool_swap/lifecycle/manager.py:75), the
first driver of the state machine, which polls it and applies the
`STARTING → LOADING → READY` transitions on its answers. The probe
itself knows nothing about containers, backends or states — it takes
an address and returns a `bool`.

One honest caveat before the detail: **no real probe exists in this
tree, and none can.** The repository declares no HTTP client at all,
and a guard test fails the suite if one is ever imported in this
module. What ships is the contract and the double; M3 ships the probe
that opens sockets.

## Status and design sources

**Status: slice C of M2b, shipped — the seam, not the probe.**
M2b is the project plan's milestone for the lifecycle layer, and
"slices A, B and C" are this branch family's shares of it: slice A
the [spec builder](spec-builder.md), slice B the
[state machine](tool-state-machine.md), slice C this seam plus the
progression that consumes it. The module is a declaration and a test
double: no socket, no HTTP client, no I/O. Its consumer,
`drive_readiness`, is shipped too — but the `LifecycleManager` class
that will own the seam in production arrives in slice D, and the
probe that answers with real HTTP arrives in M3.

The design is in
[`plans/m2b-lifecycle-manager.md`](../plans/m2b-lifecycle-manager.md):
[§1.5](../plans/m2b-lifecycle-manager.md:352) for the seam,
[D-B](../plans/m2b-lifecycle-manager.md:1152) for the no-client
decision, [§3 slice C](../plans/m2b-lifecycle-manager.md:689) for the
behaviour ledger, and [§6.11](../plans/m2b-lifecycle-manager.md:1367)
for the failure mode deliberately left unmodelled.

## The protocol: two questions, kept separate

```python
@runtime_checkable
class Probe(Protocol):
    async def health(self, target: ProbeTarget) -> bool: ...
    async def ready(self, target: ProbeTarget) -> bool: ...
```

Two methods rather than one, because the two questions are different
problems: `health` answers whether the process is up (the tool is
`STARTING`), `ready` answers whether it serves (the tool is
`LOADING`). "Ninety seconds in `LOADING`" is a very different incident
from "ninety seconds in `STARTING`" —
[`plan/01` §4](../plan/01_ARCHITECTURE.md:209) keeps the `/health`
versus `/ready` split precisely to keep those diagnoses apart, and a
single `is_ready` method would collapse the distinction the state
machine exists to express.

The other two shape decisions are `async` and `bool`:

- **Async**, because M3's probe will be async HTTP; declaring it now
  avoids an executor hop and a later signature change. This does not
  contradict the backend seam staying synchronous — the probe is a
  new seam of M2b's own, and the two coexist by design.
- **`bool`, not a status object**, because the driver owns the
  deadlines. A probe that returned a state would be a second state
  machine; a `false` answer plus a deadline is the whole contract.

`@runtime_checkable` matters beyond the pin: without it, the manager's
`isinstance` call raises `TypeError` far from the declaration site,
so the tests check the flag itself as well as the signatures.

## The address: `ProbeTarget`

```python
@dataclass(frozen=True, slots=True)
class ProbeTarget:
    tool: str
    host: str
    port: int
    health_path: str
    ready_path: str
```

The complete address of one tool, and **nothing else — no URL**,
because the probe composes the URL and this type owns no client; a
pre-composed URL would put HTTP vocabulary into a type that has no
transport. `host` is the **container name**, because tools are
addressed by name on the shared network (D21,
[`plan/01` §7](../plan/01_ARCHITECTURE.md:365)) — so the probe needs
neither config access nor container knowledge.

`frozen` and `slots` are load-bearing: without them a probe or the
manager could rewrite, or grow, the address mid-flight. The tests pin
the exact five-field set in declaration order, so a sixth field
appears nowhere it should not be visible.

The `health_path` and `ready_path` values resolve from your config —
the [Configuration
reference](configuration.md#defaults) documents the `health_path`,
`ready_path` and `probe_interval` keys; the defaults `/health` and
`/ready` live in
[`BUILT_IN_DEFAULTS`](../src/tool_swap/config/defaults.py:50).

## No HTTP client — enforced, not intended

The declared dependencies of this repository are `typer`, `pydantic`,
`pyyaml`, `python-dotenv`, `jsonschema` and `docker`
([`pyproject.toml`](../pyproject.toml)); `requests` exists only
transitively under `docker`, and importing it directly would be an
undeclared dependency. D-B therefore makes the probe **a seam with no
client**, and the rule is made executable rather than merely
documented:

- [`tests/unit/proxy/probe_guard.py`](../tests/unit/proxy/probe_guard.py)
  walks the **written** imports of `probes.py` as an AST and fails on
  `requests`, `httpx`, `urllib3` or `aiohttp` in any form — a plain
  import, a dotted import, a `from`-import or a runtime
  `__import__("...")`.
- Matching is on the **exact top-level package**, so `urllib.parse`
  and `requests_mock` are not flagged.
- The scan is static rather than a `sys.modules` check, because
  importing `docker` — a declared dependency, loaded by the backend
  tests in the same pytest process — puts `requests` into
  `sys.modules`, so a dynamic check would go red on a clean tree
  depending on test order.

The guard was verified against the real file, not only against
in-memory decoys: a planted `import requests` fails naming its line,
and the file is byte-identical after revert.

## The scripted double: `FakeProbe`

[`FakeProbe`](../src/tool_swap/proxy/probes.py:53) is what the manager
tests inject in place of a real probe. It answers each question from
a per-tool, per-phase script:

```python
FakeProbe(script={"t1": {"health": 2, "ready": 3}})
# health: false for the first 2 calls, then true and true thereafter
# ready:  false for the first 3 calls, then true and true thereafter
```

The three script shapes:

| Script value | Answer | Used to model |
|---|---|---|
| `0` | true immediately | a warm tool |
| `N > 0` | false for the first `N` calls, then true and true thereafter | a real `LOADING` window, or a slow start |
| `None` | never true | the "never ready" failure that drives the timeout paths |

A tool or phase **absent from the script answers true immediately**,
so a test that does not care about probing scripts nothing. The
`None` sentinel is the weak point of the mapping — it means both
"absent, so default true" and "scripted never true", and the
implementation disambiguates with an explicit membership check before
the read — and is recorded as the place to revisit if a fourth script
shape ever appears (plan §6.11 names M3's transport failure as the
likely one).

`FakeProbe` also carries a **call journal**: `probe.calls` is a list
of `(method, tool)` pairs in call order, recorded on entry and
including calls that answered `False`, so a hung phase is diagnosable
from how often the probe was asked. The name and the record-on-entry
purpose follow `FakeBackend.calls`; the entry shape deliberately does
not — it is the plan's pair, not the backend's triple.

`FakeProbe` never raises, it has no clock and no socket, and it
counts calls rather than wall time, so a deadline loop may poll it for
as long as the simulated deadline lasts.

## What this page does not claim

- **There is no real probe.** No socket is opened anywhere in this
  tree, and the no-HTTP guard makes it impossible to add one to this
  module without failing the suite. M3's probe implements `Probe`;
  this page documents the shape it must fit.
- **A probe that raises is not modelled.** A transport failure —
  connection refused, TLS error, a malformed response — is a real
  scenario, but its shape depends on the HTTP client M3 declares, and
  inventing it here would be an unverified claim about a dependency
  that does not exist. The plan records the hand-off: M3 must add
  that failure mode to `FakeProbe` alongside the real probe
  ([§6.11](../plans/m2b-lifecycle-manager.md:1367)).
- **The double is not a simulation of timing.** It answers by call
  count, not by elapsed time; the simulated time in the tests comes
  from the `ManualClock`, not from the probe.

## Where to go deeper

- [`docs/tool-state-machine.md`](tool-state-machine.md) — the states
  these answers move between, and `drive_readiness`, the first
  driver that polls this seam.
- [`docs/backend-seam.md`](backend-seam.md) — the `ContainerState`
  that asks a different question, and why `FakeBackend` deliberately
  has no "never ready" failure mode.
- [`plans/m2b-lifecycle-manager.md`](../plans/m2b-lifecycle-manager.md)
  — [§1.5](../plans/m2b-lifecycle-manager.md:352) for the seam's four
  shape decisions, [§3 slice C](../plans/m2b-lifecycle-manager.md:689)
  for the behaviour ledger, and
  [§6.11](../plans/m2b-lifecycle-manager.md:1367) for the unmodelled
  transport failure.
- [`plan/01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md) §4 — why
  `STARTING` and `LOADING` are distinct, and §7 (D21) for why tools
  are addressed by container name.

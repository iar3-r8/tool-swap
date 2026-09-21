# The container backend seam

Everything in this repository that starts, stops, inspects or lists a
tool's container goes through one interface: the `ContainerBackend`
protocol. This guide describes that seam — its data types, its naming
and labelling rules, its error taxonomy, and the boundary that keeps
the container runtime contained in one place.

**Status: both implementations of the seam are shipped.** The data
types, the helpers, the protocol declaration and the error taxonomy
are in the tree, and both protocol implementations are: the
in-memory `FakeBackend` (plan behaviours 10–13) and the Docker
backend, which landed in two slices on the same milestone branch —
the pure translation layer, behaviours 14–19
([`build_run_kwargs`](../src/tool_swap/backend/docker_backend.py:102)
and [`map_sdk_error`](../src/tool_swap/backend/docker_backend.py:275)),
and the [`DockerBackend`](../src/tool_swap/backend/docker_backend.py:746)
shell with the import-linter contract, behaviours 20–27. `isinstance(backend, ContainerBackend)`
is `True` for both, and "the only module that imports the Docker
SDK" is now enforced rather than hoped for. The layer **above** the
seam is documented on its own pages: the config to `ContainerSpec`
builder, M2b slice A, in [spec-builder.md](spec-builder.md), and the
M2b slice B tool state machine — `STOPPED`, `STARTING`, `LOADING`,
`READY`, `STOPPING`, `FAILED` — in
[tool-state-machine.md](tool-state-machine.md). This page documents
what is here, and says explicitly where it stops.

The design is specified in
[`plans/m2a-container-backend-seam.md`](../plans/m2a-container-backend-seam.md)
(§4 for the design, §5 for the behaviour ledger); the interface it
implements was first sketched in
[`plan/01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md) §12.

## The shape of the seam

```mermaid
flowchart LR
    subgraph cfg[config layer — ships in M1]
        VAL[validate.py: parse_mount and every TSWAP-C* judgement]
        DEF[defaults.py: BUILT_IN_DEFAULTS, the single source of truth for every built-in default]
    end
    subgraph seam[the seam — this page]
        TYPES[base.py: MountSpec, ContainerSpec, ContainerHandle, ContainerState, ContainerStatus]
        HELPER[labels.py: managed_labels, container_name, label_selector]
        PROTO[base.py: ContainerBackend protocol, six synchronous methods]
        ERR[errors.py: the seven-member error taxonomy]
        FAKE[fake_backend.py: FakeBackend, behaviours 10–13, importable with the SDK absent]
        DOCK[docker_backend.py: DockerBackend, behaviours 20–26 — the only module that may import the Docker SDK]
        DOCKT[docker_backend.py: build_run_kwargs and map_sdk_error, behaviours 14–19, the pure half]
    end
    subgraph lifc[lifecycle — M2b slices A and B, the layer above the seam]
        SPEC[spec_builder.py: build_container_spec, the config → ContainerSpec conversion]
        STATES[states.py: ToolState, ModelRuntimeState, the ten-edge transition table]
    end
    subgraph future[later branches and milestones — not shipped]
        LIFE[M2b slice D: LifecycleManager, the driver of the state machine]
        BLD[M5: build and BuildSpec]
    end
    VAL -->|ParsedMount| SPEC
    SPEC -->|produces| TYPES
    DEF -. "resolved values, passed in by callers" .-> HELPER
    TYPES --> PROTO
    HELPER --> PROTO
    PROTO -->|raises| ERR
    FAKE -->|implements| PROTO
    DOCK -->|implements| PROTO
    DOCK -->|calls| DOCKT
    DOCKT -->|reads| TYPES
    DOCKT -->|uses| HELPER
    DOCKT -->|returns members of| ERR
    LIFE -.->|will call off the event loop| PROTO
    BLD -.->|deliberately absent from the protocol| PROTO
```

Solid edges are shipped; dashed ones are named in the plan but not yet
in the tree. Both `FakeBackend` and `DockerBackend` sit inside the
seam's subgraph: the fake is in-memory and importable with the Docker
SDK absent; the Docker backend is the thin shell over its own pure
half `DOCKT` (plan §4.5) — `start` unpacks
[`build_run_kwargs`](../src/tool_swap/backend/docker_backend.py:102)'s
output into `create`, and every method routes exceptions through
[`map_sdk_error`](../src/tool_swap/backend/docker_backend.py:275) —
and it is the only module that may import the SDK (the fifth
`.importlinter` contract, behaviour 27). `SPEC` and `STATES` sit in
their own subgraph because both are M2b's layer **above** the seam,
not seam modules: `SPEC` produces the `ContainerSpec` the seam
consumes, from
[`parse_mount`](../src/tool_swap/config/validate.py:2488)'s
`ParsedMount`, and
[its page](spec-builder.md) documents the conversion and the two
refusals that keep it honest; `STATES` is the slice B tool state
machine, whose ten edges decide *when* a container should exist,
and [its page](tool-state-machine.md) documents the table, the
runtime-state holder and the logging contract.

## What is in the tree

The seam is five modules, all under `src/tool_swap/backend/`, plus
both implementations of the protocol:

| Module | Contents |
|---|---|
| [`base.py`](../src/tool_swap/backend/base.py) | [`MountSpec`](../src/tool_swap/backend/base.py:27), [`ContainerSpec`](../src/tool_swap/backend/base.py:49), [`ContainerHandle`](../src/tool_swap/backend/base.py:107), [`ContainerState`](../src/tool_swap/backend/base.py:129), [`ContainerStatus`](../src/tool_swap/backend/base.py:147), and the [`ContainerBackend`](../src/tool_swap/backend/base.py:171) protocol |
| [`labels.py`](../src/tool_swap/backend/labels.py) | [`managed_labels`](../src/tool_swap/backend/labels.py:54), [`container_name`](../src/tool_swap/backend/labels.py:111), [`label_selector`](../src/tool_swap/backend/labels.py:153) |
| [`errors.py`](../src/tool_swap/backend/errors.py) | the seven exception classes, [`BackendError`](../src/tool_swap/backend/errors.py:24) and its six concrete subclasses |
| [`fake_backend.py`](../src/tool_swap/backend/fake_backend.py) | [`FakeBackend`](../src/tool_swap/backend/fake_backend.py:77), the in-memory implementation, and [`FailureMode`](../src/tool_swap/backend/fake_backend.py:50) — the two scriptable failure modes |
| [`docker_backend.py`](../src/tool_swap/backend/docker_backend.py) | [`build_run_kwargs`](../src/tool_swap/backend/docker_backend.py:102) and [`map_sdk_error`](../src/tool_swap/backend/docker_backend.py:275) — the pure half, behaviours 14–19 — and [`DockerBackend`](../src/tool_swap/backend/docker_backend.py:746), the thin shell over them, behaviours 20–26 |

## The data types

### `MountSpec`

One **already-resolved** bind mount: a host `source` (a string), an
absolute container `target`, and a `read_only` flag that defaults to
`True` — a caller must ask for read-write explicitly. It performs no
parsing, no `~` expansion, no existence checks. It is the seam's unit
of mount, and it is hashable because M2b will key by spec fields.

### `ContainerSpec`

Everything needed to start one tool container, as fully resolved
input. Fifteen fields: the required `tool`, `name` and `image`; the
required-and-keyword-only `gpu_runtime` and `container_port`; and the
defaulted `command`, `env`, `labels`, `network`, `mounts`, `devices`,
`shm_size`, `cpus`, `memory` and `published_port`.

Two rules make this a *resolved* input rather than a mini-configuration:

- **No configured default is re-stated.** `gpu_runtime` and
  `container_port` have no field default at all — omitting either is a
  `TypeError` at construction. Every configured value arrives from the
  resolver; [`BUILT_IN_DEFAULTS`](../src/tool_swap/config/defaults.py:20)
  in the config layer remains the single named source of truth for
  their values. (Keyword-only on those two fields is mechanical: a
  dataclass cannot place a non-default field after a defaulted one.)
- **No policy.** There is no TTL, no group, no eviction. `devices=()`
  means CPU-only, and `published_port=None` means nothing is
  published to the host.

### `ContainerHandle`

One started container, identified by all four fields — `id`, `name`,
`tool`, `image` — **never by `id` alone**: a recreated container keeps
its name and tool while its runtime id changes. Handles are frozen and
hashable, and M2b keys its bookkeeping by them.

### `ContainerState`

Exactly four members — `created`, `running`, `exited`, `gone` — and
they describe one thing only: **whether a process exists**. This is
deliberately not the M2b tool state machine, which ships in slice B
([`ToolState`](../src/tool_swap/lifecycle/states.py:35), six
members, documented on
[its own page](tool-state-machine.md)): `STARTING`, `LOADING` and
`READY` are readiness concepts that a container can be `running`
while its tool is still not serving. The health probe that answers
them arrives in slice C. A test pins the four-member set, a second
pins the six-member set, and the two value sets are asserted
disjoint, so the two state machines cannot blur together.

### `ContainerStatus`

A point-in-time reading: the `handle`, its `state`, an `exit_code`
that stays `None` while the container is running (a running container
has not exited *successfully* — it has not exited at all), and a
`started_at` carried as the runtime's own string.

## The protocol

[`ContainerBackend`](../src/tool_swap/backend/base.py:171) is a
`@runtime_checkable` `Protocol` with exactly six **synchronous**
methods:

| Method | Signature | Note |
|---|---|---|
| `start` | `(spec: ContainerSpec) -> ContainerHandle` | raises on failure; the error is a taxonomy member |
| `stop` | `(handle, *, timeout_s: float) -> None` | a no-op if the container is gone |
| `is_running` | `(handle) -> bool` | `False` for a missing container, never an exception |
| `inspect` | `(handle) -> ContainerStatus` | returns `ContainerState.GONE` when the container is gone |
| `list_managed` | `() -> list[ContainerHandle]` | stopped containers included |
| `logs` | `(handle, *, follow: bool, tail: int) -> Iterator[str]` | raises on an unknown handle |

Decisions worth knowing, each pinned by the protocol's tests:

- **Synchronous.** The Docker SDK is blocking; M2b's `LifecycleManager`
  is the async layer that off-loads these calls. Making the seam async
  would hide that inside the driver.
- **`build` is absent.** [`plan/01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md) §12
  lists it on the protocol; this branch deliberately does not include
  it. It is M5's concern, and issue #3's Definition of Done names
  exactly the six methods above, without it. Including it now would
  force both future implementations to carry a stub.
- **`inspect` returns `ContainerStatus`, never a raw SDK dict.** The
  seam exists to contain the runtime's vocabulary, not leak it.
- **`stop` and `logs` take keyword-only arguments**, so the call sites
  read unambiguously.

## The boundary

The seam's value is as much in what it refuses to do.

- **No mount-string parsing.**
  [`parse_mount`](../src/tool_swap/config/validate.py:2488) in the
  config layer is the repository's only mount-string parser. Mode
  legality, container-path absoluteness and host-path existence are
  the config layer's rules (`TSWAP-C541`, `TSWAP-C542`, `TSWAP-C543`);
  re-doing any of them in the backend is exactly the duplication the
  seam was amended to prevent. A source-level guard test walks
  `src/tool_swap/backend/` on every run and fails if a second parser
  appears — and since M2b slice A, a second guard walks
  `src/tool_swap/lifecycle/` for the same reason. The single
  `ParsedMount` → `MountSpec` conversion happens in the
  config-to-spec builder,
  [`build_container_spec`](../src/tool_swap/lifecycle/spec_builder.py:19),
  which **does ship** — it is in the tree, it has no caller yet
  (the `LifecycleManager` is M2b slice D), and
  [its page](spec-builder.md) documents the conversion, the
  resolution base and the two source-level guards.
- **No configured default is re-stated.** `gpu_runtime`,
  `container_port`, `label_namespace` and `container_prefix` all live
  in [`BUILT_IN_DEFAULTS`](../src/tool_swap/config/defaults.py:20);
  the helpers below take them as **required arguments** and a guard
  test fails if a literal value reappears in `labels.py`.
- **No policy.** No TTL, no group, no eviction, no readiness. The
  backend knows whether a process exists; everything above that is
  M2b's.
- **One runtime import, one module — enforced.**
  [`docker_backend.py`](../src/tool_swap/backend/docker_backend.py)
  is the only module under `src/` that imports the Docker SDK. The
  fifth contract in
  [`.importlinter`](../.importlinter) — "The docker SDK is importable
  from one module only" — forbids `docker` from every `tool_swap`
  module and carves out exactly
  `tool_swap.backend.docker_backend -> docker`
  ([`.importlinter`](../.importlinter:39)); `lint-imports` reports
  **5 kept, 0 broken**. The other four contracts keep the router and
  runtime apart and the config layer a leaf that never imports the
  backend. The mechanism has two teeth, documented in detail in
  [The import boundary](#the-import-boundary-behaviour-27): without
  the top-level `include_external_packages` the contract would raise
  a configuration error rather than check anything, and its
  `ignore_imports` carve-out is self-policing — an expression that
  matches no real import is an error, not a silent no-op.

## Names and labels

### Container names

`container_name(prefix, tool)` returns `prefix + tool`. Both the tool
name and the whole concatenation must match
`[a-z0-9][a-z0-9_-]*` — the same rule the config layer applies to tool
names under `TSWAP-C210`
([`validate.py`](../src/tool_swap/config/validate.py:310)). That rule
is a strict subset of what Docker accepts, so every name the function
accepts is one Docker accepts; the repository has deliberately not
claimed Docker's own charset, which it has not verified, and **no
length limit is applied**. The prefix is the only input no config
rule checks, so an unusable name names the prefix in its `ValueError`.

### Labels

Every managed container carries a label set produced by
`managed_labels(namespace, tool, ...)`, keyed in the namespace the
caller supplies:

| Label | When present |
|---|---|
| `{namespace}.model` | always — the tool name |
| `{namespace}.managed-by` | always — the value is the constant `tool-swap` |
| `{namespace}.group` | only when a group is given |
| `{namespace}.config-hash` | only when a hash is given (nothing in the repository computes one yet) |
| `{namespace}.runtime-version` | only when a version is given |

An omitted optional omits its key entirely — an empty label value
would be a silent reconciliation mismatch. The `managed-by` value is
a constant independent of the namespace, on purpose: reconciliation,
`tswap ps`, `prune` and staleness detection all key off these labels,
so a value stable across namespace changes keeps containers labelled
under an older namespace recognisable as ours.

`label_selector(namespace)` returns exactly one entry — the
`managed-by` key for that namespace — and it is a **neutral label map,
not a docker filter**: the translation into the SDK's
`filters={"label": "key=value"}` form happens in
[`list_managed`](../src/tool_swap/backend/docker_backend.py:1198)
(behaviour 25), derived by *calling* `label_selector` with the
resolved namespace rather than restating the entry, so the filter
cannot drift from the map the containers were stamped with. Whether
the daemon's selector really selects is not claimed — the SDK does no
client-side interpretation of filters; that is deferred docker test 1.

## The `FakeBackend`

The first implementation of the protocol, in
[`fake_backend.py`](../src/tool_swap/backend/fake_backend.py)
(behaviours 10–13). It is a **test double, not a simulation**: state is
a plain dict of per-container records guarded by a single
`threading.Lock`, no thread is ever spawned and no I/O happens. It is
importable with the Docker SDK absent and asserts no docker fact — it
exists so a test can drive seam behaviour with no daemon.

### How a test drives it

```python
from tool_swap.backend.fake_backend import FakeBackend, FailureMode

backend = FakeBackend(script={"t1": FailureMode.FAIL_TO_START})
```

- `script` is a **tool-name → `FailureMode`** mapping, applied at
  `start` time, so a failure is scripted before any handle exists.
  `FAIL_TO_START` makes that tool's start refuse with
  [`ContainerStartError`](../src/tool_swap/backend/errors.py:97),
  repeatedly and without creating a record — the script is not
  one-shot, so a retry loop can never silently succeed.
  `DIE_AFTER_START` is a death, not a refusal: the start succeeds and
  returns a handle, but the record is created already `EXITED` with a
  non-zero exit code, so the container is dead by the first
  observation.
- **`vanish(handle)` and `seed_logs(handle, lines)` are test control,
  not seam surface.** They sit below a separator comment in the
  source, they are never journaled, and they are not
  `ContainerBackend` members: `LifecycleManager` and every other seam
  consumer must never call them. `vanish` removes a record out of
  band — the in-memory stand-in for a `docker rm -f` behind the
  backend's back — and `seed_logs` appends lines to the per-handle
  buffer that `logs` reads. Both raise
  [`ContainerNotFoundError`](../src/tool_swap/backend/errors.py:106)
  for an unmanaged handle, because both are active operations naming a
  container that may not exist.
- **`backend.calls`** journals every protocol call on entry as a
  `(name, args, kwargs)` triple — including calls that raise, since a
  losing racer's refused start leaves no trace in `list_managed` — so
  M2b can assert "exactly one start" by counting attempts. Test
  control never reaches the journal, so counts depend only on what a
  seam consumer called.

### What it models — and what it cannot

- **Dead versus vanished.** A dead or stopped container stays in
  `list_managed`; only a vanished one disappears. That is deliberate:
  reconciliation adopts by label, and M2b must still see a dead
  handle to mark the tool `FAILED` (plan §6 item 5).
- **`follow=True` returns a terminating snapshot**, because the fake
  has no stream to follow and blocking would hang a caller that never
  stops it. `tail` is pure list semantics: `tail=0` yields nothing, a
  `tail` past the buffer returns everything, and a stopped
  container's buffer survives `stop`.
- **`started_at` stays `None`** for the fake's whole life: it has no
  runtime clock to report from, and inventing a timestamp would be a
  fake docker fact.

### Four contracts exist for M2b, not for M2a

Each would look like over-engineering from M2a's side alone; plan §6
is the point of reference:

1. **The journal records on entry**, so a call that raises is still
   counted (plan §6 item 2).
2. **`is_running` returns `False` for a missing container rather than
   raising**, so M2b's liveness sweep is not an unhandled traceback in
   the watchdog (plan §6 item 4).
3. **The internals are lock-guarded**, because M2b's coalescing test
   drives the fake concurrently (plan §6 item 2).
4. **`vanish()` and `DIE_AFTER_START`** make "a vanished container
   becomes `FAILED`" testable with no daemon (plan §6 item 3).

### `FailureMode` has exactly two members

`STOP_HANGS` is **not a mode in this milestone**: it existed only for
M2b's drain test, and shipping a member no test proves would be
dead code — M2b introduces it in the same red/green cycle as that
test (plan §7 item 5). **"Never ready" is deliberately not a mode
either**: readiness belongs to M2b's health probe, which does not
exist yet, and the fake has no probe to be un-ready against. That is a
knowing departure from issue #3's Scope wording, confirmed by the
user and recorded in plan §7 item 5 — the issue was not amended, so
that plan entry is the record.

## When the container is gone

The protocol's not-found contract (plan §4.3), which M2b's liveness
sweep relies on:

| Method | Missing container |
|---|---|
| `is_running` | returns `False` — never raises |
| `inspect` | returns `ContainerState.GONE` with `exit_code=None` |
| `stop` | a no-op |
| `start`, `list_managed`, `logs` | raise a taxonomy member |

Both implementations honour the contract exactly. `FakeBackend`
makes it testable: `vanish` a running handle and the three lenient
reads behave as the table says without a daemon.
`DockerBackend` reaches it through one shared lookup
([`_fetch_container`](../src/tool_swap/backend/docker_backend.py:798)),
which turns only the SDK's `NotFound` into "missing" — every other
lookup failure is routed through
[`map_sdk_error`](../src/tool_swap/backend/docker_backend.py:275)
and raised. **The asymmetry is deliberate, and a dead daemon is never
treated as not-found:** a missing container is *state*, an
unreachable daemon is *availability*. Swallowing the latter would let
M2b's liveness sweep reap containers that are alive behind an
unreachable daemon, so `is_running`'s `False`, `inspect`'s `GONE`
and `stop`'s no-op all apply to *state* only — a dead daemon
surfaces [`BackendUnavailableError`](../src/tool_swap/backend/errors.py:70)
instead. And the contract is not symmetric the other way: `logs`
**raises** [`ContainerNotFoundError`](../src/tool_swap/backend/errors.py:106)
for a vanished container, eagerly on the call rather than on the
first `next()` — the one place in the slice where fake and docker
parity means *both raise*.

## The Docker translation layer (behaviours 14–19)

The pure half of the Docker backend: two functions in
[`docker_backend.py`](../src/tool_swap/backend/docker_backend.py),
no class, no client, no daemon round-trip. The design is plan §4.5:
the `DockerBackend` shell is deliberately **thin**, so the
interesting logic — every kwarg name, every error classification —
lives in functions testable exhaustively with no daemon. That is why
a backend that talks to Docker is testable with Docker absent: 68
tests for the pure layer, 78 more for the shell and the boundary
(behaviours 20–27, documented below).

Two things a reader must know before the tables:

- **The shell consumes these functions.**
  [`DockerBackend.start`](../src/tool_swap/backend/docker_backend.py:853)
  unpacks `build_run_kwargs`'s output into `create`, and every method
  routes its exceptions through `map_sdk_error` — which is why the
  shell's tests can assert equality against the pure function's
  output rather than against a dict invented in the same diff.
- **Nothing here was verified against a running daemon.** Every
  docker-py fact is pinned against the installed docker 7.2.0's own
  source and its own classifier, and cited in the function
  docstrings from
  [`plan/third-party-docs/docker/`](../plan/third-party-docs/docker/INDEX.md).
  M2a runs no docker tests — see the deferred note in the
  troubleshooting section below.

### `build_run_kwargs` — spec to `containers.create` kwargs

[`build_run_kwargs(spec, *, label_namespace)`](../src/tool_swap/backend/docker_backend.py:102)
reads a [`ContainerSpec`](../src/tool_swap/backend/base.py:49) and
nothing else — no client, no daemon, no environment — and returns a
fresh dict for `client.containers.create(**kwargs)`. The keys it
emits, and when:

| Key | Emitted when | Value |
|---|---|---|
| `image` | always | `spec.image`; an empty image raises `ValueError` before any SDK call |
| `name` | always | `spec.name` |
| `labels` | always | the full [`managed_labels`](../src/tool_swap/backend/labels.py:54) set for the namespace and tool, with `spec.labels` merged in — spec labels win a collision |
| `environment` | `spec.env` is non-empty | a plain dict copy of the spec's mapping |
| `network` | `spec.network is not None` | the network name — the SDK also turns it into `network_mode` internally, so this function never emits `network_mode` |
| `volumes` | `spec.mounts` is non-empty | `{source: {"bind": target, "mode": "ro" or "rw"}}` in declaration order, no de-duplication (that is config-validation's job) |
| `device_requests` | `spec.devices` is non-empty | one `DeviceRequest(driver=spec.gpu_runtime, device_ids=[...])` — indices as strings in declaration order, duplicates collapsed; `count` is never set; a negative index raises `ValueError` |
| `nano_cpus` | `spec.cpus is not None` | `round(spec.cpus * 1e9)` — an int in units of 1e-9 CPUs; no `cpu_quota`/`cpu_period` pair |
| `mem_limit` | `spec.memory is not None` | the size string, passed through verbatim |
| `shm_size` | `spec.shm_size is not None` | the size string, passed through verbatim |
| `ports` | `spec.published_port is not None` | `{container_port: published_port}` — the container port is the **key**; a non-positive port raises `ValueError`; no range check (range policy is config validation's) |

Every name is cited from
[`containers-run-create.md`](../plan/third-party-docs/docker/containers-run-create.md)
§2 and its routing table, and the device-request shape from
[`gpu-device-requests.md`](../plan/third-party-docs/docker/gpu-device-requests.md)
§1–§2. Two consequences worth knowing:

- **The start path is `create` + `start`, not `run(detach=True)`.**
  `run` returns before any exit check — hiding an immediate crash —
  and auto-pulls a missing image, so an `ImageNotFound` might never
  surface. The image must therefore pre-exist, and a missing one is
  an honest [`ImageNotFoundError`](../src/tool_swap/backend/errors.py:79)
  rather than a silent multi-gigabyte pull. Hence no `detach` key in
  the output (plan §5 behaviour 14, amended).
- **A typo'd kwarg name is a client-side `TypeError`**: the SDK's
  routing accepts only the names in its two kwarg tables and raises
  on anything else, so the snapshot tests pin the whole kwarg
  surface with no daemon.

### `map_sdk_error` — SDK exception to taxonomy

[`map_sdk_error(exc)`](../src/tool_swap/backend/docker_backend.py:275)
reads an exception — or anything else — and **returns** a member of
the seven-member taxonomy for the caller to raise. Pure and total:
it never raises, so no raw SDK exception escapes the seam, and every
returned member carries a distinctive part of the input's text, so
the original is never swallowed. A genuine exception is chained as
`__cause__`; a non-exception input cannot be chained — CPython
allows an exception's `__cause__` to be only `None` or a
`BaseException` — so for that one input the text is preserved in the
message instead.

The branches are **ordered and must stay ordered**: `APIError`
inherits `requests.exceptions.HTTPError`, so a broad `requests`
check placed first would swallow every API error.

| Order | Input | Maps to |
|---|---|---|
| 1 | an `APIError` 404, re-classified by the **daemon's text** | image fragments in the text → [`ImageNotFoundError`](../src/tool_swap/backend/errors.py:79) naming the image ref; any other 404 → [`ContainerNotFoundError`](../src/tool_swap/backend/errors.py:106) |
| 2 | an `APIError` 409 whose text is the daemon's name-conflict phrase | [`ContainerNameConflictError`](../src/tool_swap/backend/errors.py:88) naming the conflicting name |
| 3 | an `APIError` whose text matches `nvidia` or `gpu`, case-insensitively | [`GpuUnavailableError`](../src/tool_swap/backend/errors.py:115) — brittle, see below |
| 4 | any other `APIError` | [`ContainerStartError`](../src/tool_swap/backend/errors.py:97) carrying the daemon's text |
| 5 | a bare `requests` connection error (`ConnectTimeout` included) | [`BackendUnavailableError`](../src/tool_swap/backend/errors.py:70) |
| 6 | a `DockerException` "Error while fetching server API version: …" — the client-construction path | [`BackendUnavailableError`](../src/tool_swap/backend/errors.py:70) |
| 7 | anything else — an unrelated `DockerException` included, and a non-exception input | [`BackendError`](../src/tool_swap/backend/errors.py:24) fallback, preserving the text |

Each branch is cited from
[`errors.md`](../plan/third-party-docs/docker/errors.md): §1 for the
hierarchy (`APIError` **is** a `requests` `HTTPError`), §2 for the
404 mapping — the SDK classifies 404s by **string-matching the
daemon's message** and degrades to the parent `NotFound` when the
wording stops matching, which is why the re-classification is done on
the *text* rather than on which class the SDK chose — and §3 for the
two distinct dead-daemon hierarchies (operational calls surface a
bare `requests` error; client construction wraps one in a
`DockerException`).

### Two things documented as knowingly brittle

These are brittle by necessity, not interfaces:

- **`GpuUnavailableError` rests on a message heuristic** (plan §7
  item 12). The SDK has no GPU exception class — an unsatisfiable
  device request surfaces as a bare `APIError` — so the mapping
  matches `nvidia`/`gpu` in the daemon's text, which is the only
  channel that exists. The daemon's real wording is recorded nowhere
  and could not be observed in this environment, so the heuristic is
  **untested against reality**; the deferred daemon tests are where
  it would be confirmed. If it proves wrong, the failure mode is
  mild: a GPU refusal surfaces as
  [`ContainerStartError`](../src/tool_swap/backend/errors.py:97)
  with the daemon's text intact — the operator still sees the real
  message, only with a less specific remedy.
- **An authored size string like `16zz` is validated by nothing**
  (plan §7 item 11). No config rule covers it —
  [`schema.py`](../src/tool_swap/config/schema.py:150) types
  `memory` and `shm_size` as plain strings — and
  `build_run_kwargs` deliberately ships no parser of its own,
  because the SDK's `HostConfig` already owns that parsing: its
  `parse_bytes` raises the canonical message naming the accepted
  suffixes, as a `DockerException` rather than a `ValueError`. So an
  invalid string passes validation, passes the translation
  untouched, and fails at the daemon call with the SDK's message —
  not a `TSWAP-C5xx` one naming the file and line. A size-string
  rule in the config layer would be the better fix; it belongs there
  and is not part of this milestone.

## The `DockerBackend` shell (behaviours 20–26)

The second slice of the Docker backend is in the tree:
[`DockerBackend`](../src/tool_swap/backend/docker_backend.py:746),
the thin shell plan §4.5 designed — six protocol methods that are
call pairs over an injected client, each routing every exception
through [`map_sdk_error`](../src/tool_swap/backend/docker_backend.py:275)
so no raw SDK exception escapes the seam. The client protocol was
grown one behaviour at a time — `create`, then `get`, `status`,
`stop`, then `attrs`, then `list`, `name`, `labels`, then
`logs` — and never invented, so it describes exactly what the seam
touches and nothing speculative. `isinstance(backend, ContainerBackend)`
is `True`; the pin lives in behaviour 26's tests, where the last
protocol member lands, so no `NotImplementedError` placeholders were
ever shipped.

### The constructor is a guardrail

[`DockerBackend.__init__`](../src/tool_swap/backend/docker_backend.py:756)
takes an **already-built client** and stores exactly that object —
identity-wise, per behaviour 20's tests. It reads no environment
variable and no `~/.docker/config.json`;
[`from_config`](../src/tool_swap/backend/docker_backend.py:1489)
is the only path that builds a real one, via `docker.from_env()` —
and `from_config` is **not exercised by the unit suite** (it would
need a daemon). That split is what makes the whole backend
testable with no daemon, and it is pinned by a named regression
guard, not a convention: behaviour 20's guard test
([`test_docker_backend_ambient_env_guard.py`](../tests/unit/backend/test_docker_backend_ambient_env_guard.py))
poisons **six** SDK entry points — `docker.from_env`,
`docker.DockerClient.from_env`, `docker.from_context`,
`docker.DockerClient.from_context`, plus the
`DockerClient.__init__` and `APIClient.__init__` constructors — and
constructs and uses the backend under the poison. Six, not four,
because `docker.from_env` is a module-level alias bound *at import
time*, a distinct binding from the classmethod of the same name: a
guard patching only one half of the pair is the under-patched
version, and the test's in-memory decoys catch each half
independently. The guard proves the poison live before the subject
runs, so a silently-missed patch fails the verification step, not
the subject. Constructing with `None` as the client raises
`TypeError` — a programming error refused loudly rather than let
through to an SDK call.

### The six methods

Each method is thin by design: the tests assert call *shape* — who
is called, how many times, with what object — and derived equality
against the pure layer's output, never a restated dict.

| Method | The call pair | What a reader must know |
|---|---|---|
| [`start`](../src/tool_swap/backend/docker_backend.py:853) | `create(**build_run_kwargs(spec))`, then `start()` on the returned container, then a handle with the stub's `id` plus the spec's `name`/`tool`/`image` | **No `run` call — and none may be added.** `run(detach=True)` returns before any exit check and auto-pulls a missing image, which would stop `ImageNotFoundError` from ever surfacing. No post-start `reload()` either: M2a claims nothing about detecting an immediate death; liveness is M2b's sweep. |
| [`stop`](../src/tool_swap/backend/docker_backend.py:907) | shared lookup, then `stop(timeout=round(timeout_s))` | Not-found and already-exited are no-ops (§4.3). The zero-timeout trap: `timeout_s` is passed **unconditionally** — the API layer drops the parameter only on a strict `is None` check, so a falsy drop of `0` would let the daemon's own `StopTimeout` apply instead of the requested immediate stop. |
| [`is_running`](../src/tool_swap/backend/docker_backend.py:993) | shared lookup, then `status == "running"` | Only the running state is `True`; **every other state, including an unrecognised one, is `False`**. The daemon's `status` vocabulary is an *open* set — no SDK line enumerates it — so the comparison is positive, not a membership test: an unrecognised value must read `False` (the safe direction for a liveness sweep that reaps what it believes is dead), never raise or read `True`. |
| [`inspect`](../src/tool_swap/backend/docker_backend.py:1054) | shared lookup, then `status` plus two `attrs` reads | See the [INFERRED paths](#two-attribute-paths-rest-on-the-engine-api-not-on-sdk-source) below. An unrecognised state maps to `EXITED` with a logged warning rather than raising; `exit_code` is read **only when the daemon literally reports `exited`** — a running container has not exited, and passing its `0` through would report a clean exit that never happened. |
| [`list_managed`](../src/tool_swap/backend/docker_backend.py:1198) | `list(all=True, filters={"label": "key=value"}, ignore_removed=True)` | Stopped containers included (reconciliation must see an exited one). **`tool` comes from the `{namespace}.model` label, never parsed from the name**: the name is `prefix + tool`, and a container started under a different prefix would parse to the wrong tool — reconciliation adopts by label, so a name-derived tool would be reconciled against the wrong entry. A container carrying the managed-by label but no model label is skipped with a warning naming it by name and id — one malformed container must not deny the caller the rest. Returning `[]` for a daemon failure would read an outage as "nothing is managed", so daemon errors raise instead. |
| [`logs`](../src/tool_swap/backend/docker_backend.py:1364) | shared lookup, then `logs(stream=True, follow=follow, tail=tail)`, reassembled by [`_iter_log_lines`](../src/tool_swap/backend/docker_backend.py:569) | The byte chunks the daemon frames are reassembled into decoded lines: the SDK yields `bytes` whose boundaries fall wherever the daemon's frames fall — routinely *inside* a line — so each chunk is split on `b"\n"` only, decoded with `errors="replace"`, and a trailing partial line is flushed at stream end rather than dropped. `follow` is passed **explicitly, never omitted**: the SDK defaults an omitted `follow` to `stream`, so omitting it would turn a `follow=False` request into a stream that follows forever. `tail` is passed verbatim, `0` included — the SDK silently resets only *invalid* values to `'all'`, which is unbounded. |

`start` and every lookup-based method share
[`_fetch_container`](../src/tool_swap/backend/docker_backend.py:798):
`client.containers.get` — the saved single-container fetch, a full
inspect — with `NotFound` the only failure treated as *state*
(returns `None`); every other failure routes through
`map_sdk_error`. The catch is deliberately scoped to
`docker.errors.NotFound`, **not** a blanket `except Exception`: a
dead daemon surfaces from that call as a bare `requests` connection
error and must raise, never masquerade as an absent container.

### Two attribute paths rest on the Engine API, not on SDK source

`inspect`'s `exit_code` and `started_at` are read from
`attrs["State"]["ExitCode"]` and `attrs["State"]["StartedAt"]`,
and both keys are **[INFERRED]**, not [READ]:

- `ExitCode` — the string appears **once** in the installed
  package, and that one occurrence belongs to `exec_inspect` (an
  *exec* result, not a container inspect);
- `StartedAt` — **zero** matches anywhere in the installed package.

So the paths rest on the Engine API's `ContainerInspect` contract,
not on SDK source, and the deferred daemon test is what would
confirm them. The consequence for the tests is the honest one: the
[`inspect` tests](../tests/unit/backend/test_docker_backend_inspect.py)
feed the stub canned attribute dicts, so they **prove only that the
code reads the keys the fixture wrote** — they would pass unchanged
against a wrong key name. They are anti-drift pins, worth having,
and their docstrings say exactly what they rest on; promoting them
to [READ] is possible only by one live-daemon inspect. The one
exit-code route that *does* have SDK code behind it —
`wait()["StatusCode"]` — was rejected deliberately: `wait()`
**blocks until the container exits**, unbounded for a running
container, and an `inspect` built on it would hang M2b's liveness
poller on every healthy container. The stub in the tests exposes
no `wait` member, so a blocking implementation fails loudly here
rather than passing on a daemon the suite never runs.

`list_managed`'s `image` field is [INFERRED] on the same ground:
`attrs["Config"]["Image"]` is the Engine-API sibling of the [READ]
`Config.Labels` read the `labels` property already performs, and no
saved page records an SDK image property — the stub deliberately
exposes no `image` member so an unrecorded property fails loudly
here instead of passing on memory.

### What M2a does not claim

Nothing in this section was verified against a running daemon, and
the tests say so in their own text. What the stub tests show is the
call shape, the error routing and the not-found contract over
synthesised responses; what they do not show — the daemon's label
selector really selecting (deferred docker test 1), `stop`'s
return-before-exit (deferred test 2), the `State.ExitCode` /
`State.StartedAt` paths (one live-daemon inspect) — is recorded
rather than papered over. The `docker` marker is registered and
deselected by default, and no test in the tree carries it.

## The import boundary (behaviour 27)

The fifth contract in
[`.importlinter`](../.importlinter:39) — *"The docker SDK is
importable from one module only"* — is what makes
[`docker_backend.py`](../src/tool_swap/backend/docker_backend.py)
being the only SDK-importing module **enforced rather than hoped
for**. `lint-imports` reports **5 kept, 0 broken**; a test runs the
tool and asserts the summary line, and shape-pinning tests parse
the shipped file so the contract cannot drift silently.

Two mechanism facts are worth knowing, because both are load-bearing
and neither is obvious:

- **The contract needs `include_external_packages` or it checks
  nothing.** A `forbidden` contract naming an external module
  (`docker`, not a subpackage — import-linter rejects those) is
  only legal when the top-level session sets
  [`include_external_packages = true`](../.importlinter:5)
  (import-linter 2.13, `contracts/forbidden.py`): without it the
  external module is not in the graph at all, so the contract would
  have nothing to check — and `check()` refuses to run, raising a
  `ValueError` about the *configuration* rather than passing
  vacuously. The session option is pinned by a test for exactly
  that reason — a config that names an external module without the
  option is the broken version of behaviour 27.
- **The `ignore_imports` carve-out is self-policing.** The
  permitted edge is carved out with
  [`ignore_imports = tool_swap.backend.docker_backend -> docker`](../.importlinter:44).
  import-linter's `unmatched_ignore_imports_alerting` defaults to
  `error`: an expression matching **no real import** is an error at
  check time, not a silent no-op — so a rename that orphans the
  carve-out breaks `lint-imports` rather than quietly enforcing
  nothing. And dropping the line makes the contract break on the
  real, permitted edge — the non-vacuity test proves that
  differential in memory, without writing anything under `src/`.

The behavioural half of the boundary: `base`, `labels` and
`fake_backend` must import — and `FakeBackend()` must construct —
with the SDK blocked from the import system
([`test_docker_sdk_boundary.py`](../tests/unit/test_docker_sdk_boundary.py)).
The blocker is a `sys.meta_path` finder, not a `sys.modules`
deletion — deleting the already-loaded `docker*` entries is not
enough, because a fresh import would simply find the SDK again on
the path. The fake stays usable in an environment with no SDK
installed at all, which is what it exists for.

## Troubleshooting: container start failures

Each failure the backend can report is one of the seven classes in
[`errors.py`](../src/tool_swap/backend/errors.py), and each carries
its remedy in the string that M2b surfaces in `/status`. The table
is keyed by the class name; "it means" states how
[`map_sdk_error`](../src/tool_swap/backend/docker_backend.py:275)
reaches the class — which SDK condition, and by what signal, because
for several of the seven the decision is made on the daemon's
*text*, not on the SDK's class — and "surfaces from" names the
method(s) a caller meets it in, because every taxonomy member is now
reachable from a named method and condition:

| Error class | It means — and what produces it | Surfaces from | Remedy, as shipped in the class |
|---|---|---|---|
| [`BackendUnavailableError`](../src/tool_swap/backend/errors.py:70) | the container daemon is unreachable — either a bare `requests` connection error from an operational call, or the `DockerException` "Error while fetching server API version: …" from client construction (the two dead-daemon hierarchies of [`errors.md`](../plan/third-party-docs/docker/errors.md) §3) | **all six methods** — a dead daemon during any call routes through the shared lookup or the method's own catch; never read as a missing container | check that the daemon is running and reachable, and that `DOCKER_HOST` names the daemon tool-swap is configured to use |
| [`ImageNotFoundError`](../src/tool_swap/backend/errors.py:79) | the image reference does not exist — a 404 whose daemon text carries one of the image fragments, whatever class the SDK chose: the SDK string-matches the daemon's message and degrades an `ImageNotFound` to a plain `NotFound` when the wording stops matching, so the text, not the class, decides ([`errors.md`](../plan/third-party-docs/docker/errors.md) §2) | `start` (the `create` call) | build the image with `tswap build <tool>`* |
| [`ContainerNameConflictError`](../src/tool_swap/backend/errors.py:88) | the container name is already taken — a 409 whose daemon text is the name-conflict phrase, quoted around the name; any other 409 is a refused start | `start` (the `create` call) | free the name with `tswap down`* |
| [`ContainerStartError`](../src/tool_swap/backend/errors.py:97) | the daemon refused the start for another reason — any other `APIError`, including a GPU refusal whose text does not match the heuristic | `start` (the `create` or `start` call) | read the underlying error text in the message |
| [`ContainerNotFoundError`](../src/tool_swap/backend/errors.py:106) | the container was removed out of band, outside tool-swap's control — any 404 whose daemon text carries no image fragment | `logs` — raised **eagerly on the call** for a vanished container, not on the first `next()`; the three lenient methods instead treat the same 404 as *state* (`False` / `GONE` / no-op) and do not raise it | start the tool again |
| [`GpuUnavailableError`](../src/tool_swap/backend/errors.py:115) | a GPU device request could not be satisfied — **a message heuristic, not a stable interface**: an `APIError` whose text matches `nvidia` or `gpu`, case-insensitively (the SDK has no GPU exception class); the daemon's real wording is unverified, plan §7 item 12 | `start` (a device request refused at `create` time) | install or repair the NVIDIA container toolkit |
| [`BackendError`](../src/tool_swap/backend/errors.py:24) | fallback for an unrecognised runtime exception — any other SDK exception (an unrelated `DockerException` included) or a non-exception input at the seam, the original text always preserved | any of the six (the mapping's last branch) | inspect the underlying error text; report it if it does not match a known error |

\* **Forward reference.** `tswap build` and `tswap down` are quoted
from the plan's CLI design (plan §4.3) and do not ship yet; the CLI
today offers `validate`, `config show` and `version`
([`cli/main.py`](../src/tool_swap/cli/main.py)).

Two honest limits on the table:

- **Which of these a real daemon raises has not been verified
  here.** M2a runs no daemon tests: the `docker` marker is
  registered and deselected by default through `addopts`, and no
  test in the tree carries it. The mapping itself is in the tree —
  [`map_sdk_error`](../src/tool_swap/backend/docker_backend.py:275),
  behaviour 19 — and it is verified against the installed SDK's own
  source and its own classifier, but only over **synthesised
  exception instances**, never against a running daemon; the
  daemon-text branches in particular (the 404 re-classification, the
  name-conflict phrase, the GPU heuristic) encode wording the
  repository has not been able to observe. The two implementations
  *raise* different subsets today:
  [`DockerBackend`](../src/tool_swap/backend/docker_backend.py:746)
  routes every SDK exception through the mapping, so all seven are
  reachable from it — its unit tests drive the methods with stub
  clients that raise those synthesised instances;
  [`FakeBackend`](../src/tool_swap/backend/fake_backend.py:77)
  raises three of the seven for unit tests without a daemon:
  [`ContainerStartError`](../src/tool_swap/backend/errors.py:97)
  (`FAIL_TO_START` scripted on a tool name),
  [`ContainerNameConflictError`](../src/tool_swap/backend/errors.py:88)
  (starting an already-managed name) and
  [`ContainerNotFoundError`](../src/tool_swap/backend/errors.py:106)
  (`vanish` out-of-band, then `logs` the gone handle).
- **The daemon behaviour itself is deferred.** The three daemon tests
  of
  [`plans/m2-docker-testing-recommendation.md`](../plans/m2-docker-testing-recommendation.md)
  §3 — round trip, stop escalation, the vanished container — are
  planned, not yet in the tree; when they land they will be marked
  `docker` and will run **only** against a disposable daemon named by
  the environment variable `TSWAP_TEST_DOCKER_HOST`, skipping rather
  than touching the ambient daemon when it is unset.
  `TSWAP_TEST_DOCKER_HOST` appears in **no source or test file
  today** — it is named here and in the plan as the future switch.
  The DinD harness, the fixture and the loud-skip summary hook all
  belong to the follow-up issue that plan §7 item 7 calls for, which
  is not yet filed. Until that exists, `make test` — whose default
  `-m 'not docker and not gpu and not slow'` deselects the `docker`
  marker — verifies the Docker backend through the stub client only.

## Where to go deeper

- [`docs/spec-builder.md`](spec-builder.md) — the config to
  `ContainerSpec` builder (M2b slice A): how each spec field is
  assembled, the `BackendConfig`-not-`values` trap, the mount
  conversion and its refusals, and the two guards.
- [`docs/tool-state-machine.md`](tool-state-machine.md) — the tool
  state machine (M2b slice B): the six states, the ten-edge table and
  its two deliberate absences, `ModelRuntimeState`'s field
  arithmetic, and the validate-first-log-second contract.
- [`plans/m2a-container-backend-seam.md`](../plans/m2a-container-backend-seam.md) —
  the design decisions behind every type and rule on this page, with
  the per-behaviour ledger (§5) and what M2b will need from the seam
  (§6).
- [`plan/01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md) — §10 (why
  mounts are read-only by default), §11 (the failure modes the error
  taxonomy exists to surface) and §12 (the original interface sketch).
- [`docs/configuration-guide.md`](configuration-guide.md) — the
  `backend:` block and its keys, which is where the namespace, prefix
  and network values this seam consumes are configured.

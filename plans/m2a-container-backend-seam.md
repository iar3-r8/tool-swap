# M2a — Container backend seam

Implementation plan for the backend seam of milestone M2, intake
[GitHub issue iar3-r8/tool-swap#3](https://github.com/iar3-r8/tool-swap/issues/3).

- **Branch:** `feature/m2a-container-backend-seam` (already created; a *feature* branch is
  correct — this is new capability, not a correction to shipped behaviour).
- **Test command:** `make test` (runs `.venv/bin/python -m pytest`).
- **Baseline when this plan was written:** 1112 passed, 2 skipped.
- **Ledger:** 28 numbered behaviours, one red/green cycle each.

---

## 0. Delivery status — M2a lands in two pull requests

**Behaviours 1–2 are done and land as a small prerequisite pull request**, on the branch
named above. They contain no `src/` code at all: they unblock the SDK import, declare and
install the dependency, and discharge §3's blocking documentation pre-condition. Suite at
that branch tip: **1121 passed, 2 skipped**; `make lint` clean, mypy strict over 33 files.

| Behaviour | Red | Green |
|---|---|---|
| 1 — `docker/` → `images/` rename | `f701861` | `a962a4e` |
| 1 — guard corrected (see note) | `ecf3442` | — |
| 2 — `docker>=7.0` + `types-docker` | `961d48d` | `515d9c6` |
| §3 reference captured from source | — | `b80b74a` |
| Documentation | — | `19f9267` |

**Note on `ecf3442`.** Behaviour 1's guard test asserted that no `__path__` entry of the
imported `docker` module started with the repository root. That was over-broad: `.venv/`
lives *inside* the repository, so once behaviour 2 installed the SDK, its legitimate
`site-packages/docker` path tripped the assertion. It now compares resolved paths against
the four repository-anchored locations an errant import could resolve to, and was verified
to still fail against a decoy root `docker/` package carrying its own `__version__` — the
one shape where the `__file__` and `__version__` checks both pass and only the path guard
catches the wrong module. **Narrowed, not weakened.**

**Behaviours 3–28 continue on a fresh branch** as the seam proper. The ledger in §5 is
unchanged and remains the loop state for that work.

---

## 1. Scope

M2a delivers **the seam only** — the interface the rest of the lifecycle will be built on,
plus both implementations behind it:

- `ContainerBackend` protocol, `ContainerSpec`, `ContainerHandle`, `ContainerStatus`
  ([`plan/01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md:460) §12).
- `FakeBackend` — in-memory, with scriptable failures.
- `DockerBackend` — including the pure `build_run_kwargs(spec)` translation and the pure
  SDK-exception → error-taxonomy mapping.
- The label/name helpers those two share.
- The `docker/` → `images/` rename that currently makes `import docker` resolve to the wrong
  thing (behaviour 1 — a hard blocker, see §2).
- The `docker>=7.0` dependency and its type stubs (behaviour 2), and — separately, as
  **behaviour 27** — the import-linter contract that keeps `docker_backend.py` the only
  module importing the SDK. Those are two different cycles: behaviour 2 declares the
  dependency, and no contract exists until behaviour 27.

### Explicitly out of scope

| Deferred to | What |
|---|---|
| **M2b** (a later task, separate PR) | `LifecycleManager` and the `STOPPED`/`STARTING`/`LOADING`/`READY`/`STOPPING`/`FAILED` state machine, coalesced `ensure_ready`, in-flight counting, drain-then-stop, shutdown ordering, `HealthProbe` + `FakeProbe`, reconciliation (`lifecycle/reconcile.py`), the queue-policy seam. **None of these appear in the ledger below.** |
| **A separate follow-up issue** | The three `@pytest.mark.docker` daemon tests of [`plans/m2-docker-testing-recommendation.md`](m2-docker-testing-recommendation.md:96) §3, and the DinD/`TSWAP_TEST_DOCKER_HOST` harness. This environment has no `docker` CLI and no reachable daemon, so those tests could be written but never verified — and an unverified test is not evidence. |
| **M5** | `build()` / `BuildSpec` / `builder.py`. |
| **M7** | The log collector. `logs()` exists on the protocol and is implemented, but "logs survive a stop" is M7's requirement. |
| **`@pytest.mark.gpu`, nightly** | Real GPU device requests. M2a asserts only that a spec is *translated* into the right SDK kwargs. |

**Every behaviour below is verifiable with no Docker daemon**, by construction: the seam is
exercised through `FakeBackend`, the SDK-facing logic through pure functions, and the thin
`DockerBackend` shell through an injected stub client.

---

## 2. Behaviour 1 is a blocker, not a chore

Reproduced on the branch tip: [`pyproject.toml`](../pyproject.toml:66) sets
`pythonpath = ["src", "."]`, and the repository root contains `docker/` (holding only
`docker/base/.gitkeep`). Python therefore resolves `import docker` to that directory as a
namespace package rather than to the SDK:

```
.venv/bin/python -c "import docker; print(docker.__version__)"
AttributeError: module 'docker' has no attribute '__version__'
```

No `DockerBackend` code can be correct until this is fixed, which is why the rename is
behaviour 1 and behaviour 2 (the dependency) follows it rather than preceding it.

**References to update in the same behaviour** (found by search):

| File | What |
|---|---|
| [`tests/unit/test_repo_layout.py`](../tests/unit/test_repo_layout.py:66) | `OTHER_DIRS` lists `"docker"` and `"docker/base"` — this is the existing assertion that must flip, and it belongs to the qna-tester's red step. |
| [`README.md`](../README.md:125) | The repository-structure block lists `docker/` and `docker/base/`. |
| [`plan/08_REPO_LAYOUT.md`](../plan/08_REPO_LAYOUT.md:108) | The `docker/` node of the §1 tree. |
| [`plan/07_CLI_AND_OPS.md`](../plan/07_CLI_AND_OPS.md:202) | `dockerfile: docker/router.Dockerfile` in the compose sample. |

Not to be touched: `plan/12_REFERENCE_CODE.md` (quotes the *R8* repo's layout),
`plan/third-party-docs/podman/*` (vendor text mentioning `$HOME/.docker/config.json`), and
`plans/spike-E-continuation.md` (quotes the Ray image's own layout). `docker/router.Dockerfile`
does not exist yet, so the rename moves `docker/base/` only.

---

## 3. ⚠️ Unverified third-party interface — read before behaviours 14–26

**The Docker SDK for Python (`docker-py`) interface is NOT verified in this plan.**

- The **oxylabs MCP server is unavailable in this session** — it is not exposed as a tool, so
  no documentation could be fetched or saved.
- The repository has **no saved docker-py documentation**: `plan/third-party-docs/` contains
  `bentoml/`, `llama-swap/`, `podman/`, `ray-core/` and `ray-serve/` only.
- `docker` is not currently installed in `.venv`, so its source could not be read either.

What that means for this plan: behaviours 14–26 name **which facts must be pinned**, but they
deliberately **do not assert literal kwarg names, exception class names or filter shapes**,
because those are exactly the values I would otherwise be recalling rather than knowing. That
failure is not self-correcting — qna-tester would write a passing test against an invented
signature and code would satisfy it with a matching shim, leaving the real integration broken.

**Pre-condition on behaviours 14–26, blocking:** after behaviour 2 installs
`docker>=7.0`, the implementer reads the authoritative interface — the installed
`docker` package source and/or <https://docker-py.readthedocs.io> — and records what it found
under `plan/third-party-docs/docker/` (one page per file, source URL at the top, an entry in
that directory's `INDEX.md`), in the same cycle. Behaviours 14–26 then cite those saved
files. **Do not begin behaviour 14 with this open.**

The specific facts to pin:

1. `client.containers.run(...)` / `client.containers.create(...)` — exact kwarg names for
   detach, environment, labels, network, volumes-or-mounts, device requests, shm size, CPU
   quota, memory limit, published ports; and which of the two is the right call for a
   detached start.
2. The GPU device-request type and its constructor arguments.
3. The `containers.list(...)` label-filter form, and whether stopped containers need an
   explicit "all" flag.
4. The `docker.errors` class names and hierarchy, and which call raises which.
5. `container.stop(...)` — the timeout argument's name and units, and whether it returns
   before the container has exited.
6. `container.logs(...)` — the streaming/tail arguments and whether lines arrive as `bytes`.
7. `container.attrs` / `reload()` — where state, exit code and start time live.

---

## 4. Proposed design

### 4.1 `src/tool_swap/backend/base.py`

```python
@dataclass(frozen=True, slots=True)
class MountSpec:
    source: str
    target: str
    read_only: bool = True


@dataclass(frozen=True, slots=True)
class ContainerSpec:
    """Everything needed to start one tool container. Backend-agnostic."""
    tool: str                                   # logical tool name (label value)
    name: str                                   # final container name, prefix applied
    image: str
    command: tuple[str, ...] | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    labels: Mapping[str, str] = field(default_factory=dict)
    network: str | None = None
    mounts: tuple[MountSpec, ...] = ()
    devices: tuple[int, ...] = ()               # GPU indices; () is CPU-only
    gpu_runtime: str = "nvidia"
    shm_size: str | None = None                 # "1g"
    cpus: float | None = None
    memory: str | None = None                   # "16g"
    container_port: int = 8000
    published_port: int | None = None           # expose_host_port; None publishes nothing


@dataclass(frozen=True, slots=True)
class ContainerHandle:
    id: str
    name: str
    tool: str
    image: str


class ContainerState(StrEnum):
    """Backend-level container state. NOT the M2b tool state machine."""
    CREATED = "created"
    RUNNING = "running"
    EXITED = "exited"
    GONE = "gone"


@dataclass(frozen=True, slots=True)
class ContainerStatus:
    handle: ContainerHandle
    state: ContainerState
    exit_code: int | None = None
    started_at: str | None = None


@runtime_checkable
class ContainerBackend(Protocol):
    """The ONLY component that touches a container runtime."""
    def start(self, spec: ContainerSpec) -> ContainerHandle: ...
    def stop(self, handle: ContainerHandle, *, timeout_s: float) -> None: ...
    def is_running(self, handle: ContainerHandle) -> bool: ...
    def inspect(self, handle: ContainerHandle) -> ContainerStatus: ...
    def list_managed(self) -> list[ContainerHandle]: ...
    def logs(self, handle: ContainerHandle, *, follow: bool, tail: int) -> Iterator[str]: ...
```

Design notes, each with its reason:

- **Synchronous**, matching [`plan/01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md:460) §12
  verbatim. The docker SDK is blocking; M2b's `LifecycleManager` is the async layer and will
  off-load these calls. Making the seam async would hide that fact inside the driver.
- **`inspect` is in the protocol**, per the Definition of Done in issue #3, and returns a
  `ContainerStatus` rather than a raw SDK dict — otherwise SDK vocabulary leaks through the
  seam that exists to contain it.
- **`build()` is not in the protocol.** §12 lists it, but it is M5's; adding it now would
  force both implementations to carry a stub. Recorded as a deliberate divergence.
- **`ContainerState` is deliberately not the tool state machine.** `STARTING`/`LOADING`/
  `READY` are readiness concepts owned by M2b's probe; the backend only knows whether a
  process exists.
- **`ContainerSpec` carries no policy** — no TTL, no group, no eviction. It is fully resolved
  input, consistent with `BackendConfig` and `DefaultsConfig` in
  [`src/tool_swap/config/schema.py`](../src/tool_swap/config/schema.py:95) (`network`,
  `container_prefix`, `label_namespace`, `gpu_runtime`, `shm_size`, `cpus`, `memory`,
  `devices`, `env`, `mounts`, `expose_host_port`). Building a spec *from* config is M2b/M3's
  wiring, not M2a's.

### 4.2 Error taxonomy — `src/tool_swap/backend/errors.py`

Every member carries a human `message` and an actionable `remedy`, so
[`plan/01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md:444) §11's "error string surfaced in
`/status`" is real rather than aspirational.

| Class | Raised when | Remedy names |
|---|---|---|
| `BackendError` | base; also the fallback for an unrecognised SDK exception | the underlying error text |
| `BackendUnavailableError` | the daemon is unreachable | how to check the daemon / `DOCKER_HOST` |
| `ImageNotFoundError` | the image reference does not exist | the image ref and `tswap build <tool>` |
| `ContainerNameConflictError` | the name is already taken | the conflicting name and `tswap down` |
| `ContainerStartError` | the daemon refused the start for another reason | the underlying error text |
| `ContainerNotFoundError` | the container has vanished | that it was removed out of band |
| `GpuUnavailableError` | a device request could not be satisfied | the NVIDIA container toolkit |

**Contract decision:** `is_running` swallows not-found and returns `False`; `inspect` returns
`ContainerState.GONE`; `stop` on a missing container is a no-op. Every other method raises.
This is the contract test 3 of
[`plans/m2-docker-testing-recommendation.md`](m2-docker-testing-recommendation.md:102) exists
to confirm against a real daemon later.

### 4.3 `FakeBackend` scriptable failures

```python
class FailureMode(StrEnum):
    FAIL_TO_START = "fail_to_start"
    DIE_AFTER_START = "die_after_start"
    STOP_HANGS = "stop_hangs"

FakeBackend(script: Mapping[str, FailureMode] | None = None)
```

Keyed by **tool name**, so a test scripts a failure before any handle exists. Plus
`fake.vanish(handle)` for out-of-band removal (the M2b "vanished container" path), and a
recorded call journal (`fake.calls`) so a test can assert *exactly one start* without
counting side effects. Threading locks guard the in-memory dict, since M2b's coalescing test
drives it concurrently.

"Never ready" is **not** a `FakeBackend` mode — readiness is the probe's concern, and the
probe is M2b's.

### 4.4 `DockerBackend` client injection

```python
class DockerBackend:
    def __init__(self, client: DockerClientLike, *, label_namespace: str,
                 container_prefix: str) -> None: ...

    @classmethod
    def from_config(cls, cfg: BackendConfig) -> "DockerBackend": ...
```

The constructor takes an **already-built client** and never reads the ambient environment;
`from_config` is the only place a real client is created. That is both the no-daemon
testability seam and the guardrail demanded by
[`plans/m2-docker-testing-recommendation.md`](m2-docker-testing-recommendation.md:250) done 4
("a test asserting that the backend under test is never constructed from the default
environment") — here it is behaviour 20, enforceable with no daemon.

---

## 5. Behaviour ledger

One red/green cycle per behaviour. Each states inputs, outputs, edge cases, error behaviour,
files, and how it is verified with no Docker daemon.

### 1. `docker/` → `images/` rename

- **Inputs:** the repository tree; the four reference sites in §2.
- **Outputs:** `images/base/.gitkeep` exists; no `docker/` directory at the repo root;
  `import docker` resolves to the SDK (or fails as a plain `ModuleNotFoundError`, never to a
  namespace package).
- **Edge cases:** git must record a rename, not a delete-plus-add; `.gitignore` must not
  newly ignore `images/`.
- **Error behaviour:** none — a structural change.
- **Files:** `images/base/.gitkeep`, [`tests/unit/test_repo_layout.py`](../tests/unit/test_repo_layout.py:66),
  [`README.md`](../README.md:125), [`plan/08_REPO_LAYOUT.md`](../plan/08_REPO_LAYOUT.md:108),
  [`plan/07_CLI_AND_OPS.md`](../plan/07_CLI_AND_OPS.md:202).
- **Verified:** `OTHER_DIRS` asserts `images` / `images/base`; a new test asserts
  `(ROOT / "docker").exists()` is `False`; a test asserts the docs contain no `docker/base`
  path reference. No daemon.

### 2. `docker>=7.0` and `types-docker` declared

- **Inputs:** [`pyproject.toml`](../pyproject.toml:24).
- **Outputs:** `docker>=7.0` in `[project.dependencies]`; `types-docker` in the `dev` extra.
- **Edge cases:** mypy strict must pass with the stubs present; the suite's
  `filterwarnings = ["error"]` must survive importing `docker`.
- **Error behaviour:** none.
- **Files:** `pyproject.toml`.
- **Verified:** a manifest test parses `pyproject.toml` and asserts both entries; an import
  test asserts `docker.__version__` is a non-empty string — which also re-proves behaviour 1.
  Importing the SDK contacts no daemon.

### 3. `parse_mount` — pure mount-string parser

- **Inputs:** `"host:container"`, `"host:container:ro"`, `"host:container:rw"`, as authored in
  `defaults.mounts` / `tools.<name>.mounts`.
- **Outputs:** a `MountSpec`; two-part form defaults to `read_only=True`
  ([`plan/01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md:432) §10: "read-only by default").
- **Edge cases:** an absolute Windows-style path containing `:`; a trailing `:`; an empty
  string; an unknown mode.
- **Error behaviour:** raises `ValueError` naming the offending string and the accepted forms.
- **Files:** `src/tool_swap/backend/base.py`.
- **Verified:** table-driven unit test. Pure function.

### 4. `ContainerSpec` dataclass

- **Inputs:** keyword construction.
- **Outputs:** a frozen, slotted instance; documented defaults (`devices=()`,
  `gpu_runtime="nvidia"`, `container_port=8000`, `published_port=None`).
- **Edge cases:** mutable defaults must not be shared between instances.
- **Error behaviour:** assignment raises `FrozenInstanceError`.
- **Files:** `src/tool_swap/backend/base.py`.
- **Verified:** construction + immutability test. Pure data.

### 5. `ContainerHandle`, `ContainerState`, `ContainerStatus`

- **Inputs:** keyword construction.
- **Outputs:** frozen handles with value equality and hashability (M2b will key dicts by
  them); `ContainerState` members `created`/`running`/`exited`/`gone`.
- **Edge cases:** two handles with the same `id` but different `name` are unequal — the id is
  not the identity on its own.
- **Error behaviour:** assignment raises `FrozenInstanceError`.
- **Files:** `src/tool_swap/backend/base.py`.
- **Verified:** construction/equality/hash test. Pure data.

### 6. `managed_labels` — the label set

- **Inputs:** `namespace` (default `"com.tool-swap"` from
  [`BackendConfig.label_namespace`](../src/tool_swap/config/schema.py:117)), tool name,
  optional group, optional config hash.
- **Outputs:** an exact dict — `{ns}.model`, `{ns}.managed-by`, `{ns}.group`,
  `{ns}.config-hash`, per the naming table of
  [`plan/08_REPO_LAYOUT.md`](../plan/08_REPO_LAYOUT.md:185).
- **Edge cases:** a custom namespace; omitted group / config hash omit their keys rather than
  emitting empty values (an empty label value is a silent reconciliation mismatch).
- **Error behaviour:** empty namespace or empty tool name raises `ValueError`.
- **Files:** `src/tool_swap/backend/labels.py`.
- **Verified:** exact-dict snapshot test. Pure function.

### 7. `container_name` and `label_selector`

- **Inputs:** `container_prefix` (default `"ms-"`,
  [`BackendConfig.container_prefix`](../src/tool_swap/config/schema.py:110)) + tool name;
  and `namespace` for the selector.
- **Outputs:** `"ms-cxr_to_embedding"`; a selector value matching `managed_labels`' managed-by
  key so `list_managed` and `managed_labels` cannot drift.
- **Edge cases:** a tool name with characters illegal in a container name; a very long name;
  an empty prefix.
- **Error behaviour:** an unusable name raises `ValueError` naming the tool and the rule.
- **Files:** `src/tool_swap/backend/labels.py`.
- **Verified:** table test; a test asserting the selector key is exactly the key behaviour 6
  emits. Pure functions.

### 8. `ContainerBackend` protocol declared

- **Inputs:** the six method signatures of §4.1.
- **Outputs:** a `@runtime_checkable` Protocol.
- **Edge cases:** `stop` / `logs` keyword-only arguments must stay keyword-only; `build` must
  be absent (deferred to M5).
- **Error behaviour:** n/a.
- **Files:** `src/tool_swap/backend/base.py`.
- **Verified:** a signature-pin test over `inspect.signature` for each method — name, order,
  kind and annotation. This is the anti-drift test for the whole seam. Pure introspection.

### 9. Error taxonomy

- **Inputs:** construction with a message and a remedy.
- **Outputs:** the seven classes of §4.2, all deriving from `BackendError`, which derives from
  `Exception`; `str(exc)` includes both message and remedy.
- **Edge cases:** an error constructed with no remedy must still render usefully.
- **Error behaviour:** n/a — these are the errors.
- **Files:** `src/tool_swap/backend/errors.py`.
- **Verified:** hierarchy test plus a test asserting every concrete subclass produces a
  non-empty remedy. Pure.

### 10. `FakeBackend` happy path

- **Inputs:** a `ContainerSpec`.
- **Outputs:** `start` returns a handle whose `name`/`tool`/`image` match the spec and whose
  `id` is unique; `is_running` is `True`; `inspect` is `RUNNING`; `list_managed` includes it;
  after `stop` it is `EXITED` with exit code `0` and `is_running` is `False`.
- **Edge cases:** starting the same name twice raises `ContainerNameConflictError`; `stop` on
  an already-stopped container is a no-op.
- **Error behaviour:** as above.
- **Files:** `src/tool_swap/backend/fake_backend.py`.
- **Verified:** in-memory only. No daemon by construction.

### 11. `FakeBackend` scripted `FAIL_TO_START`

- **Inputs:** `FakeBackend(script={"t1": FailureMode.FAIL_TO_START})`, then `start`.
- **Outputs:** raises `ContainerStartError` whose message names the tool; no container is
  recorded; `list_managed` stays empty.
- **Edge cases:** an unscripted tool in the same backend still starts normally; the failure
  repeats on retry (it is not one-shot).
- **Error behaviour:** the raised error is the taxonomy member, never a bare `Exception`.
- **Files:** `src/tool_swap/backend/fake_backend.py`.
- **Verified:** in-memory.

### 12. `FakeBackend` death and vanishing

- **Inputs:** `DIE_AFTER_START` in the script; and `fake.vanish(handle)` on a running one.
- **Outputs:** after a scripted death, `is_running` is `False` and `inspect` is `EXITED` with
  a non-zero exit code; after `vanish`, `inspect` is `GONE` and `is_running` is `False`
  **without raising** — the contract of §4.2.
- **Edge cases:** `stop` on a vanished container is a no-op, not an error; `vanish` on an
  unknown handle raises `ContainerNotFoundError`; a vanished container disappears from
  `list_managed`.
- **Error behaviour:** as above.
- **Files:** `src/tool_swap/backend/fake_backend.py`.
- **Verified:** in-memory. This is the fake half of docker contract test 3.

### 13. `FakeBackend.logs` and the call journal

- **Inputs:** pre-seeded log lines; `logs(handle, follow=False, tail=N)`.
- **Outputs:** an iterator of `str`; `tail` returns the last N lines; `follow=False`
  terminates.
- **Edge cases:** `tail` larger than the buffer returns everything; logs of a stopped
  container are still readable; `fake.calls` records every protocol call in order with its
  arguments.
- **Error behaviour:** `logs` on an unknown handle raises `ContainerNotFoundError`.
- **Files:** `src/tool_swap/backend/fake_backend.py`.
- **Verified:** in-memory. The journal is what lets M2b assert "exactly one start".

> **Behaviours 14–26 are blocked on the §3 pre-condition.** Save the docker-py reference under
> `plan/third-party-docs/docker/` first, and cite it in each test.

### 14. `build_run_kwargs` — core translation

- **Inputs:** a minimal `ContainerSpec` (tool, name, image, env, labels, network).
- **Outputs:** a kwargs dict carrying image, name, detached start, environment, the full
  `managed_labels` set, and the network — key names taken from the saved reference.
- **Edge cases:** empty env and empty labels; a spec with `network=None` must omit the network
  key rather than pass `None`.
- **Error behaviour:** a spec with an empty image raises `ValueError` before any SDK call.
- **Files:** `src/tool_swap/backend/docker_backend.py`.
- **Verified:** snapshot of the returned dict. Pure function; no client, no daemon.

### 15. `build_run_kwargs` — mounts

- **Inputs:** a spec whose `mounts` concatenate the global defaults then the tool's own
  ([`plan/02` §5](../src/tool_swap/config/schema.py:493): "concatenated after defaults.mounts,
  not replacing them").
- **Outputs:** the mount entries in declaration order, each carrying source, target and the
  read-only flag.
- **Edge cases:** no mounts omits the key entirely; the same target declared twice keeps both
  entries in order (de-duplication is config-validation's job, not the driver's); a read-write
  mount is distinguishable from a read-only one.
- **Error behaviour:** none here — malformed strings failed at behaviour 3.
- **Files:** `src/tool_swap/backend/docker_backend.py`.
- **Verified:** snapshot. Pure.

### 16. `build_run_kwargs` — GPU device requests

- **Inputs:** `devices=()`, `devices=(0,)`, `devices=(0, 1)`, with `gpu_runtime="nvidia"`.
- **Outputs:** no device request at all for `()`; otherwise one request naming exactly those
  indices and that runtime.
- **Edge cases:** `()` must produce **no key**, not an empty list — an empty device request is
  not the same as none; a non-default `gpu_runtime` is honoured; duplicate indices collapse.
- **Error behaviour:** a negative device index raises `ValueError`.
- **Files:** `src/tool_swap/backend/docker_backend.py`.
- **Verified:** snapshot. Pure — no GPU and no daemon needed to assert a translation.

### 17. `build_run_kwargs` — resource limits

- **Inputs:** `shm_size="1g"` (the built-in default,
  [`defaults.py`](../src/tool_swap/config/defaults.py:20)), `cpus=4.0`, `memory="16g"`, and
  each of them `None`.
- **Outputs:** each limit present in the kwargs in the unit the SDK expects; each `None`
  **omits its key**.
- **Edge cases:** `cpus` is a float in the config but the SDK's quota field may be an integer
  in different units — the conversion is pinned by the saved reference and snapshotted;
  a `memory` string with an unknown suffix.
- **Error behaviour:** an unparseable size string raises `ValueError` naming the field and the
  accepted forms.
- **Files:** `src/tool_swap/backend/docker_backend.py`.
- **Verified:** snapshot. Pure.

### 18. `build_run_kwargs` — port publication

- **Inputs:** `published_port=None` (the default: **D21**, nothing published) and
  `published_port=7001` with `container_port=8000`.
- **Outputs:** no ports key for `None`; a single mapping of container port → host port
  otherwise.
- **Edge cases:** a host port outside `BackendConfig.port_range` is *not* rejected here — range
  policy belongs to config validation, and the driver holds no policy
  ([`plan/01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md:158) §2.1).
- **Error behaviour:** a port ≤ 0 raises `ValueError`.
- **Files:** `src/tool_swap/backend/docker_backend.py`.
- **Verified:** snapshot. Pure.

### 19. `map_sdk_error` — SDK exception → taxonomy

- **Inputs:** synthesised instances of each SDK exception class named in the saved reference.
- **Outputs:** the corresponding taxonomy member of §4.2, carrying a remedy that names the
  actionable thing (the image ref, the conflicting name, the NVIDIA toolkit).
- **Edge cases:** an unrecognised exception maps to `BackendError` preserving the original
  text, never swallowed; the original exception is chained as `__cause__`; a GPU-related API
  error is distinguished from a generic one.
- **Error behaviour:** `map_sdk_error` itself never raises — it returns an exception to raise.
- **Files:** `src/tool_swap/backend/docker_backend.py`.
- **Verified:** table-driven over constructed exception instances. Pure; no daemon.

### 20. `DockerBackend` never touches the ambient environment

- **Inputs:** `DockerBackend(stub_client, label_namespace=..., container_prefix=...)`.
- **Outputs:** a usable backend whose client is exactly the injected object.
- **Edge cases:** the named regression guard — with the SDK's `from_env` (and any other
  environment-reading entry point) monkeypatched to raise, constructing and using
  `DockerBackend` must still succeed. `from_config` is the only path that builds a real
  client, and it is not exercised here.
- **Error behaviour:** constructing with `None` as the client raises `TypeError`.
- **Files:** `src/tool_swap/backend/docker_backend.py`.
- **Verified:** a stub client plus monkeypatch. This is
  [`plans/m2-docker-testing-recommendation.md`](m2-docker-testing-recommendation.md:250)
  done-4's guardrail, made daemon-free.

### 21. `DockerBackend.start`

- **Inputs:** a `ContainerSpec` and a stub client recording its calls.
- **Outputs:** exactly one create/run call whose kwargs equal `build_run_kwargs(spec)`; a
  `ContainerHandle` carrying the id the stub returned plus the spec's name, tool and image.
- **Edge cases:** the stub raising image-not-found surfaces `ImageNotFoundError` via
  behaviour 19; a name conflict surfaces `ContainerNameConflictError`.
- **Error behaviour:** every SDK exception passes through `map_sdk_error`; no raw SDK
  exception escapes the seam.
- **Files:** `src/tool_swap/backend/docker_backend.py`.
- **Verified:** stub client asserts the call was made with the pure function's output — the
  shell is thin precisely so this is all there is to check.

### 22. `DockerBackend.stop`

- **Inputs:** a handle and `timeout_s`.
- **Outputs:** one stop call on the identified container, carrying the timeout in the unit the
  saved reference specifies.
- **Edge cases:** stopping a container the stub reports as missing is a **no-op**, not an
  error; an already-exited container is also a no-op; a zero timeout is passed through.
- **Error behaviour:** any other SDK exception maps via behaviour 19.
- **Files:** `src/tool_swap/backend/docker_backend.py`.
- **Verified:** stub client. (Whether the daemon really returns before the container exits is
  the deferred docker test 2 — **explicitly not claimed here**.)

### 23. `DockerBackend.is_running` on a vanished container

- **Inputs:** a handle whose container the stub reports as absent; and one it reports running.
- **Outputs:** `False` and `True` respectively — never an exception for the absent case.
- **Edge cases:** a container in a non-running state (created, exited, paused, restarting)
  maps to `False`; only the running state maps to `True`.
- **Error behaviour:** a daemon-unreachable error surfaces `BackendUnavailableError` — that is
  *not* the same as not-running and must not be silently swallowed.
- **Files:** `src/tool_swap/backend/docker_backend.py`.
- **Verified:** stub client raising the not-found exception. This encodes our half of docker
  contract test 3.

### 24. `DockerBackend.inspect`

- **Inputs:** a handle; the stub returning container attributes.
- **Outputs:** a `ContainerStatus` with state, exit code and start time read from the
  attribute paths named in the saved reference.
- **Edge cases:** a missing container yields `ContainerState.GONE` with `exit_code=None`; a
  running container has `exit_code=None`, not `0`; an unknown state string maps to `EXITED`
  with a logged warning rather than raising.
- **Error behaviour:** daemon-unreachable maps via behaviour 19.
- **Files:** `src/tool_swap/backend/docker_backend.py`.
- **Verified:** stub client returning canned attribute dicts.

### 25. `DockerBackend.list_managed`

- **Inputs:** a stub client returning a mix of our containers and foreign ones.
- **Outputs:** handles for our containers only, with `tool` recovered from the label rather
  than parsed out of the name.
- **Edge cases:** the list call must include stopped containers (reconciliation must see an
  exited one); zero matches returns `[]`; a container carrying our managed-by label but no
  model label is skipped with a warning rather than crashing the caller.
- **Error behaviour:** daemon-unreachable maps via behaviour 19.
- **Files:** `src/tool_swap/backend/docker_backend.py`.
- **Verified:** stub client asserts the filter passed equals `label_selector(namespace)` from
  behaviour 7. (Whether the daemon's selector really selects is deferred docker test 1 —
  **not claimed here**.)

### 26. `DockerBackend.logs`

- **Inputs:** a handle, `follow`, `tail`; a stub yielding byte chunks.
- **Outputs:** an iterator of decoded `str` lines.
- **Edge cases:** `bytes` are decoded with `errors="replace"` so one bad byte cannot kill the
  stream; a chunk split mid-line is rejoined; `follow=False` terminates; `tail=0` yields
  nothing.
- **Error behaviour:** a missing container raises `ContainerNotFoundError`.
- **Files:** `src/tool_swap/backend/docker_backend.py`.
- **Verified:** stub client yielding canned chunks.

### 27. import-linter contract — `docker` is importable from one module only

- **Inputs:** [`.importlinter`](../.importlinter).
- **Outputs:** a contract forbidding `docker` from every `tool_swap` module except
  `tool_swap.backend.docker_backend`, mirroring the existing bentoml rule of
  [`plan/08_REPO_LAYOUT.md`](../plan/08_REPO_LAYOUT.md:162).
- **Edge cases:** the four existing contracts must keep passing; `tool_swap.backend.base`,
  `fake_backend` and `labels` must not import the SDK — the fake must stay usable with the SDK
  absent.
- **Error behaviour:** `lint-imports` fails loudly on a violation.
- **Files:** `.importlinter`.
- **Verified:** `lint-imports`, plus a test importing `fake_backend` with `docker` blocked
  from `sys.modules`. This is what makes "the ONLY file that talks to Docker" enforced rather
  than hoped for.

### 28. Documentation

- **Inputs:** the modules delivered above.
- **Outputs:** Google-style module docstrings for `base.py`, `errors.py`, `labels.py`,
  `fake_backend.py`, `docker_backend.py`, each stating the module's responsibility and its
  boundary; a backend-seam section in the docs with a mermaid diagram of the seam (not the
  M2b state machine); a troubleshooting table for container start failures keyed by taxonomy
  member; and a short note recording that the daemon tests are deferred, with
  `TSWAP_TEST_DOCKER_HOST` named as the future switch.
- **Edge cases:** no flag or command may be documented from memory — each is checked against
  the code; docs must not claim daemon verification that M2a does not perform.
- **Error behaviour:** n/a.
- **Files:** `src/tool_swap/backend/*.py`, `docs/`.
- **Verified:** the existing docstring checks in
  [`tests/unit/test_repo_layout.py`](../tests/unit/test_repo_layout.py:113), a link check, and
  review. Handed to **docs-manager** after behaviour 27 is green.

---

## 6. What M2b will need from this seam

Stated so M2b is additive, not a refactor of M2a:

1. **A synchronous, injectable `ContainerBackend`.** `LifecycleManager` takes one by
   constructor argument and calls it off the event loop. It must never import
   `docker_backend` directly — only `base`.
2. **`FakeBackend` with a call journal and thread-safe internals.** "Ten concurrent
   `ensure_ready` ⇒ exactly one start" is asserted by counting journal entries.
3. **`vanish()` and `DIE_AFTER_START`.** These drive "a vanished container becomes `FAILED`"
   with no daemon.
4. **`is_running` returning `False` rather than raising** for a missing container. Without it
   M2b's liveness sweep becomes an unhandled traceback in the watchdog.
5. **`list_managed` returning stopped containers too, with `tool` recovered from the label.**
   Reconciliation adopts by label, and there is no port state to reconcile (**D21**).
6. **The error taxonomy with remedies.** `FAILED` carries a reason, and the reason is the
   taxonomy member's message — M2b formats it, it does not invent it.
7. **A `ContainerSpec` builder from resolved config.** M2a defines the dataclass; the
   config → spec function has no owner yet and should be M2b's or M3's first behaviour.

M2a deliberately provides **no** state machine, no readiness notion and no policy. The backend
knows whether a process exists; everything above that is M2b's.

---

## 7. Open assumptions

1. **The docker-py interface is unverified** (§3). Behaviours 14–26 must not begin until the
   reference is read and saved under `plan/third-party-docs/docker/`. This is the single
   largest risk in the plan.
2. **`build()` is excluded from the protocol** though
   [`plan/01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md:460) §12 lists it. Deferred to M5 by
   the same reasoning that defers `builder.py`. Issue #3's Definition of Done lists the
   protocol as `start`, `stop`, `is_running`, `inspect`, `list_managed`, `logs` — without
   `build` — so the two agree, but §12 was not amended.
3. **`inspect` is in the Definition of Done but absent from §12's code block.** The plan
   follows the issue and includes it.
4. **The backend seam is synchronous.** If M2b finds it needs an async seam, that is a change
   to behaviour 8 and a re-review, not a quiet adaptation.
5. **`FailureMode.STOP_HANGS` may be unused by M2a's own tests** — it exists for M2b's drain
   test. If the user prefers strictly-needed-now, drop it from behaviour 12.
6. **Docker vs Podman.** `plan/third-party-docs/podman/` exists and `BackendConfig.type`
   admits other values, but issue #3 says docker SDK, so M2a implements `DockerBackend` only.
7. **The three deferred daemon tests need their own issue**, including the DinD harness, the
   `TSWAP_TEST_DOCKER_HOST` fixture and the loud-skip summary hook. Not filed by this task.

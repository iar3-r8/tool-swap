# 09 — Implementation Plan

> Ordered milestones, each independently testable, in TDD order (write the test, watch it fail, make it pass).
> **No time estimates.** Sequence and acceptance criteria only.

---

## M−1 — Gate: ✅ **RESOLVED — build our own router**

**The gate is closed.** All three spikes from [`14_ALTERNATIVES_EVALUATION.md`](14_ALTERNATIVES_EVALUATION.md) §6 were run or answered, and none produced a cheaper path. Recorded in [ADR-0001](adr/0001-build-our-own-router.md); **do not re-run them.**

| Spike | Outcome | Consequence |
|---|---|---|
| **C** — do the models fit? | **No.** They do not all fit on the GPUs simultaneously. | The swapping premise holds. `docker compose` with everything resident is not an option. |
| **A** — llama-swap as router? | **No.** It is built for LLMs and OpenAI-compatible endpoints; our tools speak `/predict`. | The router returns to our scope: **M2, M3, M6, M7 and M8 are all in**. Its separate role serving our LLMs is unaffected ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §0). |
| **B** — KServe on k3s? | **No**, answered on the record. Kubernetes *allocates* devices and leaves the second pod `Pending`; it does not evict an incumbent. Preemption is a hard requirement here. | We would have to operate a cluster **and still write the preemption logic**. Minikube separately rejected: host-built images are invisible to the cluster, and GPU support is the experimental path. |

**A second gate outcome:** the deployment target is a **shared DGX**. [ADR-0002](adr/0002-shared-node-soft-unload.md) read this as requiring soft unload in v1; **[ADR-0004](adr/0004-hard-stop-only-in-v1.md) reverses that** after the requester clarified that a timer suffices — *"we just don't want to block all the resources indefinitely"*. **v1 reclaims by stopping the container, and there is no soft unload.** This *shrinks* M4, M5.5 and M6 below, and restores Phase 2 item 1.

**The two requirements that came out of the gate**, and which the milestones must satisfy:

1. **Preemption.** A request for tool B displaces an idle incumbent A *immediately*, rather than waiting out A's TTL. The mechanism is a container stop, so the displaced tool pays a cold start on its next request — the accepted cost of [ADR-0004](adr/0004-hard-stop-only-in-v1.md).
2. **Start under contention.** A neighbour on the shared node may hold the VRAM, so a cold start can fail through nobody's fault. That case must never be recorded as a tool failure (**D28**).

**A constraint that still holds, and is now insurance rather than a branch condition:** a tool is an OCI image exposing an HTTP server, runnable standalone with plain `docker run`, whose port and readiness path come from the environment and whose wire protocol lives in the runtime adapter rather than in any handler. That keeps tools portable (compose, llama-swap, tool-swap, KServe) and makes the router replaceable ([`14_ALTERNATIVES_EVALUATION.md`](14_ALTERNATIVES_EVALUATION.md) §8). Test it — and note that **no exporter, no second wire protocol and no Kubernetes backend is built in v1**; the portability is an invariant we maintain, not tooling we write.

---

## Sequencing principle

Build the **spine end-to-end early**, then deepen. By the end of M3 there is a working (if crude) swap-and-proxy service; every later milestone makes it better rather than making it exist. The alternative — perfecting the config layer before anything runs — reliably produces a beautifully-validated system that has never served a request.

```mermaid
graph LR
    GATE[M-1 gate RESOLVED: build our own] --> M0[M0 skeleton]
    M0 --> M1[M1 config]
    M1 --> M2[M2 backend + lifecycle]
    M2 --> M3[M3 proxy: FIRST WORKING SWAP]
    M3 --> S[M3.5 spike: does BentoML install everywhere?]
    S --> M4[M4 runtime on BentoML]
    M4 --> M5[M5 build pipeline]
    M5 --> M55[M5.5 preflight: the author gate]
    M55 --> M6[M6 TTL + eviction]
    M6 --> M7[M7 status + logs]
    M7 --> M8[M8 CLI]
    M8 --> M9[M9 API surface]
    M9 --> M10[M10 hardening + docs]
    M10 --> P2[Phase 2: MCP, R8 client, VRAM-aware scheduling]
```

---

## M0 — Repository skeleton

**Goal:** an empty but fully-wired project. Nothing to demo; everything to build on.

- Repo, licence, `pyproject.toml` with the two distributions ([`08_REPO_LAYOUT.md`](08_REPO_LAYOUT.md) §3).
- ruff, mypy strict, pytest with markers, pre-commit, **two** import-linter rules: `tool_swap` ⊥ `tool_swap_runtime`, and `bentoml` importable **only** from `tool_swap_runtime/backends/` (**D14**, [`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §2.4). Add the second rule now, while there is no code to violate it — retrofitting a boundary after the imports have spread is how seams die.
- `ci.yml` running lint + type-check + an empty test suite.
- The directory tree from [`08_REPO_LAYOUT.md`](08_REPO_LAYOUT.md) §1, with `__init__.py` and module docstrings.
- `Clock` protocol + `RealClock` + `ManualClock` (needed by nearly every later test).

**Done when:** CI is green; `tswap --help` prints; `ManualClock` is unit-tested.

---

## M1 — Configuration

**Goal:** parse, validate and resolve config with excellent error messages.

- Pydantic schema for router/backend/defaults/groups/models with `extra="forbid"`.
- YAML loader: `${VAR}` / `${VAR:-default}` interpolation, `.env` loading, `path:`-based `tool.yaml` inclusion.
- Resolver implementing precedence `inline > tool.yaml > defaults > built-in`, **tracking the origin of every value**.
- All validation rules from [`02_CONFIGURATION.md`](02_CONFIGURATION.md) §6, including the mandatory-description rule (**D19**: hard error for the tool and its inputs, warning for outputs, `--allow-missing-descriptions` never in CI) and the group-starvation warning (**D9**).
- **The schema compiler**: the simple `inputs:`/`outputs:` list → **JSON Schema 2020-12**, with `x-batchable` / `x-semantic` extensions and the raw `json_schema:` pass-through (**D13**, [`04_API_CONTRACT.md`](04_API_CONTRACT.md) §9). Projections come later (M9); the compiler is needed now because `/tools` in M3 depends on it.
- `tswap validate` and `tswap config show`.

**Tests:** the five-line minimal config works; unknown key errors name the key and suggest the nearest valid one; precedence for scalars, and merge semantics for `env` (merged) vs `mounts` (concatenated); a missing env var with no default fails; every §6 rule has a failing-config test; `tools.example.yaml` validates (asserted in CI). Schema compiler: `inputs:` compiles to the expected JSON Schema (snapshot); `batchable`/`semantic` become `x-*`; `additionalProperties: false` is always emitted; a raw `json_schema:` block passes through untouched; **the compiled output validates against the JSON Schema meta-schema**; a missing `description` fails.

**Done when:** `tswap validate` gives a message a stranger can act on for every malformed example in the test corpus.

---

## M2 — Container backend and lifecycle

**Goal:** start and stop a container and track its state — no HTTP path yet.

- `ContainerBackend` protocol, `ContainerSpec`, `ContainerHandle` ([`01_ARCHITECTURE.md`](01_ARCHITECTURE.md) §12).
- `FakeBackend`: in-memory, scriptable failures (fail to start, never ready, die while running).
- `DockerBackend`: create/start/stop/inspect/list-by-label/logs, with our labels, network, device requests, env, mounts, `shm_size`.
- `LifecycleManager`: the state machine from [`01_ARCHITECTURE.md`](01_ARCHITECTURE.md) §4, coalesced `ensure_ready`, in-flight counting, graceful drain-then-stop.
- `HealthProbe` + `FakeProbe`; the `STARTING` → `LOADING` → `READY` progression.
- Reconciliation on boot: adopt or stop labelled containers.

**Tests (fakes, fast):** ten concurrent `ensure_ready` calls ⇒ exactly one start; failure paths give `FAILED` with the reason; drain waits for in-flight then stops; a vanished container becomes `FAILED`; reconciliation adopts a ready container and stops an orphan; state transitions are logged.

**Tests (`@pytest.mark.docker`):** a real container starts, is probed, and stops; labels are queryable; stop escalates SIGTERM → SIGKILL.

**Done when:** the state machine is exercised on every edge with fakes, and one real container round-trip passes.

---

## M3 — Proxy — **the first working swap**

**Goal:** the spine is alive. A request starts a container, gets proxied, and returns.

- `POST /run/{tool}` (basic — pass `inputs` through), with large payloads travelling **by reference**, resolved inside the runtime immediately before the handler sees them (**D18**). v1's resolver accepts a filesystem path and returns it unchanged; the seam is what makes object storage additive later.
- `ANY /upstream/{tool}/{path...}` with bidirectional streaming and header hygiene.
- `ensure_ready` on the request path: a request during a cold start **blocks**, bounded by `queue_timeout` and `max_queue_depth` (**D22**). **All front doors delegate to this one function** ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §1) — no scheduling logic in any route handler.
- Tools are addressed **by container name on the shared network**, with no host ports published (**D21**). There is no allocation step and no persisted port state.
- The error envelope and code→HTTP mapping from [`04_API_CONTRACT.md`](04_API_CONTRACT.md) §6, including the `TOOL_UNAVAILABLE` `reason` field.
- Request-id middleware; `meta` with `duration_ms`, `queue_ms`, `cold_start`.
- Minimal `/health` (single endpoint: `{ok, config_loaded, backend_reachable}`) and `/tools`.

**Tests:** proxy to a fake upstream (an in-process ASGI app) verifying method/path/query/body/headers/status; SSE streams without buffering; a cold-start request blocks then succeeds; `queue_timeout` yields 503 `TOOL_UNAVAILABLE` with `reason: queue_timeout` + `Retry-After`; `max_queue_depth` yields 429; unknown tool yields 404 (**not** 500 — the explicit R8 fix); the swap-retry fires exactly once on a mid-flight stop; a success body carries `outputs` and no `status` field, and an error body carries `error` and no `outputs`; `/health` never varies with tool state.

**Integration:** with a trivial `example_echo` image — no ML involved, built from the runtime like any tool — assert an end-to-end request that started the container on demand. (A stock `httpbin` image is fine as a *test fixture* for exercising the proxy; it is not a tool in the zoo, since the zoo contains only tools we build.)

**Done when:** `curl localhost:8600/run/example_echo` starts a container on demand and returns its response. **This is the demo that proves the concept.**

---

## M3.5 — Spike: validate the BentoML decision before building on it

**Goal:** turn **D14**'s accepted risk into evidence. Timeboxed, throwaway code, one written outcome.

The decision to build the runtime on BentoML ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §1) rests on one assumption: *its pins do not conflict with real model stacks.* That assumption is cheap to test now and expensive to discover false in M6. **Run it before M4, not during.**

1. **Resolution, torch stack.** Build an image with the pinned BentoML plus `torch==2.8.0+cu129`, `transformers`, `monai`, `pydicom` — the R8 CXR/CT stack. Record the resolved versions of pydantic, starlette and click.
2. **Resolution, TensorFlow stack.** The same with `tensorflow` / `tf-keras` on a vendor base image — the R8 `organ_donor` case, and the one most likely to fight.
3. **Vendor base image.** Confirm the pinned BentoML installs on an `nvcr.io` base ([`03_TOOL_AUTHORING.md`](03_TOOL_AUTHORING.md) §6), which Level 3 authoring assumes.
4. **Batching sanity.** A trivial sleep-handler service with `batchable=True`: fire 32 concurrent requests, confirm the handler is invoked far fewer than 32 times, that every caller gets its own correct result, and that added latency is bounded near `max_latency_ms`. This measures the thing we chose BentoML *for*.
5. **Contract feasibility.** Mount a custom ASGI route beside the generated API and serve our own `/ready` (§3.2), confirming the adapter shape in [`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §3 is actually buildable.

**Outcomes and what each means:**

| Result | Action |
|---|---|
| All pass | Proceed to M4. Pin the versions the spike resolved. Record as an ADR. |
| A stack conflicts but is pinnable around | Proceed, and document the constraint in the template for that stack. |
| A stack cannot resolve at all | **D14 reopens.** Options in order: that model uses the `native` backend (which must then be built, and M4 grows); or the project-wide default changes. Either way, decide with the evidence in hand. |
| Batching underperforms a fixed size/age policy | Reconsider — the primary benefit was the dispatcher. Compare against the `CoreBatcher` policy before deciding. |

**Done when:** the resolution results and the batching numbers are written into the ADR, and the BentoML version is pinned in `pyproject.toml`. **Do not start M4 with this open** — M4 builds directly on its answer.

---

## M4 — Model runtime on BentoML

**Goal:** managed models: a handler becomes a batching server, with BentoML underneath and our contract on top.

- `tool_swap_runtime` **above the seam**: `@tool` decorator (metadata only), handler loader with static params, background load with **failure recorded and exposed**, schema compilation, and the predict wrapper (validation, batch-length check, `retry_singly`, error envelope).
- `backends/base.py`: the `RuntimeBackend` protocol ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §2.3). `backends/NATIVE.md`: the specification of the unbuilt alternative. **No native code.**
- `backends/bentoml_backend.py`: build the service, declare the batched API from config, mount our contract routes (`/health` `/ready` `/schema` `/info`), map `worker_index` → device through `TSWAP_DEVICE_LIST` and log the mapping.
- Truthful `/ready`: weights-loaded, not server-up (§3.2) — the correction of the R8 behaviour this milestone most depends on.
- **No `POST /unload` and no reload path** ([ADR-0004](adr/0004-hard-stop-only-in-v1.md)). `unload()` remains in the handler protocol as an **optional** hygiene hook, called on `SIGTERM`; nothing calls it on the reclamation path. This is where the soft-unload machinery would re-attach if [ADR-0004](adr/0004-hard-stop-only-in-v1.md)'s triggers ever fire.
- Env-var contract ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §7) translated into BentoML config; **effective config logged at startup**, including backend and BentoML versions.
- BentoML's logger folded into our format; structured errors; graceful `SIGTERM`.
- `tswap validate` enforces **D15**: a batched tool declaring a non-batchable input is a hard error.

**Tests — above the seam, fast and pure:** a length-mismatched return fails loudly (**safety-critical**: a silent misalignment returns one patient's result for another); `retry_singly` isolates the offending item and attributes the failure; validation rejects unknown, missing and mistyped inputs; static params reach `__init__` and never appear in the request schema; `validate` rejects a batched tool with a non-batchable input, naming both remedies.

**Tests — the backend contract suite** (`tests/runtime/contract/`, parameterised over backends, one backend in v1): `/health` answers before load completes **and during a 5 s inference**; `/ready` is 503 with a reason while loading; `load()` raising leaves `/ready` at 503 with the traceback and exits non-zero; `/schema` matches the compiled schema; `/info` reports backend and version; N concurrent requests produce **fewer than N** handler invocations and every caller receives its own correct result under interleaved arrival; `batching.enabled: false` still calls with lists of length 1.

**Note on batching tests:** exact flush timing is no longer assertable, because the dispatcher adapts its own window ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §4.2). Assert observable properties — invocation counts, result correctness, bounded latency — never exact timings. This is the main testing cost of **D14**, and the reason correctness assertions must be stronger to compensate.

**Done when:** the runtime serves the `example_echo` handler through BentoML, demonstrably batches, never mis-attributes a result, and the contract suite passes — a suite written to outlive the backend it currently runs against.

---

## M5 — Build pipeline

**Goal:** three files become a running image (**R2**).

- Dockerfile generation from `runtime:` (levels 0–3), correct layer order, BuildKit pip/uv cache mounts.
- Base images: `base-cpu:py312`, `base-cuda:12.4-py312`.
- Deterministic tagging by config hash; `:latest` alias; rebuild-needed detection.
- `tswap build [model|--all]`; generated Dockerfiles kept in `.tswap/build/<model>/` for inspection and graduation.
- `tswap new` templates, each of which actually runs.
- `tswap test <model>` running `tool.yaml`'s `example`.
- `tswap dev <model>` with a source bind-mount and hot reload.

**Tests:** generated Dockerfile snapshot tests per level; **editing `handler.py` does not invalidate the pip layer** (assert on the generated file ordering); the hash changes when requirements change and not when only a comment changes; every template validates.

**Integration:** build and serve `example_echo` end-to-end; build a torch-CUDA template if a GPU runner exists.

**Done when:** `tswap new` → `tswap build` → `tswap test` succeeds for every template, and rebuilds after a code-only edit are fast.

---

## M5.5 — `tswap preflight`, the author's deployment gate

**Goal:** an author can answer "will my tool deploy successfully?" with one command (**D17**, **R2**).

Placed immediately after M5 because it needs the build pipeline and the runtime, and because every milestone after this one is easier to develop with it: M6 and M10 both migrate real tools, and preflight is how you find out a tool is broken before blaming the scheduler.

- `preflight/check.py`: the `Check` protocol — `id`, `stage`, `severity`, `needs_docker`, `needs_gpu`, and a **mandatory remedy string**. A check that cannot say how to fix its own failure does not get merged.
- `preflight/registry.py`: the single registry. **Refactor `tswap validate` (M1) to consume its static subset** — this milestone must *move* those rules, not copy them (guardrail 13).
- Stage implementations 1–7 ([`03_TOOL_AUTHORING.md`](03_TOOL_AUTHORING.md) §10.1): static, build, standalone boot, truthful readiness, contract, example, batching/attribution. **Stage 8 (resource release) does not exist** ([ADR-0004](adr/0004-hard-stop-only-in-v1.md)), and **stage 9 (teardown) becomes an invariant of the runner's `finally` rather than a reported stage** ([`16_COMPLEXITY_AUDIT.md`](16_COMPLEXITY_AUDIT.md) §4.1) — still asserted, no longer a report line the author cannot act on.
- **Preflight therefore needs no GPU at any stage**, which satisfies guardrail 12 by construction instead of by exception.
- `preflight/runner.py`: sequencing, continue-after-failure where safe, and **teardown in a `finally`** so a failed run never leaks a container.
- `preflight/report.py`: verdict, the four exit codes, human and `--json` renderers.
- `preflight/recommend.py`: measurements → suggested `tools.yaml` snippet, marking values it cannot know (`group`) rather than inventing them.
- Flags `--fast`, `--strict`, `--json`, `--keep`, `--stage N`.

**Explicitly out of scope here**, to keep the milestone landable: cold-start *statistics* across runs need the stats layer from M7; a CI admission gate and a `/admin/.../preflight` endpoint are phase 2.

**Tests:** one deliberately-broken fixture tool per check, asserting that check fails and that its remedy string appears ([`10_TESTING_STRATEGY.md`](10_TESTING_STRATEGY.md) §5.1) — a check with no failing fixture is unproven and must not be merged. Plus: `validate` and `preflight` agree on every static check over the whole fixture corpus (the anti-drift test); teardown leaves nothing behind **even when a stage raises**; `--keep` does leave the container; exit code 2 is returned when Docker is unreachable and is never confused with a tool failure; `--strict` promotes warnings; the `--json` report round-trips.

**The milestone's real acceptance test:** take the `example_readiness_lies` fixture — a handler that loads in `__init__` and therefore reports ready immediately — and confirm preflight fails stage 4 with the remedy naming `load()`. That is the R8 defect this project exists to correct, caught at authoring time by the author themselves.

**Done when:** `tswap preflight example_echo` exits 0 with a config snippet, every broken fixture fails exactly the check it was built to break, and `tswap validate` is implemented as a filtered view of the same registry.

---

## M6 — TTL, groups and eviction

**Goal:** the actual product feature (**D9**, **D7**).

- `scheduler/policy.py`: **pure** `request_slot`, `find_expired`, `rank` ([`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](06_LIFECYCLE_TTL_AND_SCHEDULING.md) §5, §9).
- Group occupancy accounting over holding states.
- TTL watchdog (**one timer**, [ADR-0004](adr/0004-hard-stop-only-in-v1.md)); `keep_warm`; `autostart: false`.
- LRU / LIFO / none eviction; `min_residency`; in-flight immunity.
- **Preemption** (**D25**): a request displaces an idle incumbent via `EVICT_THEN_GRANT` rather than waiting out its TTL. This is the existing eviction path with a request as its trigger, not new machinery.
- Failure backoff and `max_consecutive_failures`.
- Thrash detection with a warning that names the competing models and suggests a fix.
- **Start under contention** (**D28**): a neighbour on the shared node may hold the VRAM. Return to `STOPPED` **not** `FAILED`, do **not** increment `consecutive_failures`, return 503 `vram_unavailable` with `Retry-After`, and log it under its own reason. Optionally read live free VRAM first to fail fast — **measurement only**; it never enters `request_slot` (**D27**, guardrail 2).
- Liveness and readiness re-checks; periodic reconciliation.

**What this milestone does *not* contain** ([ADR-0004](adr/0004-hard-stop-only-in-v1.md)): no soft sweep, no `IDLE_SOFT`, no `SOFT_UNLOAD_THEN_GRANT`, no `can_soft_unload`, no slot-versus-VRAM split in the snapshot, and no preflight stage 8. **One residency question, one idle timer, one eviction mechanism.**

**`min_residency` and thrash detection are load-bearing here, not garnish.** Displacement now costs the victim a full cold start, so the alternating-request pathology ([`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](06_LIFECYCLE_TTL_AND_SCHEDULING.md) §5.3) is more expensive than it would have been with soft unload. Thrash detection is also the instrumentation that tells us whether [ADR-0004](adr/0004-hard-stop-only-in-v1.md) was the wrong call.

**Tests:** every scenario in [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](06_LIFECYCLE_TTL_AND_SCHEDULING.md) §8 as a fast unit test with `ManualClock` + `FakeBackend` — simple swap, TTL expiry, in-flight protection, thundering herd, failure/backoff, **start under contention**, router restart, group isolation. Plus: `min_residency` prevents immediate re-eviction; `eviction: none` waits instead of evicting; ranking is deterministic on ties. **Scenarios §8.1b and §8.1c are removed** with soft unload.

**The test that matters most here:** a start that fails for lack of VRAM must leave the tool `STOPPED` with its failure counter untouched (**D28**, guardrail 5b). Get it wrong and every tool slowly marks itself broken whenever the DGX is busy — a failure that looks like our bug, reports as our bug, and is not.

**Integration:** two real containers in a `max_resident: 1` group genuinely alternate; VRAM is observably released on stop, confirmed with `nvidia-smi` (skip without a GPU); a request for the evicted tool restarts it correctly.

**Done when:** the entire policy surface is covered by tests that run in milliseconds and never sleep.

---

## M7 — Observability

**Goal:** answer "why is it slow/failing?" without reading source (**R1**).

- Log collector: container streams → per-model rotating files, **retained after the container stops**.
- Router logging: console + rotating file + `.jsonl`; effective config dumped at boot; explicit INFO lines for transitions, cold starts with durations, evictions with victim and reason, TTL stops, and failures with traceback.
- `/status` with everything in [`04_API_CONTRACT.md`](04_API_CONTRACT.md) §5, including per-tool latency percentiles and cold-start stats. This is the **only** metrics surface in v1; Prometheus `/metrics` is deferred ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §8).
- Reuse the stats layer to enrich the preflight report with **cold-start and latency statistics across runs** rather than the single measurement M5.5 produces, so `ready_timeout` suggestions stop being derived from one sample.
- `/ui` status page (single HTML file, polls `/status`, start/stop buttons, log tail).

**Tests:** logs survive a container stop (the key requirement); rotation caps disk use; a `request_id` appears in the response header, the body `meta`, the router log and the container log; `/status` shape is snapshot-tested; TTL countdown maths is correct.

**Done when:** a deliberately-broken model can be diagnosed from `/status` plus `tswap logs` alone.

---

## M8 — CLI

**Goal:** the ops surface from [`07_CLI_AND_OPS.md`](07_CLI_AND_OPS.md) (**R1**, **D8**).

- `up`, `down`, `restart`, `status`, `ps`.
- `start`, `stop`, `stop-all` (a client-side loop over `/admin/tools/{tool}/stop`; there is no `stop-all` endpoint).
- `logs` (router, per-model, `--all` interleaved, `-f`, `--tail`, `--since`).
- `run` (one-shot inference), `shell`, `warm`, `prune`, `doctor`.
- `docker-compose.yml` for the router; `docker-compose.dev.yml` overrides.
- The `up` output that lists the next commands.

**Tests:** CLI unit tests against a fake router API; `doctor` reports each failure mode correctly (no Docker, no toolkit, missing image, stale runtime, port in use); `up` fails fast and clearly on an invalid config **before** touching Docker.

**E2E:** `tests/e2e/test_quickstart.py` executes the README quickstart verbatim, so the docs cannot rot.

**Done when:** launch, status and logs are each one obvious command and the quickstart test passes.

---

## M9 — Full API surface

**Goal:** finish the four front doors (**R3**, **D4**).

- `/run/{tool}` with schema validation against the compiled JSON Schema, `options.timeout` clamping, and **list inputs on `x-batchable` ports** with per-item status in `meta.items[]` (there is no separate `/batch` endpoint).
- `GET /tools/{tool}`, with the schema cached from the container's `/schema` (there is no separate `/run/{tool}/schema` endpoint).
- `/tools` enriched with descriptions and state, plus the `?format=tools` projection (**D13**, [`04_API_CONTRACT.md`](04_API_CONTRACT.md) §8) — standard tool definitions, replacing R8's bespoke `to_node_text()`. **This is the integration surface**: with no OpenAI door, it is how an agent whose LLM lives elsewhere discovers and calls our tools. `?format=openapi` is deferred.
- The three admin endpoints (`start`, `stop`, `logs`); optional bearer auth.

There is **no OpenAI compatibility layer and no `mapping:`** — both were deleted with `kind: external` ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §7). This milestone is correspondingly smaller than it once was.

**Tests:** input validation rejects unknown/missing/mistyped inputs with 422; a list on a batchable port returns parallel outputs in order and isolates a single bad item; a list on a non-batchable port is a 422; auth is enforced on admin; `start` on a `FAILED` tool clears the failure counter. Projections: `?format=tools` output is snapshot-tested and **validated against the standard tool-definition shape**; `x-*` keys are stripped from it; `?names=a,b` subsets correctly; every tool in the zoo appears, since there is no second class of tool that could be missing one.

**Integration (the milestone's real acceptance test):** feed `?format=tools` straight into an LLM SDK's `tools=[...]` against our llama-swap deployment, and confirm the model emits a well-formed call for a zoo tool, which then succeeds against `/run/{tool}`. That round trip — llama-swap for the LLM, tool-swap for the algorithm — is the entire product thesis in one test, and the end-to-end proof that **D13** delivers what it promises.

**Done when:** an agent backed by an external LLM can discover and successfully call a tool in the zoo without a line of adapter code.

---

## M10 — Hardening and documentation

**Goal:** ready for other people to use.

- Failure-injection pass: kill containers mid-request, exhaust the disk, fill VRAM, drop the network, corrupt an image, SIGKILL the router.
- Load pass: concurrency on one model, concurrency across models in a full group, sustained thrash — confirm no leaks in the in-flight counter or the queue.
- Docs: quickstart, adding-a-model (the ladder), configuration (generated from the schema), API, operations runbook, architecture, ADRs seeded from [`13_OPEN_QUESTIONS.md`](13_OPEN_QUESTIONS.md).
- `deploy/`: systemd unit, optional Prometheus/Grafana.
- Migrate two or three real models (ideally one torch, one TensorFlow — the TF/Keras case is the one that was structurally broken in the shared-process design) as proof.
- Release: publish the runtime package and base images.

**Done when:** someone who has never seen the project stands up a two-model zoo from the README, unaided.

---

## Phase 2 (explicitly after v1 ships)

Ordered by expected value. Items 1–8 are features; the API items deferred in [`04_API_CONTRACT.md`](04_API_CONTRACT.md) §8 are listed after them with the trigger that would justify building each.

1. **Soft unload / `IDLE_SOFT`** — moved into v1 by [ADR-0002](adr/0002-shared-node-soft-unload.md), then **returned here by [ADR-0004](adr/0004-hard-stop-only-in-v1.md)** once the requester clarified that a timer suffices. **It is fully designed** — the state, `POST /unload`, `SOFT_UNLOAD_THEN_GRANT`, the slot/VRAM split and preflight stage 8 are all specified in [ADR-0002](adr/0002-shared-node-soft-unload.md) and this file's history — so re-promotion is implementation, not rediscovery. **Build it when a measurement says so**, per [ADR-0004](adr/0004-hard-stop-only-in-v1.md)'s four triggers; the strongest is cold starts exceeding ~20% of total request time for a frequently-used tool. `soft_ttl` is already reserved in the config schema, so its return is additive.
2. **The R8 client** — [`11_R8_CLIENT_PLAN.md`](11_R8_CLIENT_PLAN.md) (**D10**).
3. **VRAM-aware scheduling** — a new `Policy` implementation using `vram_gb` + live free memory; groups declare total VRAM instead of a tool count (**D7**'s "room for improvement"). Note the boundary v1 already draws: measuring free VRAM before a reload is permitted, *deciding placement* from predicted consumption is not ([ADR-0002](adr/0002-shared-node-soft-unload.md) §6). This item is about crossing that line deliberately, with evidence.
4. **Replicas / horizontal scaling** — `replicas: N` with round-robin, and load-based autoscaling within a group.
5. **Async job submission** — `POST /run/{tool}?async=true` with a result store, if minute-scale tools demand it.
6. **WebSocket passthrough** in the proxy.
7. **Multi-host** — the point at which honestly evaluating Kubernetes/KServe against extending this becomes the right move.
8. **Auth and multi-tenancy** — per-token tool access, quotas.

Deferred API surface, each to be built only when its trigger fires:

| Deferred | Trigger |
|---|---|
| `GET /metrics` (Prometheus, router + containers) | Someone stands up Prometheus and needs alerting. `/status` covers v1. |
| `?format=openapi` + per-tool operations injected into `/openapi.json` | A consumer needs generated clients or API-gateway import. |
| `POST /admin/reload` and `tswap reload` — config diffing with dirty-image restart-on-idle | Router restart proves disruptive in practice. Boot reconciliation already adopts running containers. |
| `POST /admin/tools/{tool}/reset` | A need arises to clear `FAILED` *without* starting; `start` clears it today. |
| `POST /admin/stop-all` | A non-CLI client needs one atomic call. |

---

## Cross-cutting definition of done

Every milestone must satisfy all of these before it is considered complete:

1. Tests written first; unit tests use fakes and an injected clock; **no `sleep()` in unit tests**. The one sanctioned exception is the runtime contract suite, whose batching assertions run against a real dispatcher that owns its own timing ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §4.2) — and even there, assert invocation counts and result correctness, never elapsed times.
2. Full suite green; no new warnings (zero-warning policy).
3. ruff clean; mypy strict clean; import boundaries intact.
4. Public functions have type hints and Google-style docstrings.
5. Docs updated in the same change — including the troubleshooting table when a new failure mode is introduced.
6. Errors are actionable: they name what failed, why, and the command that helps.
7. No new **direct** dependency in `tool_swap_runtime` without justification, and **no `bentoml` import outside `backends/`** — the seam that keeps **D14** reversible ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §2.4).
8. New config keys are validated, documented, and appear in `tswap config show`.
9. Anything that could return one caller's result to another is covered by an explicit test. The batch-length check and result attribution are the standing examples.

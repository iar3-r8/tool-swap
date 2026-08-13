# 08 — Repository Layout, Packaging and Tooling

---

## 1. Directory tree

```
tool-swap/
├── README.md                       # quickstart, the troubleshooting runbook, links
├── LICENSE
├── pyproject.toml                  # both packages, or see §3 on splitting
├── tools.example.yaml             # a working multi-model example
├── .env.example                    # HF_TOKEN, HF_HOME, TSWAP_TOKEN, TSWAP_PORT
├── docker-compose.yml              # the router service (D8)
├── docker-compose.dev.yml          # dev overrides: source mounts, reload
├── Makefile                        # make up / test / lint / build-all
│
├── src/
│   ├── tool_swap/                     # ── THE ROUTER (always-on, tiny deps) ──
│   │   ├── __init__.py
│   │   ├── __main__.py                 # python -m tool_swap
│   │   ├── config/
│   │   │   ├── schema.py               # pydantic models, extra="forbid"
│   │   │   ├── loader.py               # yaml + env interpolation + includes
│   │   │   ├── resolver.py             # defaults -> tool.yaml -> inline, with origins
│   │   │   └── validate.py             # the rules in 02_CONFIGURATION.md §6
│   │   ├── schema/
│   │   │   ├── compile.py              # inputs:/outputs: -> JSON Schema 2020-12 (D13)
│   │   │   └── tools.py                # -> standard tool definitions (the integration surface)
│   │   ├── registry/
│   │   │   ├── model_def.py            # immutable resolved definition
│   │   │   └── registry.py             # atomic snapshot + reload diff
│   │   ├── scheduler/
│   │   │   ├── state.py                # ModelRuntimeState, SchedulerSnapshot, enums
│   │   │   ├── policy.py               # PURE: request_slot(), find_expired(), rank()
│   │   │   └── groups.py               # occupancy accounting
│   │   ├── lifecycle/
│   │   │   ├── manager.py              # state machine, coalesced starts, in-flight counts
│   │   │   ├── watchdog.py             # TTL sweep, liveness, retry, reconcile
│   │   │   └── reconcile.py            # adopt/stop containers on boot
│   │   ├── backend/
│   │   │   ├── base.py                 # ContainerBackend protocol + ContainerSpec
│   │   │   ├── docker_backend.py        # the ONLY file that talks to Docker
│   │   │   ├── fake_backend.py          # in-memory, for tests
│   │   │   └── builder.py              # Dockerfile generation + image build/tagging
│   │   ├── preflight/                  # ── THE DEPLOYMENT GATE (D17) ──
│   │   │   ├── registry.py             # THE single check registry; validate takes
│   │   │   │                           # the static subset, preflight takes all
│   │   │   ├── check.py                # Check protocol: id, stage, severity,
│   │   │   │                           # needs_docker, needs_gpu, remedy text
│   │   │   ├── checks/
│   │   │   │   ├── static_checks.py    # tier 1 (03 §10) — no Docker, used by validate
│   │   │   │   ├── build_checks.py     # image builds; pip-layer invalidation warning
│   │   │   │   ├── boot_checks.py      # plain `docker run`, guardrail 11
│   │   │   │   ├── readiness_checks.py # truthful /ready; cold-start measurement
│   │   │   │   ├── contract_checks.py  # /schema vs tool.yaml, /info, health under load
│   │   │   │   ├── example_checks.py   # tool.yaml `example` -> output schema
│   │   │   │   ├── batching_checks.py  # attribution + retry_singly (safety-critical)
│   │   │   │   └── resource_checks.py  # unload frees VRAM — GPU only, skippable
│   │   │   ├── runner.py               # stage sequencing, continue-after-failure,
│   │   │   │                           # guaranteed teardown
│   │   │   ├── report.py               # verdict, exit codes, human + --json renderers
│   │   │   └── recommend.py            # measurements -> suggested tools.yaml snippet
│   │   ├── proxy/
│   │   │   ├── forwarder.py            # streaming reverse proxy, header hygiene
│   │   │   └── probes.py               # HealthProbe implementation
│   │   ├── api/
│   │   │   ├── app.py                  # FastAPI assembly, lifespan, middleware
│   │   │   ├── run.py                  # POST /run/{tool}
│   │   │   ├── upstream.py             # ANY /upstream/{tool}/{path...}
│   │   │   ├── admin.py                # /admin/tools/{tool}/start|stop, /admin/logs/{tool}
│   │   │   ├── discovery.py            # /tools, /tools/{tool} ?format=json|tools
│   │   │   ├── status.py               # /status, /health
│   │   │   ├── errors.py               # the error envelope + code->HTTP mapping
│   │   │   └── ui/index.html           # the status page, single file, no build step
│   │   ├── observability/
│   │   │   ├── logging.py              # console + rotating file + jsonl
│   │   │   ├── log_collector.py        # container streams -> per-tool files
│   │   │   ├── stats.py                # in-memory counters/latencies feeding /status
│   │   │   └── request_id.py           # middleware + contextvar
│   │   ├── cli/
│   │   │   ├── main.py                 # typer app
│   │   │   ├── up.py  down.py  status.py  logs.py
│   │   │   ├── build.py  new.py  validate.py  test.py  dev.py  run.py
│   │   │   ├── preflight.py            # thin: parse flags, call the runner, render
│   │   │   └── doctor.py  config_show.py  prune.py
│   │   └── utils/
│   │       ├── clock.py                # Clock protocol, RealClock, ManualClock
│   │       └── ids.py
│   │
│   └── tool_swap_runtime/             # ── IN-CONTAINER RUNTIME (bentoml + its pinned set) ──
│       ├── __init__.py                 # public API: tool, Field, __version__ — NO bentoml types
│       ├── server.py                   # python -m tool_swap_runtime.server; resolves the backend
│       ├── decorator.py               # @tool — metadata only, no magic, no framework
│       ├── handler_loader.py          # "handler.py:Class" -> instance, with static params
│       ├── lifecycle.py               # background load, ready flag, unload, warmup
│       ├── predict_wrapper.py         # ABOVE THE SEAM: validation, batch-length check,
│       │                              # retry_singly isolation, error envelope
│       ├── schema.py                  # declared schema -> JSON Schema
│       ├── endpoints.py               # our contract routes: /health /ready /schema /info /unload
│       ├── settings.py                # TSWAP_* env contract -> RuntimeSettings
│       ├── errors.py
│       └── backends/                  # ── THE ONLY BentoML-AWARE DIRECTORY (05 §2) ──
│           ├── base.py                 # RuntimeBackend protocol; no framework import
│           ├── bentoml_backend.py     # v1: builds the service, batched API, mounts our routes
│           └── NATIVE.md              # the native backend: SPECIFICATION ONLY, no code in v1
│
├── docker/
│   ├── router.Dockerfile
│   └── base/
│       ├── cpu-py312.Dockerfile
│       ├── cuda-12.4-py312.Dockerfile
│       └── cuda-12.1-py310.Dockerfile
│
├── templates/                      # `tswap new --template X` — each must actually run
│   ├── cpu/          {tool.yaml, handler.py, requirements.txt, README.md}
│   ├── cuda/
│   ├── tensorflow/
│   └── function/
│
├── models/                         # the user's zoo (gitignored except examples)
│   ├── .gitignore
│   └── example_echo/               # a dependency-free model used by the test suite
│
├── tests/
│   ├── conftest.py                 # fakes: FakeBackend, FakeProbe, ManualClock
│   ├── unit/
│   │   ├── config/  scheduler/  lifecycle/  proxy/  api/  cli/
│   ├── runtime/                    # tool_swap_runtime
│   │   ├── contract/               # backend-agnostic; parameterised over backends,
│   │   │                           # runs against 'bentoml' only in v1 (05 §2.4)
│   │   └── test_predict_wrapper.py # length check, retry_singly, errors — pure, fast
│   ├── integration/                # @pytest.mark.docker — real containers
│   │   ├── test_swap_scenarios.py  # the scenarios in 06 §8
│   │   ├── test_cold_start.py
│   │   └── test_build_and_serve.py
│   └── e2e/
│       └── test_quickstart.py      # the README quickstart, executed
│
├── docs/
│   ├── quickstart.md
│   ├── adding-a-model.md           # the graduated ladder, user-facing
│   ├── configuration.md            # generated from the pydantic schema where possible
│   ├── api.md
│   ├── operations.md               # runbook, deployment, systemd
│   ├── architecture.md
│   └── adr/                        # decision records; seed from 13_OPEN_QUESTIONS.md
│
├── deploy/
│   ├── tswap.service               # systemd unit
│   └── prometheus/  grafana/       # optional dashboards
│
└── .github/workflows/
    ├── ci.yml                      # lint, type-check, unit + runtime tests
    ├── integration.yml             # docker tests (self-hosted or docker-in-docker)
    └── release.yml                 # build/push base images, publish packages
```

### Why this shape

- **`tool_swap` and `tool_swap_runtime` are strictly separate.** The router must never import the runtime and vice versa. Enforce it with an import-linter rule in CI, because a single convenience import would silently reintroduce the coupling we are trying to eliminate.
- **`backends/` is the only place `import bentoml` may appear**, and no BentoML type may cross into a signature outside it (**D14**, [`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §2.4). A second import-linter rule enforces it. Without that rule the framework spreads by convenience — R8's service idioms reached its authoring path exactly this way — and the seam that makes **D14** reversible quietly stops existing.
- **`NATIVE.md` is deliberately a document, not a package.** v1 ships one backend; the alternative is specified so that writing it is bounded work, and **not built speculatively**. If it ever acquires an `__init__.py`, that is a decision, taken and recorded — not a refactor.
- **The predict wrapper sits above the seam on purpose.** The batch-length check is safety-critical (returning one patient's result for another), so it must not depend on which framework formed the batch, and must stay unit-testable without a server.
- **`preflight/` owns one check registry, and `validate` is a filtered view of it** (**D17**, guardrail 13). Two implementations of "is this tool well-formed" would drift within a release, and CI and the author would then disagree about whether a tool is deployable — with the author believing whichever said yes. Each check declares `needs_docker` / `needs_gpu`, so `validate` is simply *the checks that need neither*, not a separate code path.
- **Checks are data, and the CLI is thin.** `cli/preflight.py` parses flags and renders; all logic lives in `preflight/`. That is what lets the same registry later back a CI gate and a `/ui` button without a rewrite ([`13_OPEN_QUESTIONS.md`](13_OPEN_QUESTIONS.md) D17, deferred alternatives).
- **`preflight/` may not import the router's `lifecycle/` or `scheduler/`.** It drives containers through the same `ContainerBackend` protocol but must remain usable with **no router, no `tools.yaml` entry and no GPU** (guardrail 12). If preflight ever needs the scheduler, it has stopped being the thing an author can run on a laptop.
- **`scheduler/policy.py` is pure.** No imports of httpx, docker, or the clock. This is where the product's core logic lives and it must stay trivially testable.
- **`backend/docker_backend.py` is the only Docker-aware file.** Everything else goes through the protocol.
- **The tree mirrors the plan documents**, so a reader can move between plan and code without a map.
- **`tests/` mirrors `src/`**, one test module per source module.

---

## 2. Naming

| Thing | Name |
|---|---|
| Repo | `tool-swap` |
| GitHub | `iar3-r8/tool-swap` (the org used by the parent project) |
| Router package | `tool_swap` (distribution `tool-swap`) |
| Runtime package | `tool_swap_runtime` (distribution `tool-swap-runtime`) |
| CLI | `tswap` |
| Container prefix | `ms-<model>` |
| Label namespace | `com.tool-swap.*` (`model`, `group`, `managed-by`, `runtime-version`, `config-hash`) |
| Env prefix | `TSWAP_` |
| Default port | `8600` |
| Base images | `tool-swap/base-cpu:py312`, `tool-swap/base-cuda:12.4-py312` |
| Built model images | `tool-swap/<model>:<config-hash>` + `:latest` |

Labels are load-bearing: reconciliation, `tswap ps`, `prune` and staleness detection all depend on them. Define them once, in one module, and never build a container without them.

---

## 3. Packaging

**Two distributions, one repo.** The runtime is installed into every model image, so its dependency closure must stay deliberate; the router's deps (docker SDK, typer, rich) must never leak into a model image.

- Router: `fastapi`, `uvicorn[standard]`, `pydantic>=2`, `httpx`, `docker` (or the compose/CLI shell-out), `typer`, `rich`, `pyyaml`, `python-dotenv`, `prometheus-client`.
- Runtime: **`bentoml==X.Y.Z` (pinned, and with no extras) plus its transitive set** — which already provides starlette, uvicorn, pydantic and click (**D14**, [`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §1.1). **Nothing else of our own choosing**: a direct dependency we add still needs written justification, but BentoML's own tree is accepted wholesale.

**Pin policy, three rules:**

1. **Pin `bentoml==X.Y.Z` with no extras.** Extras are not installed by default, and adding one silently enlarges every tool image.
2. **Check yank status before pinning and before upgrading.** A yanked release is installable when pinned exactly, which is precisely the situation an exact pin creates.
3. **Watch the constraints that actually bind.** ⚠️ Not pydantic/starlette/click — `starlette>=0.24.0` and `click>=7.0` are **lower bounds and cannot conflict**. The two-sided constraints are **`cattrs>=22.1.0,<23.2.0`**, a **seven-package OpenTelemetry family pinned to a beta series**, and `fsspec>=2025.7.0` ([`third-party-docs/bentoml/dependency-constraints.md`](third-party-docs/bentoml/dependency-constraints.md)). `resolve.yml` must report *these* when it fails.

The pin is the point. An unpinned serving framework in every model image is the version of **D14** that would actually hurt, because a background upgrade could break a model stack with no code change on our side. Upgrading BentoML is a deliberate change, gated on the backend contract suite passing, and it bumps `runtime_version` so `tswap doctor` can flag images built against the old one.

**The declared risk, and its instrumentation.** These pins compete with model authors' own pins, which is in tension with **D2**. The stance is *acceptable until a concrete model proves an unresolvable conflict* ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §1.1), so CI must be able to *detect* the proof: a resolution job runs `uv pip compile` (or `pip install --dry-run`) for every template and example against the pinned runtime, and fails on conflict. That job is the early-warning system for the whole decision; without it, the stance is a hope rather than a position.

Publish `tool-swap-runtime` to an index (PyPI or an internal one) so generated Dockerfiles can `pip install tool-swap-runtime==X.Y.Z`. Until then, build images with the wheel copied in from the repo — decide early, because the generated Dockerfile depends on it, and note that copying the wheel in makes model images depend on the repo checkout, which complicates building on another machine.

Python 3.12 for both. The runtime should support ≥3.10 so it can install into older vendor base images — an important constraint since exotic CUDA/TF images often lag. Test the runtime against 3.10, 3.11 and 3.12 in CI.

Use `uv` for dependency management and in generated Dockerfiles (`uv pip install`), with a pip fallback. Build speed is a real part of the authoring UX (**R2**): a scientist iterating on requirements will feel every minute.

---

## 4. Tooling

Adopt the parent project's conventions so contributors move between repos without friction:

- **ruff** for lint + format (the R8 repo uses ruff with a config at the root).
- **mypy** in strict mode on `src/`. The scheduler and config layers especially — they are pure data and benefit most.
- **pytest** with `pytest-asyncio`, `pytest-cov`, `pytest-mock`; markers `docker`, `gpu`, `slow`.
- **pre-commit**: ruff, ruff-format, mypy, end-of-file-fixer, a check that `tools.example.yaml` validates, and the import-linter boundary rule.
- **Coding style**: PEP 8, type hints everywhere, Google-style docstrings with the summary on the opening line, `pathlib` over `os.path`, f-strings, dataclasses for plain containers, no redundant comments. (Same rules as the parent project, which keeps reviews consistent.)
- **Zero warnings** policy: `-W error` in the test config for our own warnings.

---

## 5. CI

| Workflow | Runs | Contains |
|---|---|---|
| `ci.yml` | every PR | ruff, mypy, **both import-linter rules** (router ⊥ runtime, and bentoml ⊥ everything outside `backends/`), unit tests, runtime contract tests, `tswap validate --all` on the examples, the preflight check-registry tests (pure, with a fake backend), docs link check. **No Docker, no GPU — must finish in ~2 minutes.** |
| `resolve.yml` | PRs touching the runtime pins or any template; weekly | Dependency resolution of every template and example against the pinned runtime (`uv pip compile`). **This is the early-warning system for D14** — a failure here is the evidence that would reopen it, so its output must name the conflicting packages, not just fail. **Report the resolved `cattrs`, OpenTelemetry and `fsspec` versions explicitly**, since those are the constraints that can actually conflict. |
| `integration.yml` | PRs touching `backend/`, `lifecycle/`, or nightly | `@pytest.mark.docker` tests using the dependency-free `example_echo` model. Builds a real image, starts a real container, exercises swap/TTL/eviction. Also runs **`tswap preflight --strict` over the broken-tool corpus** ([`10_TESTING_STRATEGY.md`](10_TESTING_STRATEGY.md) §5.1), asserting each fixture fails exactly the check it was built to break — this is what keeps the gate's checks honest. |
| `release.yml` | tags | Build and push base images (multi-arch where feasible), publish both packages, generate release notes. |

The `example_echo` model is important: a model with **no dependencies beyond the base image** that builds in seconds, so integration tests exercise the real machinery without downloading gigabytes. Never let the integration suite depend on a real foundation model.

GPU tests (`@pytest.mark.gpu`) cannot run on hosted runners; keep them runnable manually and, if a self-hosted GPU runner exists, nightly. Design so that **nothing essential is only verifiable on a GPU** — the fakes must cover the logic.

---

## 6. Documentation set

Written for three distinct audiences; do not blur them:

| Audience | Doc | Answers |
|---|---|---|
| Operator | `README.md` quickstart + `docs/operations.md` | How do I launch it, see status, read logs, fix it? (**R1**) |
| Model author | `docs/adding-a-model.md` | How do I add my model without learning Docker? (**R2**) |
| Model author | `docs/preflight.md` | Will my tool deploy successfully? The stages, the verdicts, and what each failure means (**D17**) |
| Consumer | `docs/api.md` | How do I call a model? (**R3**) |
| Contributor | `docs/architecture.md` + `docs/adr/` | Why is it built this way? |

Rules: the README quickstart must be **executed by `tests/e2e/test_quickstart.py`** so it cannot rot. The configuration reference should be generated from the pydantic schema. Every template directory needs its own README. Seed `docs/adr/` from [`13_OPEN_QUESTIONS.md`](13_OPEN_QUESTIONS.md) so the reasoning survives the people.

---

## 7. What to copy from the R8 repo

Concrete, verbatim-portable material (all reproduced in [`12_REFERENCE_CODE.md`](12_REFERENCE_CODE.md)):

| From R8 | Use for |
|---|---|
| `CoreBatcher` | **Not used in v1.** BentoML's adaptive dispatcher does the batching (**D14**). Retained in [`12_REFERENCE_CODE.md`](12_REFERENCE_CODE.md) §7 as the specification and starting code for the `native` backend, should it ever be built. |
| BentoML `service_factory` | The *ideas*, not the style: bind the port then warm up on a background thread, a batched API with size and latency bounds, per-item validation so one bad item fails alone, and logging the effective knobs at boot. Its `globals()[...] = cls` idiom and swallowed warm-up exception are explicitly not ported ([`12_REFERENCE_CODE.md`](12_REFERENCE_CODE.md) §5). |
| `BentoServiceProcess` | The shape of process supervision: health polling, readiness polling, stream pumping, graceful-then-forced stop. Port the structure to containers, and **fix** its unbounded readiness loop. |
| `ToolServiceDescriptor` | The `/tools` descriptor shape (name, doc, input/output schema, version). Its `to_node_text()` renderer is **not** ported — we emit standard tool definitions instead (**D13**). |
| `RunEngineOutput` | The `status` / `payload` / `error_message` result envelope and the `extract_payload_or_raise()` convenience. |
| `class_tool` docs (`src/core/tools/README.md`) | The user-facing authoring guide; its lifecycle guidance ("avoid heavy work in `__init__`") is already correct. |
| Config `defaults` + per-model overrides | Our config shape, with `extra="forbid"` added. |
| `Batchable[T]` | The batching declaration concept (as YAML, optionally as a type alias). |
| Logging conventions (loguru, `.jsonl`, `jq`, request-id middleware) | `observability/`. |

Do **not** port: `Modality`/`ModalityType` (a closed enum, replaced by JSON Schema + `x-semantic` per **D13**), `ToolContext.run_tool` recursion (orchestration, and a deadlock risk), the Hydra config system (overkill for one YAML file), the auth layer, the tool auto-discovery-by-module-import mechanism (impossible across container boundaries by design).

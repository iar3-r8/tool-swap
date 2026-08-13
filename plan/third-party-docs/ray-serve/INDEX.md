# Ray Serve documentation — annotated catalogue

**Root URL:** https://docs.ray.io/en/latest/serve/index.html
**Ray version at capture:** 2.57.0
**Captured:** 2026-08-13
**Extracted by:** Oxylabs `universal_scraper` MCP tool (`output_format: md`), page by page.

This directory holds local copies of the Ray Serve documentation pages that bear on [`15_RAY_SERVE_EVALUATION.md`](../../15_RAY_SERVE_EVALUATION.md) and [`ADR-0003`](../../adr/0003-ray-serve-not-adopted.md), plus a catalogue of every page in the Ray Serve section — including those **not** captured — so a future reader knows what exists and where to look without re-crawling.

Every captured file keeps the source URL, the Ray version, and a **tool-swap notes** section relating its content to our decisions (**D2**, **D5**, **D7**, **D9**, **D14**, **D25**, **D26**), requirements (**R1**–**R4**) and the open questions in §9 of the evaluation.

> **Note on quoting.** Captured pages are lightly reformatted (nav chrome, Anyscale banners and image markup stripped; admonitions turned into blockquotes). Prose and code are verbatim, so quotations taken from these files are safe to cite. Two files — [`monitoring.md`](monitoring.md) and [`api-reference.md`](api-reference.md) — are explicitly **condensed** and say so at the top.

---

## 1. What was captured

| Local file | Source page | Ray version | What it supplies | Bears on |
| --- | --- | --- | --- | --- |
| [`advanced-guides/multi-app-container.md`](advanced-guides/multi-app-container.md) | `/serve/advanced-guides/multi-app-container.html` | 2.57.0 | `image_uri` per application; **Ray/Python patch-level lockstep**; Podman prerequisite; `--privileged`; experimental + already-deprecated `container` field; `vfs` slow-startup warning; env-var propagation list | **D2** ✓ satisfiable; open questions 2, 6 |
| [`advanced-guides/inplace-updates.md`](advanced-guides/inplace-updates.md) | `/serve/advanced-guides/inplace-updates.html` | 2.57.0 | Lightweight vs code updates; `user_config` → `reconfigure()`; `num_replicas` lightweight; **`ray_actor_options` is a code update that restarts replicas**; production warning about graph updates | **D9**, **D25**, **D7**; open questions 8, 9, 10, 11 |
| [`model-multiplexing.md`](model-multiplexing.md) | `/serve/model-multiplexing.html` | 2.57.0 | `@serve.multiplexed`, `max_num_models_per_replica`, LRU eviction, `__del__` as unload hook, batch-splitting by model ID, matching timeout | **D9** within a replica; corrects [`14_ALTERNATIVES_EVALUATION.md`](../../14_ALTERNATIVES_EVALUATION.md) §2.2 |
| [`resource-allocation.md`](resource-allocation.md) | `/serve/resource-allocation.html` | 2.57.0 | GPU assignment via `ray_actor_options`; fractional GPUs; full actor-options list including `runtime_env`; `OMP_NUM_THREADS` behaviour | **D7**, **D28** |
| [`configure-serve-deployment.md`](configure-serve-deployment.md) | `/serve/configure-serve-deployment.html` | 2.57.0 | All eleven per-deployment parameters; `max_queued_requests` back-pressure; `check_health`; whole-dictionary override rule | **R4**, guardrail 10 |
| [`multi-app.md`](multi-app.md) | `/serve/multi-app.html` | 2.57.0 | "One application is a unit of upgrade"; independent add/remove/update; `serve status` output; **Ray naming our use case** ("co-host them to increase hardware utilization"); `serve.get_app_handle` | **R1**, **R3**; §2.1 of the evaluation |
| [`advanced-guides/advanced-autoscaling.md`](advanced-guides/advanced-autoscaling.md) | `/serve/advanced-guides/advanced-autoscaling.html` | 2.57.0 | **`min_replicas = 0` explicitly costs a cold start**; `downscale_to_zero_delay_s`; the metrics pipeline; **custom autoscaling policies**; **application-level policies**; **external scaling REST API** | **NEW EVIDENCE** — see §3 |
| [`autoscaling-guide.md`](autoscaling-guide.md) | `/serve/autoscaling-guide.html` | 2.57.0 | `num_replicas: auto` defaults; `target_ongoing_requests`; Serve autoscaler vs Ray autoscaler | **D25**; open question 9 |
| [`architecture.md`](architecture.md) | `/serve/architecture.html` | 2.57.0 | Controller / proxy / replica actors; **request queues until a replica of its own deployment frees up**; fault tolerance; "without KubeRay, if the Ray cluster fails, Serve cannot recover"; 100KiB object-store threshold | **D25**; open question 7; guardrail 8 |
| [`key-concepts.md`](key-concepts.md) | `/serve/key-concepts.html` | 2.57.0 | deployment / replica / application / ingress vocabulary; FastAPI ingress | Needed to read every other page; §4.3 granularity argument |
| [`advanced-guides/dyn-req-batch.md`](advanced-guides/dyn-req-batch.md) | `/serve/advanced-guides/dyn-req-batch.html` | 2.57.0 | `@serve.batch` parameters; **fixed window, not adaptive**; runtime tuning via `reconfigure()`; **`batch_size_fn`**; streaming `StopIteration` protocol | **D5**, **D14**; **answers open question 5** |
| [`production-guide/config.md`](production-guide/config.md) | `/serve/production-guide/config.html` | 2.57.0 | Full config schema; proxy/HTTP/gRPC/logging options; **`user_config` "adjust model weights and versions without restarting the cluster"**; `external_scaler_enabled` | **D9**; open question 8; **R4** |
| [`production-guide/handling-dependencies.md`](production-guide/handling-dependencies.md) | `/serve/production-guide/handling-dependencies.html` | 2.57.0 | **Per-deployment conflicting dependencies via `ray_actor_options.runtime_env`**, with a two-versions-of-`requests` example; delayed-import guidance | **NEW EVIDENCE** — see §3 |
| [`monitoring.md`](monitoring.md) *(condensed)* | `/serve/monitoring.html` | 2.57.0 | Status vocabulary; logging model; **`ray_serve_replica_startup_latency_ms`, `..._reconfigure_latency_ms`, multiplexed load/unload latency, `ray_component_rss_bytes`**; no VRAM metric | **R1**; instruments open questions 6, 7, 8, 9 |
| [`api-reference.md`](api-reference.md) *(condensed)* | `/serve/api/index.html` | 2.57.0 | Python API inventory; full CLI with flags; REST API; `serve.delete`; `RequestRouter` interface; `serve controller-health` | **R1**, **R2**; open question 10 |
| [`../ray-core/runtime-env-excerpt.md`](../ray-core/runtime-env-excerpt.md) *(excerpt)* | `/ray-core/handling-dependencies.html` | 2.57.0 | Authoritative `runtime_env` field list including **`image_uri`**; per-actor scoping; **version lockstep confirmed independently**; caching and inheritance | **D2**; §4.2 of the evaluation |

---

## 2. What was not captured, and what is in it

Listed so that a future reader can judge whether to fetch it rather than assuming it was considered and rejected.

### Ray Serve core pages

| Page | Contents | Why skipped |
| --- | --- | --- |
| `/serve/index.html` | Landing page: quickstart snippet, feature list, links | Navigational only; its link inventory is this catalogue |
| `/serve/getting_started.html` | First deployment walkthrough, converting an existing model | Tutorial; no decision-bearing facts |
| `/serve/develop-and-deploy.html` | Develop-locally-then-deploy narrative | Tutorial |
| `/serve/model_composition.html` | `DeploymentHandle` composition, DAGs | Orchestration is the caller's job for us ([`00_CONTEXT_AND_MOTIVATION.md`](../../00_CONTEXT_AND_MOTIVATION.md) §2.5) — **would matter if we ever adopted Ray-side composition** |
| `/serve/model-registries.html` | Loading models from MLflow and similar | Possibly relevant to our model-reference resolver (**D18**); worth a look if that design is revisited |
| `/serve/http-guide.html` | FastAPI integration, request/response handling, keep-alive | **R3** detail; our proxy contract is already settled ([`04_API_CONTRACT.md`](../../04_API_CONTRACT.md)) |
| `/serve/asynchronous-inference.html` | `@task_consumer`, queue-backed async inference, `AsyncInferenceAutoscalingPolicy` | Not in scope for v1 — **but it is Ray's answer to long-running jobs and would be relevant if we ever add async submission** |
| `/serve/examples.html` | Example gallery | Illustrative |
| `/serve/architecture.html#autoscaling` | (captured) | — |

### Production guide

| Page | Contents | Why skipped |
| --- | --- | --- |
| `/serve/production-guide/index.html` | Overview of the production path | Index |
| `/serve/production-guide/kubernetes.html` | RayService CRD, KubeRay deployment | We are not on Kubernetes ([ADR-0001](../../adr/0001-build-our-own-router.md)) |
| `/serve/production-guide/docker.html` | Building custom Docker images for the **cluster** (not per-application) | Cluster-image concern; distinct from `image_uri`. **Worth reading if Ray is reconsidered**, since it governs how our base images would be built |
| `/serve/production-guide/fault-tolerance.html` | End-to-end fault tolerance, GCS FT, replica recovery | Relevant to guardrail 8 if Ray is adopted |
| `/serve/production-guide/best-practices.html` | Production checklist | Short; largely points elsewhere |

### Advanced guides

| Page | Contents | Why skipped |
| --- | --- | --- |
| `/serve/advanced-guides/app-builder-guide.html` | Passing typed arguments to applications | Config-authoring detail |
| `/serve/advanced-guides/asyncio-best-practices.html` | Blocking-code pitfalls in async handlers | Relevant to Role B and to writing a custom policy |
| `/serve/advanced-guides/performance.html` | Performance tuning, `max_ongoing_requests` guidance | Would matter for a real benchmark |
| `/serve/advanced-guides/dev-workflow.html` | Local iteration loop, `serve run` | **R2** detail |
| `/serve/advanced-guides/grpc-guide.html` | gRPC service setup | We are HTTP-only |
| `/serve/advanced-guides/replica-ranks.html` | Stable ranks across replicas | For distributed training-style workloads |
| `/serve/advanced-guides/replica-scheduling.html` | How replicas are placed on nodes | **Potentially relevant to D7** — placement is adjacent to device pinning. Not read |
| `/serve/advanced-guides/gang-scheduling.html` | Co-scheduling groups of replicas | Multi-GPU sharding; Role C |
| `/serve/advanced-guides/custom-request-router.html` | Implementing the `RequestRouter` interface | **Potentially interesting**: the second extension point noted in [`api-reference.md`](api-reference.md). Not read |
| `/serve/advanced-guides/deployment-scoped-actors.html` | Actors shared across a deployment's replicas | Not read |
| `/serve/advanced-guides/deploy-vm.html` | `serve deploy` against a remote VM cluster | Closest to our DGX topology; **worth reading if Ray is reconsidered** |
| `/serve/advanced-guides/managing-java-deployments.html` | Experimental Java API | Irrelevant |
| `/serve/advanced-guides/multi-node-gpu-troubleshooting.html` | Multi-node GPU issues on KubeRay | Kubernetes-specific |

### Serve LLM (~30 pages)

`/serve/llm/*` — quickstart, configuration reference, multi-LoRA, fractional GPU serving, prefill/decode disaggregation, KV cache offloading, prefix-aware routing, vLLM/SGLang integration, architecture, benchmarks, troubleshooting.

**Not captured.** Our zoo is embeddings, classifiers and segmentation models, not LLM inference. Two pages might repay a look if that changes:

- `/serve/llm/user-guides/multi-lora.html` — multiplexing applied to adapters, the closest production use of the LRU residency primitive.
- `/serve/llm/user-guides/fractional-gpu.html` — Ray's most developed statement on GPU sharing, which is the **D7** counterargument.

### Ray Core and cluster pages

Referenced by the Serve docs but outside this extraction: `/ray-core/scheduling/resources.html`, `/ray-core/scheduling/accelerators.html`, `/ray-core/actors.html`, `/ray-observability/*`, `/cluster/*`. Only [`../ray-core/runtime-env-excerpt.md`](../ray-core/runtime-env-excerpt.md) was taken.

---

## 3. Findings that post-date `15_RAY_SERVE_EVALUATION.md`

**Three pages captured here were not part of that document's evidence base, and each moves the argument.** Recorded so the evaluation can be revised deliberately rather than drifting.

### 3.1 `min_replicas: 0` means a cold start — open question 9 leans negative

[`advanced-guides/advanced-autoscaling.md`](advanced-guides/advanced-autoscaling.md) states it directly: *"setting `min_replicas = 0` causes higher tail latencies; when you start sending traffic, the deployment scales up, and there will be a **cold start time**"*, and justifies `downscale_delay_s` as a way to *"avoid reinitialization costs when the application needs to upscale again"*.

**Consequence:** `num_replicas: 0` is our *hard stop*, not our soft unload. **`reconfigure()` (open question 8) is the only remaining candidate for `IDLE_SOFT` on Ray**, which raises the value of Spike D step 7 and lowers that of step 8.

### 3.2 Ray has two pluggable decision points, and one REST scaling API

Also from [`advanced-guides/advanced-autoscaling.md`](advanced-guides/advanced-autoscaling.md):

- **Custom autoscaling policies** — a user function receiving `AutoscalingContext` (queue depths, per-replica counts, capacity bounds, custom metrics, persisted state, timestamps), run by the controller every 0.1s.
- **Application-level policies** — one function receiving `dict[DeploymentID, AutoscalingContext]` for *every deployment in the application at once*, returning targets for all of them. **Structurally, that is a scheduler interface.**
- **External scaling API** — `POST /api/v1/applications/{app}/deployments/{deployment}/scale`, idempotent, surviving `serve deploy`, mutually exclusive with built-in autoscaling.

Plus, from [`api-reference.md`](api-reference.md), a documented abstract `RequestRouter` interface.

**Consequence:** the claim that "we would be writing the scheduler either way, and Ray gives us nowhere good to put it" is **weaker than the evaluation states**. Ray provides a designed home for exactly this logic. What it does not provide is a *residency* decision — every hook's output is a replica count.

### 3.3 Per-deployment dependency isolation is documented — the "one tool = one application" mapping may be unnecessary

[`production-guide/handling-dependencies.md`](production-guide/handling-dependencies.md) shows conflicting Python dependencies **per deployment** via `ray_actor_options={"runtime_env": ...}`, with our exact motivating example (TF1 alongside TF2). [`../ray-core/runtime-env-excerpt.md`](../ray-core/runtime-env-excerpt.md) confirms `image_uri` is a `runtime_env` field and that `runtime_env` is settable per-actor. [`resource-allocation.md`](resource-allocation.md) lists `runtime_env` as a valid `ray_actor_options` key.

**If `image_uri` works inside `ray_actor_options`**, then many separately-containerised tools can live in **one** application, and an application-level autoscaling policy could coordinate all of them. That combination — per-tool images plus one coordinating policy plus per-deployment `reconfigure()` — is much closer to a Ray-native tool-swap than the evaluation contemplates.

**Counter-evidence:** [`advanced-guides/multi-app-container.md`](advanced-guides/multi-app-container.md) presents `image_uri` as per-**application** (*"all deployment replicas in the applications start and run in containers with the respective images"*) and says it composes only with `config` and `env_vars`. **The documentation does not resolve this. It must be tested.**

### 3.4 Suggested additions to §9 of the evaluation

| # | Proposed open question | How to settle |
| --- | --- | --- |
| 12 | Does `ray_actor_options={"runtime_env": {"image_uri": ...}}` give a **per-deployment** container, or is `image_uri` application-scoped only? | Deploy one application with two deployments carrying different `image_uri` values; check which image each replica runs |
| 13 | Can an **application-level autoscaling policy** coordinate deployments that are separately containerised — and can any policy observe deployments in *other* applications? | Implement a trivial application-level policy and inspect the `contexts` dict it receives |
| 14 | What does `serve controller-health` report when config updates are driven at request cadence? | Run the sustained alternation of open question 10 and watch control-loop duration |
| 15 | Ray's own metrics can answer questions 6, 7, 8 and 9 directly — is Spike D instrumented with them rather than ad-hoc timing? | Use `ray_serve_replica_startup_latency_ms`, `ray_serve_replica_reconfigure_latency_ms`, `ray_component_rss_bytes` − `ray_component_shared_bytes` |

Open question **5 can now be closed**: `@serve.batch` is a fixed-window dispatcher, not latency-adaptive like BentoML's, though it is runtime-tunable through `reconfigure()` and has a `batch_size_fn` feature we lack. See [`advanced-guides/dyn-req-batch.md`](advanced-guides/dyn-req-batch.md).

**None of this reverses the recommendation on its own.** The hinge is unchanged and unmeasured: **can `reconfigure()` genuinely return VRAM from a live replica?** Ray's documentation says `user_config` can *"adjust model weights and versions without restarting the cluster"*, but nowhere claims device memory is released — and that is a PyTorch/CUDA question Ray's docs cannot answer.

---

## 4. Reproducing or extending this extraction

Pages were fetched one at a time with the Oxylabs MCP `universal_scraper` tool:

```
universal_scraper(url="https://docs.ray.io/en/latest/serve/<page>.html", output_format="md")
```

`output_format: "links"` on the index page produced the full link inventory that §1 and §2 are built from.

**Tooling gap worth knowing about:** the Oxylabs **AI Studio** tools (`ai_map`, `ai_crawler`, `ai_scraper`, `ai_search`, `ai_browser_agent`) would have crawled the whole section in one call, but they fail with:

> Oxylabs AI Studio API key is not provided. Set the `OXYLABS_AI_STUDIO_API_KEY` environment variable in the MCP server configuration.

[`.roo/mcp.json`](../../../.roo/mcp.json) supplies `OXYLABS_USERNAME` and `OXYLABS_PASSWORD` (Web Scraper API) but no AI Studio key, so only `universal_scraper`, `google_search_scraper` and the Amazon scrapers work. Adding `OXYLABS_AI_STUDIO_API_KEY` to the `oxylabs` server's `env` block would make bulk documentation extraction a single call in future.

**When re-capturing:** Ray's docs are versioned, and `/en/latest/` moves. Every file records the version it was taken at (2.57.0). If a claim in [`15_RAY_SERVE_EVALUATION.md`](../../15_RAY_SERVE_EVALUATION.md) turns on an experimental feature — `image_uri`, custom autoscaling policies, the external scaling API — **re-check it against the current version before relying on it**, since two of these have already churned once.

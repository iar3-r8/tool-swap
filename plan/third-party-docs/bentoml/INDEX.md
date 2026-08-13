# BentoML documentation — annotated catalogue

**Root URL:** https://docs.bentoml.com/en/latest/
**BentoML version at capture:** **1.4.39** (latest on PyPI, published 2026-05-07; `requires-python >=3.9`)
**Captured:** 2026-08-13
**Extracted by:** Oxylabs `universal_scraper` MCP tool (`output_format: md`), page by page, plus the PyPI JSON API and two files read from the GitHub repository.

This directory holds local copies of the BentoML documentation that **D14** rests on — the decision to build `tool_swap_runtime` on BentoML ([`05_RUNTIME_AND_BATCHING.md`](../../05_RUNTIME_AND_BATCHING.md) §1) — plus a catalogue of what was not captured and why.

> **This capture differs in kind from [`ray-serve/`](../ray-serve/INDEX.md).** That one is evidence for a **rejection** ([ADR-0003](../../adr/0003-ray-serve-not-adopted.md)) and only had to be good enough to justify not proceeding. **BentoML is adopted**, and [`09_IMPLEMENTATION_PLAN.md`](../../09_IMPLEMENTATION_PLAN.md) M4 builds `backends/bentoml_backend.py` directly on it. These files are therefore *working reference material for M3.5 and M4*, and their job is to make specific plan claims checkable. Several turned out not to be.

**Scope:** what phase 1 needs — **M3.5** (the spike) and **M4** (the runtime), with tails into M5 (base images), M5.5 (preflight) and M7 (metrics). BentoCloud, the examples gallery and the per-framework model APIs are excluded; see §2.

---

## 1. What was captured

| Local file | Source | What it supplies | Bears on |
| --- | --- | --- | --- |
| [`adaptive-batching.md`](adaptive-batching.md) | `/get-started/adaptive-batching.html` | The dispatcher's adaptive behaviour in the vendor's own words; `batchable`, `max_batch_size`, `max_latency_ms`, `batch_dim`; the one-parameter rule and the Pydantic composite-input pattern; *"the order of the requests in a batch is not guaranteed"*; 503 on latency overrun | **D5**, **D14**, **D15**; **the citation D14 never had** |
| [`sdk-reference.md`](sdk-reference.md) *(condensed)* | `/reference/bentoml/sdk.html` | Signatures and **defaults** for `@bentoml.service`, `@bentoml.api`, `asgi_app`, `depends`; `batch_dim` output-splitting semantics; `path_prefix` | **D14**, [`02 §7`](../../02_CONFIGURATION.md), M4 |
| [`health-endpoints-and-lifecycle-source.md`](health-endpoints-and-lifecycle-source.md) *(source excerpt)* | `BaseAppFactory`, `ServiceAppFactory` on GitHub `main` | `/livez` `/healthz` `/readyz` `/metrics` route table; readiness implementation; **the blocking lifespan**; `threads=1` limiter; `ServiceUnavailable("process is overloaded")`; error mapping | **[`05 §3`](../../05_RUNTIME_AND_BATCHING.md), §3.2, §6** — the M4 trap |
| [`lifecycle-hooks.md`](lifecycle-hooks.md) | `/build-with-bentoml/lifecycle-hooks.html` | Four lifecycle stages; `on_deployment` / `on_startup` / `on_shutdown`; **`__is_alive__` and `__is_ready__` documented**; *"before any API endpoints become available"* | [`05 §6`](../../05_RUNTIME_AND_BATCHING.md), [`01 §4`](../../01_ARCHITECTURE.md), [ADR-0004](../../adr/0004-hard-stop-only-in-v1.md) |
| [`asgi-mounting.md`](asgi-mounting.md) *(condensed)* | `/build-with-bentoml/asgi.html` | `@bentoml.asgi_app`; `get_current_service()`; prefix paths; `add_asgi_middleware` | **[`05 §3`](../../05_RUNTIME_AND_BATCHING.md) — the mechanism our whole contract uses**; M3.5 step 5 |
| [`workers-and-devices.md`](workers-and-devices.md) | `/build-with-bentoml/parallelize-requests.html` | `workers`, `cpu_count`, `worker_index` → CUDA device; *"each worker will load a copy of the model"*; workers vs concurrency | [`05 §5`](../../05_RUNTIME_AND_BATCHING.md), **D7**, [`02 §7`](../../02_CONFIGURATION.md) |
| [`metrics.md`](metrics.md) *(condensed)* | `/build-with-bentoml/observability/metrics.html` | The four default metrics and their dimensions; `namespace`; bucket rules; custom metrics via `prometheus_client` | **R1**, [`05 §9`](../../05_RUNTIME_AND_BATCHING.md), M3.5 step 4 |
| [`error-handling.md`](error-handling.md) | `/build-with-bentoml/error-handling.html` | Custom exceptions; **"BentoML reserves error codes 401, 403, and any above 500"** | [`04 §6`](../../04_API_CONTRACT.md), `retry_singly` |
| [`dependency-constraints.md`](dependency-constraints.md) *(packaging metadata)* | PyPI JSON API | The real `requires_dist`; extras; yanked releases | **D14's stated risk**, M3.5 steps 1–2, `resolve.yml` |

---

## 2. What was not captured, and why

### Deliberately excluded

| Section | Contents | Why skipped |
| --- | --- | --- |
| `/scale-with-bentocloud/*` (~20 pages) | Deployments, autoscaling, secrets, API tokens, Codespaces, BYOC, canary deploys, gateways | **BentoCloud is the commercial product.** We use the OSS framework as a library inside our own container. Its autoscaling is a competing answer to the same problem tool-swap solves, and adopting any of it would undo **D2** |
| `/examples/*` (11 pages) | vLLM, LangGraph, ShieldGemma, RAG, SDXL, ComfyUI, ControlNet, MLflow, XGBoost | Illustrative. LLM-centric, and LLMs live in llama-swap ([`00 §4`](../../00_CONTEXT_AND_MOTIVATION.md)) |
| `/reference/bentoml/frameworks/*` (18 pages) | `bentoml.pytorch`, `bentoml.tensorflow`, `bentoml.transformers`, … | **We do not use BentoML's model store.** Our handler loads its own weights (**D18**, model references). These APIs are a parallel answer we decline |
| `/reference/bentoml/stores.html`, `bento-build-options.html`, `container.html` | Bentos, `bentoml build`, `bentoml containerize` | **BentoML's packaging model is a competing answer to D2.** We generate our own Dockerfiles (M5) and our entrypoint is ours, not `bentoml serve` ([`03 §6`](../../03_TOOL_AUTHORING.md:353)). Worth reading only if that decision is ever revisited |

### Relevant, not yet captured — the honest list

| Page | Contents | Why it matters, and to whom |
| --- | --- | --- |
| `/build-with-bentoml/services.html` | `@bentoml.service` in depth; `traffic`, `resources`, `workers` kwargs | **The `**kwargs` gap in [`sdk-reference.md`](sdk-reference.md) §7.** `traffic={"timeout": …}` interacts with our `queue_timeout` (**D22**). **Capture before M4** |
| `/reference/bentoml/configurations.html` | The full configuration reference | Same gap; also the `endpoints.livez` / `endpoints.readyz` keys seen in source. **Capture before M4** |
| `/build-with-bentoml/iotypes.html` | Input/output types, Pydantic models, file handling | Bears on **D13** (schema) and **D18** (large payloads by reference). Our compiler owns the schema, so this is secondary — but the composite-input pattern for **D15** lives here |
| `/build-with-bentoml/runtime-environment.html` | `bentoml.images.Image`, `python_packages` | BentoML's in-image dependency model — a competing answer to M5. Read to *avoid*, and to check the M3.5 resolution assumptions |
| `/build-with-bentoml/observability/logging.html` | Access logs, log format, request IDs | [`05 §8`](../../05_RUNTIME_AND_BATCHING.md) requires folding BentoML's logger into ours. **Needed for M4**, low risk |
| `/build-with-bentoml/gpu-inference.html` | GPU allocation, CUDA setup | Overlaps [`workers-and-devices.md`](workers-and-devices.md); would settle the `resources={"gpu": N}` translation |
| `/build-with-bentoml/testing.html` | Testing API endpoints | Relevant to [`10_TESTING_STRATEGY.md`](../../10_TESTING_STRATEGY.md) §4.2's contract suite |
| `/reference/bentoml/cli.html` | The `bentoml` CLI | We do not use it (our entrypoint is ours), but `bentoml serve` flags may matter for debugging |
| `/build-with-bentoml/model-loading-and-management.html` | Model store, `bentoml.models` | The competing answer to **D18**. Read if the model-reference resolver is revisited |
| `/get-started/hello-world.html`, `/services.html` quickstarts | Tutorials | No decision-bearing content |
| `/build-with-bentoml/streaming.html`, `websocket.html`, `gradio.html` | Streaming, WebSockets, UI | Out of scope: our contract is request/response ([`04`](../../04_API_CONTRACT.md)); no UI in a tool image |
| `/get-started/async-task-queues.html`, `/reference/bentoml/batch.html` | `@bentoml.task`, offline batch inference | Not in v1. **Would matter if async submission is ever added** — `@bentoml.task` is BentoML's answer to long-running jobs |
| `/get-started/model-composition.html`, `/build-with-bentoml/distributed-services.html` | `bentoml.depends`, multi-service graphs | Orchestration is the caller's job ([`00 §2.5`](../../00_CONTEXT_AND_MOTIVATION.md)). **But the D15 composite-input pattern uses `depends`**, so this becomes relevant if that route is taken |
| `/build-with-bentoml/observability/tracing.html`, `monitoring-and-data-collection.html` | OTel tracing, data collection | Not in v1. Note from [`dependency-constraints.md`](dependency-constraints.md) that the OTel tree ships in every image regardless |

---

## 3. Findings — what this capture changes

**Nine findings. Three confirm the plan, six correct it.** None overturns **D14**; two would have cost real time in M4.

### 3.1 ✅ **D14's central claim is now sourced** — [`adaptive-batching.md`](adaptive-batching.md) §1

[`05 §4.1`](../../05_RUNTIME_AND_BATCHING.md:173)'s "adaptive dispatcher" claim was **uncited anywhere in `plan/`**, despite being the sole technical reason for choosing BentoML over our own batcher and over `@serve.batch`. The vendor states it directly: *"continuously adjusts batch size and window based on real-time traffic patterns"*, and `max_latency_ms` is respected *"by predicting the time it takes to process the batch"*. **Quotable.** Caveat: it says *that* the window adapts, never *how* — M3.5 step 4 still earns its place.

### 3.2 ✅ **The contract mechanism is real** — [`asgi-mounting.md`](asgi-mounting.md), [`health-endpoints-and-lifecycle-source.md`](health-endpoints-and-lifecycle-source.md) §1–2

`@bentoml.asgi_app` is a documented first-class decorator; `/livez` `/healthz` `/readyz` `/metrics` exist at the paths [`05 §3`](../../05_RUNTIME_AND_BATCHING.md:146) assumes; and [`05 §3.2`](../../05_RUNTIME_AND_BATCHING.md:159)'s claim that `/readyz` means *server-up, not weights-loaded* is confirmed in code (`mark_as_ready` flips a flag in an `on_startup` hook). **R8 polling `/readyz` really did prove nothing.**

### 3.3 ⚠️ **The bind-then-load design is mandatory, not stylistic — and this is the M4 trap**

[`lifecycle-hooks.md`](lifecycle-hooks.md) §1 and [`health-endpoints-and-lifecycle-source.md`](health-endpoints-and-lifecycle-source.md) §4. Startup hooks run *"before any API endpoints become available"*, and `lifespan` awaits `create_instance` — which runs `__init__` — **before** the socket accepts connections.

**If M4 loads the handler in `__init__` or an `on_startup` hook, then during a four-minute load the router gets connection refused, not a 503 with `reason: loading`.** That breaks [`05 §3`](../../05_RUNTIME_AND_BATCHING.md:147) (*"`/health` must answer before weights load"*), makes `LOADING` unobservable ([`01 §4`](../../01_ARCHITECTURE.md)), and makes two M4 contract tests untestable. A load failure would exit the process rather than expose a traceback.

**R8's background warm-up thread is vindicated** — it was the only way to bind before loading, not a quirk. [`05 §6`](../../05_RUNTIME_AND_BATCHING.md:299) says "bind-then-load is kept from R8"; it should say *why it is required*.

### 3.4 ⚠️ **[`05 §9`](../../05_RUNTIME_AND_BATCHING.md:353) promises a metric that does not exist** — [`metrics.md`](metrics.md) §1

`tswap_queue_wait_seconds` is attributed to "BentoML dispatcher". **There is no such metric.** BentoML provides `request_in_progress`, `request_total`, `request_duration_seconds` and `adaptive_batch_size`. Queue wait — the key diagnostic for tuning `max_wait_ms` — must be measured above the seam or dropped.

Conversely, `metrics={"namespace": "tswap"}` renames the whole default set, giving us most of [`05 §9`](../../05_RUNTIME_AND_BATCHING.md:353)'s names **free**.

### 3.5 ⚠️ **D14's dependency risk is aimed at the wrong packages** — [`dependency-constraints.md`](dependency-constraints.md) §1–2

*"Locked pins (pydantic, starlette, click)"* appears in five plan documents. In 1.4.39: `pydantic<3` (upper bound only), `starlette>=0.24.0` and `click>=7.0` (**lower** bounds — they cannot conflict). The real constraints are **`cattrs<23.2.0,>=22.1.0`**, a **seven-package OpenTelemetry family pinned to a beta series**, and `fsspec>=2025.7.0` — none named anywhere in `plan/`. M3.5 step 1 currently instructs the spike to measure the three least informative packages.

### 3.6 ⚠️ **D15 has a documented alternative remedy** — [`adaptive-batching.md`](adaptive-batching.md) §2

The one-parameter constraint behind **D15** is confirmed. But BentoML documents a second remedy — bundle parameters into a Pydantic model so **each batched item carries its own** — using our exact motivating example (`image` + `threshold`). D15's static-param rule is right for parameters that change the batched computation, and over-broad for per-item post-processing knobs, probably the commoner case. Cost of the documented pattern: a wrapper Service via `bentoml.depends`.

### 3.7 ⚠️ **`worker_index` is documented inconsistently — and the plan's criticism of R8 is unfair** — [`workers-and-devices.md`](workers-and-devices.md) §1–2

The same section says the index starts at `0` and, three paragraphs later, that it is 1-based and you must subtract 1. R8's `gpu_id = max(0, worker_index - 1)` — called *"fragile and off-by-one-prone"* in two plan documents — **is the vendor's documented idiom, with an added guard**. The design conclusion stands (pass an explicit device list); the criticism of R8 should be re-worded, and M3.5 must observe the actual value.

### 3.8 ⚠️ **BentoML reserves HTTP ≥500, and strips those messages** — [`error-handling.md`](error-handling.md) §1

*"BentoML reserves error codes 401, 403, and any above 500."* The source replaces the body of any ≥500 response with a fixed generic string. Our contract uses 503 in two meanings, and `ServiceUnavailable("process is overloaded")` loses its cause this way. Our mounted `/ready` sidesteps this; the `/predict` path must not encode meaning in the status alone.

### 3.9 ⚠️ **`max_latency_ms = 60000` is BentoML's default, not R8's mistake** — [`sdk-reference.md`](sdk-reference.md) §2

[`02 §7`](../../02_CONFIGURATION.md:345) calls it *"a nonsensical `60000`"* chosen by R8. It is the framework default, which every tool inherits unless overridden. The conclusion strengthens — **always pass `max_latency_ms` and `max_batch_size` explicitly** — but the attribution is wrong.

---

## 4. Amendments — ✅ **APPLIED 2026-08-13**

**These were originally recorded as "proposed, not applied", per the old reading of rule 2.** That convention was reversed on the requester's instruction — *"the goal of this exercise is to improve the plan"* — and every item below is now **in** the plan document named. See [`../README.md`](../README.md) rule 2 and [`plans/capture-refinement-proposals.md`](../../../plans/capture-refinement-proposals.md) for the verdicts.

| # | Document | Change | Status |
| --- | --- | --- | --- |
| 1 | [`05 §6.1`](../../05_RUNTIME_AND_BATCHING.md), [`09 M4`](../../09_IMPLEMENTATION_PLAN.md) | Background loading stated as **required, not preferred**, with the four things that break otherwise; load state read by both `/ready` and `__is_ready__` | ✅ Applied — new §6.1 *"the M4 trap"* |
| 2 | [`09 M3.5`](../../09_IMPLEMENTATION_PLAN.md) | Step 1 now records `cattrs`, the OTel set, `fsspec`, `numpy`. Step 5 gains the blocking-startup probe, the root-mount check, the `worker_index` observation, the poisoned-item test, a non-root check, and the ADR-0005 wrapper question | ✅ Applied |
| 3 | [`05 §9`](../../05_RUNTIME_AND_BATCHING.md) | `tswap_queue_wait_seconds` **removed** with an explanation; `request_in_progress` added; `metrics={"namespace": "tswap"}` named | ✅ Applied |
| 4 | [`05 §1.1`](../../05_RUNTIME_AND_BATCHING.md), [`13 D14`](../../13_OPEN_QUESTIONS.md), [`08 §3`](../../08_REPO_LAYOUT.md), [`00 §4`](../../00_CONTEXT_AND_MOTIVATION.md), [`03 §6`](../../03_TOOL_AUTHORING.md) | "Locked pins (pydantic, starlette, click)" replaced with the real constraints in **all five** places; extras noted as not installed | ✅ Applied |
| 5 | [`13 D15`](../../13_OPEN_QUESTIONS.md) | **Went further than proposed.** The requester chose to collapse the distinction rather than narrow it: **one uniform calling convention**, per-item knobs, `params:` for computation-changing values only | ✅ Applied — **[ADR-0005](../../adr/0005-one-uniform-batched-calling-convention.md)** |
| 6 | [`02 §5.5`](../../02_CONFIGURATION.md) | `60000` attributed to BentoML; adapter must always pass both batching knobs explicitly | ✅ Applied |
| 7 | [`05 §5`](../../05_RUNTIME_AND_BATCHING.md), [`10`](../../10_TESTING_STRATEGY.md) | `worker_index` criticism re-worded to *"do not build device identity on a framework's indexing convention"* | ✅ Applied |
| 8 | [`10 §4.2`](../../10_TESTING_STRATEGY.md), [`05 §4.4`](../../05_RUNTIME_AND_BATCHING.md) | Unordered batches recorded as **documented vendor behaviour**; assert attribution, never submission order | ✅ Applied |
| 9 | [`02 §5.5`](../../02_CONFIGURATION.md), rule 4c | `tswap validate` warns when `workers > 1` with `devices:` set | ✅ Applied |
| 10 | [`08 §3`](../../08_REPO_LAYOUT.md) | Three-rule pin policy: no extras, check yank status, watch the constraints that actually bind | ✅ Applied |
| 11 | [`15 §2`](../../15_RAY_SERVE_EVALUATION.md) | The interpreter-range versus exact-patch-lockstep contrast | ⏸ **Not applied** — the Ray decision is settled and [`16 §7`](../../16_COMPLEXITY_AUDIT.md) asks for *fewer* restatements of it, not more |

**Two further findings from this capture were applied that had no amendment number:** the adapter must **enable metrics explicitly** (`/metrics` is conditional) and **must never set `path_prefix`** (it moves our mounted contract routes), plus the `/schema` versus `/schema.json` collision — all now in [`05 §3.1`](../../05_RUNTIME_AND_BATCHING.md). The **saturation mapping** for `ServiceUnavailable("process is overloaded")` is in [`05 §4.5`](../../05_RUNTIME_AND_BATCHING.md).

---

## 5. Reproducing or extending this capture

Documentation pages, one at a time:

```
universal_scraper(url="https://docs.bentoml.com/en/latest/<page>.html", output_format="md")
```

`output_format: "links"` on the root produced the page inventory in §1 and §2.

Packaging metadata:

```
curl -s https://pypi.org/pypi/bentoml/json | jq '.info.version, .info.requires_dist, .info.requires_python'
```

Source files, via the GitHub MCP (`get_file_contents`, owner `bentoml`, repo `BentoML`):
`src/bentoml/_internal/server/base_app.py`, `src/_bentoml_impl/server/app.py`.

**Two cautions when re-capturing:**

1. **`/en/latest/` moves.** Everything here is 1.4.39. The `@bentoml.api` defaults, the metric names and every dependency constraint are version facts.
2. **Source reads were against `main`, which is ahead of the release.** [`health-endpoints-and-lifecycle-source.md`](health-endpoints-and-lifecycle-source.md) is the only file so derived, and it is labelled. **Re-verify it against the pinned tag in M3.5** — the blocking-lifespan finding is load-bearing for M4 and deserves confirmation against the exact version we ship.

**Tooling note:** the Oxylabs AI Studio tools (`ai_map`, `ai_crawler`) would crawl a whole section in one call but require `OXYLABS_AI_STUDIO_API_KEY`, which [`.roo/mcp.json`](../../../.roo/mcp.json) does not set — the same gap recorded in [`ray-serve/INDEX.md`](../ray-serve/INDEX.md) §4.

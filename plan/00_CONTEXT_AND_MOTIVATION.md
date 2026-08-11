# 00 — Context and Motivation

> Read this if you have never worked on the `Healthcare-Systems-R8` repository. It explains what exists there today, what works, what hurts, and precisely which parts we are extracting.

---

## 1. Where tool-swap comes from

`Healthcare-Systems-R8` is a healthcare AI research prototype with a three-layer architecture:

1. **Execution Engine ("Run Engine")** — the compute layer. Exposes individual tools as REST services. *This is the layer we are extracting.*
2. **Orchestration layer** — an agent builds and runs workflow graphs whose nodes call the Run Engine.
3. **Presentation layer** — a Gradio frontend.

The Run Engine's own documentation (from the R8 repo, `src/core/service_engine/ReadMe.md`) describes it as:

> *"a high-performance run engine for executing foundation models (text, image, tabular, signal) through a simple REST API while achieving batch-level GPU efficiency."*
>
> Key capabilities claimed:
> - **Simple external API** — callers send 1 input at a time; no batching required.
> - **Automatic micro-batching** — requests are queued and grouped dynamically.
> - **High GPU utilization** — actors keep models warm and handle parallel execution.
> - **Modular architecture** — swap models, modify batching policy, or replace the executor without touching the API.

And from the R8 system architecture overview:

> *"The engine manages the complete lifecycle of these tools — from registration and discovery to execution and resource cleanup — using a lazy loading approach where models are loaded into GPU memory on-demand and unloaded after execution to optimize resource utilization."*

That intent is exactly right. The problem is that it is entangled inside a large monolithic application, and the implementation never got to the point where models genuinely "live by themselves".

---

## 2. What exists in R8 today

There are **three** implementations of one `RunEngine` interface, in various states of completeness. Full source for the important ones is in [`12_REFERENCE_CODE.md`](12_REFERENCE_CODE.md).

### 2.1 The interface

```python
class RunEngine(ToolInvoker):
    tool_registry: List[ToolSpecification]

    def __init__(self, tools: List[ToolSpecification]) -> None:
        self.tool_registry = tools

    def run_single(self, tool_id: str, inputs: dict[str, Modality], ctx: ToolContext) -> RunEngineOutput: ...

    def list_services(self) -> List[ToolServiceDescriptor]:
        return [tool.to_tool_service_descriptor() for tool in self.tool_registry]

    def shutdown(self): ...
```

Two public HTTP endpoints sit on top of it: `POST /api/run_model` and `GET /api/list_services`.

### 2.2 `LocalRuneEngine` — the one actually in use

In-process. On every call: lazily construct the tool, `load()` it, run it, then **immediately `unload()`** it and `torch.cuda.empty_cache()`.

```python
def run_single(self, tool_id, inputs, ctx) -> RunEngineOutput:
    tool_instance = self.get_instance(tool_id)
    ...
    tool_instance.set_context(ctx)
    input_kwargs = {port: m.payload for port, m in inputs.items()}
    output = tool_instance.run(**input_kwargs)
    tool_instance.unload()          # <-- unconditional, every single request
    return output
```

**Consequence**: every request pays the full model-loading cost. There is *no* residency, *no* TTL, *no* warm models — the exact opposite of the stated goal. It also runs the model inside the API process, so a model crash or a CUDA OOM takes down the whole backend, and every model must be importable in the API's single Python environment.

### 2.3 `BentoMLRunEngine` — the closest ancestor of tool-swap

This one is genuinely the prototype of what we are now building properly. It:

- Iterates the tool registry and, **for each model**, spawns a `bentoml serve` **subprocess** on port `7000 + i`.
- Passes per-model resource knobs to the subprocess **via environment variables** (`RUN_SVC_MAX_BATCH_SIZE`, `RUN_SVC_MAX_LATENCY_MS`, `RUN_SVC_NUM_CPUS`, `RUN_SVC_NUM_GPUS`, `RUN_SVC_WORKERS`).
- Polls `/healthz` until the service answers, then polls `/readyz` until warm-up finishes.
- Forwards a request as an HTTP `POST` to `http://localhost:{port}/process`.
- Kills the process group on shutdown, with an `atexit` hook.
- Gets micro-batching **for free** from BentoML's `@bentoml.api(batchable=True, max_latency_ms=..., max_batch_size=...)`.

Read that list again: *spawn a per-model server process, health-check it, proxy to it, kill it on exit, per-model resource config, micro-batching.* **That is roughly 70% of tool-swap.** What it is missing is exactly what this plan adds:

| Missing in `BentoMLRunEngine` | Added by tool-swap |
|---|---|
| Environments are shared — every model must live in the one giant venv | One image per model (**D2**) |
| Every model is started eagerly at boot, and blocks the API until *all* are warm | On-demand start, request-triggered |
| No TTL, no idle shutdown, no eviction — everything stays resident forever | Hard/soft TTL + groups + eviction (**D9**, **D7**) |
| No proxy for arbitrary upstreams; only its own `/process` shape | Transparent proxy + normalized API (**D4**) |
| Logs are pumped into the parent process's stdout with a thread per stream and printed only if `verbose` | Per-model log files, `tswap logs -f` (**D8**) |
| No status introspection at all | `/status`, `tswap status`, status page (**R1**) |
| Ports assigned by array index — reorder the registry and every port changes | Explicit/allocated stable ports |
| Bound to BentoML as a hard dependency of **the whole R8 backend**, alongside torch, TensorFlow, Ray and every model | BentoML confined to the **inside of each tool image** (**D14**), where it competes with nothing but that one model's pins. The router depends on none of it. **This is the distinction that matters**: the problem was never BentoML, it was one shared environment holding everything |
| Readiness polled on BentoML's `/readyz`, which reports server-up, not weights-loaded | Our `/ready` means weights loaded, with a reason on failure ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §3.2) |
| A `service_factory.py` building service classes into `globals()`, visible in the authoring path | The same accommodation, confined to our adapter; `handler.py` imports no framework |

Note also that in the current R8 code the BentoML engine is **commented out** in the factory in favour of the local engine:

```python
# engine = BentoMLRunEngine(tool_specifications, config_file, verbose=verbose)
engine = LocalRuneEngine(tool_specifications)
```

That single commented line is the honest summary of the situation: the good design was too painful to keep running inside the monolith. Extracting it is the fix.

### 2.4 `RayRunEngine` — abandoned mid-flight

A Ray-actor implementation with a `CoreBatcher` (pure-Python queue with `max_batch_size` / `max_wait_ms` flush policy) wrapped in a `RayBatcher` actor. The batching logic is clean and well-tested. The rest is incomplete — its own README says the actual model-executing actor is *"Coming soon"* — and Ray is a heavy dependency for what we need.

**Since D14 we take neither.** BentoML's adaptive dispatcher does the batching, so `CoreBatcher` is not ported; it survives in [`12_REFERENCE_CODE.md`](12_REFERENCE_CODE.md) §7 as the written specification for the `native` backend, should the BentoML decision ever be reversed. Two batchers were written in this repo and neither ended up running — which is itself the argument for reusing a third-party one.

### 2.5 The tool declaration system

R8 models are declared with decorators that introspect the function/class signature and build a `ToolSpecification` (name, docstring, typed input ports with descriptions, output ports, the implementing class and method, whether it needs a runtime context).

```python
@class_tool(name="cxr_to_embedding")
class CXRToEmbedding:
    """Convert the chest X-ray image at the provided PATH into a vector
    EMBEDDING using the RAD-DINO foundation model."""

    def __init__(self, device: str = "cpu", gpu_id: int | None = None):
        ...
        self.model = None

    def load(self) -> None:
        from core.models.vision.rad_dino import RADDINO
        self.model = RADDINO(cache_folder=None, device=self.device)

    def unload(self) -> None:
        self.model = None

    def __call__(
        self,
        paths: Batchable[str] = Field(description="Path STRING to a DICOM chest X-ray image ..."),
    ) -> list[list[float]]:
        ...
```

**What is genuinely good here and must be preserved in spirit:**

- `load()` / `unload()` lifecycle hooks. This is the contract that makes soft-TTL possible. Keep it verbatim.
- `device` / `gpu_id` injected at construction.
- **Mandatory docstring and mandatory per-parameter description.** The builder *raises* if a description is missing. This is what makes the models self-describing and consumable by an LLM agent. Keep this discipline.
- `Batchable[T] = Union[T, List[T]]` — a model declares that it can accept a list where a scalar is expected, which is what makes micro-batching safe and explicit.
- Typed input/output ports enabling validation before dispatch.

**What we should not carry over wholesale:**

- The decorator machinery does heavy signature/`TypeAdapter` introspection (~440 lines in `tool_builder.py`) and couples the model author to the orchestrator's Python package. In a Docker-first world the router cannot import the model's code *at all* — different image, different interpreter. So the schema must be **declared as data** (`tool.yaml`) or **served by the model itself** at a `/schema` endpoint, not derived by importing the model into the router.
- `Modality` and `ModalityType` are a fixed enum of healthcare-specific types (`TEXT`, `CHEST_XRAY`, `CT_SCAN`, `EEG`, `NUMBER`, `BOOLEAN`, `ANY`) with validators. Useful vocabulary, but too domain-specific and too enum-rigid for a generic zoo — and adding a modality meant editing an enum inside the orchestrator. Replaced by **JSON Schema plus open `x-semantic` hints** (decision **D13**, [`04_API_CONTRACT.md`](04_API_CONTRACT.md) §9).
- `ToolServiceDescriptor.to_node_text()` renders a tool as a signature-plus-doc block for injection into an LLM prompt. The *intent* — a self-describing, agent-callable registry — is exactly right and is preserved; the bespoke text format is not. We emit standard tool definitions (JSON Schema) instead, so no consumer needs a parser (**D13**).
- `ToolContext` allows a tool to call *another* tool recursively (`ctx.run_tool(...)`, with depth limiting). That is orchestration, and it belongs in the layer above tool-swap. In tool-swap a model that wants to call another model simply calls the router's HTTP API. Keep the depth-limit idea in mind if we ever allow it, to avoid infinite loops.

### 2.6 The existing configuration shape

```yaml
# serve_config/citadel_dgx.yaml
defaults:
  cpu: 1
  gpu: 1
  max_batch_size: 100
  max_latency_ms: 60000
  workers: 1

models:
  foundation_text_to_embedding:
    gpu: 3
    batch_size: 2
    max_latency_ms: 60000
    workers: 3
```

A `defaults` block plus per-model overrides. **This pattern is good and we keep it** (see [`02_CONFIGURATION.md`](02_CONFIGURATION.md)). Two flaws to avoid repeating:

- `batch_size` here is a typo/mismatch — the schema field is `max_batch_size`, so this override *silently does nothing*. The Pydantic model does not forbid extra keys. **Our config must reject unknown keys** so typos fail loudly at startup.
- `gpu: 3` is ambiguous: it means "3 GPUs" (a count, passed to BentoML's resource block) but reads like "GPU number 3". Our config will use explicit, unambiguous names (`devices: [0,1,2]`).

---

## 3. The evidence for Docker-first isolation

The R8 backend has a single pinned requirements file for all models. An abridged look at what must coexist in that one interpreter:

```
torch==2.8.0+cu129            tensorflow==2.16.0rc0        tf-keras==2.15.0
ray==2.49.1                   bentoml==1.4.30              vllm (separate image)
transformers==4.56.1          monai==1.5.1                 sentence-transformers==5.6.0
autoawq==0.2.9                flash_attn-2.8.3 (cu12torch2.8, cp312 wheel, pinned URL)
numpy==1.26.4                 spacy==3.8.3                 xgboost==2.1.2
itk / simpleitk / nibabel / pydicom / medmnist / rad-dino / gradio / fastapi / supabase ...
```

That is ~300 pinned packages including **both** PyTorch and TensorFlow, a CUDA-version-specific flash-attention wheel pinned by URL, and a frontend framework — all so that a handful of unrelated models can be imported into one process.

The failure modes this creates are structural, not incidental:

- **Irreconcilable pins.** Model A needs `transformers==4.30`, model B needs `>=4.56`. Today one of them cannot be added. Full stop.
- **CUDA/ABI coupling.** `flash_attn` is pinned to an exact `cu12torch2.8 / cp312` build. Bumping torch for one model breaks another's binary wheel.
- **numpy 1.x vs 2.x.** A perennial split across the scientific stack; some models will need each.
- **TF and torch fighting over VRAM.** Note the R8 comment in the COMPASS tool's `unload()`: *"Also call `tf.keras.backend.clear_session()` externally to fully release GPU memory (process-wide reset, not scoped to this model alone)."* A single model cannot cleanly release its own memory because the process is shared. That is the isolation problem stated in one sentence, in their own code.
- **Blast radius.** A segfault in a native extension, or a CUDA OOM, kills the API and every other model with it.
- **Install time.** Adding one model means re-resolving a 300-package lock file and hoping.

Per-model container images make each of these a non-issue by construction. The cost — image build time, disk, container cold start — is real but bounded, and TTL/eviction is precisely how we manage it.

---

## 4. Reference points in the wider ecosystem

Per **D12**, prefer existing self-hostable software over bespoke code. Worth knowing before you build:

| Project | What it does | Relevance |
|---|---|---|
| **llama-swap** | YAML-configured proxy that starts/stops `llama.cpp`-style upstream *processes* on demand, with TTL, groups, and an OpenAI-compatible front door. Single Go binary. | **Two roles.** (1) It is our *sibling service*: LLM serving happens there, not here, which is why tool-swap has no OpenAI layer. (2) It is the direct model for our router semantics: config shape, `ttl`, `groups`, `macros`, `/upstream/{tool}` proxying, the `/ui` status page. **Read its README before designing the config.** Differences: it manages processes not containers, and assumes LLM/OpenAI endpoints, which ours are not. |
| **vLLM** | High-throughput LLM server with continuous batching, OpenAI-compatible API. Used in R8 via a dedicated Docker image + compose service. | **Out of scope for tool-swap** — it serves LLMs, which belong to llama-swap. Retained as the reference implementation for what good continuous batching looks like; the batching in our own containers comes from BentoML's adaptive dispatcher (**D14**, [`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §4). |
| **Hugging Face TEI / TGI** | Purpose-built embedding / text-generation servers with dynamic batching. | Also out of scope: we host no third-party server images. A text embedder here is a twenty-line handler on our runtime ([`03_TOOL_AUTHORING.md`](03_TOOL_AUTHORING.md) §12). |
| **NVIDIA Triton** | Multi-framework inference server with model repository, dynamic batching, instance groups, and **explicit model control (load/unload via API)**. | The heavyweight alternative to this whole project. Its "model control mode = explicit" is essentially our TTL feature. Rejected as the core because per-model *Python environment* isolation is awkward (a Python backend shares the Triton process/env unless you build custom backends or stub environments), and because its configuration surface is far from "simple to configure" (**R4**). Still: a great `external` backend for models that suit it, and worth studying for batching semantics. |
| **BentoML** | What R8 already used: Python-native services with `batchable` APIs, `max_batch_size` / `max_latency_ms`, an adaptive dispatcher, `/healthz` `/readyz` and Prometheus metrics. | **ADOPTED as the in-container runtime** (**D14**, resolving Q1), wrapped behind our own contract so that the author's `handler.py` never imports it and the router never sees it. We therefore write no batcher at all. Its locked pins are the accepted risk, instrumented by a spike and a CI resolution gate ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §1). |
| **Ray Serve** | Autoscaling, `@serve.batch` dynamic batching, per-deployment resource requests, multi-model. | Also considered; rejected as the core for the same reasons Triton was (heavy, and per-deployment env isolation via runtime_envs is fragile for native/CUDA stacks), and R8's own Ray attempt stalled. |
| **KServe / Seldon** | Kubernetes-native model serving with scale-to-zero (which *is* hard TTL). | The "right" answer at cluster scale. Rejected for v1: requires Kubernetes, contradicts **R1** (simple to launch) and **D8** (docker compose). Keep as the documented growth path. |
| **Docker Model Runner / Ollama** | On-demand load/unload of *LLMs* with idle timeouts. | Confirms the TTL UX is the industry norm; both are LLM-only so not usable as our core. |

The honest framing: **tool-swap is a thin, opinionated, self-hostable orchestrator whose value is in the swap/TTL/proxy/authoring UX, not in inventing inference technology.** Wherever a mature server exists for a model class, we should be proxying to it, not reimplementing it.

---

## 5. Non-goals for v1

State these explicitly so scope does not creep:

- **Not** a workflow/graph engine. No DAGs, no chaining, no agents. Those live above us (that is R8's orchestration layer).
- **Not** multi-node. Single host, multiple GPUs. Multi-host is a documented growth path.
- **Not** training. Inference only.
- **Not** an auth/tenancy system. Assume a trusted network for v1; leave a hook for a bearer token. (R8 has a Supabase-based auth layer; do not port it.)
- **Not** a model registry/artifact store. Weights come from wherever the model's own code fetches them (HF cache mount, MinIO, local path). We mount caches; we do not manage them.
- **Not** autoscaling by load. One instance per model in v1; `replicas` is a documented future knob.
- **No database.** State lives in memory plus the container runtime's own state. Restarting the router must be safe and cheap.

---

## 6. What "success" looks like

A new user, on a fresh GPU box, should be able to:

```bash
git clone <repo> && cd tool-swap
cp tools.example.yaml tools.yaml
tswap up                      # router is live on :8600
tswap status                  # every configured tool, its state, its device, its TTL
curl localhost:8600/tools     # discover what is available
curl -X POST localhost:8600/run/cxr_to_embedding -d '{"inputs":{"paths":"/data/x.dcm"}}'
                              # container starts on demand, answers, and stops itself later
tswap logs cxr_to_embedding -f
```

And a scientist should be able to add a tool by creating **one directory with three files** (`tool.yaml`, `handler.py`, `requirements.txt`), running `tswap build my_tool`, and having it appear in `/tools` — without touching the router's code, its environment, or any Dockerfile.

If both of those are true, the project has succeeded.

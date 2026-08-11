# 12 — Reference Code and Evidence (verbatim from the originating system)

> **Purpose:** the implementer will not have access to the originating repository. Everything worth reusing or learning from is reproduced here **verbatim**, with commentary on what to keep, what to fix, and why.
>
> Original paths are given for the record only — they are not links you can follow, and nothing in this plan requires you to.
>
> **Where the plan asserts something about the originating system, the evidence is here.** Claims about dependency conflicts (§21), about a tool being unable to free its own GPU memory (§20), about mandatory descriptions (§18) and about the working design that was switched off (§19) are all backed by quoted source rather than by recollection. If a claim elsewhere in the plan lacks evidence here, treat it as unverified.

Quick index:

| § | What | Verdict |
|---|---|---|
| 1 | `RunEngine` interface | Reference for the R8 client plan |
| 2 | `LocalRuneEngine` + `ToolInstance` | The problem statement, in code |
| 3 | `BentoMLRunEngine` | The ancestor; port the structure |
| 4 | `BentoServiceProcess` | **Port carefully; fix the bugs noted** |
| 5 | BentoML `service_factory` | **Now the closest thing to a prototype of our runtime adapter** (**D14**) — port the ideas, reject the style |
| 6 | Config schema + loader + YAML | Keep the shape, add `extra="forbid"` |
| 7 | **`CoreBatcher`** | **Not used in v1.** The specification and starting code for the `native` backend, kept for if D14 is ever reopened |
| 8 | `RayBatcher` | Cautionary tale; do not copy |
| 9 | Types: `RunEngineOutput`, `Modality`, `Port` | Adapt selectively |
| 10 | `ToolServiceDescriptor` | Port the descriptor; **not** its text renderer (D13) |
| 11 | A real class tool | The authoring target |
| 12 | `ToolContext` | Out of scope; keep for the R8 client |
| 13 | API endpoints | The positional-mapping bug to avoid |
| 14 | Tool discovery / lifecycle CLI | Ideas for `tswap validate` |
| 15 | Docker/compose | Deployment patterns to keep |
| 16 | `Batchable` | The batching declaration |
| 17 | Authoring documentation | Reusable near-verbatim |
| 18 | Tool decorator + specification builder | **The mechanism we replace**; keep its strictness |
| 19 | Engine factory | One commented line that justifies the project |
| 20 | The TensorFlow/Keras tool | **The isolation argument, in its author's own words** |
| 21 | Dependency evidence | The verbatim pins behind **D2** |
| 22 | A pure-CPU tool | The small end of the zoo |

---

## 1. The `RunEngine` interface

*`src/core/service_engine/run_engine.py`*

```python
from typing import List

from core.data.modalities import Modality
from core.service_engine.tool_context import ToolContext, ToolInvoker
from core.service_engine.types import RunEngineOutput
from core.tools.tool_builder import ToolSpecification
from core.tools.tool_service_descriptor import ToolServiceDescriptor


class RunEngine(ToolInvoker):
    tool_registry: List[ToolSpecification]

    def __init__(self, tools: List[ToolSpecification]) -> None:
        self.tool_registry = tools

    def run_single(
        self, tool_id: str, inputs: dict[str, Modality], ctx: ToolContext
    ) -> RunEngineOutput: ...

    def list_services(self) -> List[ToolServiceDescriptor]:
        return [tool.to_tool_service_descriptor() for tool in self.tool_registry]

    def shutdown(self): ...
```

**Notes.** Two operations — run one thing, list what exists — which is exactly tool-swap's `/run/{model}` and `/tools`. The interface is the seam for [`11_R8_CLIENT_PLAN.md`](11_R8_CLIENT_PLAN.md). Note `inputs` is already a **named dict**; only the HTTP layer was positional (§13).

---

## 2. `LocalRuneEngine` and `ToolInstance` — the problem, in code

*`src/core/service_engine/local_engine/local_run_engine.py`*

```python
class LocalRuneEngine(RunEngine):
    def __init__(self, tools: List[ToolSpecification]):
        super().__init__(tools)
        self.tool_dict: dict[str, ToolSpecification] = {tool.name: tool for tool in tools}
        self.instances: dict[str, ToolInstance] = {}

    def get_instance(self, tool_name: str) -> ToolInstance | None:
        """Lazy create of a tool instance when requested"""
        if tool_name not in self.instances:
            spec = self.tool_dict.get(tool_name)
            if spec is None:
                return None
            self.instances[tool_name] = ToolInstance(spec)
        return self.instances[tool_name]

    def shutdown(self) -> None:
        return

    def run_single(self, tool_id: str, inputs: Dict[str, Modality], ctx: ToolContext) -> RunEngineOutput:
        logger = get_logger()
        tool_instance = self.get_instance(tool_id)
        if tool_instance is None:
            raise ValueError(f"Unknown tool: {tool_id}")
        # TODO: Validate inputs
        logger.info(f"Run Engine launching tool: {tool_id}")
        tool_instance.set_context(ctx)
        # Convert Modality objects to payloads for tool execution
        input_kwargs = {port_name: modality.payload for port_name, modality in inputs.items()}
        output = tool_instance.run(**input_kwargs)
        tool_instance.unload()

        logger.info(f"Run Engine tool output: {output}")
        return output
```

*`src/core/service_engine/local_engine/tool_instance.py`*

```python
import torch

from core.service_engine.tool_context import ToolContext
from core.service_engine.types import ResultStatus, RunEngineOutput
from core.tools.tool_builder import ToolSpecification


class ToolInstance:
    def __init__(self, tool_spec: ToolSpecification):
        self.tool_spec = tool_spec
        self.tool = None
        self._callable = None
        self.tool_context: ToolContext | None = None

    def ensure_loaded(self):
        # Function tools require no loading
        if self.tool_spec.impl_cls is None:
            return

        # Class tools
        if self.tool is None:
            init_args = self.tool_spec.init_args or {}

            # Detect GPU availability and pass device/gpu_id to the tool
            gpu_id = 0 if torch.cuda.is_available() else None
            device = "cuda" if gpu_id is not None else "cpu"

            try:
                self.tool = self.tool_spec.impl_cls(**init_args, device=device, gpu_id=gpu_id)
            except TypeError:
                self.tool = self.tool_spec.impl_cls(**init_args)

            self._callable = getattr(self.tool, self.tool_spec.impl_method)

            if hasattr(self.tool, "load"):
                self.tool.load()

    def unload(self):
        if self.tool is not None:
            if hasattr(self.tool, "unload"):
                self.tool.unload()
            del self.tool
            self.tool = None
            self._callable = None
            self.flush_gpu_cache()

    def flush_gpu_cache(self):
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass

    def set_context(self, ctx: ToolContext):
        self.tool_context = ctx

    def run(self, **kwargs) -> RunEngineOutput:
        if self.tool_spec.requires_runtime_context:
            kwargs["ctx"] = self.tool_context

        if self.tool_spec.impl_cls is None:
            tool = self.tool_spec.get_callable()
        else:
            self.ensure_loaded()
            if self.tool is None:
                raise ValueError(f"Tool {self.tool_spec.name} failed to load")
            tool = self._callable

        # --- Apply defaults ---
        for name, default in self.tool_spec.input_defaults.items():
            if name not in kwargs:
                kwargs[name] = default

        # --- Validate inputs using adapters ---
        validated_kwargs = {}
        for name, adapter in self.tool_spec.input_adapters.items():
            if name in kwargs:
                validated_kwargs[name] = adapter.validate_python(kwargs[name])

        if "ctx" in kwargs:
            validated_kwargs["ctx"] = kwargs["ctx"]

        output = tool(**validated_kwargs)
        return RunEngineOutput(payload=output, status=ResultStatus.SUCCESS, error_message=None)
```

**Read this as the motivation for the entire project.** `run_single` calls `unload()` unconditionally after **every** request, so every call pays the full load cost — the exact opposite of the documented "keep models warm" goal. There is no TTL, no residency, no batching. And because it all runs in the API process, every model must be importable in one environment and any crash is fatal to the whole backend.

**Keep:** the `load()`/`unload()`/`hasattr` lifecycle pattern, `flush_gpu_cache`, defaults-then-validate ordering, `device`/`gpu_id` injection with a `TypeError` fallback.
**Discard:** the unconditional unload, the in-process execution, `input_adapters` introspection.

---

## 3. `BentoMLRunEngine` — the direct ancestor

*`src/core/service_engine/bentoml_engine/bentoml_run_engine.py`*

```python
BASE_PORT = 7000


class ServiceEntry:
    def __init__(self, service: BentoServiceProcess, port: int):
        self.service: BentoServiceProcess = service
        self.port: int = port

    def to_url(self) -> str:
        return f"http://localhost:{self.port}/process"


RUN_SVC_MAX_BATCH_SIZE = "RUN_SVC_MAX_BATCH_SIZE"
RUN_SVC_MAX_LATENCY_MS = "RUN_SVC_MAX_LATENCY_MS"
RUN_SVC_NUM_CPUS = "RUN_SVC_NUM_CPUS"
RUN_SVC_NUM_GPUS = "RUN_SVC_NUM_GPUS"
RUN_SVC_WORKERS = "RUN_SVC_WORKERS"


class BentoMLRunEngine(RunEngine):
    def __init__(self, tools: List[ToolSpecification], config_path: str, verbose=False):
        super().__init__(tools)
        cfg: DeploymentConfig = load_deployment_config(config_path)
        module = "core.service_engine.bentoml_engine.service_factory"
        self.service_cache = {}
        for i, model_spec in enumerate(self.tool_registry):
            port: int = BASE_PORT + i
            svc = BentoServiceProcess(
                module=module,
                model_name=model_spec.name,
                port=port,
                env=self.get_environment_from_config(model_spec.name, cfg),
                verbose=verbose,
            )
            self.service_cache[model_spec.name] = ServiceEntry(service=svc, port=port)
            svc.start()
            if not svc.health_check():
                self.shutdown()
                raise RuntimeError("Bento service failed to start")
            print("Service {} running —".format(model_spec.name))

        # Make sure that all services are warmed up before making the api available
        for service_entry in self.service_cache.values():
            service_entry.service.wait_while_warming_up()

    def get_environment_from_config(self, model_id: str, cfg: DeploymentConfig) -> dict[str, str]:
        mcfg: ServeDefaults = resolve_model_config(cfg, model_id)
        env: dict[str, str] = os.environ.copy()
        # Service-runtime knobs that your service reads
        env[RUN_SVC_MAX_BATCH_SIZE] = str(mcfg.max_batch_size)
        env[RUN_SVC_MAX_LATENCY_MS] = str(mcfg.max_latency_ms)
        env[RUN_SVC_NUM_CPUS] = str(mcfg.cpu)
        env[RUN_SVC_NUM_GPUS] = str(mcfg.gpu)
        env[RUN_SVC_WORKERS] = str(mcfg.workers)
        return env

    def shutdown(self) -> None:
        for service_entry in self.service_cache.values():
            print("Stopping service {}...".format(service_entry.service.service_name))
            service_entry.service.stop()

    def run_single(self, tool_id: str, inputs: dict[str, Modality], ctx: ToolContext,
                   timeout: Optional[float] = None) -> RunEngineOutput:
        # Check if tool_id is valid
        if tool_id not in self.service_cache:
            raise ValueError(f"Unknown tool_id: {tool_id}")
        service_entry = self.service_cache[tool_id]

        payload = {"modality_batch": [[input_modality.to_dict() for input_modality in inputs.values()]]}

        r = httpx.post(service_entry.to_url(), json=payload, timeout=timeout)
        r.raise_for_status()
        output_dict = r.json()[0] if isinstance(r.json(), list) else r.json()
        output: RunEngineOutput = RunEngineOutput(**output_dict)
        if not isinstance(output, RunEngineOutput):
            raise ValueError(f"Expected RunEngineOutput, got {type(output)}")
        return output
```

**Keep:** per-model server processes; env-var configuration (tool-swap's `TSWAP_*`); health-then-readiness gating; forwarding over HTTP; shutdown that stops everything.

**Fix:**
- `BASE_PORT + i` over an enumerated registry ⇒ **reordering models silently reassigns every port.** Use explicit or stably-derived ports ([`01_ARCHITECTURE.md`](01_ARCHITECTURE.md) §7).
- **Everything starts eagerly in `__init__`, and the API blocks until every model is warm.** With twenty models this is unusable, and it is the reason TTL/on-demand start is the core of tool-swap.
- `raise ValueError` for an unknown tool becomes an HTTP 500 upstream; use 404.
- `r.json()` is called three times — parse once.
- `print()` instead of logging.

---

## 4. `BentoServiceProcess` — port the structure, fix the bugs

*`src/core/service_engine/bentoml_engine/launch_service.py`*

```python
class BentoServiceProcess:
    def __init__(self, module: str, model_name: str, port: int, env: dict[str, str], verbose: bool = False):
        self.model_name = model_name
        self.service_name = model_name + "-service"
        self.module = module
        self.port = port
        self.proc: Optional[subprocess.Popen] = None
        self.verbose = verbose
        self.env = env

    def start(self):
        """Launch the Bento service as a background process."""
        if self.proc is not None:
            raise RuntimeError("Service already started")

        if self.verbose:
            print(f"Starting {self.module}:{self.service_name} on port {self.port}...")

        cmd = ["bentoml", "serve", f"{self.module}:{self.service_name}",
               "--port", str(self.port), "--arg", f"model_name={self.model_name}"]

        # Start with preexec_fn so child does not get killed on Ctrl-C (Linux)
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=None if subprocess.os.name == "nt" else subprocess.os.setsid,
            text=True,
            bufsize=1,
            env=self.env or os.environ.copy(),
        )

        self.stdout_thread = threading.Thread(
            target=self._stream_reader,
            args=(self.proc.stdout, f"[{self.service_name}]-stdout"), daemon=True)
        self.stderr_thread = threading.Thread(
            target=self._stream_reader,
            args=(self.proc.stderr, f"[{self.service_name}]-stderr"), daemon=True)

        self.stdout_thread.start()
        self.stderr_thread.start()

        # Register cleanup handler when the Python program exits
        atexit.register(self.stop)

    def _stream_reader(self, stream, name: str):
        """Reads the subprocess logs line-by-line in real time."""
        try:
            for line in iter(stream.readline, ""):
                if self.verbose:
                    print(f"{name}: {line.rstrip()}")
        finally:
            stream.close()

    def wait_while_warming_up(self):
        url = f"http://localhost:{self.port}/readyz"
        if self.verbose:
            print(f"Waiting for {self.service_name} to warm up...")
        while True:
            r = httpx.get(url, timeout=1.0)
            if r.status_code == 200:
                if self.verbose:
                    print(f"{self.service_name} is warmed up.")
                return True

    def health_check(self, timeout: float = 120.0) -> bool:
        """Poll the /health endpoint until it returns 200 or timeout."""
        url = f"http://localhost:{self.port}/healthz"

        deadline = time.time() + timeout
        error_message = ""
        attempt = 0
        while time.time() < deadline:
            try:
                r = httpx.get(url, timeout=1.0)
                if r.status_code == 200:
                    print(f"{self.service_name} is healthy.")
                    return True
            except Exception as e:
                if self.verbose:
                    error_message = f"Health check failed for {self.service_name}. Cause {e}"
                attempt += 1

            time.sleep(0.3)

        if self.verbose:
            print(f"Health check FAILED for {self.service_name}.")
            print(error_message)
        return False

    def stop(self):
        """Stop the Bento process cleanly when program exits or manually."""
        if self.proc is None:
            return

        if self.verbose:
            print(f"Stopping {self.service_name}...")

        try:
            # Linux/macOS: kill process group
            if subprocess.os.name != "nt":
                subprocess.os.killpg(self.proc.pid, signal.SIGTERM)
            else:
                self.proc.terminate()

            self.proc.wait(timeout=5)
        except Exception:
            if self.verbose:
                print("Forcing kill of service {}...".format(self.service_name))
            self.proc.kill()

        self.proc = None
```

**This is the closest thing in R8 to tool-swap's lifecycle manager, and its bugs are the specification for ours.**

| Bug | Consequence | Our requirement |
|---|---|---|
| `wait_while_warming_up()` is `while True` with **no timeout and no exception handling** | A model that fails to load hangs the caller **forever**; a connection error raises out of the loop uncaught | `ready_timeout` + `FAILED` with the reason ([`10_TESTING_STRATEGY.md`](10_TESTING_STRATEGY.md) §10 regression test) |
| Log lines are read and **discarded unless `verbose`** | Diagnostics silently lost by default | Always persist to per-model files, retained after stop |
| No drain before `SIGTERM` | In-flight requests are killed | `drain_timeout` then SIGTERM then SIGKILL |
| `atexit` only | An abrupt kill leaks processes | Labels + reconciliation |
| `print()` throughout | Unfilterable, unstructured | Structured logging |
| Health then readiness with different budgets, though — **correct**, and the reason for the `STARTING`/`LOADING` split | | Keep |

---

## 5. The BentoML service factory — read, do not imitate

*`src/core/service_engine/bentoml_engine/service_factory.py`* (abridged)

```python
def make_service_class(node: ToolSpecification):
    service_name = f"{node.name}-service"

    defaults = ServeDefaults()
    max_batch_size = int(os.getenv(RUN_SVC_MAX_BATCH_SIZE, defaults.max_batch_size))
    max_latency_ms = int(os.getenv(RUN_SVC_MAX_LATENCY_MS, defaults.max_latency_ms))
    cpu = int(os.getenv(RUN_SVC_NUM_CPUS, defaults.cpu))
    gpu = int(os.getenv(RUN_SVC_NUM_GPUS, defaults.gpu))
    workers = int(os.getenv(RUN_SVC_WORKERS, defaults.workers))

    print(f"Creating service {service_name} with max_batch_size={max_batch_size}, "
          f"max_latency_ms={max_latency_ms}, cpu={cpu}, gpu={gpu}, workers={workers}")

    @bentoml.service(name=service_name, resources={"gpu": gpu, "cpu": cpu}, workers=workers)
    class _Service:
        def __init__(self):
            print("Initializing service: ", service_name)
            self._lock = threading.Lock()
            self._ready = False
            self.name = service_name
            self.callable = None
            self.node = node

            # Start warmup in background so the HTTP server can bind immediately
            t = threading.Thread(target=self._warmup_background, daemon=True)
            t.start()

        def _warmup_background(self):
            print("Warming up service: ", service_name)
            try:
                wid = bentoml.server_context.worker_index
                gpu_id = max(0, wid - 1)
                device = "cuda" if gpu_id is not None else "cpu"
                self.callable = node.get_callable(device, gpu_id)
                with self._lock:
                    self._ready = True
            except Exception:
                with self._lock:
                    self._ready = False

        @bentoml.api(batchable=True, max_latency_ms=max_latency_ms, max_batch_size=max_batch_size)
        def process(self, modality_batch: List[List[Modality]]) -> List[RunEngineOutput]:
            outputs = [RunEngineOutput(payload=None, status=ResultStatus.FAILED)
                       for x in range(len(modality_batch))]

            if self.callable is None:
                for output in outputs:
                    output.status = ResultStatus.FAILED
                    output.error_message = "Service is not ready"
                return outputs

            valid_idexes = []
            batch_rows = []
            for i, modality_list in enumerate(modality_batch):
                is_valid, message = self.node.validate_inputs(modality_list)
                if is_valid:
                    batch_rows.append([x.payload for x in modality_list])
                    valid_idexes.append(i)
                else:
                    outputs[i].status = ResultStatus.FAILED
                    outputs[i].error_message = message
            batch_columns = list(map(list, zip(*batch_rows)))

            predictions = self.callable(*batch_columns)
            for i, index in enumerate(valid_idexes):
                outputs[index] = RunEngineOutput(payload=predictions[i], status=ResultStatus.SUCCESS)

            return outputs

        @bentoml.api
        def readyz(self) -> dict:
            with self._lock:
                if self._ready:
                    return {"ready": True}
            return {"ready": False}

    return _Service


args = bentoml.use_arguments()
tool_specifications = get_tool_specifications()
model_name: str = args.model_name
tool_specification = next((spec for spec in tool_specifications if spec.name == model_name), None)
if tool_specification is None:
    raise ValueError(f"Model {model_name} not found in tool specifications")
cls = make_service_class(tool_specification)
globals()[f"{args.model_name}-service"] = cls
```

**Keep the ideas:** bind the port first and warm up on a background thread (exactly our `STARTING`→`LOADING` behaviour); a batched endpoint with `max_batch_size` + `max_latency_ms`; per-item validation so one bad item fails alone; log the effective knobs at startup; row→column transposition before calling a batched callable.

**Avoid:** module-level side effects and `globals()[...] = cls` (a framework-imposed idiom that is hostile to testing); `_warmup_background` **swallowing the exception** so the failure reason is lost — our runtime must record and expose it; `gpu_id = max(0, wid - 1)` (fragile, off-by-one-prone — pass an explicit device list); the `valid_idexes` typo (cosmetic, but it is in the batching core).

**Since D14, this section is the nearest thing we have to a prototype of `backends/bentoml_backend.py`** ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §2.2), so read it as such — including its warnings. It shows the framework accommodation a BentoML service requires, and our adapter's entire job is to **absorb that accommodation so the author never sees it**. Concretely:

| In R8 | In our adapter |
|---|---|
| `make_service_class(node)` built per model, assigned into `globals()` | Built once by the adapter from `tool.yaml` + the handler; never touches `globals()` |
| Batching config read from env inside the factory | Parsed into `RuntimeSettings` above the seam, then handed down |
| Validation and per-item error shaping inside the `@bentoml.api` method | In our predict wrapper, above the seam, unit-testable with no server |
| Readiness as a bespoke `readyz` API returning `{"ready": bool}` | The same instinct, promoted to a first-class contract endpoint with a **reason** ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §3.2) |
| Warm-up failure swallowed | Recorded, logged with traceback, exposed on `/ready`, exit non-zero |

That last row is the single most valuable lesson in this file: R8's version of this code could fail to load a model and then say nothing about it, forever.

---

## 6. Config schema, loader and a real config file

*`src/core/service_engine/config_schema.py`*

```python
from pydantic import BaseModel, Field
from typing import Dict


class ServeDefaults(BaseModel):
    gpu: int = 0
    cpu: int = 1
    max_batch_size: int = 100
    max_latency_ms: int = 60000
    workers: int = 1


class ServeOverride(ServeDefaults):
    pass


class DeploymentConfig(BaseModel):
    defaults: ServeDefaults = Field(default_factory=ServeDefaults)
    models: Dict[str, ServeOverride] = Field(default_factory=dict)  # model_id -> overrides
```

*`src/core/service_engine/config_loader.py`*

```python
def load_deployment_config(path: str) -> DeploymentConfig:
    with open(path, "r") as f:
        data = yaml.safe_load(f) or {}
    return DeploymentConfig.model_validate(data)
```

*`src/api/conf/serve_config/citadel_dgx.yaml`*

```yaml
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

**Keep:** `defaults` + per-model overrides; pydantic validation.

**Fix — and note this config file contains two live examples of the flaws:**
- `batch_size: 2` is not a field (`max_batch_size` is), and because the model does not forbid extras it is **silently ignored**. Hence our `extra="forbid"` rule ([`02_CONFIGURATION.md`](02_CONFIGURATION.md) §1).
- `gpu: 3` means "three GPUs" but reads as "GPU #3". Hence `devices: [int]` only.
- `max_latency_ms: 60000` as a *batching* latency budget means a request can sit in the queue for a full minute. Our default is 20 ms.

---

## 7. `CoreBatcher` — **not used in v1; kept as the `native` backend's specification**

*`src/core/service_engine/core_batcher.py`* — reproduced in full.

> **Status changed by D14.** Batching in v1 is BentoML's adaptive dispatcher, so this code is **not** ported into the shipped runtime ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §4.1). It is retained here deliberately, for two reasons:
>
> 1. **It is the specification of the `native` backend.** If a model ever cannot install BentoML, or the dispatcher proves inadequate, this is the flush policy and roughly the code that fills the seam ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §2). Keeping the fallback *written down* is what makes "not locked in" a fact rather than a claim.
> 2. **It is the mental model for tuning.** "Flush when the queue reaches `max_batch_size`, or when the oldest item has waited `max_wait_ms`" is how operators should reason about the knobs, even though the dispatcher's real behaviour is adaptive rather than fixed.
>
> Note what would still have to be added if it were ever used: async futures instead of the synchronous poll, per-request cancellation, and compatibility keys — the last of which is currently handled by forbidding the situation instead (**D15**). Its `now_ms`-injected design remains excellent, and is why its unit tests could run in microseconds; that testability is the thing **D14** trades away (§4.2 of [`10_TESTING_STRATEGY.md`](10_TESTING_STRATEGY.md)).

```python
from __future__ import annotations
from typing import Any, List, Tuple

from pydantic import BaseModel


class PendingRequest(BaseModel):
    request_id: int
    enqueue_ts_ms: int
    inputs: list[Any]


class CoreBatcher:
    """
    Pure batching logic:
    - Maintains a queue of PendingRequest
    - Decides when a batch is ready (max_batch_size / max_wait_ms)
    - Produces (request_ids, instances) for the next batch
    """

    def __init__(self, max_batch_size: int, max_wait_ms: int):
        assert max_batch_size > 0
        assert max_wait_ms >= 0
        self.max_batch_size = max_batch_size
        self.max_wait_ms = max_wait_ms

        self._next_request_id: int = 1
        self._queue: List[PendingRequest] = []

    def enqueue(self, inputs: list[Any], now_ms: int) -> int:
        """
        Add a new request to the queue.
        Returns a request_id that the caller can use to map results back.
        """
        rid = self._next_request_id
        self._next_request_id += 1

        self._queue.append(
            PendingRequest(request_id=rid, enqueue_ts_ms=now_ms, inputs=inputs)
        )
        return rid

    def ready_to_flush(self, now_ms: int) -> bool:
        """
        Returns True if we should flush a batch now based on:
        - batch size
        - waiting time of oldest element
        """
        if not self._queue:
            return False

        if len(self._queue) >= self.max_batch_size:
            return True

        oldest = self._queue[0]
        waited = now_ms - oldest.enqueue_ts_ms
        return waited >= self.max_wait_ms

    def build_next_batch(self, now_ms: int) -> Tuple[List[int], List[list[Any]]]:
        """
        Pop the next batch from the queue, according to max_batch_size.
        Caller is responsible for checking ready_to_flush() first.
        Returns:
          request_ids, instances
        """
        if not self._queue:
            return [], []

        batch_size = min(self.max_batch_size, len(self._queue))

        batch = self._queue[:batch_size]
        self._queue = self._queue[batch_size:]

        request_ids = [p.request_id for p in batch]
        instances = [p.inputs for p in batch]
        return request_ids, instances

    # ---------- helpful diagnostics ----------

    @property
    def queue_length(self) -> int:
        return len(self._queue)

    def snapshot_request_ids(self) -> List[int]:
        return [p.request_id for p in self._queue]
```

**Why this is good code:** pure, framework-free, no clock dependency (`now_ms` is a parameter — which is exactly the injectable-clock discipline we want), request-id mapping so results return to the right caller, and diagnostics for tests.

**Would need to be added, if the `native` backend is ever built** ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §2): async plumbing (a future per request id) and cancellation; `max_batch_bytes`; compatibility keys so requests with different non-batchable arguments are never merged.

Note that per-item failure isolation and the batch-length check are **not** on that list: under **D14** they live in the predict wrapper above the seam, and a `native` backend would inherit them unchanged. That is the seam working as intended — the safety-critical logic is written once, whatever forms the batch. The compatibility-key item is also, today, moot: **D15** forbids the situation at authoring time rather than solving it at runtime.

---

## 8. `RayBatcher` — a cautionary tale

*`src/core/service_engine/ray_engine/ray_batcher.py`* (abridged; note the author's own hedging in the docstrings)

```python
    def run_single(self, instance: dict[str, Modality]) -> RunEngineOutput:
        """
        Synchronous version (simplified):
        - enqueue
        - maybe flush batch
        - (for simplicity) flush until we get our own result
        This is not the most efficient micro-batching, but shows clean separation.
        """
        ...
        now_ms = int(time.time() * 1000)
        rid = self._batcher.enqueue([x.payload for x in instance.values()], now_ms)

        if self._batcher.ready_to_flush(now_ms):
            self._flush_once(now_ms)

        # If our result is not ready yet (e.g., we didn't flush), we force a flush
        if rid not in self._pending_outputs and self._batcher.queue_length > 0:
            self._flush_once(int(time.time() * 1000))

        # At this point, our result should exist
        out = self._pending_outputs.pop(rid)
        return RunEngineOutput(payload=out, status=ResultStatus.SUCCESS)

    def _flush_once(self, now_ms: int) -> None:
        rids, instances = self._batcher.build_next_batch(now_ms)
        if not rids:
            return
        ## For now we fake the batch
        outputs = []
        for instance in instances:
            outputs.append(self.callable(instance))
        assert len(outputs) == len(rids)
```

**Lesson:** the batching *policy* was right, but a synchronous caller that force-flushes to obtain its own result **defeats batching entirely** — each request effectively flushes a batch of one (and `_flush_once` even loops calling the callable per item, so there is no batched call at all). `self._pending_outputs.pop(rid)` will `KeyError` if the assumption fails.

The correct shape is what [`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §4.2 specifies: an **async submit returning a future**, resolved by a **single background consumer** that owns the flush decision. Do not let the requester drive the flush.

---

## 9. Result and data types

*`src/core/service_engine/types.py`*

```python
class ResultStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"


class NumpyArrayAsList(np.ndarray):
    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: type, handler: GetCoreSchemaHandler) -> CoreSchema:
        def validate_from_list(value):
            if isinstance(value, list):
                return np.array(value)
            raise ValueError("Expected a list to convert to numpy array")

        return core_schema.no_info_after_validator_function(
            validate_from_list,
            core_schema.list_schema(),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda x: x.tolist(), when_used="json"
            ),
        )


class RunEngineOutput(BaseModel):
    payload: Any | None
    status: ResultStatus
    error_message: str | None = None

    def extract_payload_or_raise(self) -> Any:
        if self.status == ResultStatus.SUCCESS and self.payload is not None:
            return self.payload
        else:
            raise RuntimeError(f"Tool execution failed with error: {self.error_message}")
```

**Keep:** the `status` + `payload` + `error_message` envelope (tool-swap's `/run` response) and `extract_payload_or_raise()`. `NumpyArrayAsList` is worth remembering as evidence that **numpy payloads need explicit handling** — our guidance is that handlers call `.tolist()`.

*`src/core/data/modalities.py`* (abridged)

```python
class ModalityType(str, Enum):
    TEXT = "text"
    CHEST_XRAY = "chest_xray"
    CT_SCAN = "ct_scan"
    EEG = "eeg"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ANY = "any"


class Modality(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    payload: Any
    modality_type: ModalityType

    @field_serializer("payload", when_used="json")
    def serialize_payload(self, value: Any) -> Any:
        """Serialize numpy arrays to lists for JSON compatibility."""
        if isinstance(value, np.ndarray):
            return value.tolist()
        return value

    # ... validators coercing strings to number/boolean, and checking that
    #     payload matches modality_type (also accepting lists of that type) ...


class Port(BaseModel):
    name: str
    type: ModalityType
    description: Optional[str] = None
    default_value: Optional[Modality] = None
```

**Verdict:** a fixed enum of healthcare modalities cannot express a generic zoo — adding a modality would require changing the router. Superseded by **D13**: types come from **JSON Schema**, and the domain vocabulary survives as open `x-semantic` hints (`semantic: dicom_path`) that need no router change. **Keep** the `Port` idea (name + type + description + default) as the authoring surface that compiles into JSON Schema, and keep the numpy serialisation lesson.

---

## 10. `ToolServiceDescriptor` — port this for `/tools`

*`src/core/tools/tool_service_descriptor.py`*

```python
class ToolServiceDescriptor(BaseModel):
    name: str
    doc: Optional[str]
    version: str

    input_schema: list[Port]
    output_schema: list[Port]

    # hardware: HardwareRequirements
    # endpoint: Optional[str] = None

    def to_node_text(self) -> str:
        parameter_list = ",".join([f"{x.name}: {x.type.value}" for x in self.input_schema])
        output_list = ", ".join([f"{x.name}: {x.type.value}" for x in self.output_schema])
        documentation = (
            self.doc + "\n" + "\n".join(
                [f"- {x.name}: {x.description}" for x in self.input_schema if x.description]
            )
            if self.doc else ""
        )
        return f"{self.name}({parameter_list}) -> {output_list}:\nDOC:{documentation}"
```

**`to_node_text()` is the reason descriptions are mandatory**: it renders a model as a signature-plus-doc block for injection into an LLM prompt, so an agent can discover and call models. **Keep the motivation, discard the mechanism.**

Per **D13** we emit **JSON Schema projected into standard tool definitions** instead ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §9). A hand-rolled prompt format like this one obliges every consumer to write a parser and cannot be fed to an LLM provider's `tools=[...]` parameter; the standard shape can. Port the *descriptor* (name, doc, input/output schema, version) and drop the renderer.

---

## 11. A real class tool — the authoring target

*`src/core/tools/embedding/cxr_to_embedding.py`* (complete)

```python
"""Chest X-ray to embedding tool."""

import logging

from pydantic import Field

from core.tools.tool_decorator import class_tool
from core.utils.types import Batchable

logger = logging.getLogger(__name__)


@class_tool(name="cxr_to_embedding")
class CXRToEmbedding:
    """Convert the chest X-ray image at the provided PATH into a vector
    EMBEDDING using the RAD-DINO foundation model.
    """

    def __init__(self, device: str = "cpu", gpu_id: int | None = None):
        if device == "cuda" and gpu_id is not None:
            device += f":{gpu_id}"
        elif device == "cpu" and gpu_id is not None:
            logger.warning(
                "GPU ID provided but device is set to 'cpu'. Ignoring GPU ID and using CPU."
            )

        self.device = device
        self.model = None

    def load(self) -> None:
        """Load resources required for the tool."""
        from core.models.vision.rad_dino import RADDINO

        self.model = RADDINO(cache_folder=None, device=self.device)

    def unload(self) -> None:
        """Release resources used by the tool."""
        self.model = None

    def __call__(
        self,
        paths: Batchable[str] = Field(
            description="Path STRING to a DICOM chest X-ray image to use as input to the foundation model to be converted into a vector EMBEDDING"
        ),
    ) -> list[list[float]]:
        """Create embeddings for the chest X-ray image(s).

        Args:
            paths: A single path or a list of paths to DICOM chest X-ray images.

        Returns:
            A list of embeddings of the shape (N, 768), where N is the number of images.
        """
        from core.utils.dicom_helper import load_image_from_dicom

        if self.model is None:
            raise ValueError("Model not loaded. 'load' must be called first.")

        if isinstance(paths, list):
            images = [load_image_from_dicom(p) for p in paths]
        else:
            images = load_image_from_dicom(paths)

        embeddings = self.model.encode(images)

        return embeddings.tolist()
```

**This is the shape a tool-swap handler must be able to express** ([`03_TOOL_AUTHORING.md`](03_TOOL_AUTHORING.md) §2). Note what is already right: heavy imports inside `load`, weights released in `unload`, a guard that `load` ran, `Batchable[str]` for batching, paths rather than inlined blobs, `.tolist()` for JSON, and mandatory field descriptions and docstrings. The only changes for tool-swap are `__call__` → `predict`, the decorator's import path, dropping the `gpu_id` arithmetic (Docker remaps devices), and adding a `tool.yaml`.

Also worth recording — from the R8 COMPASS/Keras tool's `unload()`, the comment that most concisely justifies process isolation:

```python
    def unload(self) -> None:
        """
        Releases the in-memory pipeline and frees associated resources
        Sets :attr:`model` back to None so that :attr:`is_loaded` returns False.
        Also call ``tf.keras.backend.clear_session()`` externally to fully release GPU memory
        (process-wide reset, not scoped to this model alone)
        """
        self.keras_model = None
        self.preprocessing = None
        tf.keras.backend.clear_session()
```

---

## 12. `ToolContext` — out of scope, keep for the R8 client

*`src/core/service_engine/tool_context.py`*

```python
class ToolInvoker(Protocol):
    def run_single(self, tool_id: str, inputs: dict[str, Modality], ctx: "ToolContext") -> RunEngineOutput: ...


@dataclass(frozen=True)
class ToolContext:
    """
    Execution context for tools, tracking node id, max recursion depth etc.
    """
    run_id: str
    node_id: Optional[str]
    depth: int
    invoker: ToolInvoker
    max_depth: int = 10

    def child(self, *, node_id: Optional[str] = None) -> "ToolContext":
        if self.depth >= self.max_depth:
            raise RuntimeError(f"Max tool call depth exceeded (max_depth={self.max_depth})")
        return replace(self, depth=self.depth + 1, node_id=node_id or self.node_id)

    def run_tool(self, tool: str, inputs: dict[str, Modality]) -> RunEngineOutput:
        return self.invoker.run_single(tool, inputs, ctx=self.child())
```

Not in tool-swap ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §8). Relevant to [`11_R8_CLIENT_PLAN.md`](11_R8_CLIENT_PLAN.md) §3.4. Keep the `run_id` + depth-limit idea in mind if inter-model calls are ever revisited.

---

## 13. The API endpoints — and the positional-mapping bug

*`src/api/api_services.py`*

```python
class RunModelRequest(BaseModel):
    model_id: str
    input_modalities: List[Modality]


class RunEngineAPI:
    def __init__(self, node_factory: NodeFactory):
        self.router = APIRouter(prefix="/api")
        self.node_factory = node_factory

        @self.router.post("/run_model", response_model=RunEngineOutput, tags=[SERVICE_TAG],
                          summary="Run inference using a specific model with a given input.")
        def run_model(req: RunModelRequest, engine: RunEngine = Depends(get_run_engine)):
            try:
                root_ctx = ToolContext(run_id=str(uuid.uuid4()), node_id=None, depth=0, invoker=engine)
                # Convert List[Modality] to Dict[str, Modality] for internal interface
                # Map inputs to port names by order (maintains backward compatibility)
                input_dict = {}
                tool_spec = next((tool for tool in engine.tool_registry if tool.name == req.model_id), None)
                if tool_spec:
                    for i, modality in enumerate(req.input_modalities):
                        if i < len(tool_spec.input_ports):
                            port_name = tool_spec.input_ports[i].name
                            input_dict[port_name] = modality

                out = engine.run_single(req.model_id, input_dict, root_ctx)
            except ValueError as e:
                raise HTTPException(status_code=500, detail=str(e))

            return out

        @self.router.get("/list_services", tags=[SERVICE_TAG], summary="List all available services.")
        def list_services(engine: RunEngine = Depends(get_run_engine)):
            return {"services": engine.list_services()}
```

**Two documented bugs, both fixed in our contract** ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §2, §6):

1. **Positional→named mapping by index.** Reorder your arguments and you silently get wrong results. Worse, if `tool_spec` is `None` the loop is skipped and `run_single` is called with an **empty** input dict. Hence: named `inputs` only.
2. **Every `ValueError` becomes HTTP 500**, including "unknown model", which should be 404.

Also note `engine.run_single` is called synchronously inside a `def` (not `async def`) route — FastAPI runs it in a threadpool, which is workable but the concurrency semantics are accidental rather than designed.

---

## 14. Tool discovery and lifecycle testing — ideas for `tswap validate`

*`src/core/tools/tool_loader.py`* (abridged) — module-import-based discovery:

```python
    def _auto_discover_tools_from_list(self, modules: List[str]) -> List[ToolSpecification]:
        logger.info(f"Auto-discovering tools from modules: {modules}")
        all_tools = []
        for module_name in modules:
            try:
                module = importlib.import_module(module_name)
                tools = discover_tools(module)
                all_tools.extend(tools)
                logger.info(f"Loaded {len(tools)} tools from module {module_name}")
            except ImportError as e:
                logger.warning(f"Could not import module {module_name}: {e}")
                continue
        return all_tools
```

**Note the failure mode:** a broken import is a *warning*, so a model can silently vanish from the registry. Our config is explicit, and a missing/broken model is a hard validation error.

*`src/core/tools/tool_tester_cli.py`* (abridged) — the lifecycle smoke tester, whose *idea* we keep in `tswap validate` / `tswap test`:

```python
def test_tool_lifecycle(spec: ToolSpecification):
    execution_error = ErrorLog()
    loading_error = ErrorLog()
    unloading_error = ErrorLog()

    if spec.impl_cls is None:
        fn = spec.get_callable()
        try:
            dummy_inputs = {p.name: generate_dummy_value(p.type) for p in spec.input_ports}
            fn(**dummy_inputs)
        except Exception as e:
            execution_error.as_error = True
            execution_error.message = str(e)
        return execution_error, None, None

    cls = spec.impl_cls
    try:
        tool = cls()
    except Exception as e:
        loading_error.as_error = True
        loading_error.message = str(e)
        return None, loading_error, None

    if hasattr(tool, "load"):
        try:
            tool.load()
        except Exception as e:
            loading_error.as_error = True
            loading_error.message = str(e)
    ...
```

Generating dummy inputs from the declared schema and exercising `load` → `predict` → `unload` is a genuinely good check. Our version uses `tool.yaml`'s `example` when present and falls back to generated dummies, and runs inside the real container.

---

## 15. Docker and compose patterns worth keeping

*`docker/docker-compose.yml`* (abridged)

```yaml
services:
  healthcare-api:
    build: { context: .., dockerfile: src/api/Dockerfile }
    ports: ["8101:8101"]
    volumes:
      - ${DATA_DIR}:/app/data/mimic/api_data/
      - ${HF_HOME}:/root/.cache/huggingface
    command: python3 launch_api.py --config-name=docker
    profiles: ["backend", "full-stack"]
    deploy:
      resources:
        reservations:
          devices:
            - capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8101/health"]
      interval: 10s
      timeout: 10s
      retries: 3
      start_period: 5s
    depends_on:
      vllm_general:
        condition: service_healthy
    environment:
      - HF_TOKEN=${HF_TOKEN}

  vllm_general:
    build: { context: .., dockerfile: docker/vllm/Dockerfile }
    container_name: vllm_general-service
    ports: ["8102:8000"]
    volumes:
      - ${HF_HOME}:/root/.cache/huggingface
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              device_ids: ['${VLLM_DEVICE_ID}']
              capabilities: [gpu]
    command:
      - "--model"
      - "Qwen/Qwen2.5-7B-Instruct-AWQ"
      - "--host"
      - "0.0.0.0"
      - "--enforce-eager"
      - "--gpu-memory-utilization"
      - "0.9"
    healthcheck:
      # Give vLLM time to start up (e.g., load the model etc.)
      # Port 8000 is used as healthchecks run in the container namespace
      test: ["CMD", "curl", "-f", "http://0.0.0.0:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
```

*`docker/vllm/Dockerfile`* (complete)

```dockerfile
FROM nvidia/cuda:12.5.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install Python and dependencies
RUN apt-get update && apt-get install -y \
    python3-pip python3-dev git curl \
    && rm -rf /var/lib/apt/lists/*

# Install vLLM (PARADIM requires <=v0.17.1 for NVIDIA driver compatibility)
RUN pip3 install --upgrade pip
RUN pip3 install vllm==0.17.1

# Set entrypoint to match the official vLLM server
ENTRYPOINT ["python3", "-m", "vllm.entrypoints.openai.api_server"]
```

**Patterns to keep:**

- **`${HF_HOME}` mounted into every container.** This is what makes container restarts cheap instead of catastrophic, and it is why a shared weights cache is a *default* in tool-swap rather than an option ([`01_ARCHITECTURE.md`](01_ARCHITECTURE.md) §10).
- **`start_period` on healthchecks.** Model containers need a long grace period; a naive healthcheck marks a loading model unhealthy. Our `start_timeout`/`ready_timeout` split is the same insight.
- **The healthcheck runs in the container's namespace**, so it must target the *internal* port — note the comment in their compose file. An easy mistake when models are addressed by container name.
- **`device_ids: ['${VLLM_DEVICE_ID}']`** — explicit device pinning, which is exactly our `devices: [int]`.
- **vLLM as a separate service with its own image**, consumed over an OpenAI-compatible base URL. Note what this actually demonstrates, given that tool-swap hosts no LLMs: **LLM serving was already a separate concern with its own lifecycle**, which is precisely why it now belongs to llama-swap rather than here ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §0). The compose file is reference material for container wiring, not a template for a `kind: external` that no longer exists.
- **`--enforce-eager` and `--gpu-memory-utilization 0.9`** as `args:` — precisely the pass-through-arguments pattern.
- **Profiles** (`backend`, `full-stack`, `vllm`) to select subsets of services. Our equivalent is groups plus `keep_warm`, but profiles are worth remembering if compose-level selection is ever wanted.
- A pinned vLLM version with a comment explaining the driver constraint — the kind of environment coupling that per-model images make harmless.

---

## 16. `Batchable` — the batching declaration

*`src/core/utils/types.py`* (complete — all four lines of it)

```python
from typing import List, TypeVar, Union


T = TypeVar("T")
Batchable = Union[T, List[T]]
```

Tiny, and load-bearing: this alias is how an R8 tool declared "you may hand me a list where a scalar is expected", which is what makes micro-batching safe. The tool builder detected it by inspecting whether an annotation was `Union[T, List[T]]`:

```python
def is_batchable(annotation: Any) -> Any:
    """
    Check if the type is a Union[T, List[T]] and return the inner type T
    """
    origin = get_origin(annotation)
    if origin is not Union:
        return None

    args = get_args(annotation)
    if len(args) != 2:
        return None

    type_t, type_list_t = args

    list_origin = get_origin(type_list_t)
    list_args = get_args(type_list_t)

    if list_origin is list and len(list_args) == 1 and list_args[0] == type_t:
        return type_t

    return None
```

**Verdict:** keep the *concept*, move the *declaration* into `tool.yaml` as `batchable: true` ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §4.3). Reason: the router must know which inputs are batchable **without importing the model's code**, which is impossible across a container boundary by design. Optionally keep `Batchable[T]` as sugar that the `@tool` decorator translates into the declaration, so authors migrating from R8 recognise it.

---

## 17. Documentation prose worth reusing verbatim

From *`src/core/tools/README.md`* — the authoring guidance is already correct and can be lifted almost word-for-word into `docs/adding-a-model.md`:

> ### Manage heavy resources in lifecycle hooks
>
> If your tool loads:
>
> * GPU tensors
> * machine learning models
> * large datasets
>
> these operations should be placed in `load()` and released in `unload()`.
>
> **Avoid performing heavy work inside `__init__`.**

> ### Requirements
>
> When implementing a function tool:
>
> * **A docstring is mandatory** and must clearly describe what the tool does.
> * **All inputs must be explicitly typed.**
> * **The return value must also be typed.**
> * Each parameter **must include a `Field(description=...)`** explaining the input.
> * Use **clear function names and clear parameter names** so the tool's purpose is immediately understandable.

And its good/bad naming example, which is worth keeping because it teaches the discipline concretely:

```python
# Bad
@tool
def compute_value(a: str = Field(description="Main parameter"),
                  sigma: str = Field(description="Sigma of the function")) -> list[str]:
    """Transform text into tokens."""

# Good
@tool
def smooth_text(
    input_text: str = Field(description="Input text to process"),
    smoothing_sigma: float = Field(description="Standard deviation controlling the smoothing strength from 0 to 1 zero being no smoothing"),
) -> list[str]:
    """Apply a smoothing transformation to an input text and return the processed tokens."""
```

From *`src/core/service_engine/ReadMe.md`* — the original statement of intent, which tool-swap should be measured against:

> ## ✨ Key Capabilities
>
> * **Simple external API** — callers send 1 input at a time; no batching required.
> * **Automatic micro-batching** — requests are queued and grouped dynamically.
> * **High GPU utilization** — actors keep models warm and handle parallel execution.
> * **Modular architecture** — swap models, modify batching policy, or replace the executor without touching the API.
> * **Fully testable**: pure Python unit tests; REST API tests without Ray; integration tests with dummy actors or real models.

Note its "🔧 Adding a New Model" section reads, in full: **"Coming soon"**. Requirement **R2** — making that section unnecessary because the process is obvious — is the gap tool-swap exists to close.

---

## 18. The decorator and the specification builder — what "declare as data" replaces

*`src/core/tools/tool_decorator.py`* (complete)

```python
from __future__ import annotations

from typing import Any, Callable, Optional, TypeVar, Union, overload

from core.tools.tool_builder import (
    ToolOutputDefinitionError,
    _build_tool_specification_from_callable,
)

C = TypeVar("C", bound=type)
F = TypeVar("F", bound=Callable[..., Any])
TOOL_ATTRIBUTE_NAME = "_tool_specification"


def tool(
    __fn: Optional[F] = None, *, name: Optional[str] = None
) -> Union[F, Callable[[F], F]]:
    def _wrap(fn: F) -> F:
        fn_name = name or fn.__name__
        spec = _build_tool_specification_from_callable(
            fn,
            name=fn_name,
            doc=fn.__doc__,
            skip_first_param=False,
        )
        setattr(fn, TOOL_ATTRIBUTE_NAME, spec)
        return fn

    if __fn is not None:
        return _wrap(__fn)
    return _wrap


def class_tool(
    __cls: Optional[C] = None,
    *,
    method: str = "__call__",
    name: Optional[str] = None,
) -> Union[C, Callable[[C], C]]:
    def _wrap(cls: C) -> C:
        try:
            raw_attr = getattr(cls, method)
        except AttributeError:
            raise ToolOutputDefinitionError(
                f"Method {method!r} not found on class {cls.__name__}"
            )

        fn = raw_attr
        if isinstance(raw_attr, (staticmethod, classmethod)):
            fn = raw_attr.__func__

        node_name = name or cls.__name__
        doc = cls.__doc__

        tool_specification = _build_tool_specification_from_callable(
            fn,
            name=node_name,
            doc=doc,
            skip_first_param=True,   # drop "self"/"cls" from ports
            class_impl=cls,
            impl_method=method,
        )
        setattr(cls, TOOL_ATTRIBUTE_NAME, tool_specification)
        return cls

    if __cls is not None:
        return _wrap(__cls)
    return _wrap
```

**This is the mechanism tool-swap deliberately does not port**, and seeing it makes the reason concrete. The decorator attaches a specification built by **importing the tool's module and introspecting its signature**. In a Docker-first design the router runs in a different container with a different interpreter and cannot import the tool's code at all — so the schema must be *declared as data* (`tool.yaml`) or *served by the tool itself* at `/schema` (**D6**, **D13**).

The parts of `tool_builder.py` worth knowing, since the plan refers to its ~440 lines repeatedly:

```python
        if isinstance(param.default, FieldInfo):
            fi = param.default
            if fi.description is None:
                raise ToolInputDefinitionError(
                    f'Missing description for parameter {pname} in function {name}, '
                    'use Field(description="...") to add a description.'
                )
            ...
        else:
            raise ToolInputDefinitionError(
                f'Missing description for parameter {pname} in function {name}, '
                'use Field(description="...") to add a description.'
            )

    if out_adapter is None:
        raise ToolOutputDefinitionError(
            f"Output type annotation is missing from function {name}"
        )

    if doc is None:
        raise ToolDocDefinitionError(f"Doc String is missing from function {name}")
```

**Keep this discipline, and note that it is enforcement, not documentation.** A tool without a docstring, without an output annotation, or with an undescribed parameter **fails at import**. That strictness is exactly why the registry could be handed to an LLM, and it is the direct ancestor of **D19** — with one deliberate change: we hard-error on the tool and its inputs, warn on outputs, and provide `--allow-missing-descriptions` for prototyping, because a rule with no escape hatch gets deleted rather than obeyed.

**Also keep** `from_node_description()` (§10 and [`11_R8_CLIENT_PLAN.md`](11_R8_CLIENT_PLAN.md) §3.1): a constructor that builds a specification from a *descriptor* rather than by importing code. It is what allows a consumer to stop importing tool code entirely.

---

## 19. The engine factory — the commented-out line that summarises the problem

*`src/core/service_engine/run_engine_factory.py`* (complete)

```python
from contextlib import asynccontextmanager
from fastapi import Request, FastAPI
from core.service_engine.local_engine.local_run_engine import LocalRuneEngine
from core.service_engine.run_engine import RunEngine
from core.tools.tool_builder import ToolSpecification
from core.utils.logger import get_logger


def create_lifespan(
    config_file: str,
    tool_specifications: list[ToolSpecification],
    verbose: bool = False,
):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # engine = BentoMLRunEngine(tool_specifications, config_file, verbose=verbose)
        engine = LocalRuneEngine(tool_specifications)
        app.state.engine = engine
        try:
            yield
        finally:
            # SHUTDOWN
            logger = get_logger()
            try:
                logger.info("Shutting down engine...")
                app.state.engine.shutdown()
            except Exception as e:
                logger.error(f"Engine shutdown failed: {e}")

    return lifespan


def get_run_engine(request: Request) -> RunEngine:
    return request.app.state.engine
```

**Read the commented line.** The better design — per-tool server processes with batching (§3) — was written, worked, and was then switched off in favour of the in-process engine that reloads the model on every request (§2). Not because it was wrong, but because running it inside the monolith was too painful: every tool still had to be importable in one environment, and every tool was started eagerly at boot.

**That single comment is the justification for this entire project.** Extracting the engine is what makes the good design affordable.

It is also the seam for [`11_R8_CLIENT_PLAN.md`](11_R8_CLIENT_PLAN.md): swapping in a client-backed engine is a one-line change here.

---

## 20. The TensorFlow/Keras tool — the isolation argument in the original author's own words

*`src/core/tools/compass/organ_donor.py`* (abridged — the file is ~700 lines and contains two tools, XGBoost and Keras, over the same tabular features)

```python
import keras
import numpy as np
import pandas as pd
import tensorflow as tf
from pydantic import BaseModel, Field

from core.tools.tool_decorator import class_tool

tf.get_logger().setLevel("ERROR")


@class_tool
class NeuralNetworkEstimateOrganDonorProbabilityOutput:
    def __init__(self, model_dir=..., gpu_id: Optional[int] = None) -> None:
        ...
        if gpu_id is not None:
            # Restrict to a specific GPU
            gpus = tf.config.list_physical_devices("GPU")
            if gpu_id >= len(gpus):
                raise ValueError(
                    f"GPU {gpu_id} requested but only {len(gpus)} GPU(s) are available."
                )
            tf.config.set_visible_devices(gpus[gpu_id], "GPU")

    @property
    def is_loaded(self) -> bool:
        return self.keras_model is not None

    def load(self) -> "NeuralNetworkEstimateOrganDonorProbabilityOutput":
        for p in (self.keras_path, self.prep_path, self.calib_path):
            if not p.exists():
                raise FileNotFoundError(
                    f"Required artifact not found at '{p}'. "
                    "Ensure all three NN artifacts have been downloaded."
                )

        if not self.is_loaded:
            self.keras_model = keras.models.load_model(self.keras_path, compile=False)
            with open(self.prep_path, "rb") as f:
                self.preprocessing = pickle.load(f)
            with open(self.calib_path) as f:
                cal = json.load(f)
            self.sigmoid_a = cal["sigmoid_a"]
            self.sigmoid_b = cal["sigmoid_b"]
        return self

    def unload(self) -> None:
        """
        Releases the in-memory pipeline and frees associated resources

        Sets :attr:`model` back to None so that :attr:`is_loaded` returns False.
        Also call ``tf.keras.backend.clear_session()`` externally to fully release GPU memory
        (process-wide reset, not scoped to this model alone)
        """
        self.keras_model = None
        self.preprocessing = None
        tf.keras.backend.clear_session()
```

**This is the single most important file in this document**, because it is the argument for **D2** written by someone who was not making an argument.

- The `unload()` docstring is a confession: *"process-wide reset, not scoped to this model alone."* **A tool cannot release its own GPU memory without disturbing every other tool in the process.** No amount of careful coding fixes that; only a process boundary does.
- `tf.config.set_visible_devices(...)` is **process-global** and, in TensorFlow, must be called before the GPU is initialised. Two tools in one process cannot each pin their own device. Under Docker, `devices: [1]` does this correctly and invisibly, and the tool's code becomes device-agnostic.
- `tf.get_logger().setLevel("ERROR")` at import time reconfigures logging for the whole process, because one tool wanted quieter output.
- And this file coexists in one interpreter with `torch==2.8.0+cu129` and a URL-pinned flash-attention wheel (§21).

**Migration note:** this is the tool to port *first* ([`09_IMPLEMENTATION_PLAN.md`](09_IMPLEMENTATION_PLAN.md) M10), because it is the one that was structurally broken by the shared process. In its own image, `unload()` needs no caveat and `clear_session()` affects nothing but itself.

---

## 21. The dependency evidence, verbatim

Extracted from the backend's single pinned requirements file (~300 packages, one environment, all tools). These lines are quoted exactly:

```
bentoml==1.4.30
tensorflow==2.16.0rc0
tf-keras==2.15.0
torch==2.8.0+cu129
torchvision==0.23.0+cu129
transformers==4.56.1
monai==1.5.1
ray==2.49.1
numpy==1.26.4
autoawq==0.2.9
xgboost==2.1.2
rad-dino==0.1.1
gradio==5.49.1
fastapi==0.116.1
triton==3.4.0
```

plus a flash-attention wheel pinned by URL to an exact `cu12 / torch2.8 / cp312` build.

**What to notice, since this is the evidence for D2 rather than an illustration of it:**

- **TensorFlow and PyTorch in one interpreter**, both wanting the GPU, neither able to release it independently (§20).
- **`numpy==1.26.4`** pins the entire zoo to numpy 1.x. Any tool needing numpy 2.x cannot be added — and note the *frontend's* requirements file, a separate environment, already uses `numpy==2.3.3`. The split exists in the same project; it simply cannot exist within the backend.
- **A URL-pinned flash-attention wheel** couples the whole environment to one exact CUDA/torch/Python combination. Upgrading torch for one tool breaks the binary wheel for another.
- **`gradio` and `fastapi` in the same lock file as `torch` and `tensorflow`** — the frontend framework and the ML stack must resolve together.
- **`bentoml==1.4.30`** is in this list. The framework was never the problem; the *shared environment* was. Under **D14** BentoML lives inside each tool image, where it competes with exactly one tool's pins ([`00_CONTEXT_AND_MOTIVATION.md`](00_CONTEXT_AND_MOTIVATION.md) §2.3).

Adding one tool means re-resolving all of it. That is the cost per-tool images remove.

---

## 22. A pure-CPU tool — the small end of the zoo

*`src/core/tools/vision/estimate_tb_from_cxr_embedding.py`* (complete)

```python
import logging

import torch
from pydantic import Field
from core.models.vision.tb_classifier import TBClassifier
from core.tools.tool_decorator import class_tool
from core.utils.types import Batchable

logger = logging.getLogger(__name__)


@class_tool(name="estimate_tb_from_cxr_embedding")
class EstimateTBFromCXREmbedding:
    """Estimate the probability of tuberculosis (TB) given an EMBEDDING
    from a chest X-ray image generated by the `cxr_to_embedding` tool.
    """

    def __init__(self, device: str = "cpu", gpu_id: int | None = None):
        if device == "cuda" and gpu_id is not None:
            device += f":{gpu_id}"
        elif device == "cpu" and gpu_id is not None:
            logger.warning(
                "GPU ID provided but device is set to 'cpu'. Ignoring GPU ID and using CPU."
            )

        self.device = device
        self.model = None

    def load(self) -> None:
        """Load resources required for the tool."""
        self.model = TBClassifier(device=self.device)

    def unload(self) -> None:
        """Release resources used by the tool."""
        self.model = None

    def __call__(
        self,
        embeddings: Batchable[list[float]] = Field(
            description="A CXR EMBEDDING generated by the 'cxr_to_embedding' tool"
        ),
    ) -> list[float]:
        """Estimate the probability of tuberculosis (TB) given an
        EMBEDDING from a chest X-ray image.

        Args:
            embeddings: A single embedding or a list of embeddings
                generated by the `cxr_to_embedding` tool, where each
                embedding is a list of 768 floats.

        Returns:
            A list of probabilities of having TB corresponding to each
            input embedding.
        """
        if self.model is None:
            raise ValueError("Model not loaded. 'load' must be called first.")

        if not isinstance(embeddings, list):
            embeddings = [embeddings]

        embeddings_tensor = torch.tensor(embeddings, dtype=torch.float32).to(self.device)
        probabilities = self.model.predict(embeddings_tensor)

        return probabilities.flatten().cpu().tolist()
```

**Why this one is included.** It is a classifier head of a few megabytes, and it demonstrates three things the plan depends on:

1. **The zoo is not uniform.** This tool is tiny and CPU-viable; the CT segmenter is neither. It is the concrete case behind **D23**'s answer to "one container each is wasteful": put it on the CPU with `keep_warm: true`, where it costs no GPU slot and is always available. Packing several such tools into one image would reintroduce the shared environment for a saving of a few hundred megabytes.
2. **Tools compose.** Its input is another tool's output (`cxr_to_embedding` produces a 768-float embedding). That composition belongs to the orchestration layer, not to tool-swap ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §8) — but it is why `x-semantic` hints and honest descriptions matter, since an agent has to know these two connect.
3. **`Batchable[list[float]]`** is the batching declaration on a non-scalar type, which becomes `x-batchable` in the compiled schema (§16).

Note the `gpu_id` arithmetic in `__init__`, repeated near-verbatim across tools. Under Docker it disappears: the container sees only the devices it was given, so the tool always addresses `cuda:0` or `cpu`.

---

## 23. Summary: the port checklist

| R8 artefact | Action | Destination |
|---|---|---|
| `CoreBatcher` | **Not ported in v1** (**D14**); kept as the `native` backend's spec | `tool_swap_runtime/backends/NATIVE.md` |
| BentoML `service_factory` | Port the **ideas** (bind-then-warm-up, batched API, per-item validation, log the knobs); reject `globals()[...] = cls` and the swallowed warm-up exception | `tool_swap_runtime/backends/bentoml_backend.py` |
| `BentoServiceProcess` | Port structure; fix the unbounded readiness loop, add drain, always log | `tool_swap/lifecycle/`, `tool_swap/backend/` |
| `ToolServiceDescriptor` (descriptor only) | Port; replace `to_node_text()` with standard projections (**D13**) | `tool_swap/api/discovery.py`, `tool_swap/schema/` |
| `RunEngineOutput` | Adapt as the response envelope | `tool_swap/api/errors.py`, runtime |
| Config `defaults` + overrides | Adapt, add `extra="forbid"` | `tool_swap/config/schema.py` |
| `Port` (name/type/description/default) | Adapt as the authoring surface; compile to JSON Schema (**D13**) | `tool_swap/config/schema.py`, `tool_swap/schema/compile.py` |
| `Batchable` concept | Re-express as `batchable: true` in YAML. Note **D15**: on a batched tool, *every* input must be batchable, and per-request knobs become `params:` | `tool.yaml` |
| `class_tool` lifecycle contract | Simplify to `load`/`predict`/`unload` | `tool_swap_runtime/decorator.py` |
| `tools/README.md` prose | Reuse near-verbatim | `docs/adding-a-model.md` |
| Compose/HF-cache/device-pinning patterns | Reuse | `docker-compose.yml`, backend |
| `tool_tester_cli` lifecycle check | Reuse the idea | `tswap validate` / `tswap test` |
| `Modality` / `ModalityType` | **Do not port** (closed enum; JSON Schema + `x-semantic` replaces it) | — |
| `ToolContext.run_tool` | **Do not port** (orchestration; deadlock risk) | R8-side adapter only |
| `tool_builder` introspection (~440 lines) | **Do not port** (declare as data instead) | — |
| Hydra config, auth, job API | **Do not port** | — |
| Module-import tool discovery | **Do not port** (impossible across containers) | — |
| `LocalRuneEngine` unconditional unload | **Do not port** (it is the bug we are fixing) | — |
# Health endpoints, readiness and the startup sequence — **source excerpt, not documentation**

> **Source:** the BentoML repository, `main` branch, read 2026-08-13:
> - [`src/bentoml/_internal/server/base_app.py`](https://github.com/bentoml/BentoML/blob/main/src/bentoml/_internal/server/base_app.py) (`BaseAppFactory`)
> - [`src/_bentoml_impl/server/app.py`](https://github.com/bentoml/BentoML/blob/main/src/_bentoml_impl/server/app.py) (`ServiceAppFactory`)
>
> **BentoML version:** `main` at time of reading; the released line is **1.4.39**. `main` is *ahead of* the release — **re-verify against the pinned tag in M3.5.**
> **Captured:** 2026-08-13
> **Why this file exists:** [`05_RUNTIME_AND_BATCHING.md`](../../05_RUNTIME_AND_BATCHING.md) §3 and §3.2 make four claims about BentoML's health endpoints that are **not stated anywhere on the documentation site**. The docs mention *"health check endpoints"* exactly once, in passing, in the `path_prefix` parameter description ([`sdk-reference.md`](sdk-reference.md)). This file settles the question from the implementation.
> **Completeness:** **excerpt.** Only the routing, readiness, lifecycle, threading and error-mapping fragments bearing on our contract are reproduced. Code is verbatim.

---

## 1. The system routes and their default paths

From `BaseAppFactory.get_system_routes`:

```python
def get_system_routes(self, path_prefix: str = "") -> list[BaseRoute]:
    from starlette.routing import Route

    from ..configuration.containers import BentoMLContainer

    routes: list[BaseRoute] = []
    routes.append(
        Route(
            path=join_paths(path_prefix, "/livez"),
            name="livez",
            endpoint=self.livez,
        )
    )
    routes.append(
        Route(
            path=join_paths(path_prefix, "/healthz"),
            name="healthz",
            endpoint=self.livez,
        )
    )
    routes.append(
        Route(
            path=join_paths(path_prefix, "/readyz"),
            name="readyz",
            endpoint=self.readyz,
        )
    )
    if BentoMLContainer.api_server_config.metrics.enabled.get():
        routes.append(
            Route(
                path=join_paths(path_prefix, "/metrics"),
                name="metrics",
                endpoint=self.metrics,
            )
        )
    return routes
```

Note `/healthz` and `/livez` share one endpoint — `self.livez`. `/metrics` is registered **only if metrics are enabled**.

`ServiceAppFactory.routes` also adds `/schema.json`, the per-API `POST` routes at `method.route`, and — for `@bentoml.task` methods — `/submit`, `/status`, `/get`, `/retry`, `/cancel`.

## 2. The default liveness and readiness implementations

From `BaseAppFactory`:

```python
class BaseAppFactory(abc.ABC):
    _is_ready: bool = False

    @property
    def on_startup(self) -> list[LifecycleHook]:
        return [self.mark_as_ready]

    def mark_as_ready(self, _: Starlette) -> None:
        self._is_ready = True

    async def livez(self, _: Request) -> Response:
        """
        Health check for BentoML API server.
        Make sure it works with Kubernetes liveness probe
        """
        return PlainTextResponse("\n", status_code=200)

    async def readyz(self, _: Request) -> Response:
        if self._is_ready:
            return PlainTextResponse("\n", status_code=200)
        raise HTTPException(500)
```

## 3. The Service-level overrides — **`__is_alive__`, `__is_ready__`, `__metrics__`**

From `ServiceAppFactory`:

```python
async def livez(self, _: Request) -> Response:
    from starlette.exceptions import HTTPException

    from bentoml._internal.utils import is_async_callable

    if hasattr(self.service.inner, "__is_alive__"):
        assert self._service_instance is not None, "Service must be initialized"
        if is_async_callable(self.service.inner.__is_alive__):
            is_alive = await self._service_instance.__is_alive__()
        else:
            is_alive = await anyio.to_thread.run_sync(
                self._service_instance.__is_alive__
            )
        if not is_alive:
            raise HTTPException(
                status_code=503,
                detail="Service is dead because .__is_alive__() returns False.",
            )
    return await super().livez(_)

async def readyz(self, _: Request) -> Response:
    from starlette.exceptions import HTTPException
    from starlette.responses import PlainTextResponse

    from bentoml._internal.utils import is_async_callable

    from ..client import RemoteProxy

    if hasattr(self.service.inner, "__is_ready__"):
        assert self._service_instance is not None, "Service must be initialized"
        if is_async_callable(self.service.inner.__is_ready__):
            is_ready = await self._service_instance.__is_ready__()
        else:
            is_ready = await anyio.to_thread.run_sync(
                self._service_instance.__is_ready__
            )
        if not is_ready:
            raise HTTPException(
                status_code=503,
                detail="Service is not ready because .__is_ready__() returns False.",
            )

    if BentoMLContainer.api_server_config.runner_probe.enabled.get():
        dependency_statuses: list[t.Coroutine[None, None, bool]] = []
        for dep_name in self.service.dependencies:
            real = getattr(self._service_instance, dep_name)
            if isinstance(real, RemoteProxy):
                dependency_statuses.append(real.is_ready(5))
        runners_ready = all(await asyncio.gather(*dependency_statuses))

        if not runners_ready:
            raise HTTPException(status_code=503, detail="Runners are not ready.")

    return PlainTextResponse("\n", status_code=200)
```

There is a matching `__metrics__` hook, which post-processes the Prometheus exposition text before it is returned.

## 4. The startup sequence — the instance is created *inside* the lifespan, before serving

```python
@contextlib.asynccontextmanager
async def lifespan(self, app: Starlette) -> t.AsyncGenerator[None, None]:
    from starlette.applications import Starlette

    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(super().lifespan(app))

        await self.create_instance(app)
        stack.push_async_callback(self.destroy_instance, app)
        ...
        yield
```

and, in `create_instance`:

```python
self._service_instance = self.service()
self.service.gradio_app_startup_hook(max_concurrency=self.max_concurrency)
logger.info("Service %s initialized", self.service.name)

# Call on_startup hook with optional ctx or context parameter
for name in dir(self.service.inner):
    member = getattr(self.service.inner, name)
    if (
        not name.startswith("__")
        and callable(member)
        and getattr(member, "__bentoml_startup_hook__", False)
    ):
        logger.info("Running startup hook: %s", name)
        ...
```

`destroy_instance` symmetrically runs `__bentoml_shutdown_hook__` methods.

## 5. Threading — `threads` defaults to 1

```python
async def _to_thread(self, func, *args, **kwargs):
    if self._limiter is None:
        threads = self.service.config.get("threads", 1)
        self._limiter = anyio.CapacityLimiter(threads)
    func = functools.partial(func, *args, **kwargs)
    output = await anyio.to_thread.run_sync(func, limiter=self._limiter)
    return output
```

Synchronous API methods are dispatched through `_to_thread`.

## 6. The dispatcher, its overload fallback, and the batch-size metric

```python
def fallback() -> t.NoReturn:
    raise ServiceUnavailable("process is overloaded")

for name, method in service.apis.items():
    if not method.batchable:
        continue
    self.dispatchers[name] = CorkDispatcher(
        max_latency_in_ms=method.max_latency_ms,
        max_batch_size=method.max_batch_size,
        fallback=fallback,
        get_batch_size=functools.partial(
            AutoContainer.get_batch_size, batch_dim=method.batch_dim[0]
        ),
        batch_dim=method.batch_dim,
    )
```

The adaptive batch size is recorded as a Prometheus histogram, namespace `bentoml_service`, name `adaptive_batch_size`, with labels `runner_name`, `worker_index`, `method_name`, `service_version`, `service_name`.

Batching enforces the single-argument rule in code:

```python
arg_names = [k for k in input_kwargs if k != method.ctx_param]
if input_args:
    if len(input_args) > 1 or len(arg_names) > 0:
        raise TypeError("Batch inference function only accept one argument")
    value = input_args[0]
else:
    if len(arg_names) != 1:
        raise TypeError("Batch inference function only accept one argument")
    value = input_kwargs.pop(arg_names[0])
```

## 7. Error mapping at the API boundary

```python
except ValidationError as exc:
    log_exception(request)
    data = {
        "error": f"{exc.error_count()} validation error for {exc.title}",
        "detail": exc.errors(include_context=False, include_input=False),
    }
    resp = JSONResponse(data, status_code=400)
except BentoMLException as exc:
    log_exception(request)
    status = exc.error_code.value
    if status in (401, 403):
        detail = {"error": "Authorization error"}
    elif status >= 500:
        detail = {"error": "An unexpected error has occurred, please check the server log."}
    else:
        detail = ({"error": str(exc)},)
    resp = JSONResponse(detail, status_code=status)
except Exception:
    log_exception(request)
    resp = JSONResponse(
        {"error": "An unexpected error has occurred, please check the server log."},
        status_code=500,
    )
```

Response headers are augmented with `Server: BentoML Service/{name}`, `X-BentoML-Request-ID`, and optionally `X-BentoML-Trace-ID`.

---

## tool-swap notes

Everything above is BentoML's. Everything below is ours.

### 1. **The endpoint names in [`05 §3`](../../05_RUNTIME_AND_BATCHING.md:146) are correct.** ✅

`/livez`, `/healthz`, `/readyz` and `/metrics` all exist at those paths, and `/healthz` is an alias of `/livez` (same endpoint object). The mapping table in §3 stands. Note `/metrics` is conditional on `api_server_config.metrics.enabled` — [`05 §9`](../../05_RUNTIME_AND_BATCHING.md:347) assumes it is there, so **the adapter must ensure metrics are enabled** rather than assume the default.

### 2. **[`05 §3.2`](../../05_RUNTIME_AND_BATCHING.md:159) is correct — and the reason is now precise.** ✅

The claim is that BentoML's `/readyz` *"reports that the server is up — which, for a model taking four minutes to load, is a lie in the only direction that matters."* The base implementation sets `_is_ready = True` in an `on_startup` hook that does nothing but flip the flag:

```python
def mark_as_ready(self, _: Starlette) -> None:
    self._is_ready = True
```

and the Service-level override, absent an `__is_ready__` hook, falls through to an unconditional `PlainTextResponse("\n", status_code=200)`. **Readiness is a property of the server, not of the weights.** R8 polling `/readyz` to decide a model was warm proved nothing, exactly as [`12_REFERENCE_CODE.md`](../../12_REFERENCE_CODE.md) §4 says.

One correction of detail: the *base* class raises `HTTPException(500)` when not ready, not 503. The Service-level override never reaches that branch. Not important for us — we serve our own `/ready` — but if anyone ever polls BentoML's endpoint directly, the failure code is not what a reader of §3.2 would guess.

### 3. **`__is_ready__` is an undocumented hook that does exactly what our contract needs.** ⭐ **New capability, not in the plan.**

If the service class defines `__is_ready__`, BentoML calls it on every `/readyz` request — sync or async, sync variants dispatched to a thread — and returns **503 with a reason** when it returns `False`:

```
"Service is not ready because .__is_ready__() returns False."
```

That is our [`05 §3.2`](../../05_RUNTIME_AND_BATCHING.md:159) semantics — 503 plus a reason while weights load — available natively. Likewise `__is_alive__` for liveness, and `__metrics__` for augmenting the Prometheus text.

**What it changes for M4.** [`09 M4`](../../09_IMPLEMENTATION_PLAN.md:154) has the adapter mounting `/health` and `/ready` as our own ASGI routes. That is still right — **the router speaks our contract, not BentoML's** ([`05 §3`](../../05_RUNTIME_AND_BATCHING.md:156)), and `/ready` must carry a structured `reason` and `detail` that a plain 503 does not. But the adapter should **also** wire `__is_ready__` to the same underlying state, for three reasons:

1. it makes `/readyz` truthful for anyone who bypasses our contract (a `docker run` user, a `curl`, a future Kubernetes probe — guardrail 11's standalone-image promise);
2. it is three lines;
3. it means one readiness fact with two projections, rather than two facts that can disagree.

**Caveat, and it is the important one:** these hooks are **not on the documentation site**. They are implementation details of `main`, discovered by reading source, and they could change without a release note. Treat them as a *bonus*, never as the mechanism our contract depends on. Our own mounted `/ready` remains the load-bearing one. Record in `NATIVE.md` that a native backend owes only our route, not these.

### 4. ⚠️ **The startup sequence contradicts [`05 §6`](../../05_RUNTIME_AND_BATCHING.md:298)'s bind-then-load design. This is the M4 trap.**

`lifespan` **awaits `create_instance` before yielding**, and `create_instance` calls `self.service()` — constructing the user's service class, i.e. running `__init__`, which in BentoML's own idiom is where the model is loaded:

```python
@bentoml.service
class Summarization:
    def __init__(self) -> None:
        self.pipeline = pipeline('summarization')   # ← loads here
```

Uvicorn does not accept connections until lifespan startup completes. Therefore, **if our adapter loads the handler in `__init__`, the port does not bind until loading is finished**, and during a four-minute load the router gets *connection refused* — not a 503 with `reason: loading`.

That breaks several things at once:

| Plan commitment | What happens if load runs in `__init__` |
| --- | --- |
| *"`/health` … must answer **before** weights load and must never block"* ([`05 §3`](../../05_RUNTIME_AND_BATCHING.md:147)) | Nothing answers. The socket is not listening. |
| The `STARTING` → `LOADING` → `READY` progression ([`01_ARCHITECTURE.md`](../../01_ARCHITECTURE.md) §4) | `LOADING` is unobservable; the two states collapse, losing the diagnostic value §4 explicitly argues for |
| *"`/ready` is 503 with a reason while loading"* (M4 contract suite, [`09 M4`](../../09_IMPLEMENTATION_PLAN.md:163)) | Untestable — no response at all |
| *"`load()` raising leaves `/ready` at 503 with the traceback"* ([`09 M4`](../../09_IMPLEMENTATION_PLAN.md:163)) | An exception in `__init__` fails lifespan startup and the process exits; there is no server left to report the traceback over HTTP |

**This is precisely why R8 used a background warm-up thread**, and [`05 §6`](../../05_RUNTIME_AND_BATCHING.md:299) already says so — *"Bind-then-load is kept from R8's BentoML service, which started warm-up on a background thread precisely so the HTTP server could bind at once."* What was missing is **why it was necessary**: not a stylistic choice, but the only way to bind before loading given this lifespan. R8's design was correct and its bug was narrow (swallowing the exception).

**Actions:**
- **M4 must load off the lifespan path** — background thread or task started from `__init__`/startup hook, returning immediately — and record the outcome (loaded, or the exception) in adapter state that `/ready` and `__is_ready__` both read. Anything else silently loses the `LOADING` state.
- **M3.5 should verify this before M4 builds on it.** It is a small addition to step 5 (the contract-feasibility step): sleep 30 s in `__init__`, then confirm whether the port is refusing connections throughout. Cheap, and it either confirms the design or invalidates a milestone's worth of assumptions.
- The failure-recording requirement in [`09 M4`](../../09_IMPLEMENTATION_PLAN.md:152) (*"background load with failure recorded and exposed"*) is not optional polish — it is what keeps a failed load debuggable instead of a bare process exit.

### 5. `threads` defaults to 1 — [`05 §5`](../../05_RUNTIME_AND_BATCHING.md:251) is right, and the spike needs the knob

```python
threads = self.service.config.get("threads", 1)
self._limiter = anyio.CapacityLimiter(threads)
```

A single `CapacityLimiter(1)` for **all** sync API calls in the worker. So [`05 §5`](../../05_RUNTIME_AND_BATCHING.md:253)'s rule — *"Exactly one inference at a time per worker"* — is BentoML's default, not something we must enforce. Good: our design and the framework agree, and the lock §5 describes is redundant for the sync path.

**But this is the trap flagged in [`adaptive-batching.md`](adaptive-batching.md) §6, and here it is in code.** The limiter governs the *handler*; the dispatcher accumulates requests upstream of it, so batching still forms. Concurrency 1 does not by itself prevent batching. What it does mean is that **the handler must return promptly** or the queue backs up into the dispatcher's latency budget and trips the overload fallback (§6 below).

M3.5 step 4 must therefore report `threads` alongside its numbers. Firing 32 concurrent requests and reporting "batching works" or "batching does not" without stating the thread setting produces an uninterpretable result.

### 6. **The 503 in [`adaptive-batching.md`](adaptive-batching.md) §4 is `ServiceUnavailable("process is overloaded")`** — and it is nameable

```python
def fallback() -> t.NoReturn:
    raise ServiceUnavailable("process is overloaded")
```

Passed to `CorkDispatcher` as the fallback when the latency budget cannot be met. It is a `BentoMLException` subclass, so it flows through `api_endpoint_wrapper`'s `BentoMLException` branch with `status = exc.error_code.value` (503) — and because 503 ≥ 500, **the message is replaced** with the generic *"An unexpected error has occurred, please check the server log."*

Two consequences for M4:

- The adapter can catch `ServiceUnavailable` specifically and map it to a distinct saturation `reason`, keeping it separate from the router's cold-start 503 (`TOOL_UNAVAILABLE`). Without that, a saturated tool and a starting tool are indistinguishable at the router.
- Left alone, the *cause* is stripped from the response body. That collides with guardrail 6 — *"Errors are actionable: they name what failed, why, and the command that helps"* ([`09`](../../09_IMPLEMENTATION_PLAN.md:347)). Our own error envelope must reinstate the reason.

### 7. Error mapping and headers to reconcile in M4

- **`ValidationError` → 400** with `detail` from `exc.errors(...)`. Our predict wrapper validates **above the seam** ([`05 §2`](../../05_RUNTIME_AND_BATCHING.md)) and emits our envelope, so there are two validators in the path. Decide deliberately which one the caller sees; the plan's answer is ours, which means the adapter should keep BentoML's input spec permissive and let our wrapper reject.
- **Any status ≥ 500 loses its message.** Combined with `log_exception`, the information exists in the log but not the response. Where our contract promises a reason (`/ready`, `retry_singly` per-item failures), the adapter must supply it.
- **`X-BentoML-Request-ID`** is set on every response, from the OTel span id. [`09 M3`](../../09_IMPLEMENTATION_PLAN.md:112) gives us request-id middleware in the router. Two ids will exist per request; the runtime should log both so a router-side id can be correlated with a container-side log line. Cheap, and exactly the thing that is painful to add later.

### 8. `path_prefix` confirmed dangerous for us

`get_system_routes(self.service.path_prefix)` and `join_paths(self.service.path_prefix, method.route)` — and `PassiveMount(path, mount_app)` for mounted apps. Setting `path_prefix` moves the system routes, the API routes **and our mounted contract routes** together. As flagged in [`sdk-reference.md`](sdk-reference.md) §3: **the adapter must not set `path_prefix`.** Worth a comment in `bentoml_backend.py` saying why, since it looks harmless.

### 9. `/schema.json` already exists, and it is not ours

`app.add_route("/schema.json", self.schema_view, name="schema")` returns `self.service.schema()` — BentoML's own description of the service. Our contract serves **`/schema`** (no `.json`), compiled by us under **D13**. The paths differ by five characters and the payloads are unrelated. Contract tests should assert the *content* of `/schema`, not merely that a schema-shaped thing is served, or a path typo could pass silently.

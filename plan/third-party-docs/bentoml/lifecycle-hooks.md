# Configure lifecycle hooks — BentoML

> **Source:** https://docs.bentoml.com/en/latest/build-with-bentoml/lifecycle-hooks.html
> **BentoML version at capture:** 1.4.39 (latest on PyPI, published 2026-05-07) · **Captured:** 2026-08-13
> **Relevance to tool-swap:** the load/unload lifecycle in [`05_RUNTIME_AND_BATCHING.md`](../../05_RUNTIME_AND_BATCHING.md) §6, the `STARTING`/`LOADING`/`READY` states in [`01_ARCHITECTURE.md`](../../01_ARCHITECTURE.md) §4, the truthful-readiness requirement in [`05 §3.2`](../../05_RUNTIME_AND_BATCHING.md), the `SIGTERM` `unload()` hygiene hook kept by [ADR-0004](../../adr/0004-hard-stop-only-in-v1.md), and per-worker device assignment ([`05 §5`](../../05_RUNTIME_AND_BATCHING.md)).
> **Completeness:** complete. Navigation chrome stripped; prose and code verbatim.

---

Lifecycle hooks in BentoML offers a mechanism to run custom logic at various stages of a Service's lifecycle. By leveraging these hooks, you can perform setup actions at startup, clean up resources before shutdown, and more.

This document provides an overview of lifecycle hooks and how to use them in BentoML Services.

## Understand server lifecycle

BentoML's server lifecycle consists of several stages, each providing a unique opportunity to perform specific tasks:

1. **Deployment hooks**. These hooks run before any workers are spawned, making them suitable for one-time global setup tasks. They're crucial for operations that should occur once, regardless of the number of workers.
2. **Spawn workers**. BentoML then spawns worker processes according to the `workers` configuration specified in the `@bentoml.service` decorator.
3. **Service initialization and ASGI application startup**. During the startup of each worker, any integrated ASGI application begins its lifecycle. This is when the `__init__` method of your Service class is executed, allowing for instance-specific initialization.
4. **ASGI application teardown**. Finally, as the server shuts down, including the ASGI application, shutdown hooks are executed. This stage is ideal for performing cleanup tasks, ensuring a graceful shutdown.

## Configure hooks in a BentoML Service

This section provides code examples for configuring different BentoML hooks.

### Deployment hooks

Deployment hooks are similar to static methods as they do not receive the `self` argument. You can define multiple deployment hooks in a Service. Use the `@bentoml.on_deployment` decorator to specify a method as a deployment hook. For example:

```python
import bentoml

@bentoml.service(workers=4)
class HookService:
    # Deployment hook does not receive `self` argument. It acts similarly to a static method.
    @bentoml.on_deployment
    def prepare():
        print("Do some preparation work, running only once.")

    # Multiple deployment hooks can be defined
    @bentoml.on_deployment
    def additional_setup():
        print("Do more preparation work if needed, also running only once.")

    def __init__(self) -> None:
        # Startup logic and initialization code
        print("This runs on Service startup, once for each worker, so it runs 4 times.")

    @bentoml.api
    def predict(self, text) -> str:
        # Endpoint implementation logic
```

After the Service starts, you can see the following output on the server side in order:

```
$ bentoml serve

Do some preparation work, running only once. # First on_deployment hook
Do more preparation work if needed, also running only once. # Second on_deployment hook
2024-03-13T03:12:33+0000 [INFO] [cli] Starting production HTTP BentoServer from "service:HookService" listening on http://localhost:3000 (Press CTRL+C to quit)
This runs on Service startup, once for each worker, so it runs 4 times.
This runs on Service startup, once for each worker, so it runs 4 times.
This runs on Service startup, once for each worker, so it runs 4 times.
This runs on Service startup, once for each worker, so it runs 4 times.
```

### Startup hooks

Startup hooks are executed during Service initialization, after deployment hooks but **before any API endpoints become available**. These hooks run once per worker, making them ideal for worker-specific initialization tasks such as establishing database connections or loading resources.

Use the `@bentoml.on_startup` decorator to specify a method as a startup hook. For example:

```python
import bentoml

@bentoml.service(workers=4)
class HookService:
    @bentoml.on_deployment
    def prepare():
        print("Global preparation, runs once before workers start.")

    @bentoml.on_startup
    def init_resources(self):
        # This runs once per worker
        print("Initializing resources for worker.")
        self.db_connection = setup_database()

    @bentoml.on_startup
    async def init_async_resources(self):
        # For async initialization tasks
        print("Async resource initialization for worker.")
        self.cache = await setup_cache()

    @bentoml.api
    def predict(self, text) -> str:
        # Use initialized resources in API endpoints
        return self.db_connection.query(text)
```

When you start this Service, you'll see the following output:

```
$ bentoml serve service:HookService

Global preparation, runs once before workers start. # on_deployment hook
2024-03-13T03:12:33+0000 [INFO] [cli] Starting production HTTP BentoServer from "service:HookService" listening on http://localhost:3000
Initializing resources for worker. # First worker's startup hooks
Async resource initialization for worker.
...
```

### Shutdown hooks

Shutdown hooks are executed as a BentoML Service is in the process of shutting down. It allows for the execution of cleanup logic such as closing connections, releasing resources, or any other necessary teardown tasks. You can define multiple shutdown hooks in a Service.

Use the `@bentoml.on_shutdown` decorator to specify a method as a shutdown hook. For example:

```python
import bentoml

@bentoml.service(workers=4)
class HookService:
    @bentoml.on_deployment
    def prepare():
        print("Do some preparation work, running only once.")

    def __init__(self) -> None:
        # Startup logic and initialization code
        print("This runs on Service startup, once for each worker, so it runs 4 times.")

    @bentoml.api
    def predict(self, text) -> str:
        # Endpoint implementation logic

    @bentoml.on_shutdown
    def shutdown(self):
        # Logic on shutdown
        print("Cleanup actions on Service shutdown.")

    @bentoml.on_shutdown
    async def async_shutdown(self):
        print("Async cleanup actions on Service shutdown.")
```

### Health check hooks

Health check hooks allow you to specify custom logic for determining when your Service is healthy and ready to handle requests. This is particularly useful when your Service depends on external resources that need to be checked before the Service can be considered operational.

You can define the following methods in your service class to implement health checks:

* `__is_alive__`: This method is called to check if the Service is alive. It should return a boolean value indicating the Service's health status. This responds to the `/livez` endpoint.
* `__is_ready__`: This method is called to check if the Service is ready to handle requests. It should return a boolean value indicating the Service's readiness status. This responds to the `/readyz` endpoint.

Both can be asynchronous functions.

For example:

```python
import bentoml

@bentoml.service(workers=4)
class HookService:
    def __init__(self) -> None:
        self.db_connection = None
        self.cache = None

    @bentoml.on_startup
    def init_resources(self):
        self.db_connection = setup_database()
        self.cache = setup_cache()

    def __is_ready__(self) -> bool:
        # Check if required resources are available
        if self.db_connection is None or self.cache is None:
            return False
        return self.db_connection.is_connected() and self.cache.is_available()
```

When you call the `/readyz` endpoint, it returns:

* HTTP 200 if the Service is ready (the hook returns `True`)
* HTTP 503 if the Service is not ready (the hook returns `False`)

---

## tool-swap notes

Everything above is BentoML's. Everything below is ours.

### 0. **Correction to [`health-endpoints-and-lifecycle-source.md`](health-endpoints-and-lifecycle-source.md) §3**

That file, written before this page was captured, called `__is_ready__` and `__is_alive__` *"undocumented … implementation details of `main`, discovered by reading source."* **That is wrong and is corrected here.** Both are documented, under "Health check hooks", with the `/livez` and `/readyz` mapping and the 200/503 contract stated explicitly. The caution about relying on `main` does not apply to these two. (`__metrics__` remains undocumented on this page; it was read from source.)

The upgrade in confidence matters: wiring `__is_ready__` is now a **supported public feature**, not a bet on internals.

### 1. ⚠️ **The blocking-startup problem is confirmed in the vendor's own words.** This is the M4 trap.

> *"Startup hooks are executed during Service initialization, after deployment hooks but **before any API endpoints become available**."*

and, from the lifecycle list:

> *"**Service initialization and ASGI application startup.** During the startup of each worker … This is when the `__init__` method of your Service class is executed."*

This is the documentation-side confirmation of what [`health-endpoints-and-lifecycle-source.md`](health-endpoints-and-lifecycle-source.md) §4 found in code. **Anything done in `__init__` or in an `@bentoml.on_startup` hook happens before the service can answer anything.** So the natural, idiomatic, documented BentoML placement for model loading — the one every BentoML example uses, including the one in [`adaptive-batching.md`](adaptive-batching.md) — is **exactly the placement our contract forbids**.

[`05 §3`](../../05_RUNTIME_AND_BATCHING.md:147) requires `/health` to *"answer **before** weights load and … never block"*, and [`01_ARCHITECTURE.md`](../../01_ARCHITECTURE.md) §4 requires `LOADING` to be an observable state distinct from `STARTING`. Neither survives loading in `__init__` or in a startup hook.

**The design that satisfies both**, and which the plan already half-specifies in [`05 §6`](../../05_RUNTIME_AND_BATCHING.md:298):

| Stage | What the adapter does |
| --- | --- |
| `__init__` / `on_startup` | Parse `TSWAP_*` config, resolve the worker→device mapping, import the handler module, **start loading on a background thread**, and **return immediately**. Do not await the load. |
| Immediately after | Uvicorn finishes lifespan, binds, serves. `/health` answers 200; `/ready` answers 503 `reason: loading` — this is the observable `LOADING` state |
| Load completes | Adapter flips its own state to ready; `/ready` → 200, and `__is_ready__` → `True` |
| Load raises | Adapter records the exception; `/ready` stays 503 with the traceback in `detail`, **the process stays alive so the failure is inspectable**, and it exits non-zero only on request or after a deadline ([`09 M4`](../../09_IMPLEMENTATION_PLAN.md:163)) |

The `__is_ready__` hook then reads the same adapter state our mounted `/ready` reads — **one fact, two projections** — so a plain `docker run` user gets the truth on `/readyz` and the router gets it, with a reason, on `/ready`.

**R8's design is vindicated.** [`12_REFERENCE_CODE.md`](../../12_REFERENCE_CODE.md) §5 records the background warm-up thread and criticises the swallowed exception. The thread was not a stylistic quirk — **it was the only way to bind before loading**, given this lifecycle. Port the mechanism, fix the exception handling. [`05 §6`](../../05_RUNTIME_AND_BATCHING.md:299) says "bind-then-load is kept from R8"; it should also say *why it is mandatory*.

**M3.5 addition (small, high value).** Step 5 currently proves a mounted ASGI route can serve our `/ready`. Extend it: sleep 30 s in `__init__`, and confirm the port refuses connections for those 30 s. That converts this analysis into a measured fact before M4 depends on it.

### 2. **Four hook stages map onto our lifecycle; `on_deployment` is the one we should ignore**

| BentoML stage | tool-swap use |
| --- | --- |
| `@bentoml.on_deployment` | **None.** Runs once before workers spawn. Its purpose — global one-time setup — is the *router's* job in our architecture, and a per-container hook has nothing global to do. Using it would put logic outside every worker's state, which is exactly the shared-state coupling **D2** exists to prevent. |
| `@bentoml.on_startup` / `__init__` | Config parse, device mapping, handler import, **kick off** the background load. Per worker — correct granularity for [`05 §5`](../../05_RUNTIME_AND_BATCHING.md:255)'s worker→device mapping. |
| `@bentoml.on_shutdown` | **The `SIGTERM` hygiene hook of [ADR-0004](../../adr/0004-hard-stop-only-in-v1.md).** [`09 M4`](../../09_IMPLEMENTATION_PLAN.md:156) keeps `unload()` as an optional handler hook *"called on `SIGTERM`"*; this is the supported place to call it. Both sync and async forms are supported. |
| `__is_alive__` / `__is_ready__` | Mirror our `/health` and `/ready` state onto BentoML's endpoints. |

Worth noting for [ADR-0004](../../adr/0004-hard-stop-only-in-v1.md): a shutdown hook makes the `unload()` hygiene path *cheap and supported*, which slightly lowers the cost of keeping `unload()` in the handler protocol. It does **not** reopen soft unload — that requires releasing VRAM from a live process and answering requests afterwards, which no hook here provides.

### 3. Async hooks are supported — but the load must still not block

`@bentoml.on_startup async def ...` is supported, and the source awaits it. **An async hook that awaits a long load blocks startup just as a sync one does.** The distinction that matters is *background versus awaited*, not *sync versus async*. Anyone reading "async startup hook" as a solution to §1 would be wrong; noted so that mistake is not made in M4.

### 4. `workers=N` and per-worker device assignment — the granularity is right

*"These hooks run once per worker"* and *"once for each worker, so it runs 4 times."* This confirms per-worker initialisation is the correct place for [`05 §5`](../../05_RUNTIME_AND_BATCHING.md:255)'s rule: read `worker_index` once, map through `TSWAP_DEVICE_LIST`, **log the mapping**, and fail loudly if the list is shorter than the worker count. Each worker independently picks its own device at this point.

It also makes the VRAM multiplication concrete: four workers means four executions of the load, hence **four copies of the weights**, which [`05 §5`](../../05_RUNTIME_AND_BATCHING.md:256) flags and the scheduler does not know about (**D7**). Our default of `workers: 1` ([`02_CONFIGURATION.md`](../../02_CONFIGURATION.md:94)) is right; raising it is a VRAM decision, not a throughput knob.

### 5. `__is_ready__` returns a bare boolean — the *reason* is ours to keep

The hook's contract is `bool` → 200/503. **No reason travels with it.** Our contract promises `503 {"ready": false, "reason": "loading", "detail": ...}` ([`05 §3.2`](../../05_RUNTIME_AND_BATCHING.md:148)), and BentoML's own 503 body is a fixed string naming the hook.

So the two projections are **not** equivalent, and our mounted `/ready` remains the load-bearing one:

- **`/ready`** (ours, mounted) — the router's contract, with `reason` and `detail`. This is what [`09 M4`](../../09_IMPLEMENTATION_PLAN.md:163) tests.
- **`/readyz`** (BentoML's, via `__is_ready__`) — a courtesy for standalone `docker run`, `curl`, and any future orchestrator probe. Guardrail 11 territory.

Both must read one state variable. If they can disagree, they will.

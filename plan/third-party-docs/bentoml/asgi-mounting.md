# Mount ASGI applications — BentoML

> **Source:** https://docs.bentoml.com/en/latest/build-with-bentoml/asgi.html
> **BentoML version at capture:** 1.4.39 (latest on PyPI, published 2026-05-07) · **Captured:** 2026-08-13
> **Relevance to tool-swap:** **this is the mechanism the entire tool-swap HTTP contract is built on.** [`05_RUNTIME_AND_BATCHING.md`](../../05_RUNTIME_AND_BATCHING.md) §3 serves `/health`, `/ready`, `/schema` and `/info` as *"our own handlers mounted alongside its generated API"*. It is also M3.5 step 5, the contract-feasibility check ([`09_IMPLEMENTATION_PLAN.md`](../../09_IMPLEMENTATION_PLAN.md:133)).
> **Completeness:** **condensed.** The Quart section is summarised rather than reproduced (we mount one framework, not two) and the two long `EXAMPLE_INPUT` news-story strings are elided. The FastAPI section, the prefix-path section and the middleware section are verbatim.

---

ASGI (Asynchronous Server Gateway Interface) is a spiritual successor to WSGI (Web Server Gateway Interface), designed to provide a standard interface between async-capable Python web servers, frameworks, and applications. ASGI supports asynchronous request handling, allowing multiple requests to be processed at the same time, making it suitable for real-time web applications, such as WebSockets, long polling, and more.

BentoML's server runs the Service API in an ASGI web serving layer, exposing REST endpoints for inference APIs (for example, `POST /summarize`) and common infrastructure APIs (for example, `GET /metrics`) for monitoring. This ASGI-native web serving layer allows for direct mounting of existing ASGI applications, enabling them to serve side-by-side with BentoML Services.

## Why should you mount an ASGI application

Mounting an ASGI application, such as one built with FastAPI, onto a BentoML Service can be advantageous for several reasons:

* **Extended functionality**: It enables you to extend your machine learning services with additional web functionalities, such as custom APIs for data processing, user management, or serving static files and web user interfaces, which are not directly related to model serving.
* **Custom authentication and authorization**: By integrating an ASGI application, you can implement advanced authentication and authorization mechanisms, tailoring security measures to the specific needs of your application.
* **API documentation**: With tools like FastAPI, you automatically get interactive API documentation, making it easier for end-users to understand and interact with the APIs.

## Integrate BentoML with ASGI frameworks

BentoML offers seamless integration with different ASGI frameworks, allowing you to serve ML models alongside custom web application logic, such as asynchronous operations, real-time data processing, and complex web application functionalities.

When integrating the ASGI frameworks, you use `bentoml.get_current_service()` to retrieve the current BentoML Service instance. It is useful when you need to access the BentoML Service instance from within ASGI application routes or when injecting the Service instance into ASGI application routes using dependency injection patterns.

### FastAPI

FastAPI is a web framework for building APIs that is built on top of ASGI, allowing it to handle asynchronous requests. To integrate a FastAPI application with a BentoML Service, you can define a FastAPI route either inside or outside the Service as below.

> **Note**
>
> Make sure you have installed FastAPI by running `pip install fastapi`.

```python
from fastapi import FastAPI, Depends
import bentoml

app = FastAPI()

@bentoml.service
@bentoml.asgi_app(app, path="/v1")
class MyService:
    name = "MyService"

    @app.get('/hello')
    def hello(self):  # Inside service class, use `self` to access the service
        return f"Hello {self.name}"

@app.get("/hello1")
async def hello(service: MyService = Depends(bentoml.get_current_service)):
    # Outside service class, use `Depends` to get the service
    return f"Hello {service.name}"
```

Specifically, do the following to mount FastAPI:

1. Create a FastAPI application with `FastAPI()`.
2. Use the `@bentoml.asgi_app` decorator to mount the FastAPI application to the BentoML Service, enabling them to be served together. Set the `path` parameter to customize the prefix path.
3. Define a FastAPI route inside or outside the Service class using `@app.get("/<route-name>")`.

   * Inside the class: Use `self` to access the Service instance's attributes and methods.
   * Outside the class: Use FastAPI's dependency injection system (`Depends`) to inject the BentoML Service instance into the route function. In the code above, the `hello1` route uses `Depends(bentoml.get_current_service)` to inject the `MyService` instance, allowing the route to access the Service's attributes and methods.
4. Within the FastAPI route, add your desired implementation logic.

> **Note**
>
> In addition to `get`, you can use the other operations like `post`, `put`, and `delete`.

**Design choice: Inside vs. Outside**

Accessing the BentoML Service instance both inside and outside the Service class offers flexibility in how you structure and interact with your Service logic and dependencies. The differences in accessing the BentoML Service instance in these contexts primarily relate to scope and the intended use cases.

*Inside the Service class*

* **Direct access**: Within the class defining a BentoML Service, you have direct access to `self`, which represents the instance of the Service. This allows you to directly access its attributes and methods without injecting any dependency. It's the most straightforward way to use the Service's functionality from within its own definition.
* **Contextual use**: Accessing the Service instance inside the class is typical for defining the Service's internal logic, such as setting up endpoints, performing operations with the model, and handling requests directly related to the Service's primary functionality.

*Outside the Service class*

* **Dependency injection**: Accessing the BentoML Service instance outside the class typically requires dependency injection mechanisms, such as the `Depends` function in FastAPI. This approach is necessary when you want to use the Service instance in other parts of your project.
* **Modular and decoupled design**: This approach allows different components of your BentoML project to interact with the Service without being tightly integrated into its class definition. For example, your ML logic can be encapsulated within the BentoML Service, while other aspects, such as custom authentication, supplementary data processing, or additional REST endpoints, can be managed externally yet still interact with the Service as needed.

A fuller example mounts FastAPI onto the `Summarization` Service and defines `/hello-inside` and `/hello-outside`, accessing the Service from inside and outside the class respectively:

```python
from __future__ import annotations
import bentoml
from transformers import pipeline
from fastapi import FastAPI, Depends

EXAMPLE_INPUT = "..."   # (long news-story string elided)

# Create a FastAPI app instance
app = FastAPI()

@bentoml.service(
    resources={"cpu": "2"},
    traffic={"timeout": 10},
)
@bentoml.asgi_app(app, path="/v1")
class Summarization:
    def __init__(self) -> None:
        self.pipeline = pipeline('summarization')

    # Define a name attribute
    name = "MyService"

    # The original Service API endpoint for text summarization
    @bentoml.api
    def summarize(self, text: str = EXAMPLE_INPUT) -> str:
        result = self.pipeline(text)
        return result[0]['summary_text']

    # Access the Service instance inside the class
    @app.get("/hello-inside")
    def hello(self):
        return f"Hello {self.name}. You can access the Service instance inside the class."

# Access the Service instance outside the class
@app.get("/hello-outside")
async def hello(service: MyService = Depends(bentoml.get_current_service)):
    return f"Hello {service.name}. You can access the Service instance outside the class."
```

### Quart *(summarised)*

Quart is supported by the same `@bentoml.asgi_app(app, path=...)` mechanism. Routes are defined **outside** the Service class and reach the instance via `bentoml.get_current_service()`. With `path="/v1"`, `curl http://localhost:3000/v1/hello` returns `Hello, MyService`. Upstream notes that *"Unlike FastAPI, Quart does not natively support the OpenAPI specification, so the endpoint is not displayed on the Swagger UI."*

## Customize the prefix path

When mounting an ASGI tool onto a BentoML Service, it is possible to customize the route path by setting a prefix. This is useful for organizing your API endpoints and simplifying routing and namespace management.

To set a prefix path, simply set the `path` parameter in the decorator `@bentoml.asgi_app`. Here is a FastAPI example:

```python
from fastapi import FastAPI, Depends
import bentoml

app = FastAPI()

@bentoml.service
@bentoml.asgi_app(app, path="/fastapi") # Add the prefix here
class MyService:
    name = "MyService"

    @app.get('/hello')  # This endpoint should be requested via "/fastapi/hello"
    def hello(self):
        return f"Hello {self.name}"
```

By specifying `path="/fastapi"`, the entire FastAPI application is served under this prefix. This means all the routes defined within the FastAPI application will be accessible under `/fastapi`.

## Add custom ASGI middleware

`add_asgi_middleware` is an API provided by BentoML to apply custom ASGI middleware. Middleware functions as a layer that processes requests and responses, allowing you to manipulate them or execute additional actions based on specific conditions. It is commonly used for implementing security measures and custom headers, managing CORS, compressing responses, and more.

Example usage:

```python
from __future__ import annotations
import bentoml
from transformers import pipeline

from starlette.middleware.trustedhost import TrustedHostMiddleware

@bentoml.service(
    resources={"cpu": "2"},
    traffic={"timeout": 10},
)
class Summarization:
    def __init__(self) -> None:
        self.pipeline = pipeline('summarization')

    @bentoml.api
    def summarize(self, text: str) -> str:
        result = self.pipeline(text)
        return result[0]['summary_text']

# Add TrustedHostMiddleware to ensure the Service only accepts requests from certain hosts
Summarization.add_asgi_middleware(TrustedHostMiddleware, allowed_hosts=['example.com', '*.example.com'])
```

While `add_asgi_middleware` is used to add middleware to the ASGI application that BentoML uses to serve the APIs, `@bentoml.asgi_app` is used to integrate the entire ASGI application into the BentoML Service. This is suitable for adding complete web applications like FastAPI or Quart applications that come with their routing logic, directly alongside your BentoML Service.

The middleware added via `add_asgi_middleware` applies to the entire ASGI application, including both the BentoML Service and any mounted ASGI applications. This ensures consistent processing of all requests across the application, whether they target BentoML Services or other components.

---

## tool-swap notes

Everything above is BentoML's. Everything below is ours.

### 1. **The contract in [`05 §3`](../../05_RUNTIME_AND_BATCHING.md:156) is buildable, and mounting is a supported first-class feature.** ✅

*"This ASGI-native web serving layer allows for direct mounting of existing ASGI applications, enabling them to serve side-by-side with BentoML Services."* A FastAPI app carrying `/health`, `/ready`, `/schema` and `/info`, mounted with `@bentoml.asgi_app(app, path="/")`, is exactly the shape [`05 §3`](../../05_RUNTIME_AND_BATCHING.md:156) describes. **M3.5 step 5's feasibility question is answered on paper.**

There is a pleasing consequence for **D12** and for [`14_ALTERNATIVES_EVALUATION.md`](../../14_ALTERNATIVES_EVALUATION.md) §"reuse the engine, own the contract": the router is FastAPI, and the runtime's contract routes are FastAPI too. **One web framework across both sides of boundary 2** ([`01_ARCHITECTURE.md`](../../01_ARCHITECTURE.md) §2), with BentoML supplying only the batching engine and the worker model underneath. That is a smaller conceptual surface than the plan currently claims for itself.

### 2. ⚠️ **`path` defaults to `/` — and mounting at the root needs checking against BentoML's own routes**

The `asgi_app` signature ([`sdk-reference.md`](sdk-reference.md)) is `path: str = '/'`, and every example on this page sets a prefix (`/v1`, `/fastapi`). We want our contract at the **root**: the router calls `GET /ready`, not `GET /v1/ready` ([`04_API_CONTRACT.md`](../../04_API_CONTRACT.md)).

From [`health-endpoints-and-lifecycle-source.md`](health-endpoints-and-lifecycle-source.md) §1, mounts are appended as `PassiveMount` **after** the system routes are built, and Starlette matches routes in order — so `/livez`, `/healthz`, `/readyz`, `/metrics`, `/schema.json` and the API routes are registered *first*. Our paths (`/health`, `/ready`, `/schema`, `/info`) do not collide with any of them, and the near-miss `/schema` vs `/schema.json` is a distinct path.

**But this is inference from reading source, not a documented guarantee.** Mounting at `/` is not shown anywhere on this page. **Make it an explicit M3.5 step-5 check:** mount at `/`, then confirm all four of our routes answer *and* that `/livez`, `/readyz` and `/metrics` still answer. If root-mounting shadows or is shadowed, the fallback is to register our routes individually rather than mounting a whole app — uglier, but it keeps the contract paths, which are not negotiable.

### 3. **`add_asgi_middleware` is the right home for structured logging and request-id correlation**

*"The middleware added via `add_asgi_middleware` applies to the **entire** ASGI application, including both the BentoML Service and any mounted ASGI applications."*

That whole-application scope is what several plan requirements need in one place:

- **request-id correlation** — [`health-endpoints-and-lifecycle-source.md`](health-endpoints-and-lifecycle-source.md) §7 notes BentoML sets its own `X-BentoML-Request-ID` while the router sets ours ([`09 M3`](../../09_IMPLEMENTATION_PLAN.md:112)); middleware is where the two get logged together;
- **the structured log line per request** required by [`05 §8`](../../05_RUNTIME_AND_BATCHING.md:339);
- **our custom metrics** (`tswap_tool_loaded`, and the batching metrics in [`05 §9`](../../05_RUNTIME_AND_BATCHING.md:353)).

Middleware applying to *both* the generated API and our mounted routes is the desirable behaviour here — one log format across the whole container, which is precisely what [`05 §8`](../../05_RUNTIME_AND_BATCHING.md:340) asks for when it says to *"bring BentoML's own logger into our format"*.

### 4. `get_current_service()` — how a mounted route reaches adapter state, without a global

Our `/ready` must read the load state, and `/info` must read the handler name, device, pid and loaded-at ([`05 §3`](../../05_RUNTIME_AND_BATCHING.md:154)). Both live on the service instance the adapter constructs.

Two supported routes to it, and the choice has a testing consequence:

- **inside the class** — `self` is available directly. Simplest, but it puts our contract handlers *inside* the generated service class, which is R8's `service_factory` shape and the style [`12_REFERENCE_CODE.md`](../../12_REFERENCE_CODE.md) §5 says to reject.
- **outside the class** — `Depends(bentoml.get_current_service)`. Keeps the contract app a **plain FastAPI app with no BentoML types in its handlers**, with the framework touched only at the dependency. That is more faithful to [`05 §2.4`](../../05_RUNTIME_AND_BATCHING.md:129) and, more usefully, it means **the contract app can be constructed and tested with `TestClient` and a fake state object, with no server and no BentoML at all** — a large gain for [`10_TESTING_STRATEGY.md`](../../10_TESTING_STRATEGY.md), which currently expects these routes to be exercised only through the full contract suite.

**Recommendation for M4:** build the contract app outside the class, injecting a small `RuntimeState` object; use `get_current_service` only as the adapter-side wiring. Note that `bentoml.get_current_service` is one more symbol confined to `backends/bentoml_backend.py` under the import-linter rule ([`08_REPO_LAYOUT.md`](../../08_REPO_LAYOUT.md) §5).

### 5. The `/health`-during-inference test is still unanswered — and is still the one that matters

Nothing on this page speaks to whether a mounted route responds while a synchronous handler occupies the thread limiter. Given `threads=1` by default ([`health-endpoints-and-lifecycle-source.md`](health-endpoints-and-lifecycle-source.md) §5), the handler runs in a worker thread via `anyio.to_thread.run_sync` while the event loop stays free — so an **async** mounted route should answer during a 5-second inference, and a **sync** mounted route (`def`, not `async def`) would contend for the same thread pool.

That is a strong argument for a concrete M4 rule: **the contract routes must be `async def` and must never call blocking code.** [`05 §5`](../../05_RUNTIME_AND_BATCHING.md:254) already requires that they *"never touch the handler lock"*; this adds the reason and the mechanism.

It remains **the** contract-suite assertion ([`09 M4`](../../09_IMPLEMENTATION_PLAN.md:163)): `/health` answered during a 5.0 s inference. Analysis says it will pass; the test is what makes it true after the next upgrade.

### 6. Not for us: authentication, the Swagger UI, static files

The page's motivating use cases are auth, docs and static files. We want none of them in a tool container: authentication is the router's boundary ([`04_API_CONTRACT.md`](../../04_API_CONTRACT.md)), tools are addressed by container name on an internal network with no published ports (**D21**, [`09 M3`](../../09_IMPLEMENTATION_PLAN.md:110)), and our discovery surface is `/schema` plus `?format=tools` (**D13**), not Swagger. We use this feature for one narrow purpose — **serving a fixed contract** — which is worth stating so nobody later adds a UI to a tool image because the framework makes it easy.

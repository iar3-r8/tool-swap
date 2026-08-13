# BentoML SDK reference — `@service`, `@api`, `asgi_app`, `depends`

> **Source:** https://docs.bentoml.com/en/latest/reference/bentoml/sdk.html
> **BentoML version at capture:** 1.4.39 (latest on PyPI, published 2026-05-07) · **Captured:** 2026-08-13
> **Relevance to tool-swap:** the authoritative signature list for everything `backends/bentoml_backend.py` will call in **M4**. It supplies the **defaults** behind [`02_CONFIGURATION.md`](../../02_CONFIGURATION.md) §7, and it is the only source found so far that mentions BentoML's **health check endpoints**, on which [`05_RUNTIME_AND_BATCHING.md`](../../05_RUNTIME_AND_BATCHING.md) §3 depends.
> **Completeness:** **condensed.** The `bentoml.validators` classes (`PILImageEncoder`, `FileSchema`, `TensorSchema`, `DataframeSchema`, `ContentType`, `Shape`, `DType`) are listed by name only — their members are attribute stubs with no prose upstream, and they belong to the I/O layer covered by `iotypes`. Signatures are reproduced with the Sphinx cross-reference links stripped for legibility; parameter names, types and defaults are verbatim.

---

## Service decorator

```python
bentoml.service(inner: type[T], /) -> Service[T]

bentoml.service(
    *,
    name: str | None = None,
    image: Image | None = None,
    description: str | None = None,
    path_prefix: str | None = None,
    envs: list[ServiceEnvConfig] | None = None,
    labels: dict[str, str] | None = None,
    cmd: list[str] | None = None,
    service_class: type[Service[T]] = Service,
    **kwargs: Unpack,
) -> _ServiceDecorator
```

Mark a class as a BentoML service.

**Parameters:**

* **name** – The name of the service. Defaults to the class name.
* **image** – The image to use for the service.
* **description** – A description of the service.
* **path_prefix** – A URL path prefix to apply to all API endpoints of this service. For example, setting `path_prefix="/v1"` will make an endpoint `/predict` available at `/v1/predict`. This also applies to mounted ASGI applications and health check endpoints.
* **envs** – Environment variables to set for the service.
* **labels** – Labels to attach to the service.
* **cmd** – A custom command to start the service.
* **\*\*kwargs** – Additional service configurations such as `traffic`, `resources`, `workers`, etc.

Example:

```python
@service(traffic={"timeout": 60})
class InferenceService:
    @api
    def predict(self, input: str) -> str:
        return input
```

```python
bentoml.runner_service(runner: Runner, **kwargs: Unpack) -> Service[Any]
```

Make a service from a legacy Runner.

```python
bentoml.asgi_app(app: ASGIApp, *, path: str = '/', name: str | None = None) -> t.Callable[[R], R]
```

Mount an ASGI app to the service.

**Parameters:**

* **app** – The ASGI app to be mounted.
* **path** – The path to mount the app.
* **name** – The name of the app.

## Service API

```python
bentoml.api(func: t.Callable[t.Concatenate[t.Any, P], R]) -> APIMethod[P, R]

bentoml.api(
    *,
    route: str | None = None,
    name: str | None = None,
    input_spec: type[IODescriptor] | None = None,
    output_spec: type[IODescriptor] | None = None,
    batchable: bool = False,
    batch_dim: int | tuple[int, int] = 0,
    max_batch_size: int = 100,
    max_latency_ms: int = 60000,
) -> t.Callable[[t.Callable[t.Concatenate[t.Any, P], R]], APIMethod[P, R]]
```

Make a BentoML API method. This decorator can be used either with or without arguments.

**Parameters:**

* **func** – The function to be wrapped.
* **route** – The route of the API. e.g. "/predict"
* **name** – The name of the API.
* **input_spec** – The input spec of the API, should be a subclass of `pydantic.BaseModel`.
* **output_spec** – The output spec of the API, should be a subclass of `pydantic.BaseModel`.
* **batchable** – Whether the API is batchable.
* **batch_dim** – The batch dimension of the API.
* **max_batch_size** – The maximum batch size of the API.
* **max_latency_ms** – The maximum latency of the API.

Note that when you enable batching, `batch_dim` can be a tuple or a single value.

* For a tuple (`input_dim`, `output_dim`):

  + `input_dim`: Determines along which dimension the input arrays should be batched (or stacked) together before sending them for processing. For example, if you are working with 2-D arrays and `input_dim` is set to 0, BentoML will stack the arrays along the first dimension. This means if you have two 2-D input arrays with dimensions 5x2 and 10x2, specifying an `input_dim` of 0 would combine these into a single 15x2 array for processing.
  + `output_dim`: After the inference is done, the output array needs to be split back into the original batch sizes. The `output_dim` indicates along which dimension the output array should be split. In the example above, if the inference process returns a 15x2 array and `output_dim` is set to 0, BentoML will split this array back into the original sizes of 5x2 and 10x2, based on the recorded boundaries of the input batch. **This ensures that each requester receives the correct portion of the output corresponding to their input.**
* If you specify a single value for `batch_dim`, this value will apply to both `input_dim` and `output_dim`. In other words, the same dimension is used for both batching inputs and splitting outputs.

*(An image illustrating `batch_dim` for 2-D arrays follows upstream: the `batch_dim=(0,0)` path stacks two 5x2 arrays into a 10x2 array and splits the result back into two 5x2 arrays; the `batch_dim=(1,1)` path concatenates them side by side into a 5x4 array and splits the output back into two 5x2 arrays.)*

```python
bentoml.task(func: t.Callable[t.Concatenate[t.Any, P], R]) -> APIMethod[P, R]

bentoml.task(
    *,
    route: str | None = None,
    name: str | None = None,
    input_spec: type[IODescriptor] | None = None,
    output_spec: type[IODescriptor] | None = None,
    batchable: bool = False,
    batch_dim: int | tuple[int, int] = 0,
    max_batch_size: int = 100,
    max_latency_ms: int = 60000,
) -> t.Callable[[t.Callable[t.Concatenate[t.Any, P], R]], APIMethod[P, R]]
```

Mark a method as a BentoML async task. This decorator can be used either with or without arguments. *(Parameters as for `bentoml.api`.)*

## `bentoml.depends`

```python
bentoml.depends(*, url: str | None = None, deployment: str | None = None,
                cluster: str | None = None) -> Dependency[None]

bentoml.depends(on: Service[T], *, url: str | None = None, deployment: str | None = None,
                cluster: str | None = None) -> Dependency[T]
```

Create a dependency on other service or deployment.

**Parameters:**

* **on** – Service[T] | None: The service to depend on.
* **url** – str | None: The URL of the service to depend on.
* **deployment** – str | None: The deployment of the service to depend on.
* **cluster** – str | None: The cluster of the service to depend on.

Examples:

```python
@bentoml.service
class MyService:
    # depends on a service
    svc_a = bentoml.depends(SVC_A)
    # depends on a deployment
    svc_b = bentoml.depends(deployment="ci-iris")
    # depends on a remote service with url
    svc_c = bentoml.depends(url="http://192.168.1.1:3000")
    # For the latter two cases, the service can be given to provide more accurate types:
    svc_d = bentoml.depends(url="http://192.168.1.1:3000", on=SVC_D)
```

## `bentoml.validators` *(names only — see the completeness note above)*

`PILImageEncoder` · `FileSchema(format='binary', content_type=None)` · `TensorSchema(format, dtype=None, shape=None)` · `DataframeSchema(orient='records', columns=None)` · `ContentType(content_type)` · `Shape(dimensions)` · `DType(dtype)`

---

## tool-swap notes

Everything above is BentoML's. Everything below is ours.

### 1. **`asgi_app` exists and is a first-class decorator — the contract in `05 §3` is buildable.** ✅

[`05_RUNTIME_AND_BATCHING.md`](../../05_RUNTIME_AND_BATCHING.md:156) asserts *"BentoML serves an ASGI app and supports mounting additional ASGI routes, so `/health`, `/ready`, `/schema`, `/info` … are our own handlers mounted alongside its generated API."* Confirmed: `bentoml.asgi_app(app, *, path, name)` is a documented public decorator. **The whole tool-swap HTTP contract rests on this one function**, so it is worth knowing it is one line of vendor API and not a workaround.

M3.5 step 5 ([`09_IMPLEMENTATION_PLAN.md`](../../09_IMPLEMENTATION_PLAN.md:133)) still earns its place: the question is no longer *whether* mounting works but whether a mounted route **answers during a 5-second inference while the handler lock is held** — the contract test in [`09 M4`](../../09_IMPLEMENTATION_PLAN.md:163). That is a concurrency property, not an API-existence property, and nothing on this page speaks to it.

### 2. **Correction: `max_latency_ms = 60000` is BentoML's own default, not an R8 mistake.** ⚠️

[`02_CONFIGURATION.md`](../../02_CONFIGURATION.md:345) says:

> *"Maps to BentoML's `max_latency_ms` … **R8 defaulted to a nonsensical `60000` ms** (a full minute of added latency); use a small, sane default."*

The signature says `max_latency_ms: int = 60000`. **R8 did not choose that number — it is the framework default, and R8 simply passed it through.** The characterisation in the plan is therefore unfair to R8 and, more importantly, misdiagnoses the hazard: this is not one team's careless config value but a default every tool built on BentoML inherits unless we override it.

The practical conclusion is *strengthened*, not weakened. Our `max_wait_ms: 20` default is right, and the adapter must **always pass `max_latency_ms` explicitly** — never rely on the framework default — because inheriting 60 s would silently permit a minute of queueing. Worth an explicit assertion in the M4 contract suite that the effective value is ours.

Same for `max_batch_size: int = 100` against our default of `8`. Ours is the conservative one, and deliberately so, given the absent `max_batch_bytes` and CT-volume payloads ([`02 §7`](../../02_CONFIGURATION.md:344)). Also pass it always.

**Proposed amendment, not applied:** re-word [`02 §7`](../../02_CONFIGURATION.md:345) to attribute 60000 to BentoML and state the always-override rule. See [`INDEX.md`](INDEX.md) §2.

### 3. **`path_prefix` names "health check endpoints" — but does not name them.** ⚠️ **The gap stands.**

> *"setting `path_prefix="/v1"` will make an endpoint `/predict` available at `/v1/predict`. This also applies to mounted ASGI applications and **health check endpoints**."*

This is the only reference to health check endpoints found anywhere in the documentation navigation so far. It **confirms they exist** and confirms they are prefixable — but it does not name them, does not give their paths, and says nothing about semantics. So:

- [`05 §3`](../../05_RUNTIME_AND_BATCHING.md:146)'s mapping of our `/health` onto BentoML's `/livez` is **still uncited**.
- [`05 §3.2`](../../05_RUNTIME_AND_BATCHING.md:159)'s claim that `/readyz` reports *server-up rather than weights-loaded* — the correction of R8's central bug, and one of M4's stated goals — is **still uncited**. It is plausible and matches R8's observed behaviour, but the docs site does not say it.

**Two consequences.** First, this must be settled from the source repository or by observation in M3.5, and recorded — see [`INDEX.md`](INDEX.md) §3. Second, an operational trap: since `path_prefix` also shifts *mounted ASGI apps*, setting it would move **our** contract routes too. The router would then be looking for `/ready` at `/v1/ready`. **The adapter must never set `path_prefix`**, or must account for it everywhere; simplest is to forbid it and say why.

### 4. `input_spec` / `output_spec` are Pydantic — a possible shortcut for D13, and a possible trap

Both decorators accept `input_spec` / `output_spec` as *"a subclass of `pydantic.BaseModel`"*. Our schema compiler (**D13**, [`01_ARCHITECTURE.md`](../../01_ARCHITECTURE.md), M1) already produces **JSON Schema 2020-12** from the declarative `inputs:` list, and Pydantic v2 can emit JSON Schema — so it is tempting to build a Pydantic model and let BentoML derive everything.

**Resist it, or at least decide it explicitly.** [`05 §2.4`](../../05_RUNTIME_AND_BATCHING.md:129) rule 2 forbids any BentoML type in a signature above the seam, and our `/schema` must be *ours*, compiled by us, identical across backends, carrying `x-batchable` and `x-semantic`. Letting the framework own the schema would put **D13**'s output at the mercy of Pydantic's JSON Schema dialect and quietly couple the API contract to the backend. If we do generate a Pydantic model, it must be **derived from** our compiled schema inside the adapter, never the source of truth.

Note the D15 link: §"Handle multiple parameters" of [`adaptive-batching.md`](adaptive-batching.md) uses exactly this mechanism for per-item parameters, so a decision here also decides that.

### 5. `batch_dim` splits outputs by *recorded input boundaries* — relevant to attribution

> *"the output array needs to be split back into the original batch sizes … based on the recorded boundaries of the input batch. **This ensures that each requester receives the correct portion of the output corresponding to their input.**"*

This is the clearest vendor statement available that **response attribution is the dispatcher's responsibility and is boundary-tracked**. It partially reassures on the *"order of the requests in a batch is not guaranteed"* sentence in [`adaptive-batching.md`](adaptive-batching.md): ordering within the batch is not promised, correspondence is.

It also shows `batch_dim` matters more than [`02_CONFIGURATION.md`](../../02_CONFIGURATION.md) currently implies — for a handler taking a stacked `numpy.ndarray` rather than a list, `batch_dim` is what makes attribution correct at all. v1 handlers take lists (`batch_dim=0` is right), but **if any future handler batches along a tensor axis, `batch_dim` becomes safety-relevant, not cosmetic.** Record it in `NATIVE.md` as something a native backend would also have to get right.

### 6. `cmd`, `envs`, `labels`, `image` — framework features we deliberately do not use

`@bentoml.service` accepts `image` (BentoML's own container build), `envs`, `labels`, and `cmd`. tool-swap has **its own** answer for each: Dockerfile generation from `runtime:` levels 0–3 ([`03_TOOL_AUTHORING.md`](../../03_TOOL_AUTHORING.md), M5), the `TSWAP_*` env-var contract ([`05 §7`](../../05_RUNTIME_AND_BATCHING.md:310)), our Docker labels ([`01_ARCHITECTURE.md`](../../01_ARCHITECTURE.md) §12), and our own entrypoint — *"the entrypoint is **ours, not `bentoml serve`**"* ([`03 §6`](../../03_TOOL_AUTHORING.md:353)).

Worth stating plainly in the INDEX so a future reader does not "discover" `image=` and conclude the build pipeline was redundant: BentoML's packaging model (Bentos, `bentoml build`, `bentoml containerize`) is a **parallel, competing** answer to **D2**, and we use the framework as a *library inside our image* rather than adopting its packaging. That is a real decision, currently implicit in the plan.

### 7. `**kwargs: Unpack` — `traffic`, `resources`, `workers` are not specified here

The service decorator's configuration surface is `**kwargs`, documented only as *"Additional service configurations such as `traffic`, `resources`, `workers`, etc."* Three of the four things our adapter must set — `workers` for [`05 §5`](../../05_RUNTIME_AND_BATCHING.md:251), `resources` for GPU assignment, `traffic` for timeouts — are behind an untyped `**kwargs` with no signature. `threads=N`, named in [`adaptive-batching.md`](adaptive-batching.md), does not appear on this page at all.

**These are specified elsewhere** — `reference/bentoml/configurations`, `build-with-bentoml/services`, `parallelize-requests` — which is why those pages are in the capture list. Noted here so the absence reads as *documented elsewhere* rather than *undocumented*.

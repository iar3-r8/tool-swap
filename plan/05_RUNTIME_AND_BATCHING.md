# 05 — The Model Runtime and Micro-Batching

> Decision **D5**: micro-batching is in scope and valuable; take vLLM's continuous-batching behaviour as the model to imitate.
> Decision **D12**: reuse existing self-hostable software where we can.
> Decision **D14** (new, this document): **the in-container runtime is built on BentoML.** Batching is the cumbersome part, BentoML already does it well, and R8 has already run it in production. See §1.
> **[ADR-0005](adr/0005-one-uniform-batched-calling-convention.md)**: **every handler takes and returns a list, always.** `scalar_inputs` and the per-input `batchable:` flag are gone; `batching.enabled: false` now means only `max_batch_size: 1`. §4.3 and §4.4 are rewritten accordingly.
> **[ADR-0004](adr/0004-hard-stop-only-in-v1.md)**: there is **no `POST /unload` and no soft unload** in v1. §3.1 and §6 are corrected.
>
> **Verified against [`third-party-docs/bentoml/`](third-party-docs/bentoml/INDEX.md) (1.4.39, captured 2026-08-13).** Claims in this document that the capture corrected are marked ✅ where confirmed and ⚠️ where they were wrong.

> **This document is load-bearing.** Since every tool is one we build ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §0), there is no third-party server in the zoo with a better batcher to defer to. Batching quality for the entire zoo is decided here.
>
> This document specifies `tool_swap_runtime` — the small package that lives **inside** a managed model container and turns a `handler.py` into a batching HTTP server. **`tool_swap_runtime` is the contract; BentoML is the engine underneath it.** The distinction is the whole point of §2.

---

## 1. Build vs. reuse — **resolved: reuse BentoML**

**This was the highest-leverage open decision in the plan. It is now closed (**D14**, [`13_OPEN_QUESTIONS.md`](13_OPEN_QUESTIONS.md) Part A).**

| Option | Pros | Cons |
|---|---|---|
| **A. Write our own** (FastAPI + a port of R8's `CoreBatcher`) | Zero extra deps in the model image; we control the exact endpoint contract; trivially testable with an injected clock | **We own a batcher.** Correct micro-batching is the cumbersome, subtle part — async futures, cancellation, fan-out, ordering, back-pressure — and a bug in it can return one patient's result for another. Multi-worker/GPU-affinity is also on us |
| **B. Reuse BentoML** (what R8 did) — **CHOSEN** | Adaptive batching for free (`batchable=True`, `max_batch_size`, `max_latency_ms`) with an adaptive dispatcher that tunes the wait window from observed latency — better than the fixed policy we would have written; `/healthz` `/readyz` `/livez` and Prometheus metrics already there; multi-worker supported; **battle-tested, and already proven in this codebase** | A real dependency inside every model image, pinning pydantic/starlette/click; its service idioms must be kept out of the authoring path (our job, §2); we do not need bento building/yatai and must ignore them |
| **C. Reuse Ray Serve** | `@serve.batch` is excellent | Ray inside every image is far heavier than BentoML; overkill for one model per container. **Refused on cost, not on principle** — see [`15_RAY_SERVE_EVALUATION.md`](15_RAY_SERVE_EVALUATION.md) §3 (Role B) and [ADR-0003](adr/0003-ray-serve-not-adopted.md). A `ray` backend behind the §2 seam remains addable if a real tool ever needs it, which is this seam earning its keep a second time. One open question, recorded rather than assumed: whether `@serve.batch` adapts its wait window from observed latency the way BentoML's dispatcher does ([`15_RAY_SERVE_EVALUATION.md`](15_RAY_SERVE_EVALUATION.md) §9 item 5) |
| **D. LitServe** (Lightning) | Lightweight, batching + streaming, minimal API | Smaller community; no in-house experience; BentoML's dispatcher is more capable |

**Decision: B — BentoML, pinned, wrapped behind our own contract.**

Reasoning, stated plainly:

1. **Batching is the cumbersome part, and it is the part with a mature answer.** Everything else in the runtime (import a handler, load in the background, answer readiness truthfully, expose a schema) is easy code we would write either way. Writing our own batcher buys control over the one component where control is worth least and correctness risk is highest.
2. **The dependency-conflict fear is speculative; treat it as such.** BentoML's constrained dependencies are assumed **not** to be a problem until a specific model proves otherwise. We do not pay a permanent architectural cost — writing and maintaining an inference server — to pre-empt a conflict nobody has yet hit. §1.2 defines how we would find out, and §2 defines what we do if we ever do.
3. **The reuse principle (D12) applies here too.** It would be possible to argue that D12 stops at the image boundary, on the grounds that a heavyweight framework in every image partially undoes D2 — but that carve-out exists only to justify writing a batcher. With the batcher reused, the principle is honoured uniformly.

**What this does *not* change:** the author still writes a plain `handler.py` with `load()` / `predict()` / `unload()` and never imports BentoML, and the router still talks to a fixed logical contract. Those are protected by §2, and they are the reason this decision is reversible.

### 1.1 The dependency stance, written down

The stance is deliberate, so it can be checked rather than argued about later:

> **A locked dependency is acceptable until a concrete model demonstrates an unresolvable conflict.** "BentoML constrains pydantic" is not a conflict; "`tool X` requires pydantic <2 and therefore cannot install alongside BentoML" is. Only the second justifies action.

#### ⚠️ Which dependencies actually constrain us — corrected

Four plan documents said *"locked pins (pydantic, starlette, click)"*. **Checked against the packaging metadata for 1.4.39 ([`dependency-constraints.md`](third-party-docs/bentoml/dependency-constraints.md)), that list is wrong in the way that matters:**

| Dependency | Actual constraint | Can it conflict? |
|---|---|---|
| `pydantic` | `<3` | Upper bound only — plausible, but wide |
| `starlette` | `>=0.24.0` | **No.** A lower bound cannot conflict with a newer requirement |
| `click` | `>=7.0` | **No.** Same |
| **`cattrs`** | **`>=22.1.0,<23.2.0`** | **Yes — a genuine two-sided pin, and nobody had noticed it** |
| **OpenTelemetry** (seven packages) | pinned to a **beta** series | **Yes**, and beta series move without ceremony |
| **`fsspec`** | `>=2025.7.0` | A recent floor; a conflict with an older-pinned stack is realistic |

**The three packages the plan named are the three least informative ones**, two of which cannot conflict at all. The spike must measure `cattrs`, the OpenTelemetry family and `fsspec` (§1.2, [`09_IMPLEMENTATION_PLAN.md`](09_IMPLEMENTATION_PLAN.md) M3.5 step 1).

**Also confirmed:** BentoML's **extras are not installed** by default, so the tree is smaller than a reading of its `pyproject.toml` suggests. Check yank status before pinning and before upgrading; pin `bentoml==X.Y.Z` with **no extras**.

Consequences:

- The `tool_swap_runtime` dependency budget is now **BentoML plus its transitive set, and nothing further of our own choosing.** A fifth *direct* dependency added by us still needs written justification; BentoML's own tree is accepted wholesale.
- The base images ([`03_TOOL_AUTHORING.md`](03_TOOL_AUTHORING.md) §6) ship BentoML pre-installed, which makes tool builds *faster*, not slower — a genuine benefit that a "no framework in the image" position would have given up.
- **BentoML's version is pinned** in the runtime distribution (`bentoml==X.Y.Z`), and upgrading it is a deliberate, tested change, not a float. An unpinned framework in every image is the version of this decision that would actually hurt.

### 1.2 How we would find out we were wrong

Evidence, not vibes. Three cheap mechanisms:

| Mechanism | What it catches | Where |
|---|---|---|
| **Pre-M4 dependency spike** — resolve BentoML + `torch/monai/transformers`, and BentoML + `tensorflow/tf-keras`, in one image each | The realistic worst cases, *before* the runtime is built on it | [`09_IMPLEMENTATION_PLAN.md`](09_IMPLEMENTATION_PLAN.md) M3.5 |
| **Per-template resolution gate in CI** — `pip install --dry-run` (or `uv pip compile`) every template and every example model | A BentoML upgrade silently breaking a model stack | [`10_TESTING_STRATEGY.md`](10_TESTING_STRATEGY.md) |
| **`tswap doctor`** reports resolved versions of the pinned set inside each built image | Drift between what we tested and what a user's image actually has | [`07_CLI_AND_OPS.md`](07_CLI_AND_OPS.md) |

**The trigger that reopens this decision:** a model that cannot install BentoML, or a BentoML release that breaks the dispatcher contract we depend on. If that happens, §2 is the exit, and it is a *per-model* exit before it is ever a project-wide one.

---

## 2. The escape hatch: `RuntimeBackend` is a seam, not a second implementation

**We are choosing BentoML without being locked into it.** The mechanism is a single internal boundary, specified now and implemented once.

> **Scope statement:** v1 ships **exactly one** backend, `bentoml`. The `native` backend is **architecture only** — a documented interface and a written plan, with **no code in v1**. The point is that writing it later is a bounded, well-understood job, not a rewrite. Do not build it speculatively; building two backends to hedge a risk nobody has hit would cost more than the risk.
>
> ⚠️ **The seam's stated first use case has been withdrawn.** §4.3 used to name "a tool needing per-request non-batchable inputs" as the reason `native` would earn its keep beyond dependency risk; [ADR-0005](adr/0005-one-uniform-batched-calling-convention.md) removed that need entirely. **The seam still stands on its original justification** — a tool whose stack cannot resolve alongside BentoML (§1.2) — which is the risk M3.5 actually measures. One fewer reason is not no reason, but it should be stated rather than quietly dropped.

```mermaid
graph TB
    HD["handler.py — plain Python, framework-free"]
    DECL["tool.yaml — inputs, outputs, batching, params"]
    subgraph rt["tool_swap_runtime — the stable contract"]
        LOAD["handler loader + lifecycle: load / warmup / unload"]
        SCH["schema compiler -> JSON Schema"]
        WRAP["predict wrapper: validation, length check, retry_singly, errors"]
        BE{"RuntimeBackend"}
    end
    B1["BentoMLBackend — v1, the only one built"]
    B2["NativeBackend — architecture only, not built"]
    HD --> LOAD
    DECL --> SCH
    LOAD --> BE
    SCH --> BE
    WRAP --> BE
    BE --> B1
    BE -.documented, unbuilt.-> B2
    B1 --> HTTP["HTTP :8000 — the router-facing contract, §3"]
    B2 -.-> HTTP
```

### 2.1 What lives above the seam (ours, backend-independent)

Everything that defines the *product* must sit above the seam, or the seam is worthless:

- The handler protocol (`load` / `predict` / `unload` / optional `warmup`) and the `@tool` decorator.
- Handler import from `TSWAP_HANDLER`, and device binding.
- Schema compilation from the declaration to JSON Schema (**D13**).
- The predict wrapper: input validation, **the batch-length safety check** (§4.4), `retry_singly` isolation, and the structured error envelope.
- Truthful readiness — "weights loaded", not "server started" (§3.2).
- The env-var contract (§7) and the effective-configuration log line.

### 2.2 What lives below the seam (backend-specific)

Only three things, which is what makes the seam credible:

1. **Serving the HTTP contract of §3** on port 8000.
2. **Grouping concurrent calls into batches** and handing our wrapper a list of N inputs, then fanning N results back to the right callers.
3. **Worker processes** and their device assignment.

### 2.3 The interface to write down (and honour)

```python
class RuntimeBackend(Protocol):
    """Serves the tool_swap runtime HTTP contract for one loaded handler."""

    def serve(
        self,
        lifecycle: HandlerLifecycle,   # load/ready/unload, ours
        batch_fn: BatchFn,             # (list[Inputs]) -> list[Outputs], ours
        schema: ToolSchema,            # compiled JSON Schema, ours
        settings: RuntimeSettings,     # parsed env contract, ours
    ) -> None:
        """Bind the port and serve until SIGTERM. Blocks."""
```

`batch_fn` is the load-bearing detail: **our wrapper receives an already-formed batch and returns results positionally.** The backend decides *when* to form a batch; it never touches validation, error shaping, or the length check. A `NativeBackend` would therefore need to supply only a queue, a flush policy and a server loop — which is precisely the ported [`CoreBatcher`](12_REFERENCE_CODE.md) §7, retained in the plan for exactly this purpose.

### 2.4 Rules that keep the seam real

Seams rot when nothing tests them. Four rules:

1. **No BentoML import outside `tool_swap_runtime/backends/bentoml_backend.py`.** Enforce with the import-linter rule already in CI ([`08_REPO_LAYOUT.md`](08_REPO_LAYOUT.md) §5).
2. **No BentoML type in any signature above the seam** — not in the handler protocol, not in the schema compiler, not in error types.
3. **A backend-agnostic contract test suite** ([`10_TESTING_STRATEGY.md`](10_TESTING_STRATEGY.md)) written against the HTTP contract of §3, parameterised over backends. In v1 it runs once, against `bentoml`. It is the acceptance test a future `native` backend must pass, written years in advance and kept honest by running continuously.
4. **`runtime.server: bentoml` exists in the config schema from day one**, validated, with `native` as a declared-but-unimplemented value that fails with *"not implemented in this version"* rather than *"unknown key"*. A config key added later is a migration; a config key reserved now is free.

**The deeper hedge is unchanged and matters more than the seam:** a model image is an OCI image serving HTTP ([`14_ALTERNATIVES_EVALUATION.md`](14_ALTERNATIVES_EVALUATION.md) §5). Whatever serves inside it, the model remains portable. **The models are the durable asset.**

---

## 3. Runtime HTTP contract

This is the contract the router relies on. Keep it minimal and stable — it is a versioned interface, and it is defined **independently of BentoML** so §2 stays possible.

### 3.1 Endpoints

| Endpoint | Returns | Provided by |
|---|---|---|
| `GET /health` | `200 {"status":"alive"}` | BentoML's `/livez`, re-exposed at our path. Process is up. Must answer **before** weights load and must never block. |
| `GET /ready` | `200 {"ready":true}` / `503 {"ready":false,"reason":"loading","detail":...}` | **Ours** (§3.2) — BentoML's `/readyz` is not sufficient. |
| `GET /schema` | JSON Schema (draft 2020-12) for inputs and outputs, plus batching config and static params | Ours, mounted ASGI route. |
| `POST /predict` | `{"outputs": ..., "meta": {...}}` | The batched BentoML API (§4). Accepts one item or a list; **the handler always sees a list** ([ADR-0005](adr/0005-one-uniform-batched-calling-convention.md)). |
| `GET /metrics` | Prometheus text | BentoML built-in, plus our custom metrics (§9). |
| `GET /info` | Runtime version, **backend name and version**, handler name, device, pid, loaded-at | Ours. |

**`POST /unload` is not in v1** ([ADR-0004](adr/0004-hard-stop-only-in-v1.md)). Reclamation is by stopping the container; nothing asks a live container to release its weights. **`POST /predict/batch` is also gone** — with one uniform convention there is no second submission shape to give it ([ADR-0005](adr/0005-one-uniform-batched-calling-convention.md)).

**Implementation note:** BentoML serves an ASGI app and supports mounting additional ASGI routes ✅ (`@bentoml.asgi_app` is a documented first-class decorator), so `/health`, `/ready`, `/schema` and `/info` are our own handlers mounted alongside its generated API. We do **not** ask the router to speak `/healthz` / `/readyz`; the router speaks our contract, and the adapter does the translation. That indirection is cheap and is what §2.2 is buying.

**Four adapter facts, verified in source, that are cheap now and painful in M4** ([`health-endpoints-and-lifecycle-source.md`](third-party-docs/bentoml/health-endpoints-and-lifecycle-source.md)):

1. **`/metrics` is registered only if metrics are enabled.** §9 assumes the endpoint exists, so **the adapter must enable metrics explicitly** rather than rely on the default.
2. **The adapter must never set `path_prefix`.** It moves BentoML's system routes, its API routes **and our mounted contract routes** together — so it silently relocates the very endpoints the router depends on. It looks harmless; leave a comment in `bentoml_backend.py` saying why it is not.
3. **BentoML already serves `/schema.json`**, which is *its* description of the service. Ours is **`/schema`**, compiled by us under **D13**. Five characters apart, unrelated payloads — **contract tests must assert the content**, or a path typo passes silently.
4. **Any response with status ≥500 has its body replaced** with *"An unexpected error has occurred, please check the server log."* Our contract must therefore never encode meaning in a ≥500 status alone; the reason has to travel in a body we control (§3.2, §4.5).

### 3.2 Readiness must mean "weights loaded"

✅ **Confirmed in source.** BentoML's `/readyz` reports that the *server* is up — the base class flips `_is_ready = True` in an `on_startup` hook that does nothing else, and the Service-level override falls through to an unconditional 200. For a model taking four minutes to load, that is a lie in the only direction that matters. R8's `wait_while_warming_up()` polled exactly that endpoint and therefore **proved nothing** ([`12_REFERENCE_CODE.md`](12_REFERENCE_CODE.md) §4). R8 then bolted a custom `readyz` API onto its service to compensate — the right instinct, and we make it a first-class part of the contract rather than an afterthought.

Our `/ready` returns 200 only when:

1. `load()` has returned successfully, **and**
2. `warmup()` (if declared) has completed.

and returns 503 **with the reason and, on failure, the exception message** otherwise. `STARTING` vs `LOADING` in the router's state machine ([`01_ARCHITECTURE.md`](01_ARCHITECTURE.md) §4) depends entirely on this distinction being honest.

### 3.3 Also wire `__is_ready__` — one readiness fact, two projections

BentoML calls a service's `__is_ready__` hook on every `/readyz` request if it exists, and returns 503 with a reason when it is `False` (likewise `__is_alive__` for liveness). **The adapter should wire both to the same underlying state our `/ready` reads.** Three reasons:

1. it makes `/readyz` truthful for anyone bypassing our contract — a `docker run` user, a `curl`, a future Kubernetes probe — which is the standalone-image promise (guardrail 11);
2. it is about three lines;
3. it gives **one readiness fact with two projections**, instead of two facts that can disagree.

> ⚠️ **These hooks are not on the documentation site.** They were found by reading `main`, and could change without a release note. Treat them as a **bonus**: our mounted `/ready` stays the load-bearing one, and `NATIVE.md` should record that a native backend owes only our route, not these.

---

## 4. Batching

### 4.1 The engine: BentoML's adaptive dispatcher

The batched endpoint is declared once, by our adapter, from the model's declaration:

```python
@bentoml.api(
    batchable=True,
    batch_dim=0,
    max_batch_size=settings.max_batch_size,     # ALWAYS passed explicitly
    max_latency_ms=settings.max_latency_ms,     # ALWAYS passed explicitly
)
def predict(self, batch: list[Inputs]) -> list[Outputs]:
    return self._wrapper.run_batch(batch)   # ours, above the seam
```

✅ **The adaptive claim is sourced.** In the vendor's words the dispatcher *"continuously adjusts batch size and window based on real-time traffic patterns"*, and it respects `max_latency_ms` *"by predicting the time it takes to process the batch."* Prediction of processing time is precisely what a fixed-window dispatcher does not do, and it is why this was preferred over both our own batcher and `@serve.batch`. R8's `CoreBatcher` implemented the fixed policy (flush on `max_batch_size` **or** oldest-item age ≥ `max_wait_ms`); that policy remains the specification for a future `native` backend and the mental model for tuning, but it is no longer what runs.

> **Caveat, kept deliberately:** the source says *that* the window adapts, never *how*. It is a Get-Started page, not an algorithm specification. **M3.5 step 4 still earns its place** — do not treat the citation as a substitute for measuring it.

Config maps as: `batching.max_batch_size` → `max_batch_size`, `batching.max_wait_ms` → `max_latency_ms`, `batching.enabled: false` → `max_batch_size: 1` ([ADR-0005](adr/0005-one-uniform-batched-calling-convention.md) — *not* `batchable=False`, since the handler's signature must not change).

⚠️ **Always pass both knobs explicitly.** `max_latency_ms` defaults to **`60000`** — that is **BentoML's own default**, inherited by every tool that does not override it, and not, as [`02_CONFIGURATION.md`](02_CONFIGURATION.md) §7 previously said, a nonsensical value chosen by R8. Batching is also **off by default** in BentoML, so `batchable=True` must be set explicitly for every tool.

### 4.2 What the dispatcher does not give us, and what we do about it

Honest accounting of the five improvements a batcher of our own would have been built with:

| Planned improvement | Status under BentoML | Resolution |
|---|---|---|
| **1. Group by compatibility key** (never batch requests whose non-batchable args differ) | **Not supported.** The dispatcher batches whatever arrives. | **Made impossible by construction**, not handled at runtime — see §4.3. This is the most important consequence of the decision. |
| **2. Cap by payload size** (`max_batch_bytes`) | Not supported | Dropped from v1. Mitigate with a conservative per-tool `max_batch_size` (a 64-CT-volume batch is a configuration error, and the config is per tool). `max_batch_bytes` is recorded as a `native`-backend feature and a phase-2 request upstream. **Note `batch_dim` exists** and is irrelevant while handlers take and return lists; it would matter only for a handler batching along a tensor axis. Recorded so it is a decision rather than an oversight. |
| **3. Preserve order and identity** | **Provided** — the dispatcher fans results back positionally | Ours to verify: §4.4's length check plus the contract test for interleaved arrivals. ⚠️ **The vendor states plainly that *"the order of the requests in a batch is not guaranteed"*** — arrival order is not preserved into the batch. Assert *attribution*, never submission order (§4.4). |
| **4. Per-item failure isolation (`retry_singly`)** | Not supported | **Ours**, in the predict wrapper above the seam: catch a batch-wide exception, re-run items individually, attribute the failure. Default on. Unaffected by the backend choice. |
| **5. Injectable clock for unit tests** | **Impossible** — the dispatcher owns its own timing and adapts it | Batching tests move from L1 (`ManualClock`, milliseconds) to L2 (in-process server, real time, statistical assertions). A real cost, and the main testing consequence of this decision ([`10_TESTING_STRATEGY.md`](10_TESTING_STRATEGY.md)). Assert *observable* properties — "N concurrent calls produced fewer than N handler invocations", "every caller got its own correct result" — never exact timings. |

### 4.3 One uniform convention — every handler takes a list of items

> **Rewritten by [ADR-0005](adr/0005-one-uniform-batched-calling-convention.md).** This section previously banned non-batchable inputs on batched tools and pushed every per-request knob into a static param. That restriction is gone, replaced by something simpler.

**The rule: a handler always receives a list of typed items and returns a list of the same length.** There is no second calling convention, no `scalar_inputs`, and no per-input `batchable:` flag.

BentoML's constraint is real and confirmed — *"a batchable API endpoint only accepts one parameter in addition to `bentoml.Context`"* — but the vendor documents the remedy we now take: **make the batched element a composite item**, so each item carries its own parameters.

```yaml
# tool.yaml
params:                                    # per DEPLOYMENT: changes what the batch computes
  - { name: input_resolution, type: integer, default: 512,
      description: Resolution every image is resized to before the forward pass. }
inputs:                                    # per REQUEST: fields of one item
  - { name: path, type: string, required: true,
      description: Path to the DICOM series. }
  - { name: threshold, type: number, default: 0.5,
      description: Confidence threshold applied to this item's detections. }
```

**Why this is safe where the old rule was strict.** The D15 hazard — two requests with `threshold=0.5` and `threshold=0.9` batched together, one silently answered with the other's value — **cannot be expressed any more.** `threshold` belongs to the item, so item `i` is scored with item `i`'s threshold. The state is unrepresentable rather than detected, which was always D15's instinct; it now costs the author nothing.

**The test for `params:` versus `inputs:`**, which is now a real question with a real answer:

> **Does this value change what the batched forward pass computes?** If yes → `params:` (input resolution, dtype, a different model head, a weights path). If it only shapes that item's own result → `inputs:` (threshold, top-k, NMS IoU, output format).

Static params are passed to `load()`, are overridable per config entry, and are part of the tool's identity. A genuine need for two input resolutions is two config entries over the same image — which the scheduler, TTL and status surfaces already handle.

> ⚠️ **One unverified premise, and M3.5 must settle it.** BentoML's documented per-item example uses a *wrapper Service* via `bentoml.depends` — but that wrapper exists to expose a non-list, multi-parameter API to *its* clients. **Our `/predict` contract is ours**, so a wrapper may be unnecessary. If it turns out to be required, **the adapter generates it and `handler.py` never sees it** ([`03_TOOL_AUTHORING.md`](03_TOOL_AUTHORING.md) is explicit that framework accommodations must not reach the author). See [ADR-0005](adr/0005-one-uniform-batched-calling-convention.md) §5.

### 4.4 The batch-length check is safety-critical and stays ours

```python
def predict(self, items: list[Item]) -> list[dict]:
    # items: N items, each carrying its own threshold
    # self.input_resolution: fixed at load
    # MUST return exactly N results, positionally aligned with items
```

Rules:

- **Every handler is called with a list, always** — length 1 when `max_batch_size: 1`. One code path, no exceptions ([ADR-0005](adr/0005-one-uniform-batched-calling-convention.md)).
- The handler **must** return a list of length N, positionally aligned. The wrapper validates the length and fails loudly on mismatch. A silent misalignment returns one patient's result for another — in a healthcare context, the worst possible bug. **This check runs above the seam and is independent of the batching engine**, which is exactly why it lives there.
- ⚠️ **Assert attribution, never submission order.** *"The order of the requests in a batch is not guaranteed"* is documented vendor behaviour. Send N *distinguishable* concurrent requests and assert each caller receives its own answer; do **not** assert the handler observes them in submission order, and do not report that as a flake.

**ADR-0005 raises the stakes on this check rather than lowering them.** With every tool on the batched path, an off-by-one in a handler now has the same consequence everywhere. [`16_COMPLEXITY_AUDIT.md`](16_COMPLEXITY_AUDIT.md) §5 names batch attribution as never-trim; nothing in ADR-0005 may be cited to weaken it.

R8 expressed batchability as `Batchable[T] = Union[T, List[T]]`, which forces annotation introspection. We need no such flag at all now: batching is a property of the *tool's configuration*, and the handler signature is the same either way.

### 4.5 A saturated tool must be distinguishable from a starting one

When the dispatcher cannot meet its latency budget it calls a fallback that raises `ServiceUnavailable("process is overloaded")` — **HTTP 503**. The router already uses 503 + `TOOL_UNAVAILABLE` for its *own* cold-start queueing ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §6), so without intervention **"the tool is starting" and "the tool is overloaded" are indistinguishable** to the caller and to us. Worse, because 503 ≥ 500, BentoML **replaces the message** with a generic string, so the cause is lost.

**The adapter must catch `ServiceUnavailable` before BentoML's handler and re-emit it in our envelope with a distinct saturation reason.** This is not optional polish: **D28** is precisely about not misattributing a failure, and an unexplained 503 under load reads as a broken tool. See [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](06_LIFECYCLE_TTL_AND_SCHEDULING.md) for the router-side concurrency cap that decides whether the container is ever asked to make this judgement.

---

## 5. Concurrency inside the container

The trap is unchanged by the backend choice: **a GPU inference call must not block the event loop**, or `/health` and `/ready` stop answering and the router declares a busy model dead.

1. Handlers are **synchronous** by default and run in a thread executor. BentoML runs sync API methods off the loop already; do not defeat it by declaring the handler `async`.
2. ✅ Exactly **one** inference at a time per worker — **and we do not have to enforce this.** BentoML dispatches every sync API call through a single `anyio.CapacityLimiter(threads)`, with **`threads` defaulting to 1**. Our design and the framework's default agree, so **the lock this section used to require is redundant and is removed.** Two obligations replace it: the adapter **sets `threads` explicitly** rather than relying on the default, and **M3.5 reports the value it ran with** — firing 32 concurrent requests and declaring batching working or broken without stating `threads` produces an uninterpretable result.
3. `/health` and `/ready` are served from mounted routes that **never touch the handler's limiter** — they must answer during a five-second inference. Contract-tested.
4. `workers > 1` → multiple BentoML workers, each with its own handler and device. **Pass an explicit device list and index into it.** R8 derived `gpu_id = max(0, worker_index - 1)` from `worker_index`; ⚠️ **that is the vendor's own documented idiom with an added guard, not an R8 blunder** — and the vendor's own page gives the index as 0-based and 1-based three paragraphs apart. The lesson is therefore *do not build device identity on a framework's indexing convention*, not *R8 got it wrong*. Read `worker_index` once, map through `TSWAP_DEVICE_LIST`, **log the resulting mapping at startup**, fail loudly if the list is shorter than the worker count, and **have M3.5 observe the actual value.**
5. Multiple workers multiply VRAM by the worker count. Document loudly; the scheduler does not know (**D7**).
6. Support `async def predict` for genuinely I/O-bound handlers, detected by inspection.

---

## 6. Lifecycle inside the container

```mermaid
sequenceDiagram
    participant D as Docker
    participant S as BentoML server
    participant A as tool_swap_runtime adapter
    participant T as Loader thread
    participant H as Handler
    participant R as Router

    D->>S: start (python -m tool_swap_runtime.server)
    S->>A: construct service, mount our routes
    A->>A: import handler, compile schema, bind :8000
    A->>T: start background load
    R->>S: GET /health
    S-->>R: 200 alive
    T->>H: __init__(device, **params)
    T->>H: load()
    T->>H: warmup() (optional)
    T->>A: mark ready (or record failure + traceback)
    R->>S: GET /ready
    S-->>R: 200 ready
    R->>S: POST /predict
    S->>A: batched call (dispatcher-formed batch of N)
    A->>H: predict(**batched inputs)
    H-->>A: N outputs
    A->>A: length check, fan out
    S-->>R: outputs
    Note over R,S: ... idle until ttl ...
    R->>S: SIGTERM (idle TTL — the only idle path in v1)
    A->>H: unload() (advisory hygiene hook)
    S-->>D: exit 0
```

> **There is no soft-unload step** ([ADR-0004](adr/0004-hard-stop-only-in-v1.md)). One idle timer, one reclamation mechanism: the container stops and the OS reclaims. `unload()` survives only as an advisory hook on `SIGTERM`.

### ⚠️ 6.1 Bind-then-load is **mandatory**, not stylistic — the M4 trap

Bind-then-load is kept from R8's BentoML service, which started warm-up on a background thread precisely so the HTTP server could bind at once. **What the plan never said is why it was necessary**, and it is not a matter of taste:

**BentoML's `lifespan` awaits `create_instance` — which constructs the service class, running `__init__` — *before* the socket accepts connections.** Uvicorn does not serve until lifespan startup completes. So if M4 loads the handler in `__init__` or in an `on_startup` hook, then during a four-minute load:

| Plan commitment | What actually happens |
|---|---|
| *"`/health` must answer **before** weights load and must never block"* (§3.1) | **Nothing answers.** The socket is not listening — the router gets *connection refused*, not a 503 |
| The `STARTING` → `LOADING` → `READY` progression ([`01_ARCHITECTURE.md`](01_ARCHITECTURE.md) §4) | `LOADING` is **unobservable**; the two states collapse and the diagnostic value is lost |
| *"`/ready` is 503 with a reason while loading"* (M4 contract suite) | **Untestable** — there is no response at all |
| *"`load()` raising leaves `/ready` at 503 with the traceback"* | An exception in `__init__` **fails lifespan startup and exits the process**; no server survives to report it |

**Therefore M4 must load off the lifespan path** — a background thread or task started from `__init__`, returning immediately — recording the outcome (loaded, or the exception) in adapter state that both `/ready` and `__is_ready__` (§3.3) read. **R8's background warm-up thread was correct**; its bug was narrow — `_warmup_background` swallowed the exception, leaving a service that was alive, never ready, and silent about why, compounded by an unbounded readiness poll on the caller's side. Keep the design; fix the bug.

**M3.5 must verify this before M4 builds on it**: sleep 30 s in `__init__` and confirm whether the port refuses connections throughout.

Failure handling:

- `load()` raises → record error and traceback, keep `/ready` at 503 **with the reason in the body**, log the traceback, and exit non-zero after a short grace period so Docker records the failure.
- `predict()` raises → structured error for that item (or batch, with `retry_singly` isolation), log the traceback, stay ready. A bad input must not kill the server.
- OOM during predict → return the error and optionally `torch.cuda.empty_cache()`. On a configurable consecutive-OOM threshold, exit so the router restarts clean.

---

## 7. Environment contract (router → container)

The router configures the container purely through environment variables and mounts — explicit, greppable, no shared code. **The adapter translates these into BentoML configuration**; the router never sets a BentoML variable directly, so the mapping can change without touching the router.

| Variable | Meaning |
|---|---|
| `TSWAP_HANDLER` | `handler.py:ClassName` |
| `TSWAP_MODEL_NAME` | For logs/metrics labels |
| `TSWAP_PORT` | Listen port (default 8000) |
| `TSWAP_DEVICE` | `cpu` or `cuda` (indices already remapped by Docker) |
| `TSWAP_DEVICE_LIST` | e.g. `0,1` as seen inside the container, for multi-worker mapping |
| `TSWAP_MAX_BATCH_SIZE` | → `max_batch_size` |
| `TSWAP_MAX_WAIT_MS` | → `max_latency_ms` |
| `TSWAP_WORKERS` | → BentoML workers |
| `TSWAP_PARAMS` | JSON object of static params (§4.3), passed to `load()` |
| `TSWAP_LOG_LEVEL` / `TSWAP_LOG_JSON` | Runtime logging |
| `TSWAP_RETRY_SINGLY` | Per-item failure isolation |
| `TSWAP_BACKEND` | `bentoml` (v1). Reserved; `native` fails with "not implemented". |

Not available: `TSWAP_MAX_BATCH_BYTES` (§4.2 — the dispatcher has no equivalent).

R8 used the same env-var approach (`RUN_SVC_MAX_BATCH_SIZE` et al.) and **printed the resolved knobs at boot** — exactly right for answering "why is it not batching?". The runtime must **log its full effective configuration at startup**, including the backend name, the BentoML version and the worker→device mapping.

---

## 8. Logging from inside the container

- Write to **stdout/stderr only**; the router's collector persists them ([`07_CLI_AND_OPS.md`](07_CLI_AND_OPS.md)).
- Structured JSON lines when `TSWAP_LOG_JSON=true`, with `model`, `request_id`, `batch_size`, `duration_ms`.
- Propagate the router's `X-Request-Id` into the log context so one id traces client → router → container.
- `PYTHONUNBUFFERED=1` in the base image, or logs vanish on crash — precisely when they are needed.
- **Bring BentoML's own logger into our format** rather than letting it emit a parallel log stream; its access logs are useful, but two formats in one stream defeats the collector.

R8 pumped subprocess stdout/stderr through reader threads and printed them **only when `verbose` was set**, discarding them otherwise. Always persist; let the user filter.

---

## 9. Metrics

BentoML ships Prometheus metrics (request counts, latency histograms, and **batch-size and dispatcher metrics**) — a further concrete gain from the decision, since batch-size observability is exactly what tells us whether batching is working.

Serve them at `/metrics`, relabelled into our namespace where they overlap, plus our additions:

| Metric | Type | Source |
|---|---|---|
| `tswap_requests_total` | counter | BentoML (`request_total`) |
| `tswap_request_duration_seconds` | histogram | BentoML (`request_duration_seconds`) |
| `tswap_request_in_progress` | gauge | BentoML (`request_in_progress`) — **in-flight, free** |
| `tswap_batch_size` | histogram | BentoML dispatcher (`adaptive_batch_size`) |
| `tswap_tool_loaded` | gauge (0/1) | Ours |
| `tswap_load_duration_seconds` | histogram | Ours |
| `tswap_batch_item_failures_total` | counter | Ours (`retry_singly`) |

**Set `metrics={"namespace": "tswap"}`.** It renames BentoML's entire default set in one parameter, which is where most of the table above comes from **free**.

⚠️ **`tswap_queue_wait_seconds` has been removed from this table: no such BentoML metric exists.** The dispatcher exposes `request_in_progress`, `request_total`, `request_duration_seconds` and `adaptive_batch_size` — and nothing else. Queue wait is the key diagnostic for tuning `max_wait_ms`, so it must be **measured above the seam** if we want it. Do not plan around a metric the framework does not emit.

Router-side additions: `tswap_tool_state`, `tswap_cold_starts_total`, `tswap_evictions_total`, `tswap_tool_resident_seconds`. Together these answer the questions that justify the project: how often do we swap, what a cold start costs, and whether batching is actually happening.

---

## 10. Versioning the runtime contract

The runtime is baked into images; the router is upgraded independently. They **will** be out of step in production.

- `/info` reports `runtime_version`, `contract_version`, **`backend`** and **`backend_version`**. The last two are what make a "works on my image" report diagnosable.
- The router logs a warning on an unknown contract version and degrades to the minimal contract (`/health`, `/ready`, `/predict`).
- Never remove or repurpose an endpoint within a contract major version. **This applies to our paths, not BentoML's** — its route names are an implementation detail behind §2, and nothing outside the adapter may depend on them.
- A BentoML major upgrade bumps `runtime_version` and requires the contract suite (§2.4 rule 3) to pass before release.
- `tswap doctor` reports which images were built with which runtime and BentoML versions and flags stale ones. Without it, "rebuild all your models" becomes a mystery-debugging session.

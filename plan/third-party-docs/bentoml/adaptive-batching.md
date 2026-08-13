# Adaptive batching — BentoML

> **Source:** https://docs.bentoml.com/en/latest/get-started/adaptive-batching.html
> **BentoML version at capture:** 1.4.39 (latest on PyPI, published 2026-05-07) · **Captured:** 2026-08-13
> **Relevance to tool-swap:** this is **the evidence base for D14**. [`05_RUNTIME_AND_BATCHING.md`](../../05_RUNTIME_AND_BATCHING.md) §4.1 claims the dispatcher is *adaptive* rather than fixed-window, and that claim is the whole reason BentoML was preferred over a batcher of our own and over Ray's `@serve.batch`. It also bears directly on **D15** and on the batching config in [`02_CONFIGURATION.md`](../../02_CONFIGURATION.md) §7.
> **Completeness:** complete. Navigation chrome, image markup and the theme toggles are stripped; all prose and code below are verbatim.

---

Many models achieve higher throughput, better resource utilization, and lower latency when processing requests in batches. BentoML supports **adaptive batching**, a dynamic request dispatching mechanism that intelligently groups multiple requests for more efficient processing. It continuously adjusts batch size and window based on real-time traffic patterns. This ensures optimal performance as it provides fast responses during low-traffic periods and maximizes resource utilization under heavy load.

> **Note**
>
> Batching means grouping multiple inputs into a single batch for processing. It includes two main concepts:
>
> * **Batch window**: Maximum time a service waits to accumulate requests into a batch before processing.
> * **Batch size**: Maximum number of requests in a batch.

## Architecture

Adaptive batching is implemented on the server side. This is advantageous as opposed to client-side batching because it simplifies the client's logic and it is often times more efficient due to traffic volume.

Specifically, there is a dispatcher within a BentoML Service that oversees collecting requests into a batch until the conditions of the batch window or batch size are met, at which point the batch is sent to the model for inference.

*(Figure: adaptive batching in a single BentoML Service.)*

For multiple Services, the Service responsible for running model inference (`ServiceTwo` in the diagram below) collects requests from the intermediary Service (`ServiceOne`) and forms batches based on optimal latency.

*(Figure: adaptive batching across multiple BentoML Services.)*

> **Note**
>
> The `bentoml.depends()` function allows one Service to use the functionalities of another. For details, see [Run distributed Services](https://docs.bentoml.com/en/latest/build-with-bentoml/distributed-services.html).

The adaptive batching algorithm continuously learns and adjusts the batching parameters based on recent trends in request patterns and processing time. This means that during high traffic time, batches are likely to be larger and processed more frequently, whereas during quieter periods, BentoML will prioritize reducing latency, even if that means smaller batch sizes.

The order of the requests in a batch is not guaranteed.

## Configure adaptive batching

By default, adaptive batching is disabled. Use the `@bentoml.api` decorator to enable it and configure the batch behavior for an API endpoint.

Here is an example of enabling batching for the summarization Service in Hello world.

```python
from __future__ import annotations
import bentoml
from typing import List
from transformers import pipeline


@bentoml.service
class Summarization:
    def __init__(self) -> None:
        self.pipeline = pipeline('summarization')

    # Set `batchable` to True to enable batching
    @bentoml.api(batchable=True)
    def summarize(self, texts: List[str]) -> List[str]:
        results = self.pipeline(texts)
        return [item['summary_text'] for item in results]
```

Note that the batchable API:

* Should be of a type that can encapsulate multiple individual requests, such as `typing.List[str]` or `numpy.ndarray`.
* Only accepts one parameter in addition to `bentoml.Context`.

You can call the batchable endpoint through a BentoML client:

```python
import bentoml
from typing import List

client = bentoml.SyncHTTPClient("http://localhost:3000")

# Specify the texts to summarize
texts: List[str] = [
    "Paragraph one to summarize",
    "Paragraph two to summarize",
    "Paragraph three to summarize"
]

# Call the exposed API
response = client.summarize(texts=texts)

print(f"Summarized results: {response}")
```

Other available parameters for adaptive batching:

* `batch_dim`: The batch dimension for both input and output, which can be a tuple or a single value. See Service API for more information.
* `max_batch_size`: The upper limit for the number of requests that can be grouped into a single batch. Set this parameter based on the available resources, like memory or GPU, to avoid overloading the system.
* `max_latency_ms`: The upper limit, in milliseconds, for the end-to-end batch processing delay. The dispatcher will respect this value by predicting the time it takes to process the batch.

When you specify `max_batch_size` and `max_latency_ms` parameters, BentoML ensures that these constraints are respected, even as it dynamically adjusts batch sizes and processing intervals based on the adaptive batching algorithm. The algorithm's primary goal is to optimize both throughput (by batching requests together) and latency (by ensuring requests are processed within an acceptable time frame). However, it operates within the bounds set by these parameters.

> **Note**
>
> When using a synchronous endpoint in one Service to call a batchable endpoint in another Service, it sends only one request at a time and waits for a response before sending the next. This is due to the default concurrency of 1 for synchronous endpoints. To enable concurrent requests and allow batching, set the `threads=N` parameter in the `@bentoml.service` decorator.

More BentoML examples with batchable APIs: [SentenceTransformers](https://github.com/bentoml/BentoSentenceTransformers), [CLIP](https://github.com/bentoml/BentoClip) and [ColPali](https://github.com/bentoml/BentoColPali).

## Handle multiple parameters

A batchable API endpoint only accepts one parameter in addition to `bentoml.Context`. For multiple parameters, use a composite input type, such as a Pydantic model, to group these parameters into a single object. You also need a wrapper Service to serve as an intermediary to handle individual requests from clients.

Example usage:

```python
from __future__ import annotations

from pathlib import Path

import bentoml
from pydantic import BaseModel


# Group together multiple parameters with pydantic
class BatchInput(BaseModel):
    image: Path
    threshold: float


# A primary BentoML Service with a batchable API
@bentoml.service
class ImageService:
    @bentoml.api(batchable=True)
    def predict(self, inputs: list[BatchInput]) -> list[Path]:
        # Inference logic here using the image and threshold from each input
        # For demonstration, return the image paths directly
        return [input.image for input in inputs]


# A wrapper Service
@bentoml.service
class MyService:
    batch = bentoml.depends(ImageService)

    @bentoml.api
    async def generate(self, image: Path, threshold: float) -> Path:
        result = await self.batch.to_async.predict([BatchInput(image=image, threshold=threshold)])
        return result[0]
```

In the code snippet:

* The Pydantic model groups together all the required parameters. Each `BatchInput` instance represents a single request's parameters, like `image` and `threshold`.
* The primary BentoML Service `ImageService` has a batchable API method to accept a list of `BatchInput` objects.
* The wrapper Service defines an API `generate` that accepts individual parameters (`image` and `threshold`) for a single request. It uses `bentoml.depends` to invoke the `ImageService`'s batchable `predict` method with a list containing a single `BatchInput` instance.

## Error handling

If a Service can't process requests fast enough and exceeds the `max_latency_ms`, it will return an HTTP 503 Service Unavailable error. To resolve this, either increase `max_latency_ms` or improve system resources, such as adding more memory or CPUs.

---

## tool-swap notes

Everything above is BentoML's. Everything below is ours.

### 1. **D14's central claim is now sourced.** ✅

[`05_RUNTIME_AND_BATCHING.md`](../../05_RUNTIME_AND_BATCHING.md:173) §4.1 says the dispatcher *"estimates the request-arrival rate and the model's own latency curve and adapts the wait window to keep p99 under `max_latency_ms`"*. Until this capture that sentence had **no citation anywhere in `plan/`**, and it is the sole technical reason **D14** chose BentoML over writing our own fixed size-or-age batcher, and the reason open question 5 in [`15_RAY_SERVE_EVALUATION.md`](../../15_RAY_SERVE_EVALUATION.md) was closed in BentoML's favour against `@serve.batch`.

The vendor's supporting statements, quotable:

- *"It continuously adjusts batch size and window based on real-time traffic patterns."*
- *"The adaptive batching algorithm continuously learns and adjusts the batching parameters based on recent trends in request patterns and processing time."*
- *"`max_latency_ms` … The dispatcher will respect this value by **predicting the time it takes to process the batch**."*

That last clause is the strongest: prediction of processing time is precisely what a fixed-window dispatcher does not do, and it is the specific capability Ray's `@serve.batch` lacks ([`ray-serve/advanced-guides/dyn-req-batch.md`](../ray-serve/advanced-guides/dyn-req-batch.md)).

**Caveat to keep honest:** this is marketing-adjacent prose in a *Get Started* page, not an algorithm specification. It says *that* the window adapts, never *how*. M3.5 step 4 ([`09_IMPLEMENTATION_PLAN.md`](../../09_IMPLEMENTATION_PLAN.md:132)) measures the behaviour, and it should stay in the plan for exactly that reason. Do not treat this page as a substitute for the spike.

### 2. **D15 has a documented alternative remedy, and the docs use our own example.** ⚠️

**D15** ([`13_OPEN_QUESTIONS.md`](../../13_OPEN_QUESTIONS.md:120)) forbids a batched tool from declaring a non-batchable input, and pushes per-request knobs into **static params fixed at load time**, on the grounds that *"two requests with `threshold=0.5` and `threshold=0.9` would be batched together and one silently answered with the other's parameter"*.

The constraint that motivates D15 is real and confirmed here: *"A batchable API endpoint only accepts one parameter in addition to `bentoml.Context`."*

**But BentoML documents a second remedy we do not consider**, and its example is literally `image: Path` plus `threshold: float`. Group the parameters into a Pydantic model and make *that* the batched element. Each item then carries its own `threshold`, the dispatcher batches a `list[BatchInput]`, and the handler applies each item's parameters to that item.

This matters because it changes what D15 actually costs:

| Kind of parameter | Can it be per-request under BentoML? |
| --- | --- |
| Post-processing knobs (`threshold`, top-k, NMS IoU, output format) | **Yes** — carried per item, applied per item after the batched forward pass |
| Parameters that change the batched computation itself (input resolution, dtype, a different model head, sliding-window size) | **No** — these genuinely cannot vary within one batched call, and D15's static-param remedy is the right one |

**D15 is therefore over-broad as written.** It is correct for the second row and unnecessarily restrictive for the first, which is likely the more common case in our zoo. Note the interaction with **D13**: a per-item parameter is a *field of the input schema*, not a static param, so the two remedies produce different `/schema` output and different `?format=tools` projections — this is an API-surface decision, not only an internal one.

**Proposed amendment, not applied:** see §2 of [`INDEX.md`](INDEX.md). Do not change **D15** on the strength of one docs page; the safety argument behind it is sound and the failure it prevents is silent. But the plan should record that a per-item option exists and say why we do or do not take it.

**Note also the cost of the documented pattern:** it requires a *wrapper Service* using `bentoml.depends()`, i.e. two Services and an extra hop. That is exactly the kind of framework accommodation [`03_TOOL_AUTHORING.md`](../../03_TOOL_AUTHORING.md:151) insists must never reach the author — so if we adopt it, our adapter generates it, and `handler.py` still sees a plain list of typed items.

### 3. **"The order of the requests in a batch is not guaranteed."** ⚠️ **Safety-relevant.**

One flat sentence, no elaboration. It plainly means arrival order is not preserved into the batch. It does **not** say that `outputs[i]` fails to correspond to `inputs[i]` — response mapping is the dispatcher's job and the framework would be broken otherwise — but the plan's most safety-critical assertion depends on precisely that correspondence:

- the batch-length check and `retry_singly` in [`05 §4`](../../05_RUNTIME_AND_BATCHING.md);
- `test_batch_length_mismatch_raises` and the attribution tests in [`10_TESTING_STRATEGY.md`](../../10_TESTING_STRATEGY.md:288);
- the stated hazard that *"a silent misalignment returns one patient's result for another"* ([`09 M4`](../../09_IMPLEMENTATION_PLAN.md:161)).

**Consequence for M3.5 step 4 and M4's contract suite:** ordering must be asserted explicitly rather than assumed. Send N *distinguishable* concurrent requests — each recoverable from its own result — and assert every caller receives its own answer under interleaved arrival. Do **not** assert that the handler observes them in submission order; this sentence says it may not. The existing test wording in [`09 M4`](../../09_IMPLEMENTATION_PLAN.md:163) ("every caller receives its own correct result under interleaved arrival") already has the right shape. Keep it that way, and add a note that unordered arrival is documented vendor behaviour rather than a flake.

### 4. HTTP 503 on latency overrun — an error-mapping input for the router

*"If a Service can't process requests fast enough and exceeds the `max_latency_ms`, it will return an HTTP 503 Service Unavailable error."*

The router already reserves 503 + `TOOL_UNAVAILABLE` for its *own* cold-start queueing ([`04_API_CONTRACT.md`](../../04_API_CONTRACT.md) §6, [`09 M3`](../../09_IMPLEMENTATION_PLAN.md:115)). A tool that is fully **`READY` and simply saturated** will now also produce a 503, from a different origin and with a different remedy. If the proxy passes it through unchanged, "the tool is starting" and "the tool is overloaded" become indistinguishable to the caller and to us.

**Action for M4:** the adapter should catch this case and map it to a distinct `reason`, so that saturation is nameable. Worth confirming during M3.5 step 4 that the 503 is actually observable at our contract boundary.

### 5. Batching is **off by default**, and knob names map cleanly

*"By default, adaptive batching is disabled."* Our defaults are the opposite — [`02_CONFIGURATION.md`](../../02_CONFIGURATION.md:92) ships `max_batch_size: 8`, `max_wait_ms: 20`. Nothing wrong with that, but the adapter must set `batchable=True` explicitly and must honour `batching.enabled: false` by *not* setting it, and by still calling the handler with lists of length 1 (the contract test in [`09 M4`](../../09_IMPLEMENTATION_PLAN.md:163) already requires this).

Mapping confirmed: our `max_batch_size` → `max_batch_size`; our `max_wait_ms` → `max_latency_ms`. [`02 §7`](../../02_CONFIGURATION.md:345)'s gloss — *"a latency target the adaptive dispatcher aims to keep, not a fixed wait"* — is accurate, and this page is its source.

**A parameter our config does not have:** `batch_dim`, *"the batch dimension for both input and output, which can be a tuple or a single value."* Irrelevant while handlers take and return lists; it would matter for a handler batching along a tensor axis (a stacked `numpy.ndarray` rather than a list). Not needed in v1 — recorded so it is a decision rather than an oversight.

### 6. `threads=N` and the default concurrency of 1

*"This is due to the default concurrency of 1 for synchronous endpoints. To enable concurrent requests and allow batching, set the `threads=N` parameter in the `@bentoml.service` decorator."*

Stated for the Service-to-Service case, but it names a default that [`05 §5`](../../05_RUNTIME_AND_BATCHING.md:251) leans on: *"Handlers are synchronous by default and run in a thread executor… Exactly one inference at a time per worker."* Our position and BentoML's default agree — but §5 also expects the framework to accept concurrent HTTP requests and batch them, which is not the same knob as `workers`. **Verify in M3.5 step 4:** if concurrency 1 applied to the HTTP entry point of a single Service, 32 concurrent requests would serialise and batching would never engage — which would make the whole spike read as a failure for the wrong reason. Establish whether `threads` must be set for our single-Service topology before drawing conclusions from the numbers.

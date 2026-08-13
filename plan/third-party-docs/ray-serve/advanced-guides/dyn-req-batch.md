# Dynamic Request Batching

> **Source:** https://docs.ray.io/en/latest/serve/advanced-guides/dyn-req-batch.html
> **Ray version at capture:** 2.57.0 · **Captured:** 2026-08-13
> **Relevance to tool-swap:** this is Ray's `@serve.batch`, the direct competitor to BentoML's adaptive dispatcher under **D14**/**D5**. It **answers open question 5** in [`15_RAY_SERVE_EVALUATION.md`](../../../15_RAY_SERVE_EVALUATION.md) §9: the window is fixed, not latency-adaptive — but it is runtime-tunable through `reconfigure()`.

---

Serve offers a request batching feature that can improve your service throughput without sacrificing latency. When a request arrives, Serve puts the request in a queue. This queue buffers the requests to form a batch. The deployment picks up the batch and evaluates it. After the evaluation, Ray Serve splits up the resulting batch, and returns each response individually.

## Enable batching for your deployment

You can enable batching by using the `ray.serve.batch` decorator.

```python
from ray import serve
from ray.serve.handle import DeploymentHandle


@serve.deployment
class Model:
    def __call__(self, single_sample: int) -> int:
        return single_sample * 2


handle: DeploymentHandle = serve.run(Model.bind())
assert handle.remote(1).result() == 2
```

The batching decorators expect you to make the following changes in your method signature:

- Declare the method as an async method because the decorator batches in asyncio event loop.
- Modify the method to accept a list of its original input types as input. For example, `arg1: int, arg2: str` should be changed to `arg1: List[int], arg2: List[str]`.
- Modify the method to return a list. The length of the return list and the input list must be of equal lengths.

```python
from typing import List

import numpy as np

from ray import serve
from ray.serve.handle import DeploymentHandle


@serve.deployment
class Model:
    @serve.batch(max_batch_size=8, batch_wait_timeout_s=0.1)
    async def __call__(self, multiple_samples: List[int]) -> List[int]:
        return np.array(multiple_samples) * 2


handle: DeploymentHandle = serve.run(Model.bind())
responses = [handle.remote(i) for i in range(8)]
assert list(r.result() for r in responses) == [i * 2 for i in range(8)]
```

You can supply 4 optional parameters to the decorators:

- `max_batch_size` controls the size of the batch. The default value is 10.
- `batch_wait_timeout_s` controls how long Serve should wait for a batch once the first request arrives. The default value is 0.01 (10 milliseconds).
- `max_concurrent_batches` maximum number of batches that can run concurrently. The default value is 1.
- `batch_size_fn` optional function to compute the effective batch size. If provided, this function takes a list of items and returns an integer representing the batch size. Useful for batching based on custom metrics such as total nodes in graphs or total tokens in sequences. If `None` (the default), the batch size is computed as `len(batch)`.

Once the first request arrives, the batching decorator waits for a full batch (up to `max_batch_size`) until `batch_wait_timeout_s` is reached. If the timeout is reached, Serve sends the batch to the model regardless of the batch size.

> **Tip.** You can reconfigure your `batch_wait_timeout_s` and `max_batch_size` parameters using the `set_batch_wait_timeout_s` and `set_max_batch_size` methods:
>
> ```python
> from typing import Dict
>
>
> @serve.deployment(
>     # These values can be overridden in the Serve config.
>     user_config={
>         "max_batch_size": 10,
>         "batch_wait_timeout_s": 0.5,
>     }
> )
> class Model:
>     @serve.batch(max_batch_size=8, batch_wait_timeout_s=0.1)
>     async def __call__(self, multiple_samples: List[int]) -> List[int]:
>         return np.array(multiple_samples) * 2
>
>     def reconfigure(self, user_config: Dict):
>         self.__call__.set_max_batch_size(user_config["max_batch_size"])
>         self.__call__.set_batch_wait_timeout_s(user_config["batch_wait_timeout_s"])
> ```
>
> Use these methods in the constructor or the `reconfigure` method to control the `@serve.batch` parameters through your Serve configuration file.

## Custom batch size functions

By default, Ray Serve measures batch size as the number of items in the batch (`len(batch)`). However, in many workloads, the computational cost depends on properties of the items themselves:

- **Graph Neural Networks (GNNs)**: cost depends on total number of nodes across all graphs
- **Natural Language Processing (NLP)**: transformer models batch by total token count
- **Variable-resolution images**: memory usage depends on total pixels

### Graph Neural Network example

```python
@serve.deployment
class GraphNeuralNetwork:
    @serve.batch(
        max_batch_size=10000,  # Maximum total nodes per batch
        batch_wait_timeout_s=0.1,
        batch_size_fn=lambda graphs: sum(g.num_nodes for g in graphs),
    )
    async def predict(self, graphs: List[Graph]) -> List[float]:
        results = []
        for graph in graphs:
            score = float(graph.num_nodes * 0.1)
            results.append(score)
        return results

    async def __call__(self, graph: Graph) -> float:
        return await self.predict(graph)
```

### NLP token batching example

```python
@serve.deployment
class TokenBatcher:
    @serve.batch(
        max_batch_size=512,  # Maximum total tokens per batch
        batch_wait_timeout_s=0.1,
        batch_size_fn=lambda sequences: sum(len(s.split()) for s in sequences),
    )
    async def process(self, sequences: List[str]) -> List[int]:
        return [len(seq.split()) for seq in sequences]

    async def __call__(self, sequence: str) -> int:
        return await self.process(sequence)
```

## Streaming batched requests

Decorate async generator functions with the `ray.serve.batch` decorator. The function takes in a `List` of inputs and in each iteration it `yield`s an iterable of outputs with the same length as the input batch size.

```python
@serve.deployment
class StreamingResponder:
    @serve.batch(max_batch_size=5, batch_wait_timeout_s=0.1)
    async def generate_numbers(
        self, max_list: List[str]
    ) -> AsyncGenerator[List[Union[int, StopIteration]], None]:
        for i in range(max(max_list)):
            next_numbers = []
            for requested_max in max_list:
                if requested_max > i:
                    next_numbers.append(str(i))
                else:
                    next_numbers.append(StopIteration)
            yield next_numbers
            await asyncio.sleep(0.1)

    async def __call__(self, request: Request) -> StreamingResponse:
        max = int(request.query_params.get("max", "25"))
        gen = self.generate_numbers(max)
        return StreamingResponse(gen, status_code=200, media_type="text/plain")
```

Some inputs within a batch may generate fewer outputs than others. When a particular input has nothing left to yield, pass a `StopIteration` object into the output iterable. This terminates the generator Serve returns for that input, allowing the end client's connection to terminate once its call is done, instead of waiting until the entire batch is done.

## Tips for fine-tuning batching parameters

`max_batch_size` ideally should be a power of 2 (2, 4, 8, 16, …) because CPUs and GPUs are both optimized for data of these shapes. Large batch sizes incur a high memory cost as well as latency penalty for the first few requests.

When using `batch_size_fn`, set `max_batch_size` based on your custom metric rather than item count.

Set `batch_wait_timeout_s` considering the end-to-end latency SLO. For example, if your latency target is 150ms, and the model takes 100ms to evaluate the batch, set the `batch_wait_timeout_s` to a value much lower than 150ms - 100ms = 50ms.

When using batching in a Serve Deployment Graph, the relationship between an upstream node and a downstream node might affect performance. Consider a chain of two models where the first sets `max_batch_size=8` and the second sets `max_batch_size=6`. When the first model finishes a full batch of 8, the second finishes one batch of 6 and then partially fills the next batch with 8 - 6 = 2 requests, incurring latency costs. The batch size of downstream models should ideally be multiples or divisors of the upstream models.

---

## tool-swap notes — this page answers open question 5

1. **`@serve.batch` is a fixed-window dispatcher, not an adaptive one.** `max_batch_size` and `batch_wait_timeout_s` are static parameters; the page's tuning advice is manual arithmetic against a latency SLO ("set it much lower than 150ms - 100ms"). BentoML's dispatcher instead estimates the wait window from observed latency. **Point to BentoML for Role B, and open question 5 is answered.**
2. **But the window is runtime-tunable** via `set_max_batch_size` / `set_batch_wait_timeout_s` from `reconfigure()`, so an adaptive policy could be built on top — externally, by a controller watching latency.
3. **`batch_size_fn` is genuinely better than anything in our plan.** Batching by total tokens/nodes/pixels rather than item count is the correct answer for variable-cost inputs, and **D5** currently has no equivalent. Worth borrowing regardless of the Ray decision.
4. **`max_concurrent_batches` defaults to 1**, i.e. no pipelining of batch execution by default.
5. **The `StopIteration` streaming protocol** is a neat solution to ragged batch completion, relevant if we ever stream.

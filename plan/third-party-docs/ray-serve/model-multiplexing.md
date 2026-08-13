# Model Multiplexing

> **Source:** https://docs.ray.io/en/latest/serve/model-multiplexing.html
> **Ray version at capture:** 2.57.0 · **Captured:** 2026-08-13
> **Relevance to tool-swap:** this is the off-the-shelf equivalent of our central primitive — bounded LRU model residency. It is the concession in [`15_RAY_SERVE_EVALUATION.md`](../../../15_RAY_SERVE_EVALUATION.md) §1 item 2, and it corrects [`14_ALTERNATIVES_EVALUATION.md`](../../../14_ALTERNATIVES_EVALUATION.md) §2.2. Note the eviction hook (`__del__`) and the batching interaction, both of which are directly comparable to **D9** and **D5**.

---

This section helps you understand how to write multiplexed deployment by using the `serve.multiplexed` and `serve.get_multiplexed_model_id` APIs.

## Why model multiplexing?

Model multiplexing is a technique used to efficiently serve multiple models with similar input types from a pool of replicas. Traffic is routed to the corresponding model based on the request header. To serve multiple models with a pool of replicas, model multiplexing optimizes cost and load balances the traffic. This is useful in cases where you might have many models with the same shape but different weights that are sparsely invoked. If any replica for the deployment has the model loaded, incoming traffic for that model (based on request header) will automatically be routed to that replica avoiding unnecessary load time.

## Writing a multiplexed deployment

To write a multiplexed deployment, use the `serve.multiplexed` and `serve.get_multiplexed_model_id` APIs.

Assuming you have multiple PyTorch models inside an AWS S3 bucket with the following structure:

```
s3://my_bucket/1/model.pt
s3://my_bucket/2/model.pt
s3://my_bucket/3/model.pt
s3://my_bucket/4/model.pt
```

Define a multiplexed deployment:

```python
from ray import serve
import aioboto3
import torch
import starlette


@serve.deployment
class ModelInferencer:
    def __init__(self):
        self.bucket_name = "my_bucket"

    @serve.multiplexed(max_num_models_per_replica=3)
    async def get_model(self, model_id: str):
        session = aioboto3.Session()
        async with session.resource("s3") as s3:
            obj = await s3.Bucket(self.bucket_name)
            await obj.download_file(f"{model_id}/model.pt", f"model_{model_id}.pt")
            return torch.load(f"model_{model_id}.pt", weights_only=False)

    async def __call__(self, request: starlette.requests.Request):
        model_id = serve.get_multiplexed_model_id()
        model = await self.get_model(model_id)
        return model.forward(torch.rand(64, 3, 512, 512))


entry = ModelInferencer.bind()
```

> **Note.** The `serve.multiplexed` API also has a `max_num_models_per_replica` parameter. Use it to configure how many models to load in a single replica. If the number of models is larger than `max_num_models_per_replica`, Serve uses the LRU policy to evict the least recently used model.

> **Tip.** This code example uses the PyTorch Model object. You can also define your own model class and use it here. To release resources when the model is evicted, implement the `__del__` method. Ray Serve internally calls the `__del__` method to release resources when the model is evicted.

`serve.get_multiplexed_model_id` retrieves the model ID from the request header. This ID is then passed to the `get_model` function. If the model is not already cached in the replica, Serve loads it from the S3 bucket. Otherwise, the cached model is returned.

> **Note.** Internally, the Serve router uses the model ID in the request header to route traffic to a corresponding replica. If all replicas that have the model are over-subscribed, Ray Serve routes the request to a new replica, which then loads and caches the model from the S3 bucket.

To send a request to a specific model, include the `serve_multiplexed_model_id` field in the request header, and set the value to the model ID to which you want to send the request.

```python
import requests

resp = requests.get(
    "http://localhost:8000", headers={"serve_multiplexed_model_id": str("1")}
)
```

> **Note.** `serve_multiplexed_model_id` is required in the request header, and the value should be the model ID you want to send the request to.
> If the `serve_multiplexed_model_id` is not found in the request header, Serve will treat it as a normal request and route it to a random replica.

After you run the above code, you should see the following lines in the deployment logs:

```
INFO ... multiplex.py:131 - Loading model '1'.
INFO ... replica.py:542 - __CALL__ OK 1005.8ms
```

If you continue to load more models and exceed the `max_num_models_per_replica`, the least recently used model will be evicted and you will see the following lines in the deployment logs:

```
INFO ... multiplex.py:145 - Unloading model '3'.
INFO ... multiplex.py:131 - Loading model '4'.
INFO ... replica.py:542 - __CALL__ OK 1005.7ms
```

You can also send a request to a specific model by using handle `options` API.

```python
obj_ref = handle.options(multiplexed_model_id="1").remote("<your param>")
```

When using model composition, you can send requests from an upstream deployment to a multiplexed deployment using the Serve DeploymentHandle. You need to set the `multiplexed_model_id` in the options. For example:

```python
@serve.deployment
class Downstream:
    def __call__(self):
        return serve.get_multiplexed_model_id()


@serve.deployment
class Upstream:
    def __init__(self, downstream: DeploymentHandle):
        self._h = downstream

    async def __call__(self, request: starlette.requests.Request):
        return await self._h.options(multiplexed_model_id="bar").remote()


serve.run(Upstream.bind(Downstream.bind()))
resp = requests.get("http://localhost:8000")
```

## Configuring model ID matching timeout

When a request arrives with a `serve_multiplexed_model_id`, the Serve router attempts to match it to a replica that already has the model loaded. If no matching replica becomes available within the timeout, the request falls back to the default routing strategy and is sent to any available replica, which then loads the model on demand.

You can configure this timeout using the `RAY_SERVE_MULTIPLEXED_MODEL_ID_MATCHING_TIMEOUT_S` environment variable:

```bash
export RAY_SERVE_MULTIPLEXED_MODEL_ID_MATCHING_TIMEOUT_S=2.0
```

**Default**: `1.0` second. To avoid thundering herd problems when many requests for the same unloaded model arrive concurrently, the actual timeout is randomized between this value and `value * 2` (for example, 1.0–2.0 seconds by default).

Increase this timeout if your models take a long time to load and you prefer to wait for a replica that already has the model loaded. Decrease it if you prefer faster fallback to any available replica.

## Using model multiplexing with batching

You can combine model multiplexing with the `@serve.batch` decorator for efficient batched inference. When you use both features together, Ray Serve automatically splits batches by model ID to ensure each batch contains only requests for the same model. This prevents issues where a single batch would contain requests targeting different models.

```python
from typing import List
from starlette.requests import Request


@serve.deployment(max_ongoing_requests=15)
class BatchedMultiplexModel:
    @serve.multiplexed(max_num_models_per_replica=3)
    async def get_model(self, model_id: str):
        # Load and return your model here
        return model_id

    @serve.batch(max_batch_size=10, batch_wait_timeout_s=0.1)
    async def batched_predict(self, inputs: List[str]) -> List[str]:
        model_id = serve.get_multiplexed_model_id()
        model = await self.get_model(model_id)
        return [f"{model}:{inp}" for inp in inputs]

    async def __call__(self, request: Request):
        input_text = await request.body()
        return await self.batched_predict(input_text.decode())
```

> **Note.** `serve.get_multiplexed_model_id()` works correctly inside functions decorated with `@serve.batch`. Ray Serve guarantees that all requests in a batch have the same `multiplexed_model_id`, so you can safely use this value to load and apply the appropriate model for the entire batch.

---

## tool-swap notes

1. **`max_num_models_per_replica` + LRU eviction is our eviction table**, one level lower: inside a replica process rather than above the container boundary.
2. **`__del__` as the unload hook is weaker than our `unload()` contract.** It relies on refcount-driven finalisation rather than a verified release, and there is no equivalent of **D26**'s post-unload VRAM verification. Our preflight stage 8 checks `nvidia-smi`; Ray documents no such check.
3. **Batch-splitting by model ID is a genuinely good idea** and has no counterpart in our current **D5** design. Worth borrowing if we ever multiplex within a tool.
4. **The matching-timeout behaviour is a routing-level fallback**, comparable to our queue-versus-evict decision, but it resolves toward *load elsewhere* rather than *evict the incumbent*.

# Parallelize requests handling — workers, `worker_index` and device assignment

> **Source:** https://docs.bentoml.com/en/latest/build-with-bentoml/parallelize-requests.html
> **BentoML version at capture:** 1.4.39 (latest on PyPI, published 2026-05-07) · **Captured:** 2026-08-13
> **Relevance to tool-swap:** the worker→device mapping in [`05_RUNTIME_AND_BATCHING.md`](../../05_RUNTIME_AND_BATCHING.md) §5, the `workers` key in [`02_CONFIGURATION.md`](../../02_CONFIGURATION.md) §7, device pinning under **D7** ([`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../../06_LIFECYCLE_TTL_AND_SCHEDULING.md) §7), and the VRAM-multiplication warning the scheduler cannot see. It is also the source of the `worker_index - 1` idiom that [`12_REFERENCE_CODE.md`](../../12_REFERENCE_CODE.md) §5 criticises in R8.
> **Completeness:** complete. Navigation chrome and image markup stripped; prose and code verbatim.

---

BentoML workers enhance the parallel processing capabilities of machine learning models. Under the hood, there are one or multiple workers within a BentoML Service. They are the processes that actually run the code logic within the Service. This design leverages the parallelism of the underlying hardware, whether it's multi-core CPUs or multi-device GPUs.

## Configure workers

When you define a BentoML Service, use the `workers` parameter to set the number of workers. For example, setting `workers=4` launches four worker instances of the Service, each running in its process. Each worker is homogeneous, which means they perform the same tasks.

```python
@bentoml.service(
    workers=4,
)
class MyService:
    # Service implementation
```

The number of workers isn't necessarily equivalent to the number of concurrent requests a BentoML Service can serve in parallel. With optimizations like adaptable batching and continuous batching, each worker can potentially handle many requests simultaneously to enhance the throughput of your Service. To specify the ideal number of concurrent requests for a Service (namely, all workers within the Service), you can configure concurrency.

## Use cases

Workers allow a BentoML Service to effectively utilize underlying hardware accelerators, like CPUs and GPUs, ensuring optimal performance and resource utilization.

The default worker count in BentoML is set to `1`. However, depending on your computational workload and hardware configuration, you might need to adjust this number.

### CPU workloads

Python processes are subject to the Global Interpreter Lock (GIL), a mechanism that prevents multiple native threads from executing Python code at once. This means in a multi-threaded Python program, even if it runs on a multi-core processor, only one thread can execute Python code at a time. This limits the performance of CPU-bound Python programs, making them unable to fully utilize the computational power of multi-core CPUs through multi-threading.

To avoid this and fully leverage multi-core CPUs, you can start multiple workers. However, **be mindful of the memory implications, as each worker will load a copy of the model into memory.** Ensure that your machine's memory can support the cumulative memory requirements of all workers.

You can set the number of worker processes based on the available CPU cores by setting `workers` to `cpu_count`.

```python
@bentoml.service(workers="cpu_count")
class MyService:
    # Service implementation
```

### GPU workloads

In scenarios with multi-device GPUs, allocating specific GPUs to different workers allows each worker to process tasks independently. This can maximize parallel processing, increase throughput, and reduce overall inference time.

You use `worker_index` to represent a worker instance, which is a unique identifier for each worker process within a BentoML Service, **starting from `0`**. This index is used primarily to allocate GPUs among multiple workers. One common use case is to load one model per CUDA device to ensure that each GPU is utilized efficiently and to prevent resource contention between models.

Here is an example:

```python
import bentoml

@bentoml.service(
    resources={"gpu": 2},
    workers=2
)
class MyService:

    def __init__(self):
        import torch

        cuda = torch.device(f"cuda:{bentoml.server_context.worker_index-1}")
        model = models.resnet18(pretrained=True)
        model.to(cuda)
```

This Service dynamically determines the GPU device to use for the model by creating a `torch.device` object. The device ID is set by `bentoml.server_context.worker_index - 1` to allocate a specific GPU to each worker process. **Worker 1 (`worker_index = 1`) uses GPU 0 and worker 2 (`worker_index = 2`) uses GPU 1.**

*(A figure follows upstream showing GPUs allocated to different BentoML workers.)*

When determining which device ID to assign to each worker for tasks such as loading models onto GPUs, **this 1-indexing approach means you need to subtract 1 from the `worker_index` to get the 0-based device ID.** This is because hardware devices like GPUs are usually indexed starting from 0. For more information, see Work with GPUs.

If you want to use multiple GPUs for distributed operations (multiple GPUs for the same worker), PyTorch and TensorFlow offer different methods:

* PyTorch: DataParallel and DistributedDataParallel
* TensorFlow: Distributed training

---

## tool-swap notes

Everything above is BentoML's. Everything below is ours.

### 1. ⚠️ **The page contradicts itself about whether `worker_index` starts at 0 or 1**

Within the same section:

> *"You use `worker_index` to represent a worker instance … **starting from `0`**."*

then, three paragraphs later:

> *"Worker 1 (`worker_index = 1`) uses GPU 0 and worker 2 (`worker_index = 2`) uses GPU 1."*
> *"**this 1-indexing approach** means you need to subtract 1 from the `worker_index` to get the 0-based device ID."*

Both cannot be true. The code example, the worked mapping and the explanatory paragraph all say **1-based**; only the one clause says 0. The weight of evidence is 1-based, and R8's observed behaviour agrees.

**This is not a nitpick.** If it is 1-based and someone codes for 0-based, worker 1 gets `cuda:-1`; if it is 0-based and someone follows the docs' `- 1`, worker 0 gets `cuda:-1`. Either way the first worker fails, or worse, silently wraps.

**Consequences:**
- **M3.5 must observe the actual value**, not trust the page. One log line in a two-worker run settles it permanently. Add to step 5.
- **This vindicates [`05 §5`](../../05_RUNTIME_AND_BATCHING.md:255)'s rule**: *"Read `worker_index` once, map through `TSWAP_DEVICE_LIST`, **log the resulting mapping at startup**, and fail loudly if the list is shorter than the worker count."* Written to defend against off-by-one; the docs are self-contradictory on exactly that point, so the defence is warranted. **Add an explicit bounds check**: a computed index outside `range(len(TSWAP_DEVICE_LIST))` must fail loudly at startup, never reach `torch.device`.

### 2. **Correction: R8's `gpu_id = max(0, worker_index - 1)` was following the documentation.** ⚠️

[`12_REFERENCE_CODE.md`](../../12_REFERENCE_CODE.md:538) and [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../../06_LIFECYCLE_TTL_AND_SCHEDULING.md:227) both criticise this line — *"fragile and off-by-one-prone"*, *"an easy source of off-by-one bugs"*. The vendor documents `bentoml.server_context.worker_index - 1` as **the recommended idiom**, in a code sample, with a diagram.

R8 followed the docs and added a `max(0, …)` guard — arguably *more* defensive than the vendor's own example, which would produce `cuda:-1` for a 0-based index.

The plan's *conclusion* is still right: deriving device identity from a framework-defined worker index is fragile, and our answer — pass an explicit device list and index into it — is better because it does not depend on which convention the framework uses this release. But the *criticism of R8* should be re-worded. The lesson is **"do not build device identity on a framework's indexing convention"**, not "R8 wrote a careless line". The former is a design principle we act on; the latter is a misreading. Proposed amendment in [`INDEX.md`](INDEX.md).

### 3. **VRAM multiplication is confirmed by the vendor** ✅ — and it is a **D7** hazard

> *"be mindful of the memory implications, as **each worker will load a copy of the model into memory**."*

[`05 §5`](../../05_RUNTIME_AND_BATCHING.md:256) says *"Multiple workers multiply VRAM by the worker count. Document loudly; the scheduler does not know (**D7**)."* Confirmed.

The sharp edge is the interaction with **D7** and the shared DGX. Our scheduler pins devices from config and does no VRAM accounting; a tool that raises `workers` from 1 to 4 quadruples its VRAM footprint **with no signal to the scheduler and no change visible in any config the scheduler reads**. On a shared node ([ADR-0002](../../adr/0002-shared-node-soft-unload.md)), that is how a neighbour's job dies.

**Recommendation for M1:** `tswap validate` should **warn** when `workers > 1` on a tool with `devices:` set, naming the multiplication explicitly. It is a two-line rule in the validator and it converts a silent, expensive failure into a sentence at config time. Related to **D28** (`vram_unavailable` is not a tool failure) — this is a way to *cause* that condition, from a config file, without noticing.

### 4. `workers="cpu_count"` — a valid value our config does not accept

`workers` accepts the string `"cpu_count"` as well as an integer. [`02_CONFIGURATION.md`](../../02_CONFIGURATION.md:346) types `workers` as `int`, default `1`.

**Do not add it.** On a shared DGX, `cpu_count` is the *host's* core count as the container sees it, which is very likely far more workers than the tool has VRAM or the node has goodwill for — the same trap as §3, automated. Our `int`-only type is the safer contract. Recorded so the omission is a decision rather than an oversight, and so a future request for it is answered with a reason.

### 5. **Workers vs. concurrency vs. threads — three knobs, and the plan names only one**

The page distinguishes:

- **`workers`** — OS processes, each a full copy of the model;
- **`threads`** — the per-worker `CapacityLimiter` for sync handlers, default 1 ([`health-endpoints-and-lifecycle-source.md`](health-endpoints-and-lifecycle-source.md) §5), *not mentioned on this page at all*;
- **concurrency** — *"the ideal number of concurrent requests for a Service"*, documented under BentoCloud autoscaling, which we do not use.

> *"The number of workers isn't necessarily equivalent to the number of concurrent requests a BentoML Service can serve in parallel. With optimizations like adaptable batching … each worker can potentially handle many requests simultaneously."*

This settles the worry raised in [`adaptive-batching.md`](adaptive-batching.md) §6 and [`health-endpoints-and-lifecycle-source.md`](health-endpoints-and-lifecycle-source.md) §5: **`threads=1` does not prevent batching.** The dispatcher accumulates concurrent requests upstream of the handler; the limiter only serialises the handler call itself, which is what we want anyway ([`05 §5`](../../05_RUNTIME_AND_BATCHING.md:253), *"Exactly one inference at a time per worker"*).

So a single-worker, single-thread tool **can** batch, and M3.5 step 4 should see fewer than 32 handler invocations for 32 concurrent requests without any `threads` tuning. **If it does not, the spike has found something real** — report it rather than reaching for `threads` to make the number look right.

### 6. Multi-GPU-per-worker is explicitly the author's problem — which matches Role C

> *"If you want to use multiple GPUs for distributed operations (multiple GPUs for the same worker), PyTorch and TensorFlow offer different methods."*

BentoML declines to abstract this, pointing at `DataParallel` / `DistributedDataParallel`. That is the same position tool-swap takes in [ADR-0003](../../adr/0003-ray-serve-not-adopted.md) — Role C, *"a tool needing Ray for tensor-parallel sharding uses `base_image:` and imports it"*. Both layers agree that sharding belongs **inside** the tool, not in the serving layer. Useful corroboration: our boundary is where the vendor's is.

### 7. `resources={"gpu": 2}` — the ambiguity [`00_CONTEXT_AND_MOTIVATION.md`](../../00_CONTEXT_AND_MOTIVATION.md) §2.3 flagged, confirmed

The example passes `resources={"gpu": 2}` alongside `workers=2`. [`00 §2.3`](../../00_CONTEXT_AND_MOTIVATION.md:181) notes R8's `gpu: 3` is *"ambiguous: it means '3 GPUs' (a count …) but reads like 'GPU number 3'"*, and resolves it for our config with explicit `devices: [0,1,2]`. The vendor's own example shows a **count**, used together with a separate index-derived device selection — precisely the confusion described.

Our `devices:` list remains the right call, and this is the citation for why. The adapter's job is to translate `devices: [0,1]` into whatever BentoML wants (`resources`) *and* into the `TSWAP_DEVICE_LIST` the handler indexes — **without ever asking the author to do arithmetic** ([`06 §7`](../../06_LIFECYCLE_TTL_AND_SCHEDULING.md:227)).

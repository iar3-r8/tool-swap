# Resource Allocation

> **Source:** https://docs.ray.io/en/latest/serve/resource-allocation.html
> **Ray version at capture:** 2.57.0 · **Captured:** 2026-08-13
> **Relevance to tool-swap:** this is Ray's answer to **D7** (whole-device pinning). It shows GPU assignment lives in `ray_actor_options` — which [`inplace-updates.md`](advanced-guides/inplace-updates.md) classifies as a *code* update forcing a replica restart. It also documents fractional GPUs, which is the sub-allocation model **D7** deliberately declines.

---

This guide helps you configure Ray Serve to:

- Scale your deployments horizontally by specifying a number of replicas
- Scale up and down automatically to react to changing traffic
- Allocate hardware resources (CPUs, GPUs, other accelerators, etc) for each deployment

## Resource management (CPUs, GPUs, accelerators)

You may want to specify a deployment's resource requirements to reserve cluster resources like GPUs or other accelerators. To assign hardware resources per replica, you can pass resource requirements to `ray_actor_options`. By default, each replica reserves one CPU. To learn about options to pass in, take a look at the Resources with Actors guide.

For example, to create a deployment where each replica uses a single GPU:

```python
@serve.deployment(ray_actor_options={"num_gpus": 1})
def func(*args):
    return do_something_with_my_gpu()
```

Or for another type of accelerator such as an HPU:

```python
@serve.deployment(ray_actor_options={"resources": {"HPU": 1}})
def func(*args):
    return do_something_with_my_hpu()
```

### Fractional CPUs and fractional GPUs

The resources specified in `ray_actor_options` can be *fractional*. For example, if you have two models and each doesn't fully saturate a GPU, you might want to have them share a GPU by allocating 0.5 GPUs each.

```python
@serve.deployment(ray_actor_options={"num_gpus": 0.5})
def func_1(*args):
    return do_something_with_my_gpu()

@serve.deployment(ray_actor_options={"num_gpus": 0.5})
def func_2(*args):
    return do_something_with_my_gpu()
```

In this example, each replica of each deployment will be allocated 0.5 GPUs. The same can be done to multiplex over CPUs, using `"num_cpus"`.

### Custom resources, accelerator types, and more

You can also specify custom resources in `ray_actor_options`, for example to ensure that a deployment is scheduled on a specific node:

```python
@serve.deployment(ray_actor_options={"resources": {"custom_resource": 2}})
def func(*args):
    return do_something_with_my_custom_resource()
```

You can also specify accelerator types via the `accelerator_type` parameter in `ray_actor_options`.

Full list of supported options in `ray_actor_options`:

- `accelerator_type`
- `memory`
- `num_cpus`
- `num_gpus`
- `object_store_memory`
- `resources`
- `runtime_env`

## Configuring parallelism with OMP_NUM_THREADS

Deep learning models like PyTorch and Tensorflow often use multithreading when performing inference. The number of CPUs they use is controlled by the `OMP_NUM_THREADS` environment variable. Ray sets `OMP_NUM_THREADS=<num_cpus>` by default. To avoid contention, Ray sets `OMP_NUM_THREADS=1` if `num_cpus` is not specified on the tasks/actors, to reduce contention between actors/tasks which run in a single thread. If you *do* want to enable this parallelism in your Serve deployment, set `num_cpus` (recommended) to the desired value, or manually set the `OMP_NUM_THREADS` environment variable when starting Ray or in your function/class definition.

```bash
OMP_NUM_THREADS=12 ray start --head
OMP_NUM_THREADS=12 ray start --address=$HEAD_NODE_ADDRESS
```

```python
@serve.deployment
class MyDeployment:
    def __init__(self, parallelism: str):
        os.environ["OMP_NUM_THREADS"] = parallelism
        # Download model weights, initialize model, etc.

    def __call__(self):
        pass


serve.run(MyDeployment.bind("12"))
```

> **Note.** Some other libraries may not respect `OMP_NUM_THREADS` and have their own way to configure parallelism. For example, if you're using OpenCV, you'll need to manually set the number of threads using `cv2.setNumThreads(num_threads)` (set to 0 to disable multi-threading).

---

## tool-swap notes

1. **`runtime_env` is a valid `ray_actor_options` key**, which means a runtime environment — and therefore possibly `image_uri` — may be expressible at *deployment* granularity, not only *application* granularity as [`multi-app-container.md`](advanced-guides/multi-app-container.md) presents it. **Unverified**, and worth adding to the open-questions list, because it would slightly change the "one tool = one application" mapping.
2. **Resource requests are declarative reservations, not preemption.** Nothing here expresses "take the GPU from the idle incumbent". A second deployment requesting a GPU that is already reserved waits for capacity — the **D25** objection, in Ray's own resource vocabulary.
3. **Fractional GPUs are an explicit alternative to D7.** Ray's answer to two models on one GPU is `num_gpus: 0.5` each, i.e. co-residency with no memory enforcement. **D7** rejects this for VRAM-safety reasons; the trade is the same one **D28** discusses.
4. **`OMP_NUM_THREADS` defaulting to 1 when `num_cpus` is unset** is a real performance footgun that our own container runtime does not have, since we do not set CPU reservations.

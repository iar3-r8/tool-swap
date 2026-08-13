# Ray Serve Autoscaling

> **Source:** https://docs.ray.io/en/latest/serve/autoscaling-guide.html
> **Ray version at capture:** 2.57.0 · **Captured:** 2026-08-13
> **Relevance to tool-swap:** the `min_replicas: 0` path is the candidate route to **D25** (release an idle incumbent). This page bears directly on open question 9 in [`15_RAY_SERVE_EVALUATION.md`](../../15_RAY_SERVE_EVALUATION.md) §9: it says scale-to-zero costs *"some extra tail latency during upscale"*, which implies a cold start rather than a warm process.

---

Each Ray Serve deployment has one replica by default. This means there is one worker process running the model and serving requests. When traffic to your deployment increases, the single replica can become overloaded.

## Manual Scaling

You can increase the number of replicas by setting a higher value for `num_replicas` in the deployment options through in-place updates. By default, `num_replicas` is 1.

```yaml
# Deploy with a single replica
deployments:
- name: Model
  num_replicas: 1

# Scale up to 10 replicas
deployments:
- name: Model
  num_replicas: 10
```

## Autoscaling Basic Configuration

The Serve autoscaler reacts to traffic spikes by monitoring queue sizes and making scaling decisions to add or remove replicas. Turn on autoscaling for a deployment by setting `num_replicas="auto"`.

```yaml
- name: Model
  num_replicas: auto
```

Setting `num_replicas="auto"` is equivalent to the following deployment configuration:

```yaml
- name: Model
  max_ongoing_requests: 5
  autoscaling_config:
    target_ongoing_requests: 2
    min_replicas: 1
    max_replicas: 100
```

> **Note.** When you set `num_replicas="auto"`, Ray Serve applies the defaults shown above, including `max_replicas: 100`. However, if you configure autoscaling manually without using `num_replicas="auto"`, the base default for `max_replicas` is 1, which means autoscaling won't occur unless you explicitly set a higher value.

- **target_ongoing_requests** is the average number of ongoing requests per replica that the Serve autoscaler tries to ensure. Adjust it based on your request processing length (the longer the requests, the smaller this number should be) as well as your latency objective.
- **max_ongoing_requests** is the maximum number of ongoing requests allowed for a replica. This parameter is not part of the autoscaling config because it's relevant to all deployments, but it's important to set it relative to the target value if you turn on autoscaling.
- **min_replicas** is the minimum number of replicas for the deployment. **Set this to 0 if there are long periods of no traffic and some extra tail latency during upscale is acceptable.** Otherwise, set this to what you think you need for low traffic.
- **max_replicas** is the maximum number of replicas for the deployment. Set this to ~20% higher than what you think you need for peak traffic.

## Basic example

The example runs ResNet50 with `num_replicas="auto"` and `ray_actor_options={"num_cpus": 1}`, load-tested with Locust:

```python
@serve.deployment(
    ray_actor_options={"num_cpus": 1},
    num_replicas="auto",
)
class Model:
    def __init__(self):
        self.resnet50 = (
            models.resnet50(weights=ResNet50_Weights.DEFAULT).eval().to("cpu")
        )
        ...

    async def __call__(self, request: starlette.requests.Request) -> str:
        ...
```

Or through YAML:

```yaml
applications:
  - name: default
    import_path: resnet:app
    deployments:
    - name: Model
      num_replicas: auto
```

Observations from the load test:

- The number of autoscaled replicas is roughly half the number of Locust users over time, as Serve attempts to satisfy `target_ongoing_requests=2`.
- Throughput increases with the number of users and replicas.
- Latency briefly spikes when traffic increases, but otherwise stays relatively steady.

## Ray Serve Autoscaler vs Ray Autoscaler

The Ray Serve Autoscaler is an application-level autoscaler that sits on top of the Ray Autoscaler. The Ray Serve autoscaler asks Ray to start a number of replica actors based on the request demand. If the Ray Autoscaler determines there aren't enough available resources (e.g. CPUs, GPUs) to place these actors, it responds by requesting more Ray nodes. The underlying cloud provider then responds by adding more nodes. Similarly, when Ray Serve scales down and terminates replica Actors, it attempts to make as many nodes idle as possible so the Ray Autoscaler can remove them.

---

## tool-swap notes — bears on open question 9

1. **`min_replicas: 0` is supported and documented**, with the explicit caveat *"some extra tail latency during upscale is acceptable"*. That phrasing describes a **cold start**, not a warm resume — consistent with the reading that at zero replicas the actor process is gone, so imports and CUDA context must be paid again. It does not settle the measurement, but it is evidence against the optimistic reading of open question 9.
2. **Scaling is demand-driven, not contention-driven.** The autoscaler reacts to *queue depth for this deployment*. Nothing in the loop says "another deployment needs the GPU that this idle deployment is holding." That is the **D25** gap, restated in autoscaler terms.
3. **On a single fixed DGX the Ray Autoscaler layer is inert** — there is no cloud provider to add nodes. Scale-down would just free the GPU back to the local resource pool, which is the behaviour we want; the question remains *when* it triggers and how fast the return trip is.
4. **`target_ongoing_requests` + power-of-two-choices routing** is a sane load-balancing model, and richer than anything **R3** requires of us.

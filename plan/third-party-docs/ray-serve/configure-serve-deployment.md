# Configure Ray Serve deployments

> **Source:** https://docs.ray.io/en/latest/serve/configure-serve-deployment.html
> **Ray version at capture:** 2.57.0 · **Captured:** 2026-08-13
> **Relevance to tool-swap:** the full per-deployment knob list, which is what **R4** (simple config) must be judged against. Also the source for `user_config` → `reconfigure()`, `max_queued_requests` back-pressure, and `graceful_shutdown_*` — all of which have counterparts in our own design.

---

Ray Serve default values for deployments are a good starting point for exploration. To further tailor scaling behavior, resource management, or performance tuning, you can configure parameters to alter the default behavior of Ray Serve deployments.

## Configurable parameters

- `name` — Name uniquely identifying this deployment within the application. If not provided, the name of the class or function is used.
- `num_replicas` — Controls the number of replicas to run that handle requests to this deployment. This can be a positive integer, in which case the number of replicas stays constant, or `auto`, in which case the number of replicas will autoscale with a default configuration. Defaults to 1.
- `ray_actor_options` — Options to pass to the Ray Actor decorator, such as resource requirements. Valid options are: `accelerator_type`, `memory`, `num_cpus`, `num_gpus`, `object_store_memory`, `resources`, and `runtime_env`.
- `max_ongoing_requests` — Maximum number of queries that are sent to a replica of this deployment without receiving a response. Defaults to 5 (note the default changed from 100 to 5 in Ray 2.32.0). This may be an important parameter to configure for performance tuning.
- `autoscaling_config` — Parameters to configure autoscaling behavior. If this is set, you can't set `num_replicas` to a number.
- `max_queued_requests` — Maximum number of requests to this deployment that will be queued at each caller (proxy or DeploymentHandle). Once this limit is reached, subsequent requests will raise a BackPressureError (for handles) or return an HTTP 503 status code (for HTTP requests). Defaults to -1 (no limit).
- `user_config` — Config to pass to the reconfigure method of the deployment. This can be updated dynamically without restarting the replicas of the deployment. The user_config must be fully JSON-serializable.
- `health_check_period_s` — Duration between health check calls for the replica. Defaults to 10s. The health check is by default a no-op Actor call to the replica, but you can define your own health check using the `check_health` method in your deployment that raises an exception when unhealthy.
- `health_check_timeout_s` — Duration in seconds that replicas wait for a health check method to return before considering it as failed. Defaults to 30s.
- `graceful_shutdown_wait_loop_s` — Duration that replicas wait until there is no more work to be done before shutting down. Defaults to 2s.
- `graceful_shutdown_timeout_s` — Duration to wait for a replica to gracefully shut down before being forcefully killed. Defaults to 20s.
- `logging_config` — Logging Config for the deployment (e.g. log level, log directory, JSON log format and so on).

## How to specify parameters

You can specify the above mentioned parameters in two locations:

1. In your application code.
2. In the Serve Config file, which is the recommended method for production.

### Through the application code

```python
# File name: configure_serve.py

from ray import serve


@serve.deployment(
    name="Translator",
    num_replicas=2,
    ray_actor_options={"num_cpus": 0.2, "num_gpus": 0},
    max_ongoing_requests=100,
    health_check_period_s=10,
    health_check_timeout_s=30,
    graceful_shutdown_timeout_s=20,
    graceful_shutdown_wait_loop_s=2,
)
class Example:
    ...


example_app = Example.bind()
```

Use the `.options()` method to modify deployment parameters on an already-defined deployment:

```python
example_app = Example.options(
    ray_actor_options={"num_cpus": 0.2, "num_gpus": 0.0}
).bind()
```

### Through the Serve config file

```yaml
applications:
- name: app1
  import_path: configure_serve:translator_app
  deployments:
  - name: Translator
    num_replicas: 2
    max_ongoing_requests: 100
    graceful_shutdown_wait_loop_s: 2.0
    graceful_shutdown_timeout_s: 20.0
    health_check_period_s: 10.0
    health_check_timeout_s: 30.0
    ray_actor_options:
      num_cpus: 0.2
      num_gpus: 0.0
```

### Order of Priority

For each individual parameter, the order of priority is (from highest to lowest):

1. Serve Config file
2. Application code (either through the `@serve.deployment` decorator or through `.options()`)
3. Serve defaults

> **Tip.** Remember that `ray_actor_options` counts as a single setting. The entire `ray_actor_options` dictionary in the config file overrides the entire `ray_actor_options` dictionary from the graph code. If you set individual options within `ray_actor_options` (e.g. `runtime_env`, `num_gpus`, `memory`) in the code but not in the config, Serve still won't use the code settings if the config has a `ray_actor_options` dictionary. It treats these missing options as though the user never set them and uses defaults instead. This dictionary overriding behavior also applies to `user_config` and `autoscaling_config`.

---

## tool-swap notes

1. **`max_queued_requests` → HTTP 503 / `BackPressureError`** is Ray's back-pressure story and is directly comparable to our queue-depth policy.
2. **`check_health` is a user-definable liveness hook**, closer to our readiness contract than KServe's probes were.
3. **The whole-dictionary override rule for `ray_actor_options` is a config sharp edge** — relevant to **R4** and guardrail 10, since our five-line minimum config has no such trap.
4. **Config surface size:** eleven per-deployment parameters plus a nested actor-options dictionary plus an autoscaling block. Larger than our target minimum, though not unreasonably so.

# Monitor Your Application — condensed

> **Source:** https://docs.ray.io/en/latest/serve/monitoring.html
> **Ray version at capture:** 2.57.0 · **Captured:** 2026-08-13
> **This is a condensed capture.** The full page includes a Loki/Grafana walkthrough, an Arize integration, HAProxy metric tables and event-loop internals that are not relevant to us. Retained here: the status vocabulary, the logging model, and **the metrics that would directly instrument Spike D** — multiplexed model load/unload latency, replica startup/initialization/reconfigure latency, and memory profiling.
> **Relevance to tool-swap:** this is the page to judge **R1** against, and it is the strongest single argument in Ray's favour on observability. Several of these metrics are exactly the numbers our open questions ask for.

---

## Ray Dashboard

Accessible at port 8265. Shows the number of deployment replicas running, logs for the Serve controller, deployment replicas and proxies, and the Ray nodes in the cluster. The **Actors view** shows each actor's PID, links to its logs, and whether it is alive or dead.

An example single-deployment application with 2 replicas uses four Ray actors: 1 Serve controller, 1 HTTP proxy, 2 deployment replicas.

## Inspect applications with the Serve CLI

`serve config` gets the latest config file the Ray Cluster received — the application's **goal state**.

`serve status` gets the current status.

**Proxy statuses:** `STARTING`, `HEALTHY`, `UNHEALTHY`, `DRAINING`, `DRAINED`.

**Application statuses:** `NOT_STARTED`, `DEPLOYING`, `RUNNING`, `DEPLOY_FAILED`.

**Deployment statuses:** `UPDATING`, `HEALTHY`, `UNHEALTHY`, `DEPLOY_FAILED`, `UPSCALING`, `DOWNSCALING`.

**Replica states:** `STARTING`, `UPDATING` (*"The replica is undergoing a `reconfigure` update"*), `RECOVERING`, `RUNNING`, `STOPPING`.

```yaml
$ serve status
proxies:
  cef533a072b0f03bf92a6b98cb4eb9153b7b7c7b7f15954feb2f38ec: HEALTHY
applications:
  default:
    status: RUNNING
    message: ''
    last_deployed_time_s: 1694041157.2211847
    deployments:
      Translator:
        status: HEALTHY
        replica_states:
          RUNNING: 1
        message: ''
```

## Get application details in Python

`serve.status()` returns the same information as the CLI, inside a dataclass:

```python
@serve.deployment
def get_healthy_apps() -> List[str]:
    serve_status: ServeStatus = serve.status()
    app_statuses: Dict[str, ApplicationStatusOverview] = serve_status.applications
    return [name for name, s in app_statuses.items() if s.status == "RUNNING"]
```

## Ray logging

Ray Serve uses Python's standard `logging` module with a logger named `"ray.serve"`. Logs are emitted to `stderr` and to disk on each node at `/tmp/ray/session_latest/logs/serve/`, including system logs from the controller and proxy as well as access logs and custom user logs from replicas.

Log messages include the logging level, timestamp, deployment name, replica tag, request ID, route, file name, and line number.

- Log rotation via `RAY_ROTATION_MAX_BYTES` and `RAY_ROTATION_BACKUP_COUNT`.
- `logging_config` (Ray 2.9+) accepts `encoding="JSON"`, `log_level`, `logs_dir`, `enable_access_log`, and can be set at `serve.start`, `serve.run` (application) or `@serve.deployment` level; deployment-level overrides application-level.
- **Custom request IDs** via the `X-Request-ID` header, echoed back in the response and present in both proxy and replica logs.
- **Slow startup warnings**: `RAY_SERVE_SLOW_STARTUP_WARNING_S` (default `30`) *"helping you identify issues such as slow `__init__` methods, long-running `reconfigure` methods, or resource scheduling delays."*

## Built-in metrics — the subset that matters to us

Exposed in Prometheus format on each node.

### Model multiplexing metrics

| Metric | Type | Description |
| --- | --- | --- |
| `ray_serve_multiplexed_model_load_latency_ms` | Histogram | Time taken to load a model. |
| `ray_serve_multiplexed_model_unload_latency_ms` | Histogram | Time taken to unload a model. |
| `ray_serve_num_multiplexed_models` | Gauge | Current number of models loaded on the replica. |
| `ray_serve_multiplexed_models_load_counter_total` | Counter | Total model load operations. |
| `ray_serve_multiplexed_models_unload_counter_total` | Counter | Total model unload operations (evictions). |
| `ray_serve_registered_multiplexed_model_id` | Gauge | Which model IDs are currently loaded (`1` when loaded). |
| `ray_serve_multiplexed_get_model_requests_counter_total` | Counter | Total `get_model()` calls. Compare with load counter for cache hit rate. |

### Replica lifecycle metrics

| Metric | Type | Description |
| --- | --- | --- |
| `ray_serve_replica_startup_latency_ms` | Histogram | **Total time from replica creation to ready state. Includes node provisioning, runtime environment bootstrap (pip install, Docker image pull, etc.), Ray actor scheduling, and actor constructor execution. Useful for debugging slow cold starts.** |
| `ray_serve_replica_initialization_latency_ms` | Histogram | Time for the actor constructor to run (subset of the above). |
| `ray_serve_replica_reconfigure_latency_ms` | Histogram | **Time for a replica to complete reconfiguration.** Includes one control-loop iteration, so very low values may be unreliable. |
| `ray_serve_replica_shutdown_duration_ms` | Histogram | Time from shutdown signal to replica fully stopped. |
| `ray_serve_deployment_replica_starts_total` | Counter | Times the replica has started, including restarts due to failure. |
| `ray_serve_deployment_replica_healthy` | Gauge | Healthy replicas. |
| `ray_serve_health_check_latency_ms` / `ray_serve_health_check_failures_total` | Histogram / Counter | Health check duration and failures. |

Histogram buckets are configurable, notably `RAY_SERVE_MODEL_LOAD_LATENCY_BUCKETS_MS` for the multiplexing histograms and `RAY_SERVE_REPLICA_STARTUP_SHUTDOWN_LATENCY_BUCKETS_MS` for the lifecycle ones. **Bucket boundaries are fixed at startup** and require restarting Serve actors to change.

### Batching metrics

| Metric | Type | Description |
| --- | --- | --- |
| `ray_serve_batch_wait_time_ms` | Histogram | Time requests waited for the batch to fill. High values indicate batch timeout may be too long. |
| `ray_serve_batch_execution_time_ms` | Histogram | Time to execute the batch function. |
| `ray_serve_batch_queue_length` | Gauge | Requests waiting in the batch queue. |
| `ray_serve_batch_utilization_percent` | Histogram | `computed_batch_size / max_batch_size * 100`. Low utilization suggests `batch_wait_timeout_s` is too aggressive or traffic is too low. |
| `ray_serve_actual_batch_size` | Histogram | Computed size of each batch; reports the `batch_size_fn` value when configured. |
| `ray_serve_batches_processed_total` | Counter | Total batches executed. |

### Autoscaling metrics

| Metric | Type | Description |
| --- | --- | --- |
| `ray_serve_autoscaling_target_replicas` | Gauge | Target replicas the autoscaler is trying to reach. |
| `ray_serve_autoscaling_desired_replicas` | Gauge | Raw policy decision *before* applying min/max bounds. |
| `ray_serve_autoscaling_total_requests` | Gauge | Queued + in-flight requests as seen by the autoscaler — the input to the scaling decision. |
| `ray_serve_autoscaling_policy_execution_time_ms` | Gauge | Time to execute the autoscaling policy; `policy_scope` is `deployment` or `application`. |
| `ray_serve_autoscaling_replica_metrics_delay_ms` | Histogram | Time for replica metrics to reach the controller. |

### Routing and processing metrics

Notable ones: `ray_serve_deployment_queued_queries` (requests waiting to be assigned to a replica — *"High values indicate backpressure"*), `ray_serve_num_ongoing_requests_at_replicas`, `ray_serve_request_router_fulfillment_time_ms`, `ray_serve_replica_utilization_percent`, `ray_serve_deployment_processing_latency_ms`, `ray_serve_deployment_error_counter_total`.

Deployment and application status are also exported numerically as `ray_serve_deployment_status` and `ray_serve_application_status` for state-timeline visualisation.

### Metrics export interval

`RAY_SERVE_METRICS_EXPORT_INTERVAL_MS` (default `100`) controls Serve-side batching only. Ray Core's `metrics_report_interval_ms` (default `10000`) controls export to the Prometheus scrape endpoint; both must be lowered for metrics to appear sooner.

## Profiling memory

> Ray provides two useful metrics to track memory usage: `ray_component_rss_bytes` (resident set size) and `ray_component_shared_bytes` (shared memory). Approximate a Serve actor's memory usage by subtracting its shared memory from its resident set size.

For leaks, set `RAY_SERVE_ENABLE_MEMORY_PROFILING=1` and use `memray`; trackers log to `bin` files in `/tmp/ray/session_latest/logs/serve/`.

## Custom application metrics

```python
self.my_counter = metrics.Counter(
    "my_counter",
    description="The number of odd-numbered requests to this deployment.",
    tag_keys=("model",),
)
```

---

## tool-swap notes

1. **This is the strongest R1 evidence in Ray's favour, and it substantially outclasses what our plan proposes to build.** Structured JSON logs, per-request IDs, a status CLI, a Python status API, a dashboard, and a large Prometheus metric surface — all free.
2. **Several metrics are precisely the measurements our open questions demand**, and they mean Spike D can be instrumented with Ray's own telemetry rather than ad-hoc timing:
   - `ray_serve_replica_startup_latency_ms` — *includes Docker image pull and runtime env bootstrap*. This directly measures **open question 6** (cold start for a multi-gigabyte image under Podman) and the 0→1 half of **open question 9**.
   - `ray_serve_replica_reconfigure_latency_ms` — directly measures the cost of the `reconfigure()` soft-unload channel in **open question 8**.
   - `ray_serve_multiplexed_model_load_latency_ms` / `..._unload_latency_ms` — the multiplexing equivalent of our load/unload budget, comparable against [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../../06_LIFECYCLE_TTL_AND_SCHEDULING.md) §6.1.
   - `ray_component_rss_bytes` minus `ray_component_shared_bytes` — measures **open question 7** ("Ray is heavy"), which has been asserted three times in our plan and never quantified. **This makes that claim testable in minutes.**
3. **Still absent: any VRAM metric.** Every memory metric here is host RSS. There is no `ray_serve_replica_gpu_memory_bytes`, so the question **D26** cares about — did the weights actually leave the device — is not answerable from Ray's telemetry. `nvidia-smi` remains necessary, exactly as our preflight stage 8 assumes.
4. **Still absent: any residency vocabulary.** The replica states are `STARTING`/`UPDATING`/`RECOVERING`/`RUNNING`/`STOPPING`. There is no `IDLE_SOFT`, and `UPDATING` (the `reconfigure` state) is a transient, not a steady state. If we built soft unload on `reconfigure()`, **a soft-unloaded replica would report `RUNNING` and look identical to a loaded one** — so the **R1** requirement ("GPU 0 is held by tool X, soft TTL expires in 4 minutes") would still need custom metrics, though `metrics.Counter`/gauge support makes that straightforward.
5. **`RAY_SERVE_SLOW_STARTUP_WARNING_S` explicitly anticipates "long-running `reconfigure` methods"**, which is mild evidence that heavy work inside `reconfigure()` is an expected pattern rather than an abuse of it.

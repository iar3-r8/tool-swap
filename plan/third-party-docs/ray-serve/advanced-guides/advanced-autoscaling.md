# Advanced Ray Serve Autoscaling

> **Source:** https://docs.ray.io/en/latest/serve/advanced-guides/advanced-autoscaling.html
> **Ray version at capture:** 2.57.0 · **Captured:** 2026-08-13
> **Relevance to tool-swap: HIGH — this page was not consulted when [`15_RAY_SERVE_EVALUATION.md`](../../../15_RAY_SERVE_EVALUATION.md) was written, and it changes the picture again.** It documents (a) an explicit confirmation that `min_replicas = 0` incurs **cold start**, (b) `downscale_to_zero_delay_s`, a TTL by another name, (c) **custom autoscaling policies** — a user-supplied Python function run by the controller every 0.1s, and (d) an **external scaling API** — a REST endpoint that sets `target_num_replicas` for any deployment. (c) and (d) are first-class plug-in points for exactly the kind of scheduler tool-swap implements.

---

## Autoscaling config parameters

### [Required] Define the steady state of your system

#### `target_ongoing_requests` [default=2]

> The default changed from 1.0 to 2.0 in Ray 2.32.0.

Serve scales the number of replicas up or down based on the average number of ongoing requests per replica. Serve compares the *actual* number of ongoing requests per replica with the target value and makes upscale or downscale decisions from that.

#### `max_ongoing_requests` [default=5]

> The default changed from 100 to 5 in Ray 2.32.0.

Maximum queue limit that proxies respect when assigning requests to replicas. Set it ~20 to 50% higher than `target_ongoing_requests`.

- Setting it too low can throttle throughput; requests queue at the proxy.
- Setting it too high can lead to imbalanced routing and very high tail latencies during upscale, because most requests may be assigned to existing replicas before new replicas start.

### [Required] Define upper and lower autoscaling limits

- **`min_replicas` [default=1]**: minimum number of replicas. If you anticipate periods of no traffic and want to scale to zero to save cost, set `min_replicas = 0`. **Note that setting `min_replicas = 0` causes higher tail latencies; when you start sending traffic, the deployment scales up, and there will be a cold start time as Serve waits for replicas to be started to serve the request.**
- **`max_replicas` [default=1]**: maximum number of replicas. Ray Serve Autoscaling relies on the Ray Autoscaler to scale up more nodes when currently available cluster resources are not enough.
- **`initial_replicas`**: number of replicas started initially. Defaults to `min_replicas`.

### [Optional] Define how the system reacts to changing traffic

- **`upscale_delay_s` [default=30s]**: how long Serve waits before scaling up. If replicas are *consistently* serving more requests than desired for this many seconds, Serve scales up.
- **`downscale_delay_s` [default=600s]**: how long Serve waits before scaling down. **"If your application initializes slowly, you can increase `downscale_delay_s` to make downscaling happen more infrequently and avoid reinitialization costs when the application needs to upscale again."** This delay applies to all downscaling decisions except the optional 1→0 transition.
- **`downscale_to_zero_delay_s` [Optional]**: how long Serve waits before scaling from one replica down to zero (only applies when `min_replicas = 0`). If unspecified, the 1→0 transition uses `downscale_delay_s`. *"For example, you might set `downscale_delay_s = 300` for regular downscaling but `downscale_to_zero_delay_s = 1800` to wait 30 minutes before scaling to zero, avoiding cold starts for brief periods of inactivity."*
- **`upscaling_factor` [default=1.0]** / **`downscaling_factor` [default=1.0]**: multiplicative gain factors amplifying or moderating each scaling decision. (`upscale_smoothing_factor` / `downscale_smoothing_factor` are the deprecated former names.)
- **`metrics_interval_s` [default=10]**: how often each replica and handle reports ongoing requests to the autoscaler.
- **`look_back_period_s` [default=30]**: window over which the average number of ongoing requests per replica is calculated.
- **`aggregation_function` [default="mean"]**: how metrics are aggregated over `look_back_period_s`. Supported: `"mean"` (time-weighted average), `"max"` (sensitive to spikes), `"min"` (conservative). Only applies in aggregate mode.

## How autoscaling metrics work

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Metrics Pipeline Overview                                               │
├──────────────────────────────────────────────────────────────────────────┤
│  Replicas/Handles         Controller             Autoscaling Policy      │
│  ┌──────────┐             ┌──────────┐           ┌──────────┐            │
│  │ Record   │   Push      │ Receive  │  Decide   │ Policy   │            │
│  │ Metrics  │────────────>│ Metrics  │──────────>│ Runs     │            │
│  │ (10s)    │   (10s)     │          │  (0.1s)   │          │            │
│  └──────────┘             │ Aggregate│           └──────────┘            │
│                           │ (30s)    │                                   │
│                           └──────────┘                                   │
└──────────────────────────────────────────────────────────────────────────┘
```

- **Stage 1 — recording**: ongoing requests (queued + running), every 10s (`metrics_interval_s`), stored locally as a timeseries.
- **Stage 2 — pushing**: every 10s (`RAY_SERVE_REPLICA_AUTOSCALING_METRIC_PUSH_INTERVAL_S`, `RAY_SERVE_HANDLE_AUTOSCALING_METRIC_PUSH_INTERVAL_S`). Both raw timeseries (clipped to `look_back_period_s`) and pre-aggregated metrics are sent.
- **Stage 3 — aggregation**: simple mode (default) sums pre-aggregated simple averages; aggregate mode (experimental, `RAY_SERVE_AGGREGATE_METRICS_AT_CONTROLLER=1`) does time-weighted aggregation on raw timeseries. *"The long-term plan is to deprecate simple mode in favor of aggregate mode."*
- **Stage 4 — policy execution**: **every 0.1s** (`RAY_SERVE_CONTROL_LOOP_INTERVAL_S`), input `AutoscalingContext`, output `(target_replicas, updated_policy_state)`.

### Environment variables

- `RAY_SERVE_CONTROL_LOOP_INTERVAL_S` (default 0.1s): how often the controller runs the autoscaling control loop.
- `RAY_SERVE_RECORD_AUTOSCALING_STATS_TIMEOUT_S` (default 10.0s): maximum time for `record_autoscaling_stats()`.
- `RAY_SERVE_MIN_HANDLE_METRICS_TIMEOUT_S` (default 10.0s): minimum timeout for handle metrics collection.
- `RAY_SERVE_AGGREGATE_METRICS_AT_CONTROLLER` (default false): experimental controller-side aggregation.

## Model composition example

Three deployments — `HeavyLoad` (200ms), `LightLoad` (100ms), `Driver` (fan-out). Attempt 1 with a single fixed `Driver` replica saturates the driver's asyncio event loop: `HeavyLoad` only reaches 65 of the ~100 replicas needed, and `Driver` latency rises from 230 to 400ms. Attempt 2 autoscales `Driver` too (`target_ongoing_requests = 20`, up to 10 replicas); with up to 6 `Driver` replicas, `HeavyLoad` scales to 90+ and latency stays consistent.

Representative config from the example:

```yaml
- name: HeavyLoad
  max_ongoing_requests: 3
  autoscaling_config:
    target_ongoing_requests: 1
    min_replicas: 0
    initial_replicas: 0
    max_replicas: 200
    upscale_delay_s: 3
    downscale_delay_s: 60
    upscaling_factor: 0.3
    downscaling_factor: 0.3
    metrics_interval_s: 2
    look_back_period_s: 10
```

## Troubleshooting guide

- **Unstable replica counts**: use smaller `upscaling_factor` / `downscaling_factor`; match `look_back_period_s` to your delay values.
- **Latency spikes during bursts**: lower `upscale_delay_s`; raise `upscaling_factor`; lower `metrics_interval_s` (always ≤ `upscale_delay_s`); lower `max_ongoing_requests`.
- **Scaling down too quickly**: longer `downscale_delay_s`; smaller `downscaling_factor`.

## Custom autoscaling policies

> **Warning.** Custom autoscaling policies are experimental and may change in future releases.

> Use custom autoscaling policies when you need more control — e.g., scaling on external metrics (CloudWatch, Prometheus), anticipating predictable traffic, or applying business logic that goes beyond queue thresholds.

### Custom policy for deployment

A custom autoscaling policy is a user-provided Python function that takes an `AutoscalingContext` and returns `(target_replicas, policy_state)` for a single deployment.

`AutoscalingContext` provides:

- **Current state**: current replica count and deployment metadata.
- **Built-in metrics**: total requests, queued requests, per-replica counts.
- **Custom metrics**: values your deployment reports via `record_autoscaling_stats()`.
- **Capacity bounds**: `min` / `max` replica limits adjusted for current cluster capacity.
- **Policy state**: a `dict` you can use to persist arbitrary state across control-loop iterations.
- **Timing**: timestamps of the last scale actions and "now".

```python
from datetime import datetime
from typing import Any, Dict
from ray.serve.config import AutoscalingContext


def scheduled_batch_processing_policy(
    ctx: AutoscalingContext,
) -> tuple[int, Dict[str, Any]]:
    current_hour = datetime.now().hour
    if 9 <= current_hour < 17:
        return 2, {"reason": "Business hours"}
    elif 18 <= current_hour < 20:
        return 4, {"reason": "Evening batch processing"}
    else:
        return 1, {"reason": "Off-peak hours"}
```

```python
@serve.deployment(
    autoscaling_config=AutoscalingConfig(
        min_replicas=1,
        max_replicas=12,
        policy=AutoscalingPolicy(
            policy_function="autoscaling_policy:scheduled_batch_processing_policy"
        ),
    ),
)
class BatchProcessingDeployment:
    async def __call__(self) -> str:
        await asyncio.sleep(0.5)
        return "Hello, world!"
```

Policies are defined **per deployment**. The policy function is invoked by the controller every `RAY_SERVE_CONTROL_LOOP_INTERVAL_S` seconds (default **0.1s**).

> **Warning.** Keep policy functions **fast and lightweight**. Slow logic can block the Serve controller and degrade cluster responsiveness.

Ray Serve automatically applies `upscale_delay_s`, `downscale_delay_s`, `downscale_to_zero_delay_s`, `upscaling_factor`, `downscaling_factor`, `min_replicas` and `max_replicas` on top of your policy's "raw" decision.

### Custom metrics

Implement `record_autoscaling_stats()` returning `dict[str, float]`; Serve surfaces the values in `AutoscalingContext` via `ctx.raw_metrics[name]` (per-replica lists) and `ctx.aggregated_metrics[name]` (time-weighted averages).

```python
    def record_autoscaling_stats(self) -> Dict[str, float]:
        cpu_usage = self.process.cpu_percent(interval=0.1)
        memory_info = self.process.memory_full_info()
        system_memory = psutil.virtual_memory().total
        memory_usage = (memory_info.uss / system_memory) * 100
        return {"cpu_usage": cpu_usage, "memory_usage": memory_usage}
```

### Class-based policies

When your policy needs long-running setup — polling an external metrics service, maintaining a persistent connection, background computation — define it as a class, passed via `policy_function` with `policy_kwargs`. Ray Serve instantiates the class once on the controller; `__init__` runs one-time setup and `__call__` runs on every tick.

> **Note.** The instance lives only on the Serve controller and is never serialized after creation, so it's safe to hold non-picklable state such as `asyncio.Task` objects, open connections, or thread pools. `policy_kwargs` values must be JSON-serializable.

### Application level autoscaling

> By default, each deployment autoscales independently. When you have multiple deployments that need to scale in a coordinated way — such as deployments that share backend resources, have dependencies on each other, or need load-aware routing — you can define an **application-level autoscaling policy**. This policy makes scaling decisions for all deployments within an application simultaneously.

An application-level policy takes `dict[DeploymentID, AutoscalingContext]` and returns `(decisions, policy_state)`, where `policy_state` is `Dict[DeploymentID, Dict]`.

```yaml
applications:
  - name: MyApp
    import_path: application_level_autoscaling:app
    autoscaling_policy:
      policy_function: autoscaling_policy:coordinated_scaling_policy
    deployments:
      - name: Preprocessor
        autoscaling_config:
          min_replicas: 1
          max_replicas: 10
      - name: Model
        autoscaling_config:
          min_replicas: 2
          max_replicas: 20
```

> **Note.** When you specify both a deployment-level policy and an application-level policy, the application-level policy takes precedence.

> **Warning — gotchas and limitations.** Ray Serve uses `cloudpickle` to serialize custom policies and does not vendor transitive dependencies; if your policy inherits from a superclass in another module or imports custom packages, those must exist in the target environment. Differences in Python version, `cloudpickle` version, or library versions can affect deserialization.

### External scaling API

> **Warning.** This API is in alpha and may change before becoming stable.

> The external scaling API provides programmatic control over the number of replicas for any deployment. Unlike built-in autoscaling, which scales based on queue depth and ongoing requests, this API allows you to scale based on any external criteria you define.

Enable it per application:

```yaml
applications:
  - name: my-app
    import_path: external_scaler_predictive:app
    external_scaler_enabled: true
    deployments:
      - name: TextProcessor
        num_replicas: 1
```

> **Warning.** External scaling and built-in autoscaling are mutually exclusive for the same application. If you set `external_scaler_enabled: true`, you **must not** configure `autoscaling_config` on any deployment in that application.

The API:

- **Endpoint**: `POST http://localhost:8265/api/v1/applications/{application_name}/deployments/{deployment_name}/scale`
- **Body**: `{"target_num_replicas": <number>}` (schema `ScaleDeploymentRequest`)
- **Read current state**: `GET http://localhost:8265/api/serve/applications/` returns the `ServeInstanceDetails` schema, including `deployments[...]["target_num_replicas"]`.

Important considerations:

- **Idempotent API calls** — safe to call repeatedly with the same target.
- **Interaction with `serve deploy`** — replica counts set via the external scaler stay intact across upgrades.
- **Initial replica count** — comes from `num_replicas`; the external scaler adjusts from there.

---

## tool-swap notes — this page moves the argument again

**This is the most consequential page found in this extraction, and it was not part of the evidence base for [`15_RAY_SERVE_EVALUATION.md`](../../../15_RAY_SERVE_EVALUATION.md).** Four findings:

1. **Open question 9 gets a documentary answer, and it is the pessimistic one.** *"Setting `min_replicas = 0` causes higher tail latencies; when you start sending traffic, the deployment scales up, and there will be a **cold start time**."* Combined with `downscale_delay_s`'s rationale — *"if your application initializes slowly… avoid reinitialization costs when the application needs to upscale again"* — Ray plainly treats zero replicas as **no live process**. So `num_replicas: 0` is *not* a soft unload; it is our hard-stop path. **`reconfigure()` (open question 8) remains the only candidate warm path**, which raises the value of Spike D step 7 further.

2. **`downscale_to_zero_delay_s` is a TTL, under another name**, with the same purpose as our idle timer, and the docs' example value (1800s) is in the same range as our own defaults. Worth citing in [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../../../06_LIFECYCLE_TTL_AND_SCHEDULING.md) as independent convergence. **But it is still a timer, not a preemption trigger** — which is precisely the **D25** objection: *"We don't want to wait for TTL as it could take quite some time."*

3. **Custom and application-level autoscaling policies are a real extension point for our scheduler.** An application-level policy receives every deployment's `AutoscalingContext` — queued requests, per-replica counts, capacity bounds, custom metrics, persisted policy state — and returns target replica counts *for all of them at once*, every 0.1s. **That is structurally a scheduler interface**, and it is much closer to what tool-swap does than anything found so far. Caveats that keep it from being a straight win:
   - Policies are **experimental**.
   - Application-level scope means it coordinates deployments **within one application** — but our design is one tool per *application*, so a cross-tool policy would need every tool in one application, which collides with `image_uri` being per-application. **This is the granularity mismatch of §4.3 reappearing at the policy layer, and it should be verified rather than assumed.**
   - The decision variable is `target_replicas` only. There is no "release your weights but stay alive" decision to return, so the policy can express **allocation**, not **residency**.
   - *"Keep policy functions fast and lightweight. Slow logic can block the Serve controller"* — our eviction ranking is cheap, so this is satisfiable, but a `POST /unload` round trip is not.

4. **The external scaling API is the cleanest integration point of all** — a REST endpoint that sets `target_num_replicas` per deployment, idempotent, surviving `serve deploy`. A tool-swap controller could drive it directly, without writing a Ray-side plug-in. Two catches: it is **alpha**, and it is **mutually exclusive with built-in autoscaling**, so adopting it means owning all scaling decisions — which, notably, is exactly what we want and exactly what our plan already assumes.

**Net effect.** The capability gap narrows to one specific thing: **Ray's scheduling vocabulary tops out at "how many replicas", and has no way to say "stay alive, drop the weights".** Everything else — a policy hook, a control loop, an external API, a TTL, per-tool containers — Ray already has. Open question 8 (`reconfigure()` releasing VRAM) is therefore the single hinge on which the whole evaluation now turns, and Spike D step 7 should be run before any further argument is made either way.

**Also worth adding to the open questions:** can an application-level autoscaling policy see, or act on, deployments belonging to *other* applications? If yes, a Ray-hosted tool-swap scheduler is a genuinely small piece of code and the case for adoption strengthens considerably.

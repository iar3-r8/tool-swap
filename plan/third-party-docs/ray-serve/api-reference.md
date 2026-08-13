# Ray Serve API — condensed reference

> **Source:** https://docs.ray.io/en/latest/serve/api/index.html
> **Ray version at capture:** 2.57.0 · **Captured:** 2026-08-13
> **This is a condensed capture.** The original is an index of ~90 symbol pages; only the names and one-line descriptions are given there. Retained here: the full symbol inventory, the complete CLI surface with flags, and the REST API with an example response. Individual `doc/ray.serve.*.html` pages were **not** fetched.
> **Relevance to tool-swap:** the operational surface **R1** and **R2** are judged against, and the exact control-plane primitives a Ray-based scheduler would drive (`serve.delete`, `PUT /api/serve/applications/`, the external scaling endpoint).

---

## Python API

### Writing applications

| Symbol | Description |
| --- | --- |
| `serve.Deployment` | Class (or function) decorated with the `@serve.deployment` decorator. |
| `serve.Application` | One or more deployments bound with arguments that can be deployed together. |
| `serve.deployment` | Decorator that converts a Python class to a `Deployment`. |
| `serve.ingress` | Wrap a deployment class with an ASGI application for HTTP request parsing. |
| `serve.batch` | Converts a function to asynchronously handle batches. |
| `serve.multiplexed` | Wrap a callable or method used to load multiplexed models in a replica. |

### Deployment handles

`serve.handle.DeploymentHandle`, `DeploymentResponse`, `DeploymentResponseGenerator`, `DeploymentBroadcastResponse`.

> The deprecated `RayServeHandle` and `RayServeSyncHandle` APIs have been fully removed as of Ray 2.10.

### Running applications

| Symbol | Description |
| --- | --- |
| `serve.start` | Start Serve on the cluster. |
| `serve.run` | Run an application and return a handle to its ingress deployment. |
| **`serve.delete`** | **Delete an application by its name.** |
| `serve.status` | Get the status of Serve on the cluster. |
| `serve.shutdown` / `serve.shutdown_async` | Completely shut down Serve on the cluster. |

### Configurations

`ProxyLocation`, **`AutoscalingContext`** (*"Rich context provided to custom autoscaling policies"*), `autoscaling_policy.replica_queue_length_autoscaling_policy` (the default policy), `AggregationFunction` (alpha), `GangPlacementStrategy`, `GangRuntimeFailurePolicy`, `ControllerOptions`, `gRPCOptions`, `HTTPOptions`, `AutoscalingConfig`, **`AutoscalingPolicy`**, `RequestRouterConfig`, `GangSchedulingConfig`, `DeploymentActorConfig`.

### Schemas

`ServeActorDetails`, `ProxyDetails`, `ApplicationStatusOverview`, `ServeStatus`, `DeploymentStatusOverview`, `EncodingType`, `AutoscalingMetricsHealth` (alpha), `AutoscalingStatus` (alpha), `ScalingDecision` (*"One autoscaling decision with minimal provenance"*), `DeploymentAutoscalingDetail`, `ReplicaRank`, `TaskProcessorAdapter`.

### Request Router

`ReplicaID`, `PendingRequest`, `RunningReplica`, `FIFOMixin`, `LocalityMixin`, `MultiplexMixin`, **`RequestRouter`** (*"Abstract interface for a request router"*).

### Advanced APIs

`serve.get_replica_context`, `serve.get_trace_context`, `serve.get_deployment_actor`, `ReplicaContext`, `GangContext`, `serve.get_multiplexed_model_id`, `serve.get_app_handle`, `serve.get_deployment_handle`, `RayServegRPCContext`, `gRPCInputStream`.

Exceptions: `BackPressureError`, `RayServeException`, `RequestCancelledError`, `gRPCStatusError`, `DeploymentUnavailableError`, `ReplicaUnavailableError`.

## Command Line Interface

| Command | Purpose |
| --- | --- |
| `serve build IMPORT_PATHS...` | Generate a structured multi-application config. Flags: `-d/--app-dir`, `-o/--output-path`, `--grpc-servicer-functions`. |
| `serve config` | Get the current configs of Serve applications. Flags: `-a/--address`, `-n/--name`. |
| `serve controller-health` | Display health metrics for the Ray Serve controller — control loop duration statistics, event loop health, component update times, autoscaling metrics latency. Flags: `-a/--address`, `--json`. |
| `serve deploy CONFIG_OR_IMPORT_PATH [ARGS]` | Deploy an application or group of applications. Makes a REST API request to a running cluster. Flags: `--runtime-env`, `--runtime-env-json`, `--working-dir`, `--name`, `-a/--address`. |
| `serve run CONFIG_OR_IMPORT_PATH [ARGS]` | Run and stream logs, blocking by default. Flags: `--runtime-env`, `--runtime-env-json`, `--working-dir`, `-d/--app-dir`, `-a/--address`, `--blocking/--non-blocking`, **`-r/--reload`** (experimental: watches the working directory and automatically redeploys), `--route-prefix`, `--name`. |
| `serve shutdown` | Shut down Serve on the cluster, deleting all applications. Flags: `-a/--address`, `-y/--yes`. |
| `serve start` | Start Serve. Flags: `-a/--address`, `--http-host`, `--http-port`, `--proxy-location` (`Disabled`/`HeadOnly`/`EveryNode`), `--grpc-port`, `--grpc-servicer-functions`. |
| `serve status` | Print status information about all applications. Flags: `-a/--address`, `-n/--name`. |

Application states reported by `serve status`: `NOT_STARTED`, `DEPLOYING`, `RUNNING`, `DEPLOY_FAILED`, `DELETING`. Deployment states: `HEALTHY`, `UNHEALTHY`, `UPDATING`.

## Serve REST API

Exposed at the same port as the Ray Dashboard (`8265` by default).

### `PUT /api/serve/applications/`

> **Declaratively deploys a list of Serve applications. If Serve is already running on the Ray cluster, removes all applications not listed in the new config.**

```json
{
    "applications": [
        {
            "name": "text_app",
            "route_prefix": "/",
            "import_path": "text_ml:app",
            "runtime_env": {
                "working_dir": "https://github.com/ray-project/serve_config_examples/archive/HEAD.zip"
            },
            "deployments": [
                {"name": "Translator", "user_config": {"language": "french"}},
                {"name": "Summarizer"}
            ]
        }
    ]
}
```

### `GET /api/serve/applications/`

Returns cluster-level info and comprehensive details on all applications (`ServeInstanceDetails`). The response includes, per replica:

```json
{
    "actor_name": "SERVE_REPLICA::app1#Translator#oMhRlb",
    "log_file_path": "/serve/deployment_Translator_app1#Translator#oMhRlb.log",
    "replica_id": "app1#Translator#oMhRlb",
    "state": "RUNNING",
    "pid": 29892,
    "start_time_s": 1694042840.577496
}
```

and per deployment the full effective `deployment_config`, including `user_config` and `ray_actor_options`.

### `DELETE /api/serve/applications/`

Shuts down Serve and all applications running on the cluster.

### External scaling endpoint

Documented separately in [`advanced-autoscaling.md`](advanced-guides/advanced-autoscaling.md):
`POST /api/v1/applications/{application_name}/deployments/{deployment_name}/scale` with `{"target_num_replicas": N}`.

## Config schemas

`ServeDeploySchema` (multi-app), `ServeApplicationSchema` (single app), `DeploymentSchema`, `RayActorOptionsSchema`, `HTTPOptionsSchema`, `gRPCOptionsSchema`, `ScaleDeploymentRequest`, plus task-processor schemas (`CeleryAdapterConfig`, `TaskProcessorConfig`, `TaskResult`).

## Response schemas

`ServeInstanceDetails`, `ApplicationDetails`, `DeploymentDetails`, `ReplicaDetails`, `TargetGroup`/`Target` (alpha), `DeploymentNode`/`DeploymentTopology`, `ControllerHealthMetrics`, `DurationStats`, `APIType`, `ApplicationStatus`, `ProxyStatus`.

## Observability

`metrics.Counter`, `metrics.Histogram`, `metrics.Gauge`, `schema.LoggingConfig`.

## LLM API

Builders `build_llm_deployment`, `build_openai_app`; configs `LLMConfig`, `LLMServingArgs`, `ModelLoadingConfig`, `CloudMirrorConfig`, `LoraConfig`; deployments `LLMServer`, `LLMRouter`. **Not relevant to tool-swap** — our zoo is not LLM-centric — but noted for completeness.

---

## tool-swap notes

1. **`serve.delete(name)` is a single-application delete**, confirming that a controller can remove one tool without touching others. This is the primitive a Ray-hosted scheduler would call for hard eviction, and it is the Ray equivalent of our container stop.
2. **`PUT /api/serve/applications/` is declarative and destructive** — *"removes all applications not listed in the new config"*. A scheduler driving this endpoint must always send the **complete** desired set, which makes it a full-state reconciliation API rather than an incremental one. That is workable but a real design constraint, and it is a footgun if any writer ever sends a partial config.
3. **`RequestRouter` is an abstract, documented extension interface**, with `MultiplexMixin` and `LocalityMixin` provided. Combined with the custom autoscaling policy hook, Ray exposes **two** pluggable decision points — routing and scaling — which is more extensibility than [`15_RAY_SERVE_EVALUATION.md`](../../15_RAY_SERVE_EVALUATION.md) credits it with. Neither, however, exposes a *residency* decision.
4. **`serve run --reload`** watches the working directory and redeploys automatically — a genuinely nice authoring loop, relevant to **R2**.
5. **`serve controller-health`** exists specifically to diagnose controller strain *"especially as cluster size increases"*. Directly relevant to open question 10 (driving config updates at request cadence): this is the command that would show whether our cadence is overloading the control plane.
6. **`ScalingDecision` — "one autoscaling decision with minimal provenance"** — suggests scaling decisions are individually observable, which would make a Ray-hosted scheduler auditable in the way **R1** wants.

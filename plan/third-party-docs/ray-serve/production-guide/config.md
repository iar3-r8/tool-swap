# Serve Config Files

> **Source:** https://docs.ray.io/en/latest/serve/production-guide/config.html
> **Ray version at capture:** 2.57.0 · **Captured:** 2026-08-13
> **Relevance to tool-swap:** the authoritative description of the `user_config` → `reconfigure()` contract, which is the candidate soft-unload channel for **D9** (open question 8). It contains the strongest sentence found anywhere in Ray's docs for that reading: *"adjust model weights and versions without restarting the cluster."* Also the full config schema, which **R4** must be judged against.

---

The Serve config is the recommended way to deploy and update your applications in production. **One major benefit is you can dynamically update individual deployment parameters by modifying the Serve config, without needing to redeploy or restart your application.**

```yaml
proxy_location: ...

http_options:
  host: ...
  port: ...
  request_timeout_s: ...
  keep_alive_timeout_s: ...

grpc_options:
  port: ...
  grpc_servicer_functions: ...
  request_timeout_s: ...

logging_config:
  log_level: ...
  logs_dir: ...
  encoding: ...
  enable_access_log: ...

applications:
- name: ...
  route_prefix: ...
  import_path: ...
  runtime_env: ...
  external_scaler_enabled: ...
  deployments:
  - name: ...
    num_replicas: ...
```

## Proxy config

`proxy_location` configures where to run proxies:

- **EveryNode** (default): run a proxy on every node in the cluster that has at least one replica actor.
- **HeadOnly**: only run a single proxy on the head node.
- **Disabled**: don't run proxies at all. Set this if you are only making calls using deployment handles.

Proxy health checks and lifecycle environment variables:

- `RAY_SERVE_PROXY_HEALTH_CHECK_PERIOD_S` (default `10.0`)
- `RAY_SERVE_PROXY_HEALTH_CHECK_TIMEOUT_S` (default `10.0`) — after 3 consecutive failures the controller marks the proxy unhealthy and restarts it.
- `RAY_SERVE_PROXY_READY_CHECK_TIMEOUT_S` (default `5.0`)
- `RAY_SERVE_PROXY_MIN_DRAINING_PERIOD_S` (default `30.0`) — during draining the proxy fails health checks so the load balancer stops routing new traffic, ongoing requests complete normally, and the proxy waits at least this period before terminating.

## HTTP config

> The HTTP config is global to your Ray cluster, and you can't update it during runtime.

- **`host`**: default `0.0.0.0`.
- **`port`**: default `8000`.
- **`request_timeout_s`**: end-to-end timeout for a request before terminating and **retrying at another replica**. By default there is no request timeout.
- **`keep_alive_timeout_s`**: keep-alive timeout for the HTTP proxy.

## gRPC config

> Also global and not runtime-updatable.

- **`port`**: default `9000`.
- **`grpc_servicer_functions`**: list of import paths for gRPC `add_servicer_to_server` functions. Defaults to an empty list, which means the gRPC server isn't started.
- **`request_timeout_s`**.

## Logging config

Global config for controller, proxy and replica logs. Application- and deployment-level logging config take precedence over the global config.

## Application config

Fields per `application`:

- **`name`**: must be unique.
- **`route_prefix`**: defaults to `/`; must be unique.
- **`import_path`**: the path to your top-level Serve deployment. The most minimal config file consists of only an `import_path`.
- **`runtime_env`**: defines the environment the application runs in. The `import_path` must be available *within* the `runtime_env` if specified. The Serve config's `runtime_env` can only use **remote URIs** in its `working_dir` and `py_modules`; it can't use local zip files or directories.
- **`external_scaler_enabled`**: enables the external scaling API, which lets you scale deployments from outside the Ray cluster using a REST API. When enabled, you can't use built-in autoscaling (`autoscaling_config`) for any deployment in this application. Defaults to `False`.
- **`deployments` (optional)**: a list of deployment options overriding the `@serve.deployment` settings in code. If omitted, Serve launches all deployments in the graph with the parameters specified in the code.
- **`args`**: arguments passed to the application builder.

## Example config

```yaml
proxy_location: EveryNode

http_options:
  host: 0.0.0.0
  port: 8000

applications:
- name: default
  route_prefix: /
  import_path: text_ml:app
  runtime_env:
    pip:
      - torch
      - transformers
  deployments:
  - name: Translator
    num_replicas: 1
    user_config:
      language: french
  - name: Summarizer
    num_replicas: 1
```

> **Tip.** Each individual entry in the `deployments` list is optional.

## Auto-generate the Serve config using `serve build`

```bash
$ serve build text_ml:app -o serve_config.yaml
```

> Note that the `runtime_env` field will always be empty when using `serve build` and must be set manually.

## Dynamically change parameters without restarting replicas (`user_config`)

You can use the `user_config` field to supply a structured configuration for your deployment. You can pass arbitrary JSON serializable objects to the YAML configuration. Serve then applies it to all running and future deployment replicas. **The application of user configuration *doesn't* restart the replica.** This deployment continuity means that you can use this field to dynamically:

- **adjust model weights and versions without restarting the cluster.**
- adjust traffic splitting percentage for your model composition graph.
- configure any feature flag, A/B tests, and hyper-parameters for your deployments.

To enable the `user_config` feature, implement a `reconfigure` method that takes a JSON-serializable object as its only argument:

```python
@serve.deployment
class Model:
    def reconfigure(self, config: Dict[str, Any]):
        self.threshold = config["threshold"]
```

If you set the `user_config` when you create the deployment (in the decorator or the Serve config file), Ray Serve calls this `reconfigure` method **right after the deployment's `__init__` method**, and passes the `user_config` in as an argument. You can also trigger the `reconfigure` method by updating your Serve config file with a new `user_config` and reapplying it to the Ray cluster.

```yaml
deployments:
    - name: Model
      user_config:
        threshold: 1.5
```

---

## tool-swap notes — bears directly on open question 8

1. **"Adjust model weights and versions without restarting the cluster" is Ray endorsing the exact pattern Spike D step 7 proposes.** The `reconfigure()` channel is explicitly intended for swapping what a live replica holds, and the replica is explicitly not restarted. This is the strongest documentary support for **D9** being reachable on Ray.
2. **But the docs never claim VRAM is returned.** Loading different weights is not the same as releasing weights and holding none. Whether `reconfigure()` can drive an allocator down to zero resident bytes — and whether the caching allocator actually returns them — is a **PyTorch/CUDA question, not a Ray question**, and Ray's docs cannot answer it. Spike D step 7 with `nvidia-smi` remains necessary. **This is exactly the check D26 already mandates for our own `unload()`.**
3. **`reconfigure()` runs after `__init__`**, so the natural implementation is `__init__` loads nothing and `reconfigure()` decides residency — which is essentially our `IDLE_SOFT` state machine, expressed in Ray's vocabulary.
4. **`request_timeout_s` retries at another replica.** Retry-on-timeout semantics differ from ours; worth noting for the API contract if Ray is ever adopted.
5. **`proxy_location: Disabled`** is interesting: Serve can run with no HTTP layer at all, which would matter only if we used Ray purely as a scheduler behind our own proxy.
6. **Minimal config is genuinely small** — *"The most minimal config file consists of only an `import_path`"* — which softens the **R4** objection somewhat, though the full production config is much larger than our five-line target.

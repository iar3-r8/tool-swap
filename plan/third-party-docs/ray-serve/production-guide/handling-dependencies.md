# Handle Dependencies

> **Source:** https://docs.ray.io/en/latest/serve/production-guide/handling-dependencies.html
> **Ray version at capture:** 2.57.0 · **Captured:** 2026-08-13
> **Relevance to tool-swap: HIGH, and it settles a question raised elsewhere in this extraction.** This page states plainly that Ray Serve supports **per-deployment conflicting Python dependencies** via `ray_actor_options={"runtime_env": ...}`, with a working two-versions-of-`requests` example. Since `image_uri` is a `runtime_env` field, this is strong evidence that **container images can be scoped per deployment, not only per application** — which the multi-app-container guide never says.

---

## Add a runtime environment

The import path (e.g., `text_ml:app`) must be importable by Serve at runtime. When running locally, this path might be in your current working directory. However, when running on a cluster you also need to make sure the path is importable. Build the code into the cluster's container image or use a `runtime_env` with a remote URI that hosts the code in remote storage.

```yaml
import_path: text_ml:app

runtime_env:
    working_dir: "https://github.com/ray-project/serve_config_examples/archive/HEAD.zip"
    pip:
      - torch
      - transformers
```

> **Note.** You can also package a deployment graph into a standalone Python package that you can import using a `PYTHONPATH`. However, the best practice is to use a `runtime_env`, to ensure consistency across all machines in your cluster.

## Dependencies per deployment

> **Ray Serve also supports serving deployments with different (and possibly conflicting) Python dependencies. For example, you can simultaneously serve one deployment that uses legacy Tensorflow 1 and another that uses Tensorflow 2.**
>
> This is supported on Mac OS and Linux using Ray's Runtime environments feature. **As with all other Ray actor options, pass the runtime environment in via `ray_actor_options` in your deployment.** Be sure to first run `pip install "ray[default]"`.

```python
import requests
from starlette.requests import Request

from ray import serve
from ray.serve.handle import DeploymentHandle


@serve.deployment
class Ingress:
    def __init__(
        self, ver_25_handle: DeploymentHandle, ver_26_handle: DeploymentHandle
    ):
        self.ver_25_handle = ver_25_handle
        self.ver_26_handle = ver_26_handle

    async def __call__(self, request: Request):
        if request.query_params["version"] == "25":
            return await self.ver_25_handle.remote()
        else:
            return await self.ver_26_handle.remote()


@serve.deployment
def requests_version():
    return requests.__version__


ver_25 = requests_version.options(
    name="25",
    ray_actor_options={"runtime_env": {"pip": ["requests==2.25.1"]}},
).bind()
ver_26 = requests_version.options(
    name="26",
    ray_actor_options={"runtime_env": {"pip": ["requests==2.26.0"]}},
).bind()

app = Ingress.bind(ver_25, ver_26)
serve.run(app)

assert requests.get("http://127.0.0.1:8000/?version=25").text == "2.25.1"
assert requests.get("http://127.0.0.1:8000/?version=26").text == "2.26.0"
```

> **Tip.** Avoid dynamically installing packages that install from source: these can be slow and use up all resources while installing, leading to problems with the Ray cluster. Consider precompiling such packages in a private repository or Docker image.

The dependencies required in the deployment may be different than the dependencies installed in the driver program. In this case, use a **delayed import** within the class to avoid importing unavailable packages in the driver:

```python
@serve.deployment
class MyDeployment:
    def __call__(self, model_path):
        from my_module import my_model

        self.model = my_model.load(model_path)
```

---

## tool-swap notes — this changes the mapping question

1. **Per-deployment isolation is a documented, first-class feature**, illustrated with exactly our motivating example (*"one deployment that uses legacy Tensorflow 1 and another that uses Tensorflow 2"*). The isolation shown here is a virtualenv, not a container — but the mechanism (`ray_actor_options.runtime_env`) is the same one that carries `image_uri`.
2. **So the "one tool = one application" mapping in [`15_RAY_SERVE_EVALUATION.md`](../../../15_RAY_SERVE_EVALUATION.md) may be unnecessary.** If `ray_actor_options={"runtime_env": {"image_uri": ...}}` works, then **many separately-containerised tools can live inside one Serve application**, and an application-level autoscaling policy — which sees every deployment's context at once and returns replica targets for all of them — becomes a plausible home for our scheduler. **This is now the highest-value thing to verify.** It combines:
   - per-tool container images (**D2**),
   - a single coordinating policy across all of them (our scheduler),
   - `reconfigure()` per deployment for residency (**D9**, if VRAM actually returns).
   That is materially closer to a Ray-native tool-swap than anything the evaluation document currently contemplates.
3. **Counter-evidence to weigh:** the multi-app-container guide states `image_uri` is *"set per Serve application"* and that *"all deployment replicas in the applications start and run in containers with the respective images"*, and that `image_uri` composes only with `config` and `env_vars`. It is entirely possible that `image_uri` is deliberately application-scoped while `pip` is deployment-scoped. **The documentation does not resolve this, and it must be tested rather than argued.**
4. **The delayed-import guidance matches our own tool-authoring advice** and is worth cross-referencing in [`03_TOOL_AUTHORING.md`](../../../03_TOOL_AUTHORING.md).

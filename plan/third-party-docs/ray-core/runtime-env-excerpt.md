# Environment Dependencies / `runtime_env` — focused excerpt

> **Source:** https://docs.ray.io/en/latest/ray-core/handling-dependencies.html
> **Ray version at capture:** 2.57.0 · **Captured:** 2026-08-13
> **This is an excerpt, not a full capture.** The original page is long and largely concerns hosting `working_dir` archives on S3/GitHub, which is irrelevant to us. Retained here: the `runtime_env` scoping rules, the full field list including **`image_uri`**, the version-matching constraints, and the caching/inheritance semantics.
> **Relevance to tool-swap:** this is the authoritative definition of the mechanism **D2** would ride on. It confirms `image_uri` is a `runtime_env` field, that `runtime_env` is settable **per-actor**, and it independently restates the Ray/Python version-matching requirement for `pip`, `uv` and `conda`.

---

## Two ways to supply dependencies

1. **Prepare the environment in advance** — build a container image and specify it via the Cluster Launcher.
2. **Runtime environments** — install dynamically while Ray is running.

> For production usage or non-changing environments, we recommend installing your dependencies into a container image and specifying the image using the Cluster Launcher. For dynamic environments (e.g. for development and experimentation), we recommend using runtime environments.

A **runtime environment** describes the dependencies your Ray application needs to run. It is installed dynamically on the cluster at runtime and cached for future use.

> In contrast with the base cluster environment, a runtime environment will only be active for Ray processes.

## Scopes

There are two primary scopes: **per-job** and **per-task/actor within a job**.

```python
# Invoke a remote task that will run in a specified runtime environment.
f.options(runtime_env=runtime_env).remote()

# Instantiate an actor that will run in a specified runtime environment.
actor = SomeClass.options(runtime_env=runtime_env).remote()

@ray.remote(runtime_env=runtime_env)
def g():
    pass

@ray.remote(runtime_env=runtime_env)
class MyClass:
    pass
```

> This allows you to have actors and tasks running in their own environments, independent of the surrounding environment.

> **Warning.** Ray does not guarantee compatibility between tasks and actors with conflicting runtime environments. For example, if an actor whose runtime environment contains a `pip` package tries to communicate with an actor with a different version of that package, it can lead to unexpected behavior such as unpickling errors.

## API Reference — selected fields

- **`image_uri` (dict)**: **Require a given Docker image. The worker process runs in a container with this image.**
  - Example: `{"image_uri": "anyscale/ray:2.53.0-py310-cpu"}`
  - **Note: `image_uri` is experimental.**

- `working_dir` (str): local directory (≤ 500 MiB), local archive, or remote archive URI. *Setting a local directory per-task or per-actor is currently unsupported; it can only be set per-job.*

- `py_modules` (List[str|module]): modules to make importable in workers. Options (1), (3) and (4) are per-job only.

- `py_executable` (str): the executable used for running the Ray workers, including arguments. Used by the `uv run` integration. **Experimental.**

- `pip` (dict | List[str] | str): pip requirement specifiers, a `requirements.txt` path, or a dict with `packages`, `pip_check`, `pip_version`, `pip_install_options`. *"To use a library like Ray Serve or Ray Tune, you will need to include `"ray[serve]"` or `"ray[tune]"` here. **The Ray version must match that of the cluster.**"*

- `uv` (dict | List[str] | str): **alpha**. The `uv pip` equivalent of the `pip` plugin. Same constraint: *"The Ray version must match that of the cluster."*

- `conda` (dict | str): environment YAML, path to `environment.yml`, or the name of a local conda environment. *"The Python and Ray version must match that of the cluster, so you likely should not specify them manually."* `conda` and `pip` cannot both be specified.

- `env_vars` (Dict[str, str]): environment variables to set. Cluster environment variables remain visible; these override same-named ones by default. `${ENV_VAR}` references allow appending.

- `nsight`: Nsight System Profiler config.

- `config` (dict | `RuntimeEnvConfig`):
  - `setup_timeout_seconds` — timeout of runtime environment creation.
  - `eager_install` (bool, default `True`) — install at `ray.init()` time rather than on first task/actor.

## uv and version matching

> If you are running on a Ray Cluster, the Ray and Python versions of your uv environment must be the same as the Ray and Python versions of your cluster or you will get a version mismatch exception.

The `uv run` integration is implemented via the `py_executable` plugin, which also enables:

> *Applications with heterogeneous dependencies:* Ray supports using a different runtime environment for different tasks or actors. This is useful for deploying different inference engines, models, or microservices in different **Ray Serve deployments** … To implement this, you can specify a different `py_executable` for each of the runtime environments and use uv run with a different `--project` parameter for each.

## Caching and Garbage Collection

Runtime environment resources on each node (conda environments, pip packages, downloaded `working_dir` or `py_modules`) are **cached on the cluster**. Each field has its own cache, defaulting to **10 GB**, tunable via `RAY_RUNTIME_ENV_<field>_CACHE_SIZE_GB`. When the cache size limit is exceeded, resources not currently used by any Actor, Task or Job are deleted.

Cached files live at `/tmp/ray/session_latest/runtime_resources`.

> **How long does it take to install or to load from cache?** The install time usually mostly consists of the time it takes to run `pip install` or `conda create` / `conda activate`, or to upload/download a `working_dir` … This could take seconds or minutes. On the other hand, loading a runtime environment from the cache should be nearly as fast as the ordinary Ray worker startup time, which is on the order of a few seconds. **A new Ray worker is started for every Ray actor or task that requires a new runtime environment.**

## Inheritance

The runtime environment applies to all Tasks and Actors within a Job and all children, unless overridden. On override:

- `env_vars` is **merged** with the parent's.
- **Every other field is overridden**, not merged.

## Relationship to Docker

> They can be used independently or together. A container image can be specified in the Cluster Launcher for large or static dependencies, and runtime environments can be specified per-job or per-task/actor for more dynamic use cases. The runtime environment will inherit packages, files, and environment variables from the container image.

## Debugging

If `runtime_env` cannot be set up, Ray fails to schedule the tasks/actors that require it, and `ray.get` raises `RuntimeEnvSetupError`. Full logs are in `runtime_env_setup-[job_id].log`. Streaming to the driver can be enabled with `RAY_RUNTIME_ENV_LOG_TO_DRIVER_ENABLED=1`.

---

## tool-swap notes

1. **`image_uri` is a per-`runtime_env` field, and `runtime_env` is settable per-actor.** Combined with `runtime_env` being a legal key inside `ray_actor_options` ([`resource-allocation.md`](../ray-serve/resource-allocation.md)), this suggests **images may be specifiable per *deployment*, not only per *application*** as the Serve multi-app-container guide presents. If true, the "one tool = one application" mapping is not forced, and a single application containing many differently-imaged deployments becomes possible — **which would put an application-level autoscaling policy (see [`advanced-autoscaling.md`](../ray-serve/advanced-guides/advanced-autoscaling.md)) in charge of a set of separately-containerised tools.** That combination is close to what tool-swap does. **Unverified, and it should be the first thing Spike D checks**, because it materially changes the evaluation.
2. **The version lockstep is confirmed from a second, independent page**, and applies to `pip`, `uv` and `conda` alike — *"The Ray version must match that of the cluster"*, *"The Python and Ray version must match that of the cluster"*. So §4.2 of [`15_RAY_SERVE_EVALUATION.md`](../../15_RAY_SERVE_EVALUATION.md) is well-sourced and not an artefact of one experimental feature's docs.
3. **"A new Ray worker is started for every Ray actor or task that requires a new runtime environment"** — cold start per environment, consistent with the reading that residency changes cost process starts.
4. **The 10 GB per-field runtime-env cache with LRU-ish eviction is durable local state** on `/tmp/ray`, relevant to guardrail 8.
5. **`image_uri` is labelled experimental here too**, in the core API reference — a second, independent confirmation of that objection.

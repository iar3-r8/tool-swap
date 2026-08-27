"""Thin wrappers over Ray Serve REST API and CLI.

Two separate base URLs are used because the control-plane REST API
(listens on the dashboard port 8265) is distinct from the application
proxy that serves tool traffic (default 8000).

Config files that reference ``${VAR}`` placeholders are rendered
before being passed to the CLI, because Ray uses ``yaml.safe_load``
and does no substitution.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

import requests

# Dashboard port — control-plane REST API.
# This is where /api/serve/applications/, scale endpoints, etc. live.
SERVE_DASHBOARD = "http://localhost:8265"

# Proxy port — application traffic (tool endpoints).
SERVE_PROXY = "http://localhost:8000"

# Working directory for serve deploy.  Ray doesn't inherit the
# caller's PYTHONPATH; it needs --working-dir to find Python modules.
SERVE_WORKING_DIR = os.environ.get(
    "SERVE_DEPLOY_DIR", os.path.join(os.path.dirname(__file__), "..", "apps")
)


def serve_status() -> dict:
    """GET /api/serve/applications/ (dashboard port, not proxy)."""
    resp = requests.get(f"{SERVE_DASHBOARD}/api/serve/applications/", timeout=10)
    return resp.json()


def get_application(name: str) -> dict:
    """GET /api/serve/applications/{name} (dashboard port)."""
    resp = requests.get(
        f"{SERVE_DASHBOARD}/api/serve/applications/{name}", timeout=10
    )
    return resp.json()


def _deployment_runtime_env(deployment: dict) -> dict:
    """Return the deployment's ``ray_actor_options.runtime_env`` (may be empty)."""
    actor_options = deployment.get("ray_actor_options")
    runtime_env = actor_options.get("runtime_env") if actor_options else None
    return runtime_env if isinstance(runtime_env, dict) else {}


def _inject_host_pythonpath(config: dict, work_dir: str) -> None:
    """Inject host PYTHONPATH into host-side deployments only (in place).

    Ray merges application-level and deployment-level ``runtime_env`` with
    ``override_runtime_envs_except_env_vars``
    (``ray/serve/_private/utils.py:370``, invoked from
    ``ray/serve/_private/application_state.py:1865``): top-level keys are
    shallow-merged with the deployment winning, but ``env_vars`` are
    *combined* and the deployment-level value wins per key
    (``utils.py:411``).  Consequence: an application-level
    ``PYTHONPATH`` is inherited by *every* deployment in the app, including
    containerised ones — where it would overwrite the image's own
    ``PYTHONPATH`` (``/home/ray``) and break ``toolkit``/``apps`` imports
    inside the container.  So the injection is per-deployment:

    * deployment without ``image_uri`` (runs on the host): the host paths
      are set in ``ray_actor_options.runtime_env.env_vars.PYTHONPATH``
      (previous behaviour, moved to deployment level);
    * deployment with ``image_uri`` (runs in a container): ``PYTHONPATH``
      is left entirely untouched — the image already sets
      ``ENV PYTHONPATH="${PYTHONPATH}:/home/ray"`` (see the fixture
      Dockerfiles), so there is nothing to inject and no host path may
      leak in.

    Applications without an explicit ``deployments`` list (the builder
    pattern) are left alone: host-side imports are still resolved because
    the raylet inherits ``env.sh``'s exported ``PYTHONPATH``, and nothing
    must leak into the builder's containerised deployments.
    """
    for app in config.get("applications", []):
        for deployment in app.get("deployments", []) or []:
            runtime_env = _deployment_runtime_env(deployment)
            if runtime_env.get("image_uri"):
                # Containerised replica: keep the image's own PYTHONPATH.
                continue
            actor_options = deployment.setdefault("ray_actor_options", {})
            deployment_env = actor_options.setdefault("runtime_env", {})
            env_vars = deployment_env.setdefault("env_vars", {})
            existing_pythonpath = env_vars.get("PYTHONPATH", "")
            # Add both paths, preserving any existing PYTHONPATH
            new_paths = [str(Path(work_dir).resolve()), work_dir]
            if existing_pythonpath:
                new_paths.append(existing_pythonpath)
            env_vars["PYTHONPATH"] = ":".join(new_paths)


def apply_config(config_path: str) -> subprocess.CompletedProcess[str]:
    """Deploy a Serve config file via serve deploy CLI.

    The config file is rendered through :func:`~lib.render_env.render`
    first (expanding ``${VAR}`` and ``${VAR:-default}``), then augmented
    with host ``PYTHONPATH`` entries in the ``runtime_env.env_vars`` of
    every *host-side* deployment (no ``image_uri``), so Ray worker
    subprocesses can find the application modules.  Containerised
    deployments keep the image's own ``PYTHONPATH``.  Finally written
    to a temporary file and deployed via::

      serve deploy <rendered_yaml>

    Note: Ray's serve deploy CLI ignores ``--working-dir`` when deploying
    from a YAML config file (see Ray serve/scripts.py line 239-242).
    Therefore we must inject the working directory into the YAML itself
    as ``runtime_env.env_vars.PYTHONPATH`` (per-deployment, see
    :func:`_inject_host_pythonpath`).
    """
    # Use importlib to load render_env directly — relative imports
    # fail when serve_api.py is imported from a different package
    # context (e.g. step2_verify.py importing scripts.lib.serve_api
    # without the lib package being on sys.path).
    import importlib
    import yaml  # local import

    _lib_dir = os.path.dirname(__file__)
    _render_env_spec = importlib.util.spec_from_file_location(
        "render_env", os.path.join(_lib_dir, "render_env.py")
    )
    _render_env_mod = importlib.util.module_from_spec(_render_env_spec)
    _render_env_spec.loader.exec_module(_render_env_mod)
    render_file = _render_env_mod.render_file

    rendered = render_file(config_path)
    config = yaml.safe_load(rendered)

    # Resolve working directory to an absolute path
    work_dir = str(Path(SERVE_WORKING_DIR).resolve())

    # Inject the host PYTHONPATH into host-side deployments only; containerised
    # (image_uri) deployments keep the image's own PYTHONPATH.
    _inject_host_pythonpath(config, work_dir)

    augmented = yaml.dump(config, default_flow_style=False)

    with tempfile.NamedTemporaryFile(
        mode="wb", suffix=".yaml", delete=False
    ) as tmp:
        tmp.write(augmented.encode("utf-8"))
        tmp_path = tmp.name

    try:
        return subprocess.run(
            ["serve", "deploy", tmp_path],
            capture_output=True, text=True, timeout=120,
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def scale_deployment(app: str, dep: str, target: int) -> dict:
    """POST to the external scaler endpoint (dashboard port).

    Route: POST /api/v1/applications/{application_name}/deployments/{deployment_name}/scale
    Body: {"target_num_replicas": <int>}

    Note: the endpoint requires external_scaler_enabled: true on the
    application; otherwise it returns HTTP 412.
    """
    resp = requests.post(
        f"{SERVE_DASHBOARD}/api/v1/applications/{app}/deployments/{dep}/scale",
        json={"target_num_replicas": target}, timeout=30,
    )
    return resp.json()


def post_introspect(url: str, timeout: float = 60) -> dict:
    """POST introspect to a tool deployment URL (proxy port, not dashboard)."""
    resp = requests.post(
        url, json={"op": "introspect"}, timeout=timeout,
    )
    return resp.json()


def post_predict(url: str, path: str, timeout: float = 120) -> dict:
    """POST predict with a baked-in local file path (proxy port)."""
    resp = requests.post(
        url, json={"op": "predict", "path": path}, timeout=timeout,
    )
    return resp.json()


def cluster_ready(timeout_s: int = 60, interval_s: int = 2) -> bool:
    """Poll the dashboard for a live Ray cluster.

    Returns True once GET /api/ray/version succeeds within timeout_s.
    """
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            resp = requests.get(
                f"{SERVE_DASHBOARD}/api/ray/version", timeout=interval_s
            )
            if resp.status_code == 200:
                return True
        except requests.ConnectionError:
            pass
        time.sleep(interval_s)
    return False

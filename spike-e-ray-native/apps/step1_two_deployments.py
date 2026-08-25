"""Step 1 — Per-deployment image_uri.

One Ray Serve application with **two deployments**, each with a different
``image_uri`` inside ``ray_actor_options.runtime_env``. Tests whether
image_uri can be set per-deployment.

The ``application`` export composes a small ingress deployment that
holds handles to both probes, so the built app graph contains
``Step1Ingress``, ``TorchProbe`` and ``TfProbe``.  The YAML config
(``step1_config.yaml``) overrides the probe deployments'
``ray_actor_options`` (image_uri, num_gpus); the decorator-level
image_uri is the code path under test.

The ingress routes ``/torch`` to ``TorchProbe`` and ``/tf`` to
``TfProbe``, so both tools are reachable on the single Serve proxy
port (Ray Serve has one proxy per cluster; apps are separated by
route prefix, not port).
"""

from __future__ import annotations

import os

import ray.serve as serve
from toolkit.deployments import Tool

# ── Build args (must differ between the two deployments) ──────────
IMAGE_TORCH = os.environ.get("SPIKE_IMAGE_TORCH_URI", "tool_torch:spike")
IMAGE_TF = os.environ.get("SPIKE_IMAGE_TF_URI", "tool_tf:spike")


@serve.deployment(ray_actor_options={"num_gpus": 0})
class Step1Ingress:
    """Ingress routing ``/torch`` and ``/tf`` to the two probes."""

    def __init__(self, torch: TorchProbe, tf: TfProbe) -> None:
        self._torch = torch
        self._tf = tf

    async def __call__(self, request) -> dict:
        """Dispatch to the probe deployment matching the path prefix."""
        path = request.url.path
        if path.startswith("/tf"):
            probe = self._tf
        elif path.startswith("/torch"):
            probe = self._torch
        else:
            return {"error": f"Unknown route: {path}"}
        request_data = await request.json()
        return await probe.remote(request_data)


@serve.deployment(
    ray_actor_options={
        "num_gpus": 0,
        "runtime_env": {"image_uri": IMAGE_TORCH},
    },
)
class TorchProbe(Tool):
    def __init__(self) -> None:
        super().__init__(
            weights_path=os.environ.get(
                "SPIKE_WEIGHTS_PATH", "/opt/spike/weights/ckpt.bin"
            ),
            vram_mb=128,  # minimal VRAM for probes — no GPU workload
        )

    async def __call__(self, request_data: dict) -> dict:
        return await self.handle(request_data)


@serve.deployment(
    ray_actor_options={
        "num_gpus": 0,
        "runtime_env": {"image_uri": IMAGE_TF},
    },
)
class TfProbe(Tool):
    def __init__(self) -> None:
        super().__init__(
            weights_path=os.environ.get(
                "SPIKE_WEIGHTS_PATH", "/opt/spike/weights/ckpt.bin"
            ),
            vram_mb=128,
        )

    async def __call__(self, request_data: dict) -> dict:
        return await self.handle(request_data)


# ── Application ──────────────────────────────────────────────────
# Export a single Application for the YAML config's import_path.
# The ingress holds handles to both probes, so the built graph
# contains all three deployments; the YAML config overrides
# deployment-level settings (image_uri, etc.) on the two probes.
# The decorator-level image_uri is the code-path we are testing:
# if Ray merges decorator + YAML image_uri, the decorator one wins.
application = Step1Ingress.bind(TorchProbe.bind(), TfProbe.bind())

"""Step 1 — Per-deployment image_uri.

One Ray Serve application with **two deployments**, each with a different
``image_uri`` inside ``ray_actor_options.runtime_env``. Tests whether
image_uri can be set per-deployment.

The ``application`` export is a minimal Application that the YAML config
file references via ``import_path``.  The YAML config provides the actual
deployment-level overrides (image_uri, num_gpus).
"""
from __future__ import annotations

import os
import ray.serve as serve
from ray import serve

from toolkit.deployments import Tool

# ── Build args (must differ between the two deployments) ──────────
IMAGE_TORCH = os.environ.get(
    "SPIKE_IMAGE_TORCH_URI", "tool_torch:spike"
)
IMAGE_TF = os.environ.get(
    "SPIKE_IMAGE_TF_URI", "tool_tf:spike"
)


@serve.deployment(
    ray_actor_options={
        "num_gpus": 0,
        "runtime_env": {"image_uri": IMAGE_TORCH},
    },
)
class TorchProbe(Tool):
    def __init__(self):
        super().__init__(
            weights_path=os.environ.get("SPIKE_WEIGHTS_PATH", "/opt/spike/weights/ckpt.bin"),
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
    def __init__(self):
        super().__init__(
            weights_path=os.environ.get("SPIKE_WEIGHTS_PATH", "/opt/spike/weights/ckpt.bin"),
            vram_mb=128,
        )

    async def __call__(self, request_data: dict) -> dict:
        return await self.handle(request_data)


# ── Application ──────────────────────────────────────────────────
# Export a single Application for the YAML config's import_path.
# The YAML config overrides deployment-level settings (image_uri, etc.)
# The decorator-level image_uri is the code-path we are testing:
# if Ray merges decorator + YAML image_uri, the decorator one wins.
application = TorchProbe.bind()

"""Step 3 — Two conflicting tools, one GPU, on-demand start.

Each tool is a **separate application** (not two deployments of one app),
so step 3 is not blocked by step 1's outcome.

Each deployment uses num_gpus: 1 and autoscaling to zero, per the protocol.
"""
from __future__ import annotations

import os
from ray import serve

from toolkit.deployments import Tool

# ── Build args ─────────────────────────────────────────────────
IMAGE_TORCH = os.environ.get("SPIKE_IMAGE_TORCH_URI", "tool_torch:spike")
IMAGE_TF = os.environ.get("SPIKE_IMAGE_TF_URI", "tool_tf:spike")


@serve.deployment(
    ray_actor_options={
        "num_gpus": 1,
        "runtime_env": {"image_uri": IMAGE_TORCH},
    },
    autoscaling_config={
        "min_replicas": 0,
        "max_replicas": 1,
        "downscale_to_zero_delay_s": 60,
    },
)
class ToolTorch(Tool):
    def __init__(self):
        weights_path = os.environ.get(
            "SPIKE_WEIGHTS_PATH", "/opt/spike/weights/ckpt.bin"
        )
        super().__init__(weights_path=weights_path, vram_mb=4096)

    async def __call__(self, request_data: dict) -> dict:
        return await self.handle(request_data)


@serve.deployment(
    ray_actor_options={
        "num_gpus": 1,
        "runtime_env": {"image_uri": IMAGE_TF},
    },
    autoscaling_config={
        "min_replicas": 0,
        "max_replicas": 1,
        "downscale_to_zero_delay_s": 60,
    },
)
class ToolTf(Tool):
    def __init__(self):
        weights_path = os.environ.get(
            "SPIKE_WEIGHTS_PATH", "/opt/spike/weights/ckpt.bin"
        )
        super().__init__(weights_path=weights_path, vram_mb=4096)

    async def __call__(self, request_data: dict) -> dict:
        return await self.handle(request_data)


# ── Applications ───────────────────────────────────────────────
application_torch = serve.Application(ToolTorch.bind())
application_tf = serve.Application(ToolTf.bind())

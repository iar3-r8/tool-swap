"""Step 2 — App builder with baked-in weights.

Tests whether the builder executes in the controller's environment,
not inside a tool image. The fetch-timing half of this step was
removed by §0a (no S3); the remaining question is the structurally
important one.

Exposes:
    def build(args: dict) -> Application

The builder must NOT import torch or tensorflow at module scope.
It reads args["weights_path"], args["framework"], args["image_uri"]
and returns Tool.options(...).bind(...).
"""
from __future__ import annotations

import os
import socket
import sys
from typing import Any

import ray
import ray.serve as serve
from ray import serve

from toolkit.deployments import Tool

# ── Builder-environment banner ──────────────────────────────────
# This is the evidence trail for whether the builder runs in the
# controller's environment or inside a tool image.
# The SPIKE_IMAGE_MARKER being absent means we ran outside any tool image.
print(f"[BUILDER-ENV] python: {sys.executable}")
print(f"[BUILDER-ENV] version: {sys.version}")
print(f"[BUILDER-ENV] image_marker: {os.environ.get('SPIKE_IMAGE_MARKER', '<absent>')}")
print(f"[BUILDER-ENV] hostname: {socket.gethostname()}")
print(f"[BUILDER-ENV] pid: {os.getpid()}")


def _deploy(deployment_cls, args: dict) -> serve.Application:
    """Apply @serve.deployment(options).bind(...) and return a wrapped Application."""
    # Tool is a plain class — apply the decorator programmatically.
    # This returns a Deployment object that has .bind().
    deployment_cls = serve.deployment(
        deployment_cls,
        ray_actor_options={
            "num_gpus": 0,
            "runtime_env": {"image_uri": args.get("image_uri", "")} if args.get("image_uri") else {},
        },
    )
    # .bind() returns the Application directly (not a Deployment).
    return deployment_cls.bind(
        weights_path=args.get(
            "weights_path",
            os.environ.get("SPIKE_WEIGHTS_PATH", "/opt/spike/weights/ckpt.bin"),
        ),
        vram_mb=args.get("vram_mb", 4096),
    )


def build(args: dict) -> serve.Application:
    """Build a Tool application from the given args.

    Args accepted:
        weights_path (str): path to baked-in checkpoint
        framework (str): "torch" or "tensorflow" — for routing purposes
        image_uri (str): container image URI for this tool
        vram_mb (int): VRAM to allocate in __init__

    The builder does NOT import torch or tensorflow. Whether a
    *generic* builder suffices is the question — a builder that
    imported tool code would prejudge the answer.
    """
    return _deploy(Tool, args)


# ── Strict variant (for testing builder environment) ────────────
# This deliberately imports torch at function scope. If the generic
# builder works and this fails, it pins down *where* the builder runs.
def build_strict(args: dict) -> serve.Application:
    """Strict variant: imports torch at function scope.

    This is the controlled failure used to distinguish whether the
    builder runs inside a tool image or in the controller environment.
    """
    # This import will fail if we're running in the tool_tf image
    import torch  # noqa: F401  # pyright: ignore[reportUnusedImport]
    return _deploy(Tool, args)

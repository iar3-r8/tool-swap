"""The ``Tool`` deployment class — shared between tool_torch and tool_tf images.

Each image sets ``SPIKE_IMAGE_MARKER`` and installs its own framework,
so this class can import the correct framework at runtime.

The class exposes four HTTP ops, one per route, JSON in / JSON out:

    { "op": "introspect" }   -> identity report
    { "op": "startup_report" } -> replay __init__ timings
    { "op": "predict", "path": "..." } -> read a baked-in file
    { "op": "vram_report" } -> current VRAM allocation

Each replica also asserts on startup that the conflicting framework
is **not** importable — a fixture integrity check.
"""
from __future__ import annotations

import datetime
import os
import time
import socket
import json
from pathlib import Path
from typing import Any, Optional

from toolkit.localio import read_and_verify
from toolkit.introspect import introspect
from toolkit.vram import VRAMAllocator

try:
    import ray
    import ray.serve as serve
    from ray import serve
except ImportError:
    serve = None  # type: ignore[misc,assignment]
    ray = None  # type: ignore[assignment]


class Tool:
    """Spike E tool deployment. Framework is determined by image at runtime."""

    def __init__(
        self,
        weights_path: str | None = None,
        vram_mb: int = 4096,
    ) -> None:
        # ── Timings ──────────────────────────────────────────────
        self._t0 = time.monotonic()

        # ── Framework detection ──────────────────────────────────
        self._framework = "none"
        self._framework_version = "unknown"

        try:
            import torch
            self._framework = "torch"
            self._framework_version = torch.__version__
        except ImportError:
            pass

        try:
            import tensorflow
            self._framework = "tensorflow"
            self._framework_version = tensorflow.__version__
        except ImportError:
            pass

        # ── Assert conflicting framework is absent ───────────────
        # This is the fixture's own integrity check.
        marker = os.environ.get("SPIKE_IMAGE_MARKER", "")
        if "tool_torch" in marker:
            try:
                import tensorflow  # noqa: F401
                raise RuntimeError(
                    "Fixture integrity failure: tensorflow imported in tool_torch image"
                )
            except ImportError:
                pass  # expected
        elif "tool_tf" in marker:
            try:
                import torch  # noqa: F401
                raise RuntimeError(
                    "Fixture integrity failure: torch imported in tool_tf image"
                )
            except ImportError:
                pass  # expected

        # ── Load baked-in weights ────────────────────────────────
        self._weights_path = weights_path or os.environ.get(
            "SPIKE_WEIGHTS_PATH", "/opt/spike/weights/ckpt.bin"
        )
        t_load_start = time.monotonic()
        self._weights_meta = read_and_verify(self._weights_path)
        self._weights_load_seconds = time.monotonic() - t_load_start

        # ── VRAM allocation ──────────────────────────────────────
        self._vram_mb = vram_mb
        self._vram = VRAMAllocator(vram_mb)
        self._vram_report = self._vram.allocate()

        # ── Startup report ───────────────────────────────────────
        self._init_total_seconds = round(time.monotonic() - self._t0, 6)
        self._started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Hostname from /etc/hostname (not socket.gethostname)
        try:
            self._hostname = Path("/etc/hostname").read_text().strip()
        except Exception:
            self._hostname = socket.gethostname()

    # ── HTTP handlers ──────────────────────────────────────────────

    async def handle(self, request_data: dict[str, Any]) -> dict[str, Any]:
        """Route to the appropriate op handler."""
        op = request_data.get("op", "")
        if op == "introspect":
            return self._op_introspect()
        elif op == "startup_report":
            return self._op_startup_report()
        elif op == "predict":
            return self._op_predict(request_data)
        elif op == "vram_report":
            return self._op_vram_report()
        else:
            return {"error": f"Unknown op: {op}"}

    def _op_introspect(self) -> dict[str, Any]:
        """Identity report — cheap, no GPU access."""
        ray_ver = ray.__version__ if ray else "not_loaded"
        return introspect(image_marker=os.environ.get("SPIKE_IMAGE_MARKER"), ray_version=ray_ver)

    def _op_startup_report(self) -> dict[str, Any]:
        """Replay the __init__ timings."""
        return {
            "weights_path": self._weights_path,
            "weights_bytes": self._weights_meta["size_bytes"],
            "weights_sha256": self._weights_meta["sha256"],
            "weights_load_seconds": self._weights_load_seconds,
            "init_total_seconds": self._init_total_seconds,
            "vram_allocated_mb": self._vram_report.get("allocated_mb", 0),
            "framework": self._framework,
            "framework_version": self._framework_version,
            "image_marker": os.environ.get("SPIKE_IMAGE_MARKER", "<absent>"),
            "hostname": self._hostname,
            "pid": os.getpid(),
            "started_at": self._started_at,
            "replica_id": os.environ.get("RAYLET_NODE_ID", "<unknown>")[:8],
        }

    def _op_predict(self, request_data: dict[str, Any]) -> dict[str, Any]:
        """Read a baked-in file, verify against sidecar .meta.json."""
        path = request_data.get("path", os.environ.get("SPIKE_PAYLOAD_PATH", "/opt/spike/data/payload.bin"))
        t_start = time.monotonic()
        meta = read_and_verify(path)
        meta["read_seconds"] = round(time.monotonic() - t_start, 6)
        meta["image_marker"] = os.environ.get("SPIKE_IMAGE_MARKER", "<absent>")
        return meta

    def _op_vram_report(self) -> dict[str, Any]:
        """Current allocation as the framework sees it."""
        return self._vram.report()

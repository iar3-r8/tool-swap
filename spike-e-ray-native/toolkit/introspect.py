"""System and environment introspection.

Returns a dict with identity and environment details.
Used by the ``introspect`` op — must be cheap and must NOT touch the GPU.
"""
from __future__ import annotations

import os
import platform
import socket
import sys
from pathlib import Path
from typing import Any


def introspect(image_marker: str | None = None, ray_version: str | None = None) -> dict[str, Any]:
    """Return process identity and environment.

    Key fields:
        python_version, sys_executable, framework (inferred from marker),
        image_marker, hostname, pid, os_release, cuda_visible_devices,
        ray_version.

    Does NOT touch the GPU — used by step 5's latency measurements.
    """
    # Read /etc/hostname (not socket.gethostname) — §3 of protocol names the file
    try:
        hostname = Path("/etc/hostname").read_text().strip()
    except Exception:
        hostname = socket.gethostname()

    # CUDA_VISIBLE_DEVICES as seen inside the container
    cuda = os.environ.get("CUDA_VISIBLE_DEVICES", "<not set>")

    result: dict[str, Any] = {
        "python_version": platform.python_version(),
        "sys_executable": sys.executable,
        "image_marker": image_marker or os.environ.get("SPIKE_IMAGE_MARKER", "<absent>"),
        "hostname": hostname,
        "pid": os.getpid(),
        "os_release": platform.platform(),
        "cuda_visible_devices": cuda,
        "ray_version": ray_version or "<not loaded>",
    }

    # Try to detect which framework is importable
    try:
        import torch  # noqa: F401
        result["framework"] = "torch"
    except ImportError:
        result["framework"] = "none"

    try:
        import tensorflow  # noqa: F401
        result["framework"] = "tensorflow"
    except ImportError:
        pass  # stays "none" or torch if detected above

    try:
        import torch
        result["framework_version"] = torch.__version__
    except ImportError:
        try:
            import tensorflow
            result["framework_version"] = tensorflow.__version__
        except ImportError:
            result["framework_version"] = "none"

    return result

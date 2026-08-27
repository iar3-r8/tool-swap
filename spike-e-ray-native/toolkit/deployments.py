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

**Deployment-boundary rule (D27, empirical).** Ray Serve pickles op
results between deployments, so the receiver must be able to import
every type the sender serialised. A tool's whole point is that it has
dependencies the caller lacks: ``torch.__version__`` (a
``torch.torch_version.TorchVersion``, not a ``str``) in the step-1
TorchProbe reply made the host ingress — which has no torch — die
with an opaque ``RaySystemError: No module named 'torch'`` in *its*
log while the tool itself reported success. Every value returned by
an op must therefore be plain data; :meth:`Tool.handle` enforces it
with :func:`_is_plain_data`.
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

        # str(): see the deployment-boundary rule in the module docstring —
        # torch.__version__ is a TorchVersion instance, not a str, and the
        # caller cannot import it (D27).
        try:
            import torch
            self._framework = "torch"
            self._framework_version = str(torch.__version__)
        except ImportError:
            pass

        try:
            import tensorflow
            self._framework = "tensorflow"
            self._framework_version = str(tensorflow.__version__)
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
        """Route to the appropriate op handler, guarding the reply.

        Every op response is checked against the deployment-boundary
        rule before it leaves this deployment. A non-plain value is
        reported as a structured ``{"error": ...}`` payload (plus a log
        line on the tool side) rather than raised: the error then
        travels as plain data and lands in the *response* — visible in
        the ingress and the client log — instead of surfacing as an
        opaque ``RaySystemError`` in the caller's log, which is exactly
        how the D27 TorchVersion incident hid itself.
        """
        op = request_data.get("op", "")
        if op == "introspect":
            result = self._op_introspect()
        elif op == "startup_report":
            result = self._op_startup_report()
        elif op == "predict":
            result = self._op_predict(request_data)
        elif op == "vram_report":
            result = self._op_vram_report()
        else:
            return {"error": f"Unknown op: {op}"}
        if not _is_plain_data(result):
            import logging
            logging.getLogger(__name__).error(
                "op %r returned a non-plain value — refusing to cross "
                "the deployment boundary: %s",
                op,
                _plain_violation(result),
            )
            return {"error": f"op {op!r} returned a non-plain value: "
                             f"{_plain_violation(result)}"}
        return result

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


# ── Deployment-boundary guard ──────────────────────────────────────
#
# Ray Serve serialises op results between deployments with pickle. The
# receiver therefore has to be able to *import* every type the sender
# returned. The tool's whole point is that it has dependencies the
# caller lacks (see the module docstring), so a value that is not
# plain data will break on the other side of the boundary, not here.
# These helpers make that a local, loud, named failure instead of an
# opaque RaySystemError in someone else's log.

#: Types that are safe to pickle across a deployment boundary.
#: ``str`` covers ``bool`` via the isinstance checks below (bool is a
#: subclass of int); ``bytes`` is deliberately in the set — large byte
#: payloads are expected and the check never copies or hashes them.
_PLAIN_TYPES = (str, int, float, bytes)


def _is_plain_data(value: Any) -> bool:
   """Return True if *value* is plain data that is safe to pickle.

   Plain data is ``None``, ``str``, ``bool``, ``int``, ``float``,
   ``bytes``, and dicts/lists whose values are themselves plain data
   (recursively). Anything else — in particular any class instance
   from a framework the receiver cannot import — is rejected.

   The check is cheap on the request path: it only walks dict keys
   and list items and never deep-copies or reads ``bytes`` payloads.

   Args:
       value: The value to check (typically a whole op response).

   Returns:
       True if every nested value is a plain-data type.
   """
   if value is None or isinstance(value, _PLAIN_TYPES):
       return True
   if isinstance(value, dict):
       return all(_is_plain_data(v) for v in value.values())
   if isinstance(value, (list, tuple)):
       return all(_is_plain_data(v) for v in value)
   return False


def _plain_violation(value: Any) -> str | None:
   """Describe the first non-plain value found, or None if none.

   The message names the key path (e.g. ``framework_version`` or
   ``report[0].handle``) and the offending type's fully-qualified
   name, so the failure is attributable without a receiver-side log.

   Args:
       value: The value to scan.

   Returns:
       A human-readable description, or None when the value is plain.
   """
   return _find_violation(value, "$")


def _find_violation(value: Any, path: str) -> str | None:
   """Recursively locate the first non-plain value under *path*.

   Args:
       value: The value to inspect.
       path: Key path for the error message (``$`` at the root).

   Returns:
       A description of the first violation, or None if clean.
   """
   if value is None or isinstance(value, _PLAIN_TYPES):
       return None
   if isinstance(value, dict):
       for key, item in value.items():
           child = _find_violation(item, f"{path}.{key}")
           if child is not None:
               return child
       return None
   if isinstance(value, (list, tuple)):
       for i, item in enumerate(value):
           child = _find_violation(item, f"{path}[{i}]")
           if child is not None:
               return child
       return None
   return (
       f"{path} has type {type(value).__module__}."
       f"{type(value).__name__} — only plain data (str, int, float, "
       "bool, bytes, list, dict, None) may cross the deployment "
       "boundary; the receiver may not be able to import this type"
   )

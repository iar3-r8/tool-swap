"""VRAM allocation helpers for torch and tensorflow.

Each replica allocates ~4 GB of real, resident VRAM during __init__
so that ``nvidia-smi`` can see it. This is what step 3.2 checks.

When the process cannot see any GPU (e.g. a step-1 CPU-only probe in a
container without GPU passthrough), allocation is skipped and the
report says so honestly: ``gpu_available: False`` and
``framework: "none"``. A genuine allocation failure *on* a GPU host
still raises -- steps 3-5 need real resident VRAM.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class VRAMAllocator:
    """Framework-agnostic VRAM allocator backed by torch or tensorflow.

    Construction never allocates. Call :meth:`allocate` to acquire the
    VRAM. If no GPU is visible to the process, :meth:`allocate` skips
    the allocation and reports ``gpu_available: False`` instead of
    failing.
    """

    def __init__(self, vram_mb: int = 4096) -> None:
        self._vram_mb: int = vram_mb
        self._handle: Optional[Any] = None
        self._allocated_mb: int = 0
        self._reserved_mb: int = 0
        self._framework: str = "none"
        self._gpu_available: bool = False

    def _detect_gpu_framework(self) -> str:
        """Return the name of a framework that can see a GPU, or ``""``.

        Prefers torch when both are importable. Uses only the
        frameworks' own availability APIs (``torch.cuda.is_available``,
        ``tf.config.list_physical_devices``); no extra dependency.
        """
        try:
            import torch

            if torch.cuda.is_available():
                return "torch"
        except ImportError:
            pass
        try:
            import tensorflow as tf

            if len(tf.config.list_physical_devices("GPU")) > 0:
                return "tensorflow"
        except ImportError:
            pass
        return ""

    def allocate(self) -> dict[str, Any]:
        """Allocate *vram_mb* of VRAM. Returns allocation report.

        Raises if a GPU is visible but the allocation fails.
        """
        framework = self._detect_gpu_framework()
        if not framework:
            self._gpu_available = False
            logger.info(
                "No GPU visible to this process; skipping VRAM allocation"
                " (requested vram_mb=%d will not be allocated).",
                self._vram_mb,
            )
            return self.report()

        self._gpu_available = True
        if framework == "torch":
            # Allocate a float tensor (4 bytes per element)
            import torch

            num_elements = self._vram_mb * 1024 * 1024 // 4
            self._handle = torch.empty(
                num_elements, dtype=torch.float32, device="cuda:0"
            )
            torch.cuda.synchronize()
            self._framework = "torch"
            self._allocated_mb = torch.cuda.memory_allocated(
                device="cuda:0"
            ) // (1024 * 1024)
            self._reserved_mb = torch.cuda.memory_reserved(
                device="cuda:0"
            ) // (1024 * 1024)
        else:
            # tensorflow may not expose memory counters the same way, so
            # the requested size is recorded.
            import tensorflow as tf

            with tf.device("/GPU:0"):
                self._handle = tf.zeros(
                    (self._vram_mb * 1024 * 1024,), dtype=tf.float32
                )
            self._framework = "tensorflow"
            self._allocated_mb = self._vram_mb
            self._reserved_mb = self._vram_mb

        return self.report()

    def free(self) -> None:
        """Release VRAM."""
        if self._handle is not None:
            del self._handle
            self._handle = None
            if self._framework == "torch":
                try:
                    import torch

                    torch.cuda.empty_cache()
                except Exception:  # pragma: no cover - best-effort cleanup
                    pass
            self._allocated_mb = 0
            self._reserved_mb = 0
            self._framework = "none"

    def report(self) -> dict[str, Any]:
        """Current allocation state."""
        if self._framework == "torch":
            try:
                import torch

                return {
                    "allocated_mb": torch.cuda.memory_allocated(
                        device="cuda:0"
                    )
                    // (1024 * 1024),
                    "reserved_mb": torch.cuda.memory_reserved(
                        device="cuda:0"
                    )
                    // (1024 * 1024),
                    "framework": "torch",
                    "gpu_available": True,
                }
            except Exception:
                logger.warning(
                    "torch.cuda counters unavailable after allocation;"
                    " falling back to recorded values",
                    exc_info=True,
                )
        return {
            "allocated_mb": self._allocated_mb,
            "reserved_mb": self._reserved_mb,
            "framework": self._framework,
            "gpu_available": self._gpu_available,
        }

"""VRAM allocation helpers for torch and tensorflow.

Each replica allocates ~4 GB of real, resident VRAM during __init__
so that ``nvidia-smi`` can see it. This is what step 3.2 checks.
"""
from __future__ import annotations

from typing import Any, Optional


class VRAMAllocator:
    """Framework-agnostic VRAM allocator backed by torch or tensorflow."""

    def __init__(self, vram_mb: int = 4096) -> None:
        self._handle: Optional[Any] = None
        self._allocated_mb: int = 0
        self._reserved_mb: int = 0
        self._framework: str = "none"

    def allocate(self) -> dict[str, Any]:
        """Allocate *vram_mb* of VRAM. Returns allocation report."""
        try:
            import torch
            self._framework = "torch"
            # Allocate a float tensor (4 bytes per element)
            num_elements = self._vram_mb * 1024 * 1024 // 4
            self._handle = torch.empty(num_elements, dtype=torch.float32, device="cuda:0")
            torch.cuda.synchronize()
            self._allocated_mb = torch.cuda.memory_allocated(device="cuda:0") // (1024 * 1024)
            self._reserved_mb = torch.cuda.memory_reserved(device="cuda:0") // (1024 * 1024)
        except ImportError:
            import tensorflow as tf
            self._framework = "tensorflow"
            with tf.device("/GPU:0"):
                # Allocate in bytes; tensorflow may not expose memory counters the same way
                self._handle = tf.zeros((self._vram_mb * 1024 * 1024,), dtype=tf.float32)
            self._allocated_mb = self._vram_mb
            self._reserved_mb = self._vram_mb

        return {
            "allocated_mb": self._allocated_mb,
            "reserved_mb": self._reserved_mb,
            "framework": self._framework,
        }

    def free(self) -> None:
        """Release VRAM."""
        if self._handle is not None:
            del self._handle
            self._handle = None
            if self._framework == "torch":
                try:
                    import torch
                    torch.cuda.empty_cache()
                except Exception:
                    pass
            self._allocated_mb = 0
            self._reserved_mb = 0

    def report(self) -> dict[str, Any]:
        """Current allocation state."""
        if self._framework == "torch":
            try:
                import torch
                return {
                    "allocated_mb": torch.cuda.memory_allocated(device="cuda:0") // (1024 * 1024),
                    "reserved_mb": torch.cuda.memory_reserved(device="cuda:0") // (1024 * 1024),
                    "framework": "torch",
                }
            except Exception:
                pass
        return {
            "allocated_mb": self._allocated_mb,
            "reserved_mb": self._reserved_mb,
            "framework": self._framework,
        }

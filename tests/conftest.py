"""Shared test fixtures for the tool-swap test suite.

Fakes (FakeBackend, FakeProbe, ManualClock) land here once M2 provides them.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repo root and src/ are on sys.path so that tests can import
# ``tool_swap`` (from src/) and ``tests.conftest`` (from repo root).
# This guard makes ``pytest tests/unit/test_clock.py`` and IDE runners work
# even when pyproject.toml's ``pythonpath`` is not picked up.
_ROOT = Path(__file__).resolve().parent.parent  # repo root
for _p in (str(_ROOT / "src"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
del _ROOT, _p

import asyncio
import time
from typing import runtime_checkable, TYPE_CHECKING

import pytest

pytest_plugins = []


# ---------------------------------------------------------------------------
# ManualClock stub for behaviour 3 tests
# ---------------------------------------------------------------------------
# This minimal stub exists so that ``isinstance(ManualClock(), Clock)``
# exercises the runtime_checkable protocol without requiring the full
# implementation (which lands in behaviour 4).

if TYPE_CHECKING:
    from typing import Protocol
else:
    Protocol = object  # fallback — not used at runtime by this stub


class ManualClock:
    """Minimal ManualClock stub satisfying the Clock protocol.

    This is NOT the real implementation — just enough to verify that
    ``isinstance(ManualClock(), Clock)`` works once the protocol is
    ``@runtime_checkable``.
    """

    def now(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("sleep duration must be non-negative")
        await asyncio.sleep(seconds)

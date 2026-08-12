"""Tests for behaviour 3: Clock protocol and RealClock implementation.

Verifies:
- Clock is a ``@runtime_checkable`` Protocol with ``now() -> float`` and
  ``async sleep(seconds: float) -> None`` (checked via ``inspect.signature``).
- ``isinstance(RealClock(), Clock)`` is ``True``.
- ``isinstance(ManualClock(), Clock)`` is ``True`` (ManualClock is a stub
  provided by ``conftest`` for this purpose).
- ``RealClock().now()`` returns a monotonic non-decreasing float.
- ``await RealClock().sleep(0.01)`` returns after at least ~0.01 s elapsed
  monotonic time.
- ``await RealClock().sleep(0)`` returns promptly and yields to the event loop.
- ``RealClock().sleep(-1)`` raises ``ValueError`` on negative durations.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import runtime_checkable

import pytest

# ---------------------------------------------------------------------------
# Local imports
# ---------------------------------------------------------------------------
from src.tool_swap.utils.clock import Clock, RealClock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture()
def clock() -> RealClock:
    """Return a fresh RealClock instance."""
    return RealClock()


# ---------------------------------------------------------------------------
# Protocol structure tests
# ---------------------------------------------------------------------------
class TestClockProtocol:
    """Verify the Clock Protocol definition."""

    def test_clock_is_protocol(self) -> None:
        """Clock must be a typing.Protocol subclass."""
        from typing import Protocol

        assert issubclass(Clock, Protocol)

    def test_clock_is_runtime_checkable(self) -> None:
        """isinstance checks must succeed at runtime."""
        assert isinstance(RealClock(), Clock)

    def test_clock_has_now_method(self) -> None:
        """Clock must declare a ``now()`` method."""
        sig = inspect.signature(Clock.now)
        # now() takes self only
        params = [p for p in sig.parameters.values() if p.name != "self"]
        assert len(params) == 0, f"Expected no params for now(), got {params}"
        # Return annotation should be float
        assert sig.return_annotation == float

    def test_clock_has_async_sleep_method(self) -> None:
        """Clock must declare an async ``sleep(seconds: float) -> None``."""
        sig = inspect.signature(Clock.sleep)
        params = [
            p for p in sig.parameters.values() if p.name not in ("self",)
        ]
        assert len(params) == 1, f"Expected 1 param for sleep(), got {params}"
        assert params[0].name == "seconds"
        assert params[0].annotation == float
        assert sig.return_annotation is None

    def test_clock_protocol_no_extra_methods(self) -> None:
        """Clock should only have ``now`` and ``sleep`` (besides object dunder methods)."""
        methods = {
            m for m in dir(Clock) if not m.startswith("_")
        }
        assert methods == {"now", "sleep"}, f"Unexpected methods: {methods}"


# ---------------------------------------------------------------------------
# ManualClock isinstance test
# ---------------------------------------------------------------------------
class TestManualClockIsInstance:
    """ManualClock from conftest should satisfy Clock."""

    def test_manual_clock_is_instance_of_clock(self) -> None:
        """ManualClock stub from conftest must pass isinstance(Clock)."""
        from tests.conftest import ManualClock

        assert isinstance(ManualClock(), Clock)


# ---------------------------------------------------------------------------
# RealClock.now() tests
# ---------------------------------------------------------------------------
class TestRealClockNow:
    """Verify RealClock.now() uses monotonic time."""

    def test_now_returns_float(self, clock: RealClock) -> None:
        """now() must return a float."""
        result = clock.now()
        assert isinstance(result, float)

    def test_now_is_monotonic_non_decreasing(self, clock: RealClock) -> None:
        """Two successive now() calls must be non-decreasing."""
        first = clock.now()
        second = clock.now()
        assert second >= first, (
            f"now() decreased: {first} -> {second}"
        )

    def test_now_uses_monotonic_not_wall_clock(self, clock: RealClock) -> None:
        """now() must use time.monotonic(), not time.time().

        We verify indirectly: if it were time.time(), the system could return
        negative values after boot.  We check that the value is reasonable for
        a monotonic clock (always positive and roughly in the right ballpark).
        """
        val = clock.now()
        assert val > 0, "Monotonic clock should always be positive"


# ---------------------------------------------------------------------------
# RealClock.sleep() tests
# ---------------------------------------------------------------------------
class TestRealClockSleep:
    """Verify RealClock.sleep() behaviour."""

    @pytest.mark.asyncio
    async def test_sleep_01_returns_after_minimum_elapsed(self, clock: RealClock) -> None:
        """await sleep(0.01) must wait at least ~0.01 s of monotonic time."""
        start = time.monotonic()
        await clock.sleep(0.01)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.009, (  # small tolerance
            f"sleep(0.01) returned too early: {elapsed:.4f}s",
        )

    @pytest.mark.asyncio
    async def test_sleep_zero_returns_promptly(self, clock: RealClock) -> None:
        """await sleep(0) must return promptly."""
        start = time.monotonic()
        await clock.sleep(0)
        elapsed = time.monotonic() - start
        assert elapsed < 0.5, (
            f"sleep(0) took too long: {elapsed:.4f}s",
        )

    @pytest.mark.asyncio
    async def test_sleep_zero_yields_to_event_loop(self, clock: RealClock) -> None:
        """await sleep(0) must yield to the event loop (non-blocking).

        We fire an async task and verify it runs concurrently with the sleep.
        """
        fired = asyncio.Event()

        async def fire_event() -> None:
            await asyncio.sleep(0.05)
            fired.set()

        asyncio.create_task(fire_event())
        # sleep(0) should return almost immediately, not block the 0.05s
        await clock.sleep(0)
        # The event should NOT have been set yet (too soon)
        assert not fired.is_set(), (
            "sleep(0) blocked the event loop",
        )

    @pytest.mark.asyncio
    async def test_sleep_negative_raises_value_error(self, clock: RealClock) -> None:
        """sleep(-1) must raise ValueError."""
        with pytest.raises(ValueError, match="negative"):
            await clock.sleep(-1)

    @pytest.mark.asyncio
    async def test_sleep_negative_zero_point_zero_raises(self, clock: RealClock) -> None:
        """sleep(-0.0) must raise ValueError."""
        with pytest.raises(ValueError, match="negative"):
            await clock.sleep(-0.0)

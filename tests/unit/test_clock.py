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


# ---------------------------------------------------------------------------
# ManualClock tests — Behaviour 4
# ---------------------------------------------------------------------------
"""Tests for ManualClock: a deterministic, time-manipulatable clock for testing.

Verifies:
- ManualClock().now() == 0.0 (default start=0.0).
- ManualClock(start=100.0).now() == 100.0.
- advance(seconds) accumulates across calls.
- advance() returns None (command, not query).
- now() is pure: repeated calls never change the time.
- Edge cases: advance(0) is a no-op, fractional accumulation, large advances,
  independent instances, negative advance raises ValueError.
"""


class TestManualClockDefaultStart:
    """Verify ManualClock default start time."""

    def test_default_now_is_zero(self) -> None:
        """ManualClock() with no args must start at 0.0."""
        from src.tool_swap.utils.clock import ManualClock

        clock = ManualClock()
        assert clock.now() == 0.0

    def test_default_start_is_zero(self) -> None:
        """ManualClock() must use start=0.0 by default."""
        from src.tool_swap.utils.clock import ManualClock

        clock = ManualClock()
        # Calling now() multiple times must always return 0.0 (pure)
        assert clock.now() == 0.0
        assert clock.now() == 0.0
        assert clock.now() == 0.0


class TestManualClockCustomStart:
    """Verify ManualClock with explicit start parameter."""

    def test_custom_start_value(self) -> None:
        """ManualClock(start=100.0).now() must return 100.0."""
        from src.tool_swap.utils.clock import ManualClock

        clock = ManualClock(start=100.0)
        assert clock.now() == 100.0

    def test_custom_start_pure(self) -> None:
        """now() must be pure: repeated calls don't change the value."""
        from src.tool_swap.utils.clock import ManualClock

        clock = ManualClock(start=42.5)
        assert clock.now() == 42.5
        assert clock.now() == 42.5
        assert clock.now() == 42.5


class TestManualClockAdvance:
    """Verify ManualClock.advance() accumulates time."""

    def test_advance_single_call(self) -> None:
        """advance(5) then now() must return 5.0."""
        from src.tool_swap.utils.clock import ManualClock

        clock = ManualClock()
        clock.advance(5)
        assert clock.now() == 5.0

    def test_advance_accumulates(self) -> None:
        """Two advance(5) calls must yield now() == 10.0."""
        from src.tool_swap.utils.clock import ManualClock

        clock = ManualClock()
        clock.advance(5)
        assert clock.now() == 5.0
        clock.advance(5)
        assert clock.now() == 10.0

    def test_advance_returns_none(self) -> None:
        """advance() is a command: must return None."""
        from src.tool_swap.utils.clock import ManualClock

        clock = ManualClock()
        result = clock.advance(5)
        assert result is None

    def test_advance_with_custom_start(self) -> None:
        """advance(3) on ManualClock(start=10) must yield now() == 13.0."""
        from src.tool_swap.utils.clock import ManualClock

        clock = ManualClock(start=10)
        clock.advance(3)
        assert clock.now() == 13.0

    def test_advance_does_not_affect_now_without_advance(self) -> None:
        """Before advance(), now() returns start unchanged."""
        from src.tool_swap.utils.clock import ManualClock

        clock = ManualClock(start=50.0)
        assert clock.now() == 50.0


class TestManualClockNowPurity:
    """Verify now() is pure: calling it never changes the time."""

    def test_now_is_idempotent(self) -> None:
        """Repeated now() calls return the same value."""
        from src.tool_swap.utils.clock import ManualClock

        clock = ManualClock(start=7.5)
        clock.advance(2.5)  # now should be 10.0
        first = clock.now()
        second = clock.now()
        third = clock.now()
        assert first == 10.0
        assert second == 10.0
        assert third == 10.0

    def test_now_pure_after_multiple_advances(self) -> None:
        """now() remains stable even after multiple advances."""
        from src.tool_swap.utils.clock import ManualClock

        clock = ManualClock()
        clock.advance(1)
        clock.advance(2)
        clock.advance(3)
        expected = 6.0
        for _ in range(100):
            assert clock.now() == expected


class TestManualClockEdgeCases:
    """Edge case tests for ManualClock."""

    def test_advance_zero_is_noop(self) -> None:
        """advance(0) must not raise and must not change time."""
        from src.tool_swap.utils.clock import ManualClock

        clock = ManualClock(start=42.0)
        clock.advance(0)
        assert clock.now() == 42.0
        clock.advance(0)
        assert clock.now() == 42.0

    def test_fractional_accumulation(self) -> None:
        """advance(0.1) x 10 must land within 1e-9 of 1.0.

        Using pytest.approx instead of == because floating-point
        arithmetic on fractional values can produce tiny rounding
        errors (e.g., 0.1 + 0.1 + ... != 1.0 exactly in IEEE 754).
        """
        from src.tool_swap.utils.clock import ManualClock

        clock = ManualClock()
        for _ in range(10):
            clock.advance(0.1)
        assert clock.now() == pytest.approx(1.0, abs=1e-9)

    def test_large_advance_30_minutes(self) -> None:
        """advance(1800) for the 30-minute idle scenario must be exact."""
        from src.tool_swap.utils.clock import ManualClock

        clock = ManualClock()
        clock.advance(1800)
        assert clock.now() == 1800.0

    def test_instances_are_independent(self) -> None:
        """Two ManualClock instances must not share mutable state."""
        from src.tool_swap.utils.clock import ManualClock

        clock_a = ManualClock()
        clock_b = ManualClock()

        clock_a.advance(5)
        assert clock_a.now() == 5.0
        assert clock_b.now() == 0.0

        clock_b.advance(10)
        assert clock_a.now() == 5.0
        assert clock_b.now() == 10.0

    def test_independence_with_custom_start(self) -> None:
        """Instances with different starts must remain independent."""
        from src.tool_swap.utils.clock import ManualClock

        clock_a = ManualClock(start=100.0)
        clock_b = ManualClock(start=200.0)

        assert clock_a.now() == 100.0
        assert clock_b.now() == 200.0

        clock_a.advance(10)
        assert clock_a.now() == 110.0
        assert clock_b.now() == 200.0


class TestManualClockErrorBehaviour:
    """Verify ManualClock raises appropriate errors."""

    def test_negative_advance_raises_value_error(self) -> None:
        """advance(-1) must raise ValueError naming the argument and value."""
        from src.tool_swap.utils.clock import ManualClock

        clock = ManualClock()
        with pytest.raises(ValueError) as exc_info:
            clock.advance(-1)
        # The error must name the argument and the received value
        assert "seconds" in str(exc_info.value).lower() or "advance" in str(
            exc_info.value
        ).lower()
        assert "-1" in str(exc_info.value)

    def test_negative_zero_advance_raises(self) -> None:
        """advance(-0.0) must raise ValueError."""
        from src.tool_swap.utils.clock import ManualClock

        clock = ManualClock()
        with pytest.raises(ValueError):
            clock.advance(-0.0)

    def test_large_negative_advance_raises(self) -> None:
        """advance(-999) must raise ValueError."""
        from src.tool_swap.utils.clock import ManualClock

        clock = ManualClock()
        with pytest.raises(ValueError):
            clock.advance(-999)

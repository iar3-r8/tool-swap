"""Clock protocol and RealClock implementation.

Provides the ``Clock`` protocol and a concrete ``RealClock`` that wraps
``time.monotonic()`` and ``asyncio.sleep()`` for deterministic time
management throughout the tool-swap codebase.
"""

import asyncio
import math
import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Protocol defining a time source that can be stubbed for testing.

    A ``Clock`` provides monotonic wall-clock reading and non-blocking
    sleep semantics.  Implementations (e.g. ``RealClock``, test doubles)
    must supply both ``now`` and ``sleep``.
    """

    def now(self) -> float:
        """Return the current monotonic time in seconds.

        Returns:
            Monotonic clock reading since an arbitrary, unspecified origin.
        """
        ...

    async def sleep(self, seconds: float) -> None:
        """Sleep for the given number of seconds without blocking the event loop.

        Args:
            seconds: Duration in seconds.  Must be non-negative.

        Raises:
            ValueError: If ``seconds`` is negative (including negative zero).
        """
        ...


class RealClock:
    """Production Clock backed by ``time.monotonic()`` and ``asyncio.sleep()``.

    Example:
        >>> import asyncio
        >>> clock = RealClock()
        >>> t = clock.now()
        >>> asyncio.run(clock.sleep(0.01))
        >>> clock.now() >= t + 0.01
        True
    """

    def now(self) -> float:
        """Return the current monotonic time in seconds.

        Returns:
            Monotonic clock reading via ``time.monotonic()``.
        """
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        """Sleep for *seconds*, yielding to the asyncio event loop.

        Args:
            seconds: Duration in seconds.  Must be non-negative (positive zero
                allowed; negative zero and all negative values raise).

        Raises:
            ValueError: If *seconds* is negative or is negative zero.
        """
        if math.copysign(1, seconds) < 0:
            raise ValueError("sleep duration must be non-negative (got negative)")
        await asyncio.sleep(seconds)


class ManualClock:
    """Deterministic, time-manipulatable clock for testing.

    This class implements the ``Clock`` protocol and provides a simulated
    clock whose time can be advanced programmatically.  It is useful in
    tests that need precise, reproducible time control.

    Example:
        >>> clock = ManualClock(start=100.0)
        >>> clock.now()
        100.0
        >>> clock.advance(5.0)
        >>> clock.now()
        105.0
    """

    _elapsed: float

    def __init__(self, start: float = 0.0) -> None:
        """Initialize the manual clock.

        Args:
            start: The initial simulated time. Defaults to ``0.0``.
        """
        self._start = start
        self._elapsed = 0.0

    def now(self) -> float:
        """Return the current simulated monotonic time.

        This method is pure — calling it never changes the time.

        Returns:
            The sum of the start time and all accumulated advances.
        """
        return self._start + self._elapsed

    def advance(self, seconds: float) -> None:
        """Advance the simulated clock forward by *seconds*.

        Args:
            seconds: Amount of time in seconds to advance. Must be
                non-negative (positive zero and all positive values
                allowed; negative values and negative zero raise).

        Raises:
            ValueError: If *seconds* is negative or is negative zero.
        """
        if math.copysign(1, seconds) < 0:
            raise ValueError(
                f"advance seconds must be non-negative (got {seconds})"
            )
        self._elapsed += seconds

    async def sleep(self, seconds: float) -> None:
        """Advance simulated time by *seconds* and yield to the event loop.

        This method implements the ``Clock`` protocol by advancing the
        internal time by the given duration and then yielding control
        back to the asyncio event loop via ``await asyncio.sleep(0)``.

        Args:
            seconds: Duration in seconds to advance. Must be non-negative
                (positive zero allowed; negative values and negative zero
                raise ``ValueError``).

        Raises:
            ValueError: If *seconds* is negative or is negative zero.

        Example:
            >>> import asyncio
            >>> clock = ManualClock(start=100.0)
            >>> asyncio.run(clock.sleep(30))
            >>> clock.now()
            130.0
        """
        if math.copysign(1, seconds) < 0:
            raise ValueError("sleep duration must be non-negative (got negative)")
        self._elapsed += seconds
        await asyncio.sleep(0)

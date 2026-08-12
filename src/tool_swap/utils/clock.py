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

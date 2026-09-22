"""The readiness progression (m2b plan §3 behaviour 11, §1.3).

``drive_readiness`` walks one ``ModelRuntimeState`` from ``STARTING``
to ``READY``: it polls the probe's ``health`` until it answers true
and applies ``STARTING -> LOADING``, then polls ``ready`` until it
answers true and applies ``LOADING -> READY``. Every wait is
``await clock.sleep(probe_interval)`` and every deadline is a
comparison against ``clock.now()`` — never ``asyncio.wait_for``, whose
deadline is the event loop's clock, which a ``ManualClock`` does not
control. A probe answering true on its first call of a phase skips the
sleep entirely, so a warm tool costs no simulated time.

The two deadlines are independent: ``start_timeout`` covers
container-up-to-health; ``ready_timeout`` covers health-to-ready and
starts when health answered. A deadline that elapses raises
``StartTimeoutError`` or ``ReadyTimeoutError`` naming that deadline and
the simulated seconds it ran; marking the holder ``FAILED`` is
behaviour 16's, so the raise leaves the holder in the phase it hung in.
The ``LifecycleManager`` class (behaviour 12) is a later slice.
"""

from __future__ import annotations

from typing import Final, cast

from tool_swap.config.defaults import BUILT_IN_DEFAULTS
from tool_swap.lifecycle.states import (
    ModelRuntimeState,
    ToolState,
    apply_transition,
)
from tool_swap.proxy.probes import Probe, ProbeTarget
from tool_swap.utils.clock import Clock

# The built-in deadline values, read from the single named source of
# truth so the signature's defaults cannot drift from defaults.py.
_START_TIMEOUT: Final[float] = float(cast("float", BUILT_IN_DEFAULTS["start_timeout"]))
_READY_TIMEOUT: Final[float] = float(cast("float", BUILT_IN_DEFAULTS["ready_timeout"]))
_PROBE_INTERVAL: Final[float] = float(
    cast("float", BUILT_IN_DEFAULTS["probe_interval"])
)


class ReadinessTimeoutError(TimeoutError):
    """A readiness deadline elapsed (m2b plan §3 behaviour 11).

    Carries ``deadline`` — which of the two deadlines ran out — and
    ``elapsed``, the simulated seconds it ran, so an operator can tell a
    hung start from a hung ready. Subclasses the built-in
    ``TimeoutError``, which is the seam type an internal timeout keeps.
    """

    def __init__(self, deadline: str, elapsed: float) -> None:
        super().__init__(f"readiness {deadline} elapsed after {elapsed}s")
        self.deadline = deadline
        self.elapsed = elapsed


class StartTimeoutError(ReadinessTimeoutError):
    """``start_timeout`` elapsed while ``health`` still answered false,
    so the holder is left ``STARTING``."""

    def __init__(self, elapsed: float) -> None:
        super().__init__("start_timeout", elapsed)


class ReadyTimeoutError(ReadinessTimeoutError):
    """``ready_timeout`` elapsed while ``ready`` still answered false,
    so the holder is left ``LOADING``."""

    def __init__(self, elapsed: float) -> None:
        super().__init__("ready_timeout", elapsed)


async def drive_readiness(
    state: ModelRuntimeState,
    probe: Probe,
    clock: Clock,
    target: ProbeTarget,
    start_timeout: float = _START_TIMEOUT,
    ready_timeout: float = _READY_TIMEOUT,
    probe_interval: float = _PROBE_INTERVAL,
) -> ToolState:
    """Walk ``state`` from ``STARTING`` to ``READY`` on probe answers.

    Each phase polls once per ``probe_interval`` until its probe
    answers true, moving the holder through ``apply_transition`` so the
    transition table and its logging are inherited. A first-call true
    answer skips the sleep entirely. Each deadline is checked against
    ``clock.now()`` before every poll and, when it has elapsed, the
    phase's error is raised leaving the holder in that phase.

    Args:
        state: The holder, sitting at ``STARTING``; mutated in place.
        probe: The readiness probe; only ``health`` and ``ready`` are
            called.
        clock: The time source every wait and deadline reads.
        target: The ``ProbeTarget`` addressed to the tool.
        start_timeout: Seconds allowed for container-up-to-health.
        ready_timeout: Seconds allowed for health-to-ready.
        probe_interval: Simulated seconds between polls.

    Returns:
        ``ToolState.READY``.

    Raises:
        StartTimeoutError: ``health`` never answered true within
            ``start_timeout``; the holder is left ``STARTING``.
        ReadyTimeoutError: ``ready`` never answered true within
            ``ready_timeout``; the holder is left ``LOADING``.
        IllegalTransitionError: from ``apply_transition`` on an illegal
            pair, leaving the holder untouched.
    """
    # Deadlines are compared against clock.now(): asyncio.wait_for's
    # deadline is the event loop's clock, which a manual clock does not
    # control (m2b plan §1.3).
    start_deadline = clock.now() + start_timeout
    while clock.now() < start_deadline:
        if await probe.health(target):
            break
        await clock.sleep(probe_interval)
    else:
        raise StartTimeoutError(clock.now() - (start_deadline - start_timeout))
    apply_transition(state, ToolState.LOADING, reason="health probe answered true")
    # The ready window starts when health answered, not at t=0.
    ready_deadline = clock.now() + ready_timeout
    while clock.now() < ready_deadline:
        if await probe.ready(target):
            break
        await clock.sleep(probe_interval)
    else:
        raise ReadyTimeoutError(clock.now() - (ready_deadline - ready_timeout))
    return apply_transition(state, ToolState.READY, reason="ready probe answered true")

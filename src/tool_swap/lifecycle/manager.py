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
the simulated seconds it ran; marking the holder ``FAILED`` is left to
the caller, so the raise leaves the holder in the phase it hung in.

``LifecycleManager`` is the object that owns the injected ``backend``,
``probe``, ``clock`` and ``backend_config`` plus the three timeout
scalars; it constructs nothing internally, so it can be built in an
environment where the docker SDK is not importable.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from dataclasses import dataclass, field
from typing import Final, cast

from tool_swap.backend.base import ContainerBackend, ContainerHandle
from tool_swap.backend.errors import BackendError
from tool_swap.config.defaults import BUILT_IN_DEFAULTS
from tool_swap.config.resolver import ResolvedTool
from tool_swap.config.schema import BackendConfig
from tool_swap.lifecycle.spec_builder import build_container_spec
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
_STOP_TIMEOUT: Final[float] = float(cast("float", BUILT_IN_DEFAULTS["stop_timeout"]))

# Module-level logger; used only for cleanup failures a handler must
# not let mask the error it is handling.
logger = logging.getLogger(__name__)


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


class LifecycleManager:
    """Owns the injected backend, probe, clock and backend configuration.

    Holds each injected object by identity and the timeout scalars by
    value, so the manager uses exactly what it was given — a
    ``FakeBackend`` keeps it usable where the docker SDK is not
    importable, and a caller that does not use the config layer can
    still construct it. Construction performs no backend work and no
    clock movement; any readiness progression it later runs must
    delegate to :func:`drive_readiness`.

    Raises:
        TypeError: ``backend`` or ``probe`` is ``None`` — a
            programming error refused at construction rather than at
            the first call.
    """

    def __init__(
        self,
        backend: ContainerBackend,
        *,
        probe: Probe,
        clock: Clock,
        backend_config: BackendConfig,
        start_timeout: float = _START_TIMEOUT,
        ready_timeout: float = _READY_TIMEOUT,
        probe_interval: float = _PROBE_INTERVAL,
        stop_timeout: float = _STOP_TIMEOUT,
    ) -> None:
        """Store the injections by identity and the scalars by value.

        Args:
            backend: The container backend; held by identity.
            probe: The readiness probe; held by identity.
            clock: The time source every wait and deadline reads.
            backend_config: The ``backend:`` config block.
            start_timeout: Seconds allowed for container-up-to-health.
            ready_timeout: Seconds allowed for health-to-ready.
            probe_interval: Simulated seconds between polls.
            stop_timeout: Seconds a stop of the hung container is
                allowed before the runtime kills it.
        """
        if backend is None:
            raise TypeError("backend must not be None")
        if probe is None:
            raise TypeError("probe must not be None")
        self.backend = backend
        self.probe = probe
        self.clock = clock
        self.backend_config = backend_config
        self.start_timeout = start_timeout
        self.ready_timeout = ready_timeout
        self.probe_interval = probe_interval
        self.stop_timeout = stop_timeout
        self._tools: dict[str, _ToolRegistration] = {}

    def register_tool(self, tool: str, resolved: ResolvedTool, *, image: str) -> None:
        """Store a tool's configuration and image under a fresh state.

        The manager needs the ``ResolvedTool`` and an image before it
        can build a ``ContainerSpec``, and nothing else supplies them;
        registering is what makes the tool ready-able. The fresh state
        is ``STOPPED`` with no container, which is what a registered
        tool is until a start runs.

        Args:
            tool: The tool name the manager tracks it under.
            resolved: The tool's fully resolved configuration.
            image: The container image reference to start it with.

        Raises:
            ValueError: ``tool`` does not match ``resolved.name``, or
                the tool is already registered — re-registering would
                drop the state of a tool that may be serving.
        """
        if tool != resolved.name:
            raise ValueError(
                f"register_tool was given tool {tool!r} but its resolved "
                f"config names {resolved.name!r}"
            )
        if tool in self._tools:
            raise ValueError(f"tool {tool!r} is already registered")
        state = ModelRuntimeState(
            tool=tool,
            state=ToolState.STOPPED,
            handle=None,
            last_used=self.clock.now(),
            became_ready_at=None,
            inflight=0,
            last_error=None,
        )
        self._tools[tool] = _ToolRegistration(
            resolved=resolved, image=image, state=state
        )

    def state_of(self, tool: str) -> ModelRuntimeState:
        """The tool's runtime state holder, for read-back.

        Returns:
            The ``ModelRuntimeState`` the manager tracks for the tool.

        Raises:
            KeyError: the tool was never registered with this manager.
        """
        return self._registration(tool).state

    async def ensure_ready(self, tool: str) -> ContainerHandle:
        """Bring a registered tool to ``READY`` and return its handle.

        A ``STOPPED`` tool walks ``STOPPED -> STARTING -> LOADING ->
        READY`` through ``apply_transition``, starting its container
        once and delegating the probe progression to
        :func:`drive_readiness`. A tool already ``READY`` returns the
        handle it holds without starting anything or re-stamping
        ``became_ready_at``; ``last_used`` is never touched here, since
        it belongs to request completion. A ``FAILED`` tool is retried
        through the legal ``FAILED -> STARTING`` edge, so a refused start
        never strands the tool until a manual reset.

        Args:
            tool: The registered tool to make ready.

        Returns:
            The ``ContainerHandle`` the backend start produced; for a
            ``READY`` tool, the handle it already holds.

        Raises:
            KeyError: the tool was never registered with this manager.
            ValueError: the tool sits in a state this method does not
                serve yet (anything but ``STOPPED``, ``READY`` and
                ``FAILED``).
            StartTimeoutError: ``health`` never answered true within
                ``start_timeout``; the container is stopped and the
                holder ends ``FAILED``.
            ReadyTimeoutError: ``ready`` never answered true within
                ``ready_timeout``; the container is stopped and the
                holder ends ``FAILED``.
            IllegalTransitionError: from ``apply_transition`` on an
                illegal pair, leaving the holder untouched.
        """
        registration = self._registration(tool)
        # The lock is held only while deciding who starts: holding it
        # across the cold start would serialise every caller behind the
        # start instead of letting them share it.
        async with registration.lock:
            state = registration.state
            if state.state is ToolState.READY:
                return cast("ContainerHandle", state.handle)
            if (
                state.state in (ToolState.STOPPED, ToolState.FAILED)
                and registration.pending is None
            ):
                # The decision and the holder move happen under the same
                # lock: a STARTING mutation made before any await would
                # let a caller arriving in between miss the pending task
                # and race a second start.
                apply_transition(
                    state, ToolState.STARTING, reason="ensure_ready cold start"
                )
                start_task = asyncio.create_task(self._cold_start(registration))
                registration.pending = start_task
            elif registration.pending is not None:
                start_task = registration.pending
            else:
                raise ValueError(
                    f"ensure_ready on tool {tool!r} in state {state.state!r} "
                    "is not supported yet; only STOPPED, READY and FAILED "
                    "are"
                )
        # A caller cancelled while awaiting must not cancel the start
        # its peers are awaiting: shield raises the cancellation here
        # while the cold-start task runs on for everyone else.
        return await asyncio.shield(start_task)

    async def _cold_start(self, registration: _ToolRegistration) -> ContainerHandle:
        """Run one tool's cold start: start its container and drive the
        holder to ``READY``.

        Runs as the single task every concurrent ``ensure_ready`` caller
        for this tool awaits, so it is the only caller that polls the
        probe or sleeps on the clock. A backend start refusal ends the
        holder ``FAILED`` with the taxonomy member's message, recorded
        once here rather than per waiter, because the transition table
        has no ``FAILED -> FAILED`` self-edge and ten waiters each
        applying it would raise nine ``IllegalTransitionError``s on top
        of the real failure. A readiness timeout stops the hung
        container before ending the holder ``FAILED``, so a failed cold
        start never leaves a container resident. Any exception is
        re-raised into every waiter, so one failed start is one shared
        failure.
        """
        state = registration.state
        try:
            spec = build_container_spec(
                registration.resolved, self.backend_config, registration.image
            )
            target = ProbeTarget(
                tool=state.tool,
                host=spec.name,
                port=spec.container_port,
                health_path=str(registration.resolved.values["health_path"]),
                ready_path=str(registration.resolved.values["ready_path"]),
            )
            try:
                # The seam is synchronous and a backend round-trip can
                # block, so the call runs on the loop's default executor:
                # on the loop itself it would stall every other task
                # until the backend answers.
                handle = await asyncio.get_running_loop().run_in_executor(
                    None, self.backend.start, spec
                )
            except BackendError as err:
                # The refusal's message, verbatim: str(err) appends the
                # remedy, and the recorded reason must carry the message
                # alone. No handle is stored — the refusal created no
                # container — and the re-raise keeps the caller's error
                # path on the taxonomy member.
                state.last_error = err.message
                apply_transition(state, ToolState.FAILED, reason=err.message)
                raise
            state.handle = handle
            try:
                await drive_readiness(
                    state,
                    self.probe,
                    self.clock,
                    target,
                    start_timeout=self.start_timeout,
                    ready_timeout=self.ready_timeout,
                    probe_interval=self.probe_interval,
                )
            except ReadinessTimeoutError as err:
                # Unlike a start refusal, a container exists and is
                # still running, so stopping it is part of failing the
                # tool: leaving it resident would leak a slot on every
                # failed cold start. The holder is already where the
                # phase hung — STARTING or LOADING — and both edges into
                # FAILED are legal, so no from-state is passed.
                await self._fail_on_timeout(state, err)
                raise
        except BaseException:
            # Release the slot so a later caller does not await a dead
            # task; a failure the handler above does not map to FAILED
            # leaves the holder where the start died.
            registration.pending = None
            raise
        state.became_ready_at = self.clock.now()
        return state.handle

    async def _fail_on_timeout(
        self, state: ModelRuntimeState, err: ReadinessTimeoutError
    ) -> None:
        """End a timed-out cold start: stop the container, fail the tool,
        clear the handle.

        The holder sits where its phase hung — ``STARTING`` when
        ``start_timeout`` ran, ``LOADING`` when ``ready_timeout`` did —
        so the move into ``FAILED`` reads the from-state from the
        holder. ``err``'s own rendering is recorded as the reason: it
        names which deadline ran and for how long, which is what an
        operator needs to tell a hung ready from a hung start. The stop
        runs on the loop's default executor, so a backend that blocks
        inside ``stop`` cannot stall the loop. A stop that itself
        raises is logged and not allowed to replace ``err`` — the
        caller is owed the timeout — but the holder still ends
        ``FAILED`` and the handle is still cleared, since either way
        the tool no longer claims a running container.

        Args:
            state: The holder, at ``STARTING`` or ``LOADING``; mutated
                in place.
            err: The timeout that ended the cold start; re-raised by
                the caller.
        """
        handle = state.handle
        if handle is not None:
            stop = functools.partial(
                self.backend.stop, handle, timeout_s=self.stop_timeout
            )
            try:
                await asyncio.get_running_loop().run_in_executor(None, stop)
            except Exception:
                logger.warning(
                    "stop of %s failed while handling the readiness timeout for %s",
                    handle.name,
                    state.tool,
                    exc_info=True,
                )
        state.last_error = str(err)
        apply_transition(state, ToolState.FAILED, reason=str(err))
        state.handle = None

    def _registration(self, tool: str) -> _ToolRegistration:
        """The registration for a tool, or a named KeyError.

        Raises:
            KeyError: the tool was never registered with this manager.
        """
        try:
            return self._tools[tool]
        except KeyError as exc:
            raise KeyError(f"tool {tool!r} is not registered") from exc


@dataclass
class _ToolRegistration:
    """One registered tool's spec inputs and its runtime holder.

    The holder is shared by identity with ``state_of`` and
    ``ensure_ready``: ``drive_readiness`` mutates it in place, so a
    copy would let the read-back lie about the live state.

    ``lock`` serialises only the decision of who starts the tool, and
    ``pending`` is the in-flight cold-start task every concurrent
    ``ensure_ready`` caller awaits, or ``None`` when no start is in
    flight.
    """

    resolved: ResolvedTool
    image: str
    state: ModelRuntimeState
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    pending: asyncio.Task[ContainerHandle] | None = None

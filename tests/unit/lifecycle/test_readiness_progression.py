"""Pins the readiness progression (m2b plan §3 behaviour 11, §1.3, §1.5):
a holder sitting at STARTING walks to LOADING on the first true ``health``
answer and to READY on the first true ``ready`` answer, polling on the
injected clock under the two built-in deadlines. The plan names the module,
``lifecycle/manager.py``, but not the coroutine it holds — the
``LifecycleManager`` class belongs to behaviour 12 — so this file declares
the contract, for the implementation to honour:

    from tool_swap.lifecycle.manager import (
        ReadyTimeoutError,
        StartTimeoutError,
        drive_readiness,
    )

    await drive_readiness(
        state,                # a ModelRuntimeState sitting at STARTING
        probe,                # the Probe from tool_swap.proxy.probes
        clock,                # the Clock every wait and deadline reads
        target,               # the ProbeTarget addressed to the tool
        start_timeout=120.0,  # container-up-to-health, built-in default
        ready_timeout=600.0,  # health-to-ready, built-in default
        probe_interval=1.0,   # simulated seconds between polls, built-in
    )

``drive_readiness`` is a coroutine returning the final ``ToolState``. It
polls ``probe.health`` until it answers true and applies
``STARTING -> LOADING`` via ``apply_transition``, then polls ``probe.ready``
until it answers true and applies ``LOADING -> READY``. Each wait is
``await clock.sleep(probe_interval)`` and each deadline is a comparison
against ``clock.now()`` — never ``asyncio.wait_for``, whose deadline is the
event loop's clock, which a manual clock does not control. Either deadline
elapsing raises: ``StartTimeoutError`` from the STARTING phase,
``ReadyTimeoutError`` from the LOADING phase. Both are defined in
``manager.py``, both subclass the built-in ``TimeoutError``, and both carry
the deadline that ran out (``deadline``: ``"start_timeout"`` or
``"ready_timeout"``) and the simulated seconds it ran (``elapsed``, a
float). Marking the holder ``FAILED`` is behaviour 16's job, which catches
these; the raise leaves the holder in the phase it hung in. Every test here
drives exactly one polling coroutine and never calls ``clock.advance()``:
concurrent ManualClock sleeps sum rather than overlap, and the loop's own
sleeps are what must run a never-true script to its deadline. When the
module is missing, every test fails at the deferred gate that names the
missing name rather than aborting collection.
"""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Awaitable, Callable
from types import ModuleType
from typing import Any, cast

import pytest

import tool_swap.lifecycle.states as states_module
from tool_swap.config.defaults import BUILT_IN_DEFAULTS
from tool_swap.lifecycle.states import (
    ModelRuntimeState,
    ToolState,
    apply_transition,
)
from tool_swap.proxy.probes import FakeProbe, ProbeTarget
from tool_swap.utils.clock import ManualClock

TOOL = "t1"

# The built-in deadline values, read from defaults.py so the deadline
# arithmetic below cannot drift from the source of truth.
START_TIMEOUT: float = float(BUILT_IN_DEFAULTS["start_timeout"])
READY_TIMEOUT: float = float(BUILT_IN_DEFAULTS["ready_timeout"])
PROBE_INTERVAL: float = float(BUILT_IN_DEFAULTS["probe_interval"])


def _get_manager_module() -> ModuleType:
    """Import tool_swap.lifecycle.manager at call time.

    Raises:
        AssertionError: the module is missing; the message names the
            file to create.
    """
    try:
        return importlib.import_module("tool_swap.lifecycle.manager")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.lifecycle.manager is missing — create "
            "src/tool_swap/lifecycle/manager.py"
        ) from exc


def _get_drive_readiness() -> Callable[..., Awaitable[Any]]:
    """Return the ``drive_readiness`` coroutine function.

    Raises:
        AssertionError: the name is missing from manager.py.
    """
    module = _get_manager_module()
    try:
        return cast("Callable[..., Awaitable[Any]]", module.drive_readiness)
    except AttributeError as exc:
        raise AssertionError(
            "drive_readiness is missing from src/tool_swap/lifecycle/manager.py"
        ) from exc


def _get_timeout_class(name: str) -> type[BaseException]:
    """Return one of the two timeout error classes declared above.

    Raises:
        AssertionError: the name is missing from manager.py.
    """
    module = _get_manager_module()
    try:
        return cast("type[BaseException]", getattr(module, name))
    except AttributeError as exc:
        raise AssertionError(
            f"{name} is missing from src/tool_swap/lifecycle/manager.py — "
            "the progression must raise it when that deadline elapses"
        ) from exc


def _timeout_attr(error: BaseException, attribute: str) -> Any:
    """Read one pinned attribute off a raised timeout error.

    Raises:
        AssertionError: the attribute is missing; the message names it.
    """
    try:
        return getattr(error, attribute)
    except AttributeError as exc:
        raise AssertionError(
            f"{type(error).__name__} carries no {attribute} attribute — "
            "attach the deadline that ran out (deadline) and the "
            "simulated seconds it ran (elapsed)"
        ) from exc


def _starting_state() -> ModelRuntimeState:
    """A fresh holder at STARTING, where a just-started tool sits before
    its first health answer."""
    return ModelRuntimeState(
        tool=TOOL,
        state=ToolState.STARTING,
        handle=None,
        last_used=0.0,
        became_ready_at=None,
        inflight=0,
        last_error=None,
    )


def _target() -> ProbeTarget:
    """The ProbeTarget addressed to TOOL; FakeProbe reads only ``tool``."""
    return ProbeTarget(
        tool=TOOL,
        host=f"tswap-{TOOL}",
        port=8000,
        health_path="/health",
        ready_path="/ready",
    )


def _track_transitions(monkeypatch: pytest.MonkeyPatch) -> list[ToolState]:
    """Route the progression's ``apply_transition`` calls through a tracker.

    The tracker appends each to-state and then delegates to the real
    function, so the legal edges and the logging rule still run. Both the
    manager module's and the states module's names are patched, since the
    implementation may bind the function either way.
    """
    observed: list[ToolState] = []

    def tracking(
        state: ModelRuntimeState, to_state: ToolState, *, reason: str
    ) -> ToolState:
        observed.append(to_state)
        return apply_transition(state, to_state, reason=reason)

    monkeypatch.setattr(states_module, "apply_transition", tracking)
    monkeypatch.setattr(
        _get_manager_module(), "apply_transition", tracking, raising=False
    )
    return observed


# ---------------------------------------------------------------------------
# The happy progression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progression_walks_starting_loading_ready_on_polling_intervals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A health answer true after two polls and a ready answer true after
    three walks STARTING to LOADING to READY and costs exactly five
    simulated seconds, each false answer costing one probe interval."""
    # Arrange
    drive_readiness = _get_drive_readiness()
    observed = _track_transitions(monkeypatch)
    clock = ManualClock()
    probe = FakeProbe(script={TOOL: {"health": 2, "ready": 3}})
    state = _starting_state()
    # Act
    result = await drive_readiness(
        state,
        probe,
        clock,
        _target(),
        start_timeout=START_TIMEOUT,
        ready_timeout=READY_TIMEOUT,
        probe_interval=PROBE_INTERVAL,
    )
    # Assert
    assert result is ToolState.READY, (
        f"progression returned {result!r} — it must return the final state, READY"
    )
    assert observed == [ToolState.LOADING, ToolState.READY], (
        f"observed {observed} — the holder must move STARTING -> LOADING "
        "-> READY through apply_transition, in that order, so the "
        "transition logging is inherited"
    )
    assert state.state is ToolState.READY, (
        "the holder was not mutated in place — apply_transition mutates "
        "it, so the progression must route its moves through it"
    )
    assert clock.now() == 5.0, (
        f"simulated time is {clock.now()} — two false health answers cost "
        "two intervals and three false ready answers three, all through "
        "clock.sleep(probe_interval)"
    )
    assert probe.calls == [("health", TOOL)] * 3 + [("ready", TOOL)] * 4, (
        f"probe journal is {probe.calls} — each phase is asked for its "
        "false answers plus the first true one, nothing else"
    )


@pytest.mark.asyncio
async def test_warm_progression_costs_zero_simulated_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A probe answering true on its first call of each phase transitions
    both times without a single sleep: a poll-interval sleep before the
    first ask would make a warm tool cost simulated time."""
    # Arrange
    drive_readiness = _get_drive_readiness()
    observed = _track_transitions(monkeypatch)
    clock = ManualClock()
    probe = FakeProbe()  # unscripted: both phases answer true immediately
    state = _starting_state()
    # Act
    result = await drive_readiness(
        state,
        probe,
        clock,
        _target(),
        start_timeout=START_TIMEOUT,
        ready_timeout=READY_TIMEOUT,
        probe_interval=PROBE_INTERVAL,
    )
    # Assert
    assert result is ToolState.READY
    assert observed == [ToolState.LOADING, ToolState.READY]
    assert probe.calls == [("health", TOOL), ("ready", TOOL)], (
        f"probe journal is {probe.calls} — a warm tool is asked once per "
        "phase, and the sleeps must be skipped entirely"
    )
    assert clock.now() == 0.0, (
        f"simulated time is {clock.now()} — a first-call true answer must "
        "skip the sleep, so a warm tool costs no simulated time"
    )


@pytest.mark.asyncio
async def test_progression_holds_loading_across_each_false_ready_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once health answers true, the holder sits in LOADING — never back
    in STARTING — for every false ready answer, so a slow cold start is
    diagnosable as time in LOADING rather than time in STARTING."""
    # Arrange
    drive_readiness = _get_drive_readiness()
    observed = _track_transitions(monkeypatch)
    clock = ManualClock()
    probe = FakeProbe(script={TOOL: {"health": 0, "ready": 5}})
    state = _starting_state()
    # Act
    result = await drive_readiness(
        state,
        probe,
        clock,
        _target(),
        start_timeout=START_TIMEOUT,
        ready_timeout=READY_TIMEOUT,
        probe_interval=PROBE_INTERVAL,
    )
    # Assert
    assert result is ToolState.READY
    assert observed == [ToolState.LOADING, ToolState.READY], (
        f"observed {observed} — after the first true health answer the "
        "holder must be LOADING while ready is still false"
    )
    assert probe.calls == [("health", TOOL)] + [("ready", TOOL)] * 6, (
        f"probe journal is {probe.calls} — one health ask, then ready "
        "false five times and true once"
    )
    assert clock.now() == 5.0, (
        f"simulated time is {clock.now()} — the LOADING window is five "
        "false ready answers times the probe interval"
    )


# ---------------------------------------------------------------------------
# The two independent deadlines
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_timeout_names_its_deadline_and_elapsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A health probe that never answers true runs the STARTING phase to
    its deadline and raises StartTimeoutError naming that deadline and the
    simulated seconds it ran; the holder stays STARTING, because marking
    FAILED is behaviour 16's. The raise arrives by the loop's own sleeps —
    this test never calls clock.advance(), so a loop not driven by the
    injected clock hangs rather than fails."""
    # Arrange
    drive_readiness = _get_drive_readiness()
    _track_transitions(monkeypatch)
    clock = ManualClock()
    probe = FakeProbe(script={TOOL: {"health": None}})
    state = _starting_state()
    # Act
    with pytest.raises(_get_timeout_class("StartTimeoutError")) as exc_info:
        await drive_readiness(
            state,
            probe,
            clock,
            _target(),
            start_timeout=START_TIMEOUT,
            ready_timeout=READY_TIMEOUT,
            probe_interval=PROBE_INTERVAL,
        )
    # Assert
    error = exc_info.value
    assert _timeout_attr(error, "deadline") == "start_timeout", (
        "the raised error names the wrong deadline — the STARTING phase "
        "outlived start_timeout, and the operator needs that named"
    )
    assert _timeout_attr(error, "elapsed") == START_TIMEOUT, (
        f"elapsed is {_timeout_attr(error, 'elapsed')!r} — the STARTING "
        "phase ran start_timeout simulated seconds"
    )
    assert state.state is ToolState.STARTING, (
        f"the holder moved to {state.state!r} on a start timeout — this "
        "behaviour raises; the transition to FAILED is behaviour 16's"
    )
    assert clock.now() == START_TIMEOUT, (
        f"simulated time is {clock.now()} — the deadline is "
        f"start_timeout, reached by the loop's own sleeps"
    )
    expected_health_calls = int(START_TIMEOUT / PROBE_INTERVAL)
    assert probe.calls == [("health", TOOL)] * expected_health_calls, (
        f"probe journal has {len(probe.calls)} health calls — the loop "
        "polls once per interval until the deadline, no more"
    )


@pytest.mark.asyncio
async def test_ready_timeout_names_its_deadline_and_elapsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Health answers true after two polls and ready never does: the
    LOADING phase runs to its own deadline, which starts when health
    answered — the two windows are independent, so the clock reads the
    start-phase time plus ready_timeout, and the error names
    ready_timeout with an elapsed of ready_timeout alone."""
    # Arrange
    drive_readiness = _get_drive_readiness()
    _track_transitions(monkeypatch)
    clock = ManualClock()
    probe = FakeProbe(script={TOOL: {"health": 2, "ready": None}})
    state = _starting_state()
    # Act
    with pytest.raises(_get_timeout_class("ReadyTimeoutError")) as exc_info:
        await drive_readiness(
            state,
            probe,
            clock,
            _target(),
            start_timeout=START_TIMEOUT,
            ready_timeout=READY_TIMEOUT,
            probe_interval=PROBE_INTERVAL,
        )
    # Assert
    error = exc_info.value
    assert _timeout_attr(error, "deadline") == "ready_timeout", (
        "the raised error names the wrong deadline — the LOADING phase "
        "outlived ready_timeout, and the operator needs that named"
    )
    assert _timeout_attr(error, "elapsed") == READY_TIMEOUT, (
        f"elapsed is {_timeout_attr(error, 'elapsed')!r} — the LOADING "
        "phase ran ready_timeout simulated seconds, not the sum of both "
        "timeouts"
    )
    assert state.state is ToolState.LOADING, (
        f"the holder moved to {state.state!r} on a ready timeout — this "
        "behaviour raises; the transition to FAILED is behaviour 16's"
    )
    assert clock.now() == 2.0 + READY_TIMEOUT, (
        f"simulated time is {clock.now()} — the ready window starts when "
        "health answered true, so the clock reads two intervals plus "
        "ready_timeout, proving the deadlines are not chained"
    )
    expected_ready_calls = int(READY_TIMEOUT / PROBE_INTERVAL)
    assert probe.calls == (
        [("health", TOOL)] * 3 + [("ready", TOOL)] * expected_ready_calls
    ), (
        f"probe journal has {len(probe.calls)} calls — three health asks "
        "and one ready poll per interval for ready_timeout"
    )


def test_the_two_readiness_timeouts_are_distinguishable() -> None:
    """The STARTING and LOADING phase deadlines raise different classes,
    so an operator and behaviour 16 can tell a hung start from a hung
    ready — the two slow-start incidents the state machine exists to keep
    apart."""
    # Arrange
    start_error_cls = _get_timeout_class("StartTimeoutError")
    ready_error_cls = _get_timeout_class("ReadyTimeoutError")
    # Act / Assert
    assert start_error_cls is not ready_error_cls, (
        "both deadlines raise the same class — the raised error must name "
        "which phase hung, and one class cannot carry both"
    )
    assert issubclass(start_error_cls, TimeoutError), (
        "StartTimeoutError does not subclass the built-in TimeoutError — "
        "an internal timeout keeps the built-in as its seam type"
    )
    assert issubclass(ready_error_cls, TimeoutError), (
        "ReadyTimeoutError does not subclass the built-in TimeoutError"
    )


def test_progression_is_a_coroutine_function_with_built_in_defaults() -> None:
    """drive_readiness is a coroutine, and its three deadline parameters
    default to the built-in values, so the deadline arithmetic cannot
    drift from defaults.py; a missing parameter would mean the
    progression reads the deadlines from somewhere else."""
    # Arrange
    drive_readiness = _get_drive_readiness()
    # Act
    is_coroutine = inspect.iscoroutinefunction(drive_readiness)
    parameters = inspect.signature(drive_readiness).parameters
    # Assert
    assert is_coroutine, (
        "drive_readiness is not a coroutine function — the waits are "
        "awaits on the injected clock, so the progression must be async"
    )
    for name, expected in (
        ("start_timeout", BUILT_IN_DEFAULTS["start_timeout"]),
        ("ready_timeout", BUILT_IN_DEFAULTS["ready_timeout"]),
        ("probe_interval", BUILT_IN_DEFAULTS["probe_interval"]),
    ):
        parameter = parameters.get(name)
        assert parameter is not None, (
            f"drive_readiness has no {name} parameter — the three "
            "deadline values must be injectable, not read from a constant"
        )
        assert parameter.default == expected, (
            f"{name} defaults to {parameter.default!r} — the built-in "
            f"default is {expected!r} in src/tool_swap/config/defaults.py"
        )

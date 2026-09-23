"""Pins the cold start of ``LifecycleManager.ensure_ready`` (m2b plan
§3 behaviours 13 and 14, §1.3, §1.4): a ``STOPPED`` tool whose probe
answers true immediately walks ``STOPPED -> STARTING -> LOADING ->
READY`` through the transition table, the backend is started exactly
once, the returned handle is the one ``backend.start`` produced,
``became_ready_at`` is stamped from the injected clock, and a second
``ensure_ready`` on an already-``READY`` tool starts nothing, re-stamps
nothing and returns the same handle. Behaviour 14 adds the coalesced
cold start: ten concurrent callers start the backend exactly once, all
ten receive the same handle, the simulated elapsed time is what one
cold start costs (the proof that the other callers await the in-flight
start rather than poll or sleep), a failed single start reaches all ten
callers as one shared failure, and a round after ``READY`` starts
nothing.

The manager receives each tool's ``ResolvedTool`` and image through
``register_tool(tool, resolved, image=...)`` and exposes the per-tool
runtime state through ``state_of(tool)`` — the seam the plan leaves open
and this file pins, because ``build_container_spec`` needs both and
``BackendConfig`` carries no per-tool data.

The deferred gates below name the missing member when one has not been
built yet, so a red run says what to build rather than aborting
collection.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
from types import ModuleType
from typing import Any

import pytest

import tool_swap.lifecycle.states as states_module
from tool_swap.backend.base import ContainerSpec
from tool_swap.backend.fake_backend import FailureMode, FakeBackend
from tool_swap.backend.labels import container_name
from tool_swap.config.resolver import ResolvedTool, resolve_tool
from tool_swap.config.schema import BackendConfig
from tool_swap.lifecycle.states import ToolState, apply_transition
from tool_swap.proxy.probes import FakeProbe, ProbeTarget
from tool_swap.utils.clock import ManualClock

TOOL = "t1"
IMAGE = "registry.example.com/acme/model:1.0"

# A distinctive origin: a became_ready_at stamped 0.0 would pass for an
# implementation that never reads the injected clock.
CLOCK_START = 100.0


# ---------------------------------------------------------------------------
# Deferred gates: the named failures, not a collection error
# ---------------------------------------------------------------------------


def _manager_module() -> ModuleType:
    """Import ``tool_swap.lifecycle.manager`` at call time.

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


def _manager_class() -> type[Any]:
    """Return the ``LifecycleManager`` class.

    Raises:
        AssertionError: the class is missing from manager.py.
    """
    module = _manager_module()
    try:
        manager_class = module.LifecycleManager
    except AttributeError as exc:
        raise AssertionError(
            "LifecycleManager is missing from src/tool_swap/lifecycle/manager.py"
        ) from exc
    assert isinstance(manager_class, type), (
        f"LifecycleManager is not a class: {type(manager_class)!r}"
    )
    return manager_class


def _bound_method(manager: Any, name: str, purpose: str) -> Any:
    """Return one member of the manager.

    Raises:
        AssertionError: the member is missing; the message names it and
            what it is for, so a red run says what to build next.
    """
    try:
        return getattr(manager, name)
    except AttributeError as exc:
        raise AssertionError(
            f"{name} is missing from src/tool_swap/lifecycle/manager.py — {purpose}"
        ) from exc


def _ensure_ready(manager: Any) -> Any:
    """Return the ``ensure_ready`` coroutine function.

    Raises:
        AssertionError: the member is missing, or it is not a coroutine —
            the plan makes it one, because backend calls go through
            ``run_in_executor`` and every wait goes through the injected
            clock.
    """
    ensure_ready = _bound_method(
        manager, "ensure_ready", "the cold-start entry point this behaviour pins"
    )
    if not inspect.iscoroutinefunction(ensure_ready):
        raise AssertionError(
            "ensure_ready must be a coroutine: backend calls go through "
            "run_in_executor and every wait goes through the injected clock"
        )
    return ensure_ready


def _register_tool(manager: Any) -> Any:
    """Return the ``register_tool`` member.

    Raises:
        AssertionError: the member is missing.
    """
    return _bound_method(
        manager,
        "register_tool",
        "the seam that hands a tool its ResolvedTool and image so a start "
        "can build its ContainerSpec",
    )


def _state_of_method(manager: Any) -> Any:
    """Return the ``state_of`` member.

    Raises:
        AssertionError: the member is missing.
    """
    return _bound_method(
        manager, "state_of", "the read-back for the tool's per-tool runtime state"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fixtures() -> tuple[
    FakeBackend, FakeProbe, ManualClock, ResolvedTool, BackendConfig
]:
    """One of each injection, wired for a warm cold start.

    The probe is unscripted, so both phases answer true immediately and
    the happy path costs no simulated time; the clock starts at a
    distinctive origin; the config is the plain built-in backend block.
    """
    backend = FakeBackend()
    probe = FakeProbe()
    clock = ManualClock(start=CLOCK_START)
    resolved = resolve_tool(TOOL, inline={})
    backend_config = BackendConfig()
    return backend, probe, clock, resolved, backend_config


def _build_manager(
    backend: FakeBackend,
    probe: FakeProbe,
    clock: ManualClock,
    backend_config: BackendConfig,
) -> Any:
    """A manager holding exactly the injected objects; the timeout scalars
    are omitted so the constructor's built-in defaults apply."""
    return _manager_class()(
        backend,
        probe=probe,
        clock=clock,
        backend_config=backend_config,
    )


async def _register(manager: Any, resolved: ResolvedTool) -> None:
    """Register TOOL with its resolved config and image.

    Raises:
        AssertionError: ``register_tool`` does not accept the decided
            ``(tool, resolved, image=...)`` shape.
    """
    register_tool = _register_tool(manager)
    try:
        result = register_tool(TOOL, resolved, image=IMAGE)
    except TypeError as exc:
        raise AssertionError(
            f"register_tool must accept (tool, resolved, image=...): {exc}"
        ) from exc
    if inspect.iscoroutine(result):
        await result


def _call_ensure_ready(manager: Any) -> Any:
    """Invoke ``ensure_ready(TOOL)`` and return its coroutine.

    Raises:
        AssertionError: the call signature does not accept the tool name.
    """
    ensure_ready = _ensure_ready(manager)
    try:
        return ensure_ready(TOOL)
    except TypeError as exc:
        raise AssertionError(f"ensure_ready must accept the tool name: {exc}") from exc


async def _state_of(manager: Any) -> Any:
    """The tool's stored runtime state, read back through ``state_of``.

    Raises:
        AssertionError: the call signature does not accept the tool name.
    """
    state_of = _state_of_method(manager)
    try:
        state = state_of(TOOL)
    except TypeError as exc:
        raise AssertionError(f"state_of must accept the tool name: {exc}") from exc
    if inspect.iscoroutine(state):
        state = await state
    return state


def _starts(backend: FakeBackend) -> list[tuple[str, tuple[Any, ...], dict[str, Any]]]:
    """The journal's start entries.

    The journal records on entry, so it counts attempts rather than
    inferring them from ``list_managed``.
    """
    return [call for call in backend.calls if call[0] == "start"]


def _track_transitions(monkeypatch: pytest.MonkeyPatch) -> list[ToolState]:
    """Route the manager's ``apply_transition`` calls through a tracker.

    The tracker appends each to-state and then delegates to the real
    function, so the table and its logging still run. Both the manager
    module's and the states module's names are patched, since the
    implementation may bind the function either way.
    """
    observed: list[ToolState] = []

    def tracking(state: Any, to_state: ToolState, *, reason: str) -> ToolState:
        observed.append(to_state)
        return apply_transition(state, to_state, reason=reason)

    monkeypatch.setattr(states_module, "apply_transition", tracking)
    monkeypatch.setattr(_manager_module(), "apply_transition", tracking, raising=False)
    return observed


# ---------------------------------------------------------------------------
# The cold start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_ready_brings_a_stopped_tool_to_ready() -> None:
    """A STOPPED tool whose probe answers true immediately ends READY; a
    manager that never starts the container cannot reach it."""
    # Arrange
    backend, probe, clock, resolved, backend_config = _fixtures()
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    assert (await _state_of(manager)).state is ToolState.STOPPED, (
        f"the registered tool starts out {(await _state_of(manager)).state!r} — "
        "a fresh tool has no container and is STOPPED"
    )
    # Act
    await _call_ensure_ready(manager)
    # Assert
    state = await _state_of(manager)
    assert state.state is ToolState.READY, (
        f"the tool is {state.state!r} after ensure_ready — the cold "
        "start must end READY"
    )


@pytest.mark.asyncio
async def test_ensure_ready_returns_the_handle_the_backend_produced() -> None:
    """The returned handle is the one backend.start produced, and the spec
    that start received carries the tool, image and prefixed name."""
    # Arrange
    backend, probe, clock, resolved, backend_config = _fixtures()
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    handle = await _call_ensure_ready(manager)
    # Assert
    starts = _starts(backend)
    assert starts, (
        "ensure_ready reached READY without a single backend start call — "
        "there is no handle to return"
    )
    managed = backend.list_managed()
    assert len(managed) == 1, (
        f"the backend manages {len(managed)} containers — one cold start "
        "creates exactly one"
    )
    assert handle is managed[0], (
        "the returned handle is not the container the backend started — "
        "it must be backend.start's return value, identity-wise"
    )
    spec = starts[0][1][0]
    assert isinstance(spec, ContainerSpec), (
        f"backend.start received {type(spec)!r}, not a ContainerSpec — the "
        "start needs the spec built from the registered config"
    )
    assert spec.tool == TOOL, (
        f"the spec names tool {spec.tool!r} — the registered tool is {TOOL!r}"
    )
    assert spec.image == IMAGE, (
        f"the spec carries image {spec.image!r} — the registered image is {IMAGE!r}"
    )
    assert spec.name == container_name(backend_config.container_prefix, TOOL), (
        f"the spec is named {spec.name!r} — the name is the backend "
        "prefix applied to the tool"
    )


@pytest.mark.asyncio
async def test_ensure_ready_stamps_became_ready_at_from_the_injected_clock() -> None:
    """became_ready_at is the injected clock's reading when the tool became
    ready; a fixed timestamp would not match the distinctive origin this
    test starts the clock at."""
    # Arrange
    backend, probe, clock, resolved, backend_config = _fixtures()
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    await _call_ensure_ready(manager)
    # Assert
    state = await _state_of(manager)
    assert state.became_ready_at is not None, (
        "became_ready_at is still None — the tool became ready and the "
        "stamp must be written"
    )
    assert state.became_ready_at == clock.now(), (
        f"became_ready_at is {state.became_ready_at!r}, the clock reads "
        f"{clock.now()!r} — the stamp must come from the injected clock"
    )
    assert clock.now() == CLOCK_START, (
        f"simulated time is {clock.now()} — a probe answering true "
        "immediately costs no simulated time"
    )


@pytest.mark.asyncio
async def test_ensure_ready_starts_exactly_one_container_and_stops_nothing() -> None:
    """The journal shows exactly one start and no stop: the journal counts
    attempts on entry, and a happy path leaves nothing to stop."""
    # Arrange
    backend, probe, clock, resolved, backend_config = _fixtures()
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    await _call_ensure_ready(manager)
    # Assert
    starts = _starts(backend)
    assert len(starts) == 1, (
        f"the journal shows {len(starts)} start calls — one cold start "
        "makes exactly one"
    )
    assert all(call[0] != "stop" for call in backend.calls), (
        f"the journal is {[call[0] for call in backend.calls]} — the happy "
        "path starts one container and nothing asks to stop it"
    )


@pytest.mark.asyncio
async def test_ensure_ready_walks_the_full_sequence_without_skipping_a_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every move goes through apply_transition in the table's order: an
    implementation that assigns READY directly or skips LOADING leaves a
    hole in the observed sequence."""
    # Arrange
    observed = _track_transitions(monkeypatch)
    backend, probe, clock, resolved, backend_config = _fixtures()
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    await _call_ensure_ready(manager)
    # Assert
    assert observed == [ToolState.STARTING, ToolState.LOADING, ToolState.READY], (
        f"observed {observed} — the holder must move STOPPED -> STARTING -> "
        "LOADING -> READY through apply_transition; a jump straight to "
        "READY or a skipped state shows up here"
    )


# ---------------------------------------------------------------------------
# The progression is delegated, not re-implemented
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_ready_delegates_the_progression_to_drive_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The STARTING -> READY half is drive_readiness's: the manager passes
    it the stored holder, the injected probe and clock, and a target for
    the tool — and re-implementing the polling itself fails this."""
    # Arrange
    manager_module = _manager_module()
    try:
        real = manager_module.drive_readiness
    except AttributeError as exc:
        raise AssertionError(
            "drive_readiness is missing from src/tool_swap/lifecycle/"
            "manager.py — the progression it must delegate to"
        ) from exc
    seen: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def wrapping(*args: Any, **kwargs: Any) -> Any:
        seen.append((args, kwargs))
        return await real(*args, **kwargs)

    monkeypatch.setattr(manager_module, "drive_readiness", wrapping)
    backend, probe, clock, resolved, backend_config = _fixtures()
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    await _call_ensure_ready(manager)
    # Assert
    assert len(seen) == 1, (
        f"drive_readiness was called {len(seen)} times — the manager must "
        "delegate the STARTING -> LOADING -> READY progression rather than "
        "re-implement it"
    )
    call = list(seen[0][0]) + list(seen[0][1].values())
    state = await _state_of(manager)
    assert any(item is state for item in call), (
        "drive_readiness did not receive the tool's stored state — it "
        "mutates the holder in place, so the delegation must pass it"
    )
    assert any(item is probe for item in call), (
        "drive_readiness did not receive the injected probe — it polls "
        "whatever it is given, so the injection must reach it"
    )
    assert any(item is clock for item in call), (
        "drive_readiness did not receive the injected clock — every wait "
        "and deadline must read it, so the injection must reach it"
    )
    assert any(isinstance(item, ProbeTarget) and item.tool == TOOL for item in call), (
        f"drive_readiness did not receive a ProbeTarget addressed to the tool {TOOL!r}"
    )


# ---------------------------------------------------------------------------
# Idempotence — the common case in production
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_ready_on_ready_tool_starts_nothing_and_returns_same_handle() -> (
    None
):
    """A second ensure_ready on a READY tool returns the same handle,
    starts nothing and re-stamps nothing: the common case, not an edge."""
    # Arrange
    backend, probe, clock, resolved, backend_config = _fixtures()
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    first = await _call_ensure_ready(manager)
    clock.advance(50.0)
    # Act
    second = await _call_ensure_ready(manager)
    # Assert
    assert second is first, (
        "the second ensure_ready returned a different handle — a READY "
        "tool must return the one it already holds"
    )
    starts = _starts(backend)
    assert len(starts) == 1, (
        f"the journal shows {len(starts)} starts — a READY tool starts nothing"
    )
    state = await _state_of(manager)
    assert state.state is ToolState.READY
    assert state.became_ready_at == CLOCK_START, (
        f"became_ready_at moved to {state.became_ready_at!r} — a second "
        "ensure_ready must not re-record when the tool became ready"
    )


@pytest.mark.asyncio
async def test_ensure_ready_leaves_last_used_untouched() -> None:
    """last_used is written on request completion, not arrival — a stamp
    here would run a tool's TTL against a request that never ran; the
    scripted probe makes a cold-start stamp visible to the assertion."""
    # Arrange
    backend, _, clock, resolved, backend_config = _fixtures()
    # The shared probe is unscripted, so its cold start costs no simulated
    # time and a stamp written during it would store the same value as the
    # registration stamp. One scripted false health answer makes the
    # progression sleep probe_interval, so the clock has moved by the time
    # the cold start ends.
    probe = FakeProbe(script={TOOL: {"health": 1}})
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    before = (await _state_of(manager)).last_used
    # Act: the cold start
    await _call_ensure_ready(manager)
    # Assert
    assert clock.now() > before, (
        f"the scripted cold start cost no simulated time — the clock reads "
        f"{clock.now()!r}, the registration stamp is {before!r} — a stamp "
        "written during the cold start would be invisible to the next "
        "assertion"
    )
    assert (await _state_of(manager)).last_used == before, (
        "the cold start rewrote last_used — it is set on request "
        "completion, not on arrival"
    )
    # Act: the ready shortcut, after the clock has moved
    clock.advance(75.0)
    await _call_ensure_ready(manager)
    # Assert
    assert (await _state_of(manager)).last_used == before, (
        "the READY shortcut rewrote last_used — a second ensure_ready "
        "touches nothing about it"
    )


# ---------------------------------------------------------------------------
# Behaviour 14 — ten concurrent callers, one start
# ---------------------------------------------------------------------------

# One scripted false health answer forces exactly one simulated wait:
# the leader polls health, gets false, sleeps probe_interval, polls again
# and gets true; ready is unscripted and answers true immediately. The
# cold start therefore costs exactly probe_interval of simulated time —
# CLOCK_START + 1.0 = 101.0.
COALESCED_PROBE_SCRIPT = {TOOL: {"health": 1}}
COLD_START_COST = 1.0
COALESCED_CLOCK_END = CLOCK_START + COLD_START_COST
WAITERS = 10


async def _gather_ensure_ready(manager: Any, count: int = WAITERS) -> list[Any]:
    """Run *count* concurrent ``ensure_ready(TOOL)`` calls and return
    their results in caller order.

    Raises:
        AssertionError: ``ensure_ready`` is missing or does not accept
            the tool name.
    """
    ensure_ready = _ensure_ready(manager)

    async def one_call() -> Any:
        return await ensure_ready(TOOL)

    return list(await asyncio.gather(*(one_call() for _ in range(count))))


@pytest.mark.asyncio
async def test_ten_concurrent_ensure_ready_start_the_backend_exactly_once() -> None:
    """Ten concurrent callers against one STOPPED tool produce exactly
    one start entry in the journal; a cold start that is not coalesced
    starts a container per caller that still sees the tool STOPPED."""
    # Arrange
    backend = FakeBackend()
    probe = FakeProbe(script=COALESCED_PROBE_SCRIPT)
    clock = ManualClock(start=CLOCK_START)
    resolved = resolve_tool(TOOL, inline={})
    backend_config = BackendConfig()
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    await _gather_ensure_ready(manager)
    # Assert
    starts = _starts(backend)
    assert len(starts) == 1, (
        f"the journal shows {len(starts)} start calls — ten concurrent "
        "ensure_ready callers on one STOPPED tool must produce exactly "
        "one start, counted from the journal, which records on entry"
    )


@pytest.mark.asyncio
async def test_ten_concurrent_ensure_ready_return_the_same_handle() -> None:
    """All ten concurrent callers return, and every one of them holds
    the handle the single backend start produced — a caller that
    started its own container would return a different one."""
    # Arrange
    backend = FakeBackend()
    probe = FakeProbe(script=COALESCED_PROBE_SCRIPT)
    clock = ManualClock(start=CLOCK_START)
    resolved = resolve_tool(TOOL, inline={})
    backend_config = BackendConfig()
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    handles = await _gather_ensure_ready(manager)
    # Assert
    assert len(handles) == WAITERS, (
        f"only {len(handles)} of {WAITERS} callers returned — every "
        "concurrent caller must receive the handle, not an exception"
    )
    starts = _starts(backend)
    assert starts, (
        "the tool is READY without any start call in the journal — "
        "there is no backend handle the callers could share"
    )
    managed = backend.list_managed()
    assert len(managed) == 1, (
        f"the backend manages {len(managed)} containers — one coalesced "
        "cold start creates exactly one"
    )
    for handle in handles:
        assert handle is managed[0], (
            f"one caller returned {handle!r}, not the started "
            f"container {managed[0]!r} — all callers must return the "
            "single backend.start handle, identity-wise"
        )


@pytest.mark.asyncio
async def test_ten_concurrent_ensure_ready_cost_one_cold_start_in_simulated_time() -> (
    None
):
    """The clock ends exactly where one cold start ends it: concurrent
    ManualClock sleeps sum rather than overlap, so any other caller
    polling or sleeping would have advanced the clock further."""
    # Arrange
    backend = FakeBackend()
    probe = FakeProbe(script=COALESCED_PROBE_SCRIPT)
    clock = ManualClock(start=CLOCK_START)
    resolved = resolve_tool(TOOL, inline={})
    backend_config = BackendConfig()
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    await _gather_ensure_ready(manager)
    # Assert
    assert clock.now() == COALESCED_CLOCK_END, (
        f"the clock reads {clock.now()!r}, one cold start costs "
        f"{COLD_START_COST}s from {CLOCK_START} and ends at "
        f"{COALESCED_CLOCK_END} — more elapsed time means the other "
        "callers slept or polled instead of awaiting the in-flight "
        "start"
    )
    assert (await _state_of(manager)).state is ToolState.READY, (
        f"the tool is {(await _state_of(manager)).state!r} after ten "
        "concurrent ensure_ready — the coalesced cold start must end "
        "READY"
    )


@pytest.mark.asyncio
async def test_ensure_ready_after_concurrent_ready_round_starts_nothing() -> None:
    """A further round of ensure_ready calls after the tool is READY
    adds no start and returns the same handle the cold start produced —
    the READY short-circuit must serve late callers, not re-start."""
    # Arrange
    backend = FakeBackend()
    probe = FakeProbe(script=COALESCED_PROBE_SCRIPT)
    clock = ManualClock(start=CLOCK_START)
    resolved = resolve_tool(TOOL, inline={})
    backend_config = BackendConfig()
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    first_round = await _gather_ensure_ready(manager)
    # Act: the tool is READY, so a second round takes the short-circuit
    second_round = await _gather_ensure_ready(manager)
    # Assert
    starts = _starts(backend)
    assert len(starts) == 1, (
        f"the journal shows {len(starts)} starts after the READY tool "
        "was asked for again — a READY tool starts nothing"
    )
    assert len(second_round) == WAITERS, (
        f"only {len(second_round)} of {WAITERS} second-round callers "
        "returned — the READY short-circuit must serve every caller"
    )
    for handle in second_round:
        assert handle is first_round[0], (
            f"the second round returned {handle!r}, not the handle the "
            "cold start produced — a READY tool returns the handle it "
            "already holds"
        )


@pytest.mark.asyncio
async def test_failed_single_start_reaches_all_callers_once() -> None:
    """When the single coalesced start refuses, all ten callers receive
    that one start's failure — one shared failure, not nine ValueErrors
    and not ten attempts in the journal."""
    # Arrange: the backend refuses this tool's start, repeatedly
    backend = FakeBackend(script={TOOL: FailureMode.FAIL_TO_START})
    probe = FakeProbe(script=COALESCED_PROBE_SCRIPT)
    clock = ManualClock(start=CLOCK_START)
    resolved = resolve_tool(TOOL, inline={})
    backend_config = BackendConfig()
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    outcomes = await asyncio.gather(
        *(_call_ensure_ready(manager) for _ in range(WAITERS)),
        return_exceptions=True,
    )
    # Assert: every caller saw a failure
    assert len(outcomes) == WAITERS, (
        f"only {len(outcomes)} of {WAITERS} callers returned an outcome — "
        "every concurrent caller must be reached"
    )
    failures = [o for o in outcomes if isinstance(o, BaseException)]
    assert len(failures) == WAITERS, (
        f"{WAITERS - len(failures)} of {WAITERS} callers returned a "
        "handle although the start refused — a refused start must reach "
        "every caller, not some of them"
    )
    # Assert: one shared failure — one type, one message
    assert all(type(f) is type(failures[0]) for f in failures), (
        f"the callers received {sorted({type(f).__name__ for f in failures})} "
        "— every caller must receive the same failure type"
    )
    assert all(str(f) == str(failures[0]) for f in failures), (
        "the callers received different failure messages — ten callers "
        "awaiting one failed start must all receive that start's failure"
    )
    # Assert: the journal shows one refused attempt, not one per caller
    starts = _starts(backend)
    assert len(starts) == 1, (
        f"the journal shows {len(starts)} start attempts — the ten "
        "callers must coalesce into a single start, even a failing one"
    )

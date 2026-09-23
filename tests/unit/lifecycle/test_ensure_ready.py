"""Pins the cold start of ``LifecycleManager.ensure_ready`` (m2b plan
§3 behaviours 13, 14, 15 and 16, §1.3, §1.4): a ``STOPPED`` tool whose
probe answers true immediately walks ``STOPPED -> STARTING -> LOADING
-> READY`` through the transition table, the backend is started
exactly once, the returned handle is the one ``backend.start``
produced, ``became_ready_at`` is stamped from the injected clock, and a
second ``ensure_ready`` on an already-``READY`` tool starts nothing,
re-stamps nothing and returns the same handle. Behaviour 14 adds the
coalesced cold start: ten concurrent callers start the backend exactly
once, all ten receive the same handle, the simulated elapsed time is
what one cold start costs (the proof that the other callers await the
in-flight start rather than poll or sleep), a failed single start
reaches all ten callers as one shared failure, and a round after
``READY`` starts nothing. Behaviour 15 pins the start-failure path:
the tool ends ``FAILED`` with the taxonomy member's ``message`` in
``last_error`` verbatim, no handle, the transition logged with the
reason, the refusal re-raised to every caller, the name-conflict
member's message reaching ``last_error`` unaltered too, and
``ensure_ready`` on a ``FAILED`` tool retrying through the
``FAILED -> STARTING`` edge with the refusal repeating. Behaviour 16
pins the readiness-timeout path: a probe whose ``ready`` never answers
ends the tool ``FAILED`` naming ``ready_timeout`` and the elapsed
simulated seconds, the mirror case with a ``health`` that never
answers naming ``start_timeout``, the started container stopped on the
way to ``FAILED``, the simulated elapsed time equal to the one
deadline that ran (not the two deadlines chained), the handle cleared,
and the timeout re-raised as a member of the readiness timeout family
rather than the backend taxonomy. Behaviour 17 pins the cancellation
contract of the coalesced cold start: a caller cancelled mid-start
raises ``CancelledError`` and no one else does, the start keeps running
for the remaining callers, and when every caller walks away the cold
start still runs to completion and records its outcome, so a started
container is never left without a recorded handle. Behaviour 18 pins
that backend calls run in an executor, never on the event loop: a start
parked on a threading.Event leaves the loop free for other work, a
second tool's cold start is attempted while the first tool's start is
still blocked, a readiness-timeout's stop is off the loop too, and an
exception raised in the backend's thread reaches the await as the same
instance, so behaviour 15's FAILED mapping and verbatim last_error hold
across the hop. The blocking backend is a double in this file, not a
FakeBackend mode, and every thread wait is budget-bounded so a mistake
fails rather than hangs.

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
import logging
import threading
import uuid
from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest

import tool_swap.lifecycle.states as states_module
from tool_swap.backend.base import ContainerHandle, ContainerSpec, ContainerState
from tool_swap.backend.errors import (
    BackendError,
    ContainerNameConflictError,
    ContainerStartError,
)
from tool_swap.backend.fake_backend import FailureMode, FakeBackend
from tool_swap.backend.labels import container_name
from tool_swap.config.defaults import BUILT_IN_DEFAULTS
from tool_swap.config.resolver import ResolvedTool, resolve_tool
from tool_swap.config.schema import BackendConfig
from tool_swap.lifecycle.manager import ReadyTimeoutError, StartTimeoutError
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


# ---------------------------------------------------------------------------
# Behaviour 15 — a start failure yields FAILED with the taxonomy reason
# ---------------------------------------------------------------------------


async def _drive(manager: Any) -> Any:
    """One ``ensure_ready(TOOL)``: the handle returned, or the exception
    raised, so a failure test holds the backend's own error instance
    for the verbatim comparisons.

    Raises:
        AssertionError: ``ensure_ready`` is missing or does not accept
            the tool name.
    """
    try:
        return await _call_ensure_ready(manager)
    except BaseException as exc:
        return exc


def _failed_transition_records(
    caplog: pytest.LogCaptureFixture,
) -> list[logging.LogRecord]:
    """The state machine's records whose to-state is FAILED."""
    return [
        record
        for record in caplog.records
        if record.name == "tool_swap.lifecycle.states"
        and getattr(record, "to_state", None) is ToolState.FAILED
    ]


@pytest.mark.asyncio
async def test_failed_start_marks_the_tool_failed_with_the_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A refused start ends the tool FAILED with the ContainerStartError's
    message in last_error verbatim, no handle, no container, the
    transition logged with the reason, and the refusal re-raised: FAILED
    without the reason would leave an operator guessing why it is down."""
    # Arrange: this tool's starts are refused, repeatedly
    _, probe, clock, resolved, backend_config = _fixtures()
    backend = FakeBackend(script={TOOL: FailureMode.FAIL_TO_START})
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    with caplog.at_level(logging.INFO):
        outcome = await _drive(manager)
    # Assert: the refusal reached the caller, re-raised
    assert isinstance(outcome, ContainerStartError), (
        f"ensure_ready returned {type(outcome).__name__} for a refused "
        "start — the backend's refusal must be re-raised to the caller, "
        "not swallowed or replaced by a sentinel"
    )
    # Assert: the tool is FAILED, not left where the start died
    state = await _state_of(manager)
    assert state.state is ToolState.FAILED, (
        f"the tool sits in {state.state!r} after a refused start — a start "
        "failure must end it FAILED, not leave it in the phase it died in"
    )
    # Assert: the reason is the taxonomy member's message verbatim
    assert state.last_error == outcome.message, (
        f"last_error is {state.last_error!r}, the refusal's message is "
        f"{outcome.message!r} — the reason must be the taxonomy member's "
        "message verbatim, with no prefix, wrapping or reformatting"
    )
    assert state.last_error != str(outcome), (
        "last_error equals str(error), which appends the remedy — the "
        "message field alone must be recorded"
    )
    # Assert: no container exists, so no handle can
    assert state.handle is None, (
        f"the tool holds handle {state.handle!r} after a start that "
        "created nothing — no container, no handle"
    )
    assert backend.list_managed() == [], (
        f"the backend manages {len(backend.list_managed())} container(s) "
        "after a refused start — the refusal creates nothing"
    )
    # Assert: the move into FAILED was logged once, with the reason
    records = _failed_transition_records(caplog)
    assert len(records) == 1, (
        f"the move into FAILED logged {len(records)} record(s) — the "
        "transition must log exactly one INFO record"
    )
    record = records[0]
    assert record.levelno == logging.INFO, (
        f"the FAILED transition was logged at {record.levelname} — the "
        "transition log is INFO"
    )
    assert getattr(record, "tool", None) == TOOL, (
        f"the FAILED record carries tool={getattr(record, 'tool', None)!r} — "
        "the structured fields must name the tool"
    )
    assert getattr(record, "from_state", None) is ToolState.STARTING, (
        f"the FAILED record carries "
        f"from_state={getattr(record, 'from_state', None)!r} — a start "
        "failure moves the tool from STARTING"
    )
    assert getattr(record, "reason", None) == outcome.message, (
        f"the FAILED record carries "
        f"reason={getattr(record, 'reason', None)!r}, the message is "
        f"{outcome.message!r} — the transition into FAILED is logged with "
        "the taxonomy message verbatim"
    )
    assert getattr(record, "reason", None) != str(outcome), (
        "the logged reason equals str(error), which appends the remedy — "
        "the transition is logged with the message field, not the exception"
    )


@pytest.mark.asyncio
async def test_name_conflict_reaches_last_error_unaltered() -> None:
    """A taken container name is a different taxonomy member: its message
    reaches last_error unaltered and the member is re-raised, so covering
    only the scripted start error would leave this path unpinned."""
    # Arrange: a record already holds the tool's container name, so the
    # manager's start takes the backend's native name-conflict refusal
    _, probe, clock, resolved, backend_config = _fixtures()
    backend = FakeBackend()
    seed = ContainerSpec(
        tool=TOOL,
        name=container_name(backend_config.container_prefix, TOOL),
        image=IMAGE,
        gpu_runtime="cpu",
        container_port=8000,
    )
    backend.start(seed)
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    outcome = await _drive(manager)
    # Assert: the conflict member reached the caller
    assert isinstance(outcome, ContainerNameConflictError), (
        f"ensure_ready returned {type(outcome).__name__} for a taken "
        "container name — the backend's name-conflict refusal must be "
        "re-raised"
    )
    # Assert: FAILED with the conflict's message verbatim
    state = await _state_of(manager)
    assert state.state is ToolState.FAILED, (
        f"the tool sits in {state.state!r} after a name-conflict refusal — "
        "a start failure must end it FAILED"
    )
    assert state.last_error == outcome.message, (
        f"last_error is {state.last_error!r}, the conflict's message is "
        f"{outcome.message!r} — the name-conflict member's message must "
        "reach last_error unaltered"
    )
    assert state.last_error != str(outcome), (
        "last_error equals str(error), which appends the remedy — the "
        "message field alone must be recorded"
    )
    assert state.handle is None, (
        f"the tool holds handle {state.handle!r} — the refused start created nothing"
    )


@pytest.mark.asyncio
async def test_ensure_ready_on_a_failed_tool_retries_via_the_failed_to_starting_edge(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ensure_ready on a FAILED tool attempts a fresh start through the
    FAILED -> STARTING edge and re-raises the same refusal: a guard that
    serves only STOPPED and READY blocks the retry and leaves a failed
    tool unretryable until a manual reset."""
    # Arrange
    _, probe, clock, resolved, backend_config = _fixtures()
    backend = FakeBackend(script={TOOL: FailureMode.FAIL_TO_START})
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act: the first attempt is refused
    with caplog.at_level(logging.INFO):
        first = await _drive(manager)
    assert isinstance(first, ContainerStartError), (
        f"the first attempt raised {type(first).__name__} — the scripted "
        "tool must refuse to start"
    )
    state = await _state_of(manager)
    assert state.state is ToolState.FAILED, (
        f"the tool sits in {state.state!r} after the refused start — the "
        "retry needs it FAILED, which records the failure"
    )
    # Act: the retry
    with caplog.at_level(logging.INFO):
        second = await _drive(manager)
    # Assert: the retry was a fresh attempt refused again
    assert isinstance(second, ContainerStartError), (
        f"the retry raised {type(second).__name__} — a FAILED tool must "
        "retry through the FAILED -> STARTING edge and re-raise the "
        "refusal; a STOPPED/READY-only guard blocks it"
    )
    assert second.message == first.message, (
        f"the retry's refusal carries {second.message!r}, the first "
        f"carried {first.message!r} — the refusal is not one-shot, so a "
        "retry loop cannot silently succeed"
    )
    starts = _starts(backend)
    assert len(starts) == 2, (
        f"the journal shows {len(starts)} start attempts — the retry must "
        "attempt a fresh start, and the refusal must repeat on it"
    )
    # Assert: the log records both attempts and both refusals
    records = [
        record
        for record in caplog.records
        if record.name == "tool_swap.lifecycle.states"
    ]
    assert len(records) == 4, (
        f"the transition log shows {len(records)} record(s) — the two "
        "attempts and the two refusals move the tool STOPPED -> STARTING, "
        "into FAILED, back to STARTING, into FAILED again"
    )
    assert records[1].to_state is ToolState.FAILED, (
        f"the second record moves to {records[1].to_state!r} — the "
        "refusal must be recorded as the move into FAILED"
    )
    assert getattr(records[2], "from_state", None) is ToolState.FAILED, (
        f"the retry logged "
        f"from_state={getattr(records[2], 'from_state', None)!r} — the "
        "legal retry edge starts from FAILED"
    )
    assert records[2].to_state is ToolState.STARTING, (
        f"the retry logged to_state={records[2].to_state!r} — the retry "
        "moves the tool back to STARTING"
    )
    assert getattr(records[3], "from_state", None) is ToolState.STARTING, (
        f"the fourth record logged "
        f"from_state={getattr(records[3], 'from_state', None)!r} — the "
        "retry's refusal moves the tool out of STARTING"
    )
    assert records[3].to_state is ToolState.FAILED, (
        f"the fourth record moves to {records[3].to_state!r} — the retry's "
        "refusal must be recorded as the second move into FAILED; a "
        "missing record here means the refusal was silently swallowed"
    )
    assert getattr(records[3], "reason", None) == first.message, (
        f"the fourth record carries "
        f"reason={getattr(records[3], 'reason', None)!r}, the refusal's "
        f"message is {first.message!r} — the retry's refusal is logged "
        "with the taxonomy message verbatim"
    )


@pytest.mark.asyncio
async def test_coalesced_start_failure_marks_the_tool_failed_once() -> None:
    """Ten concurrent callers on a refused start all receive the
    backend's own error — no sentinel, no guard error — the single start
    is journaled once, and the tool is FAILED with the refusal recorded:
    behaviour 14's coalescing must survive the failure path intact."""
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
    # Assert: every caller received the backend's own error
    assert all(isinstance(o, BackendError) for o in outcomes), (
        f"the callers received {sorted({type(o).__name__ for o in outcomes})} "
        "— every caller must receive the backend's refusal re-raised, "
        "not a sentinel or a guard error"
    )
    assert all(o.message == outcomes[0].message for o in outcomes), (
        "the callers received different failure messages — ten callers "
        "awaiting one failed start must all receive that start's failure"
    )
    starts = _starts(backend)
    assert len(starts) == 1, (
        f"the journal shows {len(starts)} start attempts — the failed "
        "coalesced start must be attempted once"
    )
    # Assert: FAILED once, with the reason
    state = await _state_of(manager)
    assert state.state is ToolState.FAILED, (
        f"the tool sits in {state.state!r} after the coalesced start "
        "failed — the failure must end it FAILED, once, not per caller"
    )
    assert state.last_error == outcomes[0].message, (
        f"last_error is {state.last_error!r}, the shared failure carries "
        f"{outcomes[0].message!r} — the refusal must be recorded"
    )


@pytest.mark.asyncio
async def test_a_caller_arriving_after_a_failed_start_receives_the_refusal() -> None:
    """A caller arriving after the coalesced start has already failed is
    served a fresh attempt refused again with the same message — not a
    stale handle, not a sentinel, and not a hang on the dead pending
    slot the failure cleared."""
    # Arrange
    _, probe, clock, resolved, backend_config = _fixtures()
    backend = FakeBackend(script={TOOL: FailureMode.FAIL_TO_START})
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act: the first attempt fails, then a late caller arrives
    first = await _drive(manager)
    assert isinstance(first, ContainerStartError), (
        f"the first attempt raised {type(first).__name__} — the scripted "
        "tool must refuse to start"
    )
    second = await _drive(manager)
    # Assert: the late caller received the refusal again
    assert isinstance(second, ContainerStartError), (
        f"the late caller received {type(second).__name__} — a FAILED "
        "tool must be served a fresh attempt that re-raises the refusal; "
        "a sentinel return or a STOPPED/READY-only guard blocks it"
    )
    assert second.message == first.message, (
        f"the late caller's refusal carries {second.message!r}, the first "
        f"carried {first.message!r} — the refusal must repeat, not "
        "resolve itself"
    )
    starts = _starts(backend)
    assert len(starts) == 2, (
        f"the journal shows {len(starts)} start attempts — the late "
        "caller's fresh attempt must be journaled; serving the caller "
        "from a dead pending task would journal no start"
    )
    assert (await _state_of(manager)).state is ToolState.FAILED, (
        f"the tool sits in {(await _state_of(manager)).state!r} after the "
        "late caller's failed attempt — the refusal ends it FAILED again"
    )


# ---------------------------------------------------------------------------
# Behaviour 16 — a readiness timeout yields FAILED naming the deadline
# ---------------------------------------------------------------------------

# The built-in deadline values, read from defaults.py so the timeout
# arithmetic below cannot drift from the source of truth.
START_TIMEOUT: float = float(BUILT_IN_DEFAULTS["start_timeout"])
READY_TIMEOUT: float = float(BUILT_IN_DEFAULTS["ready_timeout"])

# The readiness timeout's own rendering, which names the deadline that
# ran and the simulated seconds it ran: unlike behaviour 15's
# backend-authored message, this text is the manager's own, and it must
# carry both facts so an operator tells a hung ready from a hung start.
START_TIMEOUT_TEXT = f"readiness start_timeout elapsed after {START_TIMEOUT}s"
READY_TIMEOUT_TEXT = f"readiness ready_timeout elapsed after {READY_TIMEOUT}s"

# Never-true probe scripts, one per phase.
READY_NEVER_TRUE = {TOOL: {"ready": None}}
HEALTH_NEVER_TRUE = {TOOL: {"health": None}}


def _stops(backend: FakeBackend) -> list[tuple[str, tuple[Any, ...], dict[str, Any]]]:
    """The journal's stop entries, mirroring ``_starts``."""
    return [call for call in backend.calls if call[0] == "stop"]


@pytest.mark.asyncio
async def test_ready_timeout_ends_the_tool_failed_naming_the_deadline_and_elapsed() -> (
    None
):
    """A ready probe that never answers ends the tool FAILED with
    last_error naming ready_timeout and its elapsed seconds, the timeout
    re-raised rather than mapped onto the backend taxonomy."""
    # Arrange: health answers immediately, ready never does
    backend, _, clock, resolved, backend_config = _fixtures()
    probe = FakeProbe(script=READY_NEVER_TRUE)
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    outcome = await _drive(manager)
    # Assert: the raised error is the ready timeout itself
    assert type(outcome) is ReadyTimeoutError, (
        f"ensure_ready raised {type(outcome).__name__} — a ready timeout "
        "must be re-raised as the timeout itself, since 'never became "
        "ready' and 'refused to start' have different remedies"
    )
    assert not isinstance(outcome, BackendError), (
        f"ensure_ready raised {type(outcome).__name__}, a BackendError — "
        "a readiness timeout is not a backend refusal and must stay "
        "distinguishable from one"
    )
    assert outcome.deadline == "ready_timeout", (
        f"the raised timeout names deadline {outcome.deadline!r} — the "
        "ready window is the one that ran out"
    )
    assert outcome.elapsed == READY_TIMEOUT, (
        f"the raised timeout ran {outcome.elapsed!r}s — the ready window "
        f"runs the built-in {READY_TIMEOUT!r}s"
    )
    # Assert: the tool is FAILED, not left in the phase it hung in
    state = await _state_of(manager)
    assert state.state is ToolState.FAILED, (
        f"the tool sits in {state.state!r} after the ready timeout — it "
        "must end FAILED, not be left LOADING where the probe hung"
    )
    # Assert: the reason names the deadline and the elapsed seconds, exactly
    assert state.last_error == READY_TIMEOUT_TEXT, (
        f"last_error is {state.last_error!r}, the ready timeout's own "
        f"rendering is {READY_TIMEOUT_TEXT!r} — the text must name the "
        "deadline that ran and the simulated seconds it ran"
    )
    assert state.last_error == str(outcome), (
        f"last_error is {state.last_error!r}, the raised error renders "
        f"{str(outcome)!r} — the recorded reason and the raised error "
        "must agree on the wording"
    )
    assert state.became_ready_at is None, (
        "became_ready_at is stamped although the tool never became ready"
    )
    # Assert: the cost is the ready window alone, not both windows chained
    assert clock.now() == CLOCK_START + READY_TIMEOUT, (
        f"simulated time is {clock.now()} — health answered at "
        f"{CLOCK_START} and the ready window runs {READY_TIMEOUT}s, so "
        "the cold start costs the ready window alone"
    )
    assert clock.now() != CLOCK_START + START_TIMEOUT + READY_TIMEOUT, (
        f"simulated time is {clock.now()} — the two deadlines are "
        "independent, and chaining them would cost their sum"
    )


@pytest.mark.asyncio
async def test_start_timeout_ends_the_tool_failed_naming_the_deadline_and_elapsed() -> (
    None
):
    """A health probe that never answers ends the tool FAILED naming
    start_timeout and its elapsed seconds, the timeout re-raised rather
    than mapped onto the backend taxonomy."""
    # Arrange: health never answers, so the start window runs out
    backend, _, clock, resolved, backend_config = _fixtures()
    probe = FakeProbe(script=HEALTH_NEVER_TRUE)
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    outcome = await _drive(manager)
    # Assert: the raised error is the start timeout itself
    assert type(outcome) is StartTimeoutError, (
        f"ensure_ready raised {type(outcome).__name__} — a start timeout "
        "must be re-raised as the timeout itself, since 'never became "
        "ready' and 'refused to start' have different remedies"
    )
    assert not isinstance(outcome, BackendError), (
        f"ensure_ready raised {type(outcome).__name__}, a BackendError — "
        "a readiness timeout is not a backend refusal and must stay "
        "distinguishable from one"
    )
    assert outcome.deadline == "start_timeout", (
        f"the raised timeout names deadline {outcome.deadline!r} — the "
        "start window is the one that ran out"
    )
    assert outcome.elapsed == START_TIMEOUT, (
        f"the raised timeout ran {outcome.elapsed!r}s — the start window "
        f"runs the built-in {START_TIMEOUT!r}s"
    )
    # Assert: the tool is FAILED, not left in the phase it hung in
    state = await _state_of(manager)
    assert state.state is ToolState.FAILED, (
        f"the tool sits in {state.state!r} after the start timeout — it "
        "must end FAILED, not be left STARTING where the probe hung"
    )
    # Assert: the reason names the deadline and the elapsed seconds, exactly
    assert state.last_error == START_TIMEOUT_TEXT, (
        f"last_error is {state.last_error!r}, the start timeout's own "
        f"rendering is {START_TIMEOUT_TEXT!r} — the text must name the "
        "deadline that ran and the simulated seconds it ran"
    )
    assert state.last_error == str(outcome), (
        f"last_error is {state.last_error!r}, the raised error renders "
        f"{str(outcome)!r} — the recorded reason and the raised error "
        "must agree on the wording"
    )
    assert state.became_ready_at is None, (
        "became_ready_at is stamped although the tool never became ready"
    )
    # Assert: the cost is the start window alone, not both windows chained
    assert clock.now() == CLOCK_START + START_TIMEOUT, (
        f"simulated time is {clock.now()} — the start window runs "
        f"{START_TIMEOUT}s from {CLOCK_START}, and it is the only window "
        "that ran"
    )
    assert clock.now() != CLOCK_START + START_TIMEOUT + READY_TIMEOUT, (
        f"simulated time is {clock.now()} — the two deadlines are "
        "independent, and chaining them would cost their sum"
    )


@pytest.mark.asyncio
async def test_ready_timeout_stops_the_started_container_and_clears_the_handle() -> (
    None
):
    """The container a ready timeout hung in is stopped on the way to
    FAILED and its handle cleared — a failed cold start must not leave a
    container resident, or it leaks a slot."""
    # Arrange
    backend, _, clock, resolved, backend_config = _fixtures()
    probe = FakeProbe(script=READY_NEVER_TRUE)
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    outcome = await _drive(manager)
    assert isinstance(outcome, ReadyTimeoutError), (
        f"ensure_ready raised {type(outcome).__name__} — the scripted "
        "probe must run the ready window to its timeout"
    )
    # Assert: the journal shows one start and one stop, of the same handle
    starts = _starts(backend)
    assert len(starts) == 1, (
        f"the journal shows {len(starts)} start calls — the cold start "
        "started the container before it hung"
    )
    stops = _stops(backend)
    assert len(stops) == 1, (
        f"the journal shows {len(stops)} stop calls — the hung container "
        "must be stopped on the way to FAILED, or the failed cold start "
        "leaks a slot"
    )
    stopped = stops[0][1][0]
    managed = backend.list_managed()
    assert stopped is managed[0], (
        f"the stop names handle {stopped!r}, start produced "
        f"{managed[0]!r} — the container being stopped is the one that "
        "was started"
    )
    assert backend.inspect(managed[0]).state is ContainerState.EXITED, (
        f"the container is {backend.inspect(managed[0]).state!r} after "
        "the timeout — a tool that never became ready leaves no running "
        "container"
    )
    # Assert: the holder no longer claims the stopped container
    state = await _state_of(manager)
    assert state.handle is None, (
        f"the tool still holds handle {state.handle!r} — the container "
        "it refers to has been stopped, so the holder must not claim it"
    )


@pytest.mark.asyncio
async def test_start_timeout_stops_the_started_container_and_clears_the_handle() -> (
    None
):
    """The mirror case: the container a start timeout hung in is stopped
    on the way to FAILED and its handle cleared, even though the tool
    never left STARTING."""
    # Arrange
    backend, _, clock, resolved, backend_config = _fixtures()
    probe = FakeProbe(script=HEALTH_NEVER_TRUE)
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    outcome = await _drive(manager)
    assert isinstance(outcome, StartTimeoutError), (
        f"ensure_ready raised {type(outcome).__name__} — the scripted "
        "probe must run the start window to its timeout"
    )
    # Assert: the journal shows one start and one stop, of the same handle
    starts = _starts(backend)
    assert len(starts) == 1, (
        f"the journal shows {len(starts)} start calls — the cold start "
        "started the container before it hung"
    )
    stops = _stops(backend)
    assert len(stops) == 1, (
        f"the journal shows {len(stops)} stop calls — the hung container "
        "must be stopped on the way to FAILED, or the failed cold start "
        "leaks a slot"
    )
    stopped = stops[0][1][0]
    managed = backend.list_managed()
    assert stopped is managed[0], (
        f"the stop names handle {stopped!r}, start produced "
        f"{managed[0]!r} — the container being stopped is the one that "
        "was started"
    )
    assert backend.inspect(managed[0]).state is ContainerState.EXITED, (
        f"the container is {backend.inspect(managed[0]).state!r} after "
        "the timeout — a tool that never became ready leaves no running "
        "container"
    )
    # Assert: the holder no longer claims the stopped container
    state = await _state_of(manager)
    assert state.handle is None, (
        f"the tool still holds handle {state.handle!r} — the container "
        "it refers to has been stopped, so the holder must not claim it"
    )


@pytest.mark.asyncio
async def test_ready_timeout_records_the_loading_to_failed_transition(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The holder passes through LOADING before failing: the observed
    moves are STARTING, LOADING, FAILED, and the move into FAILED is
    logged from LOADING with the timeout's own text as the reason."""
    # Arrange
    observed = _track_transitions(monkeypatch)
    backend, _, clock, resolved, backend_config = _fixtures()
    probe = FakeProbe(script=READY_NEVER_TRUE)
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    with caplog.at_level(logging.INFO):
        outcome = await _drive(manager)
    assert isinstance(outcome, ReadyTimeoutError), (
        f"ensure_ready raised {type(outcome).__name__} — the scripted "
        "probe must run the ready window to its timeout"
    )
    # Assert: every move goes through the table, ending FAILED from LOADING
    assert observed == [ToolState.STARTING, ToolState.LOADING, ToolState.FAILED], (
        f"observed {observed} — the holder moves STOPPED -> STARTING -> "
        "LOADING -> FAILED; a timeout in the ready phase fails the tool "
        "from LOADING, not from STARTING"
    )
    # Assert: the move into FAILED logged once, from LOADING, with the text
    records = _failed_transition_records(caplog)
    assert len(records) == 1, (
        f"the move into FAILED logged {len(records)} record(s) — the "
        "transition must log exactly one INFO record"
    )
    record = records[0]
    assert getattr(record, "from_state", None) is ToolState.LOADING, (
        f"the FAILED record carries "
        f"from_state={getattr(record, 'from_state', None)!r} — the ready "
        "timeout fails the tool out of LOADING"
    )
    assert getattr(record, "reason", None) == READY_TIMEOUT_TEXT, (
        f"the FAILED record carries "
        f"reason={getattr(record, 'reason', None)!r} — the move into "
        "FAILED is logged with the timeout's own text as the reason"
    )


@pytest.mark.asyncio
async def test_start_timeout_records_the_starting_to_failed_transition(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The mirror case: the holder never reaches LOADING, so the observed
    moves are STARTING and FAILED, and the move into FAILED is logged
    from STARTING with the timeout's own text as the reason."""
    # Arrange
    observed = _track_transitions(monkeypatch)
    backend, _, clock, resolved, backend_config = _fixtures()
    probe = FakeProbe(script=HEALTH_NEVER_TRUE)
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    with caplog.at_level(logging.INFO):
        outcome = await _drive(manager)
    assert isinstance(outcome, StartTimeoutError), (
        f"ensure_ready raised {type(outcome).__name__} — the scripted "
        "probe must run the start window to its timeout"
    )
    # Assert: every move goes through the table, ending FAILED from STARTING
    assert observed == [ToolState.STARTING, ToolState.FAILED], (
        f"observed {observed} — the holder moves STOPPED -> STARTING -> "
        "FAILED; a timeout in the start phase fails the tool from "
        "STARTING, having never answered health"
    )
    # Assert: the move into FAILED logged once, from STARTING, with the text
    records = _failed_transition_records(caplog)
    assert len(records) == 1, (
        f"the move into FAILED logged {len(records)} record(s) — the "
        "transition must log exactly one INFO record"
    )
    record = records[0]
    assert getattr(record, "from_state", None) is ToolState.STARTING, (
        f"the FAILED record carries "
        f"from_state={getattr(record, 'from_state', None)!r} — the start "
        "timeout fails the tool out of STARTING"
    )
    assert getattr(record, "reason", None) == START_TIMEOUT_TEXT, (
        f"the FAILED record carries "
        f"reason={getattr(record, 'reason', None)!r} — the move into "
        "FAILED is logged with the timeout's own text as the reason"
    )


# ---------------------------------------------------------------------------
# Behaviour 17 — a cancelled caller neither kills the start nor orphans
# the container
# ---------------------------------------------------------------------------

# The start phase needs two scripted false health answers before it
# answers true; ready is unscripted and answers true immediately. The
# cold start therefore sleeps probe_interval twice — it crosses at
# least one interval between the cancellation below and completion, so
# the test cannot pass by cancelling before the start really began.
CANCELLED_START_SCRIPT = {TOOL: {"health": 2}}
CANCELLED_START_COST = 2.0


async def _drain_to_terminal(manager: Any, clock: Any, *, max_steps: int = 1000) -> Any:
    """Yield loop steps until the tool reaches a terminal state.

    Each step is one ``clock.sleep(0.0)`` — it advances no simulated
    time and yields once via ``asyncio.sleep(0)`` — so the orphaned
    cold-start task, which makes progress only on loop steps, keeps
    running while the test waits. That is the whole pin: with no
    caller left, only the loop running the task can record its
    outcome, and no real-time sleep stands in for it.

    Returns:
        The tool's state holder once it is terminal.

    Raises:
        AssertionError: the tool is not terminal after ``max_steps``
            loop steps — the orphaned start never finished.
    """
    for _ in range(max_steps):
        state = await _state_of(manager)
        if state.state in (
            ToolState.READY,
            ToolState.FAILED,
            ToolState.STOPPED,
        ):
            return state
        await clock.sleep(0.0)
    raise AssertionError(
        "the tool is still in "
        f"{(await _state_of(manager)).state!r} after {max_steps} loop steps — "
        "the orphaned cold start never finished recording its outcome"
    )


async def _cancelled_caller(manager: Any, clock: Any) -> BaseException:
    """One caller cancelled mid-cold-start; the exception it raises.

    The wait steps the loop with ``clock.sleep(0.0)`` — one yield, no
    simulated time — until the first health poll is journaled. The
    caller's leader path (lock, STARTING move, start call) runs before
    its first yield, so that journal entry proves the start is in
    flight and the cold task is parked in its first poll sleep — the
    cancellation lands mid-start, not before it. Awaiting the caller
    directly would miss the window: the start completes a few loop
    steps later and the cancel would hit a finished task.

    Returns:
        The exception the cancelled caller raised.

    Raises:
        AssertionError: the cancelled caller returned normally.
    """
    ensure_ready = _ensure_ready(manager)
    caller = asyncio.create_task(ensure_ready(TOOL))
    while sum(1 for method, _ in manager.probe.calls if method == "health") < 1:
        await clock.sleep(0.0)
    caller.cancel()
    try:
        await caller
    except BaseException as raised:
        return raised
    raise AssertionError(
        "the cancelled caller returned normally — a Task.cancel must surface "
        "as an exception to the caller"
    )


@pytest.mark.asyncio
async def test_cancelled_caller_raises_cancelled_error_start_continues() -> None:
    """A caller cancelled mid-cold-start raises CancelledError while the
    start keeps running for the remaining caller: the start must not die
    with a single waiter."""
    # Arrange
    backend = FakeBackend()
    probe = FakeProbe(script=CANCELLED_START_SCRIPT)
    clock = ManualClock(start=CLOCK_START)
    resolved = resolve_tool(TOOL, inline={})
    backend_config = BackendConfig()
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act: caller one is cancelled inside the start window
    raised = await _cancelled_caller(manager, clock)
    # Assert: the caller raised CancelledError, and only it could have
    assert isinstance(raised, asyncio.CancelledError), (
        f"the cancelled caller raised {type(raised).__name__} — the "
        "cancellation must surface as CancelledError, not be mapped to "
        "a fault that never happened"
    )
    # Assert: the surviving caller still gets a READY tool
    caller_two = asyncio.create_task(_call_ensure_ready(manager))
    handle = await caller_two
    # Assert: the tool is READY holding the started container
    state = await _state_of(manager)
    assert state.state is ToolState.READY, (
        f"the tool is {state.state!r} after its only waiting caller was "
        "cancelled — the start must run to completion for the caller "
        "that stayed"
    )
    managed = backend.list_managed()
    assert len(managed) == 1, (
        f"the backend manages {len(managed)} containers — one start creates exactly one"
    )
    assert handle is managed[0], (
        f"the caller got {handle!r}, not the started container "
        f"{managed[0]!r} — the surviving caller must receive the "
        "coalesced start's handle"
    )
    # Assert: the journal shows the start ran to completion
    starts = _starts(backend)
    assert len(starts) == 1, (
        f"the journal shows {len(starts)} starts — a cancelled caller "
        "must neither add a start nor kill the one in flight"
    )
    assert len(probe.calls) >= 3, (
        f"the probe was asked {len(probe.calls)} time(s) — after the "
        "cancellation the start must still poll to completion, which "
        "needs the scripted false answers plus the true one"
    )
    # Assert: simulated time costs one cold start's worth, not two
    assert clock.now() == CLOCK_START + CANCELLED_START_COST, (
        f"the clock reads {clock.now()!r} — one cold start costs "
        f"{CANCELLED_START_COST}s from {CLOCK_START}, so the start ran "
        "exactly once to completion"
    )


@pytest.mark.asyncio
async def test_every_caller_cancelled_start_still_records_its_outcome() -> None:
    """With no waiters left, the cold start still runs to completion:
    the tool reaches a terminal state and the started container's handle
    is recorded — a started container nobody recorded is an orphan."""
    # Arrange
    backend = FakeBackend()
    probe = FakeProbe(script=CANCELLED_START_SCRIPT)
    clock = ManualClock(start=CLOCK_START)
    resolved = resolve_tool(TOOL, inline={})
    backend_config = BackendConfig()
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act: the only caller is cancelled inside the start window
    raised = await _cancelled_caller(manager, clock)
    assert isinstance(raised, asyncio.CancelledError), (
        f"the cancelled caller raised {type(raised).__name__} — the "
        "cancellation must surface as CancelledError"
    )
    # With no caller left, only the loop running the orphaned start can
    # record its outcome — drain loop steps until the tool is terminal.
    state = await _drain_to_terminal(manager, clock)
    # Assert: the tool is READY — the container started and the probe
    # genuinely answered, so the only honest terminal state with a
    # recorded handle is READY; FAILED would assert a fault that never
    # happened and STOPPED would deny a container that is running
    assert state.state is ToolState.READY, (
        f"the tool is {state.state!r} after every caller was cancelled — "
        "the start's outcome must be recorded even with no waiters left, "
        "and a start that succeeded is not a fault to record as FAILED"
    )
    assert not any(call[0] == "stop" for call in backend.calls), (
        f"the journal is {[call[0] for call in backend.calls]} — a "
        "successfully started container must not be stopped because "
        "its callers walked away"
    )
    # Assert: the handle is recorded — the container is not an orphan
    assert state.handle is not None, (
        "the tool holds no handle after its only caller was cancelled — "
        "the started container's handle must be recorded, or only "
        "reconciliation could ever find the container"
    )
    managed = backend.list_managed()
    assert len(managed) == 1 and state.handle is managed[0], (
        f"the backend manages {len(managed)} container(s) — the started "
        "container must exist and be the recorded handle"
    )
    # Assert: the start ran to completion — the probe kept being polled
    assert len(probe.calls) >= 3, (
        f"the probe was asked {len(probe.calls)} time(s) — with no "
        "waiters left the start must still poll to its answer"
    )
    # Assert: it cost exactly one cold start, so it ran once
    assert clock.now() == CLOCK_START + CANCELLED_START_COST, (
        f"the clock reads {clock.now()!r} — one cold start costs "
        f"{CANCELLED_START_COST}s from {CLOCK_START}"
    )
    # Assert: CancelledError reached the cancelled caller and nobody else
    assert isinstance(raised, asyncio.CancelledError)


@pytest.mark.asyncio
async def test_a_caller_arriving_after_a_cancelled_start_gets_ready() -> None:
    """A caller arriving after the cancelled start finished finds the
    tool READY and must not re-start or await a dead task: the start
    already ran to completion and recorded its outcome."""
    # Arrange
    backend = FakeBackend()
    probe = FakeProbe(script=CANCELLED_START_SCRIPT)
    clock = ManualClock(start=CLOCK_START)
    resolved = resolve_tool(TOOL, inline={})
    backend_config = BackendConfig()
    manager = _build_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act: the only early caller is cancelled inside the start window
    raised = await _cancelled_caller(manager, clock)
    assert isinstance(raised, asyncio.CancelledError), (
        f"the cancelled caller raised {type(raised).__name__} — the "
        "cancellation must surface as CancelledError"
    )
    # The orphaned start keeps running once the caller is gone — drain
    # loop steps until the tool is terminal, then the late caller arrives
    await _drain_to_terminal(manager, clock)
    # Act: a late caller arrives after the tool is READY
    handle = await _call_ensure_ready(manager)
    # Assert: the late caller got the handle without starting anything
    state = await _state_of(manager)
    assert state.state is ToolState.READY, (
        f"the tool is {state.state!r} before the late caller — the "
        "cancelled start must have completed and been recorded"
    )
    managed = backend.list_managed()
    assert handle is managed[0], (
        f"the late caller got {handle!r}, not the started container "
        f"{managed[0]!r} — a READY tool returns the handle it holds"
    )
    starts = _starts(backend)
    assert len(starts) == 1, (
        f"the journal shows {len(starts)} starts — a late caller on a "
        "READY tool must not start a second container"
    )


# ---------------------------------------------------------------------------
# Behaviour 18 — backend calls run in an executor, never on the event loop
# ---------------------------------------------------------------------------
#
# A backend whose start or stop blocks on a threading.Event until the
# test releases it. It is a double local to this file, not a FakeBackend
# failure mode: FakeBackend spawns no threads by construction, and a
# shared fake that can block would make every other test's timing depend
# on its release (m2b plan §3 behaviour 18).
#
# Every thread wait is bounded in two places. The double's own blocking
# wait is budget-capped: if a test forgets to release, the worker raises
# on its own budget instead of deadlocking the loop's teardown. The loop
# side never blocks: it polls worker flags with asyncio.sleep on the
# loop's real clock, and every such poll has a deadline that raises with
# the waited-on thing named rather than hanging. asyncio.wait_for appears
# nowhere — a worker thread's progress cannot be expressed in simulated
# time, so there is no simulated deadline to wait on.
#
# ManualClock never enters the assertions in this section. Simulated time
# does not advance while a worker blocks, so the assertions are about
# real concurrency: the loop ran other work while the backend call was
# still in flight, the second tool's start was reached while the first
# block was open, and the readiness-timeout's stop ran off the loop.
#
# Non-vacuity: every "the loop kept running" observation is ordered
# inside the block window. The entered flag is set from inside the
# worker, immediately before the blocking wait, so observation begins
# only once the call is genuinely blocked; the observer records, at the
# moment its own work ends, whether the block had already finished or
# raised, and asserts it had not — a test cannot pass by observing the
# loop before or after the block.


TOOL_TWO = "t2"

# The stop timeout the manager hands the backend, read from defaults.py
# so the comparison cannot drift from the source of truth.
STOP_TIMEOUT: float = float(BUILT_IN_DEFAULTS["stop_timeout"])


class BlockingStartBackend:
    """A ContainerBackend whose start or stop blocks on a threading.Event.

    ``block="start"`` parks every start until ``release()``;
    ``block="stop"`` parks stop the same way, reached through the
    readiness-timeout path (the only call site the manager has for stop
    today). ``fail_start_with`` makes start raise the given instance
    from its thread, pinning that an exception raised in the executor
    surfaces at the await with its type intact. The journal records
    every protocol call on entry, mirroring FakeBackend.

    The ``*_entered`` flags are set from the worker immediately before
    the blocking wait, ``*_finished`` only on a clean return, and
    ``*_raised`` whenever the worker gives up on its own budget — so a
    loop-side observer can tell "still blocked" from "block ended".
    """

    _THREAD_BUDGET_S = 2.0

    def __init__(
        self,
        *,
        block: str | None = None,
        fail_start_with: BaseException | None = None,
    ) -> None:
        if block not in (None, "start", "stop"):
            raise ValueError(f"block must be None, 'start' or 'stop': {block!r}")
        self.block = block
        self.fail_start_with = fail_start_with
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._containers: dict[ContainerHandle, bool] = {}
        self._release = threading.Event()
        self.start_entered = threading.Event()
        self.stop_entered = threading.Event()
        self.start_finished = threading.Event()
        self.stop_finished = threading.Event()
        self.start_raised = threading.Event()
        self.stop_raised = threading.Event()

    def release(self) -> None:
        """Unblock a parked start or stop; idempotent."""
        self._release.set()

    def _record(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self.calls.append((name, args, kwargs))

    def _wait_or_fail(self, what: str) -> None:
        # The double's own bound: if a test forgets release(), the worker
        # raises on its budget instead of holding the loop's teardown.
        if not self._release.wait(timeout=self._THREAD_BUDGET_S):
            raise TimeoutError(
                f"test forgot to release the blocking backend before its "
                f"{self._THREAD_BUDGET_S}s budget let the {what} worker out"
            )

    def start(self, spec: ContainerSpec) -> ContainerHandle:
        self._record("start", (spec,), {})
        if self.fail_start_with is not None:
            raise self.fail_start_with
        self.start_entered.set()
        try:
            if self.block == "start":
                self._wait_or_fail("start")
        except Exception:
            self.start_raised.set()
            raise
        handle = ContainerHandle(
            id=uuid.uuid4().hex,
            name=spec.name,
            tool=spec.tool,
            image=spec.image,
        )
        self._containers[handle] = True
        self.start_finished.set()
        return handle

    def stop(self, handle: ContainerHandle, *, timeout_s: float) -> None:
        self._record("stop", (handle,), {"timeout_s": timeout_s})
        self.stop_entered.set()
        try:
            if self.block == "stop":
                self._wait_or_fail("stop")
        except Exception:
            self.stop_raised.set()
            raise
        self._containers.pop(handle, None)
        self.stop_finished.set()

    def is_running(self, handle: ContainerHandle) -> bool:
        self._record("is_running", (handle,), {})
        return self._containers.get(handle, False)

    def inspect(self, handle: ContainerHandle) -> Any:
        self._record("inspect", (handle,), {})
        raise NotImplementedError

    def list_managed(self) -> list[ContainerHandle]:
        self._record("list_managed", (), {})
        return [h for h, running in self._containers.items() if running]

    def logs(self, handle: ContainerHandle, *, follow: bool, tail: int) -> Any:
        self._record("logs", (handle,), {"follow": follow, "tail": tail})
        raise NotImplementedError


async def _wait_until(
    predicate: Callable[[], bool], what: str, *, deadline_s: float = 10.0
) -> bool:
    """Poll on the loop's real clock until predicate() holds.

    The bound is on the loop's real clock, never on the ManualClock,
    whose time does not advance while a worker thread blocks. A deadline
    that trips raises with the waited-on thing named — a failure, not a
    hang.

    Returns:
        True once the predicate holds.

    Raises:
        AssertionError: the predicate did not hold within *deadline_s*.
    """
    loop = asyncio.get_running_loop()
    started = loop.time()
    while not predicate():
        if loop.time() - started >= deadline_s:
            raise AssertionError(
                f"waited {deadline_s}s for {what} and it never happened — "
                "if the loop was free the backend call never ran, and if "
                "a blocking call held the loop, nothing else could make "
                "it happen"
            )
        await asyncio.sleep(0.01)
    return True


def _observer_task(
    *flags: threading.Event,
) -> tuple[asyncio.Task[Any], list[bool]]:
    """A task that does real work on the loop, then records which of
    *flags* had already been set at the moment its work ended.

    The returned list is filled when the task completes: one entry per
    flag, True meaning the backend call behind the flag had already
    ended. A progress observation is only meaningful while the call is
    still in flight, so the test asserts every entry is False.

    Returns:
        The running task and the list it fills at completion.
    """
    finished: list[bool] = []

    async def run() -> None:
        for _ in range(20):
            await asyncio.sleep(0.005)
        finished.extend(flag.is_set() for flag in flags)

    return asyncio.create_task(run()), finished


def _build_blocking_manager(
    backend: BlockingStartBackend,
    probe: FakeProbe,
    clock: ManualClock,
    backend_config: BackendConfig,
) -> Any:
    """A manager wired to the blocking double, timeouts at their built-ins."""
    return _manager_class()(
        backend,
        probe=probe,
        clock=clock,
        backend_config=backend_config,
    )


@pytest.mark.asyncio
async def test_blocked_start_does_not_stall_the_event_loop() -> None:
    """A start parked on a threading.Event leaves the loop free: a
    concurrently spawned task does its work while the start is blocked,
    and a released start then completes the cold start to READY."""
    # Arrange: start blocks until released
    backend = BlockingStartBackend(block="start")
    probe = FakeProbe()
    clock = ManualClock(start=CLOCK_START)
    resolved = resolve_tool(TOOL, inline={})
    backend_config = BackendConfig()
    manager = _build_blocking_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    caller = asyncio.create_task(_ensure_ready(manager)(TOOL))
    # The entered flag is set from inside the worker immediately before
    # the block, so everything observed afterwards is observed while the
    # start is genuinely blocked.
    await _wait_until(backend.start_entered.is_set, "start to reach its block")
    # Act: an observer does real work on the loop while start is parked
    observer, ended_by_completion = _observer_task(
        backend.start_finished, backend.start_raised
    )
    await _wait_until(
        lambda: len(ended_by_completion) == 2, "the observer's work to finish"
    )
    await observer
    # Assert: the observer finished while the block was still open
    assert not ended_by_completion[0], (
        "start had finished by the time the observer's work was done — "
        "loop progress was observed after the block, not while the "
        "backend was blocked"
    )
    assert not ended_by_completion[1], (
        "start had already ended on its own worker budget by the time the "
        "observer ran — the loop stayed frozen for the block's whole "
        "duration, so the call ran on the loop itself, not in an "
        "executor"
    )
    # Release and let the cold start complete
    backend.release()
    handle = await caller
    # Assert: the released start completed the cold start normally
    state = await _state_of(manager)
    assert state.state is ToolState.READY, (
        f"the tool is {state.state!r} after its blocked start was released "
        "— a released start must complete the cold start to READY"
    )
    assert state.handle is handle, (
        "the state holds a different handle than ensure_ready returned — "
        "the released start must end with the started container recorded"
    )


@pytest.mark.asyncio
async def test_second_tool_progresses_while_first_start_is_blocked() -> None:
    """A second tool's cold start is attempted while the first tool's
    start is still blocked: plan/06 §8.7's group isolation in the only
    form M2b can test — a global lock held across a start would fail it."""
    # Arrange: every start blocks until released
    backend = BlockingStartBackend(block="start")
    probe = FakeProbe()
    clock = ManualClock(start=CLOCK_START)
    resolved_one = resolve_tool(TOOL, inline={})
    resolved_two = resolve_tool(TOOL_TWO, inline={})
    backend_config = BackendConfig()
    manager = _build_blocking_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved_one)
    _register_tool(manager)(TOOL_TWO, resolved_two, image=IMAGE)
    ensure_ready = _ensure_ready(manager)
    first = asyncio.create_task(ensure_ready(TOOL))
    await _wait_until(
        backend.start_entered.is_set, "the first start to reach its block"
    )
    # Act: the second tool asks for its own cold start while the first is
    # parked in the block
    second = asyncio.create_task(ensure_ready(TOOL_TWO))

    def second_attempted() -> bool:
        return any(
            name == "start" and args[0].tool == TOOL_TWO
            for name, args, _ in backend.calls
        )

    await _wait_until(second_attempted, "the second tool's start")
    # Assert: the second attempt landed while the first block was open
    assert not backend.start_finished.is_set(), (
        "the first start had finished before the second tool's start was "
        "attempted — the isolation was observed after the first block, "
        "not during it"
    )
    assert not backend.start_raised.is_set(), (
        "the first start had already ended on its own budget before the "
        "second tool's start was attempted — the loop stayed frozen for "
        "the block's whole duration, so the call ran on the loop itself, "
        "not in an executor"
    )
    # Release; both parked starts run to completion
    backend.release()
    handle_one = await first
    handle_two = await second
    # Assert: both tools ended READY on the containers their own starts
    # produced
    state_one = await _state_of(manager)
    assert state_one.state is ToolState.READY, (
        f"the first tool is {state_one.state!r} — the released start must end READY"
    )
    assert state_one.handle is handle_one, (
        "the first tool holds a different handle than its caller got — "
        "each tool must end on the container its own start produced"
    )
    state_two = _state_of_method(manager)(TOOL_TWO)
    assert state_two.state is ToolState.READY, (
        f"the second tool is {state_two.state!r} — its cold start, "
        "attempted while the first was blocked, must end READY"
    )
    assert state_two.handle is handle_two, (
        "the second tool holds a different handle than its caller got — "
        "each tool must end on the container its own start produced"
    )
    starts = [c for c in backend.calls if c[0] == "start"]
    assert len(starts) == 2, (
        f"the journal shows {len(starts)} starts — two tools "
        "cold-starting isolate into one start each, not one shared start"
    )


@pytest.mark.asyncio
async def test_blocked_stop_does_not_stall_the_event_loop() -> None:
    """A stop parked on a threading.Event leaves the loop free too: while
    the readiness-timeout path's stop is blocked, an observer task still
    does its work, and the timeout's own contract holds behind it."""
    # Arrange: start succeeds, ready never answers, stop blocks
    backend = BlockingStartBackend(block="stop")
    probe = FakeProbe(script=READY_NEVER_TRUE)
    clock = ManualClock(start=CLOCK_START)
    resolved = resolve_tool(TOOL, inline={})
    backend_config = BackendConfig()
    manager = _build_blocking_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    caller = asyncio.create_task(_ensure_ready(manager)(TOOL))
    # The timeout path burns ready_timeout of simulated time (behaviour
    # 16's territory) before it stops the container; here it only exists
    # to reach the stop call.
    await _wait_until(backend.stop_entered.is_set, "stop to reach its blocking wait")
    # Act: an observer does real work on the loop while stop is parked
    observer, ended_by_completion = _observer_task(
        backend.stop_finished, backend.stop_raised
    )
    await _wait_until(
        lambda: len(ended_by_completion) == 2, "the observer's work to finish"
    )
    await observer
    # Assert: the observer finished while the stop block was still open
    assert not ended_by_completion[0], (
        "stop had finished by the time the observer's work was done — "
        "loop progress was observed after the block, not while the "
        "backend was blocked"
    )
    assert not ended_by_completion[1], (
        "stop had already ended on its own worker budget by the time the "
        "observer ran — the loop stayed frozen for the block's whole "
        "duration, so the call ran on the loop itself, not in an "
        "executor"
    )
    # Release; the timeout failure completes
    backend.release()
    with pytest.raises(ReadyTimeoutError):
        await caller
    # Assert: the timeout's own contract, with the blocked stop behind it
    state = await _state_of(manager)
    assert state.state is ToolState.FAILED, (
        f"the tool is {state.state!r} after its readiness timeout — the "
        "timed-out cold start must end FAILED"
    )
    assert state.last_error == READY_TIMEOUT_TEXT, (
        f"last_error is {state.last_error!r}, the ready timeout's own "
        f"rendering is {READY_TIMEOUT_TEXT!r} — a stop that is off the "
        "loop must not change what the timeout records"
    )
    assert state.handle is None, (
        "the timed-out tool still holds a handle — the stopped container "
        "must not be claimed"
    )
    stops = [c for c in backend.calls if c[0] == "stop"]
    assert len(stops) == 1, (
        f"the journal shows {len(stops)} stops — the readiness timeout "
        "stops the started container once"
    )
    assert stops[0][2] == {"timeout_s": STOP_TIMEOUT}, (
        f"stop was called with {stops[0][2]} — the manager must hand the "
        f"backend its configured stop timeout of {STOP_TIMEOUT}s"
    )


@pytest.mark.asyncio
async def test_exception_in_the_backend_surfaces_at_await_with_type_intact() -> None:
    """A start exception raised in the backend's thread reaches the await
    as the very same object: behaviour 15's FAILED mapping and the
    verbatim last_error hold across the executor hop."""
    # Arrange: the backend's start raises a refusal from its own thread
    refusal = ContainerStartError("the daemon refused the start from a worker thread")
    backend = BlockingStartBackend(fail_start_with=refusal)
    probe = FakeProbe()
    clock = ManualClock(start=CLOCK_START)
    resolved = resolve_tool(TOOL, inline={})
    backend_config = BackendConfig()
    manager = _build_blocking_manager(backend, probe, clock, backend_config)
    await _register(manager, resolved)
    # Act
    outcome = await _drive(manager)
    # Assert: the await surfaced the backend's exception itself
    assert isinstance(outcome, BaseException), (
        f"ensure_ready returned {type(outcome).__name__} — a refused "
        "start must be re-raised to the caller, not swallowed"
    )
    assert outcome is refusal, (
        f"ensure_ready raised {type(outcome).__name__}, not the very "
        "exception the backend raised — the hop must surface the raised "
        "instance at the await, not a copy or a wrapper"
    )
    assert type(outcome) is ContainerStartError, (
        f"the raised type is {type(outcome).__name__} — the taxonomy "
        "member must survive the hop with its type intact"
    )
    # Assert: behaviour 15's mapping holds across the hop
    state = await _state_of(manager)
    assert state.state is ToolState.FAILED, (
        f"the tool is {state.state!r} after the refused start — a refusal "
        "raised in the backend's thread must still end the tool FAILED"
    )
    assert state.last_error == refusal.message, (
        f"last_error is {state.last_error!r}, the refusal's message is "
        f"{refusal.message!r} — the reason must carry the message "
        "verbatim across the hop"
    )
    assert state.handle is None, (
        "the tool holds a handle after a refusal that created no container"
    )

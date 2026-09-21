"""Pins ModelRuntimeState (m2b plan §3, behaviour 6): the seven-field
mutable data holder whose M6 fields are absent by decision.  The import
is deferred to call time so a missing class fails per test, not at collection."""

from __future__ import annotations

import dataclasses
import importlib
from types import ModuleType
from typing import Any, Final, cast, get_type_hints

from tool_swap.backend.base import ContainerHandle
from tool_swap.backend.errors import ContainerStartError
from tool_swap.utils.clock import ManualClock

TOOL = "t1"
IMAGE = "registry.example.com/acme/model:1.0"

# The M2b subset, per m2b plan §1.2: only the fields a M2b behaviour reads.
M2B_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "tool",
        "state",
        "handle",
        "last_used",
        "became_ready_at",
        "inflight",
        "last_error",
    }
)

# Deferred to M6 with the features that read them (m2b plan §1.2); the pin
# keeps the deferral visible rather than forgotten.
M6_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "group",
        "queued",
        "keep_warm",
        "ttl",
        "evict_cost",
        "vram_gb",
        "consecutive_failures",
    }
)


def _get_states_module() -> ModuleType:
    """Import tool_swap.lifecycle.states at call time, RED-safely.

    Raises:
        AssertionError: the module is missing; the message names the
            file to create.
    """
    try:
        return importlib.import_module("tool_swap.lifecycle.states")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.lifecycle.states is missing — create "
            "src/tool_swap/lifecycle/states.py"
        ) from exc


def _get_model_runtime_state() -> type[Any]:
    """Return the ModelRuntimeState class, RED-safely.

    Raises:
        AssertionError: the class is missing from states.py.
    """
    module = _get_states_module()
    try:
        return cast("type[Any]", module.ModelRuntimeState)
    except AttributeError as exc:
        raise AssertionError(
            "ModelRuntimeState is missing from src/tool_swap/lifecycle/states.py"
        ) from exc


def _tool_state() -> type[Any]:
    """Return the ToolState class from the same module, RED-safely.

    Raises:
        AssertionError: the class is missing from states.py.
    """
    module = _get_states_module()
    try:
        return cast("type[Any]", module.ToolState)
    except AttributeError as exc:
        raise AssertionError(
            "ToolState is missing from src/tool_swap/lifecycle/states.py"
        ) from exc


def _handle() -> ContainerHandle:
    """A started container handle — all four fields are required by the
    seam, so a non-None handle field must carry a real one."""
    return ContainerHandle(
        id="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        name="tswap-t1",
        tool=TOOL,
        image=IMAGE,
    )


def _fresh_state(
    cls: type[Any],
    *,
    handle: ContainerHandle | None = None,
    last_used: float = 0.0,
    last_error: str | None = None,
) -> Any:
    """A fresh STOPPED state for TOOL, as the manager builds one for an
    unknown tool; the parameters cover the tests that exercise one of the
    empty fields with a real value."""
    return cls(
        tool=TOOL,
        state=_tool_state().STOPPED,
        handle=handle,
        last_used=last_used,
        became_ready_at=None,
        inflight=0,
        last_error=last_error,
    )


def test_model_runtime_state_has_exactly_the_seven_m2b_fields() -> None:
    """The exact seven-field set of m2b plan §1.2; a field no behaviour
    reads is a field whose meaning is guessed, so the set stays closed."""
    # Act
    cls = _get_model_runtime_state()
    names = {f.name for f in dataclasses.fields(cls)}
    # Assert
    assert names == M2B_FIELDS, (
        f"ModelRuntimeState has fields {sorted(names)}, but the M2b subset "
        f"is {sorted(M2B_FIELDS)} — every extra field needs a behaviour "
        "that reads it"
    )


def test_model_runtime_state_defers_the_seven_m6_fields() -> None:
    """group, queued, keep_warm, ttl, evict_cost, vram_gb and
    consecutive_failures are absent by decision, deferred to M6 with the
    features that read them (m2b plan §1.2)."""
    # Act
    cls = _get_model_runtime_state()
    names = {f.name for f in dataclasses.fields(cls)}
    # Assert
    early = names & M6_FIELDS
    assert not early, (
        f"ModelRuntimeState carries M6 field(s) {sorted(early)} before the "
        "features that read them exist — adding one is a behaviour, not a "
        "quiet field edit"
    )


def test_model_runtime_state_field_types_match_the_plan_subset() -> None:
    """Each field carries §1.2's exact annotation; a drift such as
    last_error holding the exception object instead of its message string
    would break the 'M2b formats it, it does not invent it' contract."""
    # Arrange
    cls = _get_model_runtime_state()
    # Act
    hints = get_type_hints(cls)
    # Assert
    assert hints["tool"] is str
    assert hints["state"] is _tool_state()
    assert hints["last_used"] is float
    assert hints["inflight"] is int
    for name, member in (
        ("handle", ContainerHandle),
        ("became_ready_at", float),
        ("last_error", str),
    ):
        assert hints[name].__args__ == (member, type(None)), (
            f"field {name!r} is annotated {hints[name]}, expected {member} | None"
        )


def test_fresh_state_for_an_unknown_tool_is_stopped_with_no_container() -> None:
    """A fresh state for an unknown tool is STOPPED with the plan's four
    empties (m2b plan §3 behaviour 6) and last_used a plain float from the
    clock."""
    # Arrange
    cls = _get_model_runtime_state()
    stopped = _tool_state().STOPPED
    clock = ManualClock(start=123.0)
    # Act
    state = _fresh_state(cls, last_used=clock.now())
    # Assert
    assert state.tool == TOOL
    assert state.state is stopped
    assert state.handle is None
    assert state.last_used == 123.0
    assert state.became_ready_at is None
    assert state.inflight == 0
    assert state.last_error is None


def test_model_runtime_state_fields_update_in_place() -> None:
    """The manager updates the state in place on every request completion
    (m2b plan §3 behaviour 6); a frozen refactor would raise here and force
    a realloc per completion."""
    # Arrange
    state = _fresh_state(_get_model_runtime_state())
    # Act
    state.inflight = 1
    state.last_used = 42.5
    state.last_error = "the daemon refused the start"
    # Assert
    assert state.inflight == 1
    assert state.last_used == 42.5
    assert state.last_error == "the daemon refused the start"


def test_last_error_carries_the_taxonomy_message_verbatim() -> None:
    """last_error holds a real taxonomy member's message verbatim — M2b
    formats it, it does not invent it (M2a §6 item 6) — not str(err),
    which appends the remedy."""
    # Arrange
    error = ContainerStartError(
        "the daemon refused the start: driver failed programming external gamelists"
    )
    state = _fresh_state(_get_model_runtime_state(), last_error=error.message)
    # Act
    stored = state.last_error
    # Assert
    assert stored == error.message
    assert stored != str(error), (
        f"last_error holds the rendering {stored!r}, not the message alone — "
        "the remedy belongs to /status, not to the FAILED reason"
    )


def test_stopped_state_with_a_handle_is_stored_without_rejection() -> None:
    """A STOPPED state carrying a handle is stored, not rejected: the holder
    has no validation hook (error behaviour is n/a, m2b plan §3 behaviour 6) —
    the no-container-no-handle invariant belongs to the transitions."""
    # Arrange
    cls = _get_model_runtime_state()
    stopped = _tool_state().STOPPED
    handle = _handle()
    # Act
    state = _fresh_state(cls, handle=handle)
    # Assert
    assert state.state is stopped
    assert state.handle is handle

"""Pins the transition table (m2b plan §3 behaviour 7): the ten legal
edges of §1.1, exhaustive over all 36 ordered ``ToolState`` pairs, and
the raise-and-name-both-states error behaviour of ``apply_transition``.
The legal set is the data the tests compare against and the pair space
is derived with ``itertools.product``, so a missing or a spurious edge
cannot hide in a sampled test.  The new attributes are gated per test,
not at collection, because states.py already ships ``ToolState`` and
``ModelRuntimeState``."""

from __future__ import annotations

import importlib
import itertools
import re
from collections.abc import Callable
from types import ModuleType
from typing import Any, Final, cast

import pytest

from tool_swap.lifecycle.states import ToolState

TOOL = "t1"

# The ten legal edges of m2b plan §1.1, in table order. The mermaid
# diagram's `[*] --> STOPPED` is its initial pseudo-state, not an edge:
# a tool begins life STOPPED, which no transition performs.
LEGAL_TRANSITIONS: Final[frozenset[tuple[ToolState, ToolState]]] = frozenset(
    {
        (ToolState.STOPPED, ToolState.STARTING),  # ensure_ready on a stopped tool
        (ToolState.STARTING, ToolState.LOADING),  # the health probe answers true
        (ToolState.STARTING, ToolState.FAILED),  # start raised, or start_timeout
        (ToolState.LOADING, ToolState.READY),  # the ready probe answers true
        (ToolState.LOADING, ToolState.FAILED),  # ready_timeout elapsed
        (ToolState.READY, ToolState.STOPPING),  # stop requested
        (ToolState.READY, ToolState.FAILED),  # the liveness sweep found it gone
        (ToolState.STOPPING, ToolState.STOPPED),  # the backend stop returned
        (ToolState.FAILED, ToolState.STARTING),  # ensure_ready retries
        (ToolState.FAILED, ToolState.STOPPED),  # manual reset
    }
)

# All 36 ordered pairs, derived rather than listed: a hand-written list
# is where a missing pair hides.
ALL_TRANSITIONS: Final[frozenset[tuple[ToolState, ToolState]]] = frozenset(
    itertools.product(ToolState, ToolState)
)

# The twenty-six illegal pairs, derived from the difference. All six
# self-transitions are among them: a state never transitions to itself.
ILLEGAL_TRANSITIONS: Final[frozenset[tuple[ToolState, ToolState]]] = (
    ALL_TRANSITIONS - LEGAL_TRANSITIONS
)


def _pair_key(pair: tuple[ToolState, ToolState]) -> tuple[str, str]:
    return (pair[0].name, pair[1].name)


def _pair_ids(pairs: list[tuple[ToolState, ToolState]]) -> list[str]:
    return [f"{frm.name}_to_{to.name}" for frm, to in pairs]


ALL_PAIRS: Final[list[tuple[ToolState, ToolState]]] = sorted(
    ALL_TRANSITIONS, key=_pair_key
)
LEGAL_PAIRS: Final[list[tuple[ToolState, ToolState]]] = sorted(
    LEGAL_TRANSITIONS, key=_pair_key
)
ILLEGAL_PAIRS: Final[list[tuple[ToolState, ToolState]]] = sorted(
    ILLEGAL_TRANSITIONS, key=_pair_key
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


def _is_legal_transition() -> Callable[[ToolState, ToolState], bool]:
    """Return the transition predicate, RED-safely.

    Raises:
        AssertionError: the predicate is missing from states.py.
    """
    module = _get_states_module()
    try:
        predicate = module.is_legal_transition
    except AttributeError as exc:
        raise AssertionError(
            "is_legal_transition is missing from src/tool_swap/lifecycle/states.py"
        ) from exc
    return cast("Callable[[ToolState, ToolState], bool]", predicate)


def _apply_transition() -> Callable[..., ToolState]:
    """Return the transition applier, RED-safely.

    Raises:
        AssertionError: the applier is missing from states.py.
    """
    module = _get_states_module()
    try:
        apply_fn = module.apply_transition
    except AttributeError as exc:
        raise AssertionError(
            "apply_transition is missing from src/tool_swap/lifecycle/states.py"
        ) from exc
    return cast("Callable[..., ToolState]", apply_fn)


def _illegal_transition_error() -> type[Exception]:
    """Return the illegal-transition exception class, RED-safely.

    Raises:
        AssertionError: the exception class is missing from states.py.
    """
    module = _get_states_module()
    try:
        return cast("type[Exception]", module.IllegalTransitionError)
    except AttributeError as exc:
        raise AssertionError(
            "IllegalTransitionError is missing from src/tool_swap/lifecycle/states.py"
        ) from exc


def _runtime_state_at(state: ToolState) -> Any:
    """A ModelRuntimeState for TOOL sitting at ``state`` with no
    container: the minimal holder the transition table operates on, so
    a test never depends on container facts the table cannot see."""
    cls = _get_model_runtime_state()
    return cls(
        tool=TOOL,
        state=state,
        handle=None,
        last_used=0.0,
        became_ready_at=None,
        inflight=0,
        last_error=None,
    )


def test_the_pair_space_counts_match_the_transition_table() -> None:
    """The §1.1 arithmetic: six states give 36 ordered pairs, ten legal
    and twenty-six illegal; a drift in any count means an edge was added
    to or dropped from the table data."""
    # Assert (module data derived from the shipped six-member enum)
    assert len(ALL_TRANSITIONS) == 36
    assert len(LEGAL_TRANSITIONS) == 10
    assert len(ILLEGAL_TRANSITIONS) == 26
    assert ALL_TRANSITIONS == LEGAL_TRANSITIONS | ILLEGAL_TRANSITIONS


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    ALL_PAIRS,
    ids=_pair_ids(ALL_PAIRS),
)
def test_is_legal_transition_matches_the_table_on_every_ordered_pair(
    from_state: ToolState,
    to_state: ToolState,
) -> None:
    """The predicate answers true on exactly the ten §1.1 edges and
    false on the other twenty-six; a missing or a spurious edge is
    silently wrong under any sampled test."""
    # Arrange
    predicate = _is_legal_transition()
    expected = (from_state, to_state) in LEGAL_TRANSITIONS
    # Act
    result = predicate(from_state, to_state)
    # Assert
    assert result is expected, (
        f"is_legal_transition({from_state.name}, {to_state.name}) returned "
        f"{result!r}, expected {expected!r}"
    )


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    LEGAL_PAIRS,
    ids=_pair_ids(LEGAL_PAIRS),
)
def test_apply_transition_updates_and_returns_the_new_state_on_legal_pairs(
    from_state: ToolState,
    to_state: ToolState,
) -> None:
    """A legal transition updates the runtime state in place and returns
    the new state, while leaving the fields the manager owns (handle,
    timestamps, inflight, last_error) untouched."""
    # Arrange
    apply_fn = _apply_transition()
    state = _runtime_state_at(from_state)
    # Act
    result = apply_fn(state, to_state, reason="test transition")
    # Assert
    assert result is to_state
    assert state.state is to_state
    assert state.tool == TOOL
    assert state.handle is None
    assert state.last_used == 0.0
    assert state.became_ready_at is None
    assert state.inflight == 0
    assert state.last_error is None


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    ILLEGAL_PAIRS,
    ids=_pair_ids(ILLEGAL_PAIRS),
)
def test_apply_transition_rejects_every_illegal_pair_naming_both_states(
    from_state: ToolState,
    to_state: ToolState,
) -> None:
    """An illegal transition raises IllegalTransitionError naming both
    states and leaves the runtime state where it was; a silently ignored
    transition would leave a tool in a state its caller does not expect."""
    # Arrange
    apply_fn = _apply_transition()
    error_cls = _illegal_transition_error()
    state = _runtime_state_at(from_state)
    # Act
    with pytest.raises(error_cls) as excinfo:
        apply_fn(state, to_state, reason="test transition")
    # Assert
    message = str(excinfo.value)
    assert re.search(from_state.name, message, re.IGNORECASE) is not None, (
        f"IllegalTransitionError for {from_state.name} -> {to_state.name} "
        f"does not name the from-state: {message!r}"
    )
    assert re.search(to_state.name, message, re.IGNORECASE) is not None, (
        f"IllegalTransitionError for {from_state.name} -> {to_state.name} "
        f"does not name the to-state: {message!r}"
    )
    assert state.state is from_state


def test_ready_to_ready_does_not_silently_re_ready_a_serving_tool() -> None:
    """Self-transitions are illegal, and READY -> READY is the dangerous
    one: re-readying a tool already serving would reset its timers and
    re-log readiness."""
    # Arrange
    predicate = _is_legal_transition()
    apply_fn = _apply_transition()
    error_cls = _illegal_transition_error()
    state = _runtime_state_at(ToolState.READY)
    # Act / Assert
    assert predicate(ToolState.READY, ToolState.READY) is False
    with pytest.raises(error_cls):
        apply_fn(state, ToolState.READY, reason="test transition")
    assert state.state is ToolState.READY


def test_starting_to_stopped_is_m6s_vram_unavailable_path_not_an_oversight() -> None:
    """STARTING -> STOPPED is deliberately absent, not an oversight: it
    is the shared-node vram_unavailable path that needs the failure
    classification M6 owns (m2b plan §1.1, plan/06 §8.5b)."""
    # Arrange
    predicate = _is_legal_transition()
    apply_fn = _apply_transition()
    error_cls = _illegal_transition_error()
    state = _runtime_state_at(ToolState.STARTING)
    # Act / Assert
    assert predicate(ToolState.STARTING, ToolState.STOPPED) is False
    with pytest.raises(error_cls):
        apply_fn(state, ToolState.STOPPED, reason="test transition")
    assert state.state is ToolState.STARTING

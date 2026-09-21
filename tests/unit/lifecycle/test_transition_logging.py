"""Pins the transition logging rule (m2b plan §3 behaviour 8): every
applied transition logs exactly one INFO record carrying the tool, the
from-state, the to-state and the reason as structured record attributes,
and a refused illegal transition logs nothing. The four values are read
off the ``LogRecord`` attributes, never out of a formatted message, so a
wording change cannot mask a missing or a wrong value.
"""

from __future__ import annotations

import itertools
import logging
from typing import Final

import pytest

from tool_swap.backend.errors import ContainerStartError
from tool_swap.lifecycle.states import (
    IllegalTransitionError,
    ModelRuntimeState,
    ToolState,
    apply_transition,
)

LOGGER_NAME = "tool_swap.lifecycle.states"
TOOL = "t1"

# The ten legal edges of m2b plan §1.1, in table order. The set is
# duplicated here rather than imported from test_transition_table.py:
# the transition-table file already pins the shipped data against
# exactly this set, and a cross-test import would hide which contract
# failed when one of the two copies drifts.
LEGAL_TRANSITIONS: Final[frozenset[tuple[ToolState, ToolState]]] = frozenset(
    {
        (ToolState.STOPPED, ToolState.STARTING),
        (ToolState.STARTING, ToolState.LOADING),
        (ToolState.STARTING, ToolState.FAILED),
        (ToolState.LOADING, ToolState.READY),
        (ToolState.LOADING, ToolState.FAILED),
        (ToolState.READY, ToolState.STOPPING),
        (ToolState.READY, ToolState.FAILED),
        (ToolState.STOPPING, ToolState.STOPPED),
        (ToolState.FAILED, ToolState.STARTING),
        (ToolState.FAILED, ToolState.STOPPED),
    }
)

ALL_PAIRS: Final[list[tuple[ToolState, ToolState]]] = sorted(
    itertools.product(ToolState, ToolState), key=lambda p: (p[0].name, p[1].name)
)
LEGAL_PAIRS: Final[list[tuple[ToolState, ToolState]]] = [
    p for p in ALL_PAIRS if p in LEGAL_TRANSITIONS
]
ILLEGAL_PAIRS: Final[list[tuple[ToolState, ToolState]]] = [
    p for p in ALL_PAIRS if p not in LEGAL_TRANSITIONS
]


def _pair_ids(pairs: list[tuple[ToolState, ToolState]]) -> list[str]:
    return [f"{frm.name}_to_{to.name}" for frm, to in pairs]


def _runtime_state_at(state: ToolState) -> ModelRuntimeState:
    """A ModelRuntimeState for TOOL sitting at ``state`` with no
    container: the minimal holder the transition function operates on."""
    return ModelRuntimeState(
        tool=TOOL,
        state=state,
        handle=None,
        last_used=0.0,
        became_ready_at=None,
        inflight=0,
        last_error=None,
    )


def _transition_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Only the records the state machine's own logger emitted."""
    return [r for r in caplog.records if r.name == LOGGER_NAME]


def _assert_record_carries(
    record: logging.LogRecord,
    name: str,
    expected: object,
    from_state: ToolState,
    to_state: ToolState,
) -> None:
    """Assert one structured field of the record, naming the contract in
    the failure text so a missing attachment is obvious."""
    actual = getattr(record, name, None)
    assert actual == expected, (
        f"log record for {from_state.name} -> {to_state.name} carries "
        f"{name}={actual!r}, expected {expected!r}; attach the four values "
        "as record attributes via extra={'tool': ..., 'from_state': ..., "
        "'to_state': ..., 'reason': ...}"
    )


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    LEGAL_PAIRS,
    ids=_pair_ids(LEGAL_PAIRS),
)
def test_apply_transition_logs_one_info_record_with_tool_from_to_and_reason(
    from_state: ToolState,
    to_state: ToolState,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every applied transition logs exactly one INFO record whose
    structured fields carry the tool, the from-state, the to-state and
    the reason; a missing field or a swapped state leaves a log reader
    believing the tool moved the wrong way."""
    # Arrange
    state = _runtime_state_at(from_state)
    reason = f"the {from_state.name} phase ended"
    # Act
    with caplog.at_level(logging.INFO):
        apply_transition(state, to_state, reason=reason)
    # Assert
    records = _transition_records(caplog)
    assert len(records) == 1, (
        f"expected exactly one log record from {LOGGER_NAME} for the "
        f"{from_state.name} -> {to_state.name} transition, found "
        f"{len(records)}; the transition must be logged at INFO"
    )
    record = records[0]
    assert record.levelno == logging.INFO, (
        f"the {from_state.name} -> {to_state.name} transition was logged at "
        f"level {record.levelname}, expected INFO"
    )
    _assert_record_carries(record, "tool", TOOL, from_state, to_state)
    _assert_record_carries(record, "from_state", from_state, from_state, to_state)
    _assert_record_carries(record, "to_state", to_state, from_state, to_state)
    _assert_record_carries(record, "reason", reason, from_state, to_state)
    assert state.state is to_state


def test_apply_transition_into_failed_logs_the_taxonomy_message_verbatim(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The reason of a transition into FAILED is the taxonomy member's
    ``message`` verbatim (m2a §6 item 6); ``str(err)`` appends the
    remedy, and logging that would duplicate the user-facing field."""
    # Arrange
    error = ContainerStartError("the daemon refused the start")
    state = _runtime_state_at(ToolState.STARTING)
    # Act
    with caplog.at_level(logging.INFO):
        apply_transition(state, ToolState.FAILED, reason=error.message)
    # Assert
    records = _transition_records(caplog)
    assert len(records) == 1, (
        f"expected exactly one log record from {LOGGER_NAME} for the "
        f"STARTING -> FAILED transition, found {len(records)}"
    )
    record = records[0]
    assert record.reason == error.message, (
        f"the FAILED transition logged reason={record.reason!r}, expected "
        f"the taxonomy message {error.message!r} verbatim"
    )
    assert record.reason != str(error), (
        "the logged reason equals str(err), which appends the remedy — "
        "log the message field, not the exception"
    )
    assert state.state is ToolState.FAILED


@pytest.mark.parametrize(
    ("from_state", "to_state"),
    ILLEGAL_PAIRS,
    ids=_pair_ids(ILLEGAL_PAIRS),
)
def test_apply_transition_logs_nothing_for_a_refused_illegal_pair(
    from_state: ToolState,
    to_state: ToolState,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A refused transition logs nothing: logging before validating would
    leave a record for a state change that never happened, and anyone
    reading the log afterwards would believe the tool had moved."""
    # Arrange
    state = _runtime_state_at(from_state)
    # Act
    with caplog.at_level(logging.INFO), pytest.raises(IllegalTransitionError):
        apply_transition(state, to_state, reason="a refused transition")
    # Assert
    records = _transition_records(caplog)
    assert records == [], (
        f"the refused {from_state.name} -> {to_state.name} transition "
        f"emitted {len(records)} log record(s); a transition that raises "
        "must log nothing, because it did not happen"
    )
    assert state.state is from_state

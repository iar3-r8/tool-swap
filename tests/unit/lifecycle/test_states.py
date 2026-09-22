"""Pins ToolState (m2b plan §3, behaviour 5): the six-member StrEnum
answering "can this tool serve traffic".  The exact-set pin and the
value-disjointness pin keep it from blurring with ContainerState; the
import is deferred to call time so a missing module fails per test,
not at collection."""

from __future__ import annotations

import enum
import importlib
from types import ModuleType
from typing import Any, cast

import pytest


def _get_states_module() -> ModuleType:
    """Import tool_swap.lifecycle.states at call time, so a missing
    module fails as an informative assertion, not a collection error.

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


def _get_tool_state() -> type[Any]:
    """Return the ToolState class; a missing name raises an informative
    AssertionError instead of a bare AttributeError.

    Raises:
        AssertionError: the module or class is missing.
    """
    module = _get_states_module()
    try:
        state_cls = module.ToolState
    except AttributeError as exc:
        raise AssertionError(
            "ToolState is missing from src/tool_swap/lifecycle/states.py"
        ) from exc
    return cast("type[Any]", state_cls)


def _get_container_state() -> type[Any]:
    """Return the ContainerState class from the backend seam.

    Raises:
        AssertionError: the module or class is missing.
    """
    try:
        module = importlib.import_module("tool_swap.backend.base")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.backend.base is missing — the backend seam already shipped it"
        ) from exc
    try:
        return cast("type[Any]", module.ContainerState)
    except AttributeError as exc:
        raise AssertionError(
            "ContainerState is missing from src/tool_swap/backend/base.py"
        ) from exc


def test_tool_state_is_str_and_enum_subclass() -> None:
    """Members compare equal to bare strings; a non-StrEnum refactor
    would break string comparisons in the manager and CLI output."""
    # Act
    state_cls = _get_tool_state()
    # Assert
    assert issubclass(state_cls, str)
    assert issubclass(state_cls, enum.Enum)
    for member in state_cls:
        assert isinstance(member, str)


def test_tool_state_has_exactly_the_six_members() -> None:
    """Exactly STOPPED/STARTING/LOADING/READY/STOPPING/FAILED; a
    smuggled-in member or a dropped one would silently change what the
    state machine accepts (m2b plan §1.1)."""
    # Act
    state_cls = _get_tool_state()
    member_names = {member.name for member in state_cls}
    # Assert
    assert member_names == {
        "STOPPED",
        "STARTING",
        "LOADING",
        "READY",
        "STOPPING",
        "FAILED",
    }


@pytest.mark.parametrize(
    ("member_name", "value"),
    [
        ("STOPPED", "stopped"),
        ("STARTING", "starting"),
        ("LOADING", "loading"),
        ("READY", "ready"),
        ("STOPPING", "stopping"),
        ("FAILED", "failed"),
    ],
)
def test_tool_state_members_carry_their_string_values(
    member_name: str,
    value: str,
) -> None:
    """Each member holds its exact lowercase value and compares equal to
    the bare string, the values plan/01 §4's table implies."""
    # Arrange
    state_cls = _get_tool_state()
    # Act
    member = state_cls[member_name]
    # Assert
    assert member.value == value
    assert member == value
    assert isinstance(member, str)


def test_tool_state_and_container_state_values_are_disjoint() -> None:
    """No value string appears in both enums; a later RUNNING added to
    ToolState (or a readiness state to ContainerState) would collapse
    "can serve traffic" into "does a process exist"."""
    # Arrange
    tool_cls = _get_tool_state()
    container_cls = _get_container_state()
    # Act
    overlap = {m.value for m in tool_cls} & {m.value for m in container_cls}
    # Assert
    assert overlap == set(), (
        "ToolState and ContainerState share value strings "
        f"{sorted(overlap)} — the two enums must stay value-disjoint"
    )

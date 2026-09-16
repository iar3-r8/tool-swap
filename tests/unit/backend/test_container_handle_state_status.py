"""RED step for M2a behaviour 5 — the ``ContainerHandle``,
``ContainerState`` and ``ContainerStatus`` types.

See ``plans/m2a-container-backend-seam.md`` §4.1 and behaviour 5 (§5):

- ``ContainerHandle`` is a ``@dataclass(frozen=True, slots=True)``
  with four required fields ``id``, ``name``, ``tool`` and ``image``;
  value equality and hashability (M2b will key dicts by handles).
- ``ContainerState`` is a ``StrEnum`` with exactly four members —
  ``CREATED``/``"created"``, ``RUNNING``/``"running"``,
  ``EXITED``/``"exited"``, ``GONE``/``"gone"``.  It is deliberately
  NOT the M2b tool state machine: ``STARTING``/``LOADING``/``READY``
  are readiness concepts owned by M2b's health probe, and the backend
  only knows whether a process exists.  Pinning the exact member set
  makes that drift fail loudly.
- ``ContainerStatus`` is a ``@dataclass(frozen=True, slots=True)``
  with ``handle`` and ``state`` required, and ``exit_code:
  int | None`` and ``started_at: str | None`` defaulting to ``None``
  — a running container has ``exit_code=None``, not ``0``.
  ``started_at`` is a plain string, never a ``datetime``.
- Assignment to any field of either dataclass raises
  ``dataclasses.FrozenInstanceError``.

One file, not three: behaviour 5 is a single ledger behaviour that
lands all three types in the single module
``src/tool_swap/backend/base.py``, and the existing convention is
one test file per behaviour (``test_mount_spec.py``,
``test_container_spec.py``).

This file is the RED step: ``base.py`` already exists (behaviours 3
and 4) but does not define any of the three names yet, so a
module-scope ``from tool_swap.backend.base import ContainerHandle``
would raise ``ImportError`` on the missing *name* and abort pytest
*collection* of the whole suite before a single assertion executed.
Every access to ``tool_swap`` is therefore deferred out of module
scope into call-time helpers, following ``test_container_spec.py``
exactly: each gate raises ``AssertionError`` inside its own test, so
every test fails individually with the missing name named; the
moment the GREEN step adds the three types the calls resolve and
each test proceeds to its own assertions.  ``MountSpec`` and
``ContainerSpec`` exist on this branch and could be imported at
module scope without endangering collection; they are fetched at
call time anyway, because the editable ``tool_swap`` install carries
no ``py.typed`` marker and a module-scope import would fail
``mypy --strict`` on this file.

What is pinned about ``ContainerState`` being a ``StrEnum``: that
the class is both a ``str`` and an ``enum.Enum`` subclass (the two
behaviours the seam relies on, rather than naming ``enum.StrEnum``
itself — a harmless ``str, Enum``-mixin refactor would still pass),
the exact four-member set, and that each member carries its exact
string value and compares equal to the bare string.  Deliberately
NOT pinned: iteration order and the members' ``__str__`` /
``__format__`` — incidental details a harmless refactor could
change.

No ``importorskip`` and no skip of any kind is used — a skipped
test is not a red step, it is a test that silently does not run.

Conventions: pytest, AAA pattern, no ``warnings.warn`` (pyproject
sets ``filterwarnings = "error"``).
"""

from __future__ import annotations

import dataclasses
import enum
import importlib
from types import ModuleType
from typing import Any, cast, get_type_hints

import pytest


def _get_backend_module() -> ModuleType:
    """Import ``tool_swap.backend.base`` at call time, RED-safely.

    Deferred out of module scope via ``importlib.import_module`` so
    that ``mypy --strict`` stays clean over this file while no
    ``tool_swap`` name is imported at module scope (the editable
    install carries no ``py.typed``).  The RED failure mode for this
    behaviour is a missing *name* in an existing module (handled by
    the per-type gates); this guards against the module ever being
    removed.

    Raises:
        AssertionError: the module cannot be imported — behaviours
            3 and 4 already landed it.
    """
    try:
        module = importlib.import_module("tool_swap.backend.base")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.backend.base is missing — behaviours 3 and 4 "
            "already landed src/tool_swap/backend/base.py"
        ) from exc
    return module


def _get_container_handle() -> type[Any]:
    """Import and return the ``ContainerHandle`` class, RED-safely.

    While ``base.py`` lacks ``ContainerHandle`` this raises
    ``AssertionError`` naming the missing name, so every test fails
    individually instead of the run being interrupted during
    collection (``AttributeError`` is the RED failure mode here: a
    missing *name* in an existing module).

    Raises:
        AssertionError: ``ContainerHandle`` is not defined in
            ``tool_swap.backend.base`` yet — the GREEN step must add
            it.
    """
    module = _get_backend_module()
    try:
        handle_cls = module.ContainerHandle
    except AttributeError as exc:
        raise AssertionError(
            "tool_swap.backend.base.ContainerHandle is missing — the "
            "GREEN step must add ContainerHandle to "
            "src/tool_swap/backend/base.py"
        ) from exc
    return cast("type[Any]", handle_cls)


def _get_container_state() -> type[Any]:
    """Import and return the ``ContainerState`` class, RED-safely.

    While ``base.py`` lacks ``ContainerState`` this raises
    ``AssertionError`` naming the missing name, so every test fails
    individually instead of the run being interrupted during
    collection (``AttributeError`` is the RED failure mode here: a
    missing *name* in an existing module).

    Raises:
        AssertionError: ``ContainerState`` is not defined in
            ``tool_swap.backend.base`` yet — the GREEN step must add
            it.
    """
    module = _get_backend_module()
    try:
        state_cls = module.ContainerState
    except AttributeError as exc:
        raise AssertionError(
            "tool_swap.backend.base.ContainerState is missing — the "
            "GREEN step must add ContainerState to "
            "src/tool_swap/backend/base.py"
        ) from exc
    return cast("type[Any]", state_cls)


def _get_container_status() -> type[Any]:
    """Import and return the ``ContainerStatus`` class, RED-safely.

    While ``base.py`` lacks ``ContainerStatus`` this raises
    ``AssertionError`` naming the missing name, so every test fails
    individually instead of the run being interrupted during
    collection (``AttributeError`` is the RED failure mode here: a
    missing *name* in an existing module).

    Raises:
        AssertionError: ``ContainerStatus`` is not defined in
            ``tool_swap.backend.base`` yet — the GREEN step must add
            it.
    """
    module = _get_backend_module()
    try:
        status_cls = module.ContainerStatus
    except AttributeError as exc:
        raise AssertionError(
            "tool_swap.backend.base.ContainerStatus is missing — the "
            "GREEN step must add ContainerStatus to "
            "src/tool_swap/backend/base.py"
        ) from exc
    return cast("type[Any]", status_cls)


def _handle_kwargs() -> dict[str, object]:
    """The four required handle fields, as keyword arguments."""
    return {
        "id": "a1b2c3d4",
        "name": "ms-llama",
        "tool": "llama",
        "image": "llama:latest",
    }


def _make_handle(handle_cls: type[Any]) -> Any:
    """A handle built from the standard four fields."""
    return handle_cls(**_handle_kwargs())


def _base_status_kwargs(
    handle_cls: type[Any],
    state_cls: type[Any],
) -> dict[str, object]:
    """The four status fields, as keyword arguments (state is EXITED)."""
    return {
        "handle": _make_handle(handle_cls),
        "state": state_cls.EXITED,
        "exit_code": 0,
        "started_at": "2026-09-15T14:00:00Z",
    }


def _base_status(
    handle_cls: type[Any],
    state_cls: type[Any],
    status_cls: type[Any],
) -> Any:
    """A status carrying every field, for round-trip and mutation tests."""
    return status_cls(**_base_status_kwargs(handle_cls, state_cls))


def _minimal_status(
    handle_cls: type[Any],
    state_cls: type[Any],
    status_cls: type[Any],
) -> Any:
    """A status carrying only the two required fields (state is RUNNING)."""
    return status_cls(handle=_make_handle(handle_cls), state=state_cls.RUNNING)


# --- ContainerHandle --------------------------------------------------------


def test_container_handle_construction_round_trips_all_fields() -> None:
    """Keyword construction stores all four fields verbatim."""
    # Arrange
    handle_cls = _get_container_handle()
    # Act
    handle = handle_cls(**_handle_kwargs())
    # Assert
    assert dataclasses.is_dataclass(handle_cls)
    assert handle.id == "a1b2c3d4"
    assert handle.name == "ms-llama"
    assert handle.tool == "llama"
    assert handle.image == "llama:latest"


def test_container_handle_field_names_and_order_are_pinned() -> None:
    """Exactly four fields, in the order id, name, tool, image (§4.1)."""
    # Arrange
    handle_cls = _get_container_handle()
    # Act
    fields = dataclasses.fields(handle_cls)
    # Assert
    assert [f.name for f in fields] == ["id", "name", "tool", "image"]


@pytest.mark.parametrize("field_name", ["id", "name", "tool", "image"])
def test_container_handle_field_has_no_default(field_name: str) -> None:
    """Each of the four fields carries neither a default nor a factory."""
    # Arrange
    handle_cls = _get_container_handle()
    by_name = {f.name: f for f in dataclasses.fields(handle_cls)}
    # Assert
    assert by_name[field_name].default is dataclasses.MISSING
    assert by_name[field_name].default_factory is dataclasses.MISSING


@pytest.mark.parametrize("field_name", ["id", "name", "tool", "image"])
def test_container_handle_omitting_required_field_raises_type_error(
    field_name: str,
) -> None:
    """All four fields are required: omitting any is a TypeError."""
    # Arrange
    handle_cls = _get_container_handle()
    kwargs = dict(_handle_kwargs())
    del kwargs[field_name]
    # Act / Assert
    with pytest.raises(TypeError):
        handle_cls(**kwargs)


def test_container_handle_equal_fields_are_equal() -> None:
    """Two handles with equal fields are equal and hash equal."""
    # Arrange
    handle_cls = _get_container_handle()
    first = _make_handle(handle_cls)
    second = _make_handle(handle_cls)
    # Assert
    assert first == second
    assert hash(first) == hash(second)


_HANDLE_REPLACEMENTS: dict[str, object] = {
    "id": "ffffffff",
    "name": "ms-other",
    "tool": "other",
    "image": "other:latest",
}


@pytest.mark.parametrize("field_name", ["id", "name", "tool", "image"])
def test_container_handle_differing_field_is_unequal(field_name: str) -> None:
    """A difference in exactly one field makes the handles unequal."""
    # Arrange
    handle_cls = _get_container_handle()
    first = _make_handle(handle_cls)
    kwargs = dict(_handle_kwargs())
    kwargs[field_name] = _HANDLE_REPLACEMENTS[field_name]
    second = handle_cls(**kwargs)
    # Assert
    assert first != second


def test_container_handle_same_id_different_name_is_unequal() -> None:
    """The id is not the identity on its own: same id, different name.

    Behaviour 5's named edge case — a handle is identified by all
    four fields, not by ``id`` alone.
    """
    # Arrange
    handle_cls = _get_container_handle()
    first = _make_handle(handle_cls)
    second = handle_cls(
        id="a1b2c3d4",
        name="ms-llama-2",
        tool="llama",
        image="llama:latest",
    )
    # Assert
    assert first != second


def test_container_handle_usable_as_dict_key() -> None:
    """M2b will key dicts by handles: equal handles share one entry."""
    # Arrange
    handle_cls = _get_container_handle()
    key = _make_handle(handle_cls)
    equal = _make_handle(handle_cls)
    table = {key: "tracked"}
    # Act
    looked_up = table[equal]
    # Assert
    assert looked_up == "tracked"


def test_container_handle_instances_are_slotted() -> None:
    """slots=True: instances carry no ``__dict__``."""
    # Arrange
    handle_cls = _get_container_handle()
    # Act
    handle = _make_handle(handle_cls)
    # Assert
    assert not hasattr(handle, "__dict__")


@pytest.mark.parametrize("field_name", ["id", "name", "tool", "image"])
def test_container_handle_assignment_to_any_field_raises(field_name: str) -> None:
    """Assignment to any field raises FrozenInstanceError (frozen=True)."""
    # Arrange
    handle_cls = _get_container_handle()
    handle = _make_handle(handle_cls)
    value = _HANDLE_REPLACEMENTS[field_name]
    # Act / Assert
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(handle, field_name, value)


# --- ContainerState ---------------------------------------------------------


def test_container_state_is_a_str_and_enum_subclass() -> None:
    """ContainerState is a StrEnum: a str and an enum.Enum subclass.

    Both base classes are pinned (rather than ``enum.StrEnum``
    itself) because they are the two behaviours the seam relies on —
    members usable as bare strings — while naming the exact builtin
    would make a harmless ``str, Enum``-mixin refactor fail.
    """
    # Arrange
    state_cls = _get_container_state()
    # Assert
    assert issubclass(state_cls, enum.Enum)
    assert issubclass(state_cls, str)
    for member in state_cls:
        assert isinstance(member, str)


def test_container_state_has_exactly_the_four_backend_members() -> None:
    """Exactly CREATED/RUNNING/EXITED/GONE — no M2b readiness states.

    ``STARTING``/``LOADING``/``READY`` belong to M2b's health probe,
    not the backend; pinning the exact member set makes a smuggled-in
    readiness state fail loudly (plan §4.1, behaviour 5).
    """
    # Arrange
    state_cls = _get_container_state()
    # Act
    member_names = {member.name for member in state_cls}
    # Assert
    assert member_names == {"CREATED", "RUNNING", "EXITED", "GONE"}


@pytest.mark.parametrize(
    ("member_name", "value"),
    [
        ("CREATED", "created"),
        ("RUNNING", "running"),
        ("EXITED", "exited"),
        ("GONE", "gone"),
    ],
)
def test_container_state_members_carry_their_string_values(
    member_name: str,
    value: str,
) -> None:
    """Each member holds its exact value and compares equal to the string.

    The string equality is the StrEnum behaviour callers rely on: a
    bare ``"running"`` compares equal to ``ContainerState.RUNNING``.
    Iteration order and member ``__str__``/``__format__`` are
    deliberately not pinned.
    """
    # Arrange
    state_cls = _get_container_state()
    # Act
    member = state_cls[member_name]
    # Assert
    assert member.value == value
    assert member == value
    assert isinstance(member, str)


# --- ContainerStatus --------------------------------------------------------


def test_container_status_field_names_and_order_are_pinned() -> None:
    """Exactly four fields: handle, state, exit_code, started_at."""
    # Arrange
    status_cls = _get_container_status()
    # Act
    fields = dataclasses.fields(status_cls)
    # Assert
    assert [f.name for f in fields] == [
        "handle",
        "state",
        "exit_code",
        "started_at",
    ]


@pytest.mark.parametrize("field_name", ["handle", "state"])
def test_container_status_required_fields_have_no_default(field_name: str) -> None:
    """handle and state carry neither a default nor a factory."""
    # Arrange
    status_cls = _get_container_status()
    by_name = {f.name: f for f in dataclasses.fields(status_cls)}
    # Assert
    assert by_name[field_name].default is dataclasses.MISSING
    assert by_name[field_name].default_factory is dataclasses.MISSING


@pytest.mark.parametrize("field_name", ["exit_code", "started_at"])
def test_container_status_running_container_defaults(field_name: str) -> None:
    """A running container's status defaults both optionals to None.

    Built from handle + ``RUNNING`` only: ``exit_code`` is ``None``
    (not ``0`` — that distinction is load-bearing for a later
    behaviour) and ``started_at`` is ``None``.
    """
    # Arrange
    handle_cls = _get_container_handle()
    state_cls = _get_container_state()
    status_cls = _get_container_status()
    status = _minimal_status(handle_cls, state_cls, status_cls)
    # Assert
    assert status.state is state_cls.RUNNING
    assert getattr(status, field_name) is None


def test_container_status_full_construction_round_trips_all_fields() -> None:
    """Keyword construction stores all four fields."""
    # Arrange
    handle_cls = _get_container_handle()
    state_cls = _get_container_state()
    status_cls = _get_container_status()
    handle = _make_handle(handle_cls)
    # Act
    status = _base_status(handle_cls, state_cls, status_cls)
    # Assert
    assert dataclasses.is_dataclass(status_cls)
    assert status.handle == handle
    assert status.state is state_cls.EXITED
    assert status.exit_code == 0
    assert status.started_at == "2026-09-15T14:00:00Z"


@pytest.mark.parametrize("field_name", ["handle", "state"])
def test_container_status_omitting_required_field_raises_type_error(
    field_name: str,
) -> None:
    """Omitting handle or state is a TypeError at construction."""
    # Arrange
    handle_cls = _get_container_handle()
    state_cls = _get_container_state()
    status_cls = _get_container_status()
    kwargs: dict[str, object] = _base_status_kwargs(handle_cls, state_cls)
    del kwargs[field_name]
    # Act / Assert
    with pytest.raises(TypeError):
        status_cls(**kwargs)


def test_container_status_instances_are_slotted() -> None:
    """slots=True: instances carry no ``__dict__``."""
    # Arrange
    handle_cls = _get_container_handle()
    state_cls = _get_container_state()
    status_cls = _get_container_status()
    # Act
    status = _base_status(handle_cls, state_cls, status_cls)
    # Assert
    assert not hasattr(status, "__dict__")


_STATUS_REPLACEMENTS: dict[str, object] = {
    "exit_code": 42,
    "started_at": "2026-09-15T15:00:00Z",
}


def _replacement_for(
    field_name: str,
    handle_cls: type[Any],
    state_cls: type[Any],
) -> object:
    """A value that differs from the base status for the given field."""
    if field_name == "handle":
        return handle_cls(
            id="ffffffff",
            name="ms-other",
            tool="other",
            image="other:latest",
        )
    if field_name == "state":
        return state_cls.RUNNING  # the base status uses EXITED
    return _STATUS_REPLACEMENTS[field_name]


@pytest.mark.parametrize("field_name", ["handle", "state", "exit_code", "started_at"])
def test_container_status_assignment_to_any_field_raises(field_name: str) -> None:
    """Assignment to any field raises FrozenInstanceError (frozen=True)."""
    # Arrange
    handle_cls = _get_container_handle()
    state_cls = _get_container_state()
    status_cls = _get_container_status()
    status = _base_status(handle_cls, state_cls, status_cls)
    value = _replacement_for(field_name, handle_cls, state_cls)
    # Act / Assert
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(status, field_name, value)


def test_container_status_equal_fields_are_equal() -> None:
    """Two statuses with equal fields are equal and hash equal."""
    # Arrange
    handle_cls = _get_container_handle()
    state_cls = _get_container_state()
    status_cls = _get_container_status()
    first = _base_status(handle_cls, state_cls, status_cls)
    second = _base_status(handle_cls, state_cls, status_cls)
    # Assert
    assert first == second
    assert hash(first) == hash(second)


@pytest.mark.parametrize("field_name", ["handle", "state", "exit_code", "started_at"])
def test_container_status_differing_field_is_unequal(field_name: str) -> None:
    """A difference in exactly one field makes the statuses unequal."""
    # Arrange
    handle_cls = _get_container_handle()
    state_cls = _get_container_state()
    status_cls = _get_container_status()
    first = _base_status(handle_cls, state_cls, status_cls)
    kwargs = _base_status_kwargs(handle_cls, state_cls)
    kwargs[field_name] = _replacement_for(field_name, handle_cls, state_cls)
    second = status_cls(**kwargs)
    # Assert
    assert first != second


def test_container_status_fields_are_annotated_backend_vocabulary() -> None:
    """Annotations use seam types, not SDK vocabulary.

    ``handle`` is ``ContainerHandle`` and ``state`` is
    ``ContainerState`` (not ``str``); the optionals are
    ``int | None`` and ``str | None`` — in particular
    ``started_at`` is a string, not a ``datetime``.
    """
    # Arrange
    handle_cls = _get_container_handle()
    state_cls = _get_container_state()
    status_cls = _get_container_status()
    # Act
    hints = get_type_hints(status_cls)
    # Assert
    assert hints["handle"] is handle_cls
    assert hints["state"] is state_cls
    assert hints["exit_code"] == int | None
    assert hints["started_at"] == str | None


def test_container_status_started_at_is_stored_verbatim_as_string() -> None:
    """started_at is stored as the given string: no coercion to datetime."""
    # Arrange
    handle_cls = _get_container_handle()
    state_cls = _get_container_state()
    status_cls = _get_container_status()
    timestamp = "2026-09-15T14:00:00Z"
    # Act
    status = status_cls(
        handle=_make_handle(handle_cls),
        state=state_cls.RUNNING,
        started_at=timestamp,
    )
    # Assert
    assert status.started_at == timestamp
    assert isinstance(status.started_at, str)

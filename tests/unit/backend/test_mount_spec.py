"""RED step for M2a behaviour 3 — the ``MountSpec`` dataclass.

See ``plans/m2a-container-backend-seam.md`` §4.1 and behaviour 3 (§5):

- ``MountSpec`` is a ``@dataclass(frozen=True, slots=True)`` with fields
  ``source: str``, ``target: str`` and ``read_only: bool = True``.
- ``read_only`` defaults to ``True`` (``plan/01_ARCHITECTURE.md`` §10:
  "read-only by default"); a caller must ask for read-write explicitly.
- Two instances with equal fields are equal and hash equal; instances
  are hashable (M2b keys dicts by spec fields).
- Assignment to any field raises ``dataclasses.FrozenInstanceError``.
- ``MountSpec`` validates nothing: no expansion, no path resolution,
  no parsing.  Mode legality (``TSWAP-C541``), container-path
  absoluteness (``TSWAP-C542``) and host-path existence (``TSWAP-C543``)
  are config-layer rules owned by ``tool_swap.config.validate``.

This file is the RED step: ``src/tool_swap/backend/base.py`` does not
exist yet.  The import is therefore deferred out of module scope into
:func:`_get_mount_spec` so that collection of this module — and of the
whole suite — succeeds: a module-level import would abort the entire
run with ``ModuleNotFoundError`` and not one of the assertions below
would ever execute.  In the RED state every test fails individually,
on its own, at the :func:`_get_mount_spec` call, which names the
missing module; the moment the GREEN step creates ``base.py`` the call
resolves and each test proceeds to its own assertions.  No
``importorskip`` and no skip of any kind is used — a skipped test is
not a red step, it is a test that silently does not run.

Conventions: pytest, AAA pattern, no ``warnings.warn`` (pyproject sets
``filterwarnings = "error"``).
"""

from __future__ import annotations

import dataclasses
import importlib
from types import ModuleType
from typing import Any, cast

import pytest


def _get_mount_spec() -> type[Any]:
    """Import and return the ``MountSpec`` class, RED-safely.

    The import is deferred out of module scope — via
    ``importlib.import_module`` so that the not-yet-existing
    ``tool_swap.backend.base`` module cannot abort pytest collection
    of this file (and thereby of the whole suite), and so that
    ``mypy --strict`` stays clean while the module is absent.  While
    ``src/tool_swap/backend/base.py`` does not exist this raises
    ``AssertionError`` naming the missing module, so every test fails
    individually instead of the run being interrupted during
    collection.

    Raises:
        AssertionError: ``tool_swap.backend.base`` does not exist yet —
            the GREEN step must create it with ``MountSpec``.
    """
    try:
        module: ModuleType = importlib.import_module("tool_swap.backend.base")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.backend.base is missing — the GREEN step must "
            "create src/tool_swap/backend/base.py with MountSpec"
        ) from exc
    return cast("type[Any]", module.MountSpec)


def test_mount_spec_stores_source_target_and_read_only() -> None:
    """Keyword construction round-trips all three fields."""
    # Arrange
    spec_cls = _get_mount_spec()
    # Act
    spec = spec_cls(source="/host/models", target="/models", read_only=False)
    # Assert
    assert dataclasses.is_dataclass(spec_cls)
    assert spec.source == "/host/models"
    assert spec.target == "/models"
    assert spec.read_only is False


def test_mount_spec_read_only_defaults_to_true() -> None:
    """A spec built from source/target alone is read-only (architecture §10)."""
    # Arrange
    spec_cls = _get_mount_spec()
    # Act
    spec = spec_cls(source="/host/models", target="/models")
    # Assert
    assert spec.read_only is True


def test_mount_spec_field_names_and_order_are_pinned() -> None:
    """Exactly three fields, in the order source, target, read_only."""
    # Arrange
    spec_cls = _get_mount_spec()
    # Act
    fields = dataclasses.fields(spec_cls)
    # Assert
    assert [f.name for f in fields] == ["source", "target", "read_only"]


def test_mount_spec_only_read_only_has_a_default() -> None:
    """source and target are required; read_only defaults to True."""
    # Arrange
    spec_cls = _get_mount_spec()
    # Act
    by_name = {f.name: f for f in dataclasses.fields(spec_cls)}
    # Assert
    assert by_name["source"].default is dataclasses.MISSING
    assert by_name["target"].default is dataclasses.MISSING
    assert by_name["read_only"].default is True


@pytest.mark.parametrize("field", ["source", "target", "read_only"])
def test_mount_spec_assignment_to_any_field_raises(field: str) -> None:
    """Assignment to any field raises FrozenInstanceError (frozen=True)."""
    # Arrange
    spec_cls = _get_mount_spec()
    spec = spec_cls(source="/host/models", target="/models")
    value = False if field == "read_only" else "/changed"
    # Act / Assert
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(spec, field, value)


def test_mount_spec_instances_are_slotted() -> None:
    """slots=True: instances carry no ``__dict__``."""
    # Arrange
    spec_cls = _get_mount_spec()
    # Act
    spec = spec_cls(source="/host/models", target="/models")
    # Assert
    assert not hasattr(spec, "__dict__")


def test_mount_spec_equal_fields_are_equal() -> None:
    """Two instances with equal fields are equal and hash equal."""
    # Arrange
    spec_cls = _get_mount_spec()
    # Act
    first = spec_cls(source="/host/models", target="/models")
    second = spec_cls(source="/host/models", target="/models")
    # Assert
    assert first == second
    assert hash(first) == hash(second)


@pytest.mark.parametrize("field", ["source", "target", "read_only"])
def test_mount_spec_differing_field_is_unequal(field: str) -> None:
    """A difference in exactly one field makes the instances unequal."""
    # Arrange
    spec_cls = _get_mount_spec()
    first = spec_cls(source="/host/models", target="/models")
    if field == "source":
        second = spec_cls(source="/other", target="/models")
    elif field == "target":
        second = spec_cls(source="/host/models", target="/elsewhere")
    else:
        second = spec_cls(source="/host/models", target="/models", read_only=False)
    # Assert
    assert first != second


def test_mount_spec_usable_as_dict_key() -> None:
    """M2b keys dicts by spec fields: equal instances share one entry."""
    # Arrange
    spec_cls = _get_mount_spec()
    key = spec_cls(source="/host/models", target="/models")
    equal = spec_cls(source="/host/models", target="/models")
    table = {key: "mounted"}
    # Act
    looked_up = table[equal]
    # Assert
    assert looked_up == "mounted"


def test_mount_spec_stores_values_verbatim_without_validation() -> None:
    """MountSpec holds what it is given: no expansion, resolution or checks.

    ``source`` may still look unresolved (``~`` unexpanded) and
    ``target`` may be relative and absent on disk: ``MountSpec`` must
    store both verbatim and raise nothing.  Those judgements belong to
    the config layer (``TSWAP-C541``/``C542``/``C543``); re-doing them
    here is exactly the duplication the behaviour-3 amendment removed
    (plan §4.2).
    """
    # Arrange
    spec_cls = _get_mount_spec()
    # Act
    spec = spec_cls(source="~/models/weights", target="models", read_only=False)
    # Assert
    assert spec.source == "~/models/weights"
    assert spec.target == "models"
    assert spec.read_only is False

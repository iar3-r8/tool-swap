"""RED step for M2a behaviour 4 — the ``ContainerSpec`` dataclass.

See ``plans/m2a-container-backend-seam.md`` §4.1 and behaviour 4 (§5):

- ``ContainerSpec`` is a ``@dataclass(frozen=True, slots=True)`` — fully
  resolved input: everything needed to start one tool container,
  backend-agnostic, carrying no policy (no TTL, no group, no eviction).
- Fields, in order: ``tool``, ``name``, ``image``, ``gpu_runtime``,
  ``container_port``, ``command``, ``env``, ``labels``, ``network``,
  ``mounts``, ``devices``, ``shm_size``, ``cpus``, ``memory``,
  ``published_port``.
- ``tool``, ``name``, ``image``, ``gpu_runtime`` and ``container_port``
  are required; the other ten carry structural defaults only
  (``None`` / ``{}`` / ``()``).
- ``gpu_runtime`` and ``container_port`` are keyword-only and required:
  omitting either is a ``TypeError`` at construction, never a silent
  built-in default.
- **No configured default is re-stated** (the behaviour-4 amendment):
  ``BUILT_IN_DEFAULTS`` is the single named source of truth for
  ``gpu_runtime`` / ``container_port`` / ``shm_size``.  The guard tests
  below read that constant rather than restating its values, so a
  literal copied back into ``ContainerSpec`` fails a test instead of
  drifting silently.
- Assignment to any field raises ``dataclasses.FrozenInstanceError``;
  mutable defaults (``env``, ``labels``) are not shared between
  instances; ``mounts`` is a tuple of ``MountSpec`` (behaviour 3),
  never of strings.

This file is the RED step: ``src/tool_swap/backend/base.py`` exists
(behaviour 3) but does not define ``ContainerSpec`` yet.  Every access
to ``tool_swap`` is therefore deferred out of module scope into
call-time helpers, following ``test_mount_spec.py`` exactly:

- A module-level ``from tool_swap.backend.base import ContainerSpec``
  would raise ``ImportError`` on the missing *name* and abort pytest
  *collection* of the whole suite before a single assertion executed.
  :func:`_get_container_spec` instead raises ``AssertionError`` inside
  each test, so every test fails individually; the moment the GREEN
  step adds ``ContainerSpec`` to ``base.py`` the call resolves and each
  test proceeds to its own assertions.
- ``MountSpec`` (behaviour 3, committed) and
  ``BUILT_IN_DEFAULTS`` (M1) both exist and could be imported at module
  scope without endangering collection; they are still fetched at call
  time, because the editable ``tool_swap`` install carries no
  ``py.typed`` marker and a module-scope import of it fails
  ``mypy --strict`` on this file (the same error the existing
  ``tests/unit/config`` files show under a direct mypy run).  The
  guard still *reads* the constant, per behaviour 4 — it only changes
  when the import resolves, not what is read.

No ``importorskip`` and no skip of any kind is used — a skipped test is
not a red step, it is a test that silently does not run.

Construction helpers use neutral resolved values (``"cuda"``, ``8080``)
deliberately distinct from the configured defaults, so this file never
restates a value owned by ``BUILT_IN_DEFAULTS`` outside the guard
tests, which read it.

Conventions: pytest, AAA pattern, no ``warnings.warn`` (pyproject sets
``filterwarnings = "error"``).
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import typing
from collections.abc import Mapping
from types import ModuleType
from typing import Any, cast, get_type_hints

import pytest


def _get_backend_module() -> ModuleType:
    """Import ``tool_swap.backend.base`` at call time, RED-safely.

    Deferred out of module scope via ``importlib.import_module`` so
    that a missing module cannot abort pytest collection of this file
    (and thereby of the whole suite), and so that ``mypy --strict``
    stays clean over this file while no ``tool_swap`` name is imported
    at module scope (the editable install carries no ``py.typed``).

    Raises:
        AssertionError: ``tool_swap.backend.base`` does not exist yet —
            the GREEN step must create it (it exists for behaviour 3;
            this guards against it ever being removed).
    """
    try:
        module = importlib.import_module("tool_swap.backend.base")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.backend.base is missing — it must exist with "
            "ContainerSpec in src/tool_swap/backend/base.py"
        ) from exc
    return module


def _get_container_spec() -> type[Any]:
    """Import and return the ``ContainerSpec`` class, RED-safely.

    While ``base.py`` lacks ``ContainerSpec`` this raises
    ``AssertionError`` naming the missing name, so every test fails
    individually instead of the run being interrupted during
    collection.  ``AttributeError`` is the RED failure mode here (a
    missing *name* in an existing module), which is why it is caught
    separately from the module-level failure handled by
    :func:`_get_backend_module`.

    Raises:
        AssertionError: ``ContainerSpec`` is not defined in
            ``tool_swap.backend.base`` yet — the GREEN step must add it.
    """
    module = _get_backend_module()
    try:
        spec_cls = module.ContainerSpec
    except AttributeError as exc:
        raise AssertionError(
            "tool_swap.backend.base.ContainerSpec is missing — the GREEN "
            "step must add ContainerSpec to src/tool_swap/backend/base.py"
        ) from exc
    return cast("type[Any]", spec_cls)


def _get_mount_spec() -> type[Any]:
    """Return the committed behaviour-3 ``MountSpec`` class.

    Fetched from the same module (at call time, for the same mypy
    reason as :func:`_get_container_spec`) rather than imported at
    module scope; it exists on this branch.
    """
    module = _get_backend_module()
    return cast("type[Any]", module.MountSpec)


def _get_built_in_defaults() -> Mapping[str, object]:
    """Return ``tool_swap.config.defaults.BUILT_IN_DEFAULTS`` at call time.

    The guard reads the constant itself, per behaviour 4, rather than
    restating its values.  The import is deferred for the mypy reason
    given in the module docstring; nothing about *what is read*
    changes.

    Raises:
        AssertionError: the constant is missing — the guard cannot run.
    """
    try:
        module = importlib.import_module("tool_swap.config.defaults")
        defaults = module.BUILT_IN_DEFAULTS
    except (ModuleNotFoundError, AttributeError) as exc:
        raise AssertionError(
            "tool_swap.config.defaults.BUILT_IN_DEFAULTS is missing — the "
            "no-duplicate-default guard cannot run"
        ) from exc
    return cast("Mapping[str, object]", defaults)


def _required_kwargs() -> dict[str, object]:
    """The five required fields, as keyword arguments.

    Values are neutral resolved values, deliberately distinct from
    ``BUILT_IN_DEFAULTS``: construction tests exercise the dataclass,
    they do not restate configured defaults.
    """
    return {
        "tool": "llama",
        "name": "ms-llama",
        "image": "llama:latest",
        "gpu_runtime": "cuda",
        "container_port": 8080,
    }


def _minimal_spec(spec_cls: type[Any]) -> Any:
    """A spec carrying only the five required fields."""
    return spec_cls(**_required_kwargs())


def _base_spec(spec_cls: type[Any], mount_cls: type[Any]) -> Any:
    """A spec carrying every field, for round-trip and mutation tests."""
    kwargs: dict[str, object] = {
        **_required_kwargs(),
        "command": ("python", "server.py"),
        "env": {"MODEL": "7b"},
        "labels": {"com.tool-swap/tool": "llama"},
        "network": "tool-swap-net",
        "mounts": (mount_cls(source="/host/models", target="/models"),),
        "devices": (0,),
        "shm_size": "2g",
        "cpus": 2.0,
        "memory": "16g",
        "published_port": 7001,
    }
    return spec_cls(**kwargs)


def test_container_spec_minimal_construction_succeeds() -> None:
    """The five required fields alone construct a valid spec."""
    # Arrange
    spec_cls = _get_container_spec()
    # Act
    spec = _minimal_spec(spec_cls)
    # Assert
    assert dataclasses.is_dataclass(spec_cls)
    assert spec.tool == "llama"
    assert spec.name == "ms-llama"
    assert spec.image == "llama:latest"
    assert spec.gpu_runtime == "cuda"
    assert spec.container_port == 8080


def test_container_spec_stores_all_fields_verbatim() -> None:
    """Keyword construction round-trips every one of the fifteen fields."""
    # Arrange
    spec_cls = _get_container_spec()
    mount_cls = _get_mount_spec()
    mount = mount_cls(source="/host/models", target="/models")
    # Act
    spec = _base_spec(spec_cls, mount_cls)
    # Assert
    assert spec.tool == "llama"
    assert spec.name == "ms-llama"
    assert spec.image == "llama:latest"
    assert spec.gpu_runtime == "cuda"
    assert spec.container_port == 8080
    assert spec.command == ("python", "server.py")
    assert spec.env == {"MODEL": "7b"}
    assert spec.labels == {"com.tool-swap/tool": "llama"}
    assert spec.network == "tool-swap-net"
    assert spec.mounts == (mount,)
    assert spec.devices == (0,)
    assert spec.shm_size == "2g"
    assert spec.cpus == 2.0
    assert spec.memory == "16g"
    assert spec.published_port == 7001


def test_container_spec_field_names_and_order_are_pinned() -> None:
    """Exactly fifteen fields, in the order of plan §4.1."""
    # Arrange
    spec_cls = _get_container_spec()
    # Act
    fields = dataclasses.fields(spec_cls)
    # Assert
    assert [f.name for f in fields] == [
        "tool",
        "name",
        "image",
        "gpu_runtime",
        "container_port",
        "command",
        "env",
        "labels",
        "network",
        "mounts",
        "devices",
        "shm_size",
        "cpus",
        "memory",
        "published_port",
    ]


@pytest.mark.parametrize(
    "field_name", ["tool", "name", "image", "gpu_runtime", "container_port"]
)
def test_container_spec_required_fields_have_no_default(field_name: str) -> None:
    """The five required fields carry neither a default nor a factory."""
    # Arrange
    spec_cls = _get_container_spec()
    # Act
    by_name = {f.name: f for f in dataclasses.fields(spec_cls)}
    # Assert
    assert by_name[field_name].default is dataclasses.MISSING
    assert by_name[field_name].default_factory is dataclasses.MISSING


@pytest.mark.parametrize(
    ("field_name", "expected"),
    [
        ("command", None),
        ("env", {}),
        ("labels", {}),
        ("network", None),
        ("mounts", ()),
        ("devices", ()),
        ("shm_size", None),
        ("cpus", None),
        ("memory", None),
        ("published_port", None),
    ],
)
def test_container_spec_structural_defaults(field_name: str, expected: object) -> None:
    """A minimal spec carries the structural default for each other field."""
    # Arrange
    spec_cls = _get_container_spec()
    # Act
    spec = _minimal_spec(spec_cls)
    # Assert
    assert getattr(spec, field_name) == expected


def test_container_spec_resolved_fields_are_keyword_only() -> None:
    """gpu_runtime / container_port cannot be passed positionally."""
    # Arrange
    spec_cls = _get_container_spec()
    # Act
    by_name = {f.name: f for f in dataclasses.fields(spec_cls)}
    signature = inspect.signature(spec_cls)
    # Assert
    for name in ("gpu_runtime", "container_port"):
        assert by_name[name].kw_only is True
        kind = signature.parameters[name].kind
        assert kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize(
    "missing", ["tool", "name", "image", "gpu_runtime", "container_port"]
)
def test_container_spec_omitting_required_field_raises_type_error(
    missing: str,
) -> None:
    """Omitting any one of the five required fields is a TypeError."""
    # Arrange
    spec_cls = _get_container_spec()
    kwargs = dict(_required_kwargs())
    del kwargs[missing]
    # Act / Assert
    with pytest.raises(TypeError):
        spec_cls(**kwargs)


_NEW_VALUES: dict[str, object] = {
    "tool": "other",
    "name": "ms-other",
    "image": "other:latest",
    "gpu_runtime": "cuda2",
    "container_port": 9080,
    "command": ("echo", "hi"),
    "env": {"K": "V"},
    "labels": {"L": "V"},
    "network": "other-net",
    "devices": (1,),
    "shm_size": "4g",
    "cpus": 4.0,
    "memory": "8g",
    "published_port": 7200,
}


@pytest.mark.parametrize("field_name", [*sorted(_NEW_VALUES), "mounts"])
def test_container_spec_assignment_to_any_field_raises(field_name: str) -> None:
    """Assignment to any field raises FrozenInstanceError (frozen=True)."""
    # Arrange
    spec_cls = _get_container_spec()
    mount_cls = _get_mount_spec()
    spec = _base_spec(spec_cls, mount_cls)
    # The mounts value is a MountSpec instance, built here so the module
    # scope carries no tool_swap import.
    if field_name == "mounts":
        value: object = mount_cls(source="/other", target="/other")
    else:
        value = _NEW_VALUES[field_name]
    # Act / Assert
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(spec, field_name, value)


def test_container_spec_instances_are_slotted() -> None:
    """slots=True: instances carry no ``__dict__``."""
    # Arrange
    spec_cls = _get_container_spec()
    # Act
    spec = _minimal_spec(spec_cls)
    # Assert
    assert not hasattr(spec, "__dict__")


def test_container_spec_mutable_defaults_are_not_shared() -> None:
    """env and labels default to fresh dicts per instance, not one shared one."""
    # Arrange
    spec_cls = _get_container_spec()
    first = _minimal_spec(spec_cls)
    second = _minimal_spec(spec_cls)
    # Act
    first.env["K"] = "V"
    first.labels["L"] = "V"
    # Assert
    assert second.env == {}
    assert second.labels == {}
    assert first.env is not second.env
    assert first.labels is not second.labels


def test_container_spec_mounts_round_trip_mount_spec_instances() -> None:
    """mounts holds MountSpec instances (behaviour 3), stored verbatim."""
    # Arrange
    spec_cls = _get_container_spec()
    mount_cls = _get_mount_spec()
    mount = mount_cls(source="/host/models", target="/models", read_only=False)
    # Act
    spec = spec_cls(**{**_required_kwargs(), "mounts": (mount,)})
    # Assert
    assert spec.mounts == (mount,)
    assert isinstance(spec.mounts[0], mount_cls)
    assert spec.mounts[0].read_only is False


def test_container_spec_mounts_is_annotated_tuple_of_mount_spec() -> None:
    """The mounts annotation is tuple[MountSpec, ...]: never a tuple of strings."""
    # Arrange
    spec_cls = _get_container_spec()
    mount_cls = _get_mount_spec()
    # Act
    hints = get_type_hints(spec_cls)
    origin = typing.get_origin(hints["mounts"])
    args = typing.get_args(hints["mounts"])
    # Assert
    assert origin is tuple
    assert args == (mount_cls, Ellipsis)


@pytest.mark.parametrize("field_name", ["gpu_runtime", "container_port", "shm_size"])
def test_container_spec_field_does_not_restate_builtin_default(
    field_name: str,
) -> None:
    """No field default may equal the BUILT_IN_DEFAULTS value for its key.

    The guard reads ``BUILT_IN_DEFAULTS`` rather than restating the
    values, per behaviour 4.  Two shapes are distinguished in addition
    to the inequality: ``gpu_runtime`` and ``container_port`` must have
    no default at all (``dataclasses.MISSING``); ``shm_size`` must
    default to ``None``, not to the configured value.  The shape
    assertions do not depend on the configured value, so the guard
    still fails if ``BUILT_IN_DEFAULTS`` itself changes and the old
    literal is copied back into the dataclass — a guard that only
    compared against the live constant would keep passing.
    """
    # Arrange
    spec_cls = _get_container_spec()
    defaults = _get_built_in_defaults()
    by_name = {f.name: f for f in dataclasses.fields(spec_cls)}
    assert field_name in defaults, (
        f"BUILT_IN_DEFAULTS lost its '{field_name}' key — the guard "
        "behaviour-4 depends on it being the source of truth"
    )
    built_in_value: object = defaults[field_name]
    # Act
    field = by_name[field_name]
    # Assert
    assert field.default != built_in_value
    assert field.default_factory is dataclasses.MISSING
    if field_name in ("gpu_runtime", "container_port"):
        assert field.default is dataclasses.MISSING
    else:  # shm_size
        assert field.default is None

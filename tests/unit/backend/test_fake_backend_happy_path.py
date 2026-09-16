"""RED step for M2a behaviour 10 — ``FakeBackend`` happy path.

See ``plans/m2a-container-backend-seam.md`` §4.4 and behaviour 10 (§5):

- ``FakeBackend()`` constructs with no arguments; §4.4 declares
  ``FakeBackend(script: Mapping[str, FailureMode] | None = None)``, and
  behaviour 10 needs only the no-script construction.  The constructor
  is asserted to accept zero arguments and to declare a ``script``
  parameter defaulting to ``None``.
- ``start(spec)`` returns a :class:`ContainerHandle` whose ``name``,
  ``tool`` and ``image`` match the spec and whose ``id`` is a
  non-empty string, unique per start.
- ``is_running(handle)`` is ``True`` for a started container.
- ``inspect(handle)`` is ``ContainerState.RUNNING`` with
  ``exit_code=None`` (a running container has not exited — behaviour 5
  pins ``None`` rather than ``0`` for exactly this reason).
- ``list_managed()`` includes the started container.
- ``stop(handle, timeout_s=...)`` moves the container to
  ``ContainerState.EXITED`` with exit code ``0``; afterwards
  ``is_running`` is ``False``.
- Edge cases: ``start`` with an already-used name raises
  ``ContainerNameConflictError``; ``stop`` on an already-stopped
  container is a no-op, not an error.

Deliberately out of scope for this file (later ledger behaviours on the
same branch): scripted ``FAIL_TO_START`` (behaviour 11), death and
``vanish()`` (12), ``logs`` and the ``fake.calls`` journal (13).

This file is the RED step: ``src/tool_swap/backend/fake_backend.py``
does not exist yet.  A module-scope ``from tool_swap.backend.fake_backend
import FakeBackend`` would raise ``ModuleNotFoundError`` and abort pytest
*collection* of the whole suite before a single assertion executed — the
exact failure that got behaviour 3's first red step rejected.  The import
is therefore deferred out of module scope into :func:`_get_fake_backend`,
following the committed pattern in ``test_mount_spec.py``: while the
module is absent every test fails *individually* at the gate, with its
assertions present and reachable; the moment the GREEN step creates
``fake_backend.py`` the call resolves and each test proceeds to its own
assertions.  No ``importorskip`` and no skip of any kind is used — a
skipped test is not a red step, it is a test that silently does not run.

No docker fact appears anywhere in this file: the fake is in-memory by
construction, so every assertion is about the seam's own types
(``ContainerSpec``, ``ContainerHandle``, ``ContainerState``,
``ContainerStatus``) and the seam's own error
(``ContainerNameConflictError``), both of which already exist.  Had a
docker fact seemed necessary, that would signal drift toward
``DockerBackend``.

Two behaviours deliberately *not* pinned here:

- **The mount-parsing boundary** (no ``parse_mount``, no ``":"`` split)
  is already policed for ``fake_backend.py`` by the committed guard in
  ``test_backend_mount_parsing_guard.py``, which walks every module
  under ``src/tool_swap/backend/``.  A second guard here would
  duplicate it.
- **Importability with the docker SDK absent** belongs to behaviour 27,
  whose import-linter contract and ``docker``-blocked ``sys.modules``
  test exist precisely to pin it.  Pinning it here would leave
  behaviour 27 without a test of its own.

Conventions: pytest, AAA pattern, no ``warnings.warn`` (pyproject sets
``filterwarnings = "error"``).
"""

from __future__ import annotations

import importlib
import inspect
from types import ModuleType
from typing import Any, cast

import pytest

from tool_swap.backend.errors import ContainerNameConflictError


def _get_fake_backend() -> type[Any]:
    """Import and return the ``FakeBackend`` class, RED-safely.

    The import is deferred out of module scope — via
    ``importlib.import_module`` so that the not-yet-existing
    ``tool_swap.backend.fake_backend`` module cannot abort pytest
    collection of this file (and thereby of the whole suite).  While
    the module is absent this raises ``AssertionError`` naming the
    missing module, so every test fails individually instead of the
    run being interrupted during collection.

    Raises:
        AssertionError: ``tool_swap.backend.fake_backend`` does not
            exist, or does not define ``FakeBackend`` yet — the GREEN
            step must create ``src/tool_swap/backend/fake_backend.py``
            with ``FakeBackend``.
    """
    try:
        module: ModuleType = importlib.import_module("tool_swap.backend.fake_backend")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.backend.fake_backend is missing — the GREEN step "
            "must create src/tool_swap/backend/fake_backend.py with "
            "FakeBackend"
        ) from exc
    try:
        fake_cls = module.FakeBackend
    except AttributeError as exc:
        raise AssertionError(
            "tool_swap.backend.fake_backend.FakeBackend is missing — the "
            "GREEN step must define FakeBackend in "
            "src/tool_swap/backend/fake_backend.py"
        ) from exc
    return cast("type[Any]", fake_cls)


def _get_base_module() -> ModuleType:
    """Import ``tool_swap.backend.base`` at call time.

    Behaviours 3–5 already landed it; the call-time import keeps this
    file's style uniform with the other backend test files, which
    defer every ``tool_swap`` import for the same reason.

    Raises:
        AssertionError: the module cannot be imported — behaviours 3–5
            already landed ``src/tool_swap/backend/base.py``.
    """
    try:
        module = importlib.import_module("tool_swap.backend.base")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.backend.base is missing — behaviours 3-5 already "
            "landed src/tool_swap/backend/base.py"
        ) from exc
    return module


def _spec(base: ModuleType, *, tool: str, name: str) -> Any:
    """A minimal ``ContainerSpec`` for the named tool.

    Values are neutral and deliberately distinct from
    ``BUILT_IN_DEFAULTS``: behaviour 10 is about the seam's behaviour,
    and this file must not restate any configured default.
    """
    return base.ContainerSpec(
        tool=tool,
        name=name,
        image="example/tool:1.0",
        gpu_runtime="cuda",
        container_port=8080,
    )


def test_fake_backend_constructible_with_no_arguments() -> None:
    """``FakeBackend()`` is a valid construction for behaviour 10 (§4.4)."""
    # Arrange
    fake_cls = _get_fake_backend()
    # Act
    backend = fake_cls()
    # Assert
    assert isinstance(backend, fake_cls)


def test_fake_backend_constructor_declares_script_defaulting_to_none() -> None:
    """§4.4: the constructor declares ``script`` defaulting to ``None``.

    Behaviour 10 only exercises the no-script path, but the parameter's
    name and default are what make that path legal — behaviour 11
    scripts ``FAIL_TO_START`` through exactly this argument.
    """
    # Arrange
    fake_cls = _get_fake_backend()
    # Act
    params = inspect.signature(fake_cls).parameters
    # Assert
    assert "script" in params
    assert params["script"].default is None


def test_fake_backend_start_returns_handle_matching_spec() -> None:
    """``start`` returns a ``ContainerHandle`` echoing the spec's identity."""
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    spec = _spec(base, tool="llama", name="ms-llama")
    # Act
    handle = backend.start(spec)
    # Assert
    assert isinstance(handle, base.ContainerHandle)
    assert handle.name == spec.name
    assert handle.tool == spec.tool
    assert handle.image == spec.image
    assert isinstance(handle.id, str)
    assert handle.id


def test_fake_backend_start_assigns_unique_id_per_start() -> None:
    """Two different containers get distinct, non-empty ids."""
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    # Act
    first = backend.start(_spec(base, tool="llama", name="ms-llama"))
    second = backend.start(_spec(base, tool="vit", name="ms-vit"))
    # Assert
    assert first.id != second.id
    assert first.id
    assert second.id


def test_fake_backend_is_running_is_true_for_running_container() -> None:
    """A freshly started container reports ``is_running`` as ``True``."""
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    handle = backend.start(_spec(base, tool="llama", name="ms-llama"))
    # Act
    running = backend.is_running(handle)
    # Assert
    assert running is True


def test_fake_backend_inspect_running_container_reports_running() -> None:
    """``inspect`` on a started container is ``RUNNING`` and
    ``exit_code=None`` (a running container has not exited).
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    handle = backend.start(_spec(base, tool="llama", name="ms-llama"))
    # Act
    status = backend.inspect(handle)
    # Assert
    assert isinstance(status, base.ContainerStatus)
    assert status.handle == handle
    assert status.state is base.ContainerState.RUNNING
    assert status.exit_code is None


def test_fake_backend_list_managed_includes_started_container() -> None:
    """``list_managed`` returns the started container's handle."""
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    handle = backend.start(_spec(base, tool="llama", name="ms-llama"))
    # Act
    listed = backend.list_managed()
    # Assert
    assert handle in listed


def test_fake_backend_stop_transitions_container_to_exited() -> None:
    """After ``stop`` the container is ``EXITED`` with exit code ``0``."""
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    handle = backend.start(_spec(base, tool="llama", name="ms-llama"))
    # Act
    backend.stop(handle, timeout_s=5.0)
    status = backend.inspect(handle)
    # Assert
    assert status.state is base.ContainerState.EXITED
    assert status.exit_code == 0


def test_fake_backend_is_running_is_false_after_stop() -> None:
    """After ``stop`` the container reports ``is_running`` as ``False``."""
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    handle = backend.start(_spec(base, tool="llama", name="ms-llama"))
    # Act
    backend.stop(handle, timeout_s=5.0)
    running = backend.is_running(handle)
    # Assert
    assert running is False


def test_fake_backend_starting_same_name_twice_raises_name_conflict() -> None:
    """A second ``start`` with an already-used name raises
    ``ContainerNameConflictError`` (the taxonomy member, never a bare
    ``Exception``).
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    backend.start(_spec(base, tool="llama", name="ms-llama"))
    # Act / Assert
    with pytest.raises(ContainerNameConflictError):
        backend.start(_spec(base, tool="llama", name="ms-llama"))


def test_fake_backend_stop_on_stopped_container_is_no_op() -> None:
    """``stop`` on an already-stopped container is a no-op, not an error."""
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    handle = backend.start(_spec(base, tool="llama", name="ms-llama"))
    backend.stop(handle, timeout_s=5.0)
    # Act — must not raise
    backend.stop(handle, timeout_s=5.0)
    # Assert — the first stop's result is unchanged
    status = backend.inspect(handle)
    assert status.state is base.ContainerState.EXITED
    assert status.exit_code == 0
    assert backend.is_running(handle) is False

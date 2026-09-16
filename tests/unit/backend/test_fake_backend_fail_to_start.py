"""RED step for M2a behaviour 11 — ``FakeBackend`` scripted ``FAIL_TO_START``.

See ``plans/m2a-container-backend-seam.md`` §4.4 and behaviour 11 (§5):

- ``FakeBackend(script={"t1": FailureMode.FAIL_TO_START})``, then
  ``start`` for a spec whose ``tool`` is ``"t1"`` raises
  ``ContainerStartError`` — the taxonomy member, never a bare
  ``Exception`` — whose message names the tool, so a test failure or a
  surfaced ``/status`` reason says *which* tool refused to start.
- No container is recorded: ``list_managed`` stays empty after a
  scripted failure.
- Edge cases: an unscripted tool in the same backend still starts
  normally; the failure repeats on retry (the script is not one-shot,
  so a retry loop can never silently succeed).

Deliberately out of scope for this file (later ledger behaviours on the
same branch): ``DIE_AFTER_START`` and ``vanish()`` (behaviour 12),
``logs`` and the ``fake.calls`` journal (behaviour 13).  Nothing here
asserts on a call journal: ``fake.calls`` does not exist yet and is
behaviour 13's deliverable.

This file is the RED step: behaviour 10 shipped
``src/tool_swap/backend/fake_backend.py`` storing the script, but it
acts on none of it — so where these tests expect a refusal, ``start``
currently *succeeds*.  That is the correct red: each scripted-failure
test fails at its own ``pytest.raises`` (DID NOT RAISE) or on its own
assertion.  The import is deferred out of module scope via the gate
helpers below, following the committed pattern in
``test_fake_backend_happy_path.py``, so that if the module ever went
missing again every test would fail *individually* rather than
aborting pytest collection, and the two files read as one suite.

No docker fact appears anywhere in this file: the fake is in-memory by
construction, so every assertion is about the seam's own types
(``ContainerSpec``, ``ContainerHandle``) and the seam's own error
(``ContainerStartError``), both of which already exist.

Conventions: pytest, AAA pattern, no ``warnings.warn`` (pyproject sets
``filterwarnings = "error"``).
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any, cast

import pytest

from tool_swap.backend.errors import ContainerStartError


def _get_fake_backend() -> type[Any]:
    """Import and return the ``FakeBackend`` class, RED-safely.

    The import is deferred out of module scope — via
    ``importlib.import_module`` — following the committed gate helper
    in ``test_fake_backend_happy_path.py``, so that while the module
    is absent every test fails *individually* at the gate instead of
    the run being interrupted during collection.

    Raises:
        AssertionError: ``tool_swap.backend.fake_backend`` does not
            exist, or does not define ``FakeBackend`` — behaviour 10
            already shipped ``src/tool_swap/backend/fake_backend.py``.
    """
    try:
        module: ModuleType = importlib.import_module("tool_swap.backend.fake_backend")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.backend.fake_backend is missing — behaviour 10 "
            "already shipped src/tool_swap/backend/fake_backend.py"
        ) from exc
    try:
        fake_cls = module.FakeBackend
    except AttributeError as exc:
        raise AssertionError(
            "tool_swap.backend.fake_backend.FakeBackend is missing — "
            "behaviour 10 already shipped it in "
            "src/tool_swap/backend/fake_backend.py"
        ) from exc
    return cast("type[Any]", fake_cls)


def _get_failure_mode() -> type[Any]:
    """Import and return the ``FailureMode`` enum, RED-safely.

    Same deferred-import gate as :func:`_get_fake_backend`; the two
    symbols live in one module, but a distinct gate names the missing
    symbol precisely in the failure message.

    Raises:
        AssertionError: ``tool_swap.backend.fake_backend`` does not
            exist, or does not define ``FailureMode`` — behaviour 10
            already shipped it.
    """
    try:
        module: ModuleType = importlib.import_module("tool_swap.backend.fake_backend")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.backend.fake_backend is missing — behaviour 10 "
            "already shipped src/tool_swap/backend/fake_backend.py"
        ) from exc
    try:
        mode_cls = module.FailureMode
    except AttributeError as exc:
        raise AssertionError(
            "tool_swap.backend.fake_backend.FailureMode is missing — "
            "behaviour 10 already shipped it in "
            "src/tool_swap/backend/fake_backend.py"
        ) from exc
    return cast("type[Any]", mode_cls)


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

    The tool is the script key: §4.4 scripts failures by tool name so
    a test can declare a failure before any handle exists.  The name
    mirrors the tool to keep the two identities distinct in any
    failure message.
    """
    return base.ContainerSpec(
        tool=tool,
        name=name,
        image="example/tool:1.0",
        gpu_runtime="cuda",
        container_port=8080,
    )


def test_fake_backend_scripted_fail_to_start_raises_container_start_error() -> None:
    """A scripted tool refuses to start with ``ContainerStartError`` —
    the taxonomy member, never a bare ``Exception``.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    fail_to_start = _get_failure_mode()
    backend = fake_cls(script={"t1": fail_to_start.FAIL_TO_START})
    spec = _spec(base, tool="t1", name="ms-t1")
    # Act / Assert — pytest.raises on the concrete member also proves
    # the error is a taxonomy member: a bare Exception would not match.
    with pytest.raises(ContainerStartError):
        backend.start(spec)


def test_fake_backend_fail_to_start_error_message_names_the_tool() -> None:
    """The raised ``ContainerStartError``'s message names the tool.

    The plan's "whose message names the tool" is what makes a test
    failure or an M2b ``FAILED`` reason say *which* tool refused to
    start — the message is reused verbatim, so naming the tool is the
    whole of the diagnostic.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    fail_to_start = _get_failure_mode()
    backend = fake_cls(script={"t1": fail_to_start.FAIL_TO_START})
    spec = _spec(base, tool="t1", name="ms-t1")
    # Act / Assert
    with pytest.raises(ContainerStartError) as excinfo:
        backend.start(spec)
    assert "t1" in excinfo.value.message


def test_fake_backend_fail_to_start_records_no_container() -> None:
    """After a scripted failure no container is recorded:
    ``list_managed`` stays empty.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    fail_to_start = _get_failure_mode()
    backend = fake_cls(script={"t1": fail_to_start.FAIL_TO_START})
    spec = _spec(base, tool="t1", name="ms-t1")
    with pytest.raises(ContainerStartError):
        backend.start(spec)
    # Act
    listed = backend.list_managed()
    # Assert
    assert listed == []


def test_fake_backend_unscripted_tool_still_starts_normally() -> None:
    """A tool absent from the script starts normally in the same
    backend — the script is keyed by tool, not a blanket refusal.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    fail_to_start = _get_failure_mode()
    backend = fake_cls(script={"t1": fail_to_start.FAIL_TO_START})
    spec = _spec(base, tool="t2", name="ms-t2")
    # Act
    handle = backend.start(spec)
    # Assert
    assert isinstance(handle, base.ContainerHandle)
    assert handle.tool == "t2"
    assert backend.is_running(handle) is True


def test_fake_backend_fail_to_start_repeats_on_retry() -> None:
    """The scripted failure repeats on retry — the script is not
    one-shot, so a retry loop can never silently succeed.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    fail_to_start = _get_failure_mode()
    backend = fake_cls(script={"t1": fail_to_start.FAIL_TO_START})
    spec = _spec(base, tool="t1", name="ms-t1")
    # Act / Assert — both attempts must refuse
    with pytest.raises(ContainerStartError):
        backend.start(spec)
    with pytest.raises(ContainerStartError):
        backend.start(spec)
    # Assert — and still nothing is recorded
    assert backend.list_managed() == []

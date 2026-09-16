"""RED step for M2a behaviour 12 — ``FakeBackend`` death and vanishing.

See ``plans/m2a-container-backend-seam.md`` §4.4, §6 (items 3 and 4)
and behaviour 12 (§5):

- A tool scripted ``DIE_AFTER_START`` starts normally — ``start``
  succeeds and returns a handle, in contrast to ``FAIL_TO_START``
  (behaviour 11), which refuses — and the container is dead by the
  first observation: ``is_running`` is ``False`` and ``inspect`` is
  ``EXITED`` with a *non-zero* exit code.  The fake has no daemon, no
  clock and no thread, so the death must be observable without any of
  those; the pinned contract is therefore "dead by the first
  observation" — there is no observable ``RUNNING`` window and no
  step in between.
- ``exit_code`` is asserted non-zero, not a specific number: the
  plan says only "non-zero" and no saved document names one, so a
  specific code would be an invented fact — the exact failure
  behaviour 7's rejected red step made.
- ``fake.vanish(handle)`` on a running container removes it:
  ``inspect`` is ``GONE`` (with ``exit_code=None``) and
  ``is_running`` is ``False`` **without raising** — the §4.3
  not-found contract.  The "without raising" is the load-bearing
  part (plan §6 item 4): if ``is_running`` raised, M2b's liveness
  sweep becomes an unhandled traceback in the watchdog.  The test
  therefore calls it directly and lets any raise fail the test
  visibly, not just assert the returned value.
- Edge cases: ``stop`` on a vanished container is a no-op, not an
  error; ``vanish`` on an unknown handle raises
  ``ContainerNotFoundError``; a vanished container disappears from
  ``list_managed``.  A *dead* (``DIE_AFTER_START``) container stays
  listed, like a stopped one (behaviour 10, plan §6 item 5) — only
  the *vanished* one disappears.

Deliberately out of scope for this file: ``logs`` and the
``fake.calls`` journal (behaviour 13).  Nothing here asserts on a
call journal — it does not exist yet.

This file is the RED step.  Behaviour 11 shipped
``src/tool_swap/backend/fake_backend.py`` with ``DIE_AFTER_START``
*stored but un-honoured*, so the death tests fail by observing a
container that is still ``RUNNING``; and ``vanish`` does not exist
yet, so the vanish tests fail at a per-method gate that raises
``AssertionError`` naming the missing method — not a raw
``AttributeError``.  The class and enum imports are deferred out of
module scope via the gate helpers, following the committed pattern in
``test_fake_backend_happy_path.py`` and
``test_fake_backend_fail_to_start.py``, so that if the module ever
went missing again every test would fail *individually* rather than
aborting pytest collection, and the three files read as one suite.

No docker fact appears anywhere in this file: the fake is in-memory
by construction, so every assertion is about the seam's own types
and the seam's own error (``ContainerNotFoundError``), all of which
already exist.

Conventions: pytest, AAA pattern, no ``warnings.warn`` (pyproject
sets ``filterwarnings = "error"``).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from types import ModuleType
from typing import Any, cast

import pytest

from tool_swap.backend.errors import ContainerNotFoundError


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


def _get_vanish(backend: Any) -> Callable[[Any], None]:
    """Fetch ``backend.vanish`` RED-safely.

    ``vanish`` is behaviour 12's own deliverable, so it does not exist
    yet: grabbing it directly would raise a raw ``AttributeError``.
    The gate converts that into an ``AssertionError`` naming the
    missing method, so every vanish test fails at the gate with a
    message that tells the GREEN step exactly what to add.

    Args:
        backend: A constructed ``FakeBackend`` instance.

    Returns:
        The bound ``vanish`` method.

    Raises:
        AssertionError: the backend has no ``vanish`` method — the
            GREEN step must add ``vanish(handle)`` to
            ``src/tool_swap/backend/fake_backend.py``.
    """
    try:
        vanish = backend.vanish
    except AttributeError as exc:
        raise AssertionError(
            "FakeBackend.vanish is missing — the GREEN step must add "
            "vanish(handle) to src/tool_swap/backend/fake_backend.py "
            "(behaviour 12)"
        ) from exc
    return cast("Callable[[Any], None]", vanish)


def _get_base_module() -> ModuleType:
    """Import ``tool_swap.backend.base`` at call time.

    Behaviours 3–5 already landed it; the call-time import keeps this
    file's style uniform with the other backend test files, which
    defer every ``tool_swap`` import for the same reason.

    Raises:
        AssertionError: the module cannot be imported — behaviours
            3–5 already landed ``src/tool_swap/backend/base.py``.
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


def test_fake_backend_die_after_start_start_succeeds_and_returns_handle() -> None:
    """A scripted death is not a scripted refusal: ``start`` succeeds
    and returns a handle echoing the spec's identity.

    This is the contrast with behaviour 11's ``FAIL_TO_START``, which
    raises ``ContainerStartError`` — "after start" means the start
    itself succeeds.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    die_after_start = _get_failure_mode()
    backend = fake_cls(script={"t1": die_after_start.DIE_AFTER_START})
    spec = _spec(base, tool="t1", name="ms-t1")
    # Act — must not raise
    handle = backend.start(spec)
    # Assert
    assert isinstance(handle, base.ContainerHandle)
    assert handle.name == spec.name
    assert handle.tool == spec.tool
    assert handle.image == spec.image
    assert isinstance(handle.id, str)
    assert handle.id


def test_fake_backend_die_after_start_is_running_is_false() -> None:
    """After a scripted death ``is_running`` is ``False``.

    The container is dead by the first observation: with no daemon,
    no clock and no thread there is no observable ``RUNNING`` window,
    so the first ``is_running`` call a M2b liveness sweep would make
    already reports ``False``.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    die_after_start = _get_failure_mode()
    backend = fake_cls(script={"t1": die_after_start.DIE_AFTER_START})
    handle = backend.start(_spec(base, tool="t1", name="ms-t1"))
    # Act
    running = backend.is_running(handle)
    # Assert
    assert running is False


def test_fake_backend_die_after_start_inspect_is_exited_with_nonzero() -> None:
    """After a scripted death ``inspect`` is ``EXITED`` with a
    non-zero exit code.

    The plan says only "non-zero": no saved document names a specific
    code, so the test asserts non-zero rather than pinning one — a
    specific code would be an invented fact, the exact failure
    behaviour 7's rejected red step made.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    die_after_start = _get_failure_mode()
    backend = fake_cls(script={"t1": die_after_start.DIE_AFTER_START})
    handle = backend.start(_spec(base, tool="t1", name="ms-t1"))
    # Act
    status = backend.inspect(handle)
    # Assert
    assert isinstance(status, base.ContainerStatus)
    assert status.handle == handle
    assert status.state is base.ContainerState.EXITED
    assert status.exit_code is not None
    assert status.exit_code != 0


def test_fake_backend_die_after_start_container_stays_listed() -> None:
    """A dead container stays in ``list_managed``, like a stopped one.

    Plan §6 item 5: reconciliation adopts by label, and a dead
    container is still a container that exists — only a *vanished*
    one (removed out of band) disappears from the list.  M2b needs to
    see the dead handle to mark it ``FAILED`` rather than lose it.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    die_after_start = _get_failure_mode()
    backend = fake_cls(script={"t1": die_after_start.DIE_AFTER_START})
    handle = backend.start(_spec(base, tool="t1", name="ms-t1"))
    # Act
    listed = backend.list_managed()
    # Assert
    assert handle in listed


def test_fake_backend_unscripted_tool_still_running_next_to_died_one() -> None:
    """The script is keyed by tool: an unscripted tool in the same
    backend is running while the scripted one is dead.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    die_after_start = _get_failure_mode()
    backend = fake_cls(script={"t1": die_after_start.DIE_AFTER_START})
    dead = backend.start(_spec(base, tool="t1", name="ms-t1"))
    alive = backend.start(_spec(base, tool="t2", name="ms-t2"))
    # Act
    dead_running = backend.is_running(dead)
    alive_running = backend.is_running(alive)
    # Assert
    assert alive_running is True
    assert dead_running is False


def test_fake_backend_vanish_inspect_is_gone() -> None:
    """After ``vanish`` the container reads ``GONE`` with
    ``exit_code=None`` — the §4.3 not-found contract.

    ``vanish`` is out-of-band removal (the fake half of docker
    contract test 3: ``docker rm -f`` behind the backend's back), so
    the container is as far as the seam is concerned unknown, exactly
    like a handle that was never started.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    handle = backend.start(_spec(base, tool="t1", name="ms-t1"))
    vanish = _get_vanish(backend)
    # Act
    vanish(handle)
    status = backend.inspect(handle)
    # Assert
    assert isinstance(status, base.ContainerStatus)
    assert status.handle == handle
    assert status.state is base.ContainerState.GONE
    assert status.exit_code is None


def test_fake_backend_vanish_is_running_false_without_raising() -> None:
    """After ``vanish`` ``is_running`` is ``False`` — without raising.

    The "without raising" is the load-bearing part (plan §6 item 4):
    a raise here turns M2b's liveness sweep into an unhandled
    traceback in the watchdog.  The call is made directly, so a
    future implementation that raises fails this test with that
    raise, not just by returning the wrong value.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    handle = backend.start(_spec(base, tool="t1", name="ms-t1"))
    vanish = _get_vanish(backend)
    vanish(handle)
    # Act — must not raise
    running = backend.is_running(handle)
    # Assert
    assert running is False


def test_fake_backend_vanish_unknown_handle_raises_container_not_found_error() -> None:
    """``vanish`` on a handle the backend does not manage raises
    ``ContainerNotFoundError`` — the taxonomy member, never a bare
    ``Exception``.

    Unlike the read-side §4.3 contract (``is_running`` ``False``,
    ``inspect`` ``GONE``, ``stop`` no-op), ``vanish`` is an active
    operation: it names a container that is not there, and "every
    other method raises" (plan §4.3).
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    vanish = _get_vanish(backend)
    unknown = base.ContainerHandle(
        id="ghost-id",
        name="ms-ghost",
        tool="ghost",
        image="example/tool:1.0",
    )
    # Act / Assert
    with pytest.raises(ContainerNotFoundError):
        vanish(unknown)


def test_fake_backend_stop_on_vanished_container_is_no_op() -> None:
    """``stop`` on a vanished container is a no-op, not an error.

    The §4.3 not-found contract covers ``stop`` explicitly, and a
    vanished container is the most missing of missing containers —
    M2b's drain path stops whatever it still thinks it manages.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    handle = backend.start(_spec(base, tool="t1", name="ms-t1"))
    vanish = _get_vanish(backend)
    vanish(handle)
    # Act — must not raise
    backend.stop(handle, timeout_s=5.0)
    # Assert — the vanishing is unchanged; stop did not resurrect it
    status = backend.inspect(handle)
    assert status.state is base.ContainerState.GONE
    assert backend.is_running(handle) is False


def test_fake_backend_vanished_container_disappears_from_list_managed() -> None:
    """A vanished container disappears from ``list_managed`` — while
    the surviving one stays, which is what distinguishes "vanished"
    from "dead": a dead container stays listed, a vanished one does
    not.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    vanished = backend.start(_spec(base, tool="t1", name="ms-t1"))
    survivor = backend.start(_spec(base, tool="t2", name="ms-t2"))
    vanish = _get_vanish(backend)
    # Act
    vanish(vanished)
    listed = backend.list_managed()
    # Assert
    assert vanished not in listed
    assert listed == [survivor]

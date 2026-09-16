"""RED step for M2a behaviour 8 — the ``ContainerBackend`` protocol.

See ``plans/m2a-container-backend-seam.md`` §4.1 and behaviour 8 (§5):

- ``ContainerBackend`` is a ``@runtime_checkable`` ``typing.Protocol`` in
  ``src/tool_swap/backend/base.py`` — "the ONLY component that touches a
  container runtime" — declaring exactly six methods: ``start``,
  ``stop``, ``is_running``, ``inspect``, ``list_managed``, ``logs``.
- Each signature is pinned per §4.1 via ``inspect.signature`` and
  ``get_type_hints``: parameter names, their order, their kinds
  (``stop`` / ``logs`` keyword-only) and every annotation.  This is the
  anti-drift test for the whole seam: every later branch
  (``FakeBackend``, ``DockerBackend``, M2b's ``LifecycleManager``) is
  written against this declaration, so a drift must fail here, at the
  cause, rather than surfacing far from it.
- ``build`` is deliberately ABSENT (deferred to M5); a test pins that,
  making the plan's recorded divergence from architecture §12
  enforceable.
- The seam is synchronous: no method is a coroutine function.  The
  docker SDK is blocking; M2b's ``LifecycleManager`` is the async layer
  and will off-load these calls.
- ``inspect`` returns ``ContainerStatus`` (behaviour 5), never a raw
  SDK dict — the seam that exists to contain SDK vocabulary must not
  leak it.

``logs`` returns ``Iterator[str]``.  The return pin checks
``typing.get_origin(...) is collections.abc.Iterator`` and
``typing.get_args(...) == (str,)`` rather than alias identity, because
``collections.abc.Iterator[str]`` and ``typing.Iterator[str]`` normalize
to the same origin and args and are the same annotation under either
import form; pinning alias identity would reject the ``typing`` form
for no behavioural reason.  An ``AsyncIterator[str]``, a ``list[str]``
or a bare ``str`` all fail the pin.

This file is the RED step: ``base.py`` exists (behaviours 3-5
committed) but does not define ``ContainerBackend`` yet.  Every access
to ``tool_swap`` is therefore deferred out of module scope into
call-time helpers, following ``test_container_spec.py`` exactly:

- A module-level ``from tool_swap.backend.base import ContainerBackend``
  would raise ``ImportError`` on the missing *name* and abort pytest
  *collection* of the whole suite before a single assertion executed.
  :func:`_get_container_backend` instead raises ``AssertionError``
  inside each test, so every test fails individually; the moment the
  GREEN step adds the protocol the call resolves and each test proceeds
  to its own assertions.
- The behaviour-3-5 data types (``ContainerSpec``,
  ``ContainerHandle``, ``ContainerStatus``) exist on this branch and
  anchor the annotation pins.  They are fetched at call time too,
  because the editable ``tool_swap`` install carries no ``py.typed``
  marker and a module-scope import of it would fail ``mypy --strict``
  on this file.

Tautology guard: the load-bearing assertions are all
``inspect.signature`` / ``get_type_hints`` introspection of
``ContainerBackend``'s own declared members.  The one
``isinstance``-based test uses local stubs only to pin the
``runtime_checkable`` name-matching semantics in the positive
direction — ``isinstance`` on a runtime-checkable protocol checks
member *names* only, so it can never substitute for the signature
pins.

No ``importorskip`` and no skip of any kind is used — a skipped test is
not a red step, it is a test that silently does not run.

Conventions: pytest, AAA pattern, no ``warnings.warn`` (pyproject sets
``filterwarnings = "error"``).
"""

from __future__ import annotations

import collections.abc
import importlib
import inspect
import typing
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
        AssertionError: ``tool_swap.backend.base`` does not exist —
            behaviour 3 committed it; it must not be removed.
    """
    try:
        module = importlib.import_module("tool_swap.backend.base")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.backend.base is missing — it must exist in "
            "src/tool_swap/backend/base.py"
        ) from exc
    return module


def _get_container_backend() -> type[Any]:
    """Import and return the ``ContainerBackend`` protocol, RED-safely.

    While ``base.py`` lacks ``ContainerBackend`` this raises
    ``AssertionError`` naming the missing name, so every test fails
    individually instead of the run being interrupted during
    collection.  ``AttributeError`` is the RED failure mode here (a
    missing *name* in an existing module).

    Raises:
        AssertionError: ``ContainerBackend`` is not defined in
            ``tool_swap.backend.base`` yet — the GREEN step must add it.
    """
    module = _get_backend_module()
    try:
        backend_cls = module.ContainerBackend
    except AttributeError as exc:
        raise AssertionError(
            "tool_swap.backend.base.ContainerBackend is missing — the "
            "GREEN step must add the protocol to "
            "src/tool_swap/backend/base.py"
        ) from exc
    return cast("type[Any]", backend_cls)


def _get_data_type(name: str) -> type[Any]:
    """Return a committed behaviour-3-5 data type from ``base.py``.

    ``ContainerSpec``, ``ContainerHandle`` and ``ContainerStatus``
    exist on this branch and anchor the annotation pins.  Fetched at
    call time for the same mypy reason as the other gates.

    Raises:
        AssertionError: the named type is missing from
            ``tool_swap.backend.base`` — the annotation pins depend on
            it and cannot run.
    """
    module = _get_backend_module()
    try:
        data_cls = getattr(module, name)
    except AttributeError as exc:
        raise AssertionError(
            f"tool_swap.backend.base.{name} is missing — the annotation "
            "pins depend on it (behaviours 3-5)"
        ) from exc
    return cast("type[Any]", data_cls)


def _sig(signature: inspect.Signature) -> list[tuple[str, int]]:
    """``(name, kind.value)`` pairs in declaration order.

    The comparable form of a signature: it pins parameter names, their
    order and their kinds (positional vs keyword-only) in one
    structure, so a drift in any of the three fails one assertion.  The
    kind is its integer ``enum`` value — the named constants
    ``POSITIONAL_OR_KEYWORD`` and ``KEYWORD_ONLY`` both expose the same
    values — because the kind's enum class
    (``inspect._ParameterKind``) is private and unannotatable.
    """
    return [(p.name, int(p.kind.value)) for p in signature.parameters.values()]


class _ConformantStub:
    """A stub carrying all six member names.

    ``runtime_checkable`` ``isinstance`` checks match on member *names*
    only — never on signatures — so this stub exists solely to pin that
    name-matching in the positive direction.  The signature pins are
    the load-bearing assertions and stand on their own.
    """

    def start(self, spec: Any) -> Any:
        raise NotImplementedError("name-only stub; never called by the test")

    def stop(self, handle: Any, *, timeout_s: float) -> None:
        raise NotImplementedError("name-only stub; never called by the test")

    def is_running(self, handle: Any) -> bool:
        raise NotImplementedError("name-only stub; never called by the test")

    def inspect(self, handle: Any) -> Any:
        raise NotImplementedError("name-only stub; never called by the test")

    def list_managed(self) -> list[Any]:
        raise NotImplementedError("name-only stub; never called by the test")

    def logs(
        self, handle: Any, *, follow: bool, tail: int
    ) -> collections.abc.Iterator[Any]:
        raise NotImplementedError("name-only stub; never called by the test")


class _StubMissingInspect:
    """A stub with all six members except ``inspect``.

    The negative half of the name-matching pin: one missing member must
    make the runtime check fail.
    """

    def start(self, spec: Any) -> Any:
        raise NotImplementedError("name-only stub; never called by the test")

    def stop(self, handle: Any, *, timeout_s: float) -> None:
        raise NotImplementedError("name-only stub; never called by the test")

    def is_running(self, handle: Any) -> bool:
        raise NotImplementedError("name-only stub; never called by the test")

    def list_managed(self) -> list[Any]:
        raise NotImplementedError("name-only stub; never called by the test")

    def logs(
        self, handle: Any, *, follow: bool, tail: int
    ) -> collections.abc.Iterator[Any]:
        raise NotImplementedError("name-only stub; never called by the test")


def test_container_backend_is_runtime_checkable_protocol() -> None:
    """ContainerBackend is a Protocol decorated with @runtime_checkable.

    ``_is_protocol`` is the marker ``typing.Protocol`` sets (and the
    one ``typing.runtime_checkable`` itself reads).  The ``isinstance``
    call proves the decorator was applied: a non-runtime-checkable
    protocol raises ``TypeError`` on any instance check, while a
    runtime-checkable one evaluates — and must evaluate to ``False``
    for ``object()``, which carries none of the six members.
    """
    # Arrange
    backend_cls = _get_container_backend()
    # Act
    protocol_marker = getattr(backend_cls, "_is_protocol", False)
    non_conformant = isinstance(object(), backend_cls)
    # Assert
    assert protocol_marker is True
    assert non_conformant is False


def test_container_backend_declares_exactly_the_six_methods() -> None:
    """The public surface is exactly the six §4.1 methods — no more.

    Pinning the exact set (rather than merely that the six exist)
    catches both a removed method and a smuggled-in extra such as
    ``build``.  ``dir`` on a protocol class exposes its declared
    members plus only dunder names, so an underscore-free ``dir``
    comparison is the method set itself.
    """
    # Arrange
    backend_cls = _get_container_backend()
    # Act
    public_names = sorted(n for n in dir(backend_cls) if not n.startswith("_"))
    # Assert
    assert public_names == [
        "inspect",
        "is_running",
        "list_managed",
        "logs",
        "start",
        "stop",
    ]


def test_container_backend_does_not_declare_build() -> None:
    """``build`` is absent: it is M5's, not the seam's.

    Architecture §12 lists ``build`` on the backend, but the plan
    records its absence here as a deliberate divergence — adding it now
    would force both implementations to carry a stub.  Issue #3's
    Definition of Done names exactly the six other methods.
    """
    # Arrange
    backend_cls = _get_container_backend()
    # Act
    declared = dir(backend_cls)
    # Assert
    assert "build" not in declared


def test_container_backend_start_signature_is_pinned() -> None:
    """``start(spec: ContainerSpec) -> ContainerHandle`` — §4.1 verbatim."""
    # Arrange
    backend_cls = _get_container_backend()
    spec_cls = _get_data_type("ContainerSpec")
    handle_cls = _get_data_type("ContainerHandle")
    # Act
    signature = inspect.signature(backend_cls.start)
    hints = get_type_hints(backend_cls.start)
    # Assert
    assert _sig(signature) == [
        ("self", inspect.Parameter.POSITIONAL_OR_KEYWORD.value),
        ("spec", inspect.Parameter.POSITIONAL_OR_KEYWORD.value),
    ]
    assert hints == {"spec": spec_cls, "return": handle_cls}


def test_container_backend_stop_signature_is_pinned() -> None:
    """``stop(handle, *, timeout_s: float) -> None``.

    ``timeout_s`` must stay keyword-only: ``stop(handle,
    timeout_s=30)`` reads unambiguously, where a positional timeout is
    easy to confuse with a retry count at a call site.
    """
    # Arrange
    backend_cls = _get_container_backend()
    handle_cls = _get_data_type("ContainerHandle")
    # Act
    signature = inspect.signature(backend_cls.stop)
    hints = get_type_hints(backend_cls.stop)
    # Assert
    assert _sig(signature) == [
        ("self", inspect.Parameter.POSITIONAL_OR_KEYWORD.value),
        ("handle", inspect.Parameter.POSITIONAL_OR_KEYWORD.value),
        ("timeout_s", inspect.Parameter.KEYWORD_ONLY.value),
    ]
    assert hints == {"handle": handle_cls, "timeout_s": float, "return": type(None)}


def test_container_backend_is_running_signature_is_pinned() -> None:
    """``is_running(handle: ContainerHandle) -> bool``."""
    # Arrange
    backend_cls = _get_container_backend()
    handle_cls = _get_data_type("ContainerHandle")
    # Act
    signature = inspect.signature(backend_cls.is_running)
    hints = get_type_hints(backend_cls.is_running)
    # Assert
    assert _sig(signature) == [
        ("self", inspect.Parameter.POSITIONAL_OR_KEYWORD.value),
        ("handle", inspect.Parameter.POSITIONAL_OR_KEYWORD.value),
    ]
    assert hints == {"handle": handle_cls, "return": bool}


def test_container_backend_inspect_signature_is_pinned() -> None:
    """``inspect(handle) -> ContainerStatus`` — never a raw SDK dict."""
    # Arrange
    backend_cls = _get_container_backend()
    handle_cls = _get_data_type("ContainerHandle")
    status_cls = _get_data_type("ContainerStatus")
    # Act
    signature = inspect.signature(backend_cls.inspect)
    hints = get_type_hints(backend_cls.inspect)
    # Assert
    assert _sig(signature) == [
        ("self", inspect.Parameter.POSITIONAL_OR_KEYWORD.value),
        ("handle", inspect.Parameter.POSITIONAL_OR_KEYWORD.value),
    ]
    assert hints == {"handle": handle_cls, "return": status_cls}


def test_container_backend_list_managed_signature_is_pinned() -> None:
    """``list_managed() -> list[ContainerHandle]``."""
    # Arrange
    backend_cls = _get_container_backend()
    handle_cls = _get_data_type("ContainerHandle")
    # Act
    signature = inspect.signature(backend_cls.list_managed)
    hints = get_type_hints(backend_cls.list_managed)
    # Assert
    assert _sig(signature) == [
        ("self", inspect.Parameter.POSITIONAL_OR_KEYWORD.value),
    ]
    assert set(hints) == {"return"}
    return_hint = hints["return"]
    assert typing.get_origin(return_hint) is list
    assert typing.get_args(return_hint) == (handle_cls,)


def test_container_backend_logs_signature_is_pinned() -> None:
    """``logs(handle, *, follow: bool, tail: int) -> Iterator[str]``.

    The return is pinned as origin ``collections.abc.Iterator`` with
    args ``(str,)``: ``collections.abc.Iterator[str]`` and
    ``typing.Iterator[str]`` normalize to the same pair (both import
    forms of the same annotation), while ``AsyncIterator[str]``,
    ``list[str]`` or a bare ``str`` all fail it.
    """
    # Arrange
    backend_cls = _get_container_backend()
    handle_cls = _get_data_type("ContainerHandle")
    # Act
    signature = inspect.signature(backend_cls.logs)
    hints = get_type_hints(backend_cls.logs)
    # Assert
    assert _sig(signature) == [
        ("self", inspect.Parameter.POSITIONAL_OR_KEYWORD.value),
        ("handle", inspect.Parameter.POSITIONAL_OR_KEYWORD.value),
        ("follow", inspect.Parameter.KEYWORD_ONLY.value),
        ("tail", inspect.Parameter.KEYWORD_ONLY.value),
    ]
    assert set(hints) == {"handle", "follow", "tail", "return"}
    assert hints["handle"] is handle_cls
    assert hints["follow"] is bool
    assert hints["tail"] is int
    return_hint = hints["return"]
    assert typing.get_origin(return_hint) is collections.abc.Iterator
    assert typing.get_args(return_hint) == (str,)


@pytest.mark.parametrize(
    "method_name", ["start", "stop", "is_running", "inspect", "list_managed", "logs"]
)
def test_container_backend_method_is_synchronous(method_name: str) -> None:
    """No protocol method is a coroutine function.

    The seam is synchronous by design (plan §4.1): the docker SDK is
    blocking, and M2b's ``LifecycleManager`` is the async layer that
    off-loads these calls.  Making the seam async would hide that fact
    inside the driver.
    """
    # Arrange
    backend_cls = _get_container_backend()
    # Act
    method = getattr(backend_cls, method_name)
    # Assert
    assert inspect.iscoroutinefunction(method) is False


def test_container_backend_runtime_check_matches_on_member_names() -> None:
    """runtime_checkable isinstance matches a conforming stub, rejects a partial one.

    Secondary to the signature pins: a runtime-checkable
    ``isinstance`` checks member *names* only, so a conforming local
    stub passing it proves nothing about the declared signatures.  It
    pins the positive direction of the decorator (the negative
    direction — ``object()`` is not a backend — is asserted in
    ``test_container_backend_is_runtime_checkable_protocol``), and it
    cross-checks the member set from the ``isinstance`` side: a
    protocol declaring a seventh member would reject this stub.
    """
    # Arrange
    backend_cls = _get_container_backend()
    # Act
    conformant = isinstance(_ConformantStub(), backend_cls)
    missing_inspect = isinstance(_StubMissingInspect(), backend_cls)
    # Assert
    assert conformant is True
    assert missing_inspect is False

"""RED step for M2a behaviour 13 — ``FakeBackend.logs`` and the call journal.

See ``plans/m2a-container-backend-seam.md`` §4.4, §6 (item 2 especially)
and behaviour 13 (§5).  This is the last behaviour of the
``feature/m2a-fake-backend`` branch.

``logs``

- Pre-seeded log lines, then ``logs(handle, follow=False, tail=N)``
  returns an iterator of ``str``; ``tail`` returns the last N lines;
  ``follow=False`` terminates.
- Edge cases: ``tail`` larger than the buffer returns everything;
  ``tail=0`` yields nothing (pure list semantics — no docker fact);
  logs of a stopped container are still readable.
- ``logs`` on a handle the backend does not manage raises
  ``ContainerNotFoundError`` — ``logs`` is not one of the three lenient
  read-side calls of the §4.3 not-found contract, so "every other
  method raises" applies.

The call journal

- ``fake.calls`` records **every** protocol call, in order, with its
  arguments.  An entry is a ``(name, args, kwargs)`` triple: ``name``
  is the protocol member's name, ``args`` the positional arguments as
  passed and ``kwargs`` the keyword arguments as passed.  Keyword-only
  parameters (``timeout_s``, ``follow``, ``tail``) appear in ``kwargs``,
  so the entry is the call itself, not a summary.
- A call that **raises** is still a protocol call and is still
  recorded: the journal captures the *attempt*, which is exactly what
  plan §6 item 2 needs — M2b asserts "ten concurrent ``ensure_ready``
  produce exactly one start" by counting ``"start"`` entries, and a
  racing thread whose start was refused (name already taken) is
  invisible in ``list_managed`` but visible in the journal.  Counting
  successes in ``list_managed`` would show one container whether
  coalescing worked or a loser silently hit a name conflict; counting
  journal entries shows the attempts.
- Test-control methods are **not** protocol members, so neither
  ``vanish`` (behaviour 12) nor ``seed_logs`` (below) is ever
  recorded — the plan says "every protocol call", and the test-control
  section is deliberately not seam surface.

Pre-seeding API — the one thing the plan does not name

The plan says "pre-seeded log lines" but names no mechanism.  The
contract this file pins, for the GREEN step to implement:

    seed_logs(handle: ContainerHandle, lines: Sequence[str]) -> None

- Test control, not a ``ContainerBackend`` member — it sits below the
  same separator comment as ``vanish`` and is only ever called by
  tests (or by the test doubles M2b builds on top of the fake).
- Appends ``lines`` to the container's in-memory log buffer in the
  given order; the buffer is per-handle and survives ``stop`` (a
  stopped container's logs are still readable).
- Raises ``ContainerNotFoundError`` for a handle the backend does not
  manage: like ``vanish``, it is an active operation naming a
  container that may not exist, so it raises rather than silently
  buffering lines no container will ever have.

Concurrency

M2b will drive the fake concurrently (plan §6 item 2: "thread-safe
internals"), and this behaviour's journal is where that driving lands.
One test here drives the backend from eight threads behind a barrier
and asserts the journal is *complete* — every issued call recorded
exactly once, counts and per-tool identities matching.  It asserts
counts and multisets only, **never the interleaving order**: the order
of concurrent calls is inherently non-deterministic, and pinning it
would make the test flaky by construction.  A journal that drops or
corrupts entries under concurrency fails the count assertions
deterministically; a correct one passes every time.

This file is the RED step.  Behaviour 12 left ``logs`` raising
``NotImplementedError`` and shipped no journal of any kind, so the
failures split three ways, each unambiguous:

- the unknown-handle ``logs`` test fails because ``logs`` raises
  ``NotImplementedError`` where ``ContainerNotFoundError`` is expected;
- the seeded-``logs`` tests fail at the :func:`_get_seed_logs` gate, an
  ``AssertionError`` naming the missing test-control method;
- the journal tests fail at the :func:`_get_calls` gate, an
  ``AssertionError`` naming the missing ``calls`` attribute.

The deferred-import gate helpers follow the committed pattern in
``test_fake_backend_happy_path.py``,
``test_fake_backend_fail_to_start.py`` and
``test_fake_backend_death_and_vanishing.py``: if the module ever went
missing again, every test fails *individually* instead of aborting
pytest collection.  No ``importorskip`` and no skip of any kind — a
skipped test is not a red step.

No docker fact appears anywhere in this file: the fake's log buffer is
in-memory by construction, and ``plan/third-party-docs/docker/
container-logs.md`` documents ``DockerBackend.logs`` (behaviour 26) —
its streaming, chunking and byte-decoding semantics must not leak into
this one.  Had a docker fact seemed necessary here, that would signal
drift toward ``DockerBackend``.

Conventions: pytest, AAA pattern, no ``warnings.warn`` (pyproject sets
``filterwarnings = "error"``).
"""

from __future__ import annotations

import importlib
import threading
from collections.abc import Callable, Iterator, Sequence
from types import ModuleType
from typing import Any, cast

import pytest

from tool_swap.backend.errors import ContainerNotFoundError, ContainerStartError


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


def _get_calls(backend: Any) -> list[Any]:
    """Fetch ``backend.calls`` RED-safely.

    The journal is behaviour 13's own deliverable and does not exist
    yet: grabbing it directly would raise a raw ``AttributeError``.
    The gate converts that into an ``AssertionError`` naming the
    missing attribute, so every journal test fails at the gate with a
    message that tells the GREEN step exactly what to add.

    Args:
        backend: A constructed ``FakeBackend`` instance.

    Returns:
        The journal, as a list of ``(name, args, kwargs)`` triples.

    Raises:
        AssertionError: the backend has no ``calls`` attribute — the
            GREEN step must add the call journal to
            ``src/tool_swap/backend/fake_backend.py``.
    """
    try:
        calls = backend.calls
    except AttributeError as exc:
        raise AssertionError(
            "FakeBackend.calls is missing — the GREEN step must add "
            "the call journal `calls` to "
            "src/tool_swap/backend/fake_backend.py (behaviour 13)"
        ) from exc
    return cast("list[Any]", calls)


def _get_seed_logs(backend: Any) -> Callable[[Any, Sequence[str]], None]:
    """Fetch ``backend.seed_logs`` RED-safely.

    ``seed_logs`` is behaviour 13's test-control pre-seeding API (see
    the module docstring for the contract) and does not exist yet.
    Like :func:`_get_vanish` in
    ``test_fake_backend_death_and_vanishing.py``, the gate converts the
    raw ``AttributeError`` into an ``AssertionError`` naming the
    missing method.

    Args:
        backend: A constructed ``FakeBackend`` instance.

    Returns:
        The bound ``seed_logs`` method.

    Raises:
        AssertionError: the backend has no ``seed_logs`` method — the
            GREEN step must add ``seed_logs(handle, lines)`` to
            ``src/tool_swap/backend/fake_backend.py``.
    """
    try:
        seed = backend.seed_logs
    except AttributeError as exc:
        raise AssertionError(
            "FakeBackend.seed_logs is missing — the GREEN step must "
            "add the test-control method seed_logs(handle, lines) to "
            "src/tool_swap/backend/fake_backend.py (behaviour 13)"
        ) from exc
    return cast("Callable[[Any, Sequence[str]], None]", seed)


def _get_vanish(backend: Any) -> Callable[[Any], None]:
    """Fetch ``backend.vanish``; behaviour 12 already shipped it.

    Kept as a gate for symmetry with the other files: the failure
    message would name the method if it were ever removed.

    Args:
        backend: A constructed ``FakeBackend`` instance.

    Returns:
        The bound ``vanish`` method.

    Raises:
        AssertionError: the backend has no ``vanish`` method —
            behaviour 12 already shipped it.
    """
    try:
        vanish = backend.vanish
    except AttributeError as exc:
        raise AssertionError(
            "FakeBackend.vanish is missing — behaviour 12 already "
            "shipped it in src/tool_swap/backend/fake_backend.py"
        ) from exc
    return cast("Callable[[Any], None]", vanish)


def _spec(base: ModuleType, *, tool: str, name: str) -> Any:
    """A minimal ``ContainerSpec`` for the named tool.

    The name mirrors the tool to keep the two identities distinct in
    any failure message; values are neutral and deliberately distinct
    from ``BUILT_IN_DEFAULTS``.
    """
    return base.ContainerSpec(
        tool=tool,
        name=name,
        image="example/tool:1.0",
        gpu_runtime="cuda",
        container_port=8080,
    )


def _unknown_handle(base: ModuleType) -> Any:
    """A handle no container in the backend could correspond to."""
    return base.ContainerHandle(
        id="ghost-id",
        name="ms-ghost",
        tool="ghost",
        image="example/tool:1.0",
    )


# ---------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------


def test_fake_backend_logs_returns_preseeded_lines_in_order() -> None:
    """``logs`` returns an iterator of ``str`` yielding the seeded
    lines in the order they were seeded.

    ``tail`` exactly equal to the buffer size is the boundary between
    "the last N lines" and "everything": with four lines and
    ``tail=4`` the whole buffer comes back, ordered as seeded.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    handle = backend.start(_spec(base, tool="t1", name="ms-t1"))
    seed_logs = _get_seed_logs(backend)
    seed_logs(handle, ["line one", "line two", "line three", "line four"])
    # Act
    result = backend.logs(handle, follow=False, tail=4)
    lines = list(result)  # follow=False: this terminates
    # Assert
    assert isinstance(result, Iterator)
    assert lines == ["line one", "line two", "line three", "line four"]
    assert all(isinstance(line, str) for line in lines)


def test_fake_backend_logs_tail_returns_last_n_lines() -> None:
    """``tail=N`` returns the last N lines, not the first N."""
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    handle = backend.start(_spec(base, tool="t1", name="ms-t1"))
    seed_logs = _get_seed_logs(backend)
    seed_logs(handle, ["l1", "l2", "l3", "l4", "l5"])
    # Act
    lines = list(backend.logs(handle, follow=False, tail=2))
    # Assert
    assert lines == ["l4", "l5"]


def test_fake_backend_logs_tail_larger_than_buffer_returns_everything() -> None:
    """A ``tail`` larger than the buffer returns everything, not an
    error and not padding."""
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    handle = backend.start(_spec(base, tool="t1", name="ms-t1"))
    seed_logs = _get_seed_logs(backend)
    seed_logs(handle, ["only one", "only two"])
    # Act
    lines = list(backend.logs(handle, follow=False, tail=10))
    # Assert
    assert lines == ["only one", "only two"]


def test_fake_backend_logs_tail_zero_yields_nothing() -> None:
    """``tail=0`` yields nothing: the last zero lines of any buffer is
    an empty sequence.

    Pure list semantics on an in-memory buffer — no streaming or
    chunking concept is involved, and none may be imported from
    behaviour 26's docker reference.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    handle = backend.start(_spec(base, tool="t1", name="ms-t1"))
    seed_logs = _get_seed_logs(backend)
    seed_logs(handle, ["a", "b", "c"])
    # Act
    lines = list(backend.logs(handle, follow=False, tail=0))
    # Assert
    assert lines == []


def test_fake_backend_logs_of_stopped_container_are_still_readable() -> None:
    """Stopping the container does not discard its log buffer.

    "Logs survive a stop" is M7's requirement for the real runtime;
    here the edge case only pins that ``stop`` neither clears the
    buffer nor makes ``logs`` raise — the seam's contract is that a
    stopped container is still a container.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    handle = backend.start(_spec(base, tool="t1", name="ms-t1"))
    seed_logs = _get_seed_logs(backend)
    seed_logs(handle, ["before stop", "still here"])
    backend.stop(handle, timeout_s=5.0)
    # Act
    lines = list(backend.logs(handle, follow=False, tail=10))
    # Assert
    assert lines == ["before stop", "still here"]


def test_fake_backend_logs_unknown_handle_raises_container_not_found_error() -> None:
    """``logs`` on a handle the backend does not manage raises
    ``ContainerNotFoundError`` — the taxonomy member, never a bare
    ``Exception``.

    ``logs`` is not among the three lenient read-side calls of the
    §4.3 not-found contract (``is_running``, ``inspect``, ``stop``),
    so "every other method raises" applies.  RED: ``logs`` currently
    raises ``NotImplementedError`` before any handle check, so this
    test fails on the wrong exception — direct evidence the behaviour
    is absent.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    unknown = _unknown_handle(base)
    # Act / Assert
    with pytest.raises(ContainerNotFoundError):
        backend.logs(unknown, follow=False, tail=5)


def test_fake_backend_seed_logs_unknown_handle_raises_not_found() -> None:
    """``seed_logs`` on a handle the backend does not manage raises
    ``ContainerNotFoundError``.

    Like ``vanish``, ``seed_logs`` is an active operation naming a
    container that may not exist: it raises rather than silently
    building a buffer no container will ever have.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    seed_logs = _get_seed_logs(backend)
    unknown = _unknown_handle(base)
    # Act / Assert
    with pytest.raises(ContainerNotFoundError):
        seed_logs(unknown, ["orphan line"])


# ---------------------------------------------------------------------
# the call journal
# ---------------------------------------------------------------------


def test_fake_backend_calls_is_empty_before_any_protocol_call() -> None:
    """A fresh backend's journal is an empty list.

    "Exactly one start" is asserted by counting, and the count is only
    meaningful on a journal that starts empty — a pre-populated or
    shared journal would make every such count wrong.
    """
    # Arrange
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    # Act
    calls = _get_calls(backend)
    # Assert
    assert isinstance(calls, list)
    assert calls == []


def test_fake_backend_calls_records_every_call_in_order_with_args() -> None:
    """``fake.calls`` records every protocol call, in order, with its
    arguments — one ``(name, args, kwargs)`` triple per call.

    This is the exact pin M2b's "exactly one start" assertion builds
    on: the entries carry enough to filter by method name *and* to
    see what was passed, so a test can count starts without inferring
    from side effects.  Keyword-only parameters appear in ``kwargs``
    exactly as passed.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    spec = _spec(base, tool="t1", name="ms-t1")
    # Act — every protocol member, in a fixed order
    handle = backend.start(spec)
    backend.is_running(handle)
    backend.inspect(handle)
    backend.list_managed()
    backend.stop(handle, timeout_s=5.0)
    list(backend.logs(handle, follow=False, tail=3))
    # Assert
    calls = _get_calls(backend)
    assert calls == [
        ("start", (spec,), {}),
        ("is_running", (handle,), {}),
        ("inspect", (handle,), {}),
        ("list_managed", (), {}),
        ("stop", (handle,), {"timeout_s": 5.0}),
        ("logs", (handle,), {"follow": False, "tail": 3}),
    ]


def test_fake_backend_calls_records_a_refused_start_attempt() -> None:
    """A ``start`` that raises is still a protocol call and is still
    recorded.

    The journal captures the *attempt*, and that is what M2b needs: a
    racing thread whose start is refused (the name is taken by the
    thread that won the race) leaves no trace in ``list_managed`` —
    one container either way — but leaves a ``"start"`` entry here.
    Counting journal entries is therefore the only way to tell
    "coalescing worked, one attempt" from "coalescing failed, two
    attempts, one silent conflict".
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    fail_to_start = _get_failure_mode()
    backend = fake_cls(script={"t1": fail_to_start.FAIL_TO_START})
    spec = _spec(base, tool="t1", name="ms-t1")
    # Act
    with pytest.raises(ContainerStartError):
        backend.start(spec)
    # Assert
    calls = _get_calls(backend)
    assert calls == [("start", (spec,), {})]


def test_fake_backend_calls_records_a_logs_call_that_raises_not_found() -> None:
    """A ``logs`` call that raises ``ContainerNotFoundError`` is still
    recorded — "every protocol call" is unqualified by outcome.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    unknown = _unknown_handle(base)
    # Act
    with pytest.raises(ContainerNotFoundError):
        backend.logs(unknown, follow=False, tail=5)
    # Assert
    calls = _get_calls(backend)
    assert calls == [("logs", (unknown,), {"follow": False, "tail": 5})]


def test_fake_backend_test_control_calls_are_not_journalled() -> None:
    """``seed_logs`` and ``vanish`` are test control, not protocol
    members, so neither is ever recorded.

    The plan says "every *protocol* call"; the test-control section of
    the fake is deliberately not seam surface.  If either leaked into
    the journal, M2b's counts would depend on which test scaffolding
    a test happened to use.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    spec = _spec(base, tool="t1", name="ms-t1")
    handle = backend.start(spec)
    seed_logs = _get_seed_logs(backend)
    vanish = _get_vanish(backend)
    # Act
    seed_logs(handle, ["a line"])
    vanish(handle)
    # Assert
    calls = _get_calls(backend)
    assert calls == [("start", (spec,), {})]


def test_fake_backend_calls_journal_is_complete_under_concurrent_drivers() -> None:
    """Eight concurrent drivers produce a complete journal: every
    issued call recorded exactly once.

    M2b's coalescing test drives the fake concurrently (plan §6 item
    2: "thread-safe internals"), and the journal is where that driving
    lands.  The test asserts **completeness only** — total count,
    per-thread start identity and the number of ``is_running`` calls.
    It never asserts the interleaving order, because the order of
    concurrent calls is non-deterministic by definition; pinning it
    would make this test flaky rather than evidence.  A journal that
    drops or corrupts entries under concurrency fails the counts
    every time; a correct one passes every time.
    """
    # Arrange
    base = _get_base_module()
    fake_cls = _get_fake_backend()
    backend = fake_cls()
    thread_count = 8
    reads_per_thread = 10
    barrier = threading.Barrier(thread_count)
    errors: list[Exception] = []

    def worker(index: int) -> None:
        try:
            barrier.wait()  # start together: force real concurrency
            spec = _spec(base, tool=f"t{index}", name=f"ms-t{index}")
            handle = backend.start(spec)
            for _ in range(reads_per_thread):
                backend.is_running(handle)
        except Exception as exc:  # a race must surface, not vanish
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(index,)) for index in range(thread_count)
    ]
    # Act
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # Assert
    assert not errors
    calls = _get_calls(backend)
    expected_total = thread_count * (1 + reads_per_thread)
    assert len(calls) == expected_total
    starts = [entry for entry in calls if entry[0] == "start"]
    assert len(starts) == thread_count
    started_tools = {entry[1][0].tool for entry in starts}
    assert started_tools == {f"t{index}" for index in range(thread_count)}
    reads = [entry for entry in calls if entry[0] == "is_running"]
    assert len(reads) == thread_count * reads_per_thread

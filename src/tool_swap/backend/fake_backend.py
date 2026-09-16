"""In-memory ``FakeBackend`` for the container backend seam (M2a).

The first real implementation of the :class:`ContainerBackend` protocol
(``plans/m2a-container-backend-seam.md`` §4.4): a test double driven
entirely by in-memory state, importable with the docker SDK absent and
free of any docker fact.  Behaviour 10 landed the happy path plus the
not-found contract of §4.3 — ``is_running`` returns ``False`` for a
missing container rather than raising, ``inspect`` returns
``ContainerState.GONE``, and ``stop`` on a missing container is a no-op
— because M2b's liveness sweep relies on exactly that.

Behaviour 11 added the first scripted failure: a tool scripted
``FAIL_TO_START`` refuses to start with ``ContainerStartError`` —
repeatedly, without creating any container.  Behaviour 12 honoured
``DIE_AFTER_START`` — the start succeeds and returns a handle, but the
record is created already ``EXITED`` with a non-zero exit code, so the
container is dead by the first observation with no daemon, clock or
thread — and added ``vanish()``, a test-control method (not a
``ContainerBackend`` member) that removes a container's record out of
band.  Behaviour 13, the last of the branch, completed the module:
``logs`` reads a per-handle buffer pre-seeded by the test-control
``seed_logs`` and applies pure list semantics to ``tail``, and the
``fake.calls`` journal records every protocol call on entry — including
calls that raise — so M2b can assert "exactly one start" by counting
attempts rather than inferring them from side effects.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from tool_swap.backend.base import (
    ContainerHandle,
    ContainerSpec,
    ContainerState,
    ContainerStatus,
)
from tool_swap.backend.errors import (
    ContainerNameConflictError,
    ContainerNotFoundError,
    ContainerStartError,
)


class FailureMode(StrEnum):
    """Scriptable failure modes, keyed by tool name (plan §4.4).

    Exactly two members in M2a: ``STOP_HANGS`` was dropped from the
    milestone (plan §7 assumption 5) and "never ready" is the M2b
    probe's concern, not the fake's.  Behaviour 11 honours
    ``FAIL_TO_START`` and behaviour 12 honours ``DIE_AFTER_START``.
    """

    FAIL_TO_START = "fail_to_start"
    DIE_AFTER_START = "die_after_start"


@dataclass
class _Container:
    """One managed container's mutable state, guarded by the backend lock.

    ``logs`` is the per-handle log buffer pre-seeded through
    :meth:`FakeBackend.seed_logs`; it survives ``stop`` and is removed
    with the record by :meth:`FakeBackend.vanish`.
    """

    state: ContainerState
    exit_code: int | None
    logs: list[str] = field(default_factory=list)


class FakeBackend:
    """In-memory ``ContainerBackend``; a test double, not a simulation.

    Structurally satisfies the :class:`ContainerBackend` protocol:
    synchronous, handle-keyed, and honouring the §4.3 not-found
    contract — a missing container reads as ``is_running`` ``False``,
    ``inspect`` ``GONE`` and ``stop`` a no-op, so M2b's liveness sweep
    never hits an unhandled traceback in the watchdog.

    State is a plain dict guarded by a single ``threading.Lock``:
    M2b's coalescing test drives the fake concurrently (plan §6 item
    2), so every method snapshots or mutates under the lock.  No
    thread is ever spawned and no I/O happens — the fake exists so a
    test can assert seam behaviour with no daemon.

    Every protocol call is recorded in ``self.calls`` — a plain
    ``list`` of ``(name, args, kwargs)`` triples in call order, on
    entry and including calls that raise — so a test can count
    attempts (plan §6 item 2) rather than infer them from side
    effects.  Test-control methods are deliberately not recorded.
    """

    def __init__(self, script: Mapping[str, FailureMode] | None = None) -> None:
        """Create an empty fake, optionally with a failure script.

        Args:
            script: Tool name to scripted failure, as declared by
                §4.4.  Behaviour 11 honours ``FAIL_TO_START`` through
                this argument: a scripted tool refuses to start,
                repeatedly, recording nothing.  Behaviour 12 honours
                ``DIE_AFTER_START``: the start succeeds, but the
                container is already dead by the first observation.
        """
        self._script = script
        self._lock = threading.Lock()
        self._containers: dict[ContainerHandle, _Container] = {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record(self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        """Journal one protocol call, under the lock, on entry.

        Recording happens before any work that may raise (plan §6 item
        2: a losing racer's refused start must still be counted), and
        inside a lock section that returns before the method re-enters
        ``self._lock`` — the lock is a single non-reentrant lock, so
        the journal must never be touched from an already-locked
        section.

        Args:
            name: The protocol member's name.
            args: Positional arguments, as passed.
            kwargs: Keyword arguments, as passed.
        """
        with self._lock:
            self.calls.append((name, args, kwargs))

    @staticmethod
    def _journalled(method: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap a protocol method so every call is journaled on entry.

        The wrapper records first — before the body runs, so a call
        that raises is still recorded — and passes through whatever
        the body returns, raises or yields unchanged.  Test-control
        methods are not wrapped, so they never reach the journal.

        Args:
            method: The unwrapped protocol method.

        Returns:
            A wrapper with the original signature, name and
            docstring.
        """

        def wrapper(self: FakeBackend, *args: Any, **kwargs: Any) -> Any:
            self._record(method.__name__, args, kwargs)
            return method(self, *args, **kwargs)

        wrapper.__name__ = method.__name__
        wrapper.__doc__ = method.__doc__
        return wrapper

    @_journalled
    def start(self, spec: ContainerSpec) -> ContainerHandle:
        """Record the container as running and return its handle.

        The handle echoes the spec's ``name``, ``tool`` and ``image``
        and carries a fresh, non-empty, unique id per start.  A name
        already taken — by a running *or* a stopped container, as with
        the real runtime until the container is removed — raises
        :class:`ContainerNameConflictError`; no record is created.

        A tool scripted ``FAIL_TO_START`` refuses before anything is
        recorded: no container is created and ``list_managed`` is
        unaffected, and the refusal repeats on every call — the
        script is not one-shot, so a retry loop can never silently
        succeed.  The attempt still appears in ``self.calls``.

        A tool scripted ``DIE_AFTER_START`` starts — this is a death,
        not a refusal — but its record is created already ``EXITED``
        with a non-zero exit code: the fake has no daemon, clock or
        thread, so there is no observable ``RUNNING`` window and the
        container is dead by the first observation (plan §6 item 4).
        Like a stopped one it stays in ``list_managed``; only
        :meth:`vanish` removes a record.

        Args:
            spec: The fully resolved container to start.

        Returns:
            The handle of the now-running container.

        Raises:
            ContainerStartError: ``spec.tool`` is scripted
                ``FAIL_TO_START``.
            ContainerNameConflictError: ``spec.name`` is already
                managed by this backend.
        """
        with self._lock:
            # The refusal precedes the name-conflict check and every
            # mutation, so a scripted tool records no partial state.
            scripted = None if self._script is None else self._script.get(spec.tool)
            if scripted is FailureMode.FAIL_TO_START:
                raise ContainerStartError(
                    f"tool {spec.tool!r} refused to start: "
                    f"scripted failure {scripted.value}"
                )
            for existing in self._containers:
                if existing.name == spec.name:
                    raise ContainerNameConflictError(
                        f"container name {spec.name} is already taken"
                    )
            handle = ContainerHandle(
                id=uuid.uuid4().hex,
                name=spec.name,
                tool=spec.tool,
                image=spec.image,
            )
            if scripted is FailureMode.DIE_AFTER_START:
                # The plan pins only "non-zero"; no saved document
                # names a code, so the simplest non-zero one stands.
                state, exit_code = ContainerState.EXITED, 1
            else:
                state, exit_code = ContainerState.RUNNING, None
            self._containers[handle] = _Container(
                state=state,
                exit_code=exit_code,
            )
            return handle

    @_journalled
    def stop(self, handle: ContainerHandle, *, timeout_s: float) -> None:
        """Move the container to ``EXITED`` with exit code ``0``.

        A no-op — not an error — when the container is already exited
        or has vanished, per the §4.3 not-found contract.  The fake
        honours no kill timing, so ``timeout_s`` is accepted for
        signature parity and otherwise unused.  Stopping never
        touches the log buffer.

        Args:
            handle: The container to stop.
            timeout_s: Seconds the real runtime would allow before
                killing; accepted, not acted on.
        """
        with self._lock:
            container = self._containers.get(handle)
            if container is None or container.state is ContainerState.EXITED:
                return
            container.state = ContainerState.EXITED
            container.exit_code = 0

    @_journalled
    def is_running(self, handle: ContainerHandle) -> bool:
        """Whether the container is running; ``False`` if it is gone.

        A stopped and a vanished container are indistinguishable from
        this call — both report ``False`` without raising, the
        behaviour M2b's liveness sweep depends on.

        Args:
            handle: The container to check.

        Returns:
            ``True`` only while the container's state is
            ``ContainerState.RUNNING``.
        """
        with self._lock:
            container = self._containers.get(handle)
            return container is not None and container.state is ContainerState.RUNNING

    @_journalled
    def inspect(self, handle: ContainerHandle) -> ContainerStatus:
        """Current status; ``ContainerState.GONE`` if the container is gone.

        A running container reports ``exit_code=None`` — it has exited
        neither successfully nor at all.  ``started_at`` stays
        ``None`` throughout: the fake has no runtime clock to report
        from, and inventing a timestamp would be a fake docker fact.

        Args:
            handle: The container to inspect.

        Returns:
            A point-in-time status for the handle, or a
            ``ContainerState.GONE`` status carrying the handle as
            given when it is unknown.
        """
        with self._lock:
            container = self._containers.get(handle)
            if container is None:
                return ContainerStatus(handle=handle, state=ContainerState.GONE)
            return ContainerStatus(
                handle=handle,
                state=container.state,
                exit_code=container.exit_code,
            )

    @_journalled
    def list_managed(self) -> list[ContainerHandle]:
        """Every managed container, stopped ones included.

        Stopped containers stay listed until removed out of band:
        reconciliation adopts by label, and a stopped container's
        handle still carries the tool (plan §6 item 5).

        Returns:
            The handles of every running and exited container.
        """
        with self._lock:
            return list(self._containers)

    @_journalled
    def logs(
        self, handle: ContainerHandle, *, follow: bool, tail: int
    ) -> Iterator[str]:
        """Trailing log lines of the container, as an iterator of ``str``.

        The buffer is the per-handle list pre-seeded by
        :meth:`seed_logs`; ``tail`` keeps its last ``tail`` lines —
        pure list semantics, so ``tail`` larger than the buffer
        returns everything and ``tail=0`` yields nothing.  A stopped
        container's buffer survives; a vanished or never-started
        handle is unknown and raises, since ``logs`` is not one of
        the three lenient read-side calls of the §4.3 not-found
        contract.

        The lines are snapshotted under the lock and iterated from
        the snapshot: a lazy generator would read the buffer after
        the call returned and could observe later mutations.  With
        ``follow=True`` the snapshot is likewise returned and then
        the iterator terminates — the fake has no daemon and no
        stream to follow, and blocking forever would hang a caller
        that never stops it.

        Args:
            handle: The container whose logs are requested.
            follow: Whether the real implementation would follow;
                accepted for signature parity — the fake returns a
                terminating snapshot either way.
            tail: How many trailing lines to return; ``0`` yields
                nothing and a value past the buffer returns all of
                it.

        Raises:
            ContainerNotFoundError: the backend does not manage the
                handle.
        """
        with self._lock:
            container = self._containers.get(handle)
            if container is None:
                raise ContainerNotFoundError(
                    f"container {handle.name!r} is not managed by this backend"
                )
            lines = list(container.logs[-tail:]) if tail else []
        return iter(lines)

    # Test control, not seam surface: the methods above are the
    # ``ContainerBackend`` contract; everything below exists only so a
    # test can drive states the fake cannot reach on its own.  Test
    # control is deliberately never journaled, so ``fake.calls``
    # counts protocol attempts and nothing else.

    def vanish(self, handle: ContainerHandle) -> None:
        """Test control: remove the container's record out of band.

        This method is **not** a ``ContainerBackend`` member — it is
        an affordance for tests, like the ``script`` argument, and
        must never be called by ``LifecycleManager`` or any other
        seam consumer.  It stands in for removal the backend cannot
        see (``docker rm -f`` behind its back), so afterwards the
        handle reads exactly like one that was never started:
        ``is_running`` ``False``, ``inspect`` ``GONE``, ``stop`` a
        no-op — the §4.3 not-found contract.  The log buffer goes
        with the record, so ``logs`` on a vanished handle then raises
        like any unknown handle.  Nothing but this method removes a
        record, which is why a dead or stopped container stays in
        ``list_managed`` while a vanished one disappears (plan §6
        item 5).

        Args:
            handle: The container whose record is removed.

        Raises:
            ContainerNotFoundError: the backend does not manage the
                handle — ``vanish`` is an active operation, so naming
                a container that is not there raises, unlike the
                lenient read side.
        """
        with self._lock:
            if handle not in self._containers:
                raise ContainerNotFoundError(
                    f"container {handle.name!r} is not managed by this backend"
                )
            del self._containers[handle]

    def seed_logs(self, handle: ContainerHandle, lines: Sequence[str]) -> None:
        """Test control: append ``lines`` to the container's log buffer.

        The pre-seeding API behaviour 13's ``logs`` tests build on
        (plan §5 behaviour 13: "pre-seeded log lines"): ``lines`` are
        appended in the given order to the per-handle buffer, which
        ``stop`` leaves intact and :meth:`vanish` removes with the
        record.  Like ``vanish`` this is an active operation naming a
        container that may not exist, so an unmanaged handle raises
        rather than buffering lines no container will ever have.  It
        is a test-control method, not a ``ContainerBackend`` member,
        and is never journaled.

        Args:
            handle: The container whose buffer receives the lines.
            lines: Log lines, appended in the given order.

        Raises:
            ContainerNotFoundError: the backend does not manage the
                handle.
        """
        with self._lock:
            container = self._containers.get(handle)
            if container is None:
                raise ContainerNotFoundError(
                    f"container {handle.name!r} is not managed by this backend"
                )
            container.logs.extend(lines)

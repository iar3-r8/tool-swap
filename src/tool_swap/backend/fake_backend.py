"""In-memory ``FakeBackend`` for the container backend seam (M2a behaviour 10).

The first real implementation of the :class:`ContainerBackend` protocol
(``plans/m2a-container-backend-seam.md`` §4.4): a test double driven
entirely by in-memory state, importable with the docker SDK absent and
free of any docker fact.  Behaviour 10 lands the happy path plus the
not-found contract of §4.3 — ``is_running`` returns ``False`` for a
missing container rather than raising, ``inspect`` returns
``ContainerState.GONE``, and ``stop`` on a missing container is a no-op
— because M2b's liveness sweep relies on exactly that.

Behaviour 11 adds the first scripted failure: a tool scripted
``FAIL_TO_START`` refuses to start with ``ContainerStartError`` —
repeatedly, and recording nothing.  The remaining behaviours extend
this same module, each with its own red step: death and ``vanish()``
(12), ``logs`` and the ``fake.calls`` journal (13);
``DIE_AFTER_START`` is stored but still un-honoured.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum

from tool_swap.backend.base import (
    ContainerHandle,
    ContainerSpec,
    ContainerState,
    ContainerStatus,
)
from tool_swap.backend.errors import (
    ContainerNameConflictError,
    ContainerStartError,
)


class FailureMode(StrEnum):
    """Scriptable failure modes, keyed by tool name (plan §4.4).

    Exactly two members in M2a: ``STOP_HANGS`` was dropped from the
    milestone (plan §7 assumption 5) and "never ready" is the M2b
    probe's concern, not the fake's.  Behaviour 11 honours
    ``FAIL_TO_START``; behaviour 10 stores scripts but acts on none of
    them.
    """

    FAIL_TO_START = "fail_to_start"
    DIE_AFTER_START = "die_after_start"


@dataclass
class _Container:
    """One managed container's mutable state, guarded by the backend lock."""

    state: ContainerState
    exit_code: int | None


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
    """

    def __init__(self, script: Mapping[str, FailureMode] | None = None) -> None:
        """Create an empty fake, optionally with a failure script.

        Args:
            script: Tool name to scripted failure, as declared by
                §4.4.  Behaviour 11 honours ``FAIL_TO_START`` through
                this argument: a scripted tool refuses to start,
                repeatedly, recording nothing.  ``DIE_AFTER_START`` is
                stored but un-honoured until behaviour 12.
        """
        self._script = script
        self._lock = threading.Lock()
        self._containers: dict[ContainerHandle, _Container] = {}

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
        succeed.

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
            self._containers[handle] = _Container(
                state=ContainerState.RUNNING,
                exit_code=None,
            )
            return handle

    def stop(self, handle: ContainerHandle, *, timeout_s: float) -> None:
        """Move the container to ``EXITED`` with exit code ``0``.

        A no-op — not an error — when the container is already exited
        or has vanished, per the §4.3 not-found contract.  The fake
        honours no kill timing, so ``timeout_s`` is accepted for
        signature parity and otherwise unused.

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

    def logs(
        self, handle: ContainerHandle, *, follow: bool, tail: int
    ) -> Iterator[str]:
        """Log lines of the container — unimplemented in behaviour 10.

        Present only so the class structurally satisfies the
        ``ContainerBackend`` protocol; the real body (pre-seeded lines,
        ``tail`` capping, ``ContainerNotFoundError`` on an unknown
        handle) lands with the ``fake.calls`` journal in behaviour 13.

        Args:
            handle: The container whose logs are requested.
            follow: Whether the real implementation would follow.
            tail: How many trailing lines the real implementation
                would keep.

        Raises:
            NotImplementedError: always — behaviour 13 is the green
                step for this method.
        """
        raise NotImplementedError("FakeBackend.logs is implemented in M2a behaviour 13")

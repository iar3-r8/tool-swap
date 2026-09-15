"""Base data types for the container backend seam (M2a).

This module holds already-resolved data types, and declares the
``ContainerBackend`` protocol — the seam interface every lifecycle
component is written against.  No backend implementation lives here.
Its boundary
(plans/m2a-container-backend-seam.md §4.2): it stores values and knows
nothing about strings.  A :class:`MountSpec` carries an
already-resolved ``source``, an already-checked ``target`` and a
normalised ``read_only`` bool; no module under ``tool_swap.backend``
splits a mount string, expands a path or resolves anything.  Mount
string parsing and every judgement about it belong exclusively to
``tool_swap.config.validate`` (``TSWAP-C541``/``C542``/``C543``), and
the single ``ParsedMount`` to ``MountSpec`` conversion is deliberately
deferred to the config to spec builder of a later milestone.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class MountSpec:
    """One already-resolved bind mount. Holds no parsing (§4.2).

    Stores the two paths verbatim: no parsing, no ``~`` expansion, no
    lexical resolution, no existence checks.  Those judgements are
    config layer rules (``TSWAP-C541`` mode legality, ``TSWAP-C542``
    container path absoluteness, ``TSWAP-C543`` host path existence);
    re-doing them here is the duplication plan §4.2 forbids.

    Attributes:
        source: Resolved host path, as a string.
        target: Absolute container path.
        read_only: Read-only by default (architecture §10), so a
            caller must ask for read-write explicitly.
    """

    source: str
    target: str
    read_only: bool = True


@dataclass(frozen=True, slots=True)
class ContainerSpec:
    """Everything needed to start one tool container. Backend-agnostic.

    Fully resolved input: it carries no policy (no TTL, no group, no
    eviction) and re-states no configured default — every configured
    value arrives from the resolver at call time.  In particular
    ``gpu_runtime`` and ``container_port`` carry **no default at all**:
    ``BUILT_IN_DEFAULTS`` is the single named source of truth for their
    configured values, and a second copy would drift without any test
    noticing.  Omitting either is a ``TypeError`` at construction, never
    a silent built-in default.

    Keyword-only on those two required fields is a mechanical necessity,
    not a style choice: a dataclass cannot place a non-default field
    after a defaulted one, so ``kw_only`` keeps the readable field list
    ordered without reordering it.

    Stores what it is given: no parsing, no validation, no
    normalisation — the same §4.2 boundary as :class:`MountSpec`.

    Attributes:
        tool: Logical tool name (label value).
        name: Final container name, prefix applied.
        image: Container image reference.
        gpu_runtime: Resolved GPU runtime name; required, no default.
        container_port: Resolved in-container port; required, no
            default.
        command: Command to run, or ``None`` for the image default.
        env: Environment variables, empty by default.
        labels: Container labels, empty by default.
        network: Container network name, or ``None``.
        mounts: Resolved bind mounts; ``()`` means none.
        devices: GPU indices; ``()`` is CPU-only.
        shm_size: Shared-memory size (e.g. ``"1g"``), or ``None``.
        cpus: CPU limit, or ``None``.
        memory: Memory limit (e.g. ``"16g"``), or ``None``.
        published_port: Host port to publish; ``None`` publishes
            nothing.
    """

    tool: str
    name: str
    image: str
    gpu_runtime: str = field(kw_only=True)  # resolved; NO literal default
    container_port: int = field(kw_only=True)  # resolved; NO literal default
    command: tuple[str, ...] | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    labels: Mapping[str, str] = field(default_factory=dict)
    network: str | None = None
    mounts: tuple[MountSpec, ...] = ()
    devices: tuple[int, ...] = ()  # GPU indices; () is CPU-only
    shm_size: str | None = None  # e.g. "1g", resolved from config
    cpus: float | None = None
    memory: str | None = None  # e.g. "16g"
    published_port: int | None = None  # None publishes nothing


@dataclass(frozen=True, slots=True)
class ContainerHandle:
    """One started container, as the backend knows it.

    Identified by all four fields together, never by ``id`` alone: a
    recreated container keeps its name and tool while its runtime id
    changes, so a handle is the seam's unit of identity for dict
    keying and equality alike.

    Attributes:
        id: Container runtime id (hex digest), as reported by the
            runtime.
        name: Final container name, prefix applied.
        tool: Logical tool name (label value).
        image: Container image reference.
    """

    id: str
    name: str
    tool: str
    image: str


class ContainerState(StrEnum):
    """Backend-level container state.

    Deliberately NOT the M2b tool state machine: ``STARTING``,
    ``LOADING`` and ``READY`` are readiness concepts owned by M2b's
    health probe, and the backend only knows whether a process exists.
    Adding a readiness member here would blur the two state machines;
    the four-member test in ``test_container_handle_state_status.py``
    pins the boundary on purpose, not by accident.
    """

    CREATED = "created"
    RUNNING = "running"
    EXITED = "exited"
    GONE = "gone"


@dataclass(frozen=True, slots=True)
class ContainerStatus:
    """One point-in-time reading of a started container.

    ``exit_code`` defaults to ``None`` rather than ``0``: a running
    container has exited neither successfully nor at all, and
    conflating ``None`` with ``0`` would report live containers as
    clean exits.  ``started_at`` is the runtime-reported start time as
    a plain string; no coercion to ``datetime`` at the seam.

    Attributes:
        handle: The container this reading describes.
        state: Backend-level state; the M2b tool state machine is a
            separate concern.
        exit_code: Process exit code, or ``None`` while running.
        started_at: Runtime start time as reported, or ``None``.
    """

    handle: ContainerHandle
    state: ContainerState
    exit_code: int | None = None
    started_at: str | None = None


@runtime_checkable
class ContainerBackend(Protocol):
    """The ONLY component that touches a container runtime.

    Declares the seam every lifecycle component is written against;
    no implementation lives here — ``FakeBackend`` and ``DockerBackend``
    are later milestones with their own modules.

    Deliberate decisions, each pinned by the behaviour-8 tests:

    - **Synchronous by design** (architecture §12): the docker SDK is
      blocking, and M2b's ``LifecycleManager`` is the async layer that
      off-loads these calls.  Making the seam async would hide that
      fact inside the driver.
    - **``build`` is absent** although architecture §12 lists it: it is
      M5's, and issue #3's Definition of Done names exactly the six
      methods below without it.  Adding it now would force both
      implementations to carry a stub.
    - **``inspect`` returns ``ContainerStatus``**, never a raw SDK
      dict — the seam exists to contain SDK vocabulary, not leak it.
    - **``stop`` and ``logs`` take keyword-only arguments**:
      ``stop(handle, timeout_s=30)`` reads unambiguously where a
      positional timeout invites confusion with a retry count.

    Not-found contract (plan §4.3), relied on by M2b's liveness sweep:
    ``is_running`` returns ``False`` for a missing container rather
    than raising, ``inspect`` returns ``ContainerState.GONE``, and
    ``stop`` on a missing container is a no-op.  Every other method
    raises the error-taxonomy member instead.
    """

    def start(self, spec: ContainerSpec) -> ContainerHandle:
        """Start the container described by ``spec`` and return its handle."""
        ...

    def stop(self, handle: ContainerHandle, *, timeout_s: float) -> None:
        """Stop the container within ``timeout_s``; a no-op if it is gone."""
        ...

    def is_running(self, handle: ContainerHandle) -> bool:
        """Whether the container is running; ``False`` if it is gone."""
        ...

    def inspect(self, handle: ContainerHandle) -> ContainerStatus:
        """Current status; ``ContainerState.GONE`` if the container is gone."""
        ...

    def list_managed(self) -> list[ContainerHandle]:
        """Every managed container, stopped ones included."""
        ...

    def logs(
        self, handle: ContainerHandle, *, follow: bool, tail: int
    ) -> Iterator[str]:
        """Log lines of the container; ``tail`` caps how many are kept."""
        ...

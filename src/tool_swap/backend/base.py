"""Base data types for the container backend seam (M2a).

This module holds already-resolved data types.  Its boundary
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

from collections.abc import Mapping
from dataclasses import dataclass, field


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

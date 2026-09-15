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

from dataclasses import dataclass


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

"""Origin tracking primitives for configuration resolution.

Records *which* layer a resolved value came from (the "why this value"
answer for ``config show``) and *which* layers it shadowed.  In the pipeline
it is populated by the ``resolver`` during layer merging and consumed when
rendering ``tswap config show``.
See ``plans/m1-configuration.md`` §1, behaviour 9.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final


class OriginLevel(Enum):
    """The configuration layer a value came from, most specific first.

    - ``INLINE``: an entry in the user's ``tools.yaml``.
    - ``TOOL_YAML``: a ``tool.yaml`` included via ``path:``.
    - ``DEFAULTS``: the user's ``defaults:`` block.
    - ``BUILT_IN``: tool-swap's built-in defaults.
    """

    INLINE = "inline"
    TOOL_YAML = "tool.yaml"
    DEFAULTS = "defaults"
    BUILT_IN = "built-in"


#: Rendered suffix per level (``BUILT_IN`` renders a fixed string instead).
_RENDER_SUFFIX: Final[dict[OriginLevel, str]] = {
    OriginLevel.INLINE: " (inline)",
    OriginLevel.TOOL_YAML: " (tool.yaml)",
    OriginLevel.DEFAULTS: " (defaults)",
}

#: The canonical source string for built-in defaults.
_BUILT_IN_SOURCE: Final[str] = "built-in default"


@dataclass(frozen=True)
class Origin:
    """The provenance of a resolved value.

    Attributes:
        level: which configuration layer the value came from.
        source: the concrete source, e.g. ``"tools.yaml:143"`` or
            ``"tools/t/tool.yaml:12"``.
    """

    level: OriginLevel
    source: str

    @classmethod
    def built_in(cls) -> Origin:
        """Return the canonical built-in origin."""
        return cls(level=OriginLevel.BUILT_IN, source=_BUILT_IN_SOURCE)

    def render(self) -> str:
        """Return the human-readable form used by ``config show``.

        ``INLINE`` renders ``"{source} (inline)"``, ``TOOL_YAML`` renders
        ``"{source} (tool.yaml)"``, ``DEFAULTS`` renders
        ``"{source} (defaults)"``, and ``BUILT_IN`` renders exactly
        ``"built-in default"`` regardless of ``source``.
        """
        if self.level is OriginLevel.BUILT_IN:
            return _BUILT_IN_SOURCE
        return f"{self.source}{_RENDER_SUFFIX[self.level]}"


@dataclass(frozen=True)
class ResolvedValue:
    """A resolved value paired with the :class:`Origin` that won.

    Attributes:
        value: the resolved value; ``None`` is a legal (explicit unset)
            winner.
        origin: the winning origin for ``value``.
    """

    value: object
    origin: Origin


@dataclass
class _Entry:
    """Internal per-field bookkeeping: the winner and the shadowed list."""

    winning: Origin
    shadowed: list[Origin]


class OriginMap:
    """Maps a dotted field path to its winning origin and its shadows.

    A pure value container: no filesystem, environment, or clock, and no
    parsing or normalisation — field paths and source strings are stored
    and read verbatim.  Path conventions (dotted for scalars and per-key
    map entries, e.g. ``env.HF_HOME``; index suffix for list entries,
    e.g. ``mounts[0]``) are documented for callers, not enforced here.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    def record(
        self,
        field_path: str,
        origin: Origin,
        *,
        overrides: Sequence[Origin] = (),
    ) -> None:
        """(Re)set the entry for ``field_path``.

        ``origin`` becomes the winning origin and ``overrides`` the
        shadowed list, in the order given (caller convention: most
        specific first).  A second call for the same path replaces the
        previous entry entirely, shadows included.

        Args:
            field_path: the opaque dotted field path, e.g. ``"ttl"``.
            origin: the winning origin.
            overrides: the shadowed origins, most specific first.
        """
        self._entries[field_path] = _Entry(winning=origin, shadowed=list(overrides))

    def winning(self, field_path: str) -> Origin:
        """Return the winning origin for ``field_path``.

        Raises:
            KeyError: if no origin was recorded for ``field_path``.
        """
        return self._entries[field_path].winning

    def shadowed(self, field_path: str) -> list[Origin]:
        """Return the shadowed origins for ``field_path`` in recorded order.

        Returns an empty list (never ``None``) when nothing was
        shadowed.
        """
        return list(self._entries[field_path].shadowed)

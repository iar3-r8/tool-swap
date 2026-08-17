"""Tests for M1 behaviour 9 — ``Origin`` tracking primitives.

See ``plans/m1-configuration.md`` §1, behaviour 9 (lines 168-177):

- ``Origin`` names the level (``INLINE`` | ``TOOL_YAML`` | ``DEFAULTS`` |
  ``BUILT_IN``) **and** the concrete source (``tools.yaml:143``,
  ``tools/t/tool.yaml:12``, ``built-in default``).
- ``Origin.render()`` -> ``tools.yaml:143 (inline)``, ``built-in default``.
- ``ResolvedValue[T]`` pairs a value with its ``Origin``; an ``OriginMap``
  maps a dotted field path to the winning ``Origin`` and additionally
  records the **shadowed** origins so ``config show --verbose`` can say
  *"``ttl: 600`` from tools.yaml:143 (inline), overriding 900 from
  built-in default"*.
- Merged/concatenated fields need **per-element** origins: ``env.HF_HOME``
  may come from ``defaults:`` while ``env.MY_VAR`` comes from inline, and
  each ``mounts`` entry carries the origin of the layer that contributed
  it (index-addressed paths such as ``mounts[0]``).
- Requesting the origin of an unknown field path raises ``KeyError`` —
  a programming error, not a user error.

This file is the RED step: the module under test,
``src/tool_swap/config/origin.py``, does not exist yet, so the file fails
collection with ``ModuleNotFoundError``.  That is the *right* red reason —
every test body below pins a concrete behaviour the GREEN step must
satisfy, so the assertions (not just the import) are the contract.

Pinned public API (the contract the GREEN step must meet verbatim):

- ``OriginLevel`` — an enum with EXACTLY four members:
  ``OriginLevel.INLINE``, ``OriginLevel.TOOL_YAML``,
  ``OriginLevel.DEFAULTS``, ``OriginLevel.BUILT_IN``.
- ``Origin`` — a frozen dataclass with fields
  ``level: OriginLevel`` and ``source: str`` (constructed with keyword
  arguments).
  - ``Origin.render() -> str``:
    - ``INLINE``    -> ``"{source} (inline)"``
    - ``TOOL_YAML`` -> ``"{source} (tool.yaml)"``
    - ``DEFAULTS``  -> ``"{source} (defaults)"``
    - ``BUILT_IN``  -> exactly ``"built-in default"``, regardless of
      ``source``.
  - ``Origin.built_in()`` — classmethod returning the canonical built-in
    origin: ``Origin(level=OriginLevel.BUILT_IN,
    source="built-in default")``.
- ``ResolvedValue`` — a frozen dataclass with fields ``value: object``
  and ``origin: Origin`` (constructed with keyword arguments).
- ``OriginMap`` — a **pure** value container: no filesystem, no
  environment, no clock; it never parses or normalises field paths or
  sources.
  - ``OriginMap()`` — constructible with no arguments.
  - ``record(field_path: str, origin: Origin,
    *, overrides: Sequence[Origin] = ()) -> None`` — (re)sets the entry
    for ``field_path``: ``origin`` becomes the winning origin and
    ``list(overrides)`` becomes the shadowed list, in the order given.
    A second ``record`` call for the same path REPLACES the previous
    entry entirely (winning and shadows).
  - ``winning(field_path: str) -> Origin`` — the winning origin; raises
    ``KeyError`` (message text NOT pinned) for an unknown path.
  - ``shadowed(field_path: str) -> list[Origin]`` — the shadowed origins
    in recorded order, or ``[]`` (not ``None``) when nothing was
    shadowed.  Caller convention: shadows are recorded **most specific
    first**, e.g. when inline overrides defaults, which overrides
    built-in, the caller records
    ``[defaults-origin, built-in-origin]`` and reads back exactly that
    order.

Field-path conventions: a plain dotted path for scalars and per-key map
entries (``ttl``, ``env.HF_HOME``) and an index suffix for list entries
(``mounts[0]``).  Paths are opaque strings to the map.

Conventions: pytest, AAA pattern, no ``warnings.warn`` (pyproject sets
``filterwarnings = "error"``).
"""

from __future__ import annotations

import pytest
from tool_swap.config.origin import Origin, OriginLevel, OriginMap, ResolvedValue


# ---------------------------------------------------------------------------
# OriginLevel
# ---------------------------------------------------------------------------


def test_origin_level_pins_exactly_four_members() -> None:
    """``OriginLevel`` has exactly the four plan-pinned members."""
    # Act
    names = {member.name for member in OriginLevel}
    # Assert
    assert names == {"INLINE", "TOOL_YAML", "DEFAULTS", "BUILT_IN"}


# ---------------------------------------------------------------------------
# Origin
# ---------------------------------------------------------------------------


def test_origin_stores_level_and_source() -> None:
    """``Origin`` stores both the level and the concrete source."""
    # Arrange
    level = OriginLevel.TOOL_YAML
    source = "tools/t/tool.yaml:12"
    # Act
    origin = Origin(level=level, source=source)
    # Assert
    assert origin.level is level
    assert origin.source == source


def test_origin_render_inline_pins_form() -> None:
    """``render()`` for ``INLINE`` is ``"{source} (inline)"``."""
    # Act
    rendered = Origin(level=OriginLevel.INLINE, source="tools.yaml:143").render()
    # Assert
    assert rendered == "tools.yaml:143 (inline)"


def test_origin_render_tool_yaml_pins_form() -> None:
    """``render()`` for ``TOOL_YAML`` is ``"{source} (tool.yaml)"``."""
    # Act
    rendered = Origin(level=OriginLevel.TOOL_YAML, source="tools/t/tool.yaml:12").render()
    # Assert
    assert rendered == "tools/t/tool.yaml:12 (tool.yaml)"


def test_origin_render_defaults_pins_form() -> None:
    """``render()`` for ``DEFAULTS`` is ``"{source} (defaults)"``."""
    # Act
    rendered = Origin(level=OriginLevel.DEFAULTS, source="defaults:").render()
    # Assert
    assert rendered == "defaults: (defaults)"


def test_origin_render_built_in_is_constant_regardless_of_source() -> None:
    """``render()`` for ``BUILT_IN`` is exactly ``"built-in default"``."""
    # Arrange — the source is deliberately arbitrary: the pinned form
    # must not depend on it.
    origin = Origin(level=OriginLevel.BUILT_IN, source="arbitrary source")
    # Act
    rendered = origin.render()
    # Assert
    assert rendered == "built-in default"


def test_origin_built_in_classmethod_returns_canonical_origin() -> None:
    """``Origin.built_in()`` returns the canonical built-in origin."""
    # Act
    origin = Origin.built_in()
    # Assert
    assert origin.level is OriginLevel.BUILT_IN
    assert origin.source == "built-in default"
    assert origin.render() == "built-in default"


def test_origin_render_is_pure_and_deterministic() -> None:
    """``render()`` has no side effects: repeated calls give the same string."""
    # Arrange
    origin = Origin(level=OriginLevel.TOOL_YAML, source="tools/t/tool.yaml:12")
    # Act
    first = origin.render()
    second = origin.render()
    # Assert
    assert first == second == "tools/t/tool.yaml:12 (tool.yaml)"


def test_origin_is_frozen() -> None:
    """``Origin`` is immutable: mutating either field raises ``AttributeError``."""
    # Arrange
    origin = Origin(level=OriginLevel.INLINE, source="tools.yaml:1")
    # Act / Assert
    with pytest.raises(AttributeError):
        origin.source = "other"
    with pytest.raises(AttributeError):
        origin.level = OriginLevel.DEFAULTS


# ---------------------------------------------------------------------------
# ResolvedValue
# ---------------------------------------------------------------------------


def test_resolved_value_pairs_value_with_origin() -> None:
    """``ResolvedValue`` pairs a value with its ``Origin``, both readable."""
    # Arrange
    origin = Origin(level=OriginLevel.INLINE, source="tools.yaml:143")
    # Act
    resolved = ResolvedValue(value=600, origin=origin)
    # Assert
    assert resolved.value == 600
    assert resolved.origin is origin


def test_resolved_value_accepts_none_value() -> None:
    """``ResolvedValue`` may carry ``None`` (an explicit unset winner)."""
    # Arrange
    origin = Origin(level=OriginLevel.INLINE, source="tools.yaml:40")
    # Act
    resolved = ResolvedValue(value=None, origin=origin)
    # Assert
    assert resolved.value is None
    assert resolved.origin is origin


def test_resolved_value_is_frozen() -> None:
    """``ResolvedValue`` is immutable: mutating either field raises ``AttributeError``."""
    # Arrange
    origin = Origin(level=OriginLevel.DEFAULTS, source="defaults:")
    resolved = ResolvedValue(value=1, origin=origin)
    # Act / Assert
    with pytest.raises(AttributeError):
        resolved.value = 2
    with pytest.raises(AttributeError):
        resolved.origin = Origin(level=OriginLevel.INLINE, source="tools.yaml:2")


# ---------------------------------------------------------------------------
# OriginMap — winning origins
# ---------------------------------------------------------------------------


def test_origin_map_winning_returns_recorded_origin() -> None:
    """``winning()`` returns the origin recorded for a field path."""
    # Arrange
    origin_map = OriginMap()
    origin = Origin(level=OriginLevel.INLINE, source="tools.yaml:143")
    # Act
    origin_map.record("ttl", origin)
    # Assert
    assert origin_map.winning("ttl") == origin
    assert origin_map.winning("ttl").level is OriginLevel.INLINE
    assert origin_map.winning("ttl").source == "tools.yaml:143"


def test_origin_map_winning_unknown_path_raises_keyerror() -> None:
    """``winning()`` for an unknown path raises ``KeyError`` (message not pinned)."""
    # Arrange
    origin_map = OriginMap()
    # Act / Assert
    with pytest.raises(KeyError):
        origin_map.winning("no.such.field")


def test_origin_map_record_replaces_previous_entry_for_path() -> None:
    """A second ``record`` for the same path replaces winning AND shadows."""
    # Arrange
    origin_map = OriginMap()
    first = Origin(level=OriginLevel.DEFAULTS, source="defaults:")
    second = Origin(level=OriginLevel.INLINE, source="tools.yaml:7")
    # Act
    origin_map.record("ttl", first, overrides=[Origin.built_in()])
    origin_map.record("ttl", second)
    # Assert
    assert origin_map.winning("ttl") == second
    assert origin_map.shadowed("ttl") == []


# ---------------------------------------------------------------------------
# OriginMap — shadowed origins
# ---------------------------------------------------------------------------


def test_origin_map_records_and_returns_single_shadow() -> None:
    """Inline winning over built-in records one shadowed built-in origin."""
    # Arrange
    origin_map = OriginMap()
    winning_origin = Origin(level=OriginLevel.INLINE, source="tools.yaml:143")
    shadowed_origin = Origin.built_in()
    # Act
    origin_map.record("ttl", winning_origin, overrides=[shadowed_origin])
    # Assert — the plan's "600 from tools.yaml:143 (inline), overriding
    # 900 from built-in default" case.
    assert origin_map.winning("ttl") == winning_origin
    assert origin_map.shadowed("ttl") == [shadowed_origin]
    assert origin_map.shadowed("ttl")[0].render() == "built-in default"


def test_origin_map_shadowed_is_most_specific_first() -> None:
    """Shadowed origins come back in recorded order: most specific first.

    Convention pinned here: when inline overrides defaults, which
    overrides built-in, the caller records the shadows
    ``[defaults-origin, built-in-origin]`` and reads back exactly that
    order.
    """
    # Arrange
    origin_map = OriginMap()
    inline_origin = Origin(level=OriginLevel.INLINE, source="tools.yaml:143")
    defaults_origin = Origin(level=OriginLevel.DEFAULTS, source="defaults:")
    built_in_origin = Origin.built_in()
    # Act
    origin_map.record(
        "ttl",
        inline_origin,
        overrides=[defaults_origin, built_in_origin],
    )
    # Assert
    assert origin_map.shadowed("ttl") == [defaults_origin, built_in_origin]


def test_origin_map_shadowed_returns_empty_list_not_none() -> None:
    """``shadowed()`` with no shadows returns ``[]``, not ``None``."""
    # Arrange
    origin_map = OriginMap()
    origin = Origin(level=OriginLevel.DEFAULTS, source="defaults:")
    # Act
    origin_map.record("ttl", origin)
    shadows = origin_map.shadowed("ttl")
    # Assert
    assert shadows is not None
    assert shadows == []


# ---------------------------------------------------------------------------
# OriginMap — per-element origins (merged/concatenated fields)
# ---------------------------------------------------------------------------


def test_origin_map_per_key_env_origins_are_independent() -> None:
    """``env.HF_HOME`` and ``env.MY_VAR`` carry different origins independently."""
    # Arrange
    origin_map = OriginMap()
    hf_home_origin = Origin(level=OriginLevel.DEFAULTS, source="defaults:")
    my_var_origin = Origin(level=OriginLevel.INLINE, source="tools.yaml:88")
    # Act
    origin_map.record("env.HF_HOME", hf_home_origin)
    origin_map.record("env.MY_VAR", my_var_origin)
    # Assert
    assert origin_map.winning("env.HF_HOME") == hf_home_origin
    assert origin_map.winning("env.MY_VAR") == my_var_origin
    assert origin_map.shadowed("env.HF_HOME") == []
    assert origin_map.shadowed("env.MY_VAR") == []


def test_origin_map_per_index_mount_origins_are_independent() -> None:
    """``mounts[0]`` and ``mounts[1]`` carry the contributing layer's origin."""
    # Arrange — built-in concatenates first (index 0), inline last (index 1).
    origin_map = OriginMap()
    first_origin = Origin.built_in()
    second_origin = Origin(level=OriginLevel.INLINE, source="tools.yaml:91")
    # Act
    origin_map.record("mounts[0]", first_origin)
    origin_map.record("mounts[1]", second_origin)
    # Assert
    assert origin_map.winning("mounts[0]") == first_origin
    assert origin_map.winning("mounts[1]") == second_origin


# ---------------------------------------------------------------------------
# OriginMap — pure value container
# ---------------------------------------------------------------------------


def test_origin_map_stores_sources_and_paths_verbatim_without_normalization() -> None:
    """The map stores arbitrary source strings and paths as-is (no I/O, no parsing)."""
    # Arrange — deliberately un-normalizable: spaces, a trailing colon,
    # odd characters.  The map must not touch the filesystem, the
    # environment, or a clock to store it.
    source = "weird  source/with spaces & symbols:42"
    path = "some.field[3].sub"
    origin = Origin(level=OriginLevel.TOOL_YAML, source=source)
    origin_map = OriginMap()
    # Act
    origin_map.record(path, origin)
    stored = origin_map.winning(path)
    # Assert
    assert stored.source == source
    assert stored.level is OriginLevel.TOOL_YAML
    assert stored.render() == f"{source} (tool.yaml)"

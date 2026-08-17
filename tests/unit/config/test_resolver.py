"""Tests for M1 behaviour 10 — the resolver.

See ``plans/m1-configuration.md`` §1, behaviour 10 (lines 179-196):

- **Scalars:** the highest present layer wins.  A four-layer test sets
  ``ttl`` at every level and asserts inline wins with ``OriginLevel.INLINE``;
  then removes layers one at a time and asserts each next level takes over
  with the right origin level.
- **Pure function:** resolution is a pure function of the layers — no
  filesystem, no environment, no clock (plan line 189).
- ``ttl`` sentinels: ``-1`` inherits ``defaults.ttl`` with the origin of the
  layer it inherited *from*; ``0`` never stops; ``>0`` seconds; ``-2`` and
  below is ``TSWAP-C501`` naming the three legal sentinels (plan line 188).
- Explicit ``null`` in a higher layer **wins** and means unset — it does not
  fall through (plan line 191).
- A key *absent* from a layer's dict is distinct from a key present with
  value ``None`` (plan line 192): absent falls through, present-as-``None``
  wins.
- ``devices`` inherited **from the group** when the tool sets none
  (plan line 193, assumption A11): group-supplied fields sit **between**
  ``defaults:`` and built-in in precedence.
- Resolving all tools must not share mutable state (plan line 194,
  behaviour 3's guard at resolver level).
- The resolver emits diagnostics **only** for ``TSWAP-C501`` (bad ttl
  sentinel), ``TSWAP-C503`` (duplicate mount container path, tested in
  ``test_merge_semantics.py``) and ``TSWAP-C106`` (unmapped tool.yaml
  nested key, tested in ``test_merge_semantics.py``); a clean resolution
  yields no diagnostics at all.

This file is the RED step: the module under test,
``src/tool_swap/config/resolver.py``, does not exist yet, so the file fails
collection with ``ModuleNotFoundError``.  That is the *right* red reason —
every test body below pins a concrete behaviour the GREEN step must
satisfy, so the assertions (not just the import) are the contract.

Pinned public API (the contract the GREEN step must meet verbatim):

- ``resolve_tool(name: str, *, inline: dict, tool_yaml: dict | None = None,
  defaults: dict | None = None, group: dict | None = None) -> ResolvedTool``
  — parameter names are pinned; ``inline`` is required, the other three
  layers are optional keyword arguments.
- ``ResolvedTool`` — a **frozen dataclass** with:
  - ``name: str`` — the tool name passed in.
  - ``values: dict[str, object]`` — field name -> resolved value.  The key
    set is **exactly** ``set(BUILT_IN_DEFAULTS)`` (47 flat fields).
  - ``origins: OriginMap`` — winning/shadowed origins per dotted path.
  - ``diagnostics`` — the ``Diagnostic`` values this resolution emitted
    (empty for a clean resolution; the tests assert membership and length
    only, so ``tuple`` or ``list`` are both acceptable).
- **Layer-dict conventions:**
  - The layer dicts use the flat field names of ``BUILT_IN_DEFAULTS``
    (``ttl``, ``cpus``, ``devices``, ``env``, ``mounts``, ...).
  - A key **absent** from a layer dict means *unset* (falls through to the
    next layer); a key **present with value ``None``** means *explicit
    null* (wins, and the resolved value is ``None``).
  - The built-in layer is applied **automatically** from
    ``BUILT_IN_DEFAULTS``; the caller never passes it.
- **Precedence (most specific first):** ``inline`` > ``tool_yaml`` >
  ``defaults`` > ``group`` > built-in.  The ``group`` layer is the
  group's own definition dict (``devices``, and its non-tool fields such
  as ``max_resident``/``eviction`` which the resolver must ignore).
- **Group origin (A11 tension, resolved as option (a)):** ``OriginLevel``
  has exactly four members and no ``GROUP`` member, so a group-supplied
  value records ``OriginLevel.DEFAULTS`` as its level.  The *source* names
  the group: ``groups.<name>.<field>`` (plan line 193: rendered as
  ``groups.gpu0.devices``).  The group name is carried in the group dict
  itself under the key ``"name"``.
- **Origin sources:** because the resolver is a pure function of dicts it
  cannot know file/line numbers (the loader supplies those later), so the
  tests pin origin **levels** for ``inline``/``tool_yaml``/``defaults`` and
  pin the exact ``Origin.built_in()`` (level ``BUILT_IN``, source
  ``"built-in default"``) for the built-in layer.
- **Shadowed origins:** recorded most specific first, per the behaviour 9
  convention in ``origin.py``.
- ``TSWAP-C501`` — ERROR — ``ttl`` below ``-1``; the message names the
  three legal sentinels: it contains ``"-1"``, ``"0"`` and either ``">0"``
  or the word ``"positive"``.

Conventions: pytest, AAA pattern, no ``warnings.warn`` (pyproject sets
``filterwarnings = "error"``).
"""

from __future__ import annotations

import dataclasses

import pytest

from tool_swap.config.defaults import BUILT_IN_DEFAULTS
from tool_swap.config.errors import Diagnostic, Severity
from tool_swap.config.origin import Origin, OriginLevel, OriginMap
from tool_swap.config.resolver import ResolvedTool, resolve_tool

# ---------------------------------------------------------------------------
# Pinned public API shape
# ---------------------------------------------------------------------------


def test_resolved_tool_is_frozen_dataclass_with_pinned_fields() -> None:
    """``ResolvedTool`` is a frozen dataclass with the pinned fields."""
    # Act
    result = resolve_tool("t", inline={})
    # Assert
    assert dataclasses.is_dataclass(result)
    assert result.name == "t"
    assert isinstance(result.values, dict)
    assert isinstance(result.origins, OriginMap)
    assert all(isinstance(d, Diagnostic) for d in result.diagnostics)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.name = "other"
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.values = {}


def test_values_covers_exactly_the_builtin_field_set() -> None:
    """``values`` resolves exactly the 47 flat fields of BUILT_IN_DEFAULTS."""
    # Act
    result = resolve_tool("t", inline={})
    # Assert
    assert set(result.values) == set(BUILT_IN_DEFAULTS)


# ---------------------------------------------------------------------------
# Scalar precedence: inline > tool.yaml > defaults > built-in
# ---------------------------------------------------------------------------


def test_scalar_precedence_all_layers_present_inline_wins() -> None:
    """With ``ttl`` set at every layer, inline wins with ``INLINE`` origin.

    The fourth layer is built-in (automatic); the group layer carries no
    ``ttl`` (``GroupConfig`` has no ttl field).
    """
    # Act
    result = resolve_tool(
        "t",
        inline={"ttl": 100},
        tool_yaml={"ttl": 200},
        defaults={"ttl": 300},
    )
    # Assert
    assert result.values["ttl"] == 100
    assert result.origins.winning("ttl").level is OriginLevel.INLINE
    # Shadowed origins, most specific first (behaviour 9 convention).
    assert [o.level for o in result.origins.shadowed("ttl")] == [
        OriginLevel.TOOL_YAML,
        OriginLevel.DEFAULTS,
    ]


@pytest.mark.parametrize(
    ("layers", "expected_value", "expected_level"),
    [
        pytest.param(
            {"tool_yaml": {"ttl": 200}, "defaults": {"ttl": 300}},
            200,
            OriginLevel.TOOL_YAML,
            id="inline-removed-tool-yaml-wins",
        ),
        pytest.param(
            {"defaults": {"ttl": 300}},
            300,
            OriginLevel.DEFAULTS,
            id="tool-yaml-removed-defaults-wins",
        ),
        pytest.param(
            {},
            900,
            OriginLevel.BUILT_IN,
            id="defaults-removed-builtin-wins",
        ),
    ],
)
def test_scalar_precedence_cascades_when_layers_removed(
    layers: dict, expected_value: int, expected_level: OriginLevel
) -> None:
    """Removing the winning layer hands ``ttl`` to the next level down."""
    # Act
    result = resolve_tool("t", inline={}, **layers)
    # Assert
    assert result.values["ttl"] == expected_value
    assert result.origins.winning("ttl").level is expected_level
    if expected_level is OriginLevel.BUILT_IN:
        assert result.origins.winning("ttl") == Origin.built_in()


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        pytest.param("queue_timeout", 300, id="queue_timeout"),
        pytest.param("group", "default", id="group"),
        pytest.param("devices", [], id="devices"),
        pytest.param("max_batch_size", 8, id="max_batch_size"),
    ],
)
def test_field_in_no_layer_resolves_to_builtin(field: str, expected: object) -> None:
    """A field in no passed layer resolves to the built-in value automatically."""
    # Act
    result = resolve_tool("t", inline={})
    # Assert
    assert result.values[field] == expected
    assert result.origins.winning(field) == Origin.built_in()


# ---------------------------------------------------------------------------
# Group layer (A11: between defaults: and built-in)
# ---------------------------------------------------------------------------


def test_group_supplies_devices_with_group_named_origin() -> None:
    """A group-supplied ``devices`` resolves with level DEFAULTS.

    A11 tension: ``OriginLevel`` has only four members, so the group origin
    reuses ``OriginLevel.DEFAULTS`` and names the group in the source
    instead (option (a), pinned here): ``groups.gpu0.devices``.
    """
    # Arrange
    group = {"name": "gpu0", "devices": [2]}
    # Act
    result = resolve_tool("t", inline={}, group=group)
    # Assert
    assert result.values["devices"] == [2]
    origin = result.origins.winning("devices")
    assert origin.level is OriginLevel.DEFAULTS
    assert origin.source == "groups.gpu0.devices"
    assert result.diagnostics == []


def test_group_layer_sits_between_defaults_and_builtin() -> None:
    """``defaults.devices`` beats the group; the group beats built-in."""
    # Act — defaults wins over group.
    above = resolve_tool(
        "t",
        inline={},
        defaults={"devices": [0]},
        group={"name": "g", "devices": [2]},
    )
    # Act — group wins over built-in (built-in ``devices`` is ``[]``).
    below = resolve_tool("t", inline={}, group={"name": "g", "devices": [2]})
    # Assert
    assert above.values["devices"] == [0]
    assert above.origins.winning("devices").level is OriginLevel.DEFAULTS
    assert below.values["devices"] == [2]
    assert below.origins.winning("devices").source == "groups.g.devices"


def test_group_non_tool_fields_are_ignored() -> None:
    """Group-definition fields (max_resident, eviction) do not leak in."""
    # Arrange
    group = {"name": "gpu0", "devices": [2], "max_resident": 1, "eviction": "lru"}
    # Act
    result = resolve_tool("t", inline={}, group=group)
    # Assert
    assert result.values["devices"] == [2]
    assert result.diagnostics == []


# ---------------------------------------------------------------------------
# Absent vs present-as-None
# ---------------------------------------------------------------------------


def test_explicit_null_in_inline_wins_and_means_unset() -> None:
    """``cpus: null`` inline wins over ``defaults.cpus`` and resolves to None."""
    # Act
    result = resolve_tool("t", inline={"cpus": None}, defaults={"cpus": 4.0})
    # Assert
    assert result.values["cpus"] is None
    assert result.origins.winning("cpus").level is OriginLevel.INLINE
    assert result.diagnostics == []


def test_absent_key_falls_through_to_defaults() -> None:
    """``cpus`` absent from inline resolves to the defaults value (contrast)."""
    # Act
    result = resolve_tool("t", inline={}, defaults={"cpus": 4.0})
    # Assert
    assert result.values["cpus"] == 4.0
    assert result.origins.winning("cpus").level is OriginLevel.DEFAULTS


# ---------------------------------------------------------------------------
# ttl sentinels
# ---------------------------------------------------------------------------


def test_ttl_minus_one_inherits_defaults_with_defaults_origin() -> None:
    """``ttl: -1`` resolves to ``defaults.ttl`` with the DEFAULTS origin."""
    # Act
    result = resolve_tool("t", inline={"ttl": -1}, defaults={"ttl": 300})
    # Assert
    assert result.values["ttl"] == 300
    assert result.origins.winning("ttl").level is OriginLevel.DEFAULTS
    assert result.diagnostics == []


def test_ttl_minus_one_with_no_defaults_falls_to_builtin() -> None:
    """``ttl: -1`` with no ``defaults.ttl`` inherits the built-in 900."""
    # Act
    result = resolve_tool("t", inline={"ttl": -1})
    # Assert
    assert result.values["ttl"] == 900
    assert result.origins.winning("ttl") == Origin.built_in()


@pytest.mark.parametrize(
    ("ttl", "expected"),
    [
        pytest.param(0, 0, id="zero-never-stop"),
        pytest.param(5, 5, id="positive-seconds"),
        pytest.param(900, 900, id="large-seconds"),
    ],
)
def test_ttl_legal_values_resolve_as_is(ttl: int, expected: int) -> None:
    """``ttl: 0`` and ``ttl: >0`` resolve to themselves with no diagnostic."""
    # Act
    result = resolve_tool("t", inline={"ttl": ttl})
    # Assert
    assert result.values["ttl"] == expected
    assert result.origins.winning("ttl").level is OriginLevel.INLINE
    assert result.diagnostics == []


@pytest.mark.parametrize("bad_ttl", [-2, -3, -100])
def test_ttl_below_minus_one_is_c501_error_naming_sentinels(bad_ttl: int) -> None:
    """``ttl: -2`` and lower is ``TSWAP-C501`` naming the legal sentinels."""
    # Act
    result = resolve_tool("t", inline={"ttl": bad_ttl})
    # Assert
    c501 = [d for d in result.diagnostics if d.code == "TSWAP-C501"]
    assert len(c501) == 1
    assert c501[0].severity is Severity.ERROR
    message = c501[0].message
    assert "-1" in message
    assert "0" in message
    assert (">0" in message) or ("positive" in message.lower())


# ---------------------------------------------------------------------------
# Purity
# ---------------------------------------------------------------------------


def test_resolve_tool_is_pure_equal_inputs_equal_results() -> None:
    """Two calls with equal (not identical) inputs give equal results."""
    # Arrange
    inline = {"ttl": 100, "env": {"A": "1"}, "devices": [0]}
    defaults = {"cpus": 2.0}
    group = {"name": "gpu0", "devices": [7]}
    # Act — two fresh but equal layer dicts per call.
    first = resolve_tool(
        "t",
        inline=dict(inline),
        tool_yaml=None,
        defaults=dict(defaults),
        group=dict(group),
    )
    second = resolve_tool(
        "t",
        inline=dict(inline),
        tool_yaml=None,
        defaults=dict(defaults),
        group=dict(group),
    )
    # Assert
    assert first.values == second.values
    assert first.diagnostics == second.diagnostics
    for path in ("ttl", "cpus", "devices", "env.A"):
        assert first.origins.winning(path) == second.origins.winning(path)


def test_resolve_tool_deep_copies_inputs_on_entry() -> None:
    """Mutating the caller's layer dicts after the call cannot change the result."""
    # Arrange
    inline = {"env": {"X": "1"}, "mounts": ["/a:/b:ro"], "devices": [0]}
    defaults = {"cpus": 4.0}
    # Act
    result = resolve_tool("t", inline=inline, defaults=defaults)
    # Act — mutate every input, including keys not set before.
    inline["env"]["X"] = "mutated"
    inline["mounts"].append("/c:/d:ro")
    inline["devices"].append(9)
    inline["ttl"] = 12345
    defaults["cpus"] = 99.0
    defaults["env"] = {"Z": 1}
    # Assert
    assert result.values["env"] == {"X": "1"}
    assert result.values["mounts"] == ["/a:/b:ro"]
    assert result.values["devices"] == [0]
    assert result.values["ttl"] == 900
    assert result.values["cpus"] == 4.0


def test_resolving_two_tools_does_not_share_mutable_values() -> None:
    """Mutating one resolved tool's list leaves the other tool's untouched."""
    # Act
    alpha = resolve_tool("alpha", inline={"devices": [0]})
    beta = resolve_tool("beta", inline={"devices": [0]})
    alpha.values["devices"].append(9)
    # Assert — the inline-sourced list is independent per tool.
    assert alpha.values["devices"] == [0, 9]
    assert beta.values["devices"] == [0]
    # Act — and so is a built-in-sourced list (behaviour 3's guard).
    a2 = resolve_tool("a2", inline={})
    b2 = resolve_tool("b2", inline={})
    a2.values["restart_backoff"].append(99)
    # Assert
    assert b2.values["restart_backoff"] == [1, 5, 15, 60]


def test_clean_resolution_emits_no_diagnostics() -> None:
    """A fully clean resolution across all layers yields zero diagnostics."""
    # Act
    result = resolve_tool(
        "t",
        inline={"ttl": 100, "env": {"A": "1"}, "devices": [0]},
        tool_yaml={"lifecycle": {"ready_timeout": 120}},
        defaults={"cpus": 2.0},
        group={"name": "gpu0", "devices": [7]},
    )
    # Assert
    assert result.diagnostics == []

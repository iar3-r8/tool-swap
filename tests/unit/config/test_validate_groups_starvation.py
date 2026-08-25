"""Tests for M1 behaviour 19 — D9 group starvation, and group capacity.

See ``plans/m1-configuration.md`` behaviour 19 (lines 1550-1560) and its
"Confirmed contract details (2026-08-19)" block (items 0-12, incl. 9a,
lines 1561-1818).  This file is the executable form of that contract:
the three rule constants (``TSWAP_C610_RULE``, ``TSWAP_C612_RULE``,
``TSWAP_C613_RULE``), the public ``group_members`` helper and the
``_C610_MECHANISM`` constant do not exist yet in
``src/tool_swap/config/validate.py`` (behaviour 18 shipped the C60x
rules and the 38-rule ``BUILTIN_RULES`` only).  This module therefore
fails collection with a single clean ``ImportError`` naming exactly one
missing name:

    ImportError: cannot import name 'group_members'
        from 'tool_swap.config.validate'

(``group_members`` is the first missing name in the import list; Python
reports the first one it fails on.)  Every test body below pins a
concrete behaviour the GREEN step must satisfy, so the assertions — not
just the import — are the contract.

Pinned public API (the names the GREEN step must add):

- ``group_members(config) -> dict[str, list[ResolvedTool]]`` — a pure,
  public module-level helper: keys are exactly
  ``effective_groups(config.raw).keys()`` in iteration order (a
  memberless group maps to ``[]``); members are the tools of
  ``config.tools`` whose effective group is the key, in
  ``config.tools`` order.  A non-string ``group`` value and a dangling
  group reference are excluded from every group.  Two calls yield
  equal, fresh (not aliased) lists and mutate nothing.
- ``_C610_MECHANISM`` — a module constant holding the verbatim
  mechanism sentence the C610 message must contain (item 4); imported
  and asserted as a substring, never re-typed.
- ``TSWAP_C610_RULE``, ``TSWAP_C612_RULE``, ``TSWAP_C613_RULE`` — ALL
  WARNING; non-empty remedies; appended to ``BUILTIN_RULES`` in code
  order after behaviour 18's four (41 total).  ``TSWAP-C611`` was
  WITHDRAWN before implementation (item 0 / A20): its predicate ships
  as ``TSWAP-C223``, so the numbering gap between C610 and C612 is
  deliberate and load-bearing.

Data access (item 1): the rules read group data via
``group_members(config)`` and ``config.raw`` — ``max_resident`` lives in
the RAW ``groups:`` block only (the resolver drops it into no
``ResolvedTool.values``), and C612 reads the raw block's ``devices``,
NEVER member ``values["devices"]`` (item 4's double-report trap).
``_group_max_resident`` (item 2): absent key → the ``GroupConfig``
schema default (read from the schema, asserted against ``4`` — never a
literal); non-dict block / bool / non-int / < 1 → skip.

Location contract (item 7): ``Location(file=str(config.path),
yaml_path=<pinned>, line=config.line_for(<the same string>))``; C610
and C613 at ``groups.<name>.max_resident`` (even when the key is
absent — ``line_for`` then answers ``None``), C612 at the bare
``groups`` block.  All three paths are dict-only.  Pinned relationally
with a fixed-int ``line_for`` AND a ``None``-returning ``line_for``.

Conventions mirror ``tests/unit/config/test_validate_contradictions.py``:
pytest, AAA, snake_case, Google docstrings, ``from __future__ import
annotations``, an autouse fixture calling ``unregister_all()`` before
AND after every test (the registry is shared module state), the C61x
rules registered explicitly per test, ``ResolvedTool`` /
``ValidatedConfig`` fakes built directly with keyword args.  No
``importlib.reload``.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest
from tool_swap.config.errors import Diagnostic, Severity
from tool_swap.config.origin import Origin, OriginLevel, OriginMap
from tool_swap.config.resolver import ResolvedTool
from tool_swap.config.schema import GroupConfig
from tool_swap.config.validate import (  # noqa: E501  (names absent in RED step)
    group_members,
    TSWAP_C610_RULE,
    TSWAP_C612_RULE,
    TSWAP_C613_RULE,
    _C610_MECHANISM,
    BUILTIN_RULES,
    ValidatedConfig,
    register,
    unregister_all,
    validate_config,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The six behaviour-12 rule ids (§6 rules 2 and 3), in code order
#: (mirrors ``_BEHAVIOUR_12_IDS`` in ``test_validate_names_groups.py``).
_BEHAVIOUR_12_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C210",
    "TSWAP-C211",
    "TSWAP-C220",
    "TSWAP-C221",
    "TSWAP-C222",
    "TSWAP-C223",
)

#: The four behaviour-13 rule ids (§6 rule 6b), in code order (mirrors
#: ``_BEHAVIOUR_13_IDS`` in ``test_validate_descriptions.py``).
_BEHAVIOUR_13_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C300",
    "TSWAP-C301",
    "TSWAP-C302",
    "TSWAP-C303",
)

#: The six behaviour-14 rule ids (§6 rules 4 and 1c), in code order
#: (mirrors ``_BEHAVIOUR_14_IDS`` in ``test_validate_reserved.py``).
_BEHAVIOUR_14_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C400",
    "TSWAP-C401",
    "TSWAP-C402",
    "TSWAP-C403",
    "TSWAP-C404",
    "TSWAP-C405",
)

#: The seven behaviour-15 rule ids (§6 rules 5 and 6), in code order
#: (mirrors ``_BEHAVIOUR_15_IDS`` in ``test_validate_image_source.py``).
_BEHAVIOUR_15_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C510",
    "TSWAP-C511",
    "TSWAP-C512",
    "TSWAP-C513",
    "TSWAP-C514",
    "TSWAP-C515",
    "TSWAP-C516",
)

#: The seven behaviour-16 rule ids (§6 rules 4c, 7 and 8), in code order
#: (mirrors ``_BEHAVIOUR_16_IDS`` in ``test_validate_resources.py``).
_BEHAVIOUR_16_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C520",
    "TSWAP-C521",
    "TSWAP-C522",
    "TSWAP-C523",
    "TSWAP-C530",
    "TSWAP-C531",
    "TSWAP-C532",
)

#: The four behaviour-17 rule ids (§6 rule 9), in code order (mirrors
#: ``_BEHAVIOUR_17_IDS`` in ``test_validate_mounts.py``).
_BEHAVIOUR_17_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C540",
    "TSWAP-C541",
    "TSWAP-C542",
    "TSWAP-C543",
)

#: The four behaviour-18 rule ids (§6 rule 11), in code order.
_BEHAVIOUR_18_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C600",
    "TSWAP-C601",
    "TSWAP-C602",
    "TSWAP-C603",
)

#: The three behaviour-19 rule ids (§6 rules 12 and 13), in code order.
#: NOTE the deliberate gap: ``TSWAP-C611`` was WITHDRAWN before
#: implementation (2026-08-19, item 0 / A20) — its predicate already
#: ships as ``TSWAP-C223`` — so the numbering jumps C610 → C612 and the
#: gap must stay a gap.
_BEHAVIOUR_19_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C610",
    "TSWAP-C612",
    "TSWAP-C613",
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _tool(
    name: str,
    values: dict[str, object] | None = None,
    origins: OriginMap | None = None,
) -> ResolvedTool:
    """Build a minimal frozen ``ResolvedTool``; only the given keys are set.

    Args:
        name: the tool name (used as both the ``tools`` dict key and the
            ``ResolvedTool.name`` in every fixture, so the two
            namespaces agree).
        values: flat field name -> resolved value; defaults to ``{}``
            (a tool with no ``group`` entry, which resolves to
            ``"default"`` per the built-in defaults).
        origins: the ``OriginMap`` for the fields a test records;
            defaults to an empty map (the behaviour-19 rules read
            resolved values only, never origins — the layer-blind test
            records a real ``DEFAULTS`` origin to prove it).

    Returns:
        A ``ResolvedTool`` with no diagnostics.
    """
    return ResolvedTool(
        name=name,
        values=values if values is not None else {},
        origins=origins if origins is not None else OriginMap(),
        diagnostics=[],
    )


def _config(
    tools: dict[str, ResolvedTool],
    raw: dict[str, object],
    line_for: Callable[[str], int | None] | None = None,
    path: Path | None = None,
) -> ValidatedConfig:
    """Build a ``ValidatedConfig`` fake (no loader, no filesystem).

    Args:
        tools: name -> ``ResolvedTool`` (positional field).
        raw: the raw root YAML mapping (positional field); the B19 rules
            read the ``groups:`` block ONLY through here.
        line_for: dotted YAML path -> 1-based line or ``None``
            (keyword-only); defaults to a ``None``-returning mapping.
        path: the config file path (keyword-only); defaults to
            ``Path("tools.yaml")``.

    Returns:
        The frozen ``ValidatedConfig``.
    """
    return ValidatedConfig(
        tools=tools,
        raw=raw,
        line_for=line_for if line_for is not None else (lambda _p: None),
        path=path if path is not None else Path("tools.yaml"),
    )


def _diagnostics_by_code(report: object) -> dict[str, list[Diagnostic]]:
    """Group a report's diagnostics by code for set-based assertions.

    Args:
        report: a ``ConfigReport`` (``.diagnostics`` iterable of
            ``Diagnostic``).

    Returns:
        Code -> the diagnostics carrying that code.
    """
    by_code: dict[str, list[Diagnostic]] = {}
    for d in report.diagnostics:  # type: ignore[attr-defined]
        by_code.setdefault(d.code, []).append(d)
    return by_code


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Start and end every test with an empty, known registry.

    The registry is shared module state: nothing registers itself at
    import time (Option B), and each test must not depend on — and must
    not leak — registration state.
    """
    unregister_all()
    try:
        yield
    finally:
        unregister_all()


# ---------------------------------------------------------------------------
# 1. group_members — the pure group→members helper (item 1)
# ---------------------------------------------------------------------------


def test_group_members_maps_each_group_to_its_members_in_declaration_order() -> None:
    """Two groups, tools distributed -> correct mapping, both orders.

    Arrangement: a raw ``groups`` block with keys ``zeta`` then ``alpha``
    (deliberately unsorted); ``config.tools`` holding ``t1`` (zeta),
    ``t2`` (alpha), ``t3`` (zeta) in that declaration order.
    Action: call ``group_members`` once.
    Assertion: the mapping is ``{"zeta": [t1, t3], "alpha": [t2]}``; the
    keys iterate in ``effective_groups`` order (the raw block's order,
    NOT sorted order); each member list keeps ``config.tools`` order and
    holds the same tool objects.
    """
    t1 = _tool("t1", values={"group": "zeta"})
    t2 = _tool("t2", values={"group": "alpha"})
    t3 = _tool("t3", values={"group": "zeta"})
    cfg = _config(
        tools={"t1": t1, "t2": t2, "t3": t3},
        raw={
            "tools": {
                "t1": {"group": "zeta"},
                "t2": {"group": "alpha"},
                "t3": {"group": "zeta"},
            },
            "groups": {
                "zeta": {"max_resident": 2, "eviction": "lru"},
                "alpha": {"max_resident": 1, "eviction": "lru"},
            },
        },
    )

    result = group_members(cfg)

    assert list(result) == ["zeta", "alpha"]
    assert result == {"zeta": [t1, t3], "alpha": [t2]}
    assert result["zeta"][0] is t1
    assert result["zeta"][1] is t3
    assert result["alpha"][0] is t2


def test_group_members_includes_a_memberless_group_as_an_empty_list() -> None:
    """A group no tool references is still present, mapped to ``[]``.

    ``TSWAP-C223`` reports an orphan group; ``group_members`` must still
    LIST it (item 1: a group with no members maps to ``[]``) so the B19
    rules see the complete key set.

    Arrangement: groups ``default`` and ``orphan``; one tool resolving
    to ``default`` only.
    Action: call ``group_members``.
    Assertion: ``"orphan"`` is a key mapped to ``[]``; ``default`` maps
    to the tool.
    """
    alpha = _tool("alpha")  # resolves to "default"
    cfg = _config(
        tools={"alpha": alpha},
        raw={
            "tools": {"alpha": {}},
            "groups": {
                "default": {"max_resident": 4, "eviction": "lru"},
                "orphan": {"max_resident": 1, "eviction": "lru"},
            },
        },
    )

    result = group_members(cfg)

    assert list(result) == ["default", "orphan"]
    assert result["orphan"] == []
    assert result["default"] == [alpha]


def test_group_members_includes_the_synthesised_default_group() -> None:
    """No ``groups`` key: the synthesised ``default`` group still appears.

    Item 3: with ``raw`` lacking ``"groups"``, ``effective_groups``
    synthesises ``default`` (the schema defaults), and
    ``group_members`` must still judge that synthetic group — C610 needs
    it to see the members.

    Arrangement: raw without a ``groups`` key; three tools with no
    ``group`` entry (each resolves to ``default``).
    Action: call ``group_members``.
    Assertion: the result is exactly ``{"default": [t1, t2, t3]}``.
    """
    t1 = _tool("t1")
    t2 = _tool("t2")
    t3 = _tool("t3")
    cfg = _config(
        tools={"t1": t1, "t2": t2, "t3": t3},
        raw={"tools": {"t1": {}, "t2": {}, "t3": {}}},
    )

    result = group_members(cfg)

    assert list(result) == ["default"]
    assert result == {"default": [t1, t2, t3]}


def test_group_members_excludes_non_string_group_and_dangling_reference() -> None:
    """A non-string ``group`` and a dangling reference belong to no group.

    Item 1 pins both exclusions rather than leaving them incidental: a
    tool whose ``group`` value is not a string (C105's territory) and a
    tool naming a group absent from the block (C220's territory) become
    a member of NOTHING, and neither inflates nor deflates another
    group's count.

    Arrangement: group ``g1`` defined; tools ``good`` (``g1``),
    ``typed`` (``group: 7``, a non-string) and ``dangling``
    (``group: "ghost"``, not in the block).
    Action: call ``group_members``.
    Assertion: the result is exactly ``{"g1": [good]}`` — one key only,
    one member only.
    """
    good = _tool("good", values={"group": "g1"})
    typed = _tool("typed", values={"group": 7})  # type: ignore[dict-item]
    dangling = _tool("dangling", values={"group": "ghost"})
    cfg = _config(
        tools={"good": good, "typed": typed, "dangling": dangling},
        raw={
            "tools": {
                "good": {"group": "g1"},
                "typed": {"group": 7},
                "dangling": {"group": "ghost"},
            },
            "groups": {"g1": {"max_resident": 2, "eviction": "lru"}},
        },
    )

    result = group_members(cfg)

    assert list(result) == ["g1"]
    assert result == {"g1": [good]}


def test_group_members_is_pure_and_returns_fresh_lists() -> None:
    """Two calls yield equal, fresh (not aliased) lists; nothing mutates.

    Arrangement: a config with one group and two members; deep
    snapshots of ``raw`` and every tool's ``values`` mapping taken
    first.
    Action: call ``group_members`` twice; compare the results,
    alias-check the member lists, and re-check the snapshots.
    Assertion: the two results are equal but their member lists are
    distinct objects (fresh per call, never aliased); the member
    objects themselves are the original tools; ``cfg.raw`` and every
    ``values`` mapping are unchanged.
    """
    t1 = _tool("t1", values={"group": "g1"})
    t2 = _tool("t2", values={"group": "g1"})
    cfg = _config(
        tools={"t1": t1, "t2": t2},
        raw={
            "tools": {"t1": {"group": "g1"}, "t2": {"group": "g1"}},
            "groups": {"g1": {"max_resident": 2, "eviction": "lru"}},
        },
    )
    raw_before = copy.deepcopy(cfg.raw)
    values_before = {name: dict(t.values) for name, t in cfg.tools.items()}

    first = group_members(cfg)
    second = group_members(cfg)

    assert first == second
    assert first["g1"] is not second["g1"]  # fresh lists, never aliased
    assert first["g1"] == [t1, t2]
    assert first["g1"][0] is t1  # the original tool objects
    assert cfg.raw == raw_before
    for name, tool in cfg.tools.items():
        assert tool.values == values_before[name]


# ---------------------------------------------------------------------------
# 2. TSWAP-C610 — every member keep_warm while max_resident < count
# ---------------------------------------------------------------------------


def test_c610_warns_when_every_member_keep_warm_and_capacity_below_count() -> None:
    """3 keep-warm members, ``max_resident: 2`` -> one C610 WARNING.

    Item 4's first row.  The message names the group, the member count,
    ``max_resident`` and the pinned mechanism sentence (imported, not
    re-typed); the remedy names BOTH options: raising ``max_resident``
    to the member count AND ``eviction: none``.

    Arrangement: group ``gpu0`` (``max_resident: 2``) with three
    ``keep_warm: true`` members; a fixed-int ``line_for``.
    Action: run only ``TSWAP_C610_RULE``.
    Assertion: exactly one WARNING; the message substrings; the remedy
    substrings; the location ``groups.gpu0.max_resident`` at the
    ``line_for`` line.
    """
    register(TSWAP_C610_RULE)
    tools = {
        "t1": _tool("t1", values={"group": "gpu0", "keep_warm": True}),
        "t2": _tool("t2", values={"group": "gpu0", "keep_warm": True}),
        "t3": _tool("t3", values={"group": "gpu0", "keep_warm": True}),
    }
    raw = {
        "tools": {
            "t1": {"group": "gpu0", "keep_warm": True},
            "t2": {"group": "gpu0", "keep_warm": True},
            "t3": {"group": "gpu0", "keep_warm": True},
        },
        "groups": {"gpu0": {"max_resident": 2, "eviction": "lru"}},
    }
    cfg = _config(tools=tools, raw=raw, line_for=lambda _p: 12)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C610"}
    (d,) = by_code["TSWAP-C610"]
    assert d.severity is Severity.WARNING
    assert "gpu0" in d.message
    assert "3 members" in d.message
    assert "max_resident is 2" in d.message
    assert _C610_MECHANISM in d.message
    assert "max_resident to 3" in d.remedy
    assert "eviction: none" in d.remedy
    assert d.location.file == "tools.yaml"
    assert d.location.yaml_path == "groups.gpu0.max_resident"
    assert d.location.line == 12
    assert d.location.line == cfg.line_for(d.location.yaml_path)


def test_c610_is_silent_when_one_member_is_not_keep_warm() -> None:
    """A group only PARTIALLY keep-warm does not warn (item 4).

    Arrangement: 3 members, two ``keep_warm: true`` and one that never
    sets the key anywhere, so it resolves to the built-in ``False`` —
    the spec says *every* member.
    Action: run only C610.
    Assertion: an empty report.
    """
    register(TSWAP_C610_RULE)
    tools = {
        "t1": _tool("t1", values={"group": "g1", "keep_warm": True}),
        "t2": _tool("t2", values={"group": "g1", "keep_warm": True}),
        "t3": _tool("t3", values={"group": "g1", "keep_warm": False}),
    }
    raw = {
        "tools": {
            "t1": {"group": "g1", "keep_warm": True},
            "t2": {"group": "g1", "keep_warm": True},
            "t3": {"group": "g1", "keep_warm": False},
        },
        "groups": {"g1": {"max_resident": 2, "eviction": "lru"}},
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c610_is_silent_when_capacity_equals_member_count() -> None:
    """``max_resident: 3`` with 3 keep-warm members -> NO C610.

    Item 4's row 3: ``3 < 3`` is false — the group exactly fits.

    Arrangement: 3 ``keep_warm: true`` members, ``max_resident: 3``.
    Action: run only C610.
    Assertion: an empty report.
    """
    register(TSWAP_C610_RULE)
    tools = {
        f"t{i}": _tool(f"t{i}", values={"group": "g1", "keep_warm": True})
        for i in range(3)
    }
    raw = {
        "tools": {f"t{i}": {"group": "g1", "keep_warm": True} for i in range(3)},
        "groups": {"g1": {"max_resident": 3, "eviction": "lru"}},
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c610_is_silent_for_single_member_at_capacity_one() -> None:
    """1 keep-warm member, ``max_resident: 1`` -> NO C610 (the plan's edge).

    Arrangement: the plan's own edge case, falling out of clause 4 with
    no special case.
    Action: run only C610.
    Assertion: an empty report.
    """
    register(TSWAP_C610_RULE)
    tools = {"solo": _tool("solo", values={"group": "g1", "keep_warm": True})}
    raw = {
        "tools": {"solo": {"group": "g1", "keep_warm": True}},
        "groups": {"g1": {"max_resident": 1, "eviction": "lru"}},
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c610_is_silent_for_a_memberless_group() -> None:
    """0 members -> NO C610 (clause 2; C223 reports the orphan).

    ``all()`` over an empty list is vacuously ``True`` — the at-least-
    one-member guard is exactly the bug item 4's clause 2 prevents.

    Arrangement: a defined group, an empty ``tools`` mapping.
    Action: run only C610.
    Assertion: an empty report.
    """
    register(TSWAP_C610_RULE)
    raw = {"groups": {"orphan": {"max_resident": 2, "eviction": "lru"}}}
    cfg = _config(tools={}, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c610_warns_on_five_keep_warm_members_when_max_resident_absent() -> None:
    """``max_resident`` absent -> the schema default (4) applies, not a skip.

    Item 2: an absent key is checked, not skipped — Pydantic genuinely
    applies ``4`` at runtime, and a bare group block is the commonest
    hand-written shape.  Five keep-warm members against the default 4
    genuinely starve, whoever wrote the four.

    Arrangement: group ``gpu0`` with NO ``max_resident`` key; five
    ``keep_warm: true`` members; the default ``None``-returning
    ``line_for``.
    Action: run only C610.
    Assertion: one WARNING whose message names the schema-default
    capacity (read from ``GroupConfig``, asserted to be 4) and whose
    remedy raises it to 5; located at ``groups.gpu0.max_resident`` with
    ``line is None`` — the key the author did not write (item 7).
    """
    register(TSWAP_C610_RULE)
    default_capacity = int(GroupConfig.model_fields["max_resident"].default)
    assert default_capacity == 4  # verified against schema.py, GroupConfig
    tools = {
        f"t{i}": _tool(f"t{i}", values={"group": "gpu0", "keep_warm": True})
        for i in range(5)
    }
    raw = {
        "tools": {f"t{i}": {"group": "gpu0", "keep_warm": True} for i in range(5)},
        "groups": {"gpu0": {"eviction": "lru"}},
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C610"}
    (d,) = by_code["TSWAP-C610"]
    assert d.severity is Severity.WARNING
    assert "gpu0" in d.message
    assert f"max_resident is {default_capacity}" in d.message
    assert _C610_MECHANISM in d.message
    assert "max_resident to 5" in d.remedy
    assert d.location.yaml_path == "groups.gpu0.max_resident"
    assert d.location.line is None
    assert d.location.line == cfg.line_for(d.location.yaml_path)


def test_c610_is_silent_on_three_keep_warm_members_when_max_resident_absent() -> None:
    """3 keep-warm members, ``max_resident`` absent -> NO C610.

    The same default (4) that fires at 5 members does not fire at 3:
    ``4 < 3`` is false.

    Arrangement: 3 ``keep_warm: true`` members, a block with no
    ``max_resident`` key.
    Action: run only C610.
    Assertion: an empty report.
    """
    register(TSWAP_C610_RULE)
    tools = {
        f"t{i}": _tool(f"t{i}", values={"group": "g1", "keep_warm": True})
        for i in range(3)
    }
    raw = {
        "tools": {f"t{i}": {"group": "g1", "keep_warm": True} for i in range(3)},
        "groups": {"g1": {"eviction": "lru"}},
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c610_skips_a_group_with_max_resident_zero() -> None:
    """``max_resident: 0`` -> NO C610 (C221 already errors; the rule skips).

    Item 2: any value ``< 1`` is ``TSWAP-C221``'s error, already
    reported; a second warning about a capacity the author must change
    anyway is noise.

    Arrangement: 2 keep-warm members, ``max_resident: 0`` (which WOULD
    starve, 0 < 2, were the rule not to skip).
    Action: run only C610.
    Assertion: an empty report — the skip is pinned.
    """
    register(TSWAP_C610_RULE)
    tools = {
        "t1": _tool("t1", values={"group": "g1", "keep_warm": True}),
        "t2": _tool("t2", values={"group": "g1", "keep_warm": True}),
    }
    raw = {
        "tools": {
            "t1": {"group": "g1", "keep_warm": True},
            "t2": {"group": "g1", "keep_warm": True},
        },
        "groups": {"g1": {"max_resident": 0, "eviction": "lru"}},
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c610_skips_a_group_with_a_bool_max_resident() -> None:
    """``max_resident: true`` (a bool) -> NO C610 (bool-before-int skip).

    Item 2's shipped C221/C530 pattern: ``bool`` is checked before
    ``int`` (in Python ``True`` IS an ``int``), so a bool capacity is a
    skip, not a capacity of 1.

    Arrangement: 2 keep-warm members, ``max_resident: true`` (which
    WOULD starve, 1 < 2, were the bool not skipped).
    Action: run only C610.
    Assertion: an empty report.
    """
    register(TSWAP_C610_RULE)
    tools = {
        "t1": _tool("t1", values={"group": "g1", "keep_warm": True}),
        "t2": _tool("t2", values={"group": "g1", "keep_warm": True}),
    }
    raw = {
        "tools": {
            "t1": {"group": "g1", "keep_warm": True},
            "t2": {"group": "g1", "keep_warm": True},
        },
        "groups": {"g1": {"max_resident": True, "eviction": "lru"}},
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c610_is_layer_blind_for_defaults_resolved_keep_warm() -> None:
    """A ``defaults:``-resolved ``keep_warm`` counts exactly like an inline one.

    Item 4: ``_effective_group`` and ``keep_warm`` are read LAYER-BLIND
    — the rule reads the resolved value only, never the origin.  A
    member whose ``keep_warm`` came from the ``defaults:`` block starves
    the group just as hard, and no origin is consulted anywhere in
    behaviour 19.

    Arrangement: group ``g1`` (``max_resident: 2``) with three
    ``keep_warm: true`` members; the third is built the way a
    defaults-resolved tool is — its winning ``keep_warm`` origin is
    recorded at ``DEFAULTS`` level.
    Action: run only C610.
    Assertion: one WARNING — the same outcome as if every member had
    set the key inline.
    """
    register(TSWAP_C610_RULE)
    defaults_origin = Origin(OriginLevel.DEFAULTS, "defaults")
    origins = OriginMap()
    origins.record("keep_warm", defaults_origin)
    tools = {
        "t1": _tool("t1", values={"group": "g1", "keep_warm": True}),
        "t2": _tool("t2", values={"group": "g1", "keep_warm": True}),
        "t3": _tool("t3", values={"group": "g1", "keep_warm": True}, origins=origins),
    }
    raw = {
        "tools": {
            "t1": {"group": "g1", "keep_warm": True},
            "t2": {"group": "g1", "keep_warm": True},
            "t3": {"group": "g1", "keep_warm": True},
        },
        "groups": {"g1": {"max_resident": 2, "eviction": "lru"}},
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C610"}
    (d,) = by_code["TSWAP-C610"]
    assert "g1" in d.message
    assert "3 members" in d.message


def test_c610_warns_on_the_synthesised_default_group() -> None:
    """No ``groups`` key + five keep-warm tools -> C610 on ``default``.

    Item 3: C610 JUDGES the synthesised default group — exempting it
    would pull D9's teeth on the commonest config shape, and the remedy
    is still actionable (add a ``groups:`` block raising ``default``'s
    ``max_resident``).

    Arrangement: raw WITHOUT a ``groups`` key; five tools with no
    ``group`` entry (all resolve to the synthesised ``default``), all
    ``keep_warm: true`` — five against the synthesised capacity of 4.
    Action: run only C610.
    Assertion: one WARNING located at ``groups.default.max_resident``.
    """
    register(TSWAP_C610_RULE)
    tools = {
        f"t{i}": _tool(f"t{i}", values={"keep_warm": True}) for i in range(5)
    }
    raw = {"tools": {f"t{i}": {"keep_warm": True} for i in range(5)}}
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C610"}
    (d,) = by_code["TSWAP-C610"]
    assert d.severity is Severity.WARNING
    assert "default" in d.message
    assert "5 members" in d.message
    assert d.location.yaml_path == "groups.default.max_resident"
    assert d.location.line is None


# ---------------------------------------------------------------------------
# 3. TSWAP-C612 — overlapping devices, combined capacity above the larger
# ---------------------------------------------------------------------------


def test_c612_warns_when_two_groups_share_a_device_and_combined_exceeds_larger() -> None:
    """Two groups on device 0 (4 + 6) -> ONE C612 WARNING.

    Item 5's worked example: the combined ``max_resident`` (10) exceeds
    the larger group's (6).  The message names the shared device index
    and both groups, and states the "we do not model VRAM in v1"
    direction so nobody reads the warning as an arithmetic guarantee.

    Arrangement: ``gpu0`` (``max_resident: 4``, ``devices: [0]``) and
    ``gpu1`` (``max_resident: 6``, ``devices: [0]``); a fixed-int
    ``line_for``.
    Action: run only ``TSWAP_C612_RULE``.
    Assertion: exactly ONE WARNING; the message names ``gpu0``,
    ``gpu1``, device ``0``, the combined ``10`` and the larger ``6``,
    and contains the pinned VRAM direction; the location is the bare
    ``groups`` block at the ``line_for`` line.
    """
    register(TSWAP_C612_RULE)
    raw = {
        "tools": {},
        "groups": {
            "gpu0": {"max_resident": 4, "devices": [0]},
            "gpu1": {"max_resident": 6, "devices": [0]},
        },
    }
    cfg = _config(tools={}, raw=raw, line_for=lambda _p: 9)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C612"}
    (d,) = by_code["TSWAP-C612"]
    assert d.severity is Severity.WARNING
    assert "gpu0" in d.message
    assert "gpu1" in d.message
    assert "device 0" in d.message
    assert "10" in d.message
    assert "6" in d.message
    assert "does not model VRAM" in d.message
    assert d.location.file == "tools.yaml"
    assert d.location.yaml_path == "groups"
    assert d.location.line == 9
    assert d.location.line == cfg.line_for(d.location.yaml_path)


def test_c612_warns_on_equal_max_resident() -> None:
    """4 and 4 on a shared device -> ONE WARNING (the pinned 8 > 4 edge).

    Arrangement: two groups, both ``max_resident: 4``, both on device 0.
    Action: run only C612.
    Assertion: exactly one diagnostic naming both groups and the
    combined ``8``.
    """
    register(TSWAP_C612_RULE)
    raw = {
        "tools": {},
        "groups": {
            "a": {"max_resident": 4, "devices": [0]},
            "b": {"max_resident": 4, "devices": [0]},
        },
    }
    cfg = _config(tools={}, raw=raw)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C612"}
    (d,) = by_code["TSWAP-C612"]
    assert "a" in d.message
    assert "b" in d.message
    assert "8" in d.message


def test_c612_one_diagnostic_naming_all_three_groups_on_one_device() -> None:
    """Three groups on device 0 (4 + 6 + 2) -> ONE diagnostic naming all three.

    Item 5: one diagnostic per shared device index, not per pair.

    Arrangement: ``g3a`` (4), ``g3b`` (6), ``g3c`` (2), all on device 0.
    Action: run only C612.
    Assertion: exactly ONE diagnostic naming all three groups.
    """
    register(TSWAP_C612_RULE)
    raw = {
        "tools": {},
        "groups": {
            "g3a": {"max_resident": 4, "devices": [0]},
            "g3b": {"max_resident": 6, "devices": [0]},
            "g3c": {"max_resident": 2, "devices": [0]},
        },
    }
    cfg = _config(tools={}, raw=raw)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C612"}
    (d,) = by_code["TSWAP-C612"]
    assert "g3a" in d.message
    assert "g3b" in d.message
    assert "g3c" in d.message
    assert "device 0" in d.message


def test_c612_one_diagnostic_per_shared_device_index() -> None:
    """Two groups sharing devices 0 AND 1 -> TWO diagnostics, one per index.

    Item 5: each shared index is its own contended piece of hardware,
    so each gets its own diagnostic naming its own index.

    Arrangement: both groups declare ``devices: [0, 1]`` (capacities 4
    and 6).
    Action: run only C612.
    Assertion: exactly two diagnostics; one names ``device 0`` (and not
    ``device 1``), the other ``device 1`` (and not ``device 0``); both
    name both groups and locate at the bare ``groups`` block.
    """
    register(TSWAP_C612_RULE)
    raw = {
        "tools": {},
        "groups": {
            "a": {"max_resident": 4, "devices": [0, 1]},
            "b": {"max_resident": 6, "devices": [0, 1]},
        },
    }
    cfg = _config(tools={}, raw=raw)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C612"}
    diags = by_code["TSWAP-C612"]
    assert len(diags) == 2
    first, second = diags
    assert ("device 0" in first.message) != ("device 0" in second.message)
    assert ("device 1" in first.message) != ("device 1" in second.message)
    for d in diags:
        assert "a" in d.message
        assert "b" in d.message
        assert d.location.yaml_path == "groups"


def test_c612_is_silent_when_a_group_declares_no_devices() -> None:
    """A group with NO raw ``devices`` does not participate.

    Item 5: ``GroupConfig.devices`` defaults to ``None`` (not ``[]``)
    and there is no synthesis — a group that omits ``devices`` simply
    cannot overlap, whatever its capacity.

    Arrangement: ``a`` (``devices: [0]``, 4) and ``b`` (no ``devices``
    key, 4).
    Action: run only C612.
    Assertion: an empty report.
    """
    register(TSWAP_C612_RULE)
    raw = {
        "tools": {},
        "groups": {
            "a": {"max_resident": 4, "devices": [0]},
            "b": {"max_resident": 4},
        },
    }
    cfg = _config(tools={}, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c612_is_silent_for_disjoint_devices() -> None:
    """Disjoint device sets (``[0]`` vs ``[1]``) -> NO C612.

    Arrangement: two groups on different device indices.
    Action: run only C612.
    Assertion: an empty report.
    """
    register(TSWAP_C612_RULE)
    raw = {
        "tools": {},
        "groups": {
            "a": {"max_resident": 4, "devices": [0]},
            "b": {"max_resident": 6, "devices": [1]},
        },
    }
    cfg = _config(tools={}, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c612_participates_only_with_usable_device_indices() -> None:
    """A malformed raw ``devices`` entry is skipped here (C520 owns it).

    Item 5: the index set is ``{i for i in devices if
    _is_device_index(i)}`` — a string entry is unusable and causes
    NOTHING in this rule, but the usable index still participates.

    Arrangement: ``a`` with ``devices: [0, "not-an-index"]`` (4) and
    ``b`` with ``devices: [0]`` (6).
    Action: run only C612.
    Assertion: exactly one C612 — the shared usable index 0 still
    overlaps; the malformed entry adds no diagnostic of its own.
    """
    register(TSWAP_C612_RULE)
    raw = {
        "tools": {},
        "groups": {
            "a": {"max_resident": 4, "devices": [0, "not-an-index"]},
            "b": {"max_resident": 6, "devices": [0]},
        },
    }
    cfg = _config(tools={}, raw=raw)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C612"}
    (d,) = by_code["TSWAP-C612"]
    assert "a" in d.message
    assert "b" in d.message
    assert "device 0" in d.message


def test_c612_never_reads_member_devices_values() -> None:
    """Member ``values["devices"]`` never trigger C612 (the double-report trap).

    Item 4: group ``devices`` DO flow into each member's
    ``values["devices"]`` through the resolver, and a tool may override
    them inline — but C612 is a statement about the ``groups:`` block
    alone.  Reading member values would make it fire on *tools* that
    happen to share a device and double-report against behaviour 16's
    C523/C530.

    Arrangement: two groups with NO ``devices`` in their raw blocks;
    their members carry ``values["devices"] = [0]`` (a resolved,
    possibly overridden, tool field).
    Action: run only C612.
    Assertion: an empty report.
    """
    register(TSWAP_C612_RULE)
    tools = {
        "t1": _tool("t1", values={"group": "a", "devices": [0]}),
        "t2": _tool("t2", values={"group": "b", "devices": [0]}),
    }
    raw = {
        "tools": {
            "t1": {"group": "a", "devices": [0]},
            "t2": {"group": "b", "devices": [0]},
        },
        "groups": {
            "a": {"max_resident": 4},
            "b": {"max_resident": 6},
        },
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c612_uses_default_capacity_for_a_partner_missing_max_resident() -> None:
    """An overlapping partner without ``max_resident`` contributes the default.

    Item 2: the absent key means the schema default (4), not a skip — so
    ``a`` (default 4) + ``b`` (6) on device 0 combines to 10 > 6.

    Arrangement: ``a`` (``devices: [0]``, no ``max_resident``) and
    ``b`` (``devices: [0]``, ``max_resident: 6``); the default
    ``None``-returning ``line_for``.
    Action: run only C612.
    Assertion: one WARNING; location the bare ``groups`` block with
    ``line is None``.
    """
    register(TSWAP_C612_RULE)
    raw = {
        "tools": {},
        "groups": {
            "a": {"devices": [0]},
            "b": {"max_resident": 6, "devices": [0]},
        },
    }
    cfg = _config(tools={}, raw=raw)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C612"}
    (d,) = by_code["TSWAP-C612"]
    assert "a" in d.message
    assert "b" in d.message
    assert d.location.yaml_path == "groups"
    assert d.location.line is None
    assert d.location.line == cfg.line_for(d.location.yaml_path)


@pytest.mark.parametrize("capacity_a", [1, 4, 6])
@pytest.mark.parametrize("capacity_b", [1, 6])
def test_c612_fires_on_every_two_group_device_overlap(
    capacity_a: int, capacity_b: int
) -> None:
    """EVERY two-group overlap fires (item 5's recorded equivalence).

    With every ``max_resident >= 1`` after the skip filter,
    ``a + b > max(a, b)`` for ANY two participants — the inequality is
    satisfied by any pair, and that is deliberate: it is the honest
    expression of the reason, and it is recorded here so nobody reads
    the comparison as dead code.

    Arrangement: two groups both declaring ``devices: [0]`` with the
    parametrised capacities.
    Action: run only C612.
    Assertion: exactly one diagnostic for every capacity pair.
    """
    register(TSWAP_C612_RULE)
    raw = {
        "tools": {},
        "groups": {
            "a": {"max_resident": capacity_a, "devices": [0]},
            "b": {"max_resident": capacity_b, "devices": [0]},
        },
    }
    cfg = _config(tools={}, raw=raw)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C612"}
    assert len(by_code["TSWAP-C612"]) == 1


# ---------------------------------------------------------------------------
# 4. TSWAP-C613 — max_resident above the member count
# ---------------------------------------------------------------------------


def test_c613_warns_when_max_resident_exceeds_member_count() -> None:
    """``max_resident: 4`` with 2 members -> one C613 WARNING.

    Item 6: the message direction is "you probably shrank this group
    and forgot" — harmless, but usually a stale config.  The remedy
    ends with the deliberate "nothing breaks either way" clause: C613
    is the only M1 diagnostic on an entirely correct config, and under
    behaviour 24's ``--strict`` it becomes an error.

    Arrangement: group ``gpu0`` (``max_resident: 4``) with two members;
    a fixed-int ``line_for``.
    Action: run only ``TSWAP_C613_RULE``.
    Assertion: one WARNING; the message names the group, the capacity
    and the member count, and says it is harmless; the remedy lowers
    the capacity to the count and ends with the pinned harmlessness
    clause; the location ``groups.gpu0.max_resident`` at the
    ``line_for`` line.
    """
    register(TSWAP_C613_RULE)
    tools = {
        "t1": _tool("t1", values={"group": "gpu0"}),
        "t2": _tool("t2", values={"group": "gpu0"}),
    }
    raw = {
        "tools": {"t1": {"group": "gpu0"}, "t2": {"group": "gpu0"}},
        "groups": {"gpu0": {"max_resident": 4, "eviction": "lru"}},
    }
    cfg = _config(tools=tools, raw=raw, line_for=lambda _p: 21)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C613"}
    (d,) = by_code["TSWAP-C613"]
    assert d.severity is Severity.WARNING
    assert "gpu0" in d.message
    assert "max_resident 4" in d.message
    assert "2 members" in d.message
    assert "harmless" in d.message
    assert "max_resident to 2" in d.remedy
    assert "nothing breaks either way" in d.remedy
    assert d.location.file == "tools.yaml"
    assert d.location.yaml_path == "groups.gpu0.max_resident"
    assert d.location.line == 21
    assert d.location.line == cfg.line_for(d.location.yaml_path)


def test_c613_is_silent_for_a_memberless_group() -> None:
    """A memberless group (``max_resident: 4``, 0 members) -> NO C613.

    Item 6: even though ``4 > 0``, a memberless group is C223's
    finding, and reporting a stale capacity for a group with no
    members is the less useful of the two facts.

    Arrangement: a defined group, an empty ``tools`` mapping.
    Action: run only C613.
    Assertion: an empty report.
    """
    register(TSWAP_C613_RULE)
    raw = {"groups": {"orphan": {"max_resident": 4, "eviction": "lru"}}}
    cfg = _config(tools={}, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c613_is_silent_when_capacity_equals_member_count() -> None:
    """``max_resident == member count`` -> NO C613.

    Item 6: ``==`` fires neither C610 nor C613 (one needs ``<``, the
    other ``>``).

    Arrangement: ``max_resident: 2`` with exactly 2 members.
    Action: run only C613.
    Assertion: an empty report.
    """
    register(TSWAP_C613_RULE)
    tools = {
        "t1": _tool("t1", values={"group": "g1"}),
        "t2": _tool("t2", values={"group": "g1"}),
    }
    raw = {
        "tools": {"t1": {"group": "g1"}, "t2": {"group": "g1"}},
        "groups": {"g1": {"max_resident": 2, "eviction": "lru"}},
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c613_does_not_judge_the_synthesised_default_group() -> None:
    """No ``groups`` key + one tool -> NO C613, even though 1 < 4.

    Item 3: the exemption is REQUIRED, not chosen — ``4`` is OUR number
    (the schema default the synthesis carries), and warning that our
    default exceeds their one tool would warn about nothing and fail
    behaviour 23's zero-warnings golden path.  Implemented as the
    ``"groups" not in raw`` guard, checked against raw directly rather
    than by sniffing the synthesised values.

    Arrangement: raw WITHOUT a ``groups`` key; one tool with no
    ``group`` entry.
    Action: run only C613.
    Assertion: an empty report.
    """
    register(TSWAP_C613_RULE)
    tools = {"solo": _tool("solo")}
    raw = {"tools": {"solo": {}}}
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c613_fires_on_a_hand_written_default_group() -> None:
    """A hand-written ``default: {max_resident: 4}`` with one tool DOES fire.

    Item 3: the author WROTE the 4 — that is the point of the
    distinction from the synthesised block.

    Arrangement: ``groups: {default: {max_resident: 4}}``; one tool
    with no ``group`` entry (resolving to ``default``).
    Action: run only C613.
    Assertion: one WARNING located at ``groups.default.max_resident``.
    """
    register(TSWAP_C613_RULE)
    tools = {"solo": _tool("solo")}
    raw = {
        "tools": {"solo": {}},
        "groups": {"default": {"max_resident": 4, "eviction": "lru"}},
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C613"}
    (d,) = by_code["TSWAP-C613"]
    assert "default" in d.message
    assert d.location.yaml_path == "groups.default.max_resident"


def test_c610_and_c613_never_fire_for_the_same_group() -> None:
    """No single group ever produces BOTH C610 and C613.

    Item 6: mutually exclusive by construction — one needs
    ``max_resident < count``, the other ``max_resident > count``, and
    ``==`` fires neither; no suppression logic is needed, and this test
    pins that a group never carries both codes.

    Arrangement: ``g1`` (3 keep-warm members, ``max_resident: 2`` —
    C610 shape) and ``g2`` (1 member, ``max_resident: 6`` — C613
    shape); all three C61x rules registered.
    Action: run ``validate_config`` once.
    Assertion: C610 names only ``g1`` (not ``g2``); C613 names only
    ``g2`` (not ``g1``) — the two named-group sets are disjoint.
    """
    for rule in (TSWAP_C610_RULE, TSWAP_C612_RULE, TSWAP_C613_RULE):
        register(rule)
    tools = {
        "t1": _tool("t1", values={"group": "g1", "keep_warm": True}),
        "t2": _tool("t2", values={"group": "g1", "keep_warm": True}),
        "t3": _tool("t3", values={"group": "g1", "keep_warm": True}),
        "t4": _tool("t4", values={"group": "g2"}),
    }
    raw = {
        "tools": {
            "t1": {"group": "g1", "keep_warm": True},
            "t2": {"group": "g1", "keep_warm": True},
            "t3": {"group": "g1", "keep_warm": True},
            "t4": {"group": "g2"},
        },
        "groups": {
            "g1": {"max_resident": 2, "eviction": "lru"},
            "g2": {"max_resident": 6, "eviction": "lru"},
        },
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C610", "TSWAP-C613"}
    (c610,) = by_code["TSWAP-C610"]
    (c613,) = by_code["TSWAP-C613"]
    assert "g1" in c610.message
    assert "g2" not in c610.message
    assert "g2" in c613.message
    assert "g1" not in c613.message


def test_c613_location_line_is_none_when_line_for_answers_none() -> None:
    """A ``None``-returning ``line_for`` surfaces ``line=None`` on C613.

    Arrangement: the C613-firing group; the default ``None``-returning
    ``line_for``.
    Action: run only C613.
    Assertion: the ``yaml_path`` is still ``groups.gpu0.max_resident``
    and ``line is None``, equal to ``config.line_for`` of the same
    path.
    """
    register(TSWAP_C613_RULE)
    tools = {
        "t1": _tool("t1", values={"group": "gpu0"}),
        "t2": _tool("t2", values={"group": "gpu0"}),
    }
    raw = {
        "tools": {"t1": {"group": "gpu0"}, "t2": {"group": "gpu0"}},
        "groups": {"gpu0": {"max_resident": 4, "eviction": "lru"}},
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert d.code == "TSWAP-C613"
    assert d.location.yaml_path == "groups.gpu0.max_resident"
    assert d.location.line is None
    assert d.location.line == cfg.line_for(d.location.yaml_path)


# ---------------------------------------------------------------------------
# 5. Rule objects, the mechanism constant, and BUILTIN_RULES (items 0, 4, 9)
# ---------------------------------------------------------------------------


def test_c61x_rule_objects_carry_expected_ids_severities_and_remedies() -> None:
    """Each C61x rule carries its id, WARNING severity, non-empty remedy.

    Item 8: C610 WARNING, C612 WARNING, C613 WARNING — behaviour 19 is
    the only rule group in M1 that is entirely warnings, and every
    remedy is non-empty.  Item 0 (A20): ``TSWAP-C611`` is not allocated
    anywhere — the withdrawal is load-bearing and must stay withdrawn,
    so its absence from ``BUILTIN_RULES`` is pinned here.

    Arrangement: the three rule constants imported from ``validate``.
    Action: read back ``id``, ``severity`` and ``remedy``; scan
    ``BUILTIN_RULES`` for the withdrawn code.
    Assertion: ids in code order (with the deliberate C610 → C612 gap);
    all WARNING; every remedy a non-empty, non-whitespace string; no
    rule in ``BUILTIN_RULES`` carries ``TSWAP-C611``.
    """
    rules = (TSWAP_C610_RULE, TSWAP_C612_RULE, TSWAP_C613_RULE)

    assert [rule.id for rule in rules] == list(_BEHAVIOUR_19_IDS)
    assert [rule.severity for rule in rules] == [
        Severity.WARNING,
        Severity.WARNING,
        Severity.WARNING,
    ]
    for rule in rules:
        assert isinstance(rule.remedy, str)
        assert rule.remedy.strip()
    assert "TSWAP-C611" not in [rule.id for rule in BUILTIN_RULES]


def test_c610_mechanism_constant_is_the_pinned_sentence() -> None:
    """``_C610_MECHANISM`` holds the verbatim mechanism sentence (item 4).

    The sentence explains WHY the symptom (tools restarting forever)
    does not point at the cause, and the test imports the constant and
    asserts it rather than re-typing it (the ``_URLS_REASON`` /
    ``_C300_WHY`` precedent).  Note the deliberate wording: "this
    group", not the spec's "the group" — the message names a specific
    group.

    Arrangement: the module constant itself.
    Action: compare against the pinned sentence.
    Assertion: verbatim equality.
    """
    assert _C610_MECHANISM == (
        "keep_warm exempts a tool from TTL but not from eviction, so "
        "this group can never satisfy all its members"
    )


def test_c61x_rules_are_appended_to_builtin_rules_after_behaviour_18() -> None:
    """The three C61x ids are appended to ``BUILTIN_RULES`` in code order.

    Item 9: appended after behaviour 18's four — 41 landed rules in
    total — anchored by INDEX, never by tail slice or total count
    (mirrors behaviour 18's index-anchored append test, item 10).

    Arrangement: the ``BUILTIN_RULES`` tuple.
    Action: locate behaviour 18's first id, check the six preceding
    block lengths, slice forward by three.
    Assertion: the slice is exactly the three C61x ids in code order,
    and each element IS the corresponding module constant (identity).
    """
    ids = [rule.id for rule in BUILTIN_RULES]
    preceding = (
        len(_BEHAVIOUR_12_IDS)
        + len(_BEHAVIOUR_13_IDS)
        + len(_BEHAVIOUR_14_IDS)
        + len(_BEHAVIOUR_15_IDS)
        + len(_BEHAVIOUR_16_IDS)
        + len(_BEHAVIOUR_17_IDS)
    )
    first_c600 = ids.index(_BEHAVIOUR_18_IDS[0])

    assert first_c600 == preceding
    base = first_c600 + len(_BEHAVIOUR_18_IDS)
    assert ids[base : base + 3] == list(_BEHAVIOUR_19_IDS)
    assert BUILTIN_RULES[base] is TSWAP_C610_RULE
    assert BUILTIN_RULES[base + 1] is TSWAP_C612_RULE
    assert BUILTIN_RULES[base + 2] is TSWAP_C613_RULE


# ---------------------------------------------------------------------------
# 6. Cross-rule pins (only-own-codes, multiple-in-one-report)
# ---------------------------------------------------------------------------


def test_only_own_codes_fixture_carries_exactly_one_c613() -> None:
    """The only-own-codes pin: the fixture's ONLY finding is its C613.

    One group, 2 members (one keep-warm, one not), ``max_resident: 4``,
    no shared devices anywhere: C610 is silent (not EVERY member
    keep-warm), C612 is silent (no shared device index), and C613
    fires (4 > 2) — so the report carries EXACTLY one diagnostic,
    ``TSWAP-C613``: the rules' output is exactly their own findings,
    with no C610, no C612 and no internal C999.

    Arrangement: that fixture; all three C61x rules registered.
    Action: run ``validate_config`` once.
    Assertion: exactly one diagnostic, code ``TSWAP-C613``.
    """
    for rule in (TSWAP_C610_RULE, TSWAP_C612_RULE, TSWAP_C613_RULE):
        register(rule)
    tools = {
        "t1": _tool("t1", values={"group": "g1", "keep_warm": True}),
        "t2": _tool("t2", values={"group": "g1", "keep_warm": False}),
    }
    raw = {
        "tools": {
            "t1": {"group": "g1", "keep_warm": True},
            "t2": {"group": "g1", "keep_warm": False},
        },
        "groups": {"g1": {"max_resident": 4, "eviction": "lru"}},
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    assert len(report.diagnostics) == 1
    (d,) = report.diagnostics
    assert d.code == "TSWAP-C613"
    assert "TSWAP-C610" not in {x.code for x in report.diagnostics}
    assert "TSWAP-C612" not in {x.code for x in report.diagnostics}
    assert "TSWAP-C999" not in {x.code for x in report.diagnostics}


def test_starvation_findings_are_all_reported_in_one_pass() -> None:
    """C610 + C612 + C613 all fire in one report, at their pinned locations.

    The multiple-in-one-report pin: ``g1`` (3 keep-warm members,
    ``max_resident: 2``, ``devices: [0]`` → C610) and ``g2`` (1 member,
    ``max_resident: 6``, ``devices: [0]`` → C613) share device 0 with a
    combined capacity of 8 > 6 (→ C612 naming both groups) — nothing
    suppresses any of the three findings.

    Arrangement: that fixture; all three C61x rules registered.
    Action: run ``validate_config`` once.
    Assertion: exactly one diagnostic of EACH code; C610 at
    ``groups.g1.max_resident`` naming ``g1``; C612 at the bare
    ``groups`` block naming BOTH groups and device ``0``; C613 at
    ``groups.g2.max_resident`` naming ``g2``; no C999 (no rule
    crashed).
    """
    for rule in (TSWAP_C610_RULE, TSWAP_C612_RULE, TSWAP_C613_RULE):
        register(rule)
    tools = {
        "t1": _tool("t1", values={"group": "g1", "keep_warm": True}),
        "t2": _tool("t2", values={"group": "g1", "keep_warm": True}),
        "t3": _tool("t3", values={"group": "g1", "keep_warm": True}),
        "t4": _tool("t4", values={"group": "g2", "keep_warm": True}),
    }
    raw = {
        "tools": {
            "t1": {"group": "g1", "keep_warm": True},
            "t2": {"group": "g1", "keep_warm": True},
            "t3": {"group": "g1", "keep_warm": True},
            "t4": {"group": "g2", "keep_warm": True},
        },
        "groups": {
            "g1": {"max_resident": 2, "eviction": "lru", "devices": [0]},
            "g2": {"max_resident": 6, "eviction": "lru", "devices": [0]},
        },
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C610", "TSWAP-C612", "TSWAP-C613"}
    assert all(len(diags) == 1 for diags in by_code.values())
    (c610,) = by_code["TSWAP-C610"]
    (c612,) = by_code["TSWAP-C612"]
    (c613,) = by_code["TSWAP-C613"]
    assert "g1" in c610.message
    assert c610.location.yaml_path == "groups.g1.max_resident"
    assert "g1" in c612.message
    assert "g2" in c612.message
    assert "device 0" in c612.message
    assert c612.location.yaml_path == "groups"
    assert "g2" in c613.message
    assert c613.location.yaml_path == "groups.g2.max_resident"

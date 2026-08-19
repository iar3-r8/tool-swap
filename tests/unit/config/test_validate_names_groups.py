"""Tests for M1 behaviour 12 — names, duplicates, and group references.

See ``plans/m1-configuration.md`` §1, behaviour 12 (lines 210-221), and the
§6 rule → behaviour map (lines 445-467): §6 rule 2 (name charset; no
duplicates) and §6 rule 3 (group exists; ``max_resident >= 1``).

This file is the RED step: the behaviour-12 rules and the
``effective_groups`` helper do not exist yet in
``src/tool_swap/config/validate.py`` (behaviour 11 shipped the empty
registry skeleton only), so this module fails collection with a single clean
``ImportError`` naming exactly one missing name:

    ImportError: cannot import name 'TSWAP_C210_RULE'
        from 'tool_swap.config.validate'

(``TSWAP_C210_RULE`` is the first missing name in the import list; Python
reports the first one it fails on.)  Every test body below pins a concrete
behaviour the GREEN step must satisfy, so the assertions — not just the
import — are the contract.

Pinned public API (the names the GREEN step must add to ``validate.py``):

- ``TSWAP_C210_RULE`` … ``TSWAP_C223_RULE`` — module-level ``Rule``
  constants with ids ``TSWAP-C210`` … ``TSWAP-C223`` (``TSWAP-C223`` is
  WARNING, the rest ERROR).  They are aggregated in the
  ``BUILTIN_RULES`` tuple and registered by the explicit, idempotent
  ``register_builtin_rules()`` entry point (called once by the CLI,
  behaviour 21) — importing ``validate.py`` registers nothing
  ("Registration mechanism — DECIDED", 2026-08-18; no reload-based test).
- ``effective_groups(raw: dict) -> dict[str, dict]`` — pure helper: when
  ``raw`` has NO ``"groups"`` key at all it returns the synthesized
  ``{"default": {"max_resident": 4, "eviction": "lru"}}``; when ``"groups"``
  IS present it returns that block as-is (deep-copied; the input is
  untouched) and NEVER adds a ``"default"`` into a hand-written block —
  silently synthesising there would hide a typo (plan line 219).

Location contract: every diagnostic carries
``Location(file=str(config.path), yaml_path=<dotted path>,
line=config.line_for(<dotted path>))`` — pinned per code (``tools.<name>``
for C210, ``groups.<name>.max_resident`` for C221, ``groups.<name>.eviction``
for C222); a ``line_for`` returning ``None`` must surface ``line=None``.

Conventions mirror ``tests/unit/config/test_validate_registry.py``: pytest,
AAA, snake_case, Google docstrings, an autouse fixture calling
``unregister_all()`` before AND after every test (the registry is shared
module state), and fakes built directly —
``ResolvedTool(values={only the keys the rule reads}, origins=OriginMap(),
diagnostics=[])``.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest
from tool_swap.config.errors import Diagnostic, Severity
from tool_swap.config.origin import OriginMap
from tool_swap.config.resolver import ResolvedTool
from tool_swap.config.validate import (  # noqa: E501  (names absent in RED step)
    TSWAP_C210_RULE,
    TSWAP_C211_RULE,
    TSWAP_C220_RULE,
    TSWAP_C221_RULE,
    TSWAP_C222_RULE,
    TSWAP_C223_RULE,
    effective_groups,
    register,
    register_builtin_rules,
    registered_rule_ids,
    unregister_all,
    validate_config,
)

# ---------------------------------------------------------------------------
# Constants and fakes
# ---------------------------------------------------------------------------

#: The six behaviour-12 rule ids (§6 rules 2 and 3).
_BEHAVIOUR_12_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C210",
    "TSWAP-C211",
    "TSWAP-C220",
    "TSWAP-C221",
    "TSWAP-C222",
    "TSWAP-C223",
)

#: Every builtin rule id landed so far, in code order — the six
#: behaviour-12 ids plus behaviour 13's four (C300-C303; plan line 437:
#: "appended to ``BUILTIN_RULES`` in code order").  Mirrors
#: ``_EXPECTED_BUILTIN_IDS`` in ``test_validate_registry_builtins.py``
#: (behaviour 11a): BEHAVIOURS 14-19 EXTEND THIS CONSTANT FURTHER — add
#: each behaviour's codes here, in code order, when that behaviour's
#: rules land in ``BUILTIN_RULES``, so the next extension is one place.
_LANDED_BUILTIN_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C210",
    "TSWAP-C211",
    "TSWAP-C220",
    "TSWAP-C221",
    "TSWAP-C222",
    "TSWAP-C223",
    # Behaviour 13 (D19 mandatory descriptions) extends the set here.
    "TSWAP-C300",
    "TSWAP-C301",
    "TSWAP-C302",
    "TSWAP-C303",
    # Behaviour 14 (withdrawn/reserved keys) extends the set here.
    "TSWAP-C400",
    "TSWAP-C401",
    "TSWAP-C402",
    "TSWAP-C403",
    "TSWAP-C404",
    "TSWAP-C405",
    # Behaviour 15 (image source, handler, file existence) extends the
    # set here.
    "TSWAP-C510",
    "TSWAP-C511",
    "TSWAP-C512",
    "TSWAP-C513",
    "TSWAP-C514",
    "TSWAP-C515",
    "TSWAP-C516",
)

#: The pinned C210 reason phrase (plan line 214).
_URLS_REASON: Final[str] = "used in URLs, container names and log directory names"

#: The built-in default group the synthesised block must carry (plan line 219).
_SYNTHESISED_DEFAULT: Final[dict[str, int | str]] = {
    "max_resident": 4,
    "eviction": "lru",
}


def _tool(name: str, values: dict[str, object] | None = None) -> ResolvedTool:
    """Build a minimal frozen ``ResolvedTool``; only the given keys are set.

    Args:
        name: the tool name (used as both the ``tools`` dict key and the
            ``ResolvedTool.name`` in every fixture, so the two namespaces
            agree).
        values: flat field name -> value; defaults to ``{}`` (a tool with no
            ``group`` entry, which resolves to ``"default"`` per the built-in
            defaults).

    Returns:
        A ``ResolvedTool`` with ``origins=OriginMap()`` and no diagnostics.
    """
    return ResolvedTool(
        name=name,
        values=values if values is not None else {},
        origins=OriginMap(),
        diagnostics=[],
    )


def _config(
    tools: dict[str, ResolvedTool],
    raw: dict[str, object],
    line_for: Callable[[str], int | None] | None = None,
    path: Path | None = None,
) -> "object":
    """Build a ``ValidatedConfig`` fake (no loader, no filesystem).

    Args:
        tools: name -> ``ResolvedTool`` (positional field).
        raw: the raw root YAML mapping (positional field).
        line_for: dotted YAML path -> 1-based line or ``None`` (keyword-only);
            defaults to a ``None``-returning mapping.
        path: the config file path (keyword-only); defaults to
            ``Path("tools.yaml")``.

    Returns:
        The frozen ``ValidatedConfig`` (imported by the GREEN step; typed
        loosely here because the name is not yet importable in the RED step).
    """
    from tool_swap.config.validate import ValidatedConfig

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


def _valid_group_block() -> dict[str, dict[str, object]]:
    """Return a fully valid ``groups:`` block (max_resident >= 1, lru)."""
    return {
        "default": {"max_resident": 4, "eviction": "lru"},
        "gpu0": {"max_resident": 2, "eviction": "lru"},
    }


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Start and end every test with an empty, known registry.

    The registry is shared module state: this behaviour's rules register at
    import time, so each test must not depend on — and must not leak —
    registration state (same isolation contract as the behaviour-11 file).
    """
    unregister_all()
    try:
        yield
    finally:
        unregister_all()


# ---------------------------------------------------------------------------
# 1. The effective_groups helper (plan line 219, implicit default group)
# ---------------------------------------------------------------------------


def test_effective_groups_synthesises_default_when_groups_key_absent() -> None:
    """No ``groups:`` key at all -> a synthesized ``default`` group appears.

    Arrangement: a raw root mapping with tools but no ``groups`` key.
    Action: call ``effective_groups(raw)``.
    Assertion: the result is exactly the synthesized block
    (``max_resident: 4``, ``eviction: "lru"``) and the input is untouched —
    no ``groups`` key is added to it (pure helper).
    """
    raw: dict[str, object] = {"tools": {"solo": {}}}
    before = copy.deepcopy(raw)

    result = effective_groups(raw)

    assert result == {"default": dict(_SYNTHESISED_DEFAULT)}
    assert raw == before
    assert "groups" not in raw


def test_effective_groups_returns_groups_block_unchanged_and_deep_copied() -> None:
    """A present ``groups:`` block is returned as-is, deep-copied, no synthesis.

    Arrangement: two raw mappings — one whose ``groups`` block contains a
    ``default`` entry, one whose hand-written block omits it.
    Action: call ``effective_groups`` on each; then mutate the results.
    Assertion: each result equals its input block; mutating a result never
    affects the input; and NO ``default`` is ever added into a hand-written
    block (silently synthesising there would hide a typo, plan line 219).
    """
    with_default = {"groups": {"default": {"max_resident": 5}, "g1": {}}}
    without_default = {"groups": {"g1": {"max_resident": 2}}}
    before_with = copy.deepcopy(with_default)
    before_without = copy.deepcopy(without_default)

    result_with = effective_groups(with_default)
    result_without = effective_groups(without_default)

    assert result_with == before_with["groups"]
    assert result_without == before_without["groups"]
    assert "default" not in result_without  # not synthesized into hand-written block

    result_with["g1"]["max_resident"] = 999  # type: ignore[index]
    result_without["g1"]["max_resident"] = 999  # type: ignore[index]
    assert with_default == before_with
    assert without_default == before_without


# ---------------------------------------------------------------------------
# 2. Registration contract (rules land in validate.py and self-register)
# ---------------------------------------------------------------------------


def test_register_builtin_rules_registers_every_builtin_rule() -> None:
    """The central entry point registers every landed builtin rule, none dropped.

    This proves the entry point registers EVERY rule that has landed in
    ``BUILTIN_RULES`` — the six behaviour-12 rules plus behaviour 13's four
    C3xx rules (plan line 437: "appended to ``BUILTIN_RULES`` in code
    order") — in code order, so no rule is silently dropped.  The durable
    intent is "every landed builtin, none dropped"; the specific count was
    behaviour-snapshot-specific and is extended per behaviour.  It proves
    the same thing the retired import-time reload test reached for — the
    builtin rules are reachable from a central entry point — without
    module reloading and with no dependence on test collection order.  The
    reload form was superseded by the "Registration mechanism — DECIDED"
    (2026-08-18) mechanism: the rules are module-level constants aggregated
    in ``BUILTIN_RULES`` and registered by the explicit, idempotent
    ``register_builtin_rules()``.

    The expected list is the module-top constant ``_LANDED_BUILTIN_IDS``
    (mirroring ``_EXPECTED_BUILTIN_IDS`` in
    ``test_validate_registry_builtins.py``); behaviours 14-19 extend that
    constant as their rules land, so the next extension is one place.

    Arrangement: the registry cleared by the autouse fixture, with no
    builtin ids registered.
    Action: call ``register_builtin_rules()``.
    Assertion: ``registered_rule_ids()`` equals the full landed set in
    code order.
    """
    assert registered_rule_ids() == []

    register_builtin_rules()

    assert registered_rule_ids() == list(_LANDED_BUILTIN_IDS)


def test_behaviour_12_rule_objects_carry_expected_ids_and_severities() -> None:
    """Each rule instance carries its id, severity, and a non-empty remedy.

    Arrangement: the six rule objects imported from ``validate``.
    Action: read back ``id``, ``severity`` and ``remedy``.
    Assertion: ids are ``TSWAP-C210``…``TSWAP-C223`` in that order; only
    ``TSWAP-C223`` is WARNING (plan line 220: a warning); every remedy is a
    non-empty string.
    """
    rules = (
        TSWAP_C210_RULE,
        TSWAP_C211_RULE,
        TSWAP_C220_RULE,
        TSWAP_C221_RULE,
        TSWAP_C222_RULE,
        TSWAP_C223_RULE,
    )

    assert [rule.id for rule in rules] == list(_BEHAVIOUR_12_IDS)
    assert [rule.severity for rule in rules] == [
        Severity.ERROR,
        Severity.ERROR,
        Severity.ERROR,
        Severity.ERROR,
        Severity.ERROR,
        Severity.WARNING,
    ]
    for rule in rules:
        assert isinstance(rule.remedy, str)
        assert rule.remedy.strip() != ""


# ---------------------------------------------------------------------------
# 3. TSWAP-C210 — tool name charset (§6 rule 2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "offending"),
    [
        ("Tool_A", {"T", "A"}),  # uppercase letters
        ("_leading", {"_"}),  # leading underscore
        ("has space", {" "}),  # space
        ("has.dot", {"."}),  # dot
        ("ünïcode", {"ü", "ï"}),  # non-ASCII
        ("", set()),  # empty name
    ],
)
def test_c210_flags_invalid_tool_name(name: str, offending: set[str]) -> None:
    """A name outside ``^[a-z0-9][a-z0-9_-]*$`` is exactly one C210 error.

    Arrangement: one tool whose (key and) resolved name violates the charset,
    no other problems (no ``groups:`` key, so the implicit default applies).
    Action: run only ``TSWAP_C210_RULE`` via ``validate_config``.
    Assertion: exactly one diagnostic, code ``TSWAP-C210``, ``ERROR``; the
    message names the tool (when non-empty), every offending character, and
    the pinned reason phrase; the location is
    ``Location(file=str(config.path), yaml_path="tools.<name>",
    line=line_for("tools.<name>"))``; the remedy is non-empty.
    """
    register(TSWAP_C210_RULE)
    cfg = _config(tools={name: _tool(name)}, raw={"tools": {name: {}}})

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C210"}
    (d,) = by_code["TSWAP-C210"]
    assert d.severity is Severity.ERROR
    if name:
        assert name in d.message
    for char in offending:
        assert char in d.message
    assert _URLS_REASON in d.message
    assert d.location.file == "tools.yaml"
    assert d.location.yaml_path == f"tools.{name}"
    assert d.location.line is None  # default line_for returns None
    assert d.remedy.strip() != ""


def test_c210_location_uses_line_for_and_config_path() -> None:
    """The C210 location consults ``line_for`` and ``config.path``.

    Arrangement: a config with a non-default ``path`` and a ``line_for``
    returning a fixed line for any dotted path.
    Action: run only ``TSWAP_C210_RULE``.
    Assertion: the diagnostic's ``line`` is the value ``line_for`` returned
    (the dotted path was consulted) and ``file`` is ``str(config.path)`` —
    not a hardcoded file name.
    """
    register(TSWAP_C210_RULE)
    cfg = _config(
        tools={"Bad": _tool("Bad")},
        raw={"tools": {"Bad": {}}},
        line_for=lambda _p: 42,
        path=Path("my-config.yaml"),
    )

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert d.code == "TSWAP-C210"
    assert d.location.file == "my-config.yaml"
    assert d.location.line == 42


# ---------------------------------------------------------------------------
# 4. TSWAP-C211 — duplicate tool names (§6 rule 2)
# ---------------------------------------------------------------------------


def test_c211_flags_duplicate_effective_name_with_single_diagnostic() -> None:
    """Two entries resolving to the same effective name -> exactly one C211.

    This is the behaviour-12 form of a duplicate (across layers / after
    ``tool.yaml`` name resolution), distinct from behaviour 6's
    duplicate-YAML-key loader error: two ``tools`` entries whose
    ``tool.yaml`` ``name:`` field resolves to the SAME effective name.

    Arrangement: raw ``tools`` with two entries ("first", "second") both
    declaring ``name: shared``; the resolved ``tools`` dict holds both keys,
    each ``ResolvedTool.name`` equal to ``"shared"``.
    Action: run only ``TSWAP_C211_RULE``.
    Assertion: exactly one diagnostic, code ``TSWAP-C211``, ``ERROR``, whose
    message names BOTH spellings/locations ("first" and "second"); location
    file is ``str(config.path)``; remedy non-empty.
    """
    register(TSWAP_C211_RULE)
    tools = {
        "first": _tool("shared"),
        "second": _tool("shared"),
    }
    raw = {"tools": {"first": {"name": "shared"}, "second": {"name": "shared"}}}
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C211"}
    (d,) = by_code["TSWAP-C211"]
    assert d.severity is Severity.ERROR
    assert "first" in d.message
    assert "second" in d.message
    assert d.location.file == "tools.yaml"
    assert d.remedy.strip() != ""


def test_c211_does_not_flag_distinct_tool_names() -> None:
    """Distinct effective names are not duplicates — no C211.

    Arrangement: two tools with different keys AND different effective names.
    Action: run only ``TSWAP_C211_RULE``.
    Assertion: an empty report (no false positive).
    """
    register(TSWAP_C211_RULE)
    tools = {"alpha": _tool("alpha"), "beta": _tool("beta")}
    raw = {"tools": {"alpha": {}, "beta": {}}}
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# 5. TSWAP-C220 — tool references a group absent from groups: (§6 rule 3)
# ---------------------------------------------------------------------------


def test_c220_flags_missing_group_naming_nearest_and_all_defined() -> None:
    """A tool referencing an undefined group -> C220 with nearest + full list.

    Arrangement: groups ``default`` and ``gpu0`` defined; tool ``alpha``
    references the misspelled group ``defualt`` (nearest existing group per
    ``suggest.nearest_alternative`` is ``default``).
    Action: run only ``TSWAP_C220_RULE``.
    Assertion: exactly one diagnostic, code ``TSWAP-C220``, ``ERROR``; the
    message names the missing group (``defualt``), the tool (``alpha``), the
    nearest existing group (``default``), and every defined group
    (``default`` and ``gpu0``); remedy non-empty and mentions the group.
    """
    register(TSWAP_C220_RULE)
    tools = {"alpha": _tool("alpha", values={"group": "defualt"})}
    raw = {"tools": {"alpha": {"group": "defualt"}}, "groups": _valid_group_block()}
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C220"}
    (d,) = by_code["TSWAP-C220"]
    assert d.severity is Severity.ERROR
    assert "defualt" in d.message
    assert "alpha" in d.message
    assert "default" in d.message  # nearest existing group
    assert "gpu0" in d.message  # full list of defined groups
    assert "group" in d.remedy.lower()


def test_c220_flags_missing_group_when_groups_key_absent() -> None:
    """No ``groups:`` key + an explicitly named group -> still C220.

    The synthesized default satisfies only tools that resolve to ``default``;
    a tool explicitly naming another group is a dangling reference like any
    other (no silent synthesis into an explicit reference).

    Arrangement: no ``groups:`` key; tool ``alpha`` references ``gpu0``.
    Action: run only ``TSWAP_C220_RULE``.
    Assertion: exactly one C220 naming the group (``gpu0``) and the tool
    (``alpha``).
    """
    register(TSWAP_C220_RULE)
    tools = {"alpha": _tool("alpha", values={"group": "gpu0"})}
    raw = {"tools": {"alpha": {"group": "gpu0"}}}
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C220"}
    (d,) = by_code["TSWAP-C220"]
    assert "gpu0" in d.message
    assert "alpha" in d.message


# ---------------------------------------------------------------------------
# 6. TSWAP-C221 — groups.*.max_resident < 1 (§6 rule 3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [0, -1])
def test_c221_flags_max_resident_below_one(value: int) -> None:
    """``max_resident < 1`` on a group -> C221 naming the group and the value.

    Arrangement: group ``g1`` with ``max_resident = value`` (0 and -1), a
    tool referencing it, and a ``line_for`` returning a fixed line.
    Action: run only ``TSWAP_C221_RULE``.
    Assertion: exactly one diagnostic, code ``TSWAP-C221``, ``ERROR``; the
    message names the group (``g1``) and the value; the location is
    ``groups.g1.max_resident`` with the ``line_for`` line; remedy names
    ``max_resident``.
    """
    register(TSWAP_C221_RULE)
    tools = {"alpha": _tool("alpha", values={"group": "g1"})}
    raw = {
        "tools": {"alpha": {"group": "g1"}},
        "groups": {"g1": {"max_resident": value, "eviction": "lru"}},
    }
    cfg = _config(tools=tools, raw=raw, line_for=lambda _p: 7)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C221"}
    (d,) = by_code["TSWAP-C221"]
    assert d.severity is Severity.ERROR
    assert "g1" in d.message
    assert str(value) in d.message
    assert d.location.file == "tools.yaml"
    assert d.location.yaml_path == "groups.g1.max_resident"
    assert d.location.line == 7
    assert "max_resident" in d.remedy


def test_c221_accepts_max_resident_of_one() -> None:
    """``max_resident: 1`` is the valid boundary — no C221.

    Arrangement: group ``g1`` with ``max_resident: 1`` and a tool using it.
    Action: run only ``TSWAP_C221_RULE``.
    Assertion: an empty report (the rule fires on ``< 1``, not ``<= 1``).
    """
    register(TSWAP_C221_RULE)
    tools = {"alpha": _tool("alpha", values={"group": "g1"})}
    raw = {
        "tools": {"alpha": {"group": "g1"}},
        "groups": {"g1": {"max_resident": 1, "eviction": "lru"}},
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# 7. TSWAP-C222 — groups.*.eviction outside {lru, lifo, none} (§6 rule 3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["fifo", "FIFO"])
def test_c222_flags_eviction_outside_valid_set(value: str) -> None:
    """An unknown ``eviction`` value -> C222 listing the valid values.

    Arrangement: group ``g1`` with ``eviction = value`` (case-sensitive: even
    ``FIFO``/``LRU``-style variants are outside the set).
    Action: run only ``TSWAP_C222_RULE``.
    Assertion: exactly one diagnostic, code ``TSWAP-C222``, ``ERROR``; the
    message names the group (``g1``) and the offending value, and lists the
    valid values (``lru``, ``lifo``, ``none``); the location is
    ``groups.g1.eviction``; remedy names ``eviction``.
    """
    register(TSWAP_C222_RULE)
    tools = {"alpha": _tool("alpha", values={"group": "g1"})}
    raw = {
        "tools": {"alpha": {"group": "g1"}},
        "groups": {"g1": {"max_resident": 2, "eviction": value}},
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C222"}
    (d,) = by_code["TSWAP-C222"]
    assert d.severity is Severity.ERROR
    assert "g1" in d.message
    assert value in d.message
    assert "lru" in d.message
    assert "lifo" in d.message
    assert "none" in d.message
    assert d.location.file == "tools.yaml"
    assert d.location.yaml_path == "groups.g1.eviction"
    assert d.location.line is None
    assert "eviction" in d.remedy


# ---------------------------------------------------------------------------
# 8. TSWAP-C223 — group defined but referenced by nothing (plan line 220)
# ---------------------------------------------------------------------------


def test_c223_warns_on_group_referenced_by_no_tool() -> None:
    """A group no tool references -> one C223 WARNING naming the group.

    A tool "references" a group when its resolved ``group`` value equals the
    group name, or when it has no ``group`` entry at all (meaning
    ``default``).

    Arrangement: groups ``default`` and ``orphan``; one tool with no
    ``group`` entry (so it references ``default`` only).
    Action: run only ``TSWAP_C223_RULE``.
    Assertion: exactly one diagnostic, code ``TSWAP-C223``, severity
    ``WARNING``; the message names ``orphan`` (and not ``default``); remedy
    non-empty and mentions the group.
    """
    register(TSWAP_C223_RULE)
    tools = {"alpha": _tool("alpha")}  # resolves to "default"
    raw = {"tools": {"alpha": {}}, "groups": _valid_group_block() | {"orphan": {"max_resident": 2, "eviction": "lru"}}}

    report = validate_config(_config(tools=tools, raw=raw))

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C223"}
    (d,) = by_code["TSWAP-C223"]
    assert d.severity is Severity.WARNING
    assert "orphan" in d.message
    assert "group" in d.remedy.lower()


def test_c223_is_silent_when_every_defined_group_is_referenced() -> None:
    """Every defined group referenced -> no C223.

    Arrangement: groups ``default`` and ``gpu0``; one tool resolving to
    ``default`` (no ``group`` entry) and one explicitly on ``gpu0``.
    Action: run only ``TSWAP_C223_RULE``.
    Assertion: an empty report.
    """
    register(TSWAP_C223_RULE)
    tools = {
        "alpha": _tool("alpha"),  # implicit "default"
        "beta": _tool("beta", values={"group": "gpu0"}),
    }
    raw = {
        "tools": {"alpha": {}, "beta": {"group": "gpu0"}},
        "groups": _valid_group_block(),
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# 9. The implicit default group end-to-end (plan line 219)
# ---------------------------------------------------------------------------


def test_config_without_groups_block_is_clean_for_implicit_default() -> None:
    """The five-line config works: no ``groups:`` key, no diagnostics.

    A tool with no ``group`` entry resolves to ``default``; with no
    ``groups:`` key at all the synthesized default (``max_resident: 4``)
    satisfies it, so NONE of the six behaviour-12 rules fires.

    Arrangement: one tool, no ``group`` entry, no ``groups:`` key; all six
    rules registered.
    Action: run ``validate_config``.
    Assertion: an ok, empty report (no C210-C223 diagnostics at all).
    """
    for rule in (
        TSWAP_C210_RULE,
        TSWAP_C211_RULE,
        TSWAP_C220_RULE,
        TSWAP_C221_RULE,
        TSWAP_C222_RULE,
        TSWAP_C223_RULE,
    ):
        register(rule)
    tools = {"solo": _tool("solo")}
    raw = {"tools": {"solo": {}}}
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()
    assert report.ok is True


def test_default_omitted_from_explicit_groups_block_is_a_plain_c220() -> None:
    """A hand-written ``groups:`` omitting ``default`` is C220, not synthesized.

    Silently synthesising ``default`` into a hand-written block would hide a
    typo (plan line 219), so a tool that needs the default group while
    ``groups:`` is present without it is a dangling reference like any other.

    Arrangement: ``groups:`` with only ``gpu0``; one tool with no ``group``
    entry (resolves to ``default``); all six rules registered.
    Action: run ``validate_config``.
    Assertion: the ONLY diagnostic is C220, and it names the group
    (``default``) and the tool (``solo``).
    """
    for rule in (
        TSWAP_C210_RULE,
        TSWAP_C211_RULE,
        TSWAP_C220_RULE,
        TSWAP_C221_RULE,
        TSWAP_C222_RULE,
        TSWAP_C223_RULE,
    ):
        register(rule)
    tools = {"solo": _tool("solo")}
    raw = {
        "tools": {"solo": {}},
        "groups": {"gpu0": {"max_resident": 2, "eviction": "lru"}},
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C220"}
    (d,) = by_code["TSWAP-C220"]
    assert "default" in d.message
    assert "solo" in d.message


def test_tool_named_default_is_legal() -> None:
    """A tool NAMED ``default`` is legal (names and groups are separate namespaces).

    Explicit pin so nobody "fixes" it: ``default`` matches the name charset,
    and the tool's own reference to the ``default`` group is satisfied by the
    synthesized block, so nothing fires.

    Arrangement: one tool keyed and named ``default``, no ``groups:`` key;
    all six rules registered.
    Action: run ``validate_config``.
    Assertion: an ok, empty report.
    """
    for rule in (
        TSWAP_C210_RULE,
        TSWAP_C211_RULE,
        TSWAP_C220_RULE,
        TSWAP_C221_RULE,
        TSWAP_C222_RULE,
        TSWAP_C223_RULE,
    ):
        register(rule)
    tools = {"default": _tool("default")}
    raw = {"tools": {"default": {}}}
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    assert report.diagnostics == ()
    assert report.ok is True


# ---------------------------------------------------------------------------
# 10. Rules emit ONLY their own codes (no cross-talk)
# ---------------------------------------------------------------------------


def test_clean_config_produces_no_names_group_diagnostics() -> None:
    """A fully valid name/group config yields no C210-C223 diagnostics.

    Arrangement: valid tool names; every referenced group defined with a
    valid ``max_resident`` (>= 1) and a valid ``eviction``; every defined
    group referenced by at least one tool; all six rules registered.
    Action: run ``validate_config``.
    Assertion: the report carries no behaviour-12 codes at all (the rules are
    silent on a clean config — their output is exactly their own findings).
    """
    for rule in (
        TSWAP_C210_RULE,
        TSWAP_C211_RULE,
        TSWAP_C220_RULE,
        TSWAP_C221_RULE,
        TSWAP_C222_RULE,
        TSWAP_C223_RULE,
    ):
        register(rule)
    tools = {
        "alpha": _tool("alpha", values={"group": "gpu0"}),
        "beta": _tool("beta"),  # implicit "default"
    }
    groups = {
        "default": {"max_resident": 4, "eviction": "lru"},
        "gpu0": {"max_resident": 2, "eviction": "lifo"},
    }
    raw = {
        "tools": {"alpha": {"group": "gpu0"}, "beta": {}},
        "groups": groups,
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    assert not (set(d.code for d in report.diagnostics) & set(_BEHAVIOUR_12_IDS))


# ---------------------------------------------------------------------------
# 11. All findings at once (behaviour 11 contract applied to behaviour 12)
# ---------------------------------------------------------------------------


def test_multiple_names_group_problems_are_all_reported_in_one_pass() -> None:
    """Several distinct name/group problems -> ALL of them in one report.

    Arrangement: a config bundling one trigger per rule — ``Bad_Name``
    (C210), a tool referencing the missing group ``missing`` (C220),
    ``default.max_resident: 0`` (C221), ``gpu0.eviction: fifo`` (C222), and
    the unreferenced group ``orphan`` (C223); all six rules registered.
    Action: run ``validate_config`` once.
    Assertion: the single report contains at least one diagnostic of EACH of
    the five codes (not just the first problem), no internal C999 (no rule
    crashed), and no C211 (there is no duplicate here).
    """
    for rule in (
        TSWAP_C210_RULE,
        TSWAP_C211_RULE,
        TSWAP_C220_RULE,
        TSWAP_C221_RULE,
        TSWAP_C222_RULE,
        TSWAP_C223_RULE,
    ):
        register(rule)
    tools = {
        "Bad_Name": _tool("Bad_Name", values={"group": "gpu0"}),
        "alpha": _tool("alpha", values={"group": "missing"}),
        "beta": _tool("beta"),  # implicit "default"
    }
    raw = {
        "tools": {
            "Bad_Name": {"group": "gpu0"},
            "alpha": {"group": "missing"},
            "beta": {},
        },
        "groups": {
            "default": {"max_resident": 0, "eviction": "lru"},
            "gpu0": {"max_resident": 2, "eviction": "fifo"},
            "orphan": {"max_resident": 1, "eviction": "none"},
        },
    }
    cfg = _config(tools=tools, raw=raw)

    report = validate_config(cfg)

    codes = {d.code for d in report.diagnostics}
    assert {"TSWAP-C210", "TSWAP-C220", "TSWAP-C221", "TSWAP-C222", "TSWAP-C223"} <= codes
    assert "TSWAP-C999" not in codes
    assert "TSWAP-C211" not in codes
    assert len(report.diagnostics) >= 5

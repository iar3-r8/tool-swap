"""Tests for M1 behaviour 13 — D19 mandatory descriptions (§6 rule 6b).

See ``plans/m1-configuration.md`` §1, behaviour 13 (lines 288-298), and its
"Confirmed contract details (2026-08-18)" block (lines 300-437).  This file
is the executable form of that contract: the behaviour-13 rule constants,
the ``MISSING_DESCRIPTION_CODES`` set, the pinned banner text, and the
``downgrade_missing_descriptions`` post-processor do not exist yet in
``src/tool_swap/config/validate.py`` (behaviour 12 shipped the six
C210…C223 rules only), and the ``ResolvedTool`` carrier fields
(``description``, ``inputs``, ``outputs``, ``params``, ``json_schema``) do
not exist yet in ``src/tool_swap/config/resolver.py``.  This module
therefore fails collection with a single clean ``ImportError`` naming
exactly one missing name:

    ImportError: cannot import name 'TSWAP_C300_RULE'
        from 'tool_swap.config.validate'

(``TSWAP_C300_RULE`` is the first missing name in the import list; Python
reports the first one it fails on.)  Every test body below pins a concrete
behaviour the GREEN step must satisfy, so the assertions — not just the
import — are the contract.

Pinned public API (the names the GREEN step must add to ``validate.py``):

- ``TSWAP_C300_RULE``, ``TSWAP_C301_RULE``, ``TSWAP_C302_RULE``,
  ``TSWAP_C303_RULE`` — module-level ``Rule`` constants whose ids are the
  matching codes; ``TSWAP-C302`` is ``Severity.WARNING``, the other three
  ``Severity.ERROR``; every ``remedy`` non-empty; no import-time
  self-registration — all four are appended to ``BUILTIN_RULES`` in code
  order after the six behaviour-12 rules.
- ``MISSING_DESCRIPTION_CODES`` — the set ``{TSWAP-C300, TSWAP-C301,
  TSWAP-C303}`` (NOT C302, which is already a warning).
- ``ALLOW_MISSING_DESCRIPTIONS_BANNER`` — the exact downgrade text.
- ``downgrade_missing_descriptions(report: ConfigReport) ->
  ConfigReport`` — a pure post-processor (mechanism (a), plan line 408):
  rewrites the severity of the missing-description diagnostics to WARNING
  and appends the banner to each of their messages (so it survives
  ``to_json``); touches nothing else; idempotent.

The rules read ONLY the carrier fields on ``ResolvedTool`` (plan block 3);
the tests construct ``ResolvedTool`` with those keyword fields directly.
Blankness: a description counts as missing when it is ``None`` or a
``str`` whose ``.strip()`` is empty; a non-string value (e.g. ``42``)
counts as PRESENT (left to ``TSWAP-C105``); ``"x"`` is present.
Robustness: a non-mapping entry and a non-list block are skipped
silently (no diagnostic, no ``TSWAP-C999``, no crash).  Locations follow
the behaviour-12 form: ``Location(file=str(config.path), yaml_path=<dotted
path>, line=config.line_for(<the same string>))`` — dotted-numeric list
indices, never a hardcoded line number.

Conventions mirror ``tests/unit/config/test_validate_names_groups.py``:
pytest, AAA, snake_case, Google docstrings, an autouse fixture calling
``unregister_all()`` before AND after every test (the registry is shared
module state), and the C3xx rules registered explicitly per test.  No
``importlib.reload`` anywhere.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest
from tool_swap.config.errors import ConfigReport, Diagnostic, Location, Severity
from tool_swap.config.origin import OriginMap
from tool_swap.config.resolver import ResolvedTool, resolve_tool
from tool_swap.config.validate import (  # noqa: E501  (names absent in RED step)
    TSWAP_C300_RULE,
    TSWAP_C301_RULE,
    TSWAP_C302_RULE,
    TSWAP_C303_RULE,
    ALLOW_MISSING_DESCRIPTIONS_BANNER,
    BUILTIN_RULES,
    MISSING_DESCRIPTION_CODES,
    ValidatedConfig,
    downgrade_missing_descriptions,
    register,
    unregister_all,
    validate_config,
)

# ---------------------------------------------------------------------------
# Constants and fakes
# ---------------------------------------------------------------------------

#: The four behaviour-13 rule ids (§6 rule 6b), in code order.
_BEHAVIOUR_13_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C300",
    "TSWAP-C301",
    "TSWAP-C302",
    "TSWAP-C303",
)

#: The pinned C300 WHY phrase (plan line 292).
_WHY_PHRASE: Final[str] = (
    "the description is what an LLM agent reads to decide whether to call this tool"
)


def _tool(
    name: str,
    *,
    description: object = None,
    inputs: object = None,
    outputs: object = None,
    params: object = None,
) -> ResolvedTool:
    """Build a ``ResolvedTool`` carrying behaviour-13's carrier fields.

    Args:
        name: the tool name (used as both the ``tools`` dict key and the
            ``ResolvedTool.name`` in every fixture, so the two namespaces
            agree).
        description: the ``description`` carrier field (``None`` = absent).
        inputs: the ``inputs`` carrier field (``None`` = absent, ``[]`` =
            declared empty; the two stay distinct).
        outputs: the ``outputs`` carrier field.
        params: the ``params`` carrier field.

    Returns:
        A frozen ``ResolvedTool`` with empty ``values`` (the C3xx rules
        read only the carrier fields), ``origins=OriginMap()`` and no
        diagnostics.
    """
    return ResolvedTool(
        name=name,
        values={},
        origins=OriginMap(),
        diagnostics=[],
        description=description,  # type: ignore[arg-type]
        inputs=inputs,  # type: ignore[arg-type]
        outputs=outputs,  # type: ignore[arg-type]
        params=params,  # type: ignore[arg-type]
    )


def _config(
    tools: dict[str, ResolvedTool],
    line_for: Callable[[str], int | None] | None = None,
    path: Path | None = None,
) -> ValidatedConfig:
    """Build a ``ValidatedConfig`` fake (no loader, no filesystem).

    The C3xx rules read only the carrier fields on the tools, so the raw
    block is an inert placeholder.

    Args:
        tools: name -> ``ResolvedTool`` (positional field).
        line_for: dotted YAML path -> 1-based line or ``None``; defaults to
            a ``None``-returning mapping.
        path: the config file path; defaults to ``Path("tools.yaml")``.

    Returns:
        The frozen ``ValidatedConfig``.
    """
    return ValidatedConfig(
        tools=tools,
        raw={"tools": {}},
        line_for=line_for if line_for is not None else (lambda _p: None),
        path=path if path is not None else Path("tools.yaml"),
    )


def _diagnostics_by_code(report: ConfigReport) -> dict[str, list[Diagnostic]]:
    """Group a report's diagnostics by code for set-based assertions.

    Args:
        report: a ``ConfigReport``.

    Returns:
        Code -> the diagnostics carrying that code.
    """
    by_code: dict[str, list[Diagnostic]] = {}
    for d in report.diagnostics:
        by_code.setdefault(d.code, []).append(d)
    return by_code


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Start and end every test with an empty, known registry.

    The registry is shared module state: each test registers exactly the
    C3xx rules it exercises (explicitly, like the behaviour-12 file) and
    must not depend on — and must not leak — registration state.
    """
    unregister_all()
    try:
        yield
    finally:
        unregister_all()


# ---------------------------------------------------------------------------
# 1. The rule objects, the codes set, and the banner text
# ---------------------------------------------------------------------------


def test_rule_objects_carry_expected_ids_and_severities() -> None:
    """Each rule instance carries its id, severity, and a non-empty remedy.

    Arrangement: the four rule objects imported from ``validate``.
    Action: read back ``id``, ``severity`` and ``remedy``.
    Assertion: ids are ``TSWAP-C300``…``TSWAP-C303`` in that order; only
    ``TSWAP-C302`` is WARNING (plan line 294); the other three are ERROR;
    every remedy is a non-empty string.
    """
    rules = (
        TSWAP_C300_RULE,
        TSWAP_C301_RULE,
        TSWAP_C302_RULE,
        TSWAP_C303_RULE,
    )

    assert [rule.id for rule in rules] == list(_BEHAVIOUR_13_IDS)
    assert [rule.severity for rule in rules] == [
        Severity.ERROR,
        Severity.ERROR,
        Severity.WARNING,
        Severity.ERROR,
    ]
    for rule in rules:
        assert isinstance(rule.remedy, str)
        assert rule.remedy.strip() != ""


def test_builtin_rules_append_the_behaviour_13_codes_in_code_order() -> None:
    """The four rules are appended to ``BUILTIN_RULES`` after behaviour 12.

    Plan line 437: all four are appended to ``BUILTIN_RULES`` in code
    order after the six behaviour-12 rules, and their *identity* is what
    ``register_builtin_rules()`` relies on for idempotency — so the tuple
    must hold the very module-level singletons, not equal stand-ins.

    Arrangement: the ``BUILTIN_RULES`` tuple.
    Action: read the trailing ids back; check object identity per rule.
    Assertion: the last four ids are the behaviour-13 codes in code order,
    and each rule constant is an element of the tuple.
    """
    ids = [rule.id for rule in BUILTIN_RULES]

    assert ids[-4:] == list(_BEHAVIOUR_13_IDS)
    for constant in (
        TSWAP_C300_RULE,
        TSWAP_C301_RULE,
        TSWAP_C302_RULE,
        TSWAP_C303_RULE,
    ):
        assert any(rule is constant for rule in BUILTIN_RULES)


def test_missing_description_codes_is_exactly_c300_c301_c303() -> None:
    """``MISSING_DESCRIPTION_CODES`` is exactly the three ERROR codes.

    Plan line 415: the set is ``{TSWAP-C300, TSWAP-C301, TSWAP-C303}``.
    C302 is deliberately EXCLUDED — it is already a warning, and
    appending "downgraded by" to a diagnostic the flag did not change
    would be a lie (plan line 427).

    Arrangement: the module constant.
    Action: compare its contents and membership of C302.
    Assertion: set equality in both directions; C302 absent.
    """
    assert set(MISSING_DESCRIPTION_CODES) == {
        "TSWAP-C300",
        "TSWAP-C301",
        "TSWAP-C303",
    }
    assert "TSWAP-C302" not in MISSING_DESCRIPTION_CODES


def test_allow_missing_descriptions_banner_text_is_pinned() -> None:
    """The banner text is the pinned string, verbatim (plan line 418).

    The banner is part of the diagnostic, so it survives ``--json`` and
    cannot be lost by a caller that only prints diagnostics (plan line
    296); paraphrasing it would break the pin.

    Arrangement: the module constant.
    Action: compare against the pinned text.
    Assertion: exact string equality, and non-empty.
    """
    assert ALLOW_MISSING_DESCRIPTIONS_BANNER == (
        "downgraded by --allow-missing-descriptions; this flag is for local "
        "prototyping and is never permitted in CI"
    )
    assert ALLOW_MISSING_DESCRIPTIONS_BANNER.strip() != ""


# ---------------------------------------------------------------------------
# 2. TSWAP-C300 — the tool's own description (plan lines 292, 297)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blank", [None, "", "   ", "\n"])
def test_c300_flags_missing_or_blank_tool_description(blank: object) -> None:
    """A missing or whitespace-only tool description is exactly one C300.

    Plan line 297: a description of ``"   "`` or ``"\\n"`` counts as
    missing, same as ``None``.

    Arrangement: one tool whose ``description`` carrier field is the
    parametrized blank value; only ``TSWAP_C300_RULE`` registered.
    Action: run ``validate_config``.
    Assertion: exactly one diagnostic, code ``TSWAP-C300``, ERROR; the
    message states the pinned WHY phrase; the remedy names the key to add
    (contains ``"description"``) and is non-empty; the location is
    ``Location(file=str(config.path), yaml_path="tools.t1",
    line=line_for("tools.t1"))`` (None under the default ``line_for``).
    """
    register(TSWAP_C300_RULE)
    cfg = _config(tools={"t1": _tool("t1", description=blank)})

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C300"}
    (d,) = by_code["TSWAP-C300"]
    assert d.severity is Severity.ERROR
    assert _WHY_PHRASE in d.message
    assert "description" in d.remedy
    assert d.remedy.strip() != ""
    assert d.location.file == "tools.yaml"
    assert d.location.yaml_path == "tools.t1"
    assert d.location.line is None  # default line_for returns None


def test_c300_accepts_short_nonblank_description() -> None:
    """A very short description (``"x"``) is accepted (plan line 297).

    We do not invent a length rule the spec does not state.

    Arrangement: one tool with ``description="x"``; only C300 registered.
    Action: run ``validate_config``.
    Assertion: no diagnostics at all.
    """
    register(TSWAP_C300_RULE)
    cfg = _config(tools={"t1": _tool("t1", description="x")})

    report = validate_config(cfg)

    assert report.diagnostics == ()


@pytest.mark.parametrize("line", [42, None])
def test_c300_location_uses_line_for_and_config_path(line: int | None) -> None:
    """The C300 location consults ``line_for`` and ``config.path``.

    Plan line 403: the test asserts ``location.line ==
    config.line_for(location.yaml_path)`` — NEVER a hardcoded line
    number; ``line=None`` is a legal outcome, and both cases are pinned.

    Arrangement: a config with a non-default ``path`` and a ``line_for``
    returning a fixed value for any dotted path.
    Action: run only ``TSWAP_C300_RULE`` on a description-less tool.
    Assertion: the diagnostic's ``line`` is the value ``line_for``
    returned and ``file`` is ``str(config.path)`` — not a hardcoded name.
    """
    register(TSWAP_C300_RULE)
    cfg = _config(
        tools={"t1": _tool("t1")},
        line_for=lambda _p, _line=line: _line,
        path=Path("my-config.yaml"),
    )

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert d.location.file == "my-config.yaml"
    assert d.location.yaml_path == "tools.t1"
    assert d.location.line == line


def test_c300_precedence_blank_inline_description_beats_good_tool_yaml() -> None:
    """A blank INLINE description beats a good ``tool.yaml`` one (plan 297).

    Precedence interaction that is easy to implement backwards, so it gets
    its own test: ``description`` is layered ``inline > tool.yaml`` and a
    key present with a blank value wins, exactly like every other layer
    key (plan line 346).  A blank inline ``description`` therefore wins
    over a good ``tool.yaml`` one, and the C300 rule must then flag it.

    Arrangement: ``resolve_tool`` called with a blank inline description
    and a good ``tool.yaml`` description.
    Action: inspect the resolved carrier field, then run C300 over the
    resolved tool.
    Assertion: the resolved ``description`` is the blank inline value
    (not the tool.yaml one), and the rule emits exactly one C300 ERROR.
    """
    register(TSWAP_C300_RULE)
    resolved = resolve_tool(
        "t1",
        inline={"description": "   "},
        tool_yaml={"description": "A real description"},
    )

    assert resolved.description == "   "  # blank wins (behaviour 10 rule)

    cfg = _config(tools={"t1": resolved})
    report = validate_config(cfg)
    by_code = _diagnostics_by_code(report)

    assert set(by_code) == {"TSWAP-C300"}
    (d,) = by_code["TSWAP-C300"]
    assert d.severity is Severity.ERROR
    assert _WHY_PHRASE in d.message


def test_c300_non_string_description_counts_as_present() -> None:
    """A non-string description (e.g. ``42``) is PRESENT, not missing.

    Plan line 373: a non-string value is left to the schema layer's
    ``TSWAP-C105`` so one mistake yields one diagnostic rather than two.

    Arrangement: one tool with ``description=42``; only C300 registered.
    Action: run ``validate_config``.
    Assertion: no diagnostics at all.
    """
    register(TSWAP_C300_RULE)
    cfg = _config(tools={"t1": _tool("t1", description=42)})

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# 3. TSWAP-C301 — inputs entries (plan line 293)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blank", [None, "", "   ", "\n"])
def test_c301_flags_entries_missing_or_blank_description(blank: object) -> None:
    """A missing/blank input description is a C301 error naming the input.

    Arrangement: one input entry named ``payload`` whose description is
    the parametrized blank value (absent key or blank value); only
    ``TSWAP_C301_RULE`` registered.
    Action: run ``validate_config``.
    Assertion: exactly one diagnostic, code ``TSWAP-C301``, ERROR; the
    message names the input (``payload``); the location is
    ``tools.t1.inputs.0.description`` (dotted-numeric index, plan line
    390); the remedy is non-empty.
    """
    register(TSWAP_C301_RULE)
    entry: dict[str, object] = {"name": "payload", "type": "string"}
    if blank is not None:
        entry["description"] = blank
    cfg = _config(tools={"t1": _tool("t1", inputs=[entry])})

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C301"}
    (d,) = by_code["TSWAP-C301"]
    assert d.severity is Severity.ERROR
    assert "payload" in d.message
    assert d.location.file == "tools.yaml"
    assert d.location.yaml_path == "tools.t1.inputs.0.description"
    assert d.location.line is None
    assert d.remedy.strip() != ""


@pytest.mark.parametrize(
    "entry",
    [
        {"type": "string"},  # no name key at all
        {"name": "", "type": "string"},  # empty name
        {"name": "   ", "type": "string"},  # blank name
    ],
)
def test_c301_names_unnamed_entries_positionally(entry: dict[str, object]) -> None:
    """An entry without a usable name is named positionally (plan 377).

    The entry's ``name`` is used when it is a non-empty string; otherwise
    the entry is named ``inputs[<i>]`` so the message stays actionable.

    Arrangement: one input entry at index 0 whose name is absent, empty,
    or blank.
    Action: run only ``TSWAP_C301_RULE``.
    Assertion: exactly one C301 whose message names ``inputs[0]``.
    """
    register(TSWAP_C301_RULE)
    cfg = _config(tools={"t1": _tool("t1", inputs=[entry])})

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C301"}
    (d,) = by_code["TSWAP-C301"]
    assert "inputs[0]" in d.message
    assert d.location.yaml_path == "tools.t1.inputs.0.description"


def test_c301_reports_every_missing_entry() -> None:
    """Every missing entry is reported: 2 bad of 3 inputs -> 2 diagnostics.

    Arrangement: three input entries — index 0 missing its description,
    index 1 described, index 2 blank.
    Action: run only ``TSWAP_C301_RULE``.
    Assertion: exactly two C301 diagnostics, at the dotted-numeric paths
    of the two bad entries (0 and 2), both ERROR.
    """
    register(TSWAP_C301_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                inputs=[
                    {"name": "a", "type": "string"},
                    {"name": "b", "type": "string", "description": "fine"},
                    {"name": "c", "type": "string", "description": "   "},
                ],
            )
        }
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C301"}
    diags = by_code["TSWAP-C301"]
    assert len(diags) == 2
    assert {d.location.yaml_path for d in diags} == {
        "tools.t1.inputs.0.description",
        "tools.t1.inputs.2.description",
    }
    assert all(d.severity is Severity.ERROR for d in diags)


@pytest.mark.parametrize("block", [None, []])
def test_c301_absent_or_empty_inputs_yield_nothing(block: object) -> None:
    """``inputs`` absent (``None``) and ``inputs: []`` both yield nothing.

    Plan block 4: the block is legal absent — ``None`` must stay distinct
    from ``[]`` — and both yield no diagnostics from C301.

    Arrangement: one tool whose ``inputs`` carrier is the parametrized
    value; only C301 registered.
    Action: run ``validate_config``.
    Assertion: no diagnostics at all.
    """
    register(TSWAP_C301_RULE)
    cfg = _config(tools={"t1": _tool("t1", inputs=block)})

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c301_non_string_entry_description_counts_as_present() -> None:
    """A non-string entry description (e.g. ``42``) is PRESENT (plan 373).

    Arrangement: one input entry with ``description=42``; only C301.
    Action: run ``validate_config``.
    Assertion: no diagnostics at all (left to the schema layer).
    """
    register(TSWAP_C301_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", inputs=[{"name": "x", "description": 42}])}
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c301_skips_non_mapping_entries_silently() -> None:
    """A non-mapping entry (a bare string) is skipped, no C999 (plan 375).

    Malformed entries belong to behaviour 20's ``TSWAP-S1xx``; this rule
    must neither flag them nor crash (a crash would surface as the
    internal ``TSWAP-C999``).

    Arrangement: ``inputs`` with a bare string entry next to a good one.
    Action: run only ``TSWAP_C301_RULE``.
    Assertion: no diagnostics at all — no C301, no C999.
    """
    register(TSWAP_C301_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                inputs=["paths", {"name": "ok", "description": "d"}],
            )
        }
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


@pytest.mark.parametrize("block", ["oops", {"name": "x"}])
def test_c301_skips_non_list_blocks_silently(block: object) -> None:
    """A block whose value is not a list is skipped, no C999 (plan 375).

    Arrangement: ``inputs`` set to a string or a dict.
    Action: run only ``TSWAP_C301_RULE``.
    Assertion: no diagnostics at all — no C301, no C999, no crash.
    """
    register(TSWAP_C301_RULE)
    cfg = _config(tools={"t1": _tool("t1", inputs=block)})

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# 4. TSWAP-C302 — outputs entries (plan line 294, WARNING)
# ---------------------------------------------------------------------------


def test_c302_flags_output_entries_missing_description() -> None:
    """A missing output description is a C302 WARNING naming the output.

    Same shape as C301, but WARNING severity and the ``outputs.`` yaml
    path.

    Arrangement: one output entry named ``result`` with no description;
    only ``TSWAP_C302_RULE`` registered.
    Action: run ``validate_config``.
    Assertion: exactly one diagnostic, code ``TSWAP-C302``, WARNING; the
    message names the output; the location is
    ``tools.t1.outputs.0.description``; the remedy is non-empty.
    """
    register(TSWAP_C302_RULE)
    cfg = _config(tools={"t1": _tool("t1", outputs=[{"name": "result"}])})

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C302"}
    (d,) = by_code["TSWAP-C302"]
    assert d.severity is Severity.WARNING
    assert "result" in d.message
    assert d.location.file == "tools.yaml"
    assert d.location.yaml_path == "tools.t1.outputs.0.description"
    assert d.location.line is None
    assert d.remedy.strip() != ""


@pytest.mark.parametrize("block", [None, []])
def test_c302_absent_or_empty_outputs_yield_nothing(block: object) -> None:
    """``outputs`` absent (``None``) and ``outputs: []`` yield nothing.

    Arrangement: one tool whose ``outputs`` carrier is the parametrized
    value; only C302 registered.
    Action: run ``validate_config``.
    Assertion: no diagnostics at all.
    """
    register(TSWAP_C302_RULE)
    cfg = _config(tools={"t1": _tool("t1", outputs=block)})

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# 5. TSWAP-C303 — params entries (plan line 295)
# ---------------------------------------------------------------------------


def test_c303_flags_param_entries_missing_description() -> None:
    """A missing param description is a C303 ERROR naming the param.

    §5.5.1 requires ``name``, ``type`` and ``description`` on every param.

    Arrangement: one param entry named ``limit`` with no description;
    only ``TSWAP_C303_RULE`` registered.
    Action: run ``validate_config``.
    Assertion: exactly one diagnostic, code ``TSWAP-C303``, ERROR; the
    message names the param; the location is
    ``tools.t1.params.0.description``; the remedy is non-empty.
    """
    register(TSWAP_C303_RULE)
    cfg = _config(tools={"t1": _tool("t1", params=[{"name": "limit"}])})

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C303"}
    (d,) = by_code["TSWAP-C303"]
    assert d.severity is Severity.ERROR
    assert "limit" in d.message
    assert d.location.file == "tools.yaml"
    assert d.location.yaml_path == "tools.t1.params.0.description"
    assert d.location.line is None
    assert d.remedy.strip() != ""


@pytest.mark.parametrize("block", [None, []])
def test_c303_absent_or_empty_params_yield_nothing(block: object) -> None:
    """``params`` absent (``None``) and ``params: []`` yield nothing.

    Arrangement: one tool whose ``params`` carrier is the parametrized
    value; only C303 registered.
    Action: run ``validate_config``.
    Assertion: no diagnostics at all.
    """
    register(TSWAP_C303_RULE)
    cfg = _config(tools={"t1": _tool("t1", params=block)})

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# 6. Rule isolation and aggregation
# ---------------------------------------------------------------------------


def test_clean_tool_produces_no_description_diagnostics() -> None:
    """A well-described tool yields no C300-C303 diagnostics at all.

    The only-own-codes pin: with all four rules registered, a tool whose
    description, inputs, outputs and params are all described produces
    none of the four codes.

    Arrangement: one fully described tool; all four rules registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    for rule in (
        TSWAP_C300_RULE,
        TSWAP_C301_RULE,
        TSWAP_C302_RULE,
        TSWAP_C303_RULE,
    ):
        register(rule)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                description="Does the thing.",
                inputs=[{"name": "a", "type": "string", "description": "input a"}],
                outputs=[{"name": "b", "type": "string", "description": "output b"}],
                params=[{"name": "c", "type": "integer", "description": "param c"}],
            )
        }
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_multiple_description_problems_are_all_in_one_report() -> None:
    """C300 + two C301 + a C303 all surface in one ``validate_config`` run.

    ``validate_config`` runs every registered rule and aggregates ALL
    findings (never stopping at the first error), so a config with four
    missing descriptions must yield all four diagnostics — and, since the
    rules read only the carrier fields, nothing else.

    Arrangement: one tool with no description, two of three inputs
    undescribed, and one undescribed param (``outputs`` absent).
    Action: run all four rules via ``validate_config``.
    Assertion: exactly one C300, two C301, one C303, and no C302 (absent
    block) and no C999 (no rule crashed).
    """
    for rule in (
        TSWAP_C300_RULE,
        TSWAP_C301_RULE,
        TSWAP_C302_RULE,
        TSWAP_C303_RULE,
    ):
        register(rule)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                inputs=[
                    {"name": "a", "type": "string"},
                    {"name": "b", "type": "string", "description": "fine"},
                    {"name": "c", "type": "string", "description": "   "},
                ],
                params=[{"name": "limit", "type": "integer"}],
            )
        }
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C300", "TSWAP-C301", "TSWAP-C303"}
    assert len(by_code["TSWAP-C300"]) == 1
    assert len(by_code["TSWAP-C301"]) == 2
    assert len(by_code["TSWAP-C303"]) == 1
    assert "TSWAP-C999" not in by_code


# ---------------------------------------------------------------------------
# 7. downgrade_missing_descriptions — the --allow-missing-descriptions
#    post-processor (plan block 6, mechanism (a)); tested directly on
#    hand-built ConfigReports, no registry needed
# ---------------------------------------------------------------------------


def _diag(code: str, severity: Severity, message: str) -> Diagnostic:
    """Build a hand-crafted diagnostic at a fixed location.

    Args:
        code: the diagnostic code (must match the TSWAP pattern).
        severity: the diagnostic severity.
        message: the diagnostic message.

    Returns:
        A frozen ``Diagnostic`` located in ``tools.yaml`` at
        ``tools.t1``.
    """
    return Diagnostic(
        code=code,
        severity=severity,
        message=message,
        location=Location(file="tools.yaml", yaml_path="tools.t1"),
        remedy="Do the thing.",
    )


def _base_report() -> ConfigReport:
    """Build a report with one diagnostic of each relevant code.

    The diagnostics are supplied already in the report's deterministic
    ``(file, line or 0, code)`` sort order, so order-sensitive
    comparisons stay meaningful.

    Returns:
        A ``ConfigReport`` holding a C210 (ERROR, other code), a C300,
        a C301, a C302 (WARNING) and a C303.
    """
    return ConfigReport(
        diagnostics=(
            _diag("TSWAP-C210", Severity.ERROR, "Bad name."),
            _diag("TSWAP-C300", Severity.ERROR, "Tool 't1' is missing a description."),
            _diag("TSWAP-C301", Severity.ERROR, "Input 'x' is missing a description."),
            _diag(
                "TSWAP-C302",
                Severity.WARNING,
                "Output 'y' is missing a description.",
            ),
            _diag("TSWAP-C303", Severity.ERROR, "Param 'z' is missing a description."),
        )
    )


def _by_code(report: ConfigReport) -> dict[str, Diagnostic]:
    """Map a report's diagnostics by code (one diagnostic per code here).

    Args:
        report: a ``ConfigReport`` with at most one diagnostic per code.

    Returns:
        Code -> that code's diagnostic.
    """
    return {d.code: d for d in report.diagnostics}


def test_downgrade_rewrites_severity_for_c300_c301_c303_only() -> None:
    """Only C300/C301/C303 change severity; C302 and others are untouched.

    Plan line 427: exactly C300, C301, C303 are touched.  C302 is
    untouched — it is already a warning — and every other diagnostic
    (here a C210 error) passes through with its severity AND message
    unchanged.

    Arrangement: the hand-built report with one diagnostic per code.
    Action: call ``downgrade_missing_descriptions``.
    Assertion: C300/C301/C303 are now WARNING; C302 is still WARNING with
    its original message; the C210 is still ERROR with its original
    message.
    """
    report = _base_report()

    result = downgrade_missing_descriptions(report)

    out = _by_code(result)
    for code in ("TSWAP-C300", "TSWAP-C301", "TSWAP-C303"):
        assert out[code].severity is Severity.WARNING
    assert out["TSWAP-C302"].severity is Severity.WARNING
    assert out["TSWAP-C302"].message == "Output 'y' is missing a description."
    assert out["TSWAP-C210"].severity is Severity.ERROR
    assert out["TSWAP-C210"].message == "Bad name."


def test_downgrade_appends_banner_to_downgraded_messages() -> None:
    """The banner is appended to each downgraded message (plan line 426).

    The banner goes in ``message`` — which is what makes it survive
    ``--json`` — as ``f"{original} — {banner}"``, so the original message
    text is preserved as a prefix and the banner appears for the
    downgraded entries in ``to_json()`` (and nowhere else).

    Arrangement: the hand-built report.
    Action: call ``downgrade_missing_descriptions`` and inspect the
    returned messages and the report's JSON.
    Assertion: each downgraded message is exactly the original message
    followed by ``" — "`` and the pinned banner; the untouched messages
    carry no banner; ``to_json()`` contains the banner exactly three
    times.
    """
    report = _base_report()
    original = _by_code(report)

    result = downgrade_missing_descriptions(report)

    out = _by_code(result)
    for code in ("TSWAP-C300", "TSWAP-C301", "TSWAP-C303"):
        assert out[code].message.startswith(original[code].message)
        assert out[code].message == (
            f"{original[code].message} — {ALLOW_MISSING_DESCRIPTIONS_BANNER}"
        )
    assert ALLOW_MISSING_DESCRIPTIONS_BANNER not in out["TSWAP-C210"].message
    assert ALLOW_MISSING_DESCRIPTIONS_BANNER not in out["TSWAP-C302"].message
    assert result.to_json().count(ALLOW_MISSING_DESCRIPTIONS_BANNER) == 3


def test_downgrade_is_pure_and_does_not_mutate_the_input() -> None:
    """The input report is left untouched (plan line 410: pure).

    Arrangement: the hand-built report, with its diagnostics tuple and
    severities snapshotted.
    Action: call ``downgrade_missing_descriptions`` on it.
    Assertion: the original report still holds the SAME diagnostics tuple
    with ERROR severity and the original messages for C300/C301/C303.
    """
    report = _base_report()
    snapshot = report.diagnostics

    downgrade_missing_descriptions(report)

    assert report.diagnostics is snapshot
    original = _by_code(report)
    for code in ("TSWAP-C300", "TSWAP-C301", "TSWAP-C303"):
        assert original[code].severity is Severity.ERROR
    assert (
        original["TSWAP-C300"].message == "Tool 't1' is missing a description."
    )


def test_downgrade_is_idempotent() -> None:
    """A double call cannot double-append the banner (plan line 429).

    A diagnostic already carrying the banner is returned unchanged, so
    applying the post-processor twice yields exactly the same report as
    applying it once — pinned because a CLI refactor could easily call
    it twice.

    Arrangement: the hand-built report.
    Action: call ``downgrade_missing_descriptions`` twice.
    Assertion: the twice-report equals the once-report (full report
    equality, including diagnostic messages); each downgraded message
    carries the banner exactly once.
    """
    report = _base_report()

    once = downgrade_missing_descriptions(report)
    twice = downgrade_missing_descriptions(once)

    assert twice == once
    assert twice.diagnostics == once.diagnostics
    for code in ("TSWAP-C300", "TSWAP-C301", "TSWAP-C303"):
        message = _by_code(once)[code].message
        assert message.count(ALLOW_MISSING_DESCRIPTIONS_BANNER) == 1


def test_downgrade_returns_a_config_report() -> None:
    """The post-processor returns a ``ConfigReport`` of the same size.

    Type pin (plan line 423): the signature is
    ``ConfigReport -> ConfigReport`` — a NEW report, not the same object
    (purity) and not a raw tuple.

    Arrangement: the hand-built report.
    Action: call ``downgrade_missing_descriptions``.
    Assertion: the result is a ``ConfigReport``, is not the input object,
    and carries the same number of diagnostics.
    """
    report = _base_report()

    result = downgrade_missing_descriptions(report)

    assert isinstance(result, ConfigReport)
    assert result is not report
    assert len(result.diagnostics) == len(report.diagnostics)

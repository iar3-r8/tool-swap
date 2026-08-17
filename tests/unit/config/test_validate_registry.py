"""Tests for M1 behaviour 11 — the validator skeleton: a rule registry
that reports everything at once.

See ``plans/m1-configuration.md`` §1, behaviour 11 (lines 198-208), and the §6
rule → behaviour map (lines 445-467).  This file is the RED step: the module
under test, ``src/tool_swap/config/validate.py``, does not exist yet, so the
file fails collection with ``ModuleNotFoundError``.  That is the *right* red
reason — every test body below pins a concrete behaviour the GREEN step must
satisfy, so the assertions (not just the import) are the contract.

Scope.  Behaviour 11 is the SKELETON only: the rule shape, the registry, and
``validate_config()``.  The individual §6 rules (``TSWAP-C210`` … ``TSWAP-C613``,
behaviours 12-19) and their own test files come later; NO specific §6 rule
logic is tested here.  What is tested is the registry's *contract* that those
future rules plug into, exercised with small fake rules (frozen-dataclass
subclasses of ``Rule``) defined in this file.

Pinned public API (the contract the GREEN step must meet verbatim):

- ``Rule`` — a **frozen dataclass** in ``validate.py``.  A rule is a registered
  object with ``id``, ``severity``, ``remedy`` and a ``check()`` method;
  deliberately the shape ``plan/08_REPO_LAYOUT.md`` specifies for the M5
  preflight ``Check`` protocol (id / severity / remedy text), so M5 *moves*
  these rules rather than reimplementing them (guardrail 13).  Field order is
  pinned so subclasses may add trailing fields:

  - ``id: str`` — the diagnostic code, e.g. ``"TSWAP-C210"``; must match
    ``TSWAP-[CS]\\d{3}`` or construction raises ``ValueError`` whose message
    contains ``"TSWAP-"`` (the id IS the diagnostic code; mirrors ``Diagnostic``).
  - ``remedy: str`` — **mandatory, non-empty**: the rule's default remedy text.
    Empty or whitespace-only raises ``ValueError`` whose message contains
    ``"remedy"`` (mirrors ``Diagnostic.__post_init__``; behaviour 2).  This is
    the "a check that cannot say how to fix its own failure does not get
    merged" guardrail.
  - ``severity: Severity = Severity.ERROR`` — the rule's default severity.
  - ``check(self, config: ValidatedConfig) -> list[Diagnostic]`` — a **method**
    (possibly returning ``[]``); the base ``Rule.check`` returns ``[]`` and
    rule subclasses override it.
  - frozen: assigning any attribute after construction raises
    ``AttributeError`` (the ``FrozenInstanceError`` subclass).

- ``ValidatedConfig`` — the **frozen** input container for ``validate_config``,
  constructible directly by tests with fake data (no loader, no filesystem):

  - ``tools: dict[str, ResolvedTool]`` — the resolved tools (positional);
  - ``raw: dict`` — the raw root mapping (positional);
  - ``line_for: Callable[[str], int | None]`` — **keyword-only**, maps a dotted
    YAML path to a 1-based source line or ``None``; default returns ``None``;
  - ``path: Path`` — **keyword-only**, the config file path; default
    ``Path("tools.yaml")``.

- ``RULES`` — the module-level registry, a **tuple** of ``Rule``; initially
  **empty** (behaviour 11 ships the skeleton; behaviours 12-19 register the
  real rules).  Importing ``validate.py`` never registers a rule.

- ``register(rule: Rule) -> None`` — appends ``rule`` to the registry; a rule
  whose ``id`` is already registered raises ``ValueError`` (message contains
  the id), and the registry is unchanged.

- ``registered_rule_ids() -> list[str]`` — the registered rule ids in
  registration order; returns a fresh list (mutating the result does not
  mutate the registry).

- ``unregister_all() -> None`` — clears the registry (required for
  deterministic, isolated tests).

- ``validate_config(config: ValidatedConfig) -> ConfigReport`` — a **pure**
  function of its input (no filesystem, no clock, no environment).  Runs
  **every** registered rule and returns ONE ``ConfigReport``; it does not stop
  at the first error; the report's diagnostics are deterministically sorted
  per behaviour 2 (``(file, line or 0, code)``); rule registration order does
  not affect the outcome.  A rule whose ``check`` raises an unexpected
  exception is **caught** and reported as a single internal diagnostic:
  code ``TSWAP-C999``, ``Severity.ERROR``, whose message contains the rule's
  ``id`` *and* the exception text (``"boom"``), with location
  ``Location(file=str(config.path))``; the other rules' diagnostics are still
  present (the failure does not hide the other findings).

Conventions: pytest, AAA pattern, snake_case, Google docstrings, no
``warnings.warn`` (pyproject sets ``filterwarnings = "error"``).
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest
from tool_swap.config.validate import (  # noqa: E501  (module absent in RED step)
    RULES,
    Rule,
    ValidatedConfig,
    register,
    registered_rule_ids,
    unregister_all,
    validate_config,
)

from tool_swap.config.errors import Diagnostic, Location, Severity
from tool_swap.config.origin import OriginMap
from tool_swap.config.resolver import ResolvedTool

# ---------------------------------------------------------------------------
# Constants and fakes
# ---------------------------------------------------------------------------

#: Diagnostic codes the fake rules may emit; legal per the ``TSWAP-[CS]\d{3}``
#: pattern enforced by ``Diagnostic`` (behaviour 2).
_FAKE_ERROR_CODE: Final[str] = "TSWAP-C900"
_FAKE_WARNING_CODE: Final[str] = "TSWAP-C901"
_FAKE_ERROR2_CODE: Final[str] = "TSWAP-C902"

#: Pinned code for the internal diagnostic emitted when a rule raises
#: (behaviour 11 edge case; ``TSWAP-C999`` is free in the C-series).
_INTERNAL_RULE_CODE: Final[str] = "TSWAP-C999"


@dataclass(frozen=True)
class FixedDiagnosticRule(Rule):
    """A rule returning a fixed tuple of diagnostics (implements the ``Rule`` shape).

    Subclassing the pinned ``Rule`` proves a user-defined rule type can satisfy
    the registry contract without redeclaring the mandatory ``id`` / ``remedy``
    / ``severity`` surface; only the ``check`` behaviour is added.
    """

    diagnostics: tuple[Diagnostic, ...] = ()

    def check(self, config: ValidatedConfig) -> list[Diagnostic]:  # noqa: ARG002
        """Return the fixed diagnostics, ignoring the config."""
        return list(self.diagnostics)


@dataclass(frozen=True)
class RaisingRule(Rule):
    """A rule whose ``check`` raises a stored exception (deliberately broken)."""

    exception: BaseException = RuntimeError("boom")

    def check(self, config: ValidatedConfig) -> list[Diagnostic]:  # noqa: ARG002
        """Raise the stored exception."""
        raise self.exception


def _resolved_tool(name: str = "fake") -> ResolvedTool:
    """Build a minimal, frozen ``ResolvedTool`` for a fake ``ValidatedConfig``."""
    return ResolvedTool(name=name, values={}, origins=OriginMap(), diagnostics=[])


def _validated_config(
    tools: dict[str, ResolvedTool] | None = None,
    raw: dict | None = None,
    line_for: Callable[[str], int | None] | None = None,
    path: Path | None = None,
) -> ValidatedConfig:
    """Build a ``ValidatedConfig`` with fake data (pins the field names)."""
    return ValidatedConfig(
        tools=tools if tools is not None else {},
        raw=raw if raw is not None else {},
        line_for=line_for if line_for is not None else (lambda _p: None),
        path=path if path is not None else Path("tools.yaml"),
    )


def _diagnostic(
    code: str = _FAKE_ERROR_CODE,
    severity: Severity = Severity.ERROR,
    message: str = "fake problem",
    file: str = "tools.yaml",
    line: int | None = None,
    yaml_path: str | None = None,
) -> Diagnostic:
    """Build a valid ``Diagnostic``; override any field per test."""
    return Diagnostic(
        code=code,
        severity=severity,
        message=message,
        location=Location(file=file, yaml_path=yaml_path, line=line),
        remedy="Fix the fake problem.",
    )


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Start and end every test with an empty, known registry.

    Behaviour 11's GREEN ships with an empty registry; later behaviour test
    modules (12-19) will register rules at import time, so each test must not
    depend on — and must not leak — registration state.
    """
    unregister_all()
    try:
        yield
    finally:
        unregister_all()


# ---------------------------------------------------------------------------
# 1. The rule shape (plan line 202: id, severity, check(), mandatory remedy)
# ---------------------------------------------------------------------------


def test_rule_exposes_id_severity_remedy_and_check_method() -> None:
    """A rule carries ``id``, ``severity``, ``remedy`` and a ``check`` method.

    Arrangement: a valid rule constructed with all three fields.
    Action: read back every field.
    Assertion: the three fields hold the given values and ``check`` is callable.
    """
    rule = Rule(id=_FAKE_ERROR_CODE, severity=Severity.WARNING, remedy="Do it.")

    assert rule.id == _FAKE_ERROR_CODE
    assert rule.severity is Severity.WARNING
    assert rule.remedy == "Do it."
    assert callable(rule.check)


def test_rule_rejects_empty_remedy_with_value_error_naming_remedy() -> None:
    """Plan line 202: the remedy is MANDATORY — an empty remedy is rejected.

    Arrangement: a rule with ``remedy=""``.
    Action: construct it.
    Assertion: ``ValueError`` whose message names the remedy (pin: the frozen
    dataclass ``__post_init__`` rejects it, mirroring ``Diagnostic``).
    """
    with pytest.raises(ValueError, match="remedy"):
        Rule(id=_FAKE_ERROR_CODE, remedy="")


def test_rule_rejects_whitespace_remedy_with_value_error() -> None:
    """A whitespace-only remedy is also rejected (non-empty means non-blank).

    Arrangement: a rule with ``remedy="   "``.
    Action: construct it.
    Assertion: ``ValueError`` naming the remedy.
    """
    with pytest.raises(ValueError, match="remedy"):
        Rule(id=_FAKE_ERROR_CODE, remedy="   ")


def test_rule_rejects_malformed_id_with_value_error() -> None:
    """The rule id is the diagnostic code and must match ``TSWAP-[CS]\\d{3}``.

    Arrangement: rules with ids outside the pattern.
    Action: construct each.
    Assertion: ``ValueError`` naming the code convention.
    """
    for bad_id in ("C900", "TSWAP-X900", "TSWAP-C90", ""):
        with pytest.raises(ValueError, match="TSWAP-"):
            Rule(id=bad_id, remedy="Fix it.")


def test_rule_is_frozen_and_rejects_mutation() -> None:
    """The rule shape is frozen — no attribute mutation after construction.

    Arrangement: one valid rule.
    Action: attempt to assign to every field (and the ``check`` method).
    Assertion: every mutation raises ``AttributeError`` (frozen dataclass).
    """
    rule = Rule(id=_FAKE_ERROR_CODE, remedy="Fix it.")
    for field_name in ("id", "remedy", "severity", "check"):
        with pytest.raises(AttributeError):
            setattr(rule, field_name, None)


def test_rule_defaults_severity_to_error_and_check_to_empty() -> None:
    """Severity defaults to ``ERROR``; the base ``check`` returns ``[]``.

    Arrangement: a rule constructed with only id and remedy.
    Action: inspect the defaulted fields.
    Assertion: ``severity is Severity.ERROR`` and ``check`` returns an empty
    list for a fake config.
    """
    rule = Rule(id=_FAKE_ERROR_CODE, remedy="Fix it.")

    assert rule.severity is Severity.ERROR
    assert rule.check(_validated_config()) == []


# ---------------------------------------------------------------------------
# 2. The ValidatedConfig input type (constructible directly by tests)
# ---------------------------------------------------------------------------


def test_validated_config_fields_and_defaults() -> None:
    """``ValidatedConfig`` pins ``tools``, ``raw``, ``line_for``, ``path``.

    Arrangement: construction with explicit fields, then with none.
    Action: read back the fields and call the default ``line_for``.
    Assertion: explicit values are stored; the defaults are a ``None``-
    returning ``line_for`` and ``Path("tools.yaml")``.
    """
    tools = {"fake": _resolved_tool()}
    raw = {"tools": {"fake": {}}}
    cfg = ValidatedConfig(
        tools=tools, raw=raw, line_for=lambda p: 42, path=Path("a/b.yaml")
    )
    assert cfg.tools is tools
    assert cfg.raw is raw
    assert cfg.line_for("tools.fake.ttl") == 42
    assert cfg.path == Path("a/b.yaml")

    empty = ValidatedConfig(tools={}, raw={})
    assert empty.line_for("anything") is None
    assert empty.path == Path("tools.yaml")


def test_validated_config_is_frozen() -> None:
    """The input container is frozen — ``validate_config`` must not mutate it.

    Arrangement: one config.
    Action: attempt to assign to every field.
    Assertion: every mutation raises ``AttributeError``.
    """
    cfg = ValidatedConfig(tools={}, raw={})
    for field_name in ("tools", "raw", "line_for", "path"):
        with pytest.raises(AttributeError):
            setattr(cfg, field_name, None)


# ---------------------------------------------------------------------------
# 3. Registration (the registry's contract)
# ---------------------------------------------------------------------------


def test_registered_rule_ids_returns_registered_ids_in_order() -> None:
    """A registered rule is in the registry; the accessor returns all ids.

    Arrangement: two rules registered in order.
    Action: call ``registered_rule_ids()`` and inspect ``RULES``.
    Assertion: the ids come back in registration order, and ``RULES`` holds
    the same rule objects.
    """
    r1 = Rule(id=_FAKE_ERROR_CODE, remedy="Fix one.")
    r2 = Rule(id=_FAKE_WARNING_CODE, remedy="Fix two.")
    register(r1)
    register(r2)

    assert registered_rule_ids() == [_FAKE_ERROR_CODE, _FAKE_WARNING_CODE]
    assert (r1, r2) == RULES


def test_register_rejects_duplicate_rule_id() -> None:
    """Two rules with the same id cannot both be registered.

    Arrangement: one rule id registered.
    Action: register a second rule with the same id.
    Assertion: ``ValueError`` naming the id, and the registry still holds
    exactly the first rule.
    """
    r1 = Rule(id=_FAKE_ERROR_CODE, remedy="Fix one.")
    r2 = Rule(id=_FAKE_ERROR_CODE, remedy="Fix one again.")
    register(r1)

    with pytest.raises(ValueError, match=_FAKE_ERROR_CODE):
        register(r2)

    assert registered_rule_ids() == [_FAKE_ERROR_CODE]
    assert (r1,) == RULES


def test_registered_rule_ids_returns_a_copy() -> None:
    """The accessor returns a fresh list, not the registry's internals.

    Arrangement: one registered rule.
    Action: mutate the returned list.
    Assertion: the registry is unaffected.
    """
    register(Rule(id=_FAKE_ERROR_CODE, remedy="Fix one."))

    ids = registered_rule_ids()
    ids.clear()

    assert registered_rule_ids() == [_FAKE_ERROR_CODE]


def test_unregister_all_clears_the_registry() -> None:
    """``unregister_all`` empties the registry (deterministic test isolation).

    Arrangement: two registered rules.
    Action: call ``unregister_all()``.
    Assertion: both the accessor and ``RULES`` report an empty registry.
    """
    register(Rule(id=_FAKE_ERROR_CODE, remedy="Fix one."))
    register(Rule(id=_FAKE_WARNING_CODE, remedy="Fix two."))

    unregister_all()

    assert registered_rule_ids() == []
    assert RULES == ()


# ---------------------------------------------------------------------------
# 4. validate_config runs EVERY rule and reports everything at once
#    (plan lines 203-204)
# ---------------------------------------------------------------------------


def test_validate_config_reports_every_rules_diagnostics_at_once() -> None:
    """A config with distinct problems across rules yields ALL of them.

    Arrangement: three fake rules, each returning one distinct diagnostic
    (an error at a line, a warning at a different line, an error with no line).
    Action: run ``validate_config`` on a fake config.
    Assertion: the report contains all three — not just the first — with the
    right severities, and it is not ok.
    """
    d_err = _diagnostic(
        code=_FAKE_ERROR_CODE, severity=Severity.ERROR, file="tools.yaml", line=3
    )
    d_warn = _diagnostic(
        code=_FAKE_WARNING_CODE, severity=Severity.WARNING, file="tools.yaml", line=9
    )
    d_err2 = _diagnostic(
        code=_FAKE_ERROR2_CODE, severity=Severity.ERROR, file="tools.yaml"
    )

    register(
        FixedDiagnosticRule(id="TSWAP-C910", remedy="Fix A.", diagnostics=(d_err,))
    )
    register(
        FixedDiagnosticRule(id="TSWAP-C911", remedy="Fix B.", diagnostics=(d_warn,))
    )
    register(
        FixedDiagnosticRule(id="TSWAP-C912", remedy="Fix C.", diagnostics=(d_err2,))
    )

    report = validate_config(_validated_config())

    assert sorted(report.diagnostics) == sorted([d_err, d_warn, d_err2])
    assert len(report.diagnostics) == 3
    assert {d.code for d in report.diagnostics} == {
        _FAKE_ERROR_CODE,
        _FAKE_WARNING_CODE,
        _FAKE_ERROR2_CODE,
    }
    assert [d.code for d in report.warnings] == [_FAKE_WARNING_CODE]
    assert report.ok is False
    assert report.exit_code == 1


def test_validate_config_runs_rules_returning_no_diagnostics_too() -> None:
    """A rule that finds nothing still runs; its silence is not a skip.

    Arrangement: one quiet rule (base ``Rule.check`` returns ``[]``) and one
    loud rule.
    Action: run ``validate_config``.
    Assertion: the report contains exactly the loud rule's diagnostic, and
    both rule ids are registered (the quiet one is not dropped).
    """
    d = _diagnostic(code=_FAKE_ERROR_CODE, message="only finding")
    quiet = Rule(id="TSWAP-C920", remedy="Nothing to fix.")
    loud = FixedDiagnosticRule(id="TSWAP-C921", remedy="Fix it.", diagnostics=(d,))
    register(quiet)
    register(loud)

    report = validate_config(_validated_config())

    assert report.diagnostics == (d,)
    assert registered_rule_ids() == ["TSWAP-C920", "TSWAP-C921"]


def test_report_diagnostics_are_sorted_per_behaviour_2() -> None:
    """The report serves its diagnostics in deterministic sorted order.

    Arrangement: rules whose diagnostics are deliberately NOT in (file, line,
    code) order.
    Action: run ``validate_config``.
    Assertion: ``report.diagnostics`` equals its own sorted form — the
    behaviour-2 ``(file, line or 0, code)`` order.
    """
    d_late = _diagnostic(code=_FAKE_ERROR2_CODE, file="tools.yaml", line=99)
    d_early = _diagnostic(code=_FAKE_ERROR_CODE, file="tools.yaml", line=2)
    register(
        FixedDiagnosticRule(id="TSWAP-C930", remedy="Fix late.", diagnostics=(d_late,))
    )
    register(
        FixedDiagnosticRule(
            id="TSWAP-C931", remedy="Fix early.", diagnostics=(d_early,)
        )
    )

    report = validate_config(_validated_config())

    assert report.diagnostics == tuple(sorted(report.diagnostics))
    assert [d.line for d in report.diagnostics] == [2, 99]


# ---------------------------------------------------------------------------
# 5. Rule order does not affect the outcome (plan line 204)
# ---------------------------------------------------------------------------


def test_registration_order_does_not_affect_the_report() -> None:
    """Two rules registered in opposite orders give the same report.

    Arrangement: two fake rules emitting diagnostics for *different* files, so
    the behaviour-2 sort order is unambiguous.
    Action: register [r_a, r_b] and validate; reset; register [r_b, r_a] and
    validate.
    Assertion: the JSON and human render are byte-identical in both orders, and
    the sort order (file a before file b) holds in both.
    """
    d_a = _diagnostic(code=_FAKE_ERROR_CODE, file="a.yaml", line=1, message="in a")
    d_b = _diagnostic(
        code=_FAKE_WARNING_CODE,
        severity=Severity.WARNING,
        file="b.yaml",
        line=5,
        message="in b",
    )
    r_a = FixedDiagnosticRule(id="TSWAP-C940", remedy="Fix a.", diagnostics=(d_a,))
    r_b = FixedDiagnosticRule(id="TSWAP-C941", remedy="Fix b.", diagnostics=(d_b,))

    register(r_a)
    register(r_b)
    first = validate_config(_validated_config())

    unregister_all()
    register(r_b)
    register(r_a)
    second = validate_config(_validated_config())

    assert first.to_json() == second.to_json()
    assert first.render() == second.render()
    assert [d.location.file for d in first.diagnostics] == ["a.yaml", "b.yaml"]
    assert [d.location.file for d in second.diagnostics] == ["a.yaml", "b.yaml"]


# ---------------------------------------------------------------------------
# 6. A raising rule is caught and reported, not fatal (plan line 206)
# ---------------------------------------------------------------------------


def test_raising_rule_yields_internal_diagnostic_naming_the_rule_id() -> None:
    """A rule whose check() raises does not crash the whole command.

    Arrangement: a rule whose ``check`` raises ``RuntimeError("boom")`` plus
    one healthy rule with its own diagnostic.
    Action: run ``validate_config`` (must not raise).
    Assertion: exactly one internal diagnostic — code ``TSWAP-C999``,
    ``Severity.ERROR``, message containing the rule's id AND ``"boom"``,
    location on the config path — is present, and the healthy rule's
    diagnostic is still there (the failure did not hide other findings).
    """
    healthy = _diagnostic(
        code=_FAKE_ERROR_CODE, file="tools.yaml", line=4, message="healthy"
    )
    broken = RaisingRule(
        id="TSWAP-C950", remedy="Fix broken.", exception=RuntimeError("boom")
    )
    register(
        FixedDiagnosticRule(
            id="TSWAP-C951", remedy="Fix healthy.", diagnostics=(healthy,)
        )
    )
    register(broken)

    report = validate_config(_validated_config())

    internal = [d for d in report.diagnostics if d.code == _INTERNAL_RULE_CODE]
    assert len(internal) == 1
    (d,) = internal
    assert d.severity is Severity.ERROR
    assert "TSWAP-C950" in d.message
    assert "boom" in d.message
    assert d.location.file == "tools.yaml"
    assert healthy in report.diagnostics
    assert report.ok is False
    assert report.exit_code == 1


def test_internal_diagnostic_carries_a_non_empty_remedy() -> None:
    """Even the internal diagnostic obeys the mandatory-remedy rule.

    Arrangement: a single raising rule.
    Action: run ``validate_config``.
    Assertion: the internal diagnostic's remedy is a non-empty string (so it
    survives ``Diagnostic`` construction and the "one report shape" rule).
    """
    broken = RaisingRule(id="TSWAP-C960", remedy="Fix broken.")
    register(broken)

    report = validate_config(_validated_config())

    (d,) = report.diagnostics
    assert d.code == _INTERNAL_RULE_CODE
    assert d.remedy.strip() != ""


# ---------------------------------------------------------------------------
# 7. Empty registry -> ok report (plan line 203, degenerate case)
# ---------------------------------------------------------------------------


def test_empty_registry_yields_ok_report() -> None:
    """With no rules registered, ``validate_config`` reports nothing.

    Arrangement: the (pinned-empty) registry and a fake config.
    Action: run ``validate_config``.
    Assertion: an ok report with no diagnostics, exit code 0, empty render and
    ``"[]"`` JSON (behaviour 2's empty-report forms).
    """
    assert registered_rule_ids() == []

    report = validate_config(_validated_config())

    assert report.diagnostics == ()
    assert report.ok is True
    assert report.exit_code == 0
    assert report.render() == ""
    assert report.to_json() == "[]"


# ---------------------------------------------------------------------------
# 8. The remedy mandate over the whole registry (a check that cannot say how
#    to fix its own failure does not get merged)
# ---------------------------------------------------------------------------


def test_every_registered_rule_carries_a_non_empty_remedy() -> None:
    """Every rule in the registry has a non-empty ``remedy``.

    Arrangement: a mix of rules with explicit and padded remedies.
    Action: iterate every registered rule.
    Assertion: each ``remedy`` is a non-empty string after ``strip()``.
    """
    register(Rule(id="TSWAP-C970", remedy="Fix one."))
    register(Rule(id="TSWAP-C971", remedy="Fix two."))
    register(Rule(id="TSWAP-C972", severity=Severity.WARNING, remedy="  Fix three.  "))

    for rule in RULES:
        assert isinstance(rule.remedy, str)
        assert rule.remedy.strip() != ""


# ---------------------------------------------------------------------------
# 9. The registry is module-level, importable without side effects
# ---------------------------------------------------------------------------


def test_importing_validate_leaves_the_registry_unchanged() -> None:
    """Importing (or re-importing) validate.py registers no rules.

    Arrangement: the registry cleared in the main process.
    Action: ``importlib`` the module again and read the registry.
    Assertion: the registry is still empty — the import is clean and has no
    side effects; the registry is live module-level state, not per-call.
    """
    import importlib

    assert registered_rule_ids() == []
    importlib.import_module("tool_swap.config.validate")

    assert registered_rule_ids() == []
    assert RULES == ()


def test_fresh_interpreter_starts_with_an_empty_registry() -> None:
    """In a fresh interpreter, importing validate yields the empty skeleton.

    A plain re-import cannot prove the *initial* state (the module would
    already be loaded), so this spawns a fresh interpreter that imports
    ``tool_swap.config.validate`` and reports its registry.

    Arrangement: the repo layout (``src/`` on ``PYTHONPATH``).
    Action: run the child interpreter.
    Assertion: it exits 0 and reports an empty id list — behaviour 11 ships
    with ZERO built-in rules; behaviours 12-19 add them.
    """
    child = (
        "import sys;"
        "sys.path.insert(0, 'src');"
        "import tool_swap.config.validate as v;"
        "ids = v.registered_rule_ids();"
        "assert ids == [], f'initial registry not empty: {ids}';"
        "print('EMPTY')"
    )
    result = subprocess.run(
        [sys.executable, "-c", child], capture_output=True, text=True, timeout=60
    )

    assert result.returncode == 0, result.stderr
    assert "EMPTY" in result.stdout


# ---------------------------------------------------------------------------
# 10. validate_config is a pure function of its input
#     (no filesystem, no clock, no environment)
# ---------------------------------------------------------------------------


def test_validate_config_is_pure_and_does_not_mutate_its_input() -> None:
    """Equal input gives equal output, twice, and the input is untouched.

    Arrangement: a config holding mutable fake data (a tool dict, a raw dict
    with a nested list) and two fixed fake rules.
    Action: call ``validate_config`` twice with the *same* config object,
    snapshotting deep copies of the input before the calls.
    Assertion: both reports are equal; the input data is deep-equal to its
    pre-call snapshot (the function did not mutate the tools, the raw mapping,
    or any nested value).
    """
    tools = {"fake": _resolved_tool()}
    raw = {"tools": {"fake": {"mounts": ["/a:/b:ro"]}}}
    cfg = _validated_config(tools=tools, raw=raw)
    before_tools = copy.deepcopy(tools)
    before_raw = copy.deepcopy(raw)

    register(
        FixedDiagnosticRule(
            id="TSWAP-C980", remedy="Fix one.", diagnostics=(_diagnostic(line=1),)
        )
    )
    register(
        FixedDiagnosticRule(
            id="TSWAP-C981",
            severity=Severity.WARNING,
            remedy="Fix two.",
            diagnostics=(_diagnostic(code=_FAKE_WARNING_CODE, line=7),),
        )
    )

    report_1 = validate_config(cfg)
    report_2 = validate_config(cfg)

    assert report_1 == report_2
    assert tools == before_tools
    assert raw == before_raw


def test_validate_config_ignores_the_ambient_environment() -> None:
    """The report is not a function of the process environment.

    Arrangement: one rule with a fixed diagnostic.
    Action: set unrelated environment variables between two calls on the same
    config.
    Assertion: the reports are equal — nothing in the ambient environment
    leaks into the outcome.
    """
    cfg = _validated_config()
    register(
        FixedDiagnosticRule(
            id="TSWAP-C990", remedy="Fix it.", diagnostics=(_diagnostic(),)
        )
    )

    first = validate_config(cfg)
    os.environ["TSWAP_FAKE_ENV"] = "changed"
    os.environ["TZ"] = "Mars/Olympus"
    try:
        second = validate_config(cfg)
    finally:
        del os.environ["TSWAP_FAKE_ENV"]
        del os.environ["TZ"]

    assert first == second

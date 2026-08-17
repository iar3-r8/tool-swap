"""Tests for M1 behaviour 2 — the diagnostic model and the error-report container.

See ``plans/m1-configuration.md`` §1, behaviour 2 (lines 66-78), and the
diagnostic-model section (lines 21-48), which is *fixed in behaviour 2*:

.. code-block:: python

    @dataclass(frozen=True)
    class Diagnostic:
        code: str            # "TSWAP-C101" — stable, greppable, documented
        severity: Severity   # ERROR | WARNING
        message: str         # what is wrong, naming the offending key/value
        location: Location   # file, yaml_path, line, column
        remedy: str          # what to do about it — MANDATORY, non-empty

This file is the RED step: the module under test,
``src/tool_swap/config/errors.py``, does not exist yet, so the file fails
collection with ``ModuleNotFoundError``.  That is the *right* red reason —
every test body below pins a concrete behaviour the GREEN step must satisfy,
so the assertions (not just the import) are the contract.

Pinned public API (the contract the GREEN step must meet verbatim):

- ``Severity`` — an enum with EXACTLY two members: ``Severity.ERROR`` and
  ``Severity.WARNING``; ``Severity.ERROR.value == "error"`` and
  ``Severity.WARNING.value == "warning"`` (lowercase string values).
- ``Location`` — a constructible value type:
  ``Location(file, yaml_path=None, line=None, column=None)`` where ``file``
  is required and the other three are optional.  ``Location.render() -> str``:
  - file + line              -> ``"tools.yaml:42"``
  - file + yaml_path only    -> ``"tools.yaml (tools.cxr_to_embedding.ttl)"``
  - file only                -> ``"tools.yaml"``
- ``Diagnostic(code, severity, message, location, remedy)`` — frozen,
  hashable; ordering such that
  ``sorted([d1, d2]) == sorted([d1, d2], key=lambda d: (d.location.file,
  (d.location.line or 0), d.code))`` (``line=None`` sorts as line 0);
  ``__post_init__`` validation:
  - empty / whitespace-only ``remedy`` -> ``ValueError`` whose message
    contains ``"remedy"``;
  - ``code`` not matching ``TSWAP-[CS]\\d{3}`` -> ``ValueError`` whose
    message contains ``"TSWAP-"`` and ``"code"``.
- ``ConfigReport(diagnostics=...)`` (single argument, optional, iterable of
  ``Diagnostic``, defaulting to empty) exposing:
  - ``.errors``   — list of the ERROR-severity diagnostics, deterministically
    ordered;
  - ``.warnings`` — list of the WARNING-severity diagnostics, deterministically
    ordered;
  - ``.ok``       — ``True`` iff ``.errors`` is empty;
  - ``.exit_code``— ``0`` when ok else ``1`` (the CLI's exit-2 for an
    unreadable file is behaviour 21 and is NOT tested here);
  - ``.render()`` — one block per diagnostic (sorted), format pinned in
    ``test_config_report_render_pins_exact_block_format``; ``""`` when empty;
  - ``.to_json()``— ``json.dumps(list)`` where each object has exactly the
    keys ``code, severity, message, file, yaml_path, line, remedy`` (severity
    lowercase, ``None`` for absent yaml_path/line); ``"[]"`` when empty.
- ``ConfigError(report)`` — an exception that ALWAYS carries a report in
  ``.report``; constructing it without a report is a programming error and
  raises ``TypeError`` (there is no report-less form).

Conventions: pytest, AAA pattern, no ``warnings.warn`` (pyproject sets
``filterwarnings = "error"``).
"""

from __future__ import annotations

import json
import re

import pytest
from tool_swap.config.errors import (  # noqa: E501
    ConfigError,
    ConfigReport,
    Diagnostic,
    Location,
    Severity,
)

# A documented code from the plan's code-block table (TSWAP-C1xx = schema shape).
_VALID_CODE = "TSWAP-C101"
_VALID_REMEDY = "Set 'ttl' to an integer number of seconds."
_VALID_MESSAGE = "Tool 'cxr_to_embedding': 'ttl' must be an integer."


def _location(file="tools.yaml", yaml_path=None, line=None, column=None):
    """Build a ``Location`` with explicit keyword arguments (pins the signature)."""
    return Location(file=file, yaml_path=yaml_path, line=line, column=column)


def _diagnostic(
    code=_VALID_CODE,
    severity=None,
    message=_VALID_MESSAGE,
    location=None,
    remedy=_VALID_REMEDY,
):
    """Build a valid ``Diagnostic``; override any field per test."""
    return Diagnostic(
        code=code,
        severity=Severity.ERROR if severity is None else severity,
        message=message,
        location=location if location is not None else _location(),
        remedy=remedy,
    )


# ---------------------------------------------------------------------------
# 1. Diagnostic is frozen, hashable, value-equal
# ---------------------------------------------------------------------------


def test_diagnostic_is_frozen_and_rejects_mutation() -> None:
    """Plan: ``@dataclass(frozen=True)`` — mutating any field raises.

    Arrangement: one valid diagnostic.
    Action: attempt to assign to every field.
    Assertion: every mutation raises ``AttributeError`` (frozen dataclass).
    """
    diag = _diagnostic()
    for field in ("code", "severity", "message", "location", "remedy"):
        with pytest.raises(AttributeError):
            setattr(diag, field, "mutated")


def test_diagnostic_instances_are_hashable_and_value_equal() -> None:
    """Frozen dataclasses are hashable; two field-equal diagnostics dedupe in a set."""
    a = _diagnostic()
    b = _diagnostic()
    # Value equality and a stable hash make them interchangeable in a set.
    assert a == b
    assert hash(a) == hash(b)
    assert {a, b} == {a}


def test_diagnostic_fields_round_trip_through_constructors() -> None:
    """Field access returns exactly what was constructed.

    The attribute names (``code``, ``severity``, ``message``, ``location``,
    ``remedy``) are the contract the GREEN step must meet.
    """
    loc = _location(file="tools.yaml", yaml_path="tools.x.ttl", line=7, column=3)
    diag = _diagnostic(location=loc)
    assert diag.code == _VALID_CODE
    assert diag.severity is Severity.ERROR
    assert diag.message == _VALID_MESSAGE
    assert diag.remedy == _VALID_REMEDY
    assert diag.location is loc
    assert diag.location.file == "tools.yaml"
    assert diag.location.yaml_path == "tools.x.ttl"
    assert diag.location.line == 7
    assert diag.location.column == 3


# ---------------------------------------------------------------------------
# 2. Deterministic ordering by (file, line, code)
# ---------------------------------------------------------------------------


def test_diagnostics_sort_by_file_then_line_then_code() -> None:
    """Plan: ordered deterministically by ``(file, line, code)``.

    Pinned rule: ``line=None`` is treated as line 0 (sorts before any real
    line number).  ``sorted()`` must therefore coincide with sorting on the
    explicit key ``(file, line or 0, code)``.
    """
    a = _diagnostic(code="TSWAP-C102", location=_location(file="b.yaml", line=2))
    b = _diagnostic(code="TSWAP-C101", location=_location(file="b.yaml", line=2))
    c = _diagnostic(code="TSWAP-C101", location=_location(file="a.yaml", line=9))
    # line=None -> 0
    d = _diagnostic(code="TSWAP-C103", location=_location(file="a.yaml"))

    expected = sorted(
        [a, b, c, d], key=lambda x: (x.location.file, x.location.line or 0, x.code)
    )
    assert sorted([a, b, c, d]) == expected
    # a.yaml/no-line (0) < a.yaml:9 (C101) < b.yaml:2 (C101) < b.yaml:2 (C102).
    assert [x.code for x in expected] == [
        "TSWAP-C103",
        "TSWAP-C101",
        "TSWAP-C101",
        "TSWAP-C102",
    ]
    # Two diagnostics with the same file and line order by code.
    assert expected[2].code < expected[3].code


# ---------------------------------------------------------------------------
# 3. Location rendering — all three documented forms
# ---------------------------------------------------------------------------


def test_location_renders_file_and_line() -> None:
    """Plan: ``Location`` renders as ``tools.yaml:42`` when a line is known."""
    assert _location(file="tools.yaml", line=42).render() == "tools.yaml:42"


def test_location_renders_file_and_yaml_path_only() -> None:
    """Plan: ``tools.yaml (tools.cxr_to_embedding.ttl)`` when only the path is known."""
    assert _location(
        file="tools.yaml", yaml_path="tools.cxr_to_embedding.ttl"
    ).render() == ("tools.yaml (tools.cxr_to_embedding.ttl)")


def test_location_renders_file_only() -> None:
    """Plan: ``tools.yaml`` when neither line nor yaml_path is known."""
    assert _location(file="tools.yaml").render() == "tools.yaml"


# ---------------------------------------------------------------------------
# 4. remedy is MANDATORY, non-empty (DoD: "a message a stranger can act on")
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("remedy", ["", "   "])
def test_diagnostic_with_empty_or_whitespace_remedy_raises_value_error(remedy) -> None:
    """Plan edge case: an empty remedy raises ValueError at construction.

    The M1 Definition of Done is *a message a stranger can act on*; the error
    must say the remedy is mandatory so the bug is findable.
    """
    with pytest.raises(ValueError, match="remedy"):
        _diagnostic(remedy=remedy)


# ---------------------------------------------------------------------------
# 5. Severity is an enum with exactly ERROR and WARNING
# ---------------------------------------------------------------------------


def test_severity_has_exactly_error_and_warning_members() -> None:
    """Plan: ``severity: Severity   # ERROR | WARNING`` — no third member."""
    members = {m.name for m in Severity}
    assert members == {"ERROR", "WARNING"}
    # Pinned serialization: lowercase string values (used by to_json() below).
    assert Severity.ERROR.value == "error"
    assert Severity.WARNING.value == "warning"


# ---------------------------------------------------------------------------
# 6. ConfigReport: .errors / .warnings / .ok / .exit_code
# ---------------------------------------------------------------------------


def test_config_report_filters_errors_and_warnings_by_severity() -> None:
    """Plan: ``.errors`` / ``.warnings`` filter by severity."""
    err = _diagnostic(severity=Severity.ERROR, code="TSWAP-C101")
    warn = _diagnostic(severity=Severity.WARNING, code="TSWAP-C102")
    report = ConfigReport([err, warn])
    assert list(report.errors) == [err]
    assert list(report.warnings) == [warn]
    # Nothing of the wrong severity leaks into either view.
    assert all(d.severity is Severity.ERROR for d in report.errors)
    assert all(d.severity is Severity.WARNING for d in report.warnings)


def test_config_report_ok_and_exit_code() -> None:
    """Plan: ``.ok`` is true iff ``errors`` is empty; ``.exit_code`` 0 when ok else 1.

    The CLI's exit-2 for an unreadable config file is behaviour 21 and is NOT
    tested here — behaviour 2 only pins 0 and 1.
    """
    err = _diagnostic(severity=Severity.ERROR)
    warn = _diagnostic(severity=Severity.WARNING)
    report_with_errors = ConfigReport([err, warn])
    assert report_with_errors.ok is False
    assert report_with_errors.exit_code == 1
    warnings_only = ConfigReport([warn])
    # Warnings alone never make a report not-ok.
    assert warnings_only.ok is True
    assert warnings_only.exit_code == 0


# ---------------------------------------------------------------------------
# 7. ConfigReport.render() — exact block format, deterministic order, empty case
# ---------------------------------------------------------------------------

# Snapshot: the plan's "one block per diagnostic: severity + code, location,
# message, then an indented 'remedy:' line", rendered exactly like this.
# Pinned block format (one blank line between blocks; each block ends with a
# trailing newline; order per rule 2: (file, line or 0, code)):
#
#     ERROR TSWAP-C101 a.yaml:1
#     message…
#       remedy: …
#
#     WARNING TSWAP-C101 b.yaml
#     message…
#       remedy: …
#
#     ERROR TSWAP-C101 b.yaml:5
#     message…
#       remedy: …
#
_RENDER_SNAPSHOT = (
    "ERROR TSWAP-C101 a.yaml:1\n"
    "msg a-line1\n"
    "  remedy: fix a-line1\n"
    "\n"
    "WARNING TSWAP-C101 b.yaml\n"
    "msg b-no-line\n"
    "  remedy: fix b-no-line\n"
    "\n"
    "ERROR TSWAP-C101 b.yaml:5\n"
    "msg b-line5\n"
    "  remedy: fix b-line5\n"
)


def test_config_report_render_pins_exact_block_format() -> None:
    """Plan: one block per diagnostic — severity + code, location, message, then
    an indented ``remedy:`` line.

    Order per rule 2: ``a.yaml:1`` first (file sorts first), then ``b.yaml``
    (line None -> 0) before ``b.yaml:5`` — which also shows the severity does
    not change the order (the WARNING block sits between two ERROR blocks).
    The snapshot exercises all three Location render forms at once.
    """
    a = _diagnostic(
        severity=Severity.ERROR,
        message="msg a-line1",
        remedy="fix a-line1",
        location=_location(file="a.yaml", line=1),
    )
    b = _diagnostic(
        severity=Severity.WARNING,
        message="msg b-no-line",
        remedy="fix b-no-line",
        location=_location(file="b.yaml"),
    )
    c = _diagnostic(
        severity=Severity.ERROR,
        message="msg b-line5",
        remedy="fix b-line5",
        location=_location(file="b.yaml", line=5),
    )
    # Deliberately pass out of sort order.
    report = ConfigReport([c, a, b])
    assert report.render() == _RENDER_SNAPSHOT


def test_config_report_render_is_empty_string_for_empty_report() -> None:
    """Plan edge case: an empty report renders to the empty string, not "no errors".

    The caller owns the success message — the report never invents one.
    """
    assert ConfigReport().render() == ""


# ---------------------------------------------------------------------------
# 8. ConfigReport.to_json() — one report shape, three consumers
# ---------------------------------------------------------------------------


def _expected_json_object(code, severity, message, file, yaml_path, line, remedy):
    """Build the expected dict for one to_json() entry (pins the key set and types)."""
    return {
        "code": code,
        "severity": severity,  # pinned: lowercase string value of Severity
        "message": message,
        "file": file,
        "yaml_path": yaml_path,  # pinned: null/None when the path is unknown
        "line": line,  # pinned: null/None when the line is unknown
        "remedy": remedy,
    }


def test_config_report_to_json_pins_keys_and_serialization() -> None:
    """Plan: a list of objects with keys ``code, severity, message, file,
    yaml_path, line, remedy``.

    Severity is serialized as its lowercase string value.  Absent location
    parts are ``null``.  The content mirrors the human render (the *"one
    report shape, three consumers"* rule, ``plan/07_CLI_AND_OPS.md`` §6), and
    the order follows rule 2.
    """
    err = _diagnostic(
        severity=Severity.ERROR,
        message="msg a",
        remedy="fix a",
        location=_location(file="a.yaml", line=1),
    )
    warn = _diagnostic(
        severity=Severity.WARNING,
        message="msg b",
        remedy="fix b",
        location=_location(file="b.yaml", yaml_path="tools.cxr_to_embedding.ttl"),
    )
    report = ConfigReport([warn, err])
    loaded = json.loads(report.to_json())
    assert loaded == [
        _expected_json_object(
            "TSWAP-C101", "error", "msg a", "a.yaml", None, 1, "fix a"
        ),
        _expected_json_object(
            "TSWAP-C101",
            "warning",
            "msg b",
            "b.yaml",
            "tools.cxr_to_embedding.ttl",
            None,
            "fix b",
        ),
    ]
    # The key set is exact — no extras, none missing.
    assert set(loaded[0]) == {
        "code",
        "severity",
        "message",
        "file",
        "yaml_path",
        "line",
        "remedy",
    }


# ---------------------------------------------------------------------------
# 9. Empty report — render(), to_json(), .ok
# ---------------------------------------------------------------------------


def test_empty_report_to_json_is_empty_list_and_ok_is_true() -> None:
    """Plan edge case: empty report -> ``to_json() == []`` and ``.ok is True``.

    (The empty ``render()`` half of this case is pinned in
    ``test_config_report_render_is_empty_string_for_empty_report``.)
    """
    report = ConfigReport()
    assert report.to_json() == "[]"
    assert report.ok is True
    assert report.errors == []
    assert report.warnings == []


# ---------------------------------------------------------------------------
# 10. ConfigError carries a ConfigReport; no report-less form
# ---------------------------------------------------------------------------


def test_config_error_exposes_the_report_it_was_constructed_with() -> None:
    """Plan: ``ConfigError`` (the raised form) carries a ``ConfigReport``.

    Pinned attribute name: ``.report`` — the contract the GREEN step must
    meet.  Exception and report use the same data.
    """
    report = ConfigReport([_diagnostic(severity=Severity.ERROR)])
    exc = ConfigError(report)
    assert exc.report is report
    # It is raisable like any exception, carrying the report with it.
    with pytest.raises(ConfigError) as excinfo:
        raise exc
    assert excinfo.value.report is report


def test_config_error_without_report_is_a_programming_error() -> None:
    """Pinned: ``ConfigError`` always takes a report — there is no report-less form.

    A report-less ConfigError is a programming error, so the constructor
    raises ``TypeError`` when called with no arguments.
    """
    with pytest.raises(TypeError):
        ConfigError()


# ---------------------------------------------------------------------------
# 11. Diagnostic codes must match the documented pattern TSWAP-[CS]\d{3}
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_code",
    [
        "SWAP-C101",  # missing TSWAP prefix
        "TSWAP-c101",  # lowercase block letter
        "TSWAP-X101",  # undocumented block letter (only S and C exist)
        "TSWAP-C10",  # too few digits
        "TSWAP-C1011",  # too many digits
        "TSWAP-C101 ",  # trailing whitespace
    ],
)
def test_diagnostic_with_malformed_code_raises_value_error(bad_code) -> None:
    """Pinned: codes are "stable, greppable, documented" (plan line 26), so the
    format is validated AT CONSTRUCTION: a code not matching
    ``TSWAP-[CS]\\d{3}`` raises ``ValueError`` with a message that names the
    expected pattern (contains ``"TSWAP-"`` and ``"code"``).
    """
    with pytest.raises(ValueError) as excinfo:
        _diagnostic(code=bad_code)
    message = str(excinfo.value)
    assert "TSWAP-" in message
    assert "code" in message


@pytest.mark.parametrize(
    "good_code", ["TSWAP-C001", "TSWAP-C101", "TSWAP-C999", "TSWAP-S101"]
)
def test_diagnostic_with_valid_code_is_accepted(good_code) -> None:
    """Documented codes (C-blocks, S-blocks) construct fine."""
    assert _diagnostic(code=good_code).code == good_code


def test_valid_code_pattern_matches_documented_examples() -> None:
    """Sanity: the plan's example ``TSWAP-C101`` and the S-block match the pattern."""
    assert re.fullmatch(r"TSWAP-[CS]\d{3}", "TSWAP-C101") is not None
    assert re.fullmatch(r"TSWAP-[CS]\d{3}", "TSWAP-S101") is not None

r"""Tests for M1 behaviour 5 — ``${VAR}`` / ``${VAR:-default}`` interpolation.

See ``plans/m1-configuration.md`` §1, behaviour 5 (lines 107-123), and
assumption A10 (§5 table, maintainer-confirmed 2026-08-17): an
empty-but-set variable counts as SET.

This file is the RED step: the module under test,
``src/tool_swap/config/interpolate.py``, does not exist yet, so this file
fails collection with
``ModuleNotFoundError: No module named 'tool_swap.config.interpolate'``.
That is the *right* red reason: every test body below pins a concrete
behaviour the GREEN step must satisfy.

Pinned public API (the contract the GREEN step must meet verbatim):

- ``interpolate(text: str, env: Mapping[str, str], *, file: str = "<text>")
  -> Interpolated`` — operates on RAW TEXT before YAML parsing (plan line
  117) and never reads the ambient environment.  It RETURNS a result; it
  does not raise.  The caller (behaviour 6's loader) decides whether to
  raise ``ConfigError``.
- ``Interpolated`` — a small FROZEN dataclass with exactly two fields:
  - ``text: str`` — the interpolated text; when ``errors`` is non-empty
    this is the input text VERBATIM (the caller must not use it).
  - ``errors: list[Diagnostic]`` — all problems found in ONE pass (plan
    line 122: "All missing variables are reported together"); ``[]`` on
    success.
- Diagnostic codes pinned here:
  - ``TSWAP-C010`` — referenced variable unset and no default (code pinned
    by the plan, line 122); message names the variable; the remedy starts
    with ``set <VAR>`` and offers both the ``.env`` route and the
    ``${<VAR>:-}`` default route; the location carries the passed ``file``
    and the 1-based line of the reference.
  - ``TSWAP-C013`` — an unclosed ``${`` (no closing brace at depth 0,
    including a bare ``${``); the location names the 1-based line; the
    message says it is unclosed; the remedy names the closing brace.
    (C000-C004: behaviour 6; C010: this behaviour; C011/C012: behaviour 7
    — C013 is the first free C0xx.)
- Substitution quoting (injection safety, plan line 117): a substituted
  value is emitted as a plain scalar only when it is non-empty, matches
  ``^[A-Za-z0-9_~][A-Za-z0-9_~./-]*$``, is not a reserved YAML scalar
  (``null``/``~``/``true``/``false`` forms), and is not numeric; otherwise
  it is single-quoted (internal ``'`` doubled to ``''``) unless it
  contains ``\r`` or ``\n``, in which case it is double-quoted with the
  ``\\``, ``\"``, ``\n`` and ``\r`` escapes.  Pinned case by case below.
- Default-parsing rule (ambiguity resolved and pinned HERE, plan line 119
  edge case): a reference ends at the first ``}`` that returns brace depth
  to zero — depth starts at 1 after ``${``, each ``{`` increments, each
  ``}`` decrements.  Consequences: ``${X:-a:-b}`` → default ``a:-b``
  (``:-`` has no special meaning inside a default); ``${X:-{}}`` → default
  ``{}`` (balanced braces extend the default, no stray ``}`` in the
  output).  A ``{`` with no matching ``}`` before EOF is an unclosed
  reference (``TSWAP-C013``).
- ``$$`` escapes to a literal ``$`` on the final text, so it also works
  inside defaults: ``${X:-a$$b}`` → ``a$b`` (plan line 115).
- A bare ``$VAR`` without braces is left untouched (plan line 116).

Conventions: pytest, AAA pattern, Google-style docstrings, no
``warnings.warn`` (pyproject sets ``filterwarnings = "error"``).  ``yaml``
is used ONLY in the injection-safety round-trip assertions.
"""

from __future__ import annotations

import pytest
import yaml

from tool_swap.config.errors import Severity
from tool_swap.config.interpolate import Interpolated, interpolate

# Pinned default location.file when no file is passed (text-level API).
_DEFAULT_FILE = "<text>"

# Pinned diagnostic codes (see module docstring for the allocation).
_CODE_MISSING = "TSWAP-C010"
_CODE_UNCLOSED = "TSWAP-C013"


# ---------------------------------------------------------------------------
# Simple substitution and defaults
# ---------------------------------------------------------------------------


def test_interpolate_text_without_references_is_unchanged() -> None:
    """Text with no references is returned verbatim, no diagnostics."""
    text = "k: v\nplain: 1"
    result = interpolate(text, {})
    assert result.errors == []
    assert result.text == text


def test_interpolate_braced_var_substitutes_value_plain() -> None:
    """Plan line 111: ``${HF_TOKEN}`` -> the variable's value.

    Arrangement: env with ``HF_TOKEN`` set to a plain-safe token.
    Action: interpolate a YAML scalar position.
    Assertion: exact substituted text, no diagnostics.
    """
    result = interpolate("auth_token: ${HF_TOKEN}", {"HF_TOKEN": "sk-abc123"})
    assert result.errors == []
    assert result.text == "auth_token: sk-abc123"


def test_interpolate_var_with_empty_default_unset_yields_quoted_empty() -> None:
    """Plan line 112: ``${TSWAP_TOKEN:-}`` -> the empty string when unset.

    The empty value is single-quoted so ``auth_token:`` does not parse as
    null; ``''`` parses as the empty string.
    """
    result = interpolate("auth_token: ${TSWAP_TOKEN:-}", {})
    assert result.errors == []
    assert result.text == "auth_token: ''"
    assert yaml.safe_load(result.text) == {"auth_token": ""}


def test_interpolate_default_tilde_is_not_expanded() -> None:
    """Plan line 113: ``~`` in a default is literal (no path expansion).

    Path expansion is behaviour 7's job; the interpolator emits the
    default verbatim.  ``~/.cache/huggingface`` is plain-safe, so it is
    emitted unquoted and must parse back to the same string.
    """
    result = interpolate("hub: ${HF_HOME:-~/.cache/huggingface}", {})
    assert result.errors == []
    assert result.text == "hub: ~/.cache/huggingface"
    assert yaml.safe_load(result.text) == {"hub": "~/.cache/huggingface"}


def test_interpolate_default_ignored_when_var_set() -> None:
    """The default only applies when the variable is absent.

    Arrangement: ``${HF_HOME:-/x}`` with ``HF_HOME`` SET.
    Assertion: the variable's value wins; the default never appears.
    """
    result = interpolate("hub: ${HF_HOME:-/x}", {"HF_HOME": "hf-value"})
    assert result.errors == []
    assert result.text == "hub: hf-value"


def test_interpolate_multiple_references_in_one_scalar_all_substituted() -> None:
    """Plan line 114: all references in one scalar are substituted."""
    result = interpolate("s: a${X}b${Y}c", {"X": "foo", "Y": "bar"})
    assert result.errors == []
    assert result.text == "s: afoobbarc"


def test_interpolate_reference_inside_longer_string_substituted_in_place() -> None:
    """Plan line 114: ``${HF_HOME}/hub`` substitutes in place."""
    result = interpolate("path: ${HF_HOME}/hub", {"HF_HOME": "/data"})
    assert result.errors == []
    assert result.text == "path: /data/hub"
    assert yaml.safe_load(result.text) == {"path": "/data/hub"}


def test_interpolate_double_dollar_escapes_to_literal_dollar() -> None:
    """Plan line 115: ``$$`` -> a literal ``$`` (a lone ``$`` is quoted)."""
    result = interpolate("note: $$", {})
    assert result.errors == []
    assert result.text == "note: '$'"
    assert yaml.safe_load(result.text) == {"note": "$"}


def test_interpolate_bare_dollar_var_without_braces_is_untouched() -> None:
    """Plan line 116: only the braced form is a reference.

    ``$HOME`` with ``HOME`` set must come back byte-identical; silently
    interpolating a bare ``$`` would be a data-corruption bug.
    """
    text = "x: $HOME"
    result = interpolate(text, {"HOME": "/root"})
    assert result.errors == []
    assert result.text == text


# ---------------------------------------------------------------------------
# Injection safety (plan line 117): substituted values must stay a scalar
# ---------------------------------------------------------------------------


def test_interpolate_value_with_colon_space_is_quoted_and_stays_one_scalar() -> None:
    """Adversarial: ``HF_TOKEN='a: b'`` must not inject YAML structure.

    SAFETY PROPERTY: the substituted region is single-quoted so the whole
    value remains ONE scalar; the output parses to exactly one key whose
    value is the original string (no nested mapping, no ``b`` key).
    """
    result = interpolate("auth_token: ${HF_TOKEN}", {"HF_TOKEN": "a: b"})
    assert result.errors == []
    # Pinned quoting form: single-quoted (no ' inside the value).
    assert result.text == "auth_token: 'a: b'"
    parsed = yaml.safe_load(result.text)
    assert parsed == {"auth_token": "a: b"}
    assert isinstance(parsed["auth_token"], str)


def test_interpolate_value_with_newline_is_escaped_and_stays_one_scalar() -> None:
    r"""Adversarial: a value containing ``\n`` must not inject a new YAML
    line or structure.

    SAFETY PROPERTY: the value is double-quoted with a ``\n`` escape
    (single-quoted YAML would fold the newline to a space), so the output
    stays one line and parses back to the original string.
    """
    value = "line1\nline2"
    result = interpolate("auth_token: ${HF_TOKEN}", {"HF_TOKEN": value})
    assert result.errors == []
    assert result.text == 'auth_token: "line1\\nline2"'
    assert yaml.safe_load(result.text) == {"auth_token": "line1\nline2"}


def test_interpolate_value_with_crlf_is_escaped_and_stays_one_scalar() -> None:
    r"""A value containing ``\r\n`` uses ``\r\n`` escapes, one YAML line."""
    value = "line1\r\nline2"
    result = interpolate("auth_token: ${HF_TOKEN}", {"HF_TOKEN": value})
    assert result.errors == []
    assert result.text == 'auth_token: "line1\\r\\nline2"'
    assert yaml.safe_load(result.text) == {"auth_token": "line1\r\nline2"}


def test_interpolate_value_with_single_quote_doubles_the_quote() -> None:
    """Single-quoted YAML pins: an internal ``'`` is doubled to ``''``."""
    result = interpolate("k: ${V}", {"V": "it's"})
    assert result.errors == []
    assert result.text == "k: 'it''s'"
    assert yaml.safe_load(result.text) == {"k": "it's"}


def test_interpolate_value_with_double_quote_stays_single_quoted() -> None:
    """A ``"`` does not force double-quoting; single-quoting suffices."""
    result = interpolate("k: ${V}", {"V": 'say "hi"'})
    assert result.errors == []
    assert result.text == "k: 'say \"hi\"'"
    assert yaml.safe_load(result.text) == {"k": 'say "hi"'}


def test_interpolate_value_starting_with_hash_is_quoted() -> None:
    """A leading ``#`` would start a YAML comment; it must be quoted."""
    result = interpolate("k: ${V}", {"V": "#frag"})
    assert result.errors == []
    assert result.text == "k: '#frag'"
    assert yaml.safe_load(result.text) == {"k": "#frag"}


@pytest.mark.parametrize(
    ("value", "expected_text"),
    [
        ("123", "k: '123'"),
        ("null", "k: 'null'"),
        ("true", "k: 'true'"),
        ("a:b", "k: 'a:b'"),
    ],
)
def test_interpolate_scalar_coercing_values_are_quoted(
    value: str, expected_text: str
) -> None:
    """Values YAML would coerce must be quoted so they stay strings.

    ``123``/``null``/``true`` would parse as int/None/bool unquoted;
    ``a:b`` is plain-safe in YAML but the pinned plain-charset excludes
    ``:`` entirely (a stricter, simpler rule to implement).
    """
    result = interpolate("k: ${V}", {"V": value})
    assert result.errors == []
    assert result.text == expected_text
    assert yaml.safe_load(result.text) == {"k": value}


# ---------------------------------------------------------------------------
# Defaults containing special characters (plan line 119)
# ---------------------------------------------------------------------------


def test_interpolate_default_containing_colon_dash_ends_at_first_brace() -> None:
    """Parsing rule pinned here: the default runs to the closing brace.

    ``:-`` has no special meaning inside a default, so
    ``${X:-a:-b}`` with X absent yields ``a:-b``.
    """
    result = interpolate("k: ${X:-a:-b}", {})
    assert result.errors == []
    assert result.text == "k: 'a:-b'"
    assert yaml.safe_load(result.text) == {"k": "a:-b"}


def test_interpolate_default_with_balanced_nested_braces() -> None:
    """Parsing rule: balanced ``{`` inside a default extends the default.

    ``${X:-{}}``: depth goes 1 -> 2 -> 1 -> 0, so the default is ``{}``
    and the whole reference is consumed (no stray ``}`` in the output).
    """
    result = interpolate("k: ${X:-{}}", {})
    assert result.errors == []
    assert result.text == "k: '{}'"
    assert yaml.safe_load(result.text) == {"k": "{}"}


def test_interpolate_default_with_nested_braces_ignored_when_set() -> None:
    """With X set, ``${X:-{}}`` yields the value; the default is unused."""
    result = interpolate("k: ${X:-{}}", {"X": "v"})
    assert result.errors == []
    assert result.text == "k: v"


def test_interpolate_default_with_double_dollar_escapes() -> None:
    """``$$`` is processed on the final text, so it works in defaults."""
    result = interpolate("k: ${X:-a$$b}", {})
    assert result.errors == []
    assert result.text == "k: 'a$b'"
    assert yaml.safe_load(result.text) == {"k": "a$b"}


# ---------------------------------------------------------------------------
# Syntax errors: TSWAP-C013
# ---------------------------------------------------------------------------


def test_interpolate_unclosed_reference_reports_c013_naming_the_line() -> None:
    """Plan line 120: an unclosed ``${VAR`` is a syntax error, not a
    silent pass-through.

    Pinned: code ``TSWAP-C013`` (first free C0xx — C000-C004 are
    behaviour 6, C010 is behaviour 5, C011/C012 are behaviour 7), ERROR
    severity, the location names the 1-based line of the reference, the
    message says it is unclosed, and the remedy names the closing brace.
    """
    text = "a: 1\nb: ${UNCLOSED"
    result = interpolate(text, {}, file="tools.yaml")
    assert len(result.errors) == 1
    err = result.errors[0]
    assert err.code == _CODE_UNCLOSED
    assert err.severity is Severity.ERROR
    assert "unclosed" in err.message.lower()
    assert err.location.file == "tools.yaml"
    assert err.location.line == 2
    assert "}" in err.remedy
    assert result.text == text  # verbatim on error (pinned contract)


def test_interpolate_bare_dollar_brace_is_a_syntax_error() -> None:
    """A lone ``${`` (no name, no close) is still an unclosed reference."""
    text = "k: ${"
    result = interpolate(text, {})
    assert [d.code for d in result.errors] == [_CODE_UNCLOSED]
    assert result.errors[0].location.line == 1
    assert result.text == text


# ---------------------------------------------------------------------------
# Missing variables: TSWAP-C010 (code pinned by the plan, line 122)
# ---------------------------------------------------------------------------


def test_interpolate_missing_var_without_default_reports_c010() -> None:
    """Plan line 122: unset var, no default -> ``TSWAP-C010``.

    Pinned: ERROR severity, the message names the variable, and the
    remedy is actionable — it starts with ``set HF_TOKEN`` and offers
    both the ``.env`` route and the ``${HF_TOKEN:-}`` default route.
    The location carries the caller's file and the reference's 1-based
    line.
    """
    text = "a: 1\nauth_token: ${HF_TOKEN}"
    result = interpolate(text, {}, file="tools.yaml")
    assert len(result.errors) == 1
    err = result.errors[0]
    assert err.code == _CODE_MISSING
    assert err.severity is Severity.ERROR
    assert "HF_TOKEN" in err.message
    assert err.remedy.startswith("set HF_TOKEN")
    assert ".env" in err.remedy
    assert "${HF_TOKEN:-}" in err.remedy
    assert err.location.file == "tools.yaml"
    assert err.location.line == 2


def test_interpolate_missing_var_default_file_is_placeholder() -> None:
    """Without a ``file`` argument the location names the placeholder
    ``<text>`` (the API is text-level and does not invent a filename).
    """
    result = interpolate("k: ${NOPE}", {})
    assert result.errors[0].code == _CODE_MISSING
    assert result.errors[0].location.file == _DEFAULT_FILE


def test_interpolate_all_missing_vars_reported_together_in_one_call() -> None:
    """Plan line 122: all missing variables are reported together, not
    one per run — two unset vars yield exactly two C010 diagnostics.
    """
    text = "a: ${MISSING_A}\nb: ${MISSING_B}"
    result = interpolate(text, {}, file="tools.yaml")
    assert len(result.errors) == 2
    assert all(d.code == _CODE_MISSING for d in result.errors)
    assert {d.location.line for d in result.errors} == {1, 2}
    messages = " | ".join(d.message for d in result.errors)
    assert "MISSING_A" in messages
    assert "MISSING_B" in messages
    assert result.text == text


# ---------------------------------------------------------------------------
# A10 and the error-text contract
# ---------------------------------------------------------------------------


def test_interpolate_empty_but_set_counts_as_set_a10() -> None:
    """A10 (plan §5, maintainer-confirmed 2026-08-17): empty-but-set is
    SET.

    ``${TSWAP_TOKEN:-fallback}`` with ``TSWAP_TOKEN=""`` yields ``""``,
    NOT ``"fallback"`` — an explicitly empty token must not resurrect
    the default.  This is the one deliberate deviation from POSIX
    ``:-`` (which substitutes on unset OR empty); it is pinned here and
    documented.
    """
    result = interpolate("auth_token: ${TSWAP_TOKEN:-fallback}", {"TSWAP_TOKEN": ""})
    assert result.errors == []
    assert result.text == "auth_token: ''"


def test_interpolate_error_text_is_input_verbatim_and_must_not_be_used() -> None:
    """Pinned contract: when ``errors`` is non-empty, ``text`` is the
    input VERBATIM (references neither substituted nor blanked).

    Verbatim is the least surprising value to carry; the caller
    (behaviour 6) must not use the text when ``errors`` is non-empty.
    """
    text = "a: ${MISSING_ONE} and ${MISSING_TWO}"
    result = interpolate(text, {})
    assert result.errors
    assert result.text == text


# ---------------------------------------------------------------------------
# Result object shape
# ---------------------------------------------------------------------------


def test_interpolated_is_frozen_with_text_and_errors_fields() -> None:
    """Pinned shape of the result object: frozen, ``text`` + ``errors``.

    Arrangement: a directly constructed ``Interpolated``.
    Action: read the fields; attempt to mutate them.
    Assertion: fields are readable, ``errors`` is a list, and mutation
    raises ``AttributeError`` (frozen dataclass).
    """
    result = Interpolated(text="t", errors=[])
    assert result.text == "t"
    assert result.errors == []
    assert isinstance(result.errors, list)
    with pytest.raises(AttributeError):
        result.text = "other"
    with pytest.raises(AttributeError):
        result.errors = None

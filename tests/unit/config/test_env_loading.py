r"""Tests for M1 behaviour 7 — ``.env`` loading, merged before resolution.

See ``plans/m1-configuration.md`` §1, behaviour 7 (lines 137-147).

This file is the RED step for behaviour 7.  The module under test,
``src/tool_swap/config/loader.py``, already exists (behaviour 6), so the
``load_config`` import SUCCEEDS and this red is NOT a missing-module error.
The right red reasons are assertion-level:

- the current ``load_config`` has no ``env_file`` keyword, so every call
  that passes ``env_file=`` raises ``TypeError``;
- the current loader never reads a ``.env`` file, so a variable that lives
  only in ``.env`` stays unsubstituted and behaviour 5's ``TSWAP-C010`` is
  raised instead of the value resolving.

Tests that are already green in RED (they pin backward compatibility and
cannot fail before the GREEN step):

- ``test_load_config_env_kwarg_wins_over_dotenv`` — the ``env`` kwarg
  already beats a non-existent ``.env`` trivially;
- ``test_load_config_missing_auto_discovered_env_is_not_an_error`` — a
  missing ``.env`` is already a non-event because nothing reads it yet.

Pinned public API (the contract the GREEN step must meet verbatim):

- ``load_config(path: Path, *, env: Mapping[str, str] | None = None,
  env_file: Path | None = None) -> LoadedConfig`` — the behaviour 6
  signature EXTENDED with one keyword-only parameter, ``env_file``,
  defaulting to ``None``; NO other new parameter exists (pinned by a
  signature-guard test, which also keeps the tool-config ``env_file:``
  key out of this behaviour — plan line 145).
  - ``env_file=None``: a ``.env`` next to the config file
    (``path.parent / ".env"``) is loaded automatically IF PRESENT; a
    missing ``.env`` is NOT an error (plan line 144).
  - ``env_file`` given: that file is used INSTEAD of the auto-discovered
    one (the auto-discovered ``.env`` is NOT also read); a missing
    explicitly-requested file is an error (plan line 140, 144).
  - Precedence (plan line 142): the real process environment —
    represented in tests by the injected ``env`` kwarg — WINS over
    ``.env``: the merged mapping handed to interpolation is
    ``{**env_from_dotenv, **env}``.
- ``.env`` values are visible to interpolation (behaviour 5): a
  ``.env``-only variable resolves in the config (plan line 143).
- ``.env`` values do NOT leak into the returned ``data`` or into
  diagnostics of a successful load — interpolation-only.
- ``.env`` format (python-dotenv-compatible, pinned by substitution
  assertions, not by parser internals): ``KEY=value`` lines,
  ``export KEY=value`` prefixes, ``#`` comments (a commented-out
  ``KEY=...`` must NOT set the variable), blank lines, double-quoted
  values (quotes stripped, a value containing ``=`` survives intact),
  single-quoted values (quotes stripped).
- Diagnostic codes and message substrings pinned here:
  - ``TSWAP-C011`` — an explicitly requested ``env_file`` does not
    exist; message names the RESOLVED ABSOLUTE path
    (``str(env_file.resolve())``), matching the C000 convention.
  - ``TSWAP-C012`` — an unparseable ``.env`` line; the pinned malformed
    line is ``=value`` (no key) on line 2 of the ``.env`` file; the
    diagnostic's ``location.line`` is 2, its message contains the line
    number ("2") AND the offending content ("=value") (plan line 146).
- All fatal diagnostics have ``severity`` ERROR, and the loader RAISES
  ``ConfigError`` (from ``tool_swap.config.errors``) carrying a
  ``ConfigReport`` whose ``errors`` list holds the diagnostic — same
  raising convention as behaviour 6.

Ambiguities resolved and pinned here (flagged in the report):
- "Unparseable ``.env`` line" is pinned concretely as a line with no key
  (``=value``); the diagnostic must carry both the 1-based line number
  (via ``location.line == 2`` and "2" in the message) and the content
  ("=value" in the message).
- When ``env_file`` is given, the auto-discovered ``.env`` next to the
  config is skipped entirely — pinned by asserting that a variable
  present ONLY in the auto-discovered ``.env`` raises ``TSWAP-C010``.
- ``.env`` auto-discovery is exactly ``path.parent / ".env"``: no upward
  directory search and no CWD search (the tests write ``.env`` only next
  to the config and expect it found; nothing else is written).
- Quote handling: quotes are stripped; no backslash escape sequences are
  pinned (out of scope for the behaviour).

Conventions: pytest, AAA pattern, snake_case, Google-style docstrings,
``tmp_path`` for every file, no ``warnings.warn`` (pyproject sets
``filterwarnings = "error"``).
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from tool_swap.config.errors import ConfigError, Diagnostic, Severity
from tool_swap.config.loader import LoadedConfig, load_config

# Pinned diagnostic codes (see module docstring for the allocation).
_CODE_MISSING_VAR = "TSWAP-C010"  # behaviour 5, surfaced through the loader
_CODE_ENV_FILE_MISSING = "TSWAP-C011"  # behaviour 7: explicit env_file missing
_CODE_ENV_PARSE = "TSWAP-C012"  # behaviour 7: unparseable .env line

# A minimal config with no ${...} references (behaviour 23 shape).
MINIMAL_CONFIG = (
    "tools:\n"
    "  echo:\n"
    "    path: ./tools/echo\n"
)

# The pinned malformed .env line for C012 (plan line 146).
MALFORMED_ENV_LINE = "=value"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, text: str) -> Path:
    """Write ``text`` (UTF-8) to ``tmp_path/name`` and return the path."""
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _error_for(exc: ConfigError, code: str) -> Diagnostic:
    """Return the single ERROR diagnostic with ``code`` in the report.

    Fails loudly when a different number of diagnostics with that code
    is present, so the GREEN step cannot hide a problem among extras.
    """
    matches = [
        d
        for d in exc.report.errors
        if d.code == code and d.severity is Severity.ERROR
    ]
    assert len(matches) == 1, (
        f"expected exactly one {code} error diagnostic, "
        f"got: {exc.report.diagnostics!r}"
    )
    return matches[0]


def _config_with_ref(var: str) -> str:
    """Return a minimal config whose single env value references ``${var}``."""
    return "tools:\n  echo:\n    env:\n      token: ${" + var + "}\n"


# ---------------------------------------------------------------------------
# 1+4. Auto-discovered .env next to the config; a .env-only var resolves
# ---------------------------------------------------------------------------


def test_load_config_auto_discovered_env_next_to_config_loads(tmp_path: Path) -> None:
    """Plan lines 140-143: a ``.env`` next to the config file is loaded
    automatically and a ``.env``-only variable resolves (no ``env`` kwarg).
    """
    # Arrange: .env and tools.yaml in the same directory, no env kwarg.
    _write(tmp_path, ".env", "HF_TOKEN=abc\n")
    path = _write(tmp_path, "tools.yaml", _config_with_ref("HF_TOKEN"))

    # Act.
    result: LoadedConfig = load_config(path)

    # Assert: the .env-only variable was substituted by interpolation.
    assert result.data == {"tools": {"echo": {"env": {"token": "abc"}}}}
    assert result.diagnostics == []


# ---------------------------------------------------------------------------
# 2. env_file kwarg replaces (not augments) the auto-discovered .env
# ---------------------------------------------------------------------------


def test_load_config_env_file_kwarg_replaces_auto_discovered_env(
    tmp_path: Path,
) -> None:
    """Plan line 140: ``env_file=`` uses that file INSTEAD of the
    auto-discovered ``.env`` — the auto-discovered one is NOT also read.
    """
    # Arrange: both an auto-discovered .env and an explicit env file,
    # with disjoint variable sets so the source of each value is observable.
    _write(tmp_path, ".env", "SHARED=from_dotenv\nAUTO_ONLY=auto\n")
    env_file = _write(tmp_path, "other.env", "SHARED=from_env_file\n")

    # Act 1: a variable in the explicit file resolves to its value.
    path = _write(tmp_path, "tools.yaml", _config_with_ref("SHARED"))
    result = load_config(path, env_file=env_file)

    # Assert 1: the explicit file's value won (not the .env's "from_dotenv").
    assert result.data == {
        "tools": {"echo": {"env": {"token": "from_env_file"}}}
    }

    # Act 2: a variable ONLY in the auto-discovered .env.
    path2 = _write(tmp_path, "tools2.yaml", _config_with_ref("AUTO_ONLY"))

    # Assert 2: it does NOT resolve -> the auto-discovered .env was not
    # merged, so behaviour 5's C010 names the variable.
    with pytest.raises(ConfigError) as exc_info:
        load_config(path2, env_file=env_file)
    diagnostic = _error_for(exc_info.value, _CODE_MISSING_VAR)
    assert "AUTO_ONLY" in diagnostic.message


# ---------------------------------------------------------------------------
# 3. Precedence: the env kwarg (process environment) wins over .env
# ---------------------------------------------------------------------------


def test_load_config_env_kwarg_wins_over_dotenv(tmp_path: Path) -> None:
    """Plan line 142: a var set in BOTH ``.env`` and the ``env`` kwarg
    resolves to the kwarg's value (the real process environment wins).
    """
    # Arrange: the variable is set in both .env and the injected env.
    _write(tmp_path, ".env", "HF_TOKEN=from_dotenv\n")
    path = _write(tmp_path, "tools.yaml", _config_with_ref("HF_TOKEN"))

    # Act.
    result = load_config(path, env={"HF_TOKEN": "from_env"})

    # Assert: the env kwarg's value won.
    assert result.data == {
        "tools": {"echo": {"env": {"token": "from_env"}}}
    }


# ---------------------------------------------------------------------------
# 5. Missing auto-discovered .env is not an error
# ---------------------------------------------------------------------------


def test_load_config_missing_auto_discovered_env_is_not_an_error(
    tmp_path: Path,
) -> None:
    """Plan line 144: no ``.env`` next to the config and no ``env_file``
    -> the config loads fine; ``.env`` is optional.
    """
    # Arrange: only the config file, no .env anywhere.
    path = _write(tmp_path, "tools.yaml", MINIMAL_CONFIG)

    # Act.
    result = load_config(path)

    # Assert.
    assert result.data == {"tools": {"echo": {"path": "./tools/echo"}}}
    assert result.diagnostics == []


# ---------------------------------------------------------------------------
# 6. Missing explicitly-requested env_file -> TSWAP-C011
# ---------------------------------------------------------------------------


def test_load_config_missing_explicit_env_file_raises_c011(tmp_path: Path) -> None:
    """Plan line 144: a missing explicitly-requested ``env_file`` is an
    error, TSWAP-C011, naming the (resolved) path.
    """
    # Arrange: an env file path that does not exist.
    path = _write(tmp_path, "tools.yaml", MINIMAL_CONFIG)
    missing = tmp_path / "nope.env"

    # Act.
    with pytest.raises(ConfigError) as exc_info:
        load_config(path, env_file=missing)

    # Assert: exactly one C011, message names the resolved absolute path.
    diagnostic = _error_for(exc_info.value, _CODE_ENV_FILE_MISSING)
    assert str(missing.resolve()) in diagnostic.message


# ---------------------------------------------------------------------------
# 7. Unparseable .env line -> TSWAP-C012 naming line number and content
# ---------------------------------------------------------------------------


def test_load_config_unparseable_env_line_raises_c012(tmp_path: Path) -> None:
    """Plan line 146: an unparseable ``.env`` line is an error, TSWAP-C012,
    naming the line number and the content.  The pinned malformed line is
    ``=value`` (no key) on line 2 of the file.
    """
    # Arrange: line 1 is valid, line 2 has no key.
    _write(tmp_path, ".env", "GOOD=ok\n" + MALFORMED_ENV_LINE + "\n")
    path = _write(tmp_path, "tools.yaml", MINIMAL_CONFIG)

    # Act.
    with pytest.raises(ConfigError) as exc_info:
        load_config(path)

    # Assert: exactly one C012; location.line is 2; the message contains
    # both the line number and the offending content.
    diagnostic = _error_for(exc_info.value, _CODE_ENV_PARSE)
    assert diagnostic.location.line == 2
    assert "2" in diagnostic.message
    assert MALFORMED_ENV_LINE in diagnostic.message


# ---------------------------------------------------------------------------
# 8. .env format: KEY=value, export prefix, comments, blanks, quoting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("env_text", "var", "expected"),
    [
        pytest.param(
            "PLAIN=plain value\n",
            "PLAIN",
            "plain value",
            id="key-value",
        ),
        pytest.param(
            "export EXPORTED=exported value\n",
            "EXPORTED",
            "exported value",
            id="export-prefix",
        ),
        pytest.param(
            '# header comment\n\nSPACED=spaced value\n\n',
            "SPACED",
            "spaced value",
            id="comments-and-blank-lines",
        ),
        pytest.param(
            'EQ="quoted with = sign"\n',
            "EQ",
            "quoted with = sign",
            id="double-quoted-with-equals",
        ),
        pytest.param(
            "SINGLE='single quoted'\n",
            "SINGLE",
            "single quoted",
            id="single-quoted",
        ),
    ],
)
def test_load_config_env_format_variants_resolve(
    tmp_path: Path,
    env_text: str,
    var: str,
    expected: str,
) -> None:
    """Plan line 145: python-dotenv-compatible lines parse and the value
    reaches interpolation: ``KEY=value``, ``export KEY=value``, comments
    and blank lines, double-quoted values containing ``=``, single-quoted
    values (quotes stripped in both quoting styles).
    """
    # Arrange.
    _write(tmp_path, ".env", env_text)
    path = _write(tmp_path, "tools.yaml", _config_with_ref(var))

    # Act.
    result = load_config(path)

    # Assert: the parsed value was substituted into the config.
    assert result.data == {"tools": {"echo": {"env": {"token": expected}}}}


def test_load_config_env_commented_out_variable_is_not_set(tmp_path: Path) -> None:
    """Plan line 145: a ``# KEY=...`` comment does NOT set the variable —
    pinned with a ``${COMMENTED:-absent}`` default that must survive.
    """
    # Arrange.
    _write(tmp_path, ".env", "# COMMENTED=hidden\nVISIBLE=visible\n")
    config = (
        "tools:\n"
        "  echo:\n"
        "    env:\n"
        "      visible: ${VISIBLE}\n"
        "      commented: ${COMMENTED:-absent}\n"
    )
    path = _write(tmp_path, "tools.yaml", config)

    # Act.
    result = load_config(path)

    # Assert: the commented-out variable fell back to its default.
    assert result.data == {
        "tools": {"echo": {"env": {"visible": "visible", "commented": "absent"}}}
    }


# ---------------------------------------------------------------------------
# 9. .env values do not leak into data or diagnostics
# ---------------------------------------------------------------------------


def test_load_config_dotenv_values_do_not_leak_into_data_or_diagnostics(
    tmp_path: Path,
) -> None:
    """Plan line 143: ``.env`` values are only used for interpolation —
    they do not appear in the returned ``data`` (beyond the substituted
    value) and nowhere in the diagnostics of a successful load.
    """
    # Arrange: .env holds a referenced var and one that is never referenced.
    _write(tmp_path, ".env", "HF_TOKEN=abc\nLEAK_VAR=must-not-appear\n")
    path = _write(tmp_path, "tools.yaml", _config_with_ref("HF_TOKEN"))

    # Act.
    result = load_config(path)

    # Assert: data contains exactly the config's own keys; the never
    # referenced .env variable is absent.
    assert result.data == {"tools": {"echo": {"env": {"token": "abc"}}}}
    assert "LEAK_VAR" not in str(result.data)

    # Assert: a clean load has no diagnostics at all, so the .env file
    # name appears in none of them.
    assert result.diagnostics == []
    for d in result.diagnostics:
        assert ".env" not in d.message
        assert ".env" not in d.location.file


# ---------------------------------------------------------------------------
# 10. Signature guard: env_file is the ONLY env-file mechanism on load_config
# ---------------------------------------------------------------------------


def test_load_config_signature_pins_env_file_as_only_env_file_parameter() -> None:
    """Plan line 145: the loader's ``env_file`` kwarg and ``.env``
    auto-discovery are the ONLY env-file mechanisms in this behaviour —
    the tool-config ``env_file:`` key is a different, later concern.
    Pinned: ``load_config`` has exactly the parameters ``path`` (positional),
    ``env`` (keyword-only, default None) and ``env_file`` (keyword-only,
    default None); no other parameter exists.
    """
    # Arrange.
    params = inspect.signature(load_config).parameters

    # Assert: the exact parameter set, kinds, and defaults.
    assert set(params) == {"path", "env", "env_file"}
    assert params["path"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert params["env"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["env"].default is None
    assert params["env_file"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["env_file"].default is None

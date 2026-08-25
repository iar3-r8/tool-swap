r"""Tests for M1 behaviour 6 — the YAML loader.

See ``plans/m1-configuration.md`` §1, behaviour 6 (lines 125-135), the
diagnostic code table (lines 39-47), and behaviour 23's minimal config
(lines 375-380).

This file is the RED step: the module under test,
``src/tool_swap/config/loader.py``, does not exist yet, so this file
fails collection with
``ModuleNotFoundError: No module named 'tool_swap.config.loader'``.
That is the *right* red reason: every test body below pins a concrete
behaviour the GREEN step must satisfy.

Pinned public API (the contract the GREEN step must meet verbatim):

- ``load_config(path: Path, *, env: Mapping[str, str] | None = None)
  -> LoadedConfig`` — reads the file at ``path``, runs behaviour 5's
  ``interpolate`` on the raw text with the injected ``env`` (``None``
  means the EMPTY mapping; the loader never reads the ambient process
  environment), parses the YAML, tracks source lines, and returns a
  ``LoadedConfig``.  For every fatal C0xx case (C000 not found, C001
  syntax error, C002 duplicate key, C003 empty file, C004 non-mapping
  root, C010 missing env var) it RAISES ``ConfigError`` (from
  ``tool_swap.config.errors``) carrying a ``ConfigReport`` whose
  ``errors`` list holds the diagnostic(s).  Exit code 2 is the CLI's
  concern (behaviour 21), not the loader's.
- ``LoadedConfig`` — a FROZEN dataclass with exactly three fields:
  - ``data: dict`` — the parsed top-level mapping (line info kept OUT
    of this dict; behaviour 4's Pydantic layer receives it as-is).
  - ``path: Path`` — the path as passed to ``load_config``.
  - ``diagnostics: list[Diagnostic]`` — non-fatal notes; ``[]`` on a
    clean load.
- Line tracking: ``LoadedConfig.line_for(yaml_path: str) -> int | None``
  — returns the 1-based source line of the key named by the DOTTED
  yaml path (e.g. ``"tools"``, ``"tools.example_echo"``,
  ``"tools.example_echo.path"``), or ``None`` when the path does not
  exist in the loaded data.
- Diagnostic codes and message substrings pinned here (loader-owned
  C0xx block; C010 is behaviour 5's code, surfaced through the loader):
  - ``TSWAP-C000`` — file not found; message names the RESOLVED
    ABSOLUTE path (``str(path.resolve())``); remedy contains
    ``create tools.yaml`` and ``--config``.
  - ``TSWAP-C001`` — YAML syntax error; location.line/column match the
    parser's problem mark; the message echoes the offending line's
    text and contains a ``^`` caret beneath it.
  - ``TSWAP-C002`` — duplicate key in one mapping (an ERROR, not
    last-wins); message names the key; location.line is the duplicate
    (second) occurrence's line.
  - ``TSWAP-C003`` — empty file; message contains ``empty`` and names
    the ``tools:`` block as the minimal fix.
  - ``TSWAP-C004`` — top level is not a mapping; message names what
    was found (``list`` / ``scalar``).
  - ``TSWAP-C010`` — missing env var (no default), produced by
    behaviour 5's ``interpolate`` and raised by the loader; message
    names the variable.
  All fatal diagnostics have ``severity`` ERROR and
  ``location.file == str(path.resolve())``.

Ambiguities resolved and pinned here (flagged in the report):
- The plan calls the fixture the "five-line" config, but the snippet
  at plan lines 376-380 is 3 lines; the tests use the snippet
  verbatim and pin line numbers against it (1/2/3).
- ``line_for`` takes a dotted path and returns the key's line for
  BOTH mapping keys and leaf keys.
- "The offending line echoed with a caret" means the diagnostic
  message itself contains the offending line's text and a ``^``
  character (the classic ``expected <block end>`` style echo).

Conventions: pytest, AAA pattern, snake_case, Google-style
docstrings, ``tmp_path`` for every file, no ``warnings.warn``
(pyproject sets ``filterwarnings = "error"``).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from tool_swap.config.errors import ConfigError, Diagnostic, Severity
from tool_swap.config.loader import LoadedConfig, load_config

# Pinned diagnostic codes (see module docstring for the allocation).
_CODE_NOT_FOUND = "TSWAP-C000"
_CODE_SYNTAX = "TSWAP-C001"
_CODE_DUPLICATE = "TSWAP-C002"
_CODE_EMPTY = "TSWAP-C003"
_CODE_NON_MAPPING = "TSWAP-C004"
_CODE_MISSING_VAR = "TSWAP-C010"

# The minimal config from plan lines 376-380 (behaviour 23), verbatim.
MINIMAL_CONFIG = (
    "tools:\n"
    "  example_echo:\n"
    "    path: ./tools/example_echo\n"
)


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


# ---------------------------------------------------------------------------
# Golden path: the minimal config loads
# ---------------------------------------------------------------------------


def test_load_config_minimal_config_loads_expected_mapping(
    tmp_path: Path,
) -> None:
    """Plan line 129: the minimal config loads to the expected mapping.

    The ``path:`` value is NOT resolved here (that is behaviour 8);
    the loader just reads it.
    """
    # Arrange: the minimal config from plan lines 376-380.
    path = _write(tmp_path, "tools.yaml", MINIMAL_CONFIG)

    # Act.
    result: LoadedConfig = load_config(path)

    # Assert: exact mapping, path echo, no non-fatal diagnostics.
    assert result.data == {
        "tools": {"example_echo": {"path": "./tools/example_echo"}}
    }
    assert result.data["tools"]["example_echo"]["path"] == (
        "./tools/example_echo"
    )
    assert result.path == path
    assert result.diagnostics == []


def test_load_config_env_none_means_empty_mapping(tmp_path: Path) -> None:
    """``env=None`` behaves like ``env={}`` (ambient env is never read).

    A file referencing an unset var with a default loads fine with no
    env argument, so the loader cannot be silently drawing on the
    process environment.
    """
    # Arrange: a reference that has a default, loaded without env.
    path = _write(tmp_path, "tools.yaml", "tools:\n  t:\n    name: ${X:-n}\n")

    # Act.
    result = load_config(path)

    # Assert: the default was used, proving env=None == empty mapping.
    assert result.data["tools"]["t"]["name"] == "n"


# ---------------------------------------------------------------------------
# Source-line tracking (plan line 130)
# ---------------------------------------------------------------------------


def test_load_config_line_for_reports_key_source_lines(
    tmp_path: Path,
) -> None:
    """Plan line 130: every mapping node carries its source line.

    Pinned mechanism: ``LoadedConfig.line_for(dotted_path)``.  For the
    minimal config the keys sit on lines 1, 2 and 3.
    """
    # Arrange.
    path = _write(tmp_path, "tools.yaml", MINIMAL_CONFIG)

    # Act.
    result = load_config(path)

    # Assert: mapping keys and the leaf key all report their lines.
    assert result.line_for("tools") == 1
    assert result.line_for("tools.example_echo") == 2
    assert result.line_for("tools.example_echo.path") == 3


def test_load_config_line_for_unknown_path_returns_none(
    tmp_path: Path,
) -> None:
    """A dotted path absent from the data returns ``None``."""
    # Arrange.
    path = _write(tmp_path, "tools.yaml", MINIMAL_CONFIG)

    # Act.
    result = load_config(path)

    # Assert.
    assert result.line_for("nope") is None
    assert result.line_for("tools.example_echo.nope") is None
    assert result.line_for("tools.example_echo.path.deeper") is None


# ---------------------------------------------------------------------------
# Anchors, aliases, and top-level ``x-`` keys (plan line 131)
# ---------------------------------------------------------------------------


def test_load_config_anchor_and_alias_resolve(tmp_path: Path) -> None:
    """Plan line 131: YAML anchors/aliases resolve (``&``/``*``)."""
    # Arrange: an anchor defined at the top level, aliased in a tool.
    path = _write(
        tmp_path,
        "tools.yaml",
        "common: &c\n  ttl: 300\ntools:\n  t1:\n    base: *c\n",
    )

    # Act.
    result = load_config(path)

    # Assert: the alias resolves to the anchored mapping.
    assert result.data["tools"]["t1"]["base"] == {"ttl": 300}


def test_load_config_top_level_x_key_kept_in_data(tmp_path: Path) -> None:
    """Plan line 131: a top-level ``x-`` key is accepted and kept.

    The loader does NOT drop it (``extra="forbid"`` at the schema
    layer is behaviour 4's concern); it does not raise, and the
    ``x-defaults`` anchor idiom from the examples works.
    """
    # Arrange: the documented ``x-defaults`` anchor idiom with a merge.
    path = _write(
        tmp_path,
        "tools.yaml",
        "x-defaults: &x_defaults\n"
        "  ttl: 300\n"
        "tools:\n"
        "  t1:\n"
        "    <<: *x_defaults\n",
    )

    # Act (must not raise).
    result = load_config(path)

    # Assert: the x- key is present in data and the merge resolved.
    assert "x-defaults" in result.data
    assert result.data["x-defaults"] == {"ttl": 300}
    assert result.data["tools"]["t1"]["ttl"] == 300


# ---------------------------------------------------------------------------
# Duplicate keys (plan line 132)
# ---------------------------------------------------------------------------


def test_load_config_duplicate_key_raises_c002(tmp_path: Path) -> None:
    """Plan line 132: duplicate keys in one mapping are ``TSWAP-C002``.

    PyYAML's default is last-wins (silently); the loader must instead
    raise an ERROR naming the key and the duplicate's line.
    """
    # Arrange: two ``ttl:`` keys under the same tool (lines 3 and 4).
    path = _write(
        tmp_path,
        "tools.yaml",
        "tools:\n  t:\n    ttl: 300\n    ttl: 600\n",
    )

    # Act.
    with pytest.raises(ConfigError) as exc_info:
        load_config(path)

    # Assert: exactly one C002 ERROR, naming the key and the 2nd line.
    diag = _error_for(exc_info.value, _CODE_DUPLICATE)
    assert "ttl" in diag.message
    assert diag.location.file == str(path.resolve())
    assert diag.location.line == 4
    assert diag.remedy.strip()


# ---------------------------------------------------------------------------
# Empty file and non-mapping root (plan line 133)
# ---------------------------------------------------------------------------


def test_load_config_empty_file_raises_c003(tmp_path: Path) -> None:
    """Plan line 133: empty file -> ``TSWAP-C003`` with an actionable msg."""
    # Arrange.
    path = _write(tmp_path, "tools.yaml", "")

    # Act.
    with pytest.raises(ConfigError) as exc_info:
        load_config(path)

    # Assert: the pinned message content (plan line 133's sentence).
    diag = _error_for(exc_info.value, _CODE_EMPTY)
    assert "empty" in diag.message.lower()
    assert "tools:" in diag.message
    assert diag.location.file == str(path.resolve())
    assert diag.remedy.strip()


def test_load_config_list_root_raises_c004(tmp_path: Path) -> None:
    """Plan line 133: top level is a list -> ``TSWAP-C004`` naming it."""
    # Arrange.
    path = _write(tmp_path, "tools.yaml", "- a\n- b\n")

    # Act.
    with pytest.raises(ConfigError) as exc_info:
        load_config(path)

    # Assert.
    diag = _error_for(exc_info.value, _CODE_NON_MAPPING)
    assert "list" in diag.message.lower()
    assert diag.location.file == str(path.resolve())
    assert diag.remedy.strip()


def test_load_config_scalar_root_raises_c004(tmp_path: Path) -> None:
    """Plan line 133: top level is a scalar -> ``TSWAP-C004`` naming it."""
    # Arrange.
    path = _write(tmp_path, "tools.yaml", "just a string\n")

    # Act.
    with pytest.raises(ConfigError) as exc_info:
        load_config(path)

    # Assert.
    diag = _error_for(exc_info.value, _CODE_NON_MAPPING)
    assert "scalar" in diag.message.lower()
    assert diag.location.file == str(path.resolve())
    assert diag.remedy.strip()


# ---------------------------------------------------------------------------
# Encoding robustness (plan line 133)
# ---------------------------------------------------------------------------


def test_load_config_utf8_bom_is_tolerated(tmp_path: Path) -> None:
    """Plan line 133: a UTF-8 BOM prefix loads identically to no BOM."""
    # Arrange: the same content with and without a BOM.
    plain = _write(tmp_path, "plain.yaml", MINIMAL_CONFIG)
    bom_path = tmp_path / "bom.yaml"
    bom_path.write_bytes(b"\xef\xbb\xbf" + MINIMAL_CONFIG.encode("utf-8"))

    # Act.
    plain_result = load_config(plain)
    bom_result = load_config(bom_path)

    # Assert: identical parsed data despite the BOM.
    assert bom_result.data == plain_result.data
    assert bom_result.data["tools"]["example_echo"]["path"] == (
        "./tools/example_echo"
    )


def test_load_config_crlf_does_not_shift_line_numbers(tmp_path: Path) -> None:
    """Plan line 133: CRLF line endings do not shift reported lines."""
    # Arrange: the minimal config with and without CRLF endings.
    lf = _write(tmp_path, "lf.yaml", MINIMAL_CONFIG)
    crlf = _write(
        tmp_path, "crlf.yaml", MINIMAL_CONFIG.replace("\n", "\r\n")
    )

    # Act.
    lf_result = load_config(lf)
    crlf_result = load_config(crlf)

    # Assert: identical data AND identical reported line numbers.
    assert crlf_result.data == lf_result.data
    for yaml_path in ("tools", "tools.example_echo", "tools.example_echo.path"):
        assert crlf_result.line_for(yaml_path) == lf_result.line_for(yaml_path)
    assert crlf_result.line_for("tools") == 1
    assert crlf_result.line_for("tools.example_echo") == 2
    assert crlf_result.line_for("tools.example_echo.path") == 3


# ---------------------------------------------------------------------------
# File not found (plan line 134)
# ---------------------------------------------------------------------------


def test_load_config_missing_file_raises_c000(tmp_path: Path) -> None:
    """Plan line 134: file not found -> ``TSWAP-C000`` with a remedy.

    The message names the RESOLVED ABSOLUTE path and the remedy offers
    both the ``create tools.yaml`` and the ``--config`` routes.
    """
    # Arrange: a path that does not exist.
    path = tmp_path / "does_not_exist.yaml"

    # Act.
    with pytest.raises(ConfigError) as exc_info:
        load_config(path)

    # Assert.
    diag = _error_for(exc_info.value, _CODE_NOT_FOUND)
    assert str(path.resolve()) in diag.message
    assert "create tools.yaml" in diag.remedy
    assert "--config" in diag.remedy


# ---------------------------------------------------------------------------
# YAML syntax error (plan line 134)
# ---------------------------------------------------------------------------


def test_load_config_yaml_syntax_error_raises_c001(tmp_path: Path) -> None:
    """Plan line 134: YAML syntax error -> ``TSWAP-C001`` with line + caret.

    The pinned malformed file::

        tools:      line 1
          a: b      line 2
         c: d       line 3  <- bad indentation

    PyYAML's problem mark is line 3, column 2; the message must echo
    the offending line's text (``c: d``) with a ``^`` caret.
    """
    # Arrange.
    path = _write(tmp_path, "tools.yaml", "tools:\n  a: b\n c: d\n")

    # Act.
    with pytest.raises(ConfigError) as exc_info:
        load_config(path)

    # Assert: parser's line/column, offending line echoed, caret present.
    diag = _error_for(exc_info.value, _CODE_SYNTAX)
    assert diag.location.file == str(path.resolve())
    assert diag.location.line == 3
    assert diag.location.column == 2
    assert "c: d" in diag.message
    assert "^" in diag.message


# ---------------------------------------------------------------------------
# Interpolation wiring (plan line 122, behaviour 5 -> behaviour 6)
# ---------------------------------------------------------------------------


def test_load_config_missing_env_var_surfaces_c010(tmp_path: Path) -> None:
    """A missing env var (no default) surfaces ``TSWAP-C010`` via the loader.

    Interpolation runs inside the loader, so the behaviour-5 C010
    diagnostic is raised as a ``ConfigError`` carrying the report.
    """
    # Arrange: a reference to an unset variable with no default.
    path = _write(
        tmp_path,
        "tools.yaml",
        "tools:\n  t:\n    env:\n      X: ${UNSET_VAR}\n",
    )

    # Act.
    with pytest.raises(ConfigError) as exc_info:
        load_config(path, env={})

    # Assert: the C010 diagnostic names the variable and its line.
    diag = _error_for(exc_info.value, _CODE_MISSING_VAR)
    assert "UNSET_VAR" in diag.message
    assert diag.location.line == 4
    assert diag.remedy.strip()


def test_load_config_env_var_set_substitutes_in_data(tmp_path: Path) -> None:
    """Interpolation runs in the loader: a set var lands in ``data``.

    This is the wiring check for behaviour 5 -> 6 (not a re-test of
    interpolation semantics): the substituted value appears in the
    parsed mapping.
    """
    # Arrange: the same reference, this time with the variable set.
    path = _write(
        tmp_path,
        "tools.yaml",
        "tools:\n  t:\n    env:\n      X: ${UNSET_VAR}\n",
    )

    # Act.
    result: LoadedConfig = load_config(path, env={"UNSET_VAR": "secret1"})

    # Assert: substituted value present, no diagnostics, no raise.
    assert result.data["tools"]["t"]["env"]["X"] == "secret1"
    assert result.diagnostics == []


def test_load_config_env_is_a_keyword_only_mapping(tmp_path: Path) -> None:
    """``env`` is keyword-only and accepts any ``Mapping`` (pinned sig).

    Guards the exact signature ``load_config(path, *, env=None)``:
    passing env positionally must be a TypeError.
    """
    # Arrange.
    path = _write(tmp_path, "tools.yaml", MINIMAL_CONFIG)

    # Act / Assert: positional env is rejected.
    with pytest.raises(TypeError):
        load_config(path, {})
    # A plain dict (a Mapping) is accepted via keyword.
    result = load_config(path, env={})
    assert isinstance(result, LoadedConfig)
    assert result.data == {
        "tools": {"example_echo": {"path": "./tools/example_echo"}}
    }

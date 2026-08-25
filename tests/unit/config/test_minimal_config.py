"""
Behaviour 23 (RED) — the five-line minimal config works end to end.

Executable form of ``plans/m1-configuration.md`` behaviour 23 and its
"Confirmed contract details (2026-08-20)" block (items 0-12). The golden
config is the spec's three-line snippet, and the golden tool directory is
the committed ``tools/example_echo/`` fixture (three files: ``tool.yaml``,
``handler.py``, ``requirements.txt``) — which does not exist yet.

Expected RED shape (plan item 10, pinned so red is verified, not
interpreted):

- ``test_committed_fixture_files_exist`` fails: the three fixture files
  are absent from the repo;
- every ``_plant``-based test fails with ``FileNotFoundError`` from
  ``shutil.copytree`` — the committed tool directory is missing (either
  way the failure is unambiguous — plan item 10);
- the one test that drives the pipeline directly against a ``tmp_path``
  config WITHOUT copying the committed directory
  (``test_no_group_diagnostic_when_groups_is_absent``) still passes at
  red: the missing ``path:`` directory is skipped silently at
  ``loader.py:452`` (no ``C005``), yielding exactly ``TSWAP-C300`` +
  ``TSWAP-C511`` — neither a C2xx code — and the synthesised ``default``
  group is a property of the raw config;
- two tests pass by design at red: ``test_the_minimal_config_is_at_most_
  five_lines`` (a property of the constant, not the fixtures — the R4
  mechanical check) and ``test_no_group_diagnostic_when_groups_is_
  absent``.

GREEN lands the three fixture files plus the ``OTHER_DIRS`` amendment in
``test_repo_layout.py`` (plan item 10) — neither belongs in this file.

Shipped-code pins verified while writing this file:

- ``run_pipeline(path, *, env, env_file, collected=None)`` —
  ``src/tool_swap/cli/_pipeline.py:85``; the pipeline call is passed an
  EMPTY env (not ``os.environ``) so a developer's environment cannot leak
  into the golden path;
- the red code set — probed with the missing directory: ``['TSWAP-C300',
  'TSWAP-C511']``, both ``severity=error``, both ``yaml_path='tools.
  example_echo'``; ``effective_groups`` still returns the synthesised
  ``{'default': {'max_resident': 4, 'eviction': 'lru'}}``;
- ``TOOL_FIELDS`` — ``src/tool_swap/cli/config_show.py:105`` — 30 fields
  in ``BUILT_IN_DEFAULTS`` order; ``description`` and ``inputs`` are NOT
  among the 30 (carriers, rendered outside the loop), so the
  ``built-in default`` loop needs no exclusion;
- the ``tool.yaml`` origin annotation is ``<abs path> (tool.yaml)`` with
  no line number — ``config_show.py:249-251``; this test asserts only the
  ``(tool.yaml)`` suffix, never the ``tmp_path``-dependent path (plan
  item 7);
- ``_emit`` renders warnings on stderr on the success path —
  ``validate.py:291`` — which is why ``stderr == ""`` is asserted in
  addition to the exit code (plan item 9);
- the zero-warning success line is ``f"OK {path} — 1 tools, no problems
  found"`` — ``validate.py:210-213``.

The runner and registry-isolation helpers are COPIED (not imported) from
``tests/unit/cli/test_config_show_cli.py`` — the shipped precedent for
cross-directory test imports in leaf dirs without ``__init__.py``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tool_swap.__main__ import app
from tool_swap.cli._pipeline import run_pipeline
from tool_swap.cli.config_show import (
    _BUILTIN_ANNOTATION,
    TOOL_FIELDS,
)
from tool_swap.config.validate import (
    RULES,
    effective_groups,
    register,
    unregister_all,
)

# ---------------------------------------------------------------------------
# Pinned artifacts (plan items 1, 3)
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[3]
COMMITTED_TOOL_DIR = ROOT / "tools" / "example_echo"

#: The spec's snippet, verbatim (plan, behaviour 23, "Inputs"): three
#: non-comment lines, comfortably inside R4's five.
MINIMAL_CONFIG = "tools:\n  example_echo:\n    path: ./tools/example_echo\n"

#: The fixture's ``tool.yaml`` description, verbatim from plan item 1 —
#: ``C300`` requires it non-blank, and the ``config show`` assertion pins
#: the rendered line against this exact text.
_FIXTURE_DESCRIPTION = "Echo the text you send it back, unchanged."


# ---------------------------------------------------------------------------
# Runner (verbatim copy of test_config_show_cli.py's shipped pattern —
# plan item 4: NO_COLOR=1, COLUMNS=80, TERM=linux for clean assertions)
# ---------------------------------------------------------------------------


def _make_runner(**overrides) -> CliRunner:
    """Return a CliRunner with NO_COLOR enforced for clean assertions.

    *overrides* may add/replace environment variables on top of the
    defaults (``COLUMNS=80 TERM=linux NO_COLOR=1``).
    """
    env = {**os.environ, "COLUMNS": "80", "TERM": "linux", "NO_COLOR": "1"}
    env.update(overrides)
    return CliRunner(env=env)


@pytest.fixture()
def runner() -> CliRunner:
    """Return a CliRunner with NO_COLOR enforced for clean assertions."""
    return _make_runner()


# ---------------------------------------------------------------------------
# Registry isolation (verbatim copy of test_config_show_cli.py:154 — plan
# item 4: ``run_pipeline`` calls ``register_builtin_rules()``)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_registry():
    """Keep the module-level rule registry state untouched across tests.

    ``run_pipeline`` calls ``register_builtin_rules()`` (idempotent,
    object-identity based), so driving the pipeline leaves the builtins
    registered. Snapshot the live registry and restore exactly that state
    after each test.
    """
    snapshot: list = list(RULES)

    def _restore() -> None:
        unregister_all()
        for rule in snapshot:
            register(rule)

    try:
        yield
    finally:
        _restore()


# ---------------------------------------------------------------------------
# Fixtures (plan items 3-4): the committed tool directory copied next to a
# tmp_path config — the config file itself is written by the test (A26:
# only the tool DIRECTORY is a repo artifact)
# ---------------------------------------------------------------------------


def _plant(tmp_path: Path) -> Path:
    """Copy the committed tool directory next to a ``tmp_path`` config.

    RED: raises ``FileNotFoundError`` while ``COMMITTED_TOOL_DIR`` is
    absent — the green step lands the fixture, so the failure is the
    guard working.
    """
    shutil.copytree(COMMITTED_TOOL_DIR, tmp_path / "tools" / "example_echo")
    config = tmp_path / "tools.yaml"
    config.write_text(MINIMAL_CONFIG, encoding="utf-8")
    return config


def _write_config(tmp_path: Path) -> Path:
    """Write ``MINIMAL_CONFIG`` to ``tmp_path/tools.yaml`` (no fixtures).

    For the one test that must observe the MISSING-directory shape
    directly (C300 + C511, not the ``_plant`` copy failure): the config
    exists, its ``path:`` directory does not, and the loader skips a
    non-existent ``path:`` directory silently (no ``C005``).
    """
    config = tmp_path / "tools.yaml"
    config.write_text(MINIMAL_CONFIG, encoding="utf-8")
    return config


def _invoke_validate(runner: CliRunner, config: Path, *args: str):
    """Invoke ``tswap validate`` with ``--config <abs path>`` plus *args*.

    ``--config`` is passed as an ABSOLUTE path: locating the file is the
    shell's job, not the resolver's — the ``path:`` inside the config
    stays relative, which is what the CWD edge tests (plan item 8).
    """
    return runner.invoke(app, ["validate", "--config", str(config.resolve()), *args])


def _invoke_show(runner: CliRunner, config: Path, *args: str):
    """Invoke ``tswap config show`` with ``--config <abs path>`` plus *args*."""
    return runner.invoke(
        app, ["config", "show", "--config", str(config.resolve()), *args]
    )


def _line_containing(stdout: str, fragment: str) -> str:
    """The single stdout line containing ``fragment`` (asserts uniqueness)."""
    matches = [line for line in stdout.splitlines() if fragment in line]
    assert len(matches) == 1, (
        f"Expected exactly one line containing {fragment!r}; "
        f"got {len(matches)}:\n" + "\n".join(matches)
    )
    return matches[0]


def _non_comment_lines(text: str) -> list[str]:
    """The config's significant lines: blank and #-comment lines dropped."""
    return [
        line
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


# ---------------------------------------------------------------------------
# Item 1 — the R4 mechanical check: the file fits in five lines
# ---------------------------------------------------------------------------


def test_the_minimal_config_is_at_most_five_lines() -> None:
    """R4: 'a working single-model config must fit in five lines'.

    Asserted against the same constant the other tests write to disk, so
    the promise cannot drift from the file that proves it. ``<=``, not
    ``==``: R4 is a ceiling, and the snippet uses three.
    """
    assert len(_non_comment_lines(MINIMAL_CONFIG)) <= 5


# ---------------------------------------------------------------------------
# Item 9 (plan) — the committed fixture guard
# ---------------------------------------------------------------------------


def test_committed_fixture_files_exist() -> None:
    """The three ``tools/example_echo/`` files exist in the repo.

    A one-line guard so a deleted fixture fails with "the fixture is
    gone" rather than as a confusing C300/C511 cascade three tests later
    (plan item 9, table row 9). RED: all three missing.
    """
    for name in ("tool.yaml", "handler.py", "requirements.txt"):
        fixture = COMMITTED_TOOL_DIR / name
        assert fixture.is_file(), (
            f"Committed fixture {fixture} is missing — behaviour 23's "
            "green step ships it (plan item 1)."
        )


# ---------------------------------------------------------------------------
# Item 2 (plan) — the pipeline form: the mechanical, severity-blind guard
# ---------------------------------------------------------------------------


def test_pipeline_reports_zero_diagnostics(tmp_path: Path) -> None:
    """``run_pipeline`` reports NO diagnostics of any severity.

    The mechanical guard: loader + root schema + resolver + all 41 rules,
    severity-blind by construction — a future WARNING cannot slip past an
    exit-code check (plan items 2, 9). The env is EMPTY (not
    ``os.environ``): the golden config interpolates nothing, and a clean
    env proves it. RED: ``_plant``'s ``shutil.copytree`` raises
    ``FileNotFoundError`` — the committed tool directory is missing.
    """
    config = _plant(tmp_path)

    pipeline = run_pipeline(config, env={}, env_file=None)

    assert pipeline.diagnostics == []


# ---------------------------------------------------------------------------
# Item 8 (plan) — the CWD edge: behaviour 8's rule at the integration level
# ---------------------------------------------------------------------------


def test_validate_from_a_different_cwd_is_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner
) -> None:
    """The same config validates identically from two different CWDs.

    ``--config`` is ABSOLUTE; the ``path:`` inside it is RELATIVE and
    resolves against the config file's directory (behaviour 8's shipped
    rule, ``loader._resolve_tool_path`` with ``base_dir=path.parent``).
    ``elsewhere`` is a sibling of ``tmp_path`` containing neither the
    config nor a ``tools/`` directory — a CWD-reading resolver would fail
    loudly rather than accidentally succeed. Byte-identical stdout and
    stderr, not merely equal exit codes (plan item 8).
    """
    config = _plant(tmp_path)
    elsewhere = tmp_path.parent / "elsewhere"
    elsewhere.mkdir()

    monkeypatch.chdir(tmp_path)
    inside = _invoke_validate(runner, config)
    monkeypatch.chdir(elsewhere)
    outside = _invoke_validate(runner, config)

    assert inside.exit_code == 0
    assert outside.exit_code == inside.exit_code
    assert outside.stdout == inside.stdout
    assert outside.stderr == inside.stderr == ""


# ---------------------------------------------------------------------------
# Item 8 (plan, row 8) — the synthesised default group exists AND is silent
# ---------------------------------------------------------------------------


def test_no_group_diagnostic_when_groups_is_absent(tmp_path: Path) -> None:
    """With ``groups:`` absent, the synthesised ``default`` group is silent.

    Asserts both halves so a future C223/C613 regression names itself
    (plan item 9, table row 8): no C2xx diagnostic of any severity, and
    ``effective_groups`` returns exactly the synthesised group. The
    C613 exemption (``"groups" not in config.raw``) exists FOR this
    behaviour — this test is what keeps it honest.
    """
    config = _write_config(tmp_path)

    pipeline = run_pipeline(config, env={}, env_file=None)

    c2xx = [d for d in pipeline.diagnostics if d.code.startswith("TSWAP-C2")]
    assert c2xx == []
    assert effective_groups(pipeline.config.raw) == {
        "default": {"max_resident": 4, "eviction": "lru"}
    }


# ---------------------------------------------------------------------------
# Item 4 (plan) — the CLI form: exit 0 AND empty stderr (warning-freedom)
# ---------------------------------------------------------------------------


def test_validate_exits_zero_with_empty_stderr(
    tmp_path: Path, runner: CliRunner
) -> None:
    """``tswap validate`` exits 0 with NOTHING on stderr.

    ``exit_code == 0`` alone is insufficient: ``_emit`` renders warnings
    on stderr on the success path and still exits 0 (plan item 9). The
    stdout success line is the zero-warning ``_ok_line`` form with the
    config path as typed (absolute, since the test passes it absolute).
    RED: ``_plant``'s ``shutil.copytree`` raises ``FileNotFoundError``.
    """
    config = _plant(tmp_path)

    result = _invoke_validate(runner, config)

    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}. "
        f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
    )
    assert result.stderr == ""
    assert f"OK {config.resolve()} — 1 tools, no problems found" in result.stdout


# ---------------------------------------------------------------------------
# Item 3 (plan) — the --json form: the only assertion covering the schema
# layer (appended by the command AFTER run_pipeline returns)
# ---------------------------------------------------------------------------


def test_validate_json_report_is_empty(tmp_path: Path, runner: CliRunner) -> None:
    """``tswap validate --json`` exits 0 with an empty report: ``[]``.

    The schema-layer diagnostics are appended by the command after
    ``run_pipeline`` returns, so the pipeline form cannot see them; an
    empty report JSON is ``[]`` (plan item 9, table row 3). RED:
    ``_plant``'s ``shutil.copytree`` raises ``FileNotFoundError``.
    """
    config = _plant(tmp_path)

    result = _invoke_validate(runner, config, "--json")

    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}. "
        f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
    )
    assert result.stdout.strip() == "[]"


# ---------------------------------------------------------------------------
# Item 5 (plan) — the --strict angle: a third, independent proof
# ---------------------------------------------------------------------------


def test_validate_strict_also_exits_zero(tmp_path: Path, runner: CliRunner) -> None:
    """``tswap validate --strict`` exits 0 with empty stderr.

    ``--strict`` promotes any warning to a failure, so this is the third
    independent warning-freedom angle and it anticipates behaviour 24's
    ``--strict`` gate (plan item 9, table row 5). RED: ``_plant``'s
    ``shutil.copytree`` raises ``FileNotFoundError``.
    """
    config = _plant(tmp_path)

    result = _invoke_validate(runner, config, "--strict")

    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}. "
        f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
    )
    assert result.stderr == ""


# ---------------------------------------------------------------------------
# Item 7 (plan) — config show: a substring set, not a second golden
# ---------------------------------------------------------------------------


def test_config_show_is_fully_populated_with_builtin_origins(
    tmp_path: Path, runner: CliRunner
) -> None:
    """``tswap config show``: fully populated, built-in origins everywhere.

    Substring set (plan item 7), NOT a second golden snapshot — B22 owns
    the byte-for-byte format. Content claims pinned: the 30 tool fields
    all present and annotated ``built-in default`` (``description`` is a
    carrier, not one of the 30, so the loop needs no exclusion); the
    ``description`` line carries the ``(tool.yaml)`` suffix (never the
    ``tmp_path``-dependent absolute path); the concrete ``ttl: 900``
    ledger example; ``inputs: 1 entry``; no redaction firing; the
    router/backend blocks once each; the router's ``port: 8600`` line
    exactly once — ``port`` is a router field, never a tool-section
    line.
    """
    config = _plant(tmp_path)

    result = _invoke_show(runner, config)

    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}. "
        f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
    )
    assert result.stderr == ""
    stdout = result.stdout

    # The tool header.
    assert "tool: example_echo" in stdout

    # All 30 tool fields present, each annotated ``built-in default``.
    # ``description`` is asserted separately below (its origin is
    # tool.yaml, not built-in) and is provably not one of the 30.
    assert "description" not in TOOL_FIELDS
    for field in TOOL_FIELDS:
        line = _line_containing(stdout, f"  {field}:")
        assert line.rstrip().endswith(f"# {_BUILTIN_ANNOTATION}"), (
            f"Field {field!r} is not annotated {_BUILTIN_ANNOTATION!r}. Got: {line!r}"
        )

    # The ledger's own concrete example value, asserted as one line
    # rather than left to the loop.
    ttl_line = _line_containing(stdout, "  ttl:")
    assert "900" in ttl_line
    assert ttl_line.rstrip().endswith(f"# {_BUILTIN_ANNOTATION}")

    # The description line: the fixture's verbatim text with the
    # ``tool.yaml`` origin suffix — the suffix only, never the
    # tmp_path-dependent absolute path.
    desc_line = _line_containing(stdout, "  description:")
    assert _FIXTURE_DESCRIPTION in desc_line
    assert desc_line.rstrip().endswith("(tool.yaml)"), (
        f"The description origin must be tool.yaml (the fixture declares "
        f"it). Got: {desc_line!r}"
    )

    # The singular inputs count (B22's pin at config_show.py:750),
    # tool.yaml-sourced like the description.
    inputs_line = _line_containing(stdout, "inputs: 1 entry")
    assert inputs_line.rstrip().endswith("(tool.yaml)"), (
        f"The inputs carrier origin must be tool.yaml. Got: {inputs_line!r}"
    )

    # No secret-shaped value, so the redaction path must not fire.
    assert "***" not in stdout

    # The router and backend blocks appear exactly once each (A24).
    # ``port`` is a ROUTER field: a tool section must not render a port
    # line. The guard is VALUE-scoped, matching B22's shipped precedent
    # (test_config_show_cli.py:1188 pins ``stdout.count("port: 9000") ==
    # 1`` on the raw router value): the router's own rendered line
    # ``port: 8600`` (built-in default) appears exactly once, so no tool
    # section can carry a second one. A bare ``"port:"`` substring count
    # cannot work — the tool-level fields ``container_port:`` and
    # ``expose_host_port:`` each contain ``port:`` as a substring — nor
    # can ``"  port:" not in stdout``, because the router block itself
    # renders ``  port: 8600  # built-in default``.
    assert stdout.count("router:") == 1
    assert stdout.count("backend:") == 1
    assert stdout.count("port: 8600") == 1

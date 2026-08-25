"""
Behaviour 24 (RED) — ``tools.example.yaml`` validates in CI under ``--strict``.

Executable form of ``plans/m1-configuration.md`` behaviour 24 and its
"Confirmed contract details (2026-08-21)" block (items 6-10). The example
config, the two ``tools/example_*`` fixture directories and the CI step are
GREEN artifacts — none exists yet, and every test in this file is expected
to RED (plan item 10).

Expected RED shape (plan item 10, pinned so red is verified, not
interpreted):

- ``test_the_example_config_exists`` fails: the one-line guard, the file is
  absent;
- ``test_pipeline_reports_zero_diagnostics_with_an_empty_environment``
  fails as an ERROR, not an assertion failure: ``run_pipeline`` RAISES
  ``ConfigError`` because ``load_config`` raises ``TSWAP-C000`` for a
  missing file at ``loader.py:628-636`` — it does not return diagnostics;
- ``test_validate_strict_exits_zero`` and
  ``test_validate_json_report_is_empty`` fail with exit code **2** (not 1):
  ``except ConfigError`` renders the report on stderr and raises
  ``typer.Exit(2)`` at ``validate.py:387-389``;
- ``test_every_referenced_path_exists``,
  ``test_the_example_exercises_the_documented_surface`` and
  ``test_every_variable_reference_has_a_default`` fail via
  ``FileNotFoundError`` from ``read_text``: the pinned form for the
  parse-and-check tests is an explicit file-existence assertion at the top
  of each (plan item 10: "read_text raising"), so the failure names the
  missing file rather than a diagnostic code;
- ``test_the_ci_workflow_validates_the_example`` fails: the
  ``tswap validate --config tools.example.yaml --strict`` step is absent
  from ``.github/workflows/ci.yml``.

No test passes by design at red: test 1 fails on ``is_file()``, tests 2-7
on the missing file, and test 8 on the un-amended workflow.

Cleared-environment mechanics (plan item 7, the honest framing): the
pipeline form with ``env={}`` is the cleared-environment proof —
``interpolate`` never reads the ambient environment, so every ``${VAR}``
must fall to its default. ``env_file`` is an EXISTING empty file, not
``None``: ``None`` means auto-discovery of the gitignored ``.env`` at the
repo root (``loader.py:263``). The CLI form is the CI-equivalent, not a
cleared environment (the command hard-codes ``env=os.environ`` at
``validate.py:343``); it explicitly unsets the three variables the file
names and passes ``--env-file <empty>``, so its claim is "clean when
nothing the file references is set".

The runner and registry-isolation helpers are COPIED (not imported) from
``tests/unit/cli/test_config_show_cli.py`` — the shipped precedent for leaf
test directories without ``__init__.py``. The repo-root idiom
(``Path(__file__).resolve().parents[3]``) is the same as
``test_minimal_config.py:88``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from tool_swap.__main__ import app
from tool_swap.cli._pipeline import run_pipeline
from tool_swap.config.validate import RULES, register, unregister_all

# ---------------------------------------------------------------------------
# Pinned artifacts (plan items 1, 8)
# ---------------------------------------------------------------------------

#: Repo root — three levels up from ``tests/unit/config/``; the same
#: idiom as ``test_minimal_config.py:88``.
ROOT = Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "tools.example.yaml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

#: The CI step the green step must add (plan item 8), asserted verbatim.
_CI_STEP = "tswap validate --config tools.example.yaml --strict"

#: The six documented root keys (plan item 9, test 6).
_ROOT_KEYS = {"version", "router", "backend", "defaults", "groups", "tools"}

#: The variables the example references; the CLI tests unset them (item 7).
_NAMED_VARS = ("TSWAP_TOKEN", "TSWAP_MODELS_DIR", "HF_TOKEN")


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


@pytest.fixture()
def empty_env_file(tmp_path: Path) -> Path:
    """An existing, empty env file — the only way to switch OFF ``.env``
    auto-discovery, which would otherwise read the repo root's ``.env``."""
    path = tmp_path / "empty.env"
    path.write_text("", encoding="utf-8")
    return path


def _invoke_validate(runner: CliRunner, config: Path, *args: str):
    """Invoke ``tswap validate`` with ``--config <abs path>`` plus *args*.

    ``--config`` is passed as an ABSOLUTE path: locating the file is the
    shell's job, not the resolver's (the B23 idiom, plan item 7: the CI
    run itself uses the relative name from the checkout root).
    """
    return runner.invoke(app, ["validate", "--config", str(config), *args])


def _substituted_host(mount: str) -> str:
    """The host side of a mount entry, its ``${VAR:-default}`` at the default.

    Mount hosts resolve against the config file's directory (item 6), and
    with an empty environment the interpolated host is the reference's
    default — the example's only path-bearing reference is
    ``${TSWAP_MODELS_DIR:-./models}`` (item 3), so the existence check
    resolves against the default. A bare entry is sliced as-is.
    """
    host = re.sub(r"\$\{[^}]*:-([^}]*)\}", r"\1", mount)
    return host.split(":", 1)[0]


# ---------------------------------------------------------------------------
# Test 1 — the committed file exists (plan item 9)
# ---------------------------------------------------------------------------


def test_the_example_config_exists() -> None:
    """``tools.example.yaml`` is committed at the repo root.

    The one-line guard so a deleted file fails by name rather than as a
    ``C000`` cascade in the other seven tests. RED: the file is absent
    (a GREEN artifact, plan item 10).
    """
    assert EXAMPLE.is_file(), (
        f"the example config is not committed at the repo root: {EXAMPLE}"
    )


# ---------------------------------------------------------------------------
# Test 2 — the cleared-environment proof (plan items 7, 9)
# ---------------------------------------------------------------------------


def test_pipeline_reports_zero_diagnostics_with_an_empty_environment(
    empty_env_file: Path,
) -> None:
    """``run_pipeline`` over the example with ``env={}`` is severity-blind
    clean: ``diagnostics == []``.

    With ``env={}`` every ``${VAR}`` must fall to its default or raise
    ``C010`` — the cleared-environment claim, mechanically (item 7). The
    empty EXISTING ``env_file`` switches off ``.env`` auto-discovery, which
    would otherwise read the gitignored ``.env`` at the repo root.

    RED: ``run_pipeline`` RAISES ``ConfigError`` (``TSWAP-C000`` at
    ``loader.py:628``) because the file does not exist — it does not
    return diagnostics. Plan item 10: the red is an error, not an
    assertion failure, and that is the honest shape.
    """
    report = run_pipeline(EXAMPLE, env={}, env_file=empty_env_file)
    assert report.diagnostics == []


# ---------------------------------------------------------------------------
# Tests 3-4 — the CI-equivalent CLI runs (plan items 7, 9)
# ---------------------------------------------------------------------------


def test_validate_strict_exits_zero(
    runner: CliRunner,
    empty_env_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``tswap validate --config <example> --strict --env-file <empty>``
    exits 0 with nothing on stderr.

    The CI-equivalent (item 7): the command hard-codes
    ``env=os.environ``, so the test unsets the three variables the file
    names — the honest claim is "clean when nothing the file references is
    set", not "os.environ was empty". The only form that also covers the
    schema layer (appended after ``run_pipeline`` returns,
    ``validate.py:351``).

    RED: exit 2 with ``TSWAP-C000`` on stderr (``validate.py:387-389``).
    """
    for var in _NAMED_VARS:
        monkeypatch.delenv(var, raising=False)
    result = _invoke_validate(
        runner, EXAMPLE.resolve(), "--strict", "--env-file", str(empty_env_file)
    )
    assert result.exit_code == 0, (
        f"Expected exit 0 under --strict, got {result.exit_code}. "
        f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
    )
    assert result.stderr == "", (
        f"--strict tolerates no diagnostics of any severity. "
        f"stderr: {result.stderr!r}"
    )


def test_validate_json_report_is_empty(
    runner: CliRunner,
    empty_env_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same run with ``--json`` exits 0 and prints ``[]`` on stdout.

    The machine-readable restatement of "zero diagnostics of any
    severity": the only schema-layer assertion in this file (plan item 9,
    test 4).

    RED: exit 2 with ``TSWAP-C000`` on stderr, stdout empty.
    """
    for var in _NAMED_VARS:
        monkeypatch.delenv(var, raising=False)
    result = _invoke_validate(
        runner, EXAMPLE.resolve(), "--strict", "--json", "--env-file", str(empty_env_file)
    )
    assert result.exit_code == 0, (
        f"Expected exit 0, got {result.exit_code}. "
        f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
    )
    assert result.stdout.strip() == "[]", (
        f"An empty report serialises to '[]'. stdout: {result.stdout!r}"
    )


# ---------------------------------------------------------------------------
# Test 5 — every referenced path exists (plan items 2, 9)
# ---------------------------------------------------------------------------


def test_every_referenced_path_exists() -> None:
    """Every ``path:`` / ``handler:`` / ``requirements:`` /
    ``build: {context, dockerfile}`` value — and the host side of every
    ``mounts:`` entry — resolves to an existing file or directory.

    A parse-and-check that makes the "every path it references exists in
    the repo" claim mechanical and independent of the rule layer
    (``C005``/``C006``/``C513``/``C514``/``C515``/``C543`` deliberately
    do the same at validation; this test names the missing file directly,
    the B23 fixture-guard reason). Handler file parts resolve against the
    tool directory when the entry has a ``path:`` and against the repo
    root otherwise (the ``_tool_base`` rule, ``validate.py:1433``); mount
    hosts resolve against the config file's directory (item 6), which is
    the repo root.

    RED: the file is absent; the existence guard at the top fails with a
    ``FileNotFoundError`` naming it (plan item 10).
    """
    assert EXAMPLE.is_file(), f"missing example config: {EXAMPLE}"
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    tools = data.get("tools") or {}
    mounts: list[str] = []
    defaults = data.get("defaults")
    if isinstance(defaults, dict) and isinstance(defaults.get("mounts"), list):
        mounts.extend(str(m) for m in defaults["mounts"])

    missing: list[str] = []
    for name, entry in tools.items():
        if not isinstance(entry, dict):
            continue
        base = ROOT
        if isinstance(entry.get("path"), str):
            base = ROOT / entry["path"]
        for key in ("path", "requirements"):
            if isinstance(entry.get(key), str):
                target = ROOT / entry[key] if key == "path" else base / entry[key]
                if not (target.is_file() or target.is_dir()):
                    missing.append(f"tools.{name}.{key}: {entry[key]}")
        handler = entry.get("handler")
        if isinstance(handler, str) and ":" in handler:
            file_part = handler.split(":", 1)[0]
            if not (base / file_part).is_file():
                missing.append(f"tools.{name}.handler: {file_part}")
        build = entry.get("build")
        if isinstance(build, dict):
            context = build.get("context")
            if isinstance(context, str):
                context_dir = ROOT / context
                if not context_dir.is_dir():
                    missing.append(f"tools.{name}.build.context: {context}")
                else:
                    dockerfile = build.get("dockerfile")
                    if isinstance(dockerfile, str) and not (
                        context_dir / dockerfile
                    ).is_file():
                        missing.append(
                            f"tools.{name}.build.dockerfile: "
                            f"{context}/{dockerfile}"
                        )
        if isinstance(entry.get("mounts"), list):
            mounts.extend(str(m) for m in entry["mounts"])

    for mount in mounts:
        host = _substituted_host(mount)
        target = ROOT / host
        if not (target.is_file() or target.is_dir()):
            missing.append(f"mount host: {host}")

    assert missing == [], (
        "referenced paths that do not exist in the repo: " + "; ".join(missing)
    )


# ---------------------------------------------------------------------------
# Test 6 — the documented surface is exercised (plan item 9)
# ---------------------------------------------------------------------------


def test_the_example_exercises_the_documented_surface() -> None:
    """The parsed YAML has the six documented root keys, ``defaults``
    carries both ``env`` and ``mounts``, and the three ``tools:`` forms
    each appear exactly once: one ``path:``, one inline ``handler:``,
    one ``build:``.

    A structural parse-assert, not a golden snapshot — the mechanical form
    of the ledger's "it exercises the documented surface", with the file
    free to change its values (plan item 9, test 6).

    RED: the file is absent; the existence guard at the top fails with a
    ``FileNotFoundError`` naming it (plan item 10).
    """
    assert EXAMPLE.is_file(), f"missing example config: {EXAMPLE}"
    data = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    assert set(data) >= _ROOT_KEYS, (
        f"expected the six documented root keys {_ROOT_KEYS}, got {set(data)}"
    )
    defaults = data.get("defaults")
    assert isinstance(defaults, dict) and "env" in defaults and "mounts" in defaults, (
        "defaults: must include both env and mounts"
    )
    groups = data.get("groups")
    assert isinstance(groups, dict) and len(groups) >= 2, (
        "groups: must define at least two groups (plan item 9, test 6); "
        f"got {groups!r}"
    )
    tools = data.get("tools") or {}
    counts = {"path": 0, "handler": 0, "build": 0}
    for entry in tools.values():
        if not isinstance(entry, dict):
            continue
        for form in counts:
            if form in entry:
                counts[form] += 1
    assert counts == {"path": 1, "handler": 1, "build": 1}, (
        "expected exactly one path: form, one inline handler: form and "
        f"one build: form; got {counts} over {list(tools)}"
    )


# ---------------------------------------------------------------------------
# Test 7 — every variable reference has a default (plan items 3, 9)
# ---------------------------------------------------------------------------


def test_every_variable_reference_has_a_default() -> None:
    """Every ``${VAR}`` occurrence in the raw text is ``${VAR:-...}``.

    The "validates with an empty environment" proof at the text level:
    test 2 proves the consequence (``env={}`` clean), this one proves the
    property, and it is the test that fails with a readable message when
    someone adds a bare ``${FOO}`` (plan item 9, test 7).

    RED: the file is absent; the existence guard at the top fails with a
    ``FileNotFoundError`` naming it (plan item 10).
    """
    assert EXAMPLE.is_file(), f"missing example config: {EXAMPLE}"
    text = EXAMPLE.read_text(encoding="utf-8")
    bare = [
        match
        for match in re.findall(r"\$\{[^}]+\}", text)
        if ":-" not in match
    ]
    assert bare == [], (
        "variable references without a :- default (an empty environment "
        f"could not interpolate them): {bare}"
    )


# ---------------------------------------------------------------------------
# Test 8 — CI actually checks it (plan item 8)
# ---------------------------------------------------------------------------


def test_the_ci_workflow_validates_the_example() -> None:
    """``.github/workflows/ci.yml`` contains a step running
    ``tswap validate --config tools.example.yaml --strict``.

    A substring check over the workflow text — the only thing standing
    between "the example validates" and "CI actually checks that it does"
    (plan item 9, test 8).

    RED: the step is absent (a GREEN artifact, plan item 8: "The workflow
    file is a GREEN artifact").
    """
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert _CI_STEP in text, (
        f"the CI workflow has no step running: {_CI_STEP}"
    )

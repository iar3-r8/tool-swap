"""
Behaviour 21 (RED) — the ``tswap validate`` CLI command.

Executable form of ``plans/m1-configuration.md`` behaviour 21 and its
"Confirmed contract details (2026-08-20)" block (items 1-16). The command
does not exist yet: ``src/tool_swap/cli/main.py`` currently registers only
``version``. Every test in this file is expected to RED with the
``validate`` subcommand absent — typer answers unknown subcommands with a
usage error (exit 2), and ``validate --help`` therefore exits 2 as well.
Nothing here should pass against the current tree.

Contract pinned by these tests (plan items in parentheses):

- call chain: ``register_builtin_rules()`` first, ``load_config`` with
  ``env=os.environ``, ``validate_root`` before the resolver, ``resolve_tool``
  twice per tool, ``validate_config``, then the schema step (item 1);
- the S1xx conversion reaches the report as ``to_diagnostic`` output with
  the dotted-numeric ``yaml_path`` (item 3);
- the exhaustive exit-code table (item 8);
- the per-tool ``yaml_path``-prefix filter with the "elsewhere" note
  (item 6, assumption A22);
- the verbatim output strings: the success line, the summary line, the
  strict clause, the never-in-CI banner, the unknown-tool line (items 5,
  7, 11);
- the exception-guard ordering: a raising *rule* is caught by
  ``validate_config``'s own guard and becomes ``TSWAP-C999`` (exit 1); a
  failure outside the rule loop is caught by the CLI guard and exits 2
  with "internal error while validating" and never a ``Traceback``
  (item 13);
- the fixture strategy: ``tmp_path`` plus a module-level ``_write`` helper,
  no committed fixture files (item 15, ``test_loader.py`` pattern).

Shipped-code pins verified while writing this file:

- missing file: ``TSWAP-C000`` — ``src/tool_swap/config/loader.py:59``
  (``_CODE_NOT_FOUND``), raised at ``loader.py:627-636``;
- unresolvable env var: ``TSWAP-C010`` — ``src/tool_swap/config/
  interpolate.py:23`` (``_CODE_MISSING``), surfaced as a ``ConfigError``
  by ``loader.py:648-649``;
- no image source: ``TSWAP-C511`` (ERROR) — ``_C511Rule``,
  ``validate.py:1513``;
- defined-but-unreferenced group: ``TSWAP-C223`` (WARNING) —
  ``_C223Rule``, ``validate.py:638``;
- shared host port: ``TSWAP-C530`` (ERROR) at bare ``tools`` —
  ``_C530Rule``, ``validate.py:2149``;
- ``keep_warm: true`` + explicit ``ttl > 0``: ``TSWAP-C601`` (WARNING) —
  ``_C601Rule``, ``validate.py:2853``;
- missing tool description: ``TSWAP-C300`` (ERROR) — ``_C300Rule``,
  ``validate.py:862``; missing ``inputs:`` entry description:
  ``TSWAP-C301`` (ERROR) — ``_C301Rule``, ``validate.py:895``;
- unsupported ``inputs:`` entry type: ``TSWAP-S103`` (ERROR) and missing
  entry description: ``TSWAP-S120`` (ERROR on the input side) —
  ``src/tool_swap/schema/compile.py``; raw ``json_schema:`` block failing
  the meta-schema: ``TSWAP-S140`` (ERROR) via
  ``validate_against_metaschema``;
- ``downgrade_missing_descriptions`` (``validate.py:3503``) DOWNGRADES
  ``C300``/``C301``/``C303`` to WARNING (it never removes them) and appends
  the per-diagnostic banner ``ALLOW_MISSING_DESCRIPTIONS_BANNER`` to each
  rewritten message; the flag therefore turns an exit-1 report into an
  exit-0 one while the diagnostics stay visible.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
import typer.main

# ``conftest`` is importable here because pytest's default prepend
# importmode puts the ``tests/`` directory on ``sys.path`` when it loads
# ``tests/conftest.py`` (no ``__init__.py`` at that level, so it is imported
# as a top-level module). This is the one cross-directory sharing point the
# repo allows: leaf test dirs have no ``__init__.py`` and import sibling test
# modules by relative path, but the shared conftest is loadable by name.
from conftest import normalize_help_output
from typer.core import TyperArgument, TyperOption
from typer.testing import CliRunner

from tool_swap.__main__ import app
from tool_swap.config.validate import (
    BUILTIN_RULES,
    RULES,
    register,
    registered_rule_ids,
    unregister_all,
)

# ---------------------------------------------------------------------------
# Pinned strings (plan item 5's table, verbatim; the "—" is a real em-dash)
# ---------------------------------------------------------------------------

_OK_LINE = "OK {} — 2 tools, no problems found"
_OK_WARNINGS_LINE = "OK {} — 1 tools, 1 warning(s)"
_OK_ONE_TOOL_LINE = "OK {} — 1 tools, no problems found"
_SUMMARY_ONE_ONE = "1 error(s), 1 warning(s)"
_SUMMARY_ONE_ZERO = "1 error(s), 0 warning(s)"
_SUMMARY_ZERO_ONE = "0 error(s), 1 warning(s)"
_STRICT_CLAUSE = " — failing due to --strict"
_NORE_CROSS_TOOL_NOTE_PREFIX = "note: 1 diagnostic(s) elsewhere in "
_NOTE_CROSS_TOOL_SUFFIX = " are not shown by 'tswap validate"
_UNKNOWN_TOOL_LINE = "error: unknown tool 'preidt'; did you mean 'predict'?"

_FLAG_BANNER = (
    "WARNING: --allow-missing-descriptions is for local prototyping "
    "and is never permitted in CI"
)

# The EXACT documented flag surface of ``tswap validate`` (plan item 12).
# The metadata test asserts set-equality, so adding or dropping a flag
# without updating this list fails the suite (and vice versa).
_VALIDATE_FLAGS = (
    "--config",
    "--env-file",
    "--all",
    "--strict",
    "--json",
    "--allow-missing-descriptions",
)
#: A declared help string shorter than this is "trivial" (plan item 12).
_MIN_HELP_LEN = 10
#: The metavar of validate's single positional argument.
_TOOL_METAVAR = "TOOL"

# ---------------------------------------------------------------------------
# Runner / env (verbatim copy of tests/unit/test_cli.py's shipped pattern —
# plan item 14; copied, not imported, because leaf test dirs have no
# __init__.py and cross-directory test imports are unavailable)
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
# Registry isolation: snapshot/restore the shared rule registry
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_registry():
    """Keep the module-level rule registry state untouched across tests.

    Behaviour 21's command calls ``register_builtin_rules()`` (idempotent,
    object-identity based), so invoking the CLI leaves the builtins
    registered. Rather than unregistering on exit (which would strip any
    rules a preceding test file legitimately registered for its own
    in-process assertions), snapshot the live registry and restore exactly
    that state after each test.
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
# Fixtures (plan item 15): tmp_path + a module-level _write helper,
# no committed fixture files — test_loader.py's shipped pattern
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, text: str) -> Path:
    """Write ``text`` (UTF-8) to ``tmp_path/name`` and return the path.

    Parent directories are created as needed (``t/tool.yaml`` fixtures).
    """
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


#: Valid config, two tools, zero diagnostics at every layer. Exercises the
#: success line, the tool count, exit 0, and (via its tool names) the
#: nearest-name candidates of the unknown-tool error.
VALID_TWO_TOOLS = (
    "tools:\n"
    "  echo:\n"
    "    image: registry.example.com/echo:1\n"
    "    description: Echoes its input back.\n"
    "  predict:\n"
    "    image: registry.example.com/predict:1\n"
    "    description: Runs the prediction handler.\n"
)

_TOOL_YAML_INPUTS = (
    "name: t\n"
    "description: A tool with a well-formed inputs block.\n"
    "inputs:\n"
    "  - name: prompt\n"
    "    type: string\n"
    "    description: The prompt text.\n"
)

#: A ``path:`` tool whose ``tool.yaml`` carries a well-formed ``inputs:``
#: block with descriptions — the S1xx negative control: the schema pipeline
#: runs end to end and produces ZERO schema diagnostics.
VALID_WITH_INPUTS = (
    "tools:\n"
    "  t:\n"
    "    image: registry.example.com/t:1\n"
    "    description: A tool with a well-formed inputs block.\n"
    "    path: ./t\n"
)

_BAD_INPUTS_TOOL_YAML = (
    "name: t\n"
    "description: A tool with an unsupported input type.\n"
    "inputs:\n"
    "  - name: x\n"
    "    type: enum\n"
    "    description: An entry with an unsupported type.\n"
)

#: Same shape, but ``type: enum`` is not in ``SUPPORTED_TYPES`` — the
#: compiler emits TSWAP-S103 (ERROR) end to end through the CLI, located at
#: ``tools.t.inputs.0`` (plan item 3's ``to_diagnostic`` yaml_path).
BAD_INPUTS = (
    "tools:\n"
    "  t:\n"
    "    image: registry.example.com/t:1\n"
    "    description: A tool with an unsupported input type.\n"
    "    path: ./t\n"
)

_RAW_JSON_SCHEMA_TOOL_YAML = (
    "name: t\n"
    "description: A tool with a broken raw json_schema block.\n"
    "json_schema:\n"
    "  type: object\n"
    "  properties:\n"
    "    p:\n"
    "      type: 5\n"
)

#: A passed-through ``json_schema:`` block that fails the JSON Schema
#: 2020-12 meta-schema — TSWAP-S140 (ERROR) proves the CLI meta-validates
#: the passed-through half, not only the compiled one (plan item 4).
RAW_JSON_SCHEMA_BAD = (
    "tools:\n"
    "  t:\n"
    "    image: registry.example.com/t:1\n"
    "    description: A tool with a broken raw json_schema block.\n"
    "    path: ./t\n"
)

#: One ERROR (tool ``b`` has no image source — TSWAP-C511) plus one WARNING
#: (``keep_warm: true`` with an explicit ``ttl: 300`` — TSWAP-C601). The
#: plan's item-8 shape (C511 + C223) is replaced by C601 because C223 is
#: suppressed whenever no defined group is referenced at all (shipped
#: _C223Rule); C601 is the plan's own alternate warning and is stable.
ONE_ERROR_ONE_WARNING = (
    "tools:\n"
    "  a:\n"
    "    image: registry.example.com/a:1\n"
    "    description: A clean tool.\n"
    "    keep_warm: true\n"
    "    ttl: 300\n"
    "  b:\n"
    "    description: A tool with no image source at all.\n"
)

#: Only the C601 warning, everything else clean: exit 0 plain, exit 1 under
#: --strict with the pinned strict clause.
WARNING_ONLY = (
    "tools:\n"
    "  a:\n"
    "    image: registry.example.com/a:1\n"
    "    description: A warm tool.\n"
    "    keep_warm: true\n"
    "    ttl: 300\n"
)

_MISSING_DESC_TOOL_YAML = "name: t\ninputs:\n  - name: x\n    type: string\n"

#: The tool itself has no ``description:`` (TSWAP-C300, ERROR) and its
#: ``inputs:`` entry has none either (TSWAP-C301 from the config layer and
#: TSWAP-S120 from the schema layer, both ERROR). ``--allow-missing-
#: descriptions`` downgrades C300/C301 to WARNING (S120 is a schema code,
#: NOT in MISSING_DESCRIPTION_CODES, and stays an ERROR), so this fixture
#: still exits 1 with the flag — it pins the downgrade, not the exit.
MISSING_DESCRIPTIONS = (
    "tools:\n  t:\n    image: registry.example.com/t:1\n    path: ./t\n"
)

#: A tool whose only finding is its own missing description (TSWAP-C300,
#: ERROR; no inputs block, so no C301/S120). With
#: ``--allow-missing-descriptions`` the C300 is downgraded to WARNING, the
#: report has zero remaining errors, and the exit becomes 0 (plan item 8,
#: row 5) — the flag's whole purpose.
TOOLS_DESC = "tools:\n  t:\n    image: registry.example.com/t:1\n"

#: ``image:`` references a variable that is neither in the ambient env nor
#: in any env file — TSWAP-C010 from the interpolator, exit 2.
UNRESOLVABLE_ENV = (
    "tools:\n"
    "  t:\n"
    "    image: registry.example.com/${TSWAP_TEST_MISSING_XYZ}\n"
    "    description: A tool whose image variable is unset.\n"
)

#: Two tools sharing an explicit host port — TSWAP-C530 (ERROR) at bare
#: ``tools``. The port 7100 is INSIDE the built-in backend.port_range
#: [7000, 7999], so C531 (out-of-range port) stays silent and C530 is the
#: ONLY finding: one error, whole-file exit 1. Pins the per-tool filter:
#: the whole-file run reports it; ``tswap validate alpha`` must NOT, and
#: must print the "elsewhere" note.
CROSS_TOOL = (
    "tools:\n"
    "  alpha:\n"
    "    image: registry.example.com/alpha:1\n"
    "    description: First port claimant.\n"
    "    expose_host_port: 7100\n"
    "  beta:\n"
    "    image: registry.example.com/beta:1\n"
    "    description: Second port claimant.\n"
    "    expose_host_port: 7100\n"
)

#: ``--env-file`` contract: the variable exists only in the file, so the
#: flag must replace .env discovery and resolve it.
ENV_FILE_CONFIG = (
    "tools:\n"
    "  t:\n"
    "    image: registry.example.com/${TSWAP_ENV_FILE_IMAGE}\n"
    "    description: A tool resolved from the explicit env file.\n"
)
_ENV_FILE_TEXT = "TSWAP_ENV_FILE_IMAGE=image:1\n"


def _invoke(runner: CliRunner, config_path: Path, *args: str) -> object:
    """Invoke ``validate`` with ``--config <path>`` plus *args*."""
    return runner.invoke(app, ["validate", "--config", str(config_path), *args])


# ---------------------------------------------------------------------------
# Help and absence
# ---------------------------------------------------------------------------


def _validate_click_command() -> object:
    """Return the Click command object for ``tswap validate``.

    ``typer.main.get_command`` is the documented bridge from a Typer app to
    its Click representation; the returned command's ``.params`` and
    ``.commands`` are then walked directly, never re-rendered.
    """
    root = typer.main.get_command(app)
    return root.commands["validate"]


def _flag_opts(command: object) -> set[str]:
    """Return the long-option strings (``--foo``) declared on *command*."""
    opts: set[str] = set()
    for param in command.params:  # type: ignore[attr-defined]
        if isinstance(param, TyperOption):
            opts.update(param.opts)
            opts.update(param.secondary_opts)
    return opts


def _tool_argument(command: object) -> object:
    """Return the single ``TyperArgument`` on *command*, or None."""
    args = [
        p
        for p in command.params  # type: ignore[attr-defined]
        if isinstance(p, TyperArgument)
    ]
    assert len(args) == 1, (
        f"Expected exactly one positional argument on the command, got {len(args)}"
    )
    return args[0]


class TestHelp:
    """``tswap validate --help`` lists every flag with a description.

    The documented CLI surface is pinned in two layers, chosen because the
    rendered ``--help`` text is UNRELIABLE on GitHub Actions:

    - ``typer/rich_utils.py`` evaluates ``FORCE_TERMINAL`` from the real
      process environment at module-import time, so
      ``CliRunner(env={"NO_COLOR": "1"})`` — applied only at ``invoke()``
      time — cannot stop Rich from styling the help;
    - with ``force_terminal=True`` Rich injects ANSI escapes mid-token
      (``\\x1b[1m--config\\x1b[0m`` makes ``"--config" in stdout`` False)
      AND wraps long lines, pushing a flag's description onto a
      continuation line.

    Layer 1 therefore asserts the DECLARED command metadata (zero rendering
    involved) and Layer 2 a normalised (escape-stripped, whitespace-
    collapsed) smoke check that the text actually reaches ``--help`` output.
    """

    def test_validate_help_exits_zero_and_lists_every_flag(self) -> None:
        """Every declared flag and the TOOL argument carries a real help string.

        Plan item 12, asserted against the command metadata rather than the
        rendered help: each option in ``_VALIDATE_FLAGS`` must be declared
        on the Click command with a help string of at least
        ``_MIN_HELP_LEN`` characters, the positional TOOL argument must do
        the same, and the declared option set must equal ``_VALIDATE_FLAGS``
        exactly — so both dropping and sneaking in a flag fail the suite.
        This has zero dependence on terminal width or ANSI rendering.
        """
        command = _validate_click_command()

        opts = _flag_opts(command)
        assert opts == set(_VALIDATE_FLAGS), (
            f"The declared validate flags must be exactly "
            f"{sorted(_VALIDATE_FLAGS)}, got {sorted(opts)}"
        )
        for flag in _VALIDATE_FLAGS:
            param = next(
                p
                for p in command.params  # type: ignore[attr-defined]
                if isinstance(p, TyperOption) and flag in p.opts
            )
            assert isinstance(param.help, str) and len(param.help) >= _MIN_HELP_LEN, (
                f"Flag {flag} must declare a help string of at least "
                f"{_MIN_HELP_LEN} characters, got {param.help!r}"
            )
        tool = _tool_argument(command)
        assert tool.metavar == _TOOL_METAVAR, (
            f"Expected the positional argument to render as {_TOOL_METAVAR}, "
            f"got {tool.metavar!r}"
        )
        assert isinstance(tool.help, str) and len(tool.help) >= _MIN_HELP_LEN, (
            f"The TOOL argument must declare a help string of at least "
            f"{_MIN_HELP_LEN} characters, got {tool.help!r}"
        )

    def test_validate_help_smoke_renders_every_flag(self, runner: CliRunner) -> None:
        """``validate --help`` exits 0 and shows every flag name in its text.

        Layer 2 (rendering smoke): proves the metadata above actually
        reaches ``--help`` output. The output is normalised through
        ``normalize_help_output`` (shared conftest helper) — ANSI escapes
        stripped AND whitespace collapsed — because on GitHub Actions Rich
        both injects escapes mid-token and wraps lines, so raw substring
        or line-anchor assertions are unreliable. Whole-token membership
        on the collapsed line is the weakest check that still survives
        both failure modes.
        """
        result = runner.invoke(app, ["validate", "--help"])

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        normalized = normalize_help_output(result.stdout)
        for token in (*_VALIDATE_FLAGS, _TOOL_METAVAR):
            assert token in normalized, (
                f"Expected {token!r} in the normalised validate --help "
                f"output. Normalised:\n{normalized}"
            )

    def test_root_help_lists_validate_subcommand(self) -> None:
        """The root command declares ``validate`` with a description.

        Metadata form: the root Click group's ``.commands`` dict must map
        ``"validate"`` to a command whose ``.help`` is non-trivial. The
        previous rendered-text assertion (``\\bvalidate\\b`` on a help
        line) was doubly broken on GitHub Actions — Rich's bold SGR reset
        sits immediately before the name so ``\\b`` finds no boundary, and
        the same pattern passed for ``config`` only via a FALSE POSITIVE
        (the word "config" inside validate's description).
        """
        root = typer.main.get_command(app)

        assert "validate" in root.commands, (
            f"Expected a 'validate' subcommand on the root, got {sorted(root.commands)}"
        )
        help_ = root.commands["validate"].help
        assert isinstance(help_, str) and len(help_) >= 3, (
            f"The validate subcommand must declare a non-trivial help "
            f"string, got {help_!r}"
        )

    def test_root_help_smoke_lists_validate_and_config(self, runner: CliRunner) -> None:
        """``tswap --help`` exits 0 and shows both subcommand names.

        Rendering smoke (layer 2) for the root: the normalised output must
        contain the whole tokens ``validate`` and ``config`` — the latter
        asserted here as a token because on a raw line it only ever appears
        as a false positive inside validate's description.
        """
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        normalized = normalize_help_output(result.stdout)
        for token in ("validate", "config"):
            assert token in normalized, (
                f"Expected {token!r} in the normalised root --help output. "
                f"Normalised:\n{normalized}"
            )


# ---------------------------------------------------------------------------
# Success paths (whole file)
# ---------------------------------------------------------------------------


class TestSuccess:
    """Success rendering: OK line on stdout, stderr empty, exit 0."""

    def test_valid_two_tools_prints_exact_ok_line_on_stdout(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Plan item 5: ``OK <file> — 2 tools, no problems found`` on stdout.

        The file is echoed exactly as passed on the command line; the
        dash is a real em-dash. Diagnostics go to stderr, the success line
        to stdout, so this run leaves stderr empty.
        """
        path = _write(tmp_path, "tools.yaml", VALID_TWO_TOOLS)

        result = _invoke(runner, path)

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert _OK_LINE.format(str(path)) in result.stdout, (
            f"Expected the exact success line on stdout. stdout: {result.stdout!r}"
        )
        assert result.stderr == ""

    def test_valid_with_inputs_zero_schema_diagnostics(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """The S1xx negative control: a well-formed inputs: stays silent.

        The schema pipeline (compile + meta-validate) runs end to end on a
        well-formed ``inputs:`` block and contributes ZERO diagnostics, so
        the run is a plain success.
        """
        path = _write(tmp_path, "tools.yaml", VALID_WITH_INPUTS)
        _write(tmp_path, "t/tool.yaml", _TOOL_YAML_INPUTS)

        result = _invoke(runner, path)

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert result.stderr == ""
        assert re.search(r"TSWAP-S\d{3}", result.stderr) is None

    def test_success_with_warnings_ok_line_and_warning_on_stderr(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Warnings never fail: exit 0, OK line, warning on stderr only.

        Plan item 5: ``OK <file> — <n> tools, <m> warning(s)``; the
        rendered diagnostic (C601) is on stderr; and the summary line is
        NOT printed on a successful run (it belongs to the failure path).
        """
        path = _write(tmp_path, "tools.yaml", WARNING_ONLY)

        result = _invoke(runner, path)

        assert result.exit_code == 0, (
            f"Expected exit 0 (warnings never fail), got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert _OK_WARNINGS_LINE.format(str(path)) in result.stdout
        assert "TSWAP-C601" in result.stderr, (
            f"Expected the C601 diagnostic rendered on stderr. "
            f"stderr: {result.stderr!r}"
        )
        assert "error(s)" not in result.stdout, (
            f"No summary line may appear on a successful run. stdout: {result.stdout!r}"
        )

    def test_missing_file_exits_two_with_c000(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """A nonexistent --config path is TSWAP-C000 on stderr, exit 2.

        The loader's missing-file code is TSWAP-C000
        (src/tool_swap/config/loader.py:59, raised at :627-636); every
        C0xx ConfigError is exit 2 (plan item 1).
        """
        missing = tmp_path / "does_not_exist.yaml"

        result = runner.invoke(app, ["validate", "--config", str(missing)])

        assert result.exit_code == 2, (
            f"Expected exit 2 for a missing config, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert "TSWAP-C000" in result.stderr
        assert "TSWAP-C000" not in result.stdout

    def test_unresolvable_env_var_exits_two_with_c010(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """An unset ${VAR} with no default is TSWAP-C010, exit 2.

        The interpolator's missing-variable code is TSWAP-C010
        (src/tool_swap/config/interpolate.py:23), raised as a ConfigError
        by the loader (loader.py:648-649); exit 2 per the exhaustive
        table row 8.
        """
        path = _write(tmp_path, "tools.yaml", UNRESOLVABLE_ENV)

        result = _invoke(runner, path)

        assert result.exit_code == 2, (
            f"Expected exit 2 for an unresolvable env var, got "
            f"{result.exit_code}. stdout: {result.stdout!r} "
            f"stderr: {result.stderr!r}"
        )
        assert "TSWAP-C010" in result.stderr
        assert "TSWAP-C010" not in result.stdout

    def test_env_file_flag_resolves_variable_from_the_file(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """--env-file replaces .env discovery and resolves the variable.

        The variable exists ONLY in the explicit env file (not in the
        ambient env), so a green run proves the flag was honoured.
        """
        path = _write(tmp_path, "tools.yaml", ENV_FILE_CONFIG)
        env_path = _write(tmp_path, "env.test", _ENV_FILE_TEXT)

        result = _invoke(runner, path, "--env-file", str(env_path))

        assert result.exit_code == 0, (
            f"Expected exit 0 with --env-file, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert result.stderr == ""
        assert _OK_ONE_TOOL_LINE.format(str(path)) in result.stdout


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


class TestFailure:
    """Error rendering: diagnostics + summary on stderr, exit 1."""

    def test_one_error_one_warning_renders_diagnostics_and_summary(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Exit 1; stderr has both diagnostics and the summary line.

        The C511 (ERROR) and C601 (WARNING) blocks render on stderr,
        followed by the exact summary ``1 error(s), 1 warning(s)``; stdout
        carries no OK line on failure.
        """
        path = _write(tmp_path, "tools.yaml", ONE_ERROR_ONE_WARNING)

        result = _invoke(runner, path)

        assert result.exit_code == 1, (
            f"Expected exit 1, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert "TSWAP-C511" in result.stderr
        assert "TSWAP-C601" in result.stderr
        assert _SUMMARY_ONE_ONE in result.stderr
        assert "OK " not in result.stdout, (
            f"No success line may appear on a failing run. stdout: {result.stdout!r}"
        )

    def test_failure_keeps_diagnostics_out_of_stdout(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Diagnostics go to stderr and NOT to stdout on failure.

        The shell-composition pin: ``tswap validate && deploy`` must not
        see diagnostic prose on the success stream.
        """
        path = _write(tmp_path, "tools.yaml", ONE_ERROR_ONE_WARNING)

        result = _invoke(runner, path)

        assert result.exit_code == 1
        for token in ("TSWAP-C511", "TSWAP-C601", _SUMMARY_ONE_ONE):
            assert token not in result.stdout, (
                f"{token!r} must not appear on stdout. stdout: {result.stdout!r}"
            )


class TestStrict:
    """--strict promotes warnings to a failing exit without mutation."""

    def test_strict_with_only_warnings_exits_one_with_clause(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Plan item 10: the strict gate and its pinned summary clause.

        0 errors, 1 warning, --strict → exit 1 and the summary reads
        ``0 error(s), 1 warning(s) — failing due to --strict`` — it must
        NOT claim an error the rules did not find.
        """
        path = _write(tmp_path, "tools.yaml", WARNING_ONLY)

        result = _invoke(runner, path, "--strict")

        assert result.exit_code == 1, (
            f"Expected exit 1 under --strict, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert _SUMMARY_ZERO_ONE + _STRICT_CLAUSE in result.stderr, (
            f"Expected the pinned strict summary clause on stderr. "
            f"stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# --json
# ---------------------------------------------------------------------------


class TestJson:
    """--json: only the report's JSON on stdout; humans go to stderr."""

    def test_json_stdout_is_valid_json_with_nothing_else(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Plan item 9: ``to_json()`` and nothing else on stdout.

        The human rendering (diagnostic blocks) goes to stderr; stdout must
        parse as JSON and be the sole non-whitespace content. The JSON is
        the list of objects with exactly the pinned keys (item 9 /
        behaviour 2's ``to_json``).
        """
        path = _write(tmp_path, "tools.yaml", ONE_ERROR_ONE_WARNING)

        result = _invoke(runner, path, "--json")

        assert result.exit_code == 1, (
            f"Expected exit 1, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        payload = json.loads(result.stdout)
        assert isinstance(payload, list) and len(payload) == 2
        for entry in payload:
            assert set(entry) == {
                "code",
                "severity",
                "message",
                "file",
                "yaml_path",
                "line",
                "remedy",
            }
        assert "TSWAP-C511" in result.stderr, (
            "Human rendering must go to stderr in --json mode. "
            f"stderr: {result.stderr!r}"
        )
        assert (
            "TSWAP-C511" not in result.stdout.replace('"TSWAP-C511"', "")
            or "remedy" in result.stdout
        )  # code appears only inside JSON fields
        for entry in payload:
            assert entry["severity"] in {"error", "warning"}

    def test_json_carries_the_diagnostic_codes(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """The JSON body carries the codes of both diagnostics."""
        path = _write(tmp_path, "tools.yaml", ONE_ERROR_ONE_WARNING)

        result = _invoke(runner, path, "--json")

        payload = json.loads(result.stdout)
        codes = {entry["code"] for entry in payload}
        assert codes == {"TSWAP-C511", "TSWAP-C601"}, (
            f"Expected exactly the C511 and C601 codes in the JSON, got {codes!r}"
        )


# ---------------------------------------------------------------------------
# The per-tool reporting filter (A22)
# ---------------------------------------------------------------------------


class TestToolFilter:
    """tswap validate <tool>: yaml_path-prefix filter + the note line."""

    def test_whole_file_reports_cross_tool_port_clash(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """The whole-file run reports the bare-``tools`` C530 diagnostic.

        Port 7100 is inside the built-in port_range, so C530 is the ONLY
        finding: exactly one error, zero warnings.
        """
        path = _write(tmp_path, "tools.yaml", CROSS_TOOL)

        result = _invoke(runner, path)

        assert result.exit_code == 1
        assert "TSWAP-C530" in result.stderr
        assert "TSWAP-C531" not in result.stderr
        assert _SUMMARY_ONE_ZERO in result.stderr

    def test_per_tool_hides_cross_tool_diagnostic_and_prints_note(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Plan item 6: C530 (at bare ``tools``) is filtered out per tool.

        The filter is a yaml_path prefix test, so the cross-tool finding is
        not reported; because the unfiltered report had errors the filter
        hid, the note line is appended; and the exit follows the FILTERED
        report (0).
        """
        path = _write(tmp_path, "tools.yaml", CROSS_TOOL)

        result = _invoke(runner, path, "alpha")

        assert result.exit_code == 0, (
            "Exit follows the filtered report (no findings for alpha). "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert "TSWAP-C530" not in result.stderr, (
            "The cross-tool C530 must not be shown under "
            f"'tswap validate alpha'. stderr: {result.stderr!r}"
        )
        assert _NOTE_CROSS_TOOL_SUFFIX in result.stderr, (
            f"Expected the 'are not shown by tswap validate' note. "
            f"stderr: {result.stderr!r}"
        )
        assert _NORE_CROSS_TOOL_NOTE_PREFIX in result.stderr
        assert _OK_ONE_TOOL_LINE.format(str(path)) in result.stdout

    def test_per_tool_shows_the_tool_own_local_error(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """A diagnostic under ``tools.<X>`` IS reported for tool X.

        Give alpha its own local error (no image source, C511) on top of
        the shared-port config: the per-tool run shows C511 and exits 1,
        while the bare-``tools`` C530 stays hidden.
        """
        local_error = (
            "tools:\n"
            "  alpha:\n"
            "    description: Alpha lost its image source.\n"
            "    expose_host_port: 7100\n"
            "  beta:\n"
            "    image: registry.example.com/beta:1\n"
            "    description: Second port claimant.\n"
            "    expose_host_port: 7100\n"
        )
        path = _write(tmp_path, "tools.yaml", local_error)

        result = _invoke(runner, path, "alpha")

        assert result.exit_code == 1
        assert "TSWAP-C511" in result.stderr, (
            f"alpha's own C511 must be shown. stderr: {result.stderr!r}"
        )
        assert "TSWAP-C530" not in result.stderr


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------


class TestUnknownTool:
    """tswap validate <unknown-tool>: exit 1, no TSWAP code, nearest name."""

    def test_unknown_tool_suggests_nearest_and_exits_one(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Plan item 7: the verbatim suggestion line on stderr, exit 1.

        ``'preidt'`` is distance 2 over length 7 from ``'predict'``
        (2 <= 0.3*7), so nearest_alternative suggests it. The line carries
        NO TSWAP- code — it is a usage error, not a config finding.
        """
        path = _write(tmp_path, "tools.yaml", VALID_TWO_TOOLS)

        result = _invoke(runner, path, "preidt")

        assert result.exit_code == 1, (
            f"Expected exit 1 for an unknown tool, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert _UNKNOWN_TOOL_LINE in result.stderr
        assert re.search(r"TSWAP-[CS]\d{3}", result.stderr) is None, (
            "The unknown-tool error must carry no TSWAP- code. "
            f"stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Schema diagnostics end to end (S103 / S140)
# ---------------------------------------------------------------------------


class TestSchemaDiagnostics:
    """S1xx reach the report through to_diagnostic (plan items 3 and 4)."""

    def test_bad_inputs_type_s103_end_to_end(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """An unsupported entry type emits TSWAP-S103 at inputs.0.

        ``to_diagnostic`` pins ``yaml_path == tools.t.inputs.0`` for
        entry-indexed findings; ``line_for`` yields None for a
        list-indexed path, so Location.render degrades to
        ``<file> (tools.t.inputs.0)`` — asserted as the dotted path,
        never a literal line.
        """
        path = _write(tmp_path, "tools.yaml", BAD_INPUTS)
        _write(tmp_path, "t/tool.yaml", _BAD_INPUTS_TOOL_YAML)

        result = _invoke(runner, path)

        assert result.exit_code == 1, (
            f"Expected exit 1, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert "TSWAP-S103" in result.stderr
        assert "tools.t.inputs.0" in result.stderr
        assert _SUMMARY_ONE_ZERO in result.stderr

    def test_raw_json_schema_bad_s140_end_to_end(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """A failed meta-schema on a passed-through block emits TSWAP-S140.

        Proves the CLI meta-validates the passed-through ``json_schema:``
        half (plan item 4: compile first, then meta-validate every
        non-None half). ``validate_against_metaschema`` yields S140s with
        no block, and the CLI back-fills the half it was validating, so
        the finding lands at ``tools.t.inputs`` (the passed-through half)
        — verified against the shipped pipeline; the ``tools.<key>.
        json_schema`` row of the plan's table is reached only by a
        compiler-emitted block-tagged finding.
        """
        path = _write(tmp_path, "tools.yaml", RAW_JSON_SCHEMA_BAD)
        _write(tmp_path, "t/tool.yaml", _RAW_JSON_SCHEMA_TOOL_YAML)

        result = _invoke(runner, path)

        assert result.exit_code == 1, (
            f"Expected exit 1, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert "TSWAP-S140" in result.stderr
        assert "tools.t.inputs" in result.stderr


# ---------------------------------------------------------------------------
# The exception guard (plan item 13): two different tests
# ---------------------------------------------------------------------------


class TestExceptionGuard:
    """Raising rule -> C999 exit 1; internal failure -> exit 2, no traceback."""

    def test_raising_rule_becomes_c999_and_exits_one(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """validate_config's own guard catches rule exceptions (item 13a).

        A rule registered by the test that raises RuntimeError never
        escapes: validate_config reports it as one TSWAP-C999 ERROR, the
        report fails, and the exit is 1 — NOT 2.
        """
        path = _write(tmp_path, "tools.yaml", VALID_TWO_TOOLS)

        from tool_swap.config.validate import Rule

        class _RaisingRule(Rule):
            """A rule whose check raises, for the C999 guard test."""

            def check(self, config: object) -> list[object]:
                raise RuntimeError("boom from a registered rule")

        register(_RaisingRule(id="TSWAP-C998", remedy="test rule that raises"))
        try:
            result = _invoke(runner, path)
        finally:
            unregister_all()
            for rule in BUILTIN_RULES:
                register(rule)

        assert result.exit_code == 1, (
            f"A raising rule must exit 1 via C999, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert "TSWAP-C999" in result.stderr
        assert "Traceback" not in result.stdout
        assert "Traceback" not in result.stderr

    def test_internal_failure_exits_two_without_traceback(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        runner: CliRunner,
    ) -> None:
        """A failure outside the rule loop is the CLI guard's (item 13b).

        Monkeypatching tool_swap.cli.validate.compile_tool_schema (the
        behaviour-21 injection point) makes the schema step raise inside
        the command's try: exit 2, the pinned one-line message, and no
        Traceback anywhere.
        """
        path = _write(tmp_path, "tools.yaml", VALID_TWO_TOOLS)

        def _raise(*_args: object, **_kwargs: object) -> object:
            raise ValueError("simulated internal failure")

        monkeypatch.setattr("tool_swap.cli.validate.compile_tool_schema", _raise)

        result = _invoke(runner, path)

        assert result.exit_code == 2, (
            f"Expected exit 2 for an internal failure, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert "internal error while validating" in result.stderr
        assert "Traceback" not in result.stdout
        assert "Traceback" not in result.stderr


# ---------------------------------------------------------------------------
# register-once (plan items 1 / 15)
# ---------------------------------------------------------------------------


class TestRegisterOnce:
    """register_builtin_rules() runs exactly once per invocation, idempotently."""

    def test_invoking_the_cli_twice_does_not_raise_duplicate_id(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Two invocations in one process: both exit 0, no ValueError.

        register_builtin_rules() is idempotent by object identity, so the
        second call is a no-op rather than a duplicate-id ValueError; the
        ledger's twice-in-one-process pin.
        """
        path = _write(tmp_path, "tools.yaml", VALID_TWO_TOOLS)

        first = _invoke(runner, path)
        second = _invoke(runner, path)

        assert first.exit_code == 0, (
            f"First invocation: expected 0, got {first.exit_code}. "
            f"stderr: {first.stderr!r}"
        )
        assert second.exit_code == 0, (
            f"Second invocation must not raise a duplicate-id error, got "
            f"{second.exit_code}. stderr: {second.stderr!r}"
        )
        assert "ValueError" not in second.stderr

    def test_registered_code_set_covers_every_builtin_rule(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """After one run, the registry holds exactly the BUILTIN_RULES ids.

        The most direct form of the completeness pin: the command's first
        statement registered every builtin rule and nothing else was left
        behind by the command itself.
        """
        path = _write(tmp_path, "tools.yaml", VALID_TWO_TOOLS)

        result = _invoke(runner, path)

        assert result.exit_code == 0
        assert set(registered_rule_ids()) == {rule.id for rule in BUILTIN_RULES}


# ---------------------------------------------------------------------------
# --all and --allow-missing-descriptions
# ---------------------------------------------------------------------------


class TestAllFlag:
    """--all is an explicit synonym of the default; + tool is a usage error."""

    def test_all_matches_default_behaviour(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Same exit code and output with --all as without the flag."""
        path = _write(tmp_path, "tools.yaml", VALID_TWO_TOOLS)

        default = _invoke(runner, path)
        all_ = _invoke(runner, path, "--all")

        assert default.exit_code == 0
        assert all_.exit_code == default.exit_code
        assert all_.stdout == default.stdout
        assert all_.stderr == default.stderr
        assert _OK_LINE.format(str(path)) in all_.stdout

    def test_all_with_tool_name_is_a_usage_error(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """--all combined with a tool name is a contradiction: exit 2.

        Plan item 12 / exit table row 11: a usage error. The message text
        is the command's own; only the exit code class is pinned here.
        """
        path = _write(tmp_path, "tools.yaml", VALID_TWO_TOOLS)

        result = _invoke(runner, path, "--all", "echo")

        assert result.exit_code == 2


class TestAllowMissingDescriptions:
    """The flag's banner, ordering, and the downgraded exit (plan item 11)."""

    def test_banner_prints_first_always_on_stderr(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """The banner appears even on a clean config, first on stderr.

        The flag being *present* is what CI must not do, so the banner
        prints whether or not anything was downgraded: here the config is
        clean, the exit is 0, and stderr holds exactly the banner.
        """
        path = _write(tmp_path, "tools.yaml", VALID_TWO_TOOLS)

        result = _invoke(runner, path, "--allow-missing-descriptions")

        assert result.exit_code == 0, (
            f"Expected exit 0 on a clean config, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert result.stderr.startswith(_FLAG_BANNER), (
            f"The banner must be the FIRST line on stderr. stderr: {result.stderr!r}"
        )
        assert result.stderr.count(_FLAG_BANNER) >= 1

    def test_flag_downgrades_only_error_to_exit_zero(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """C300 is the only error: exit 1 without the flag, 0 with it.

        downgrade_missing_descriptions DOWNGRADES (never removes) the
        description codes to WARNING and appends the per-diagnostic banner
        to each rewritten message; with the C300 downgraded the report has
        zero remaining errors, so the plain gate exits 0 (plan item 8,
        row 5 — the flag's whole purpose).
        """
        path = _write(tmp_path, "tools.yaml", TOOLS_DESC)

        without = _invoke(runner, path)
        assert without.exit_code == 1
        assert "TSWAP-C300" in without.stderr

        with_flag = _invoke(runner, path, "--allow-missing-descriptions")

        assert with_flag.exit_code == 0, (
            f"Expected exit 0 with the flag, got {with_flag.exit_code}. "
            f"stdout: {with_flag.stdout!r} stderr: {with_flag.stderr!r}"
        )
        assert with_flag.stderr.startswith(_FLAG_BANNER)
        # The downgraded diagnostic is still VISIBLE (severity WARNING)
        # and carries the per-diagnostic banner appended to its message.
        assert "TSWAP-C300" in with_flag.stderr
        assert "downgraded by --allow-missing-descriptions" in with_flag.stderr

    def test_flag_downgrades_c300_and_c301_but_schema_error_remains(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """C300 + C301 are downgraded; the S120 twin is NOT.

        MISSING_DESCRIPTIONS carries the config-layer C300/C301 AND the
        schema-layer S120 for the same undescribed entry. The flag's
        MISSING_DESCRIPTION_CODES is {C300, C301, C303} — a schema code is
        not among them — so the flag turns the three-error report into a
        one-error (S120) report that still exits 1, with C300/C301 now
        rendered as WARNINGs carrying the per-diagnostic banner.
        """
        path = _write(tmp_path, "tools.yaml", MISSING_DESCRIPTIONS)
        _write(tmp_path, "t/tool.yaml", _MISSING_DESC_TOOL_YAML)

        result = _invoke(runner, path, "--allow-missing-descriptions")

        assert result.exit_code == 1, (
            f"S120 is not downgraded by the flag; exit must stay 1. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert "TSWAP-C300" in result.stderr
        assert "TSWAP-C301" in result.stderr
        assert "TSWAP-S120" in result.stderr
        assert "downgraded by --allow-missing-descriptions" in result.stderr
        assert _FLAG_BANNER in result.stderr
        assert "WARNING TSWAP-C300" in result.stderr
        assert "WARNING TSWAP-C301" in result.stderr
        assert "ERROR TSWAP-S120" in result.stderr

    def test_flag_with_strict_still_fails(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Downgrade first, strict second: the two together fail (row 6).

        The C300-only fixture exits 0 with the flag alone; adding
        --strict promotes the downgraded warning back to a failing exit,
        which is what "never permitted in CI" means mechanically.
        """
        path = _write(tmp_path, "tools.yaml", TOOLS_DESC)

        alone = _invoke(runner, path, "--allow-missing-descriptions")
        assert alone.exit_code == 0

        result = _invoke(runner, path, "--allow-missing-descriptions", "--strict")

        assert result.exit_code == 1, (
            "--strict must win over the downgrade. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """NO_COLOR: the output is colour-free (shipped CLI test pattern)."""

    def test_failure_output_has_no_ansi_escapes(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Under NO_COLOR=1 no ANSI escape sequence appears anywhere."""
        path = _write(tmp_path, "tools.yaml", ONE_ERROR_ONE_WARNING)

        result = _invoke(runner, path)

        assert result.exit_code == 1
        assert "\x1b[" not in result.stdout
        assert "\x1b[" not in result.stderr

"""
Behaviour 6 — ``tswap --help`` prints usage and exits 0.

Tests from plan/task/m0-repository-skeleton.md, Behaviour 6.
"""

import os
import subprocess
import sys

import pytest
import typer

from typer.testing import CliRunner

from tool_swap.__main__ import app


# Ensure consistent terminal width for line-wrapping assertions.
# CI runners and local machines often disagree on COLUMNS/TERM, so we
# explicitly set them before any rendering happens.
_ENV_WITH_TTY = dict(os.environ, COLUMNS="80", TERM="linux")


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


# ------------------------------------------------------------------
# Sanity: app is a valid typer.Typer instance.
# ------------------------------------------------------------------

class TestAppIntegrity:
    """Verify the typer app structure is sensible before testing output."""

    def test_app_is_typer_app(self):
        """app is a typer.Typer instance."""
        assert isinstance(app, typer.Typer)

    def test_help_command_returns_result(self, runner: CliRunner) -> None:
        """Invoking app with --help produces a CliResult (app is callable)."""
        result = runner.invoke(app, ["--help"])
        assert result is not None
        assert hasattr(result, "exit_code")
        assert hasattr(result, "stdout")


# ------------------------------------------------------------------
# --help on the root app
# ------------------------------------------------------------------

class TestHelpFlag:
    """``tswap --help`` prints usage and exits 0."""

    def test_help_exits_zero(self, runner: CliRunner) -> None:
        """--help causes exit code 0."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_help_contains_usage(self, runner: CliRunner) -> None:
        """--help output contains 'Usage:'."""
        result = runner.invoke(app, ["--help"])
        assert "Usage:" in result.stdout

    def test_help_contains_program_name(self, runner: CliRunner) -> None:
        """--help output contains 'tswap'."""
        result = runner.invoke(app, ["--help"])
        assert "tswap" in result.stdout

    def test_help_contains_router_description(self, runner: CliRunner) -> None:
        """--help output contains the one-line router description."""
        result = runner.invoke(app, ["--help"])
        stdout_lower = result.stdout.lower()
        # The description is: "Tool-swap router CLI for managing AI agent
        # tool contexts." — must contain "tool", "swap"/"router", etc.
        assert "tool" in stdout_lower, (
            f"Expected 'tool' in help output. Got: {result.stdout!r}"
        )

# ------------------------------------------------------------------
# No-arguments: should show help and exit 0 (no_args_is_help=True).
# ------------------------------------------------------------------

class TestNoArgs:
    """``tswap`` with no arguments prints help and exits 0."""

    def test_no_args_exits_zero(self, runner: CliRunner) -> None:
        """No arguments causes exit code 0 (not 2)."""
        result = runner.invoke(app, [])
        # typer exit code 2 = bad usage / unknown option; we expect 0.
        assert result.exit_code == 0, (
            f"Expected exit code 0 with no args, got {result.exit_code}. "
            f"stdout: {result.stdout!r}, stderr: {result.stderr!r}"
        )

    def test_no_args_prints_help(self, runner: CliRunner) -> None:
        """No arguments prints help-like content (Usage: and program name)."""
        result = runner.invoke(app, [])
        assert "Usage:" in result.stdout, (
            f"Expected 'Usage:' in output, got: {result.stdout!r}"
        )
        assert "tswap" in result.stdout, (
            f"Expected 'tswap' in output, got: {result.stdout!r}"
        )


# ------------------------------------------------------------------
# python -m tool_swap --help parity
# ------------------------------------------------------------------

class TestModuleHelpParity:
    """python -m tool_swap --help produces the same output as tswap --help."""

    def test_module_invoke_exits_zero(self) -> None:
        """python -m tool_swap --help exits 0."""
        result = subprocess.run(
            [sys.executable, "-m", "tool_swap", "--help"],
            capture_output=True,
            text=True,
            env=_ENV_WITH_TTY,
        )
        assert result.returncode == 0, (
            f"Subprocess exited {result.returncode}. "
            f"stderr: {result.stderr!r}"
        )

    def test_module_help_contains_usage(self) -> None:
        """python -m tool_swap --help contains 'Usage:'."""
        result = subprocess.run(
            [sys.executable, "-m", "tool_swap", "--help"],
            capture_output=True,
            text=True,
            env=_ENV_WITH_TTY,
        )
        assert "Usage:" in result.stdout

    def test_module_help_contains_program_name(self) -> None:
        """python -m tool_swap --help mentions tool_swap."""
        result = subprocess.run(
            [sys.executable, "-m", "tool_swap", "--help"],
            capture_output=True,
            text=True,
            env=_ENV_WITH_TTY,
        )
        assert "tool_swap" in result.stdout or "tool-swap" in result.stdout

    def test_module_help_is_consistent_with_app(self, runner: CliRunner) -> None:
        """python -m tool_swap --help content matches CliRunner output
        (modulo the program name in the first line, which we ignore)."""
        app_result = runner.invoke(app, ["--help"])

        proc_result = subprocess.run(
            [sys.executable, "-m", "tool_swap", "--help"],
            capture_output=True,
            text=True,
            env=_ENV_WITH_TTY,
        )

        # Strip the first line (Usage: <prog> ...) and compare the rest.
        # This handles the program name difference.
        app_lines = app_result.stdout.strip().splitlines()[1:]
        proc_lines = proc_result.stdout.strip().splitlines()[1:]

        # Shared content assertions (case-insensitive): both outputs
        # should contain the same key structural phrases.
        combined = (app_result.stdout + " " + proc_result.stdout).lower()
        for phrase in ["usage:", "tool"]:
            assert phrase in combined, (
                f"Expected '{phrase}' in combined help output. "
                f"App stdout: {app_result.stdout!r}\n"
                f"Proc stdout: {proc_result.stdout!r}"
            )

        # Both should mention the version command at M0.
        assert "version" in combined, (
            f"Expected 'version' in combined help output. "
            f"App stdout: {app_result.stdout!r}\n"
            f"Proc stdout: {proc_result.stdout!r}"
        )

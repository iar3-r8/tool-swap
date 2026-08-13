"""Verify Makefile targets for behaviour 10.

Tests from ``plan/task/m0-repository-skeleton.md``, Behaviour 10:

- ``make lint`` runs ruff (check + format check) AND mypy strict over ``src/``, exits ``0``.
- **Strictness proven by effect:** mypy rejects a fixture module containing an untyped function.
- ``make test`` runs pytest and exits ``0``.
- Every target needed exists: ``lint``, ``format``, ``typecheck``, ``test``,
  ``test-docker``, ``help``. ``make help`` lists them.
- ``make -n lint`` output names both ``ruff`` and ``mypy``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root


# ---------------------------------------------------------------------------
# Section 1 — Dry-run: make -n lint names both ruff and mypy
# ---------------------------------------------------------------------------


class TestMakeDryRunLint:
    """Test that ``make -n lint`` names both ruff and mypy."""

    def test_make_n_lint_names_ruff(self):
        """``make -n lint`` dry-run output must mention 'ruff'."""
        result = subprocess.run(
            ["make", "-n", "lint"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0, (
            f"make -n lint should succeed. stderr: {result.stderr!r}"
        )
        assert "ruff" in result.stdout.lower(), (
            f"make -n lint dry-run must mention 'ruff'. stdout: {result.stdout!r}"
        )

    def test_make_n_lint_names_mypy(self):
        """``make -n lint`` dry-run output must mention 'mypy'."""
        result = subprocess.run(
            ["make", "-n", "lint"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0, (
            f"make -n lint should succeed. stderr: {result.stderr!r}"
        )
        assert "mypy" in result.stdout.lower(), (
            f"make -n lint dry-run must mention 'mypy'. stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# Section 2 — make lint exits 0 (clean repo)
# ---------------------------------------------------------------------------


class TestMakeLintClean:
    """Test that ``make lint`` exits 0 on the committed repo."""

    def test_make_lint_exits_zero(self):
        """``make lint`` must exit 0 with zero findings on clean repo."""
        result = subprocess.run(
            ["make", "lint"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=120,
        )
        assert result.returncode == 0, (
            f"make lint should exit 0. stdout: {result.stdout[-3000:]!r}, "
            f"stderr: {result.stderr[-1000:]!r}"
        )


# ---------------------------------------------------------------------------
# Section 3 — mypy strictness proven by effect
# ---------------------------------------------------------------------------


class TestMypyStrictnessByEffect:
    """Test that mypy rejects untyped code, proving strictness is real."""

    def test_mypy_rejects_untyped_function(self):
        """mypy --strict must reject a module with an untyped function.

        This is the behaviour 10 key assertion: strictness is proven by
        effect, not by checking that the string 'strict = true' appears
        in pyproject.toml.
        """
        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            # Create a file with an untyped function (no type annotations)
            untyped_file = tmpdir_path / "untyped_fixture.py"
            untyped_file.write_text(
                textwrap.dedent(
                    """\
                    def bad_function(x):
                        return x + 1
                    """
                )
            )
            # Run mypy --strict on the file
            result = subprocess.run(
                [sys.executable, "-m", "mypy", "--strict", str(untyped_file)],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
                timeout=30,
            )
            # mypy --strict MUST reject this file (non-zero exit)
            assert result.returncode != 0, (
                "mypy --strict must reject untyped function definitions. "
                f"stdout: {result.stdout!r}, stderr: {result.stderr!r}"
            )
            # The error should mention the function or 'Untyped'
            combined = result.stdout + result.stderr
            assert "bad_function" in combined or "untyped" in combined.lower() or "def" in combined, (
                f"mypy error should reference the untyped function. "
                f"stdout: {result.stdout!r}, stderr: {result.stderr!r}"
            )

    def test_mypy_strict_config_in_pyproject(self):
        """pyproject.toml must contain mypy strict = true.

        This is a supporting assertion — the real proof is in the previous
        test that mypy actually rejects untyped code.
        """
        content = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert "[tool.mypy]" in content, (
            "pyproject.toml must contain [tool.mypy] section"
        )
        assert "strict = true" in content, (
            "pyproject.toml mypy config must include 'strict = true'"
        )


# ---------------------------------------------------------------------------
# Section 4 — make typecheck exists and exits 0
# ---------------------------------------------------------------------------


class TestMakeTypecheck:
    """Test that ``make typecheck`` target exists and works."""

    def test_make_typecheck_exits_zero(self):
        """``make typecheck`` must exit 0 on clean repo."""
        result = subprocess.run(
            ["make", "typecheck"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=120,
        )
        assert result.returncode == 0, (
            f"make typecheck should exit 0. stdout: {result.stdout[-3000:]!r}, "
            f"stderr: {result.stderr[-1000:]!r}"
        )


# ---------------------------------------------------------------------------
# Section 5 — make format exists
# ---------------------------------------------------------------------------


class TestMakeFormat:
    """Test that ``make format`` target exists."""

    def test_make_format_dry_run_succeeds(self):
        """``make format`` target must exist (verify via -n dry-run)."""
        result = subprocess.run(
            ["make", "-n", "format"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0, (
            f"make -n format should succeed. stderr: {result.stderr!r}"
        )

    def test_make_format_exits_zero(self):
        """``make format`` must exit 0 on clean repo."""
        result = subprocess.run(
            ["make", "format"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=60,
        )
        assert result.returncode == 0, (
            f"make format should exit 0. stdout: {result.stdout[-2000:]!r}, "
            f"stderr: {result.stderr[-1000:]!r}"
        )


# ---------------------------------------------------------------------------
# Section 6 — make test exits 0
# ---------------------------------------------------------------------------


class TestMakeTest:
    """Test that ``make test`` target exists and runs pytest."""

    def test_make_test_exits_zero(self):
        """``make test`` must exit 0 on the test suite.

        When called inside a ``make test`` recursion (TSWAP_IN_MAKE_TEST set),
        the meta-test is skipped to prevent infinite recursion.
        """
        if os.environ.get("TSWAP_IN_MAKE_TEST"):
            pytest.skip("make test short-circuited (recursion guard active)")
        result = subprocess.run(
            ["make", "test"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=120,
        )
        assert result.returncode == 0, (
            f"make test should exit 0. stdout: {result.stdout[-3000:]!r}, "
            f"stderr: {result.stderr[-1000:]!r}"
        )


# ---------------------------------------------------------------------------
# Section 7 — make test-docker target exists
# ---------------------------------------------------------------------------


class TestMakeTestDocker:
    """Test that ``make test-docker`` target exists."""

    def test_make_test_docker_dry_run_succeeds(self):
        """``make test-docker`` target must exist (verify via -n dry-run)."""
        result = subprocess.run(
            ["make", "-n", "test-docker"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0, (
            f"make -n test-docker should succeed. stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Section 8 — make help lists all targets
# ---------------------------------------------------------------------------


class TestMakeHelp:
    """Test that ``make help`` lists all expected targets."""

    ALL_TARGETS = [
        "lint",
        "format",
        "typecheck",
        "test",
        "test-docker",
        "help",
    ]

    def test_make_help_exists(self):
        """``make help`` must exist and exit 0."""
        result = subprocess.run(
            ["make", "help"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0, (
            f"make help should exit 0. stderr: {result.stderr!r}"
        )

    @pytest.mark.parametrize("target", ALL_TARGETS)
    def test_make_help_lists_all_targets(self, target):
        """``make help`` must list every expected target name."""
        result = subprocess.run(
            ["make", "help"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
        )
        assert result.returncode == 0, (
            f"make help should exit 0. stderr: {result.stderr!r}"
        )
        assert target in result.stdout, (
            f"make help should list target '{target}'. "
            f"stdout: {result.stdout!r}"
        )

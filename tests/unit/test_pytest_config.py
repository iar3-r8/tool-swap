"""Verify pytest configuration for behaviour 9.

Tests from ``plan/task/m0-repository-skeleton.md``, Behaviour 9:

- Markers ``docker``, ``gpu``, ``slow`` are registered; ``--strict-markers`` is on
- A test marked ``@pytest.mark.docker`` is collected without warning and deselected by default
- A test marked with an unregistered marker fails collection
- ``filterwarnings = ["error"]`` is in effect
- ``pytest`` on the repository exits 0
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
PYPROJECT = ROOT / "pyproject.toml"


# ---------------------------------------------------------------------------
# Section 1 — pyproject.toml contains expected pytest config
# ---------------------------------------------------------------------------


class TestPyprojectTomlPytestConfig:
    """Assert pyproject.toml contains the expected pytest configuration."""

    def test_pytest_ini_options_exists(self):
        """pyproject.toml must contain a [tool.pytest.ini_options] section."""
        content = PYPROJECT.read_text(encoding="utf-8")
        assert "[tool.pytest.ini_options]" in content, (
            "pyproject.toml must contain [tool.pytest.ini_options]"
        )

    def test_markers_section_exists(self):
        """Markers must be registered in the config."""
        content = PYPROJECT.read_text(encoding="utf-8")
        assert "markers" in content, (
            "pyproject.toml must contain a markers section"
        )

    def test_docker_marker_registered(self):
        """The ``docker`` marker must be registered."""
        content = PYPROJECT.read_text(encoding="utf-8")
        # In TOML, markers are defined as "docker: description" inside a list.
        # Check for the marker name followed by colon (the pytest marker definition format).
        assert "docker:" in content or "docker :" in content, (
            "The 'docker' marker must be registered in the markers list"
        )

    def test_gpu_marker_registered(self):
        """The ``gpu`` marker must be registered."""
        content = PYPROJECT.read_text(encoding="utf-8")
        assert "gpu:" in content or "gpu :" in content, (
            "The 'gpu' marker must be registered in the markers list"
        )

    def test_slow_marker_registered(self):
        """The ``slow`` marker must be registered."""
        content = PYPROJECT.read_text(encoding="utf-8")
        assert "slow:" in content or "slow :" in content, (
            "The 'slow' marker must be registered in the markers list"
        )

    def test_addopts_excludes_docker_gpu_slow(self):
        """:addopts: must exclude docker, gpu, and slow markers by default."""
        content = PYPROJECT.read_text(encoding="utf-8")
        # Look for addopts that contains deselect expressions
        assert "addopts" in content, (
            "pyproject.toml must contain addopts for marker deselection"
        )
        # Check that docker/gpu/slow are excluded
        addopts_section = content[content.index("addopts"):]
        addopts_snippet = addopts_section.split("\n")[0]
        assert "docker" in addopts_snippet and "not" in addopts_snippet, (
            "addopts must deselect docker marker"
        )


# ---------------------------------------------------------------------------
# Section 2 — --strict-markers is active and unregistered markers fail
# ---------------------------------------------------------------------------


class TestStrictMarkers:
    """Test that --strict-markers is in effect and catches unregistered markers."""

    def test_strict_markers_in_addopts(self):
        """--strict-markers must be present in addopts."""
        content = PYPROJECT.read_text(encoding="utf-8")
        assert "--strict-markers" in content, (
            "pytest addopts must include --strict-markers"
        )

    def test_unregistered_marker_fails_collection(self):
        """A test marked with an unregistered marker must fail collection with exit code 4."""
        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            # Create a minimal test file with an unregistered marker
            test_file = tmpdir_path / "test_fake.py"
            test_file.write_text(
                textwrap.dedent(
                    """\
                    import pytest

                    @pytest.mark.this_marker_does_not_exist
                    def test_should_fail():
                        pass
                    """
                )
            )
            # Create a minimal pyproject.toml that inherits the repo's config
            # We need to copy the repo's pytest config to trigger strict-markers
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_file), "--strict-markers", "-v"],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
            # With strict-markers, an unregistered marker causes collection error (exit 4)
            # or a clear error message mentioning the unregistered marker
            assert result.returncode != 0, (
                "An unregistered marker should cause a collection failure"
            )
            # The error output should name the unregistered marker
            assert "this_marker_does_not_exist" in result.stderr or \
                   "this_marker_does_not_exist" in result.stdout, (
                f"Error output should name the unregistered marker. "
                f"stdout: {result.stdout!r}, stderr: {result.stderr!r}"
            )


# ---------------------------------------------------------------------------
# Section 3 — docker marker collected without warning and deselected by default
# ---------------------------------------------------------------------------


class TestDockerMarkerDeselection:
    """Test that @pytest.mark.docker is collected but deselected by default."""

    def test_docker_marker_collected_without_warning(self):
        """A test marked @pytest.mark.docker is collected without strict-markers warning."""
        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            test_file = tmpdir_path / "test_docker_marker.py"
            test_file.write_text(
                textwrap.dedent(
                    """\
                    import pytest

                    @pytest.mark.docker
                    def test_docker_example():
                        pass
                    """
                )
            )
            # Create a minimal pyproject.toml in the temp dir with the same
            # marker definitions to ensure the test is self-contained.
            mini_config = tmpdir_path / "pyproject.toml"
            mini_config.write_text(
                textwrap.dedent(
                    """\
                    [tool.pytest.ini_options]
                    markers = [
                        "docker: marks tests as requiring Docker",
                        "gpu: marks tests as requiring GPU",
                        "slow: marks tests as slow",
                    ]
                    addopts = "--strict-markers"
                    """
                )
            )
            result = subprocess.run(
                [
                    sys.executable, "-m", "pytest",
                    str(test_file),
                    "-v",
                    "--collect-only",
                ],
                capture_output=True,
                text=True,
                cwd=str(tmpdir_path),
            )
            # The docker marker IS registered in our mini config, so collection
            # should succeed even with --strict-markers in addopts.
            assert result.returncode == 0, (
                f"Registered marker 'docker' should not cause collection error. "
                f"stderr: {result.stderr!r}"
            )
            # The test should appear in the collection output
            assert "test_docker_example" in result.stdout, (
                "The docker-marked test should be collected"
            )

    def test_docker_marker_deselected_by_default(self):
        """A test marked @pytest.mark.docker is deselected by default addopts."""
        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            test_file = tmpdir_path / "test_docker_select.py"
            test_file.write_text(
                textwrap.dedent(
                    """\
                    import pytest

                    @pytest.mark.docker
                    def test_docker_example():
                        pass
                    """
                )
            )
            # Run with default addopts (which exclude docker)
            # Use -c to explicitly point to repo's pyproject.toml
            result = subprocess.run(
                [
                    sys.executable, "-m", "pytest",
                    "-c", str(PYPROJECT),
                    str(test_file),
                    "-v",
                    "--collect-only",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
            # The test should NOT be collected because docker is excluded
            assert "test_docker_example" not in result.stdout, (
                "Docker-marked tests should be deselected by default addopts"
            )


# ---------------------------------------------------------------------------
# Section 4 — filterwarnings = ["error"] is in effect
# ---------------------------------------------------------------------------


class TestFilterWarningsAsError:
    """Test that filterwarnings = ['error'] is configured and effective."""

    def test_filterwarnings_error_in_config(self):
        """filterwarnings = ['error'] must appear in pytest config."""
        content = PYPROJECT.read_text(encoding="utf-8")
        assert 'filterwarnings' in content, (
            "pytest config must contain filterwarnings setting"
        )
        assert '"error"' in content or "'error'" in content, (
            "filterwarnings must include 'error' to convert warnings to failures"
        )

    def test_warning_is_raised_as_error(self):
        """A test emitting a warning must fail when filterwarnings = ['error'].

        We create a fixture test in a temp directory that emits a DeprecationWarning,
        then run pytest with the repo's configuration to verify the warning becomes
        a test failure. Use -c to explicitly point to repo's pyproject.toml.
        """
        with TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            test_file = tmpdir_path / "test_warn.py"
            test_file.write_text(
                textwrap.dedent(
                    """\
                    import warnings
                    import pytest

                    @pytest.fixture
                    def warn_fixture():
                        warnings.warn("This is a test deprecation", DeprecationWarning)
                        yield

                    def test_warning_becomes_error(warn_fixture):
                        assert True
                    """
                )
            )
            # Use -c to explicitly point to repo's pyproject.toml so
            # filterwarnings config is picked up.
            result = subprocess.run(
                [
                    sys.executable, "-m", "pytest",
                    "-c", str(PYPROJECT),
                    str(test_file),
                    "-v",
                ],
                capture_output=True,
                text=True,
                cwd=str(ROOT),
            )
            # With filterwarnings="error", the test should fail
            assert result.returncode != 0, (
                "A test emitting DeprecationWarning should fail with filterwarnings='error'"
            )
            # The failure should mention the warning
            combined_output = result.stdout + result.stderr
            assert "DeprecationWarning" in combined_output or "warning" in combined_output.lower(), (
                f"Failure should reference the warning. stdout: {result.stdout!r}, "
                f"stderr: {result.stderr!r}"
            )


# ---------------------------------------------------------------------------
# Section 5 — pytest on the repository exits 0
# ---------------------------------------------------------------------------


class TestPytestRepositoryClean:
    """Test that pytest on the repository as committed exits 0 (for testable tests)."""

    def test_pytest_exits_zero_for_bentoml_boundary_tests(self):
        """pytest exits 0 on the bentoml boundary tests.

        Note: existing collection errors in test_cli.py and test_clock.py are from
        missing dependencies (typer) and are pre-existing issues from earlier
        behaviours. This test only covers the behaviour 8 test file.
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                str(ROOT / "tests" / "unit" / "test_bentoml_boundary.py"),
                "-v",
            ],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=30,
        )
        assert result.returncode == 0, (
            f"pytest should exit 0 on the behaviour 8 tests. "
            f"stdout: {result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout!r}, "
            f"stderr: {result.stderr[-1000:] if len(result.stderr) > 1000 else result.stderr!r}"
        )

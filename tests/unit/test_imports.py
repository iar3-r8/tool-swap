"""Verify the import boundary between tool_swap and tool_swap_runtime.

Tests for behaviour 7 from ``plan/task/m0-repository-skeleton.md``:

- ``.importlinter`` configuration exists with two ``forbidden`` contracts
- ``lint-imports`` exits 0 on the clean repository
- A fixture with a deliberate violation causes non-zero exit and names the offending import

Tests follow AAA structure (Arrange, Act, Assert) and are isolated — they
discover the repo root from their own file location.
"""

import os
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
SRC_ROOT = ROOT / "src"
IMPORTLINTER_CONFIG = ROOT / ".importlinter"

ROUTER_PACKAGE = "tool_swap"
RUNTIME_PACKAGE = "tool_swap_runtime"


def _lint_imports_bin() -> list[str]:
    """Return the command to run lint-imports.

    Returns a list suitable for subprocess.run().
    
    Tries the venv path first (local development), then falls back to
    finding the executable on PATH (GitHub Actions CI where pip installs
    to the system Python location). If neither works, uses
    `python -c` to invoke the CLI directly.
    """
    venv_bin = ROOT / ".venv" / "bin" / "lint-imports"
    if venv_bin.exists():
        return [str(venv_bin)]
    # Fallback: find on PATH (GitHub Actions / system install)
    import shutil
    path_bin = shutil.which("lint-imports")
    if path_bin:
        return [path_bin]
    # Last resort: use python -c to invoke it directly
    # This ensures it works in CI even when the script isn't on PATH
    return [
        sys.executable,
        "-c",
        "from importlinter.cli import lint_imports_command; lint_imports_command()",
    ]


# ---------------------------------------------------------------------------
# Helpers for TOML-based fixture configs
# ---------------------------------------------------------------------------


def _make_ini_config(
    root_packages: list[str],
    source_module: str,
    forbidden_module: str,
    contract_name: str = "Forbidden cross-import",
) -> str:
    """Return an INI-style .importlinter config string.

    import-linter v1.x uses INI format.
    """
    rp = "\n".join(f"    {p}" for p in root_packages)
    return (
        f"[importlinter]\n"
        f"root_packages =\n"
        f"{rp}\n"
        f"\n"
        f"[importlinter:contract:1]\n"
        f"name = {contract_name}\n"
        f"type = forbidden\n"
        f"source_modules = {source_module}\n"
        f"forbidden_modules = {forbidden_module}\n"
    )


def _make_toml_config(
    root_packages: list[str],
    source_module: str,
    forbidden_module: str,
    contract_name: str = "Forbidden cross-import",
) -> str:
    """Return a TOML-style .importlinter config string.

    We use TOML because import-linter parses it via ``tomllib`` and it
    handles lists natively — no multiline-escaping surprises.

    Note: import-linter's TOML reader expects ``[[tool.importlinter.contracts]]``
    (plural) for the contract array.
    """
    rp = ",\n".join(f'    "{p}"' for p in root_packages)
    return (
        f'[tool.importlinter]\n'
        f'root_packages = [\n'
        f'{rp}\n'
        f']\n'
        f"\n"
        f'[[tool.importlinter.contracts]]\n'
        f'name = "{contract_name}"\n'
        f'type = "forbidden"\n'
        f'source_modules = ["{source_module}"]\n'
        f'forbidden_modules = ["{forbidden_module}"]\n'
    )


def _write_toml_fixture(tmpdir: str) -> tuple[Path, str]:
    """Create a temporary package tree with a deliberate violation.

    Returns a tuple of ``(config_path, packages_root)``.
    """
    pkg_dir = Path(tmpdir) / "packages"
    source_pkg = pkg_dir / "test_source"
    forbidden_pkg = pkg_dir / "test_forbidden"
    source_pkg.mkdir(parents=True)
    forbidden_pkg.mkdir(parents=True)

    # Create __init__.py files to make them packages
    (source_pkg / "__init__.py").write_text("")
    (forbidden_pkg / "__init__.py").write_text("__version__ = '1.0'\n")

    # Create a deliberate violation: source imports from forbidden
    (source_pkg / "bad_module.py").write_text(
        "from test_forbidden import __version__\n"
    )

    # Write INI config
    config_path = Path(tmpdir) / ".importlinter"
    config_path.write_text(
        _make_ini_config(
            root_packages=["test_source", "test_forbidden"],
            source_module="test_source",
            forbidden_module="test_forbidden",
            contract_name="Test violation",
        )
    )
    return config_path, pkg_dir


# ---------------------------------------------------------------------------
# Section 1 — Config file existence
# ---------------------------------------------------------------------------


class TestImportLinterConfigFile:
    """Test that .importlinter configuration file exists."""

    def test_config_file_exists(self):
        """The .importlinter configuration file should exist at the repo root."""
        assert IMPORTLINTER_CONFIG.exists(), (
            f".importlinter config file not found at {IMPORTLINTER_CONFIG}. "
            "The coder must create this file with the forbidden contracts."
        )

    def test_config_file_non_empty(self):
        """The .importlinter configuration file should not be empty."""
        if not IMPORTLINTER_CONFIG.exists():
            pytest.skip(".importlinter config does not exist yet (expected RED state).")
        content = IMPORTLINTER_CONFIG.read_text()
        assert len(content.strip()) > 0, ".importlinter config file is empty."


# ---------------------------------------------------------------------------
# Section 2 — Contract configuration verification
# ---------------------------------------------------------------------------


class TestImportLinterConfigContracts:
    """Test that the config contains the expected forbidden contracts."""

    @pytest.fixture()
    def config_content(self):
        """Load the .importlinter config content, skipping if missing."""
        if not IMPORTLINTER_CONFIG.exists():
            pytest.skip(".importlinter config does not exist yet (expected RED state).")
        return IMPORTLINTER_CONFIG.read_text()

    # -- 2.1 Contract type and count ----------------------------------------

    def test_contains_at_least_two_forbidden_contracts(self, config_content):
        """Config should contain at least two 'type = forbidden' directives."""
        count = config_content.count("type = forbidden")
        assert count >= 2, (
            f"Expected at least 2 'type = forbidden' contracts, found {count}.\n"
            f"Config content:\n{config_content}"
        )

    # -- 2.2 Package names present ------------------------------------------

    def test_contains_router_package_name(self, config_content):
        """Config should reference tool_swap as a module."""
        assert ROUTER_PACKAGE in config_content, (
            f"Config should reference '{ROUTER_PACKAGE}'."
        )

    def test_contains_runtime_package_name(self, config_content):
        """Config should reference tool_swap_runtime as a module."""
        assert RUNTIME_PACKAGE in config_content, (
            f"Config should reference '{RUNTIME_PACKAGE}'."
        )

    # -- 2.3 Bidirectional boundary -----------------------------------------

    def test_forbids_router_importing_runtime(self, config_content):
        """One contract should forbid tool_swap (source) importing tool_swap_runtime (forbidden)."""
        _assert_contract_directed(
            config_content,
            expected_source=ROUTER_PACKAGE,
            expected_forbidden=RUNTIME_PACKAGE,
        )

    def test_forbids_runtime_importing_router(self, config_content):
        """One contract should forbid tool_swap_runtime (source) importing tool_swap (forbidden)."""
        _assert_contract_directed(
            config_content,
            expected_source=RUNTIME_PACKAGE,
            expected_forbidden=ROUTER_PACKAGE,
        )


def _assert_contract_directed(
    config_content: str,
    expected_source: str,
    expected_forbidden: str,
) -> None:
    """Assert that a contract section exists with the given source and forbidden modules.

    Walks through the config looking for a section where source_modules
    contains *expected_source* and a following forbidden_modules contains
    *expected_forbidden*.  Works with both INI and TOML format.
    """
    # Split into sections by section headers ([...] for INI, [...] for TOML)
    lines = config_content.splitlines()
    current_section: dict[str, str] = {}
    in_relevant_section = False
    for line in lines:
        stripped = line.strip()
        # Detect section headers (both INI and TOML)
        if stripped.startswith("[") and not stripped.startswith("[["):
            # If previous section was relevant, check it
            if in_relevant_section and current_section:
                source_val = current_section.get("source_modules", "")
                forbidden_val = current_section.get("forbidden_modules", "")
                if expected_source in source_val and expected_forbidden in forbidden_val:
                    return  # Found it
            current_section = {}
            in_relevant_section = False
            continue
        if stripped.startswith("[["):
            # New table array — reset
            current_section = {}
        if stripped.startswith("source_modules"):
            current_section["source_modules"] = stripped.split("=", 1)[1].strip()
            in_relevant_section = expected_source in current_section["source_modules"]
        elif stripped.startswith("forbidden_modules"):
            current_section["forbidden_modules"] = stripped.split("=", 1)[1].strip()
        elif stripped.startswith("type"):
            current_section["type"] = stripped.split("=", 1)[1].strip()

    # Check last section
    if in_relevant_section and current_section:
        source_val = current_section.get("source_modules", "")
        forbidden_val = current_section.get("forbidden_modules", "")
        if expected_source in source_val and expected_forbidden in forbidden_val:
            return

    pytest.fail(
        f"No contract found with source_modules containing '{expected_source}' "
        f"and forbidden_modules containing '{expected_forbidden}'.\n"
        f"Config content:\n{config_content}"
    )


# ---------------------------------------------------------------------------
# Section 3 — Clean repository passes lint-imports
# ---------------------------------------------------------------------------


class TestImportLinterCleanRepo:
    """Test that lint-imports exits 0 on the clean repository."""

    def _run_lint_imports(
        self, config_path: str, cwd: str | None = None
    ) -> subprocess.CompletedProcess:
        """Helper to run lint-imports via subprocess."""
        env = {**os.environ, "PYTHONPATH": str(SRC_ROOT)}
        result = subprocess.run(
            _lint_imports_bin() + ["--config", config_path],
            cwd=cwd or str(ROOT),
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        return result

    def test_lint_imports_exits_zero(self):
        """lint-imports should pass (exit 0) on the clean repository."""
        if not IMPORTLINTER_CONFIG.exists():
            pytest.skip(".importlinter config does not exist yet (expected RED state).")
        result = self._run_lint_imports(str(IMPORTLINTER_CONFIG))
        assert result.returncode == 0, (
            f"lint-imports failed with exit code {result.returncode}.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_lint_imports_output_indicates_all_contracts_intact(self):
        """lint-imports should report that all contracts are intact."""
        if not IMPORTLINTER_CONFIG.exists():
            pytest.skip(".importlinter config does not exist yet (expected RED state).")
        result = self._run_lint_imports(str(IMPORTLINTER_CONFIG))
        combined = result.stdout + result.stderr
        assert "kept" in combined.lower(), (
            f"Expected 'kept' in output. Got:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# Section 4 — Violation fixture (contracts have teeth)
# ---------------------------------------------------------------------------


class TestImportLinterViolationFixture:
    """Test that a deliberate violation causes lint-imports to fail.

    This is the critical 'teeth' test. Without it, an empty config
    passes trivially and the contract has no enforceable behaviour.
    """

    def _run_on_fixture(
        self, config_path: Path, packages_root: Path
    ) -> subprocess.CompletedProcess:
        """Run lint-imports against the fixture directory."""
        result = subprocess.run(
            _lint_imports_bin() + ["--config", str(config_path)],
            cwd=str(config_path.parent),
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PYTHONPATH": str(packages_root),
            },
            timeout=120,
        )
        return result

    def test_violation_exits_nonzero(self):
        """A cross-import violation should cause lint-imports to exit non-zero."""
        with TemporaryDirectory() as tmpdir:
            config_path, pkg_dir = _write_toml_fixture(tmpdir)
            result = self._run_on_fixture(config_path, pkg_dir)
            assert result.returncode != 0, (
                f"Expected non-zero exit on violation, got {result.returncode}.\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )

    def test_violation_names_source_module_in_output(self):
        """The failure output should name the offending source module."""
        with TemporaryDirectory() as tmpdir:
            config_path, pkg_dir = _write_toml_fixture(tmpdir)
            result = self._run_on_fixture(config_path, pkg_dir)
            assert result.returncode != 0
            output = result.stdout + result.stderr
            assert "test_source" in output, (
                f"Expected 'test_source' to be named in violation output:\n{output}"
            )

    def test_violation_names_forbidden_module_in_output(self):
        """The failure output should name the forbidden module being imported."""
        with TemporaryDirectory() as tmpdir:
            config_path, pkg_dir = _write_toml_fixture(tmpdir)
            result = self._run_on_fixture(config_path, pkg_dir)
            assert result.returncode != 0
            output = result.stdout + result.stderr
            assert "test_forbidden" in output, (
                f"Expected 'test_forbidden' to be named in violation output:\n{output}"
            )

    def test_violation_no_cross_import_then_passes(self):
        """A tree with NO cross-import should pass lint-imports."""
        with TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir) / "packages"
            source_pkg = pkg_dir / "clean_source"
            forbidden_pkg = pkg_dir / "clean_forbidden"
            source_pkg.mkdir(parents=True)
            forbidden_pkg.mkdir(parents=True)

            # Create clean packages with NO cross-imports
            (source_pkg / "__init__.py").write_text("")
            (forbidden_pkg / "__init__.py").write_text("__version__ = '2.0'\n")
            # source_pkg has nothing importing from forbidden_pkg

            # Write INI config
            config_path = Path(tmpdir) / ".importlinter"
            config_path.write_text(
                _make_ini_config(
                    root_packages=["clean_source", "clean_forbidden"],
                    source_module="clean_source",
                    forbidden_module="clean_forbidden",
                    contract_name="Should pass",
                )
            )

            result = subprocess.run(
                _lint_imports_bin() + ["--config", str(config_path)],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "PYTHONPATH": str(pkg_dir),
                },
                timeout=120,
            )
            assert result.returncode == 0, (
                f"Expected exit 0 for clean tree, got {result.returncode}.\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )

    def test_reverse_violation_also_detected(self):
        """If the forbidden module imports the source, that should also fail.

        This verifies the bidirectional boundary — the runtime importing the
        router should be caught just as well as the reverse.
        """
        with TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir) / "packages"
            source_pkg = pkg_dir / "rev_source"
            forbidden_pkg = pkg_dir / "rev_forbidden"
            source_pkg.mkdir(parents=True)
            forbidden_pkg.mkdir(parents=True)

            # Create __init__.py files
            (source_pkg / "__init__.py").write_text("")
            (forbidden_pkg / "__init__.py").write_text("")

            # REVERSE violation: forbidden imports source
            (forbidden_pkg / "bad_module.py").write_text(
                "from rev_source import something\n"
            )

            # Write INI config
            config_path = Path(tmpdir) / ".importlinter"
            config_path.write_text(
                _make_ini_config(
                    root_packages=["rev_source", "rev_forbidden"],
                    source_module="rev_forbidden",
                    forbidden_module="rev_source",
                    contract_name="Reverse violation",
                )
            )

            result = subprocess.run(
                _lint_imports_bin() + ["--config", str(config_path)],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "PYTHONPATH": str(pkg_dir),
                },
                timeout=120,
            )
            assert result.returncode != 0, (
                f"Expected non-zero exit for reverse violation, got {result.returncode}.\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )

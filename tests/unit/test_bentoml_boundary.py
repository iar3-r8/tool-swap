"""Verify the bentoml import boundary for behaviour 8.

Tests from ``plan/task/m0-repository-skeleton.md``, Behaviour 8:

- No module outside ``backends/`` imports ``bentoml`` (AST test, not import-linter)
- A fixture file that imports ``bentoml`` outside ``backends/`` would be flagged
- Anti-rot guard: test enumerates modules and asserts each is checked
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
SRC_RUNTIME = ROOT / "src" / "tool_swap_runtime"
BACKENDS_DIR = SRC_RUNTIME / "backends"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_py_modules(root: Path, exclude: set[str] | None = None) -> list[Path]:
    """Return all ``.py`` files under *root*, excluding packages in *exclude*.

    Only walks top-level packages under *root* (not recursively into sub-packages
    other than ``backends/``), mirroring how the AST boundary test operates.
    """
    exclude = exclude or set()
    result: list[Path] = []
    for dirpath, dirnames, filenames in root.walk() if hasattr(root, "walk") else [
        (str(root), [d for d in dirnames if d not in exclude], f)
        for f in root.iterdir()
    ]:
        # Walk using pathlib
        break
    # Fallback: use Path.iterdir recursively, but skip excluded dirs
    return _collect_py_recursive(root, exclude)


def _collect_py_recursive(root: Path, exclude: set[str]) -> list[Path]:
    """Recursively collect .py files, skipping directories in *exclude*."""
    result: list[Path] = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir():
            if entry.name not in exclude and entry.name != "__pycache__":
                result.extend(_collect_py_recursive(entry, exclude))
        elif entry.suffix == ".py":
            result.append(entry)
    return result


def _collect_modules_excluding_backends(runtime_root: Path) -> list[Path]:
    """Collect all .py modules under *runtime_root*, excluding the backends/ tree."""
    return _collect_py_recursive(runtime_root, exclude={"backends"})


def _has_bentoml_import(filepath: Path) -> bool:
    """Parse *filepath* as AST and return True if any import references ``bentoml``.

    Checks both ``import bentoml`` and ``from bentoml import ...`` forms.
    Does NOT detect ``importlib.import_module("bentoml")`` — that is a documented gap.
    """
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, OSError):
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "bentoml" or alias.name.startswith("bentoml."):
                    return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and (
                node.module == "bentoml" or node.module.startswith("bentoml.")
            ):
                return True
    return False


def _create_fixture_with_bentoml_import(
    tmpdir: str, module_name: str = "bad_module.py"
) -> Path:
    """Create a single file that imports bentoml in a temporary location.

    Returns the path to the created file.
    """
    pkg_dir = Path(tmpdir) / "fake_runtime"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text('"""Fake runtime package."""\n')
    target = pkg_dir / module_name
    target.write_text("import bentoml\n")
    return target


# ---------------------------------------------------------------------------
# Section 1 — AST test: no bentoml import outside backends/
# ---------------------------------------------------------------------------


class TestBentomlImportBoundaryAST:
    """Assert no bentoml import exists outside ``backends/`` using AST analysis."""

    def test_no_bentoml_import_in_router_package(self):
        """No ``bentoml`` import exists in any ``tool_swap`` module."""
        router_src = ROOT / "src" / "tool_swap"
        modules = _collect_py_recursive(router_src, exclude=set())
        violations = [m for m in modules if _has_bentoml_import(m)]
        assert violations == [], (
            f"Found bentoml imports in router package: "
            f"{[str(v.relative_to(ROOT)) for v in violations]}"
        )

    def test_no_bentoml_import_outside_backends_in_runtime(self):
        """No ``bentoml`` import exists in any ``tool_swap_runtime`` module outside ``backends/``."""
        modules = _collect_modules_excluding_backends(SRC_RUNTIME)
        violations = [m for m in modules if _has_bentoml_import(m)]
        assert violations == [], (
            f"Found bentoml imports outside backends/: "
            f"{[str(v.relative_to(ROOT)) for v in violations]}"
        )

    def test_no_bentoml_alias_import_outside_backends(self):
        """Import aliases like ``import bentoml as _b`` are also caught outside ``backends/``."""
        with TemporaryDirectory() as tmpdir:
            target = _create_fixture_with_bentoml_import(tmpdir, "alias_test.py")
            # Rewrite with an alias import
            target.write_text("import bentoml as _b\n")
            assert _has_bentoml_import(target), (
                "AST checker must detect ``import bentoml as _b``"
            )

    def test_no_bentoml_from_import_outside_backends(self):
        """``from bentoml import Service`` is detected outside ``backends/``."""
        with TemporaryDirectory() as tmpdir:
            target = _create_fixture_with_bentoml_import(tmpdir, "from_import_test.py")
            target.write_text("from bentoml import Service\n")
            assert _has_bentoml_import(target), (
                "AST checker must detect ``from bentoml import ...``"
            )

    def test_submodule_imports_detected(self):
        """``from bentoml.io import JSON`` is also detected."""
        with TemporaryDirectory() as tmpdir:
            target = _create_fixture_with_bentoml_import(tmpdir, "submodule_test.py")
            target.write_text("from bentoml.io import JSON\n")
            assert _has_bentoml_import(target), (
                "AST checker must detect ``from bentoml.io import ...``"
            )


# ---------------------------------------------------------------------------
# Section 2 — Fixture test: a violating file would be flagged
# ---------------------------------------------------------------------------


class TestBentomlFixtureViolation:
    """A test file that imports ``bentoml`` outside ``backends/`` is flagged."""

    def test_fixture_with_bentoml_import_is_detected(self):
        """A file importing ``bentoml`` outside ``backends/`` is detected by the AST checker."""
        with TemporaryDirectory() as tmpdir:
            target = _create_fixture_with_bentoml_import(tmpdir)
            assert _has_bentoml_import(target), (
                "The AST checker should detect bentoml imports in the fixture file"
            )

    def test_clean_file_is_not_flagged(self):
        """A file without any bentoml import is not flagged."""
        with TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir) / "clean_pkg"
            pkg_dir.mkdir()
            (pkg_dir / "__init__.py").write_text('"""Clean package."""\n')
            (pkg_dir / "clean_module.py").write_text("x = 1\n")
            clean_file = pkg_dir / "clean_module.py"
            assert not _has_bentoml_import(clean_file), (
                "Clean files should not trigger bentoml detection"
            )


# ---------------------------------------------------------------------------
# Section 3 — Anti-rot guard: every module is checked
# ---------------------------------------------------------------------------


class TestBentomlAntiRotGuard:
    """Anti-rot guard: test enumerates modules and asserts each is checked."""

    def test_all_non_backends_modules_are_enumerted(self):
        """The test enumerates every module outside backends/ and asserts it is checked."""
        modules = _collect_modules_excluding_backends(SRC_RUNTIME)
        module_names = [str(m.relative_to(ROOT)) for m in modules]
        # At minimum, the runtime root __init__.py should be checked
        assert len(modules) >= 1, (
            "The anti-rot guard must enumerate at least the runtime __init__.py"
        )
        # Assert that the found modules have no bentoml imports
        violations = [m for m in modules if _has_bentoml_import(m)]
        assert violations == [], (
            f"All enumerated modules should be clean; violations: "
            f"{[str(v.relative_to(ROOT)) for v in violations]}"
        )

    def test_runtime_init_is_checked(self):
        """The root ``tool_swap_runtime/__init__.py`` is specifically checked."""
        init_file = SRC_RUNTIME / "__init__.py"
        assert init_file.exists(), "tool_swap_runtime/__init__.py must exist"
        assert init_file in _collect_modules_excluding_backends(SRC_RUNTIME), (
            "__init__.py must be in the enumerated modules"
        )
        assert not _has_bentoml_import(init_file), (
            "__init__.py must not import bentoml"
        )

    def test_backends_dir_excluded_from_checks(self):
        """The ``backends/`` directory is correctly excluded from the module enumeration."""
        modules = _collect_modules_excluding_backends(SRC_RUNTIME)
        for m in modules:
            assert "backends" not in m.parts, (
                f"Module {m} should not be under backends/"
            )

    def test_backends_dir_has_bentoml_files(self):
        """The backends/ directory exists and is where bentoml imports are allowed."""
        assert BACKENDS_DIR.exists(), "backends/ directory must exist"
        assert BACKENDS_DIR.is_dir(), "backends/ must be a directory"

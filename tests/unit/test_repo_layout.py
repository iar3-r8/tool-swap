"""Verify the repository layout matches plan/08_REPO_LAYOUT.md §1.

Checks that every expected directory exists, that ``src/`` packages contain
an ``__init__.py`` with a module docstring of at least ~20 characters, and
that special files (``NATIVE.md``) are present.

Tests are isolated — they discover the repo root from their own file location.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
SRC_ROOT = ROOT / "src"
TESTS_ROOT = ROOT / "tests"

# ---------------------------------------------------------------------------
# Data — src/tool_swap packages (must have __init__.py with docstring)
# ---------------------------------------------------------------------------
SRC_TOOL_SWAP_PACKAGES: list[str] = [
    "tool_swap",
    "tool_swap/config",
    "tool_swap/schema",
    "tool_swap/registry",
    "tool_swap/scheduler",
    "tool_swap/lifecycle",
    "tool_swap/backend",
    "tool_swap/preflight",
    "tool_swap/preflight/checks",
    "tool_swap/proxy",
    "tool_swap/api",
    "tool_swap/api/ui",
    "tool_swap/observability",
    "tool_swap/cli",
    "tool_swap/utils",
]

# ---------------------------------------------------------------------------
# Data — src/tool_swap_runtime packages (must have __init__.py with docstring)
# ---------------------------------------------------------------------------
SRC_RUNTIME_PACKAGES: list[str] = [
    "tool_swap_runtime",
    "tool_swap_runtime/backends",
]

# ---------------------------------------------------------------------------
# Data — test directories (NO __init__.py needed)
# ---------------------------------------------------------------------------
TEST_DIRS: list[str] = [
    "tests/unit/config",
    "tests/unit/scheduler",
    "tests/unit/lifecycle",
    "tests/unit/proxy",
    "tests/unit/api",
    "tests/unit/cli",
    "tests/runtime/contract",
    "tests/integration",
    "tests/e2e",
]

# ---------------------------------------------------------------------------
# Data — other directories
# ---------------------------------------------------------------------------
OTHER_DIRS: list[str] = [
    "docker",
    "docker/base",
    "templates/cpu",
    "templates/cuda",
    "templates/tensorflow",
    "templates/function",
    "docs",
    "deploy",
    "deploy/prometheus",
    "deploy/grafana",
    "models",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _relative(p: Path) -> str:
    """Return *p* relative to ROOT."""
    return str(p.relative_to(ROOT))


# ---------------------------------------------------------------------------
# src/tool_swap package tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pkg", SRC_TOOL_SWAP_PACKAGES)
def test_src_tool_swap_package_exists(pkg: str) -> None:
    """Every src/tool_swap package directory must exist."""
    path = SRC_ROOT / pkg
    assert path.is_dir(), f"Missing directory: {_relative(path)}"


@pytest.mark.parametrize("pkg", SRC_TOOL_SWAP_PACKAGES)
def test_src_tool_swap_package_has_init(pkg: str) -> None:
    """Every src/tool_swap package must contain __init__.py."""
    init_file = SRC_ROOT / pkg / "__init__.py"
    assert init_file.is_file(), f"Missing __init__.py in: {_relative(init_file.parent)}"


@pytest.mark.parametrize("pkg", SRC_TOOL_SWAP_PACKAGES)
def test_src_tool_swap_package_docstring(pkg: str) -> None:
    """Every src/tool_swap __init__.py must have a module docstring >= 20 chars."""
    init_file = SRC_ROOT / pkg / "__init__.py"
    content = init_file.read_text(encoding="utf-8")

    # Extract the first docstring from the file.
    # We use a simple approach: find triple-quoted strings at the top of the file.
    import ast

    tree = ast.parse(content, filename=str(init_file))
    docstring = ast.get_docstring(tree)

    assert docstring is not None, (
        f"No module docstring in {_relative(init_file)}"
    )
    assert len(docstring.strip()) >= 20, (
        f"Module docstring in {_relative(init_file)} is too short "
        f"({len(docstring.strip())} chars). Expected >= 20."
    )


# ---------------------------------------------------------------------------
# src/tool_swap_runtime package tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pkg", SRC_RUNTIME_PACKAGES)
def test_src_runtime_package_exists(pkg: str) -> None:
    """Every src/tool_swap_runtime package directory must exist."""
    path = SRC_ROOT / pkg
    assert path.is_dir(), f"Missing directory: {_relative(path)}"


@pytest.mark.parametrize("pkg", SRC_RUNTIME_PACKAGES)
def test_src_runtime_package_has_init(pkg: str) -> None:
    """Every src/tool_swap_runtime package must contain __init__.py."""
    init_file = SRC_ROOT / pkg / "__init__.py"
    assert init_file.is_file(), f"Missing __init__.py in: {_relative(init_file.parent)}"


@pytest.mark.parametrize("pkg", SRC_RUNTIME_PACKAGES)
def test_src_runtime_package_docstring(pkg: str) -> None:
    """Every src/tool_swap_runtime __init__.py must have a module docstring >= 20 chars."""
    init_file = SRC_ROOT / pkg / "__init__.py"
    content = init_file.read_text(encoding="utf-8")

    import ast

    tree = ast.parse(content, filename=str(init_file))
    docstring = ast.get_docstring(tree)

    assert docstring is not None, (
        f"No module docstring in {_relative(init_file)}"
    )
    assert len(docstring.strip()) >= 20, (
        f"Module docstring in {_relative(init_file)} is too short "
        f"({len(docstring.strip())} chars). Expected >= 20."
    )


# ---------------------------------------------------------------------------
# Test directories (must exist, must NOT have __init__.py)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("td", TEST_DIRS)
def test_test_directory_exists(td: str) -> None:
    """Every expected test directory must exist."""
    path = ROOT / td
    assert path.is_dir(), f"Missing test directory: {_relative(path)}"


@pytest.mark.parametrize("td", TEST_DIRS)
def test_test_directory_no_init(td: str) -> None:
    """Test directories must NOT have __init__.py (pytest rootdir collection)."""
    init_file = ROOT / td / "__init__.py"
    assert not init_file.exists(), (
        f"Test directory {_relative(td)} should not have __init__.py"
    )


# ---------------------------------------------------------------------------
# Other directories
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("od", OTHER_DIRS)
def test_other_directory_exists(od: str) -> None:
    """Every expected non-package directory must exist."""
    path = ROOT / od
    assert path.is_dir(), f"Missing directory: {_relative(path)}"


# ---------------------------------------------------------------------------
# Special files / edge cases
# ---------------------------------------------------------------------------


def test_natives_spec_file_exists() -> None:
    """NATIVE.md must exist in src/tool_swap_runtime/backends/ as a file."""
    path = SRC_ROOT / "tool_swap_runtime/backends/NATIVE.md"
    assert path.is_file(), "Missing NATIVE.md in backends/"


def test_no_native_package_directory() -> None:
    """There must NOT be a native/ package directory in backends/."""
    path = SRC_ROOT / "tool_swap_runtime/backends/native"
    assert not path.exists(), (
        "native/ should not exist as a package directory in backends/"
    )

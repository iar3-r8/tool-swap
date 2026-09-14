"""Verify the repository layout matches plan/08_REPO_LAYOUT.md §1.

Checks that every expected directory exists, that ``src/`` packages contain
an ``__init__.py`` with a module docstring of at least ~20 characters, and
that special files (``NATIVE.md``) are present.

Tests are isolated — they discover the repo root from their own file location.
"""

import re
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
    "tests/unit/schema",
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
    "images",
    "images/base",
    "templates/cpu",
    "templates/cuda",
    "templates/tensorflow",
    "templates/function",
    "docs",
    "deploy",
    "deploy/prometheus",
    "deploy/grafana",
    "models",
    "tools",
    "tools/example_echo",
    "tools/example_add",
    "tools/example_build",
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


# ---------------------------------------------------------------------------
# M2a behaviour 1 — docker/ → images/ rename
# ---------------------------------------------------------------------------

# A ``docker/`` path reference in our own docs: a path separator directly
# after ``docker``, not preceded by a word character or a dot (so that
# ``docker run``, ``docker compose``, ``docker-compose`` and
# ``.docker/config.json`` do not match).
_STALE_DOCKER_PATH_RE = re.compile(r"(?<![\w.])docker/")

_DOC_FILES: list[str] = [
    "README.md",
    "plan/08_REPO_LAYOUT.md",
    "plan/07_CLI_AND_OPS.md",
]


def test_docker_directory_does_not_exist() -> None:
    """There must be no ``docker/`` directory at the repository root.

    A directory that was copied instead of moved would still shadow
    ``import docker`` as an implicit namespace package, so its absence is
    part of the layout contract (M2a behaviour 1).
    """
    path = ROOT / "docker"
    assert not path.exists(), (
        "docker/ must not exist at the repository root; it was renamed to "
        "images/ in M2a behaviour 1"
    )


def test_import_docker_not_a_namespace_package() -> None:
    """``import docker`` must never resolve to a repo-root namespace package.

    Because ``pyproject.toml`` puts the repository root on ``sys.path``, a
    directory named ``docker/`` at the root shadows the Docker SDK with an
    implicit namespace package: the import *succeeds* and yields a module
    with ``__file__ is None`` and ``__path__`` inside the repository. That
    silent failure mode is the defect this test stands guard against.

    Acceptable outcomes: ``ModuleNotFoundError`` (SDK not installed yet —
    correct before M2a behaviour 2), or a real module with a ``__file__``
    and a ``__version__`` (SDK installed).

    Note: intentionally NOT marked ``docker`` — it needs no daemon, and
    the marker would make pytest deselect it by default.
    """
    import sys

    # Purge stale ``docker`` entries so a namespace package imported by
    # another test cannot make this test pass spuriously.
    saved: dict[str, object] = {}
    for name in [
        m for m in sys.modules if m == "docker" or m.startswith("docker.")
    ]:
        saved[name] = sys.modules.pop(name)
    try:
        try:
            import docker  # noqa: F401
        except ModuleNotFoundError:
            return  # SDK not installed: expected outcome before M2a behaviour 2
        module = sys.modules["docker"]
        assert module.__file__ is not None, (
            "import docker resolved to a namespace package (no __file__); "
            "the repository root must not contain a docker/ directory"
        )
        assert hasattr(module, "__version__"), (
            "import docker resolved to a module without __version__; "
            "this is the namespace-package symptom, not the Docker SDK"
        )
        namespace_path = getattr(module, "__path__", None)
        if namespace_path is not None:
            for entry in namespace_path:
                assert not str(entry).startswith(str(ROOT)), (
                    f"import docker resolved with __path__ inside the "
                    f"repository: {entry}"
                )
    finally:
        for name in list(sys.modules):
            if name == "docker" or name.startswith("docker."):
                del sys.modules[name]
        sys.modules.update(saved)


def test_docs_have_no_stale_docker_dir_reference() -> None:
    """README.md and the layout/ops plan docs must not reference our ``docker/``.

    The repository's own ``docker/`` directory was renamed to ``images/``;
    ``README.md``, ``plan/08_REPO_LAYOUT.md`` and ``plan/07_CLI_AND_OPS.md``
    must not still point at the old path (e.g. ``docker/base``,
    ``docker/router.Dockerfile``). Legitimate mentions of Docker — the
    product name, ``docker run``, ``docker compose``, the SDK, or
    ``.docker/config.json``-style dot-prefixed paths — must not match.
    """
    stale: list[str] = []
    for rel in _DOC_FILES:
        path = ROOT / rel
        lines = path.read_text(encoding="utf-8").splitlines()
        for lineno, line in enumerate(lines, 1):
            if _STALE_DOCKER_PATH_RE.search(line):
                stale.append(f"{rel}:{lineno}: {line.strip()}")
    assert not stale, (
        "Stale references to the repository's own docker/ directory:\n"
        + "\n".join(stale)
    )

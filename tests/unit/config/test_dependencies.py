"""Tests for M1 behaviour 1 — dependencies are declared and importable.

See ``plans/m1-configuration.md`` §1, behaviour 1.

Verified behaviours:

- The four M1 runtime libraries (``pydantic``, ``yaml``, ``dotenv``,
  ``jsonschema``) import successfully in the venv built from
  ``pip install -e ".[dev]"``.
- ``pydantic`` is a v2 release (the whole M1 schema design assumes v2
  semantics; v1 would be a hard break).
- The root ``pyproject.toml`` declares all four in ``[project]
  dependencies`` and in the ``dev`` extra, plus ``types-PyYAML`` in the
  ``dev`` extra (the test extra must be self-sufficient, matching the
  ``typer`` precedent set in M0).
- ``src/tool_swap_runtime/pyproject.toml`` declares NONE of them — the
  runtime distribution stays dependency-light and the import-linter
  contracts keep the two packages apart.
- No ``try/except ImportError`` optional-degradation shims exist in
  ``src/``: a missing dependency must surface as an ordinary
  ``ModuleNotFoundError`` at import (the direct import tests above are
  the assertion for that — a shim would make them pass even when the
  library is genuinely missing).

Tests are isolated — they discover the repo root from their own file
location and use only stdlib (``tomllib``) to parse the manifests.
"""

import importlib
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # repo root
ROOT_PYPROJECT = ROOT / "pyproject.toml"
RUNTIME_PYPROJECT = ROOT / "src" / "tool_swap_runtime" / "pyproject.toml"

# The four M1 runtime dependencies (canonical PEP 508 names).
M1_RUNTIME_DEPS = ["pydantic", "pyyaml", "python-dotenv", "jsonschema"]

# Dev-only typing stubs: mypy strict cannot type ``yaml`` without this.
DEV_ONLY_STUBS = ["types-PyYAML"]

# Import names differ from distribution names for two of the libraries.
IMPORT_NAMES = {
    "pydantic": "pydantic",
    "pyyaml": "yaml",
    "python-dotenv": "dotenv",
    "jsonschema": "jsonschema",
}

# A requirement line starts with its project name:
# letters/digits, then any of ``.``, ``_``, ``-``.
_REQ_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")

# Optional-degradation shims: catching ImportError/ModuleNotFoundError so a
# missing library degrades silently instead of failing at import.
_SHIM_PATTERNS = (
    re.compile(r"except\s+ImportError"),
    re.compile(r"except\s+ModuleNotFoundError"),
)


def _requirement_name(requirement: str) -> str:
    """Return the PEP 503-normalised name of a PEP 508 requirement string.

    Normalisation (case-insensitive, ``_``/``.`` treated as ``-``) so that
    ``PyYAML`` and ``pyyaml`` compare equal, as in ``pip``.
    """
    match = _REQ_NAME_RE.match(requirement.strip())
    if match is None:
        raise ValueError(f"Not a valid PEP 508 requirement: {requirement!r}")
    return match.group(1).lower().replace("_", "-").replace(".", "-")


def _load_pyproject(path: Path) -> dict:
    """Parse a ``pyproject.toml`` file into its top-level table dict."""
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _declared_names(project_table: dict, section: str) -> set[str]:
    """Return the set of normalised names declared in a dependency list.

    *section* is ``"dependencies"`` or an extra name under
    ``optional-dependencies``.
    """
    if section == "dependencies":
        requirements = project_table.get("dependencies", [])
    else:
        requirements = project_table.get("optional-dependencies", {}).get(
            section, []
        )
    return {_requirement_name(req) for req in requirements}


# ---------------------------------------------------------------------------
# 1. The libraries import successfully (no try/except ImportError shims)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dep", sorted(IMPORT_NAMES))
def test_m1_library_imports_successfully(dep: str) -> None:
    """Each M1 dependency imports in the venv without error.

    A ``try/except ImportError`` shim in ``src/`` would mask a missing
    library here, so this also pins the "plain ModuleNotFoundError" error
    behaviour required by behaviour 1.
    """
    # Arrange: nothing — the venv is the fixture (pip install -e ".[dev]").
    # Act:
    module = importlib.import_module(IMPORT_NAMES[dep])
    # Assert:
    assert module is not None, f"{IMPORT_NAMES[dep]} imported to None"


def test_pydantic_is_v2_series() -> None:
    """``pydantic.VERSION`` must be a 2.x release.

    The M1 schema design (behaviour 4 onward) relies on v2 semantics
    (``model_config``, ``ValidationError`` shape, ``.model_dump()``); a
    v1 install would silently pass imports but break the design.
    """
    # Act:
    import pydantic

    version = pydantic.VERSION
    # Assert:
    assert version.startswith("2"), (
        f"pydantic {version} is not a 2.x release; M1 requires "
        "pydantic>=2.7 (v2 semantics)."
    )


# ---------------------------------------------------------------------------
# 2. Root pyproject.toml declares the dependencies
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dep", M1_RUNTIME_DEPS)
def test_root_pyproject_declares_dependency_in_project_dependencies(
    dep: str,
) -> None:
    """``[project] dependencies`` declares every M1 runtime dependency."""
    # Arrange:
    table = _load_pyproject(ROOT_PYPROJECT)
    declared = _declared_names(table["project"], "dependencies")
    # Act / Assert:
    assert _requirement_name(dep) in declared, (
        f"{dep} is not declared in [project] dependencies of "
        f"{ROOT_PYPROJECT.name}; declared: {sorted(declared)}"
    )


@pytest.mark.parametrize("dep", M1_RUNTIME_DEPS)
def test_root_pyproject_declares_dependency_in_dev_extra(dep: str) -> None:
    """The ``dev`` extra is self-sufficient: it re-declares all four.

    Matches the ``typer`` precedent set in M0, where the dev extra
    carries the runtime dependency so a bare dev install works.
    """
    # Arrange:
    table = _load_pyproject(ROOT_PYPROJECT)
    declared = _declared_names(table["project"], "dev")
    # Act / Assert:
    assert _requirement_name(dep) in declared, (
        f"{dep} is not declared in the 'dev' extra of "
        f"{ROOT_PYPROJECT.name}; declared: {sorted(declared)}"
    )


@pytest.mark.parametrize("stub", DEV_ONLY_STUBS)
def test_root_pyproject_declares_dev_stub_in_dev_extra(stub: str) -> None:
    """``types-PyYAML`` is in the ``dev`` extra (dev-only, not runtime)."""
    # Arrange:
    table = _load_pyproject(ROOT_PYPROJECT)
    declared_dev = _declared_names(table["project"], "dev")
    declared_runtime = _declared_names(table["project"], "dependencies")
    # Act / Assert:
    assert _requirement_name(stub) in declared_dev, (
        f"{stub} is missing from the 'dev' extra; mypy strict cannot "
        f"type 'yaml' without it. declared: {sorted(declared_dev)}"
    )
    assert _requirement_name(stub) not in declared_runtime, (
        f"{stub} must not be a runtime dependency, only a dev one."
    )


# ---------------------------------------------------------------------------
# 3. The runtime distribution stays dependency-light
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dep", M1_RUNTIME_DEPS)
def test_runtime_pyproject_declares_no_m1_dependencies(dep: str) -> None:
    """The runtime distribution declares none of the M1 dependencies.

    The import-linter contracts keep ``tool_swap`` and
    ``tool_swap_runtime`` apart; this milestone must not weaken that by
    pulling router-side libraries into the runtime image.
    """
    # Arrange:
    table = _load_pyproject(RUNTIME_PYPROJECT)
    declared_runtime = _declared_names(table["project"], "dependencies")
    declared_extras = set()
    for extra in table["project"].get("optional-dependencies", {}):
        declared_extras |= _declared_names(table["project"], extra)
    # Act / Assert:
    assert _requirement_name(dep) not in declared_runtime, (
        f"{dep} must not be a dependency of tool-swap-runtime; "
        f"declared: {sorted(declared_runtime)}"
    )
    assert _requirement_name(dep) not in declared_extras, (
        f"{dep} must not appear in any extra of tool-swap-runtime; "
        f"declared: {sorted(declared_extras)}"
    )


@pytest.mark.parametrize("stub", DEV_ONLY_STUBS)
def test_runtime_pyproject_declares_no_dev_stubs(stub: str) -> None:
    """The runtime distribution declares none of the dev-only stubs either."""
    # Arrange:
    table = _load_pyproject(RUNTIME_PYPROJECT)
    declared = _declared_names(table["project"], "dependencies")
    for extra in table["project"].get("optional-dependencies", {}):
        declared |= _declared_names(table["project"], extra)
    # Act / Assert:
    assert _requirement_name(stub) not in declared, (
        f"{stub} must not appear in tool-swap-runtime; "
        f"declared: {sorted(declared)}"
    )


# ---------------------------------------------------------------------------
# 4. No optional-degradation shims for these libraries in src/
# ---------------------------------------------------------------------------


def test_no_import_error_shims_in_src() -> None:
    """``src/`` contains no ``except ImportError`` / ``ModuleNotFoundError``.

    Behaviour 1's error behaviour: a missing dependency surfaces as an
    ordinary ``ModuleNotFoundError`` at import. A catch-and-degrade shim
    for pydantic/yaml/dotenv/jsonschema would silently produce a half
    working install, so the pattern is banned repo-wide in ``src/``.
    """
    # Arrange / Act: collect offending lines.
    offenders: list[str] = []
    for py_file in sorted((ROOT / "src").rglob("*.py")):
        text = py_file.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if any(p.search(line) for p in _SHIM_PATTERNS):
                relative = py_file.relative_to(ROOT)
                offenders.append(f"{relative}:{line_no}: {line.strip()}")
    # Assert:
    assert not offenders, (
        "Optional-degradation shims found (M1 behaviour 1 forbids "
        "catching ImportError for its dependencies):\n" + "\n".join(offenders)
    )

"""Verify the M1 import boundary contracts on top of M0's (behaviour 26).

Tests for behaviour 26 from ``plans/m1-configuration.md`` — the two new
``forbidden`` contracts that must land in ``.importlinter`` alongside M0's
existing pair:

- contract 3: ``The config layer is a leaf`` — ``tool_swap.config`` and
  ``tool_swap.schema`` must not import ``tool_swap.cli``,
  ``tool_swap.lifecycle``, ``tool_swap.backend`` or ``tool_swap.proxy``.
- contract 4: ``The schema compiler does not depend on the pydantic config
  models`` — ``tool_swap.schema`` must not import
  ``tool_swap.config.schema`` (but may import ``tool_swap.config.errors``).

M0's file, ``tests/unit/test_imports.py``, keeps behaviour-7 ownership; this
file imports nothing from it and copies the one helper it needs.

Tests follow AAA structure (Arrange, Act, Assert) and are isolated — they
discover the repo root from their own file location.
"""

from __future__ import annotations

import configparser
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]  # repo root
SRC_ROOT = ROOT / "src"
IMPORTLINTER_CONFIG = ROOT / ".importlinter"

# The four contract names that ``.importlinter`` must carry exactly — M0's
# two (quoted verbatim from the shipped file) plus behaviour 26's two
# (plans/m1-configuration.md, item 3, verbatim).
_EXPECTED_CONTRACTS = frozenset(
    {
        "Router and runtime are strictly separate",
        "Router and runtime are strictly separate (reverse)",
        "The config layer is a leaf",
        "The schema compiler does not depend on the pydantic config models",
    }
)

_CONFIG_LAYER_CONTRACT = "The config layer is a leaf"
_SCHEMA_COMPILER_CONTRACT = (
    "The schema compiler does not depend on the pydantic config models"
)


def _lint_imports_bin() -> list[str]:
    """Return the command to run lint-imports.

    Returns a list suitable for subprocess.run().

    Tries the venv path first (local development), then falls back to
    finding the executable on PATH (GitHub Actions CI where pip installs
    to the system Python location). If neither works, uses
    ``python -c`` to invoke the CLI directly.

    Copied from ``tests/unit/test_imports.py`` (the plan's item 5 pins the
    copy, not an import). This copy includes the ``import sys`` the
    fallback branch needs and the M0 file lacks.
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


def _parse_importlinter() -> configparser.ConfigParser:
    """Parse ``.importlinter`` into a ConfigParser.

    The file is INI-shaped: an ``[importlinter]`` section plus one
    ``[importlinter:contract:N]`` section per contract, with multi-line
    values on four-space indented continuation lines (handled natively by
    configparser).
    """
    parser = configparser.ConfigParser()
    parser.read_string(IMPORTLINTER_CONFIG.read_text())
    return parser


def _contract_sections(parser: configparser.ConfigParser) -> list[str]:
    """Return the names of every ``[importlinter:contract:N]`` section."""
    return [s for s in parser.sections() if s.startswith("importlinter:contract")]


def _contract_names(parser: configparser.ConfigParser) -> dict[str, str]:
    """Return a mapping of contract section name -> its ``name`` value."""
    return {s: parser.get(s, "name") for s in _contract_sections(parser)}


def _section_for_name(
    parser: configparser.ConfigParser, contract_name: str
) -> configparser.SectionProxy:
    """Return the contract section whose ``name`` is ``contract_name``.

    Fails with a readable message listing the sections that DO exist when
    the wanted name is absent, so a red run is informative rather than a
    bare ``NoSectionError``.
    """
    for section in _contract_sections(parser):
        if parser.get(section, "name") == contract_name:
            return parser[section]
    existing = [f"{s} ({parser.get(s, 'name')!r})" for s in _contract_sections(parser)]
    pytest.fail(
        f"No contract section named {contract_name!r} in .importlinter. "
        f"Contract sections present: {existing}"
    )


def _module_set(section: configparser.SectionProxy, option: str) -> set[str]:
    """Return the set of stripped, non-empty lines of a multi-line value."""
    return {line.strip() for line in section[option].splitlines() if line.strip()}


def test_the_expected_contract_names_are_exactly_the_shipped_ones() -> None:
    """The contract names in .importlinter are exactly the four pinned ones.

    Arrange: parse the shipped ``.importlinter``.
    Act: collect the ``name`` value of every contract section.
    Assert: the SET of names equals the four-name literal — M0's two plus
    behaviour 26's two. Prints missing and unexpected names separately.
    """
    parser = _parse_importlinter()
    shipped = set(_contract_names(parser).values())
    missing = _EXPECTED_CONTRACTS - shipped
    unexpected = shipped - _EXPECTED_CONTRACTS
    assert not missing and not unexpected, (
        f".importlinter contract names do not equal the expected four.\n"
        f"Missing: {sorted(missing)}\n"
        f"Unexpected: {sorted(unexpected)}\n"
        f"Shipped: {sorted(shipped)}"
    )


def test_the_config_layer_contract_forbids_all_four_downstream_packages() -> None:
    """Contract 3 pins the config layer's source and forbidden sets exactly.

    Arrange: parse ``.importlinter`` and locate the section named
    ``The config layer is a leaf``.
    Act: read its ``type``, ``source_modules`` and ``forbidden_modules``.
    Assert: type is ``forbidden``; source is exactly
    ``{tool_swap.config, tool_swap.schema}``; forbidden is exactly the four
    downstream packages.
    """
    parser = _parse_importlinter()
    section = _section_for_name(parser, _CONFIG_LAYER_CONTRACT)
    assert section["type"] == "forbidden", (
        f"Contract {_CONFIG_LAYER_CONTRACT!r} must be of type 'forbidden', "
        f"got {section['type']!r}"
    )
    source = _module_set(section, "source_modules")
    forbidden = _module_set(section, "forbidden_modules")
    assert source == {"tool_swap.config", "tool_swap.schema"}, (
        f"Contract {_CONFIG_LAYER_CONTRACT!r} source_modules mismatch: {source}"
    )
    assert forbidden == {
        "tool_swap.cli",
        "tool_swap.lifecycle",
        "tool_swap.backend",
        "tool_swap.proxy",
    }, f"Contract {_CONFIG_LAYER_CONTRACT!r} forbidden_modules mismatch: {forbidden}"


def test_the_schema_compiler_contract_forbids_the_pydantic_models() -> None:
    """Contract 4 forbids ``config.schema`` to the compiler — and only that.

    Arrange: parse ``.importlinter`` and locate the section named
    ``The schema compiler does not depend on the pydantic config models``.
    Act: read its ``type``, ``source_modules`` and ``forbidden_modules``;
    also collect the forbidden set of EVERY contract.
    Assert: source is exactly ``{tool_swap.schema}``, forbidden is exactly
    ``{tool_swap.config.schema}``, and ``tool_swap.config.errors`` is absent
    from every contract's forbidden set (the line-4015 permission, asserted
    as an absence).
    """
    parser = _parse_importlinter()
    section = _section_for_name(parser, _SCHEMA_COMPILER_CONTRACT)
    assert section["type"] == "forbidden", (
        f"Contract {_SCHEMA_COMPILER_CONTRACT!r} must be of type 'forbidden', "
        f"got {section['type']!r}"
    )
    source = _module_set(section, "source_modules")
    forbidden = _module_set(section, "forbidden_modules")
    assert source == {"tool_swap.schema"}, (
        f"Contract {_SCHEMA_COMPILER_CONTRACT!r} source_modules mismatch: {source}"
    )
    assert forbidden == {"tool_swap.config.schema"}, (
        f"Contract {_SCHEMA_COMPILER_CONTRACT!r} forbidden_modules mismatch: "
        f"{forbidden}"
    )
    for s in _contract_sections(parser):
        every_forbidden = _module_set(parser[s], "forbidden_modules")
        assert "tool_swap.config.errors" not in every_forbidden, (
            f"Section {s} forbids tool_swap.config.errors, but the schema "
            f"compiler must remain free to import config.errors"
        )


def test_lint_imports_reports_every_contract_kept() -> None:
    """lint-imports keeps all four contracts and reports ``4 kept``.

    Arrange: locate the lint-imports binary (the M0 helper idiom).
    Act: run ``lint-imports --config .importlinter`` with ``PYTHONPATH=src``
    in the repo root.
    Assert: exit 0, each of the four contract names appears in the output,
    and the tool's own summary line reads ``4 kept, 0 broken`` — so a
    silently-dropped contract fails here even if the name check were
    relaxed.
    """
    env = {**os.environ, "PYTHONPATH": str(SRC_ROOT)}
    result = subprocess.run(
        _lint_imports_bin() + ["--config", str(IMPORTLINTER_CONFIG)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"lint-imports failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    for name in sorted(_EXPECTED_CONTRACTS):
        assert name in combined, (
            f"Contract {name!r} is not named in the lint-imports output.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    assert "4 kept, 0 broken" in combined, (
        f"Expected the summary line to read '4 kept, 0 broken'.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_the_cli_actually_imports_the_config_layer() -> None:
    """Importing the CLI pulls in the config layer — the edge is live.

    The permitted ``cli`` -> ``config``/``schema`` direction is exercised by
    shipped code, not merely unforbidden:

    - ``tool_swap.cli._pipeline`` imports ``tool_swap.config.loader`` and
      ``tool_swap.config.schema`` (``src/tool_swap/cli/_pipeline.py:25-27``).
    - ``tool_swap.cli.validate`` imports ``tool_swap.schema.compile``
      (``src/tool_swap/cli/validate.py:43``).

    Arrange: a fresh interpreter (subprocess) so the in-process test's
    already-imported modules cannot fake the result.
    Act: import the two CLI modules there and inspect ``sys.modules``.
    Assert: the three config-layer modules above are present.
    """
    probe = (
        "import sys\n"
        "import tool_swap.cli._pipeline\n"
        "import tool_swap.cli.validate\n"
        "mods = sys.modules\n"
        "assert 'tool_swap.config.loader' in mods, mods.keys()\n"
        "assert 'tool_swap.config.schema' in mods, mods.keys()\n"
        "assert 'tool_swap.schema.compile' in mods, mods.keys()\n"
    )
    env = {**os.environ, "PYTHONPATH": str(SRC_ROOT)}
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Importing tool_swap.cli._pipeline and tool_swap.cli.validate did "
        f"not pull the config layer into sys.modules.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

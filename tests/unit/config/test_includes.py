r"""Tests for M1 behaviour 8 — ``path:`` inclusion of ``tool.yaml``.

See ``plans/m1-configuration.md`` §1, behaviour 8 (lines 149-166).

This file is the RED step: the ``load_config`` loader
(``src/tool_swap/config/loader.py``) does not process ``path:`` yet, so
every test below fails for a *right* red reason:

- accessor tests fail with ``AttributeError`` (no ``tool_yaml`` method
  on ``LoadedConfig`` yet);
- C005 / C006 / C007 / C201 tests fail with ``DID NOT RAISE`` (no
  include handling, so no ``ConfigError`` is produced);
- the C202 test fails its assertion (no warning diagnostic is
  recorded);
- nothing fails collection (``load_config`` and ``LoadedConfig``
  already import cleanly).

Pinned public API (the contract the GREEN step must meet verbatim):

- ``load_config`` keeps its exact signature
  (``load_config(path, *, env=None, env_file=None) -> LoadedConfig``)
  and remains backward-compatible: a ``tools.<name>:`` entry whose
  ``path:`` resolves to a directory that does NOT exist at all loads
  cleanly with NO diagnostic and no layer (this is what keeps the
  behaviour 6-7 fixtures — minimal configs whose ``path:`` points at a
  non-existent directory — passing unchanged).  ``TSWAP-C005`` fires
  only when the directory EXISTS but holds no ``tool.yaml``.
- NEW on ``LoadedConfig``::

      def tool_yaml(self, name: str) -> tuple[Path, dict[str, Any]] | None

  - Returns ``(resolved_tool_yaml_path, tool_yaml_mapping)`` for a
    tool named ``name`` whose ``path:`` was processed: the first
    element is the RESOLVED ABSOLUTE path of the included
    ``<dir>/tool.yaml`` (its ``.parent`` is the directory that the
    resolver, behaviour 10, must use to resolve relative paths inside
    ``tool.yaml`` such as ``handler: handler.py:Cls`` and
    ``runtime.requirements: requirements.txt``); the second is the
    parsed ``tool.yaml`` mapping, as-is.
  - Returns ``None`` when the tool has no ``path:`` key, when the
    resolved directory does not exist (backward-compat skip), or when
    ``name`` is not a key of ``tools:``.
  - ``data`` is NOT polluted: for an included tool,
    ``data["tools"][name]`` stays exactly the inline entry as written
    (the resolver is built against this accessor, not against a
    reserved key in ``data``).
- ``path:`` resolution rules (all relative to the ROOT CONFIG FILE'S
  directory, never the CWD):
  - relative ``path:`` resolves against ``path.parent`` of the config
    file passed to ``load_config``;
  - ``~`` expands (``expanduser``);
  - absolute ``path:`` is honoured as-is.
- Diagnostic codes and pinned message/remedy substrings (loader-owned
  include block; all location files are resolved absolute paths):
  - ``TSWAP-C005`` (ERROR) — the resolved ``path:`` directory exists
    but has no ``tool.yaml``; message names the resolved directory
    and the expected filename ``tool.yaml``;
    ``location.file == str(resolved_dir)``.
  - ``TSWAP-C006`` (ERROR) — the resolved ``path:`` is a file, not a
    directory; message names the resolved file path; remedy names the
    directory form (contains ``directory`` and ``tool.yaml``);
    ``location.file == str(resolved_file)``.
  - ``TSWAP-C007`` (ERROR) — the included ``tool.yaml`` itself
    contains a ``path:`` key (no include recursion, one level only);
    message contains ``path``; ``location.file == str(resolved
    tool.yaml)``.
  - ``TSWAP-C201`` (ERROR) — ``name:`` inside ``tool.yaml`` differs
    from the ``tools:`` map key; message names BOTH the map key and
    the ``name:`` value; ``location.file == str(resolved tool.yaml)``.
    A ``tool.yaml`` with NO ``name:`` key is not a C201 at the loader
    level (required-ness is a later behaviour's concern) — that is
    what lets two entries legally share one unnamed ``tool.yaml``.
  - ``TSWAP-C202`` (WARNING, load is NOT fatal) — two ``tools:``
    entries use the same ``path:``; exactly one WARNING diagnostic in
    ``LoadedConfig.diagnostics``; message names BOTH tool keys;
    remedy names the legitimate ``params:``-only-differs case
    (contains ``params``).
- The loader does NOT schema-validate ``tool.yaml`` content (the
  root data is equally not schema-validated by the loader — that is
  behaviour 4's ``validate_root`` layer).  The contract records the
  tool.yaml's resolved path in the accessor's first element so the
  validator layer can locate its diagnostics in THAT file, not in
  ``tools.yaml``.

Conventions: pytest, AAA pattern, snake_case, Google-style
docstrings, ``tmp_path`` for every file, no ``warnings.warn``
(pyproject sets ``filterwarnings = "error"``).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from tool_swap.config.errors import ConfigError, Diagnostic, Severity
from tool_swap.config.loader import LoadedConfig, load_config

# Pinned diagnostic codes for behaviour 8 (see module docstring).
_CODE_MISSING_TOOL_YAML = "TSWAP-C005"
_CODE_PATH_IS_FILE = "TSWAP-C006"
_CODE_RECURSION = "TSWAP-C007"
_CODE_NAME_MISMATCH = "TSWAP-C201"
_CODE_SHARED_PATH = "TSWAP-C202"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(directory: Path, name: str, text: str) -> Path:
    """Write ``text`` (UTF-8) to ``directory/name`` and return the path."""
    p = directory / name
    p.write_text(text, encoding="utf-8")
    return p


def _tool_yaml_text(name: str | None = "t") -> str:
    """Return a minimal, schema-valid ``tool.yaml`` body for tool ``name``.

    When ``name`` is ``None`` the ``name:`` line is omitted entirely —
    that is the form a tool.yaml shared by several ``tools:`` entries
    takes (a missing ``name:`` is not a loader-level error; see the
    C201 note in the module docstring).
    """
    lines = []
    if name is not None:
        lines.append(f"name: {name}\n")
    lines.append("description: demo tool\n")
    lines.append("handler: handler.py:Handler\n")
    return "".join(lines)


def _build_tool_dir(tool_dir: Path, name: str | None = "t") -> None:
    """Create ``tool_dir`` with ``tool.yaml``, ``handler.py``,
    ``requirements.txt`` (plan line 151's tree)."""
    tool_dir.mkdir(parents=True)
    _write(tool_dir, "tool.yaml", _tool_yaml_text(name))
    _write(tool_dir, "handler.py", "")
    _write(tool_dir, "requirements.txt", "")


def _build_tree(
    tmp_path: Path,
    name: str = "t",
    tool_yaml: str | None = None,
    config: str | None = None,
) -> Path:
    """Build the behaviour 8 tree and return the config file's path.

    Default tree::

        tools.yaml            tools: <name>: path: ./tools/<name>
        tools/<name>/tool.yaml   name: <name> + handler
        tools/<name>/handler.py
        tools/<name>/requirements.txt

    Args:
        tmp_path: Root of the scratch tree.
        name: Tool name (``tools:`` key and ``name:`` agree).
        tool_yaml: Override the ``tool.yaml`` body (without trailing
            newline management — written verbatim).
        config: Override the whole ``tools.yaml`` body.
    """
    tool_dir = tmp_path / "tools" / name
    _build_tool_dir(tool_dir, name)
    if tool_yaml is not None:
        _write(tool_dir, "tool.yaml", tool_yaml)
    text = config if config is not None else (
        f"tools:\n  {name}:\n    path: ./tools/{name}\n"
    )
    return _write(tmp_path, "tools.yaml", text)


def _error_for(exc: ConfigError, code: str) -> Diagnostic:
    """Return the single ERROR diagnostic with ``code`` in the report.

    Fails loudly when a different number of diagnostics with that
    code is present, so the GREEN step cannot hide a problem among
    extras.
    """
    matches = [
        d
        for d in exc.report.errors
        if d.code == code and d.severity is Severity.ERROR
    ]
    assert len(matches) == 1, (
        f"expected exactly one {code} error diagnostic, "
        f"got: {exc.report.diagnostics!r}"
    )
    return matches[0]


def _warning_for(result: LoadedConfig, code: str) -> Diagnostic:
    """Return the single WARNING diagnostic with ``code`` in ``result``."""
    matches = [
        d
        for d in result.diagnostics
        if d.code == code and d.severity is Severity.WARNING
    ]
    assert len(matches) == 1, (
        f"expected exactly one {code} warning diagnostic, "
        f"got: {result.diagnostics!r}"
    )
    return matches[0]


def _layer(result: LoadedConfig, name: str) -> tuple[Path, dict[str, Any]]:
    """Assert ``result.tool_yaml(name)`` is present and return it."""
    layer = result.tool_yaml(name)
    assert layer is not None, f"expected a tool.yaml layer for {name!r}"
    return layer


# ---------------------------------------------------------------------------
# Golden path: basic include (plan line 151)
# ---------------------------------------------------------------------------


def test_include_basic_tool_yaml_exposed_as_layer(tmp_path: Path) -> None:
    """Plan line 151: a ``path:`` entry loads; the tool.yaml content is
    available via the pinned accessor; no errors; ``data`` stays clean.
    """
    # Arrange: the behaviour 8 tree.
    config = _build_tree(tmp_path)

    # Act.
    result = load_config(config)

    # Assert: clean load, layer present with the pinned tuple shape.
    assert result.diagnostics == []
    tool_yaml_path, mapping = _layer(result, "t")
    assert tool_yaml_path == (tmp_path / "tools" / "t" / "tool.yaml").resolve()
    assert mapping == {
        "name": "t",
        "description": "demo tool",
        "handler": "handler.py:Handler",
    }
    # ``data`` is NOT polluted by the include (pinned contract):
    assert result.data == {"tools": {"t": {"path": "./tools/t"}}}


def test_include_cwd_independent_data_and_layer_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan line 155: identical results from any CWD.

    The same tree loaded from two different working directories yields
    byte-identical ``data`` and an identical tool.yaml layer (the
    resolved path is anchored to the config file's directory, so it is
    CWD-independent).
    """
    # Arrange: one tree, two working directories.
    config = _build_tree(tmp_path)

    # Act: load from the tree's dir, then from its parent.
    monkeypatch.chdir(tmp_path)
    first = load_config(config)
    monkeypatch.chdir(tmp_path.parent)
    second = load_config(config)

    # Assert: identical data and identical layer (absolute, anchored).
    assert first.data == second.data
    assert first.tool_yaml("t") == second.tool_yaml("t")
    assert first.tool_yaml("t") is not None


def test_include_tool_dir_exposed_for_relative_path_resolution(
    tmp_path: Path,
) -> None:
    """Plan line 154: relative paths INSIDE tool.yaml resolve against
    the tool.yaml's own directory.

    Pinned contract: the accessor's first element is the resolved
    tool.yaml path, so the resolver (behaviour 10) resolves
    ``handler: handler.py:Handler`` and ``requirements.txt`` against
    ``tool_yaml_path.parent`` — not the CWD, not the config's dir.
    """
    # Arrange.
    config = _build_tree(tmp_path)

    # Act.
    result = load_config(config)

    # Assert: the exposed directory is the tool.yaml's own directory.
    tool_yaml_path, _mapping = _layer(result, "t")
    assert tool_yaml_path.parent == (tmp_path / "tools" / "t").resolve()


def test_include_tilde_in_path_expands_to_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan line 156: ``~`` in ``path:`` expands (to HOME).

    HOME is redirected to a scratch directory so the test never
    touches the real $HOME.
    """
    # Arrange: a fake home holding the tool dir; HOME points at it.
    fake_home = tmp_path / "home"
    _build_tool_dir(fake_home / "tools" / "t", "t")
    monkeypatch.setenv("HOME", str(fake_home))
    config = _write(tmp_path, "tools.yaml", "tools:\n  t:\n    path: ~/tools/t\n")

    # Act.
    result = load_config(config)

    # Assert: the layer resolves through the expanded home.
    tool_yaml_path, _mapping = _layer(result, "t")
    assert tool_yaml_path == (fake_home / "tools" / "t" / "tool.yaml").resolve()


def test_include_absolute_path_honoured(tmp_path: Path) -> None:
    """Plan line 156: an absolute ``path:`` is honoured as-is, even when
    it points outside the config file's directory.
    """
    # Arrange: the tool tree lives under a sibling of the config dir.
    site = tmp_path / "site"
    site.mkdir()
    warehouse_tool = tmp_path / "warehouse" / "tools" / "t"
    _build_tool_dir(warehouse_tool, "t")
    config = _write(
        site,
        "tools.yaml",
        f"tools:\n  t:\n    path: {warehouse_tool}\n",
    )

    # Act.
    result = load_config(config)

    # Assert: the layer comes from the absolute location.
    tool_yaml_path, _mapping = _layer(result, "t")
    assert tool_yaml_path == (warehouse_tool / "tool.yaml").resolve()


# ---------------------------------------------------------------------------
# name: mismatch (plan line 157)
# ---------------------------------------------------------------------------


def test_include_name_mismatch_raises_c201_naming_both(
    tmp_path: Path,
) -> None:
    """Plan line 157: ``name:`` != ``tools:`` key -> ``TSWAP-C201``
    naming BOTH, located in the tool.yaml file.
    """
    # Arrange: the map key is ``echo_tool``, tool.yaml says otherwise.
    config = _build_tree(
        tmp_path,
        name="echo_tool",
        tool_yaml="name: different\nhandler: handler.py:Handler\n",
    )

    # Act.
    with pytest.raises(ConfigError) as exc_info:
        load_config(config)

    # Assert: one C201 naming both names, located in the tool.yaml.
    diag = _error_for(exc_info.value, _CODE_NAME_MISMATCH)
    assert "echo_tool" in diag.message
    assert "different" in diag.message
    assert diag.location.file == str(
        (tmp_path / "tools" / "echo_tool" / "tool.yaml").resolve()
    )
    assert diag.remedy.strip()


# ---------------------------------------------------------------------------
# path: target problems (plan lines 159-160)
# ---------------------------------------------------------------------------


def test_include_dir_without_tool_yaml_raises_c005(tmp_path: Path) -> None:
    """Plan line 159: a ``path:`` directory with no ``tool.yaml`` ->
    ``TSWAP-C005`` naming the directory and the expected filename.
    """
    # Arrange: the directory exists but is empty.
    tool_dir = tmp_path / "tools" / "empty"
    tool_dir.mkdir(parents=True)
    config = _write(
        tmp_path, "tools.yaml", "tools:\n  t:\n    path: ./tools/empty\n"
    )

    # Act.
    with pytest.raises(ConfigError) as exc_info:
        load_config(config)

    # Assert: one C005 naming the dir and tool.yaml, located at the dir.
    diag = _error_for(exc_info.value, _CODE_MISSING_TOOL_YAML)
    assert str(tool_dir.resolve()) in diag.message
    assert "tool.yaml" in diag.message
    assert diag.location.file == str(tool_dir.resolve())
    assert diag.remedy.strip()


def test_include_path_points_at_file_raises_c006(tmp_path: Path) -> None:
    """Plan line 160: a ``path:`` pointing at a FILE -> ``TSWAP-C006``,
    remedy naming the directory form.
    """
    # Arrange: ``tools/t`` is a regular file, not a directory.
    target = tmp_path / "tools" / "t"
    target.parent.mkdir(parents=True)
    target.write_text("definitely not a directory\n", encoding="utf-8")
    config = _write(tmp_path, "tools.yaml", "tools:\n  t:\n    path: ./tools/t\n")

    # Act.
    with pytest.raises(ConfigError) as exc_info:
        load_config(config)

    # Assert: one C006 naming the file; remedy names the directory form.
    diag = _error_for(exc_info.value, _CODE_PATH_IS_FILE)
    assert str(target.resolve()) in diag.message
    assert "directory" in diag.remedy
    assert "tool.yaml" in diag.remedy
    assert diag.location.file == str(target.resolve())


# ---------------------------------------------------------------------------
# path: combined with inline keys (plan line 161)
# ---------------------------------------------------------------------------


def test_include_path_and_inline_handler_loads_clean(tmp_path: Path) -> None:
    """Plan line 161: ``path:`` AND an inline ``handler:`` in the same
    entry is legal — the loader must not error (inline wins later, in
    behaviour 10's resolver; the loader only supplies the layer).
    """
    # Arrange: the entry carries both a path and an inline handler.
    config = _build_tree(
        tmp_path,
        config="tools:\n  t:\n    path: ./tools/t\n    handler: inline.py:Inline\n",
    )

    # Act (must not raise).
    result = load_config(config)

    # Assert: clean load; inline key preserved; layer still exposed.
    assert result.diagnostics == []
    assert result.data == {
        "tools": {"t": {"path": "./tools/t", "handler": "inline.py:Inline"}}
    }
    _tool_yaml_path, mapping = _layer(result, "t")
    assert mapping["handler"] == "handler.py:Handler"


# ---------------------------------------------------------------------------
# shared path: warning, not error (plan line 162)
# ---------------------------------------------------------------------------


def test_include_shared_path_warns_c202_not_error(tmp_path: Path) -> None:
    """Plan line 162: two ``tools:`` entries with the SAME ``path:`` ->
    ``TSWAP-C202`` WARNING; the load succeeds and is not fatal.

    The shared ``tool.yaml`` deliberately omits ``name:`` (a single
    name cannot equal two keys; a missing ``name:`` is not a
    loader-level error), so C201 does not confound this test.
    """
    # Arrange: t1 and t2 point at the same directory.
    config = _build_tree(
        tmp_path,
        name="shared",
        tool_yaml=_tool_yaml_text(name=None),
        config="tools:\n  t1:\n    path: ./tools/shared\n  t2:\n    path: ./tools/shared\n",
    )

    # Act (must NOT raise).
    result = load_config(config)

    # Assert: exactly one C202 WARNING naming both keys; no ERROR.
    diag = _warning_for(result, _CODE_SHARED_PATH)
    assert "t1" in diag.message
    assert "t2" in diag.message
    assert "params" in diag.remedy
    assert result.diagnostics == [diag]
    assert not [d for d in result.diagnostics if d.severity is Severity.ERROR]
    # Both entries still expose the shared layer.
    assert _layer(result, "t1")[0] == _layer(result, "t2")[0]


# ---------------------------------------------------------------------------
# no include recursion (plan line 163)
# ---------------------------------------------------------------------------


def test_include_recursion_in_tool_yaml_raises_c007(tmp_path: Path) -> None:
    """Plan line 163: a ``tool.yaml`` that itself contains ``path:`` ->
    ``TSWAP-C007`` (one level only, located in the tool.yaml).
    """
    # Arrange: the included tool.yaml tries to include further.
    config = _build_tree(
        tmp_path,
        tool_yaml="name: t\npath: ./nested\nhandler: handler.py:Handler\n",
    )

    # Act.
    with pytest.raises(ConfigError) as exc_info:
        load_config(config)

    # Assert: one C007, located in the tool.yaml, naming the key.
    diag = _error_for(exc_info.value, _CODE_RECURSION)
    assert "path" in diag.message
    assert diag.location.file == str(
        (tmp_path / "tools" / "t" / "tool.yaml").resolve()
    )
    assert diag.remedy.strip()


# ---------------------------------------------------------------------------
# symlinked tool directory (plan line 164)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unsupported")
def test_include_symlinked_tool_dir_resolves(tmp_path: Path) -> None:
    """Plan line 164: a symlinked tool directory resolves through the
    symlink without error.
    """
    # Arrange: the real tree under ``real_t``; ``tools/t`` is a symlink.
    real_dir = tmp_path / "tools" / "real_t"
    _build_tool_dir(real_dir, "t")
    link = tmp_path / "tools" / "t"
    os.symlink(real_dir, link)
    config = _write(tmp_path, "tools.yaml", "tools:\n  t:\n    path: ./tools/t\n")

    # Act (must not raise).
    result = load_config(config)

    # Assert: clean load; the layer resolves through the symlink.
    assert result.diagnostics == []
    tool_yaml_path, mapping = _layer(result, "t")
    assert tool_yaml_path == (link / "tool.yaml").resolve()
    assert mapping["name"] == "t"


# ---------------------------------------------------------------------------
# tool.yaml schema failure location (plan line 165)
# ---------------------------------------------------------------------------


def test_include_tool_yaml_unknown_key_loads_with_file_recorded(
    tmp_path: Path,
) -> None:
    """Plan line 165: a ``tool.yaml`` failing its own schema must report
    diagnostics located in THAT file.

    The loader does NOT schema-validate (root data is equally not
    validated by the loader — ``validate_root`` is behaviour 4's
    layer), so the loader-level pin here is the contract that makes
    the validator's location possible: the accessor records the
    tool.yaml's resolved path and exposes the offending mapping, so a
    later layer can locate its ``ToolYamlConfig`` diagnostics in
    ``tools/t/tool.yaml``, not in ``tools.yaml``.  (The validator
    layer's own ``location.file`` pin lives in its own tests.)
    """
    # Arrange: tool.yaml carries a key ToolYamlConfig forbids.
    config = _build_tree(
        tmp_path, tool_yaml="name: t\nbogus_key: 1\n"
    )

    # Act (must not raise — the loader is not the schema layer).
    result = load_config(config)

    # Assert: clean load; the layer records the file and the content.
    assert result.diagnostics == []
    tool_yaml_path, mapping = _layer(result, "t")
    assert tool_yaml_path == (tmp_path / "tools" / "t" / "tool.yaml").resolve()
    assert mapping == {"name": "t", "bogus_key": 1}


# ---------------------------------------------------------------------------
# backward compatibility with behaviours 6-7 (module docstring)
# ---------------------------------------------------------------------------


def test_include_missing_tool_dir_is_backward_compatible_skip(
    tmp_path: Path,
) -> None:
    """A ``path:`` whose directory does NOT exist at all loads cleanly
    with no diagnostic and no layer.

    This is the backward-compatibility pin that keeps the behaviour
    6-7 fixtures (their minimal configs write ``path: ./tools/...``
    with no tool directory on disk) passing UNCHANGED.  ``TSWAP-C005``
    is reserved for a directory that EXISTS without a ``tool.yaml``;
    a missing directory is skipped here and is expected to be caught
    by a later cross-check behaviour (e.g. behaviour 15's
    exactly-one-image-source rule) rather than at read time.
    """
    # Arrange: the classic minimal config; ``tools/ghost`` is absent.
    config = _write(
        tmp_path, "tools.yaml", "tools:\n  t:\n    path: ./tools/ghost\n"
    )

    # Act (must not raise).
    result = load_config(config)

    # Assert: identical to the pre-include behaviour: clean, no layer.
    assert result.data == {"tools": {"t": {"path": "./tools/ghost"}}}
    assert result.diagnostics == []
    assert result.tool_yaml("t") is None


def test_include_no_path_key_yields_none_layer(tmp_path: Path) -> None:
    """A tool entry without ``path:`` has no layer; an unknown tool
    name also yields ``None`` (pinned accessor contract).
    """
    # Arrange: an inline-only tool.
    config = _write(
        tmp_path,
        "tools.yaml",
        "tools:\n  inline_only:\n    handler: handler.py:Handler\n",
    )

    # Act.
    result = load_config(config)

    # Assert: clean load; no layer for the tool, nor for a ghost name.
    assert result.diagnostics == []
    assert result.tool_yaml("inline_only") is None
    assert result.tool_yaml("ghost") is None

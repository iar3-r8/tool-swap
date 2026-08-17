"""YAML loader for M1 behaviours 6, 7 and 8: read, interpolate, parse, include.

This module is the YAML reading step of the M1 configuration pipeline.  It
reads one config file (UTF-8, BOM and CRLF tolerant), runs behaviour 5's
``interpolate`` on the raw text with an injected environment, parses the
result with a ``SafeLoader`` subclass that records the source line of every
mapping key in a parallel structure kept OUT of the parsed data, and returns
a ``LoadedConfig``.  For interpolation, the injected ``env`` mapping is
merged over a ``.env`` file (behaviour 7): a ``.env`` next to the config is
auto-discovered unless ``env_file`` names a replacement file; the merged
mapping is ``{**env_from_dotenv, **env}`` so the (injected) process
environment wins.  ``env=None`` means the empty mapping and the ambient
process environment is never read.  Every fatal problem (file missing, YAML
syntax error, duplicate key, empty file, non-mapping root, behaviour 5's
missing-variable error, a missing explicit env file, an unparseable
``.env`` line, and behaviour 8's include errors) is raised as a
``ConfigError`` carrying a ``ConfigReport`` with exactly one ERROR
diagnostic.

Behaviour 8 (``path:`` inclusion): a ``tools.<name>:`` entry whose
``path:`` names a directory holding a ``tool.yaml`` includes that file as
the tool's mid-precedence layer, exposed via ``LoadedConfig.tool_yaml``
(the returned path's ``.parent`` is the directory relative paths inside
``tool.yaml`` resolve against, behaviour 10).  A relative ``path:``
resolves against the ROOT CONFIG FILE's directory (never the CWD), ``~``
expands, absolute paths are honoured as-is, and a directory that does not
exist at all is skipped silently (backward compatibility with the
behaviours 6-7 fixtures).  The loader-level include checks are
``TSWAP-C005`` (directory exists but has no ``tool.yaml``),
``TSWAP-C006`` (``path:`` is a file, not a directory), ``TSWAP-C007`` (the
included ``tool.yaml`` itself contains ``path:``; one level only, no
recursion), ``TSWAP-C201`` (``name:`` in ``tool.yaml`` differs from the
``tools:`` map key) and ``TSWAP-C202`` (two entries share a ``path:``; a
WARNING, not fatal).  The loader does not schema-validate ``tool.yaml``
content (that is behaviour 4's layer); it only records the tool.yaml's
resolved path via the accessor so a validator can locate its diagnostics
there.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
import yaml.error

from tool_swap.config.errors import (
    ConfigError,
    ConfigReport,
    Diagnostic,
    Location,
    Severity,
)
from tool_swap.config.interpolate import interpolate

_CODE_NOT_FOUND = "TSWAP-C000"
_CODE_SYNTAX = "TSWAP-C001"
_CODE_DUPLICATE = "TSWAP-C002"
_CODE_EMPTY = "TSWAP-C003"
_CODE_NON_MAPPING = "TSWAP-C004"
_CODE_MISSING_TOOL_YAML = "TSWAP-C005"
_CODE_PATH_IS_FILE = "TSWAP-C006"
_CODE_RECURSION = "TSWAP-C007"
_CODE_ENV_FILE_MISSING = "TSWAP-C011"
_CODE_ENV_PARSE = "TSWAP-C012"
_CODE_NAME_MISMATCH = "TSWAP-C201"
_CODE_SHARED_PATH = "TSWAP-C202"


class _DuplicateKeyError(Exception):
    """Internal signal: a mapping node holds a key twice (plan line 132).

    Attributes:
        line: 1-based source line of the duplicate (second) occurrence.
        key_node: The duplicate key's node, for the message.
    """

    def __init__(self, line: int, key_node: yaml.Node) -> None:
        """Store the duplicate's line and key node."""
        super().__init__(f"duplicate key at line {line}")
        self.line = line
        self.key_node = key_node


def _key_label(key_node: Any) -> str:
    """Return the dotted-path label for a mapping key node."""
    if isinstance(key_node, yaml.ScalarNode):
        return str(key_node.value)
    return str(key_node.id)


def _walk_lines(
    node: Any,
    prefix: tuple[str, ...],
    line_of: Mapping[Any, int],
    lines: dict[str, int],
) -> None:
    """Record ``dotted_path -> line`` for every mapping key reachable from ``node``.

    Sequence elements are indexed numerically so nested paths stay unique;
    the caller only ever looks up dotted paths of keys.  Keys injected by
    ``flatten_mapping`` (merge ``<<``) carry no recorded line and are
    skipped, not fatal.
    """
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            path = prefix + (_key_label(key_node),)
            line = line_of.get(key_node)
            if line is not None:
                lines[".".join(path)] = line
            _walk_lines(value_node, path, line_of, lines)
    elif isinstance(node, yaml.SequenceNode):
        for index, item in enumerate(node.value):
            _walk_lines(item, prefix + (str(index),), line_of, lines)


def _key_signature(key_node: Any) -> tuple[Any, ...]:
    """Return a comparable signature for a mapping key node.

    PyYAML's ``Node.__eq__`` is identity, so two occurrences of the same
    scalar key (e.g. ``ttl:`` twice) are distinct objects; scalar keys are
    therefore compared by ``(tag, value)`` and non-scalar keys fall back to
    identity (the composer reuses the anchored node object for aliases, so
    identity also distinguishes aliased keys).
    """
    if isinstance(key_node, yaml.ScalarNode):
        return ("scalar", key_node.tag, key_node.value)
    return ("id", id(key_node))


def _duplicate_key_message(key_node: Any) -> str:
    """Build the C002 message, naming the duplicated key."""
    if isinstance(key_node, yaml.ScalarNode):
        return f"duplicate key '{key_node.value}' in one mapping"
    return f"duplicate key of type {key_node.id} in one mapping"


def _syntax_message(text: str, mark: Any) -> str:
    """Build the C001 message: the offending line's text plus a ``^`` caret."""
    lines = text.split("\n")
    offending = lines[mark.line].rstrip("\r") if mark.line < len(lines) else ""
    caret = " " * mark.column + "^"
    return (
        "YAML syntax error near line "
        f"{mark.line + 1}, column {mark.column + 1}:\n{offending}\n{caret}"
    )


class _EnvLineError(Exception):
    """Internal signal: a ``.env`` line is not a valid ``KEY=value`` pair.

    Attributes:
        line: 1-based line number of the offending line.
        content: The stripped offending line, for the message.
    """

    def __init__(self, line: int, content: str) -> None:
        """Store the line number and content."""
        super().__init__(f"unparseable .env line {line}")
        self.line = line
        self.content = content


def _unquote(value: str) -> str:
    """Strip one matching pair of surrounding single or double quotes."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a ``.env`` file into a mapping without touching ``os.environ``.

    The supported format is the python-dotenv-compatible subset pinned by
    the tests: ``KEY=value`` lines, ``export `` prefixes, ``#`` comments,
    blank lines, and single- or double-quoted values (quotes stripped, a
    value containing ``=`` survives intact).  Duplicate keys are last-wins,
    matching dotenv semantics.

    Args:
        path: Path of the ``.env`` file (already checked to exist).

    Returns:
        The parsed ``KEY -> value`` mapping.

    Raises:
        _EnvLineError: On a non-empty, non-comment line that is not a
            valid ``KEY=value`` pair, carrying the 1-based line number.
    """
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    values: dict[str, str] = {}
    for line_no, raw_line in enumerate(text.split("\n"), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key:
            raise _EnvLineError(line_no, line)
        values[key] = _unquote(value.strip())
    return values


def _env_file_missing_error(env_file: Path) -> ConfigError:
    """Build the C011 ``ConfigError`` for a missing explicit env file."""
    resolved = str(env_file.resolve())
    error = Diagnostic(
        code=_CODE_ENV_FILE_MISSING,
        severity=Severity.ERROR,
        message=f"env file not found: {resolved}",
        location=Location(file=resolved),
        remedy=(
            "create the file, or drop --env-file to auto-discover .env "
            "next to the config"
        ),
    )
    return ConfigError(ConfigReport((error,)))


def _env_line_error(env_file: Path, err: _EnvLineError) -> ConfigError:
    """Build the C012 ``ConfigError`` for an unparseable ``.env`` line."""
    resolved = str(env_file.resolve())
    error = Diagnostic(
        code=_CODE_ENV_PARSE,
        severity=Severity.ERROR,
        message=f"unparseable .env line {err.line}: {err.content!r}",
        location=Location(file=resolved, line=err.line),
        remedy=("write the line as KEY=value, or prefix it with '#' to comment it out"),
    )
    return ConfigError(ConfigReport((error,)))


def _dotenv_values(path: Path, env_file: Path | None) -> dict[str, str]:
    """Locate and parse the ``.env`` file for interpolation.

    With ``env_file`` given, that file is used INSTEAD of the
    auto-discovered ``.env`` (the auto-discovered one is not also read); a
    missing explicit file is C011.  With ``env_file=None``,
    ``path.parent / ".env"`` is used when present; a missing ``.env`` is
    not an error.  The ambient process environment is never read.

    Args:
        path: Path of the config file, for auto-discovery.
        env_file: Explicit env file, or ``None`` for auto-discovery.

    Returns:
        The parsed mapping; ``{}`` when no env file applies.

    Raises:
        ConfigError: C011 for a missing explicit file; C012 for an
            unparseable line (the first one, in file order).
    """
    if env_file is not None:
        if not env_file.is_file():
            raise _env_file_missing_error(env_file)
        target = env_file
    else:
        candidate = path.parent / ".env"
        if not candidate.is_file():
            return {}
        target = candidate
    try:
        return _parse_env_file(target)
    except _EnvLineError as err:
        raise _env_line_error(target, err) from None


# ---------------------------------------------------------------------------
# Behaviour 8 — ``path:`` inclusion of ``tool.yaml``
# ---------------------------------------------------------------------------


def _resolve_tool_path(value: str, base_dir: Path) -> Path:
    """Resolve a ``path:`` value against the root config file's directory.

    ``~`` is expanded on the value BEFORE joining, because a tilde
    embedded in an already-joined path is not a leading one and
    ``expanduser`` would leave it literal; a leading tilde expands to an
    absolute path, and joining an absolute right-hand path returns that
    path as-is, which also honours absolute ``path:`` values.

    Args:
        value: The ``path:`` value from the config.
        base_dir: The root config file's directory (never the CWD).

    Returns:
        The resolved absolute path; relative values resolve against
        ``base_dir``, ``~`` expands via ``expanduser``, absolute values
        are honoured as-is.
    """
    return (base_dir / Path(value).expanduser()).resolve()


def _missing_tool_yaml_error(tool_dir: Path) -> ConfigError:
    """Build the C005 ``ConfigError``: the directory exists, no tool.yaml."""
    resolved = str(tool_dir.resolve())
    error = Diagnostic(
        code=_CODE_MISSING_TOOL_YAML,
        severity=Severity.ERROR,
        message=f"tool directory {resolved} exists but has no tool.yaml",
        location=Location(file=resolved),
        remedy=(
            "create tool.yaml in that directory, or drop the 'path:' key "
            "and configure the tool inline"
        ),
    )
    return ConfigError(ConfigReport((error,)))


def _path_is_file_error(target: Path) -> ConfigError:
    """Build the C006 ``ConfigError``: ``path:`` points at a file."""
    resolved = str(target.resolve())
    error = Diagnostic(
        code=_CODE_PATH_IS_FILE,
        severity=Severity.ERROR,
        message=f"tool path {resolved} is a file, not a directory",
        location=Location(file=resolved),
        remedy=(
            "point 'path:' at the directory that holds tool.yaml "
            "(a tool directory, e.g. ./tools/t)"
        ),
    )
    return ConfigError(ConfigReport((error,)))


def _recursion_error(tool_yaml: Path) -> ConfigError:
    """Build the C007 ``ConfigError``: tool.yaml contains a ``path:`` key."""
    resolved = str(tool_yaml.resolve())
    error = Diagnostic(
        code=_CODE_RECURSION,
        severity=Severity.ERROR,
        message=(
            "included tool.yaml contains a 'path:' key; include recursion "
            "is not supported (one level only)"
        ),
        location=Location(file=resolved),
        remedy=(
            "remove the 'path:' key from tool.yaml; nested includes are not allowed"
        ),
    )
    return ConfigError(ConfigReport((error,)))


def _name_mismatch_error(
    map_key: str, declared_name: str, tool_yaml: Path
) -> ConfigError:
    """Build the C201 ``ConfigError``: tool.yaml ``name:`` != map key."""
    resolved = str(tool_yaml.resolve())
    error = Diagnostic(
        code=_CODE_NAME_MISMATCH,
        severity=Severity.ERROR,
        message=(
            f"tool.yaml declares name '{declared_name}' but the tools: "
            f"map key is '{map_key}'"
        ),
        location=Location(file=resolved),
        remedy=(
            "make the 'name:' in tool.yaml equal the tools: map key, or "
            "remove the 'name:' key if this tool.yaml is shared"
        ),
    )
    return ConfigError(ConfigReport((error,)))


def _shared_path_warning(keys: tuple[str, ...], config_file: str) -> Diagnostic:
    """Build the C202 WARNING: several entries use the same ``path:``."""
    names = " and ".join(repr(key) for key in keys)
    return Diagnostic(
        code=_CODE_SHARED_PATH,
        severity=Severity.WARNING,
        message=f"tools {names} use the same 'path:' value",
        location=Location(file=config_file),
        remedy=(
            "give each tool its own directory, unless the entries "
            "deliberately differ only by params:"
        ),
    )


def _read_tool_yaml(tool_yaml: Path) -> Any:
    """Read and parse an included ``tool.yaml`` (no interpolation).

    Args:
        tool_yaml: The tool.yaml file (already checked to exist).

    Returns:
        The parsed YAML content, whatever its type (the caller handles
        non-mapping content; the loader does not schema-validate).

    Raises:
        ConfigError: C001, with the location in the tool.yaml file, for a
            YAML syntax error.
    """
    resolved = str(tool_yaml.resolve())
    raw_text = tool_yaml.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    try:
        return yaml.safe_load(raw_text)
    except yaml.error.YAMLError as err:
        error = Diagnostic(
            code=_CODE_SYNTAX,
            severity=Severity.ERROR,
            message=f"YAML syntax error in {resolved}: {err}",
            location=Location(file=resolved),
            remedy="fix the YAML syntax in the included tool.yaml",
        )
        raise ConfigError(ConfigReport((error,))) from None


def _load_includes(
    data: dict[str, Any], base_dir: Path, config_file: str
) -> tuple[dict[str, tuple[Path, dict[str, Any]]], list[Diagnostic]]:
    """Process every ``tools.<name>:`` entry's ``path:`` (behaviour 8).

    Args:
        data: The parsed root mapping (not mutated).
        base_dir: The root config file's directory, the anchor for
            relative ``path:`` values (CWD-independent).
        config_file: The resolved root config file path, the C202
            warning's location.

    Returns:
        A ``(layers, diagnostics)`` pair: ``layers`` maps each tool name
        whose ``path:`` was successfully included to
        ``(resolved tool.yaml path, parsed tool.yaml mapping)``; a tool
        with no ``path:`` key, or whose resolved directory does not
        exist, gets no layer (the backward-compat skip); ``diagnostics``
        holds the non-fatal C202 warning(s).

    Raises:
        ConfigError: C001 (tool.yaml YAML syntax error), C005 (directory
            without tool.yaml), C006 (path is a file), C007 (tool.yaml
            contains ``path:``), or C201 (``name:`` mismatch).  A
            non-mapping tool entry is skipped (its shape is the schema
            layer's concern).
    """
    tools = data.get("tools")
    layers: dict[str, tuple[Path, dict[str, Any]]] = {}
    warnings: list[Diagnostic] = []
    if not isinstance(tools, dict):
        return layers, warnings
    # Resolved path -> the tool keys using it, in map order (for C202).
    seen_paths: dict[str, list[str]] = {}
    for name, entry in tools.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            continue
        target = _resolve_tool_path(entry["path"], base_dir)
        if not target.exists():
            continue  # backward-compat skip; a later behaviour catches it
        if not target.is_dir():
            raise _path_is_file_error(target)
        tool_yaml = target / "tool.yaml"
        if not tool_yaml.is_file():
            raise _missing_tool_yaml_error(target)
        content: Any = _read_tool_yaml(tool_yaml)
        if not isinstance(content, dict):
            content = {}
        if "path" in content:
            raise _recursion_error(tool_yaml)
        declared = content.get("name")
        if declared is not None and declared != name:
            raise _name_mismatch_error(name, str(declared), tool_yaml)
        layers[str(name)] = (tool_yaml.resolve(), content)
        seen_paths.setdefault(str(target), []).append(str(name))
    for keys in seen_paths.values():
        if len(keys) > 1:
            warnings.append(_shared_path_warning(tuple(keys), config_file))
    return layers, warnings


@dataclass(frozen=True)
class LoadedConfig:
    """A successfully loaded config: raw data, path echo, line info, layers.

    Attributes:
        data: The parsed top-level mapping; line info and included
            ``tool.yaml`` layers (behaviour 8) are kept OUT of it.
        path: The path exactly as passed to ``load_config`` (not resolved).
        diagnostics: Non-fatal notes; ``[]`` on a clean load.
        _line_map: Dotted YAML path -> 1-based source line, for ``line_for``.
        _tool_layers: Tool name -> included tool.yaml layer (behaviour 8).
    """

    data: dict[str, Any]
    path: Path
    diagnostics: list[Diagnostic]
    _line_map: dict[str, int] = field(default_factory=dict)
    _tool_layers: dict[str, tuple[Path, dict[str, Any]]] = field(default_factory=dict)

    def line_for(self, yaml_path: str) -> int | None:
        """Return the 1-based source line of the key named by ``yaml_path``.

        Args:
            yaml_path: Dotted path, e.g. ``"tools"``, ``"tools.t"``,
                ``"tools.t.path"``.

        Returns:
            The 1-based source line of that key (mapping keys and leaf
            keys alike), or ``None`` when the path is absent from the data.
        """
        current: Any = self.data
        for segment in yaml_path.split("."):
            if not isinstance(current, dict):
                return None
            if segment not in current:
                return None
            current = current[segment]
        return self._line_map.get(yaml_path)

    def tool_yaml(self, name: str) -> tuple[Path, dict[str, Any]] | None:
        """Return the included ``tool.yaml`` layer for tool ``name``.

        The first element is the resolved absolute path of the included
        ``tool.yaml``; its ``.parent`` is the directory that relative
        paths inside ``tool.yaml`` (``handler.py:Cls``,
        ``requirements.txt``) resolve against (behaviour 10).  The
        second is the parsed ``tool.yaml`` mapping, as-is.  ``data`` is
        NOT polluted: the layer is exposed only through this accessor.

        Args:
            name: The ``tools:`` map key of the tool.

        Returns:
            ``(resolved tool.yaml path, parsed tool.yaml mapping)`` for a
            tool whose ``path:`` was included, or ``None`` when the tool
            has no ``path:`` key, its resolved directory does not exist
            (the backward-compat skip), or ``name`` is not a key of
            ``tools:``.
        """
        return self._tool_layers.get(name)


class LineTrackingLoader(yaml.SafeLoader):
    """A ``SafeLoader`` that records each mapping key's source line.

    ``construct_mapping`` records the 1-based line of every key node in
    ``line_of`` (a node -> line table kept out of the parsed data) and
    raises ``_DuplicateKeyError`` on a repeated key, because PyYAML's
    default silently last-wins and a duplicated ``ttl:`` where one value is
    ignored is exactly the silent failure M1 exists to eliminate.  Merge-key
    handling (``<<``) comes unchanged from the base constructor, and
    ``root_node`` holds the composed root for the post-parse line walk.
    """

    def __init__(self, stream: Any) -> None:
        """Initialize the loader, its node -> line table, and root slot."""
        super().__init__(stream)
        self.line_of: dict[Any, int] = {}
        self.root_node: Any = None

    def construct_mapping(
        self, node: Any, deep: bool = False, **kwargs: Any
    ) -> dict[Any, Any]:
        """Record key lines, reject duplicate keys, then build the mapping.

        Duplicate detection runs BEFORE any key/value construction so the
        first duplicate in document order is the one reported.
        """
        if isinstance(node, yaml.MappingNode):
            seen: set[Any] = set()
            for key_node, _value_node in node.value:
                self.line_of[key_node] = key_node.start_mark.line + 1
                signature = _key_signature(key_node)
                if signature in seen:
                    raise _DuplicateKeyError(key_node.start_mark.line + 1, key_node)
                seen.add(signature)
        return super().construct_mapping(node, deep=deep, **kwargs)

    def construct_document(self, node: Any) -> Any:
        """Remember the composed root node, then construct the document."""
        self.root_node = node
        return super().construct_document(node)


def load_config(
    path: Path,
    *,
    env: Mapping[str, str] | None = None,
    env_file: Path | None = None,
) -> LoadedConfig:
    """Read, interpolate, and parse the YAML config at ``path``.

    Interpolation (behaviour 5) runs on the raw text BEFORE YAML parsing
    with a merged environment: a ``.env`` file (behaviour 7) is parsed and
    the injected ``env`` mapping is merged over it, so a variable set in
    both resolves to ``env``'s value.  With ``env_file=None`` the ``.env``
    next to the config (``path.parent / ".env"``) is used when present and
    a missing ``.env`` is not an error; with ``env_file`` given, that file
    is used INSTEAD of the auto-discovered one and a missing file is C011.
    ``env=None`` means the empty mapping and the ambient process
    environment is never read.  ``.env`` values are interpolation-only:
    they never appear in the returned data or diagnostics.  Parsing uses a
    ``SafeLoader`` subclass that records each mapping key's source line in
    a parallel structure, so the returned ``data`` stays clean for the
    schema layer.  Behaviour 8's ``path:`` inclusion then loads each
    tool's ``tool.yaml`` (kept OUT of ``data``, exposed via
    ``LoadedConfig.tool_yaml``); a missing target directory is skipped
    silently (backward compatibility).  Every fatal problem raises
    ``ConfigError`` carrying a ``ConfigReport`` with exactly one ERROR
    diagnostic: C000 missing file, C001 YAML syntax error, C002 duplicate
    key, C003 empty file, C004 non-mapping root, C005 (behaviour 8)
    directory without tool.yaml, C006 (behaviour 8) path is a file, C007
    (behaviour 8) include recursion, C010 (behaviour 5) missing variable,
    C011 missing explicit env file, C012 unparseable ``.env`` line, or
    C201 (behaviour 8) tool.yaml name mismatch.  The C202 shared-path note
    is a WARNING in the returned diagnostics, not fatal.

    Args:
        path: Path of the config file (echoed back unresolved).
        env: Environment mapping for interpolation; keyword-only; wins
            over any ``.env`` value for the same variable.
        env_file: Explicit env file, replacing auto-discovery;
            keyword-only.

    Returns:
        The loaded config: parsed top-level mapping, path echo, diagnostics
        (empty on a clean load), and a dotted-path -> line index.

    Raises:
        ConfigError: With a report holding exactly one ERROR diagnostic,
            for every fatal C0xx case.
    """
    resolved = str(path.resolve())
    if not path.is_file():
        error = Diagnostic(
            code=_CODE_NOT_FOUND,
            severity=Severity.ERROR,
            message=f"config file not found: {resolved}",
            location=Location(file=resolved),
            remedy="create tools.yaml, or pass --config <path>",
        )
        raise ConfigError(ConfigReport((error,)))

    # BOM-tolerant read (utf-8-sig), CRLF normalized so reported lines are
    # stable regardless of the file's line endings (plan line 133).
    raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")

    dotenv_env = _dotenv_values(path, env_file)
    env_mapping: Mapping[str, str] = {
        **dotenv_env,
        **(env if env is not None else {}),
    }
    interpolated = interpolate(raw, env_mapping, file=resolved)
    if interpolated.errors:
        raise ConfigError(ConfigReport(tuple(interpolated.errors)))

    loader = LineTrackingLoader(interpolated.text)
    try:
        data: Any = loader.get_data()
    except _DuplicateKeyError as dup:
        error = Diagnostic(
            code=_CODE_DUPLICATE,
            severity=Severity.ERROR,
            message=_duplicate_key_message(dup.key_node),
            location=Location(file=resolved, line=dup.line),
            remedy="remove the duplicate key so the mapping has one of each",
        )
        raise ConfigError(ConfigReport((error,))) from None
    except yaml.error.YAMLError as err:
        if isinstance(err, yaml.error.MarkedYAMLError):
            mark = (
                err.problem_mark if err.problem_mark is not None else err.context_mark
            )
            if mark is not None:
                location = Location(
                    file=resolved, line=mark.line + 1, column=mark.column + 1
                )
                message = _syntax_message(interpolated.text, mark)
            else:
                location = Location(file=resolved)
                message = f"YAML syntax error: {err.problem or err.context or err}"
        else:
            location = Location(file=resolved)
            message = f"YAML syntax error: {err}"
        error = Diagnostic(
            code=_CODE_SYNTAX,
            severity=Severity.ERROR,
            message=message,
            location=location,
            remedy="fix the YAML syntax at the cited line",
        )
        raise ConfigError(ConfigReport((error,))) from None

    if data is None:
        error = Diagnostic(
            code=_CODE_EMPTY,
            severity=Severity.ERROR,
            message=(
                f"config file {resolved} is empty; a minimal config needs a "
                "'tools:' block"
            ),
            location=Location(file=resolved),
            remedy="add at least a 'tools:' block, e.g. the minimal config",
        )
        raise ConfigError(ConfigReport((error,)))

    if not isinstance(data, dict):
        found = "a list" if isinstance(data, list) else "a scalar"
        error = Diagnostic(
            code=_CODE_NON_MAPPING,
            severity=Severity.ERROR,
            message=f"top level of the config is {found}, not a mapping",
            location=Location(file=resolved, line=1),
            remedy="make the top level a YAML mapping of keys to values",
        )
        raise ConfigError(ConfigReport((error,)))

    lines: dict[str, int] = {}
    _walk_lines(loader.root_node, (), loader.line_of, lines)

    layers, diagnostics = _load_includes(data, path.parent, resolved)
    return LoadedConfig(
        data=data,
        path=path,
        diagnostics=diagnostics,
        _line_map=lines,
        _tool_layers=layers,
    )

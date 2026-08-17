"""YAML loader for M1 behaviour 6: read, interpolate, parse, track source lines.

This module is the YAML reading step of the M1 configuration pipeline.  It
reads one config file (UTF-8, BOM and CRLF tolerant), runs behaviour 5's
``interpolate`` on the raw text with an injected environment (``env=None``
means the empty mapping; the ambient process environment is never read),
parses the result with a ``SafeLoader`` subclass that records the source line
of every mapping key in a parallel structure kept OUT of the parsed data,
and returns a ``LoadedConfig``.  Every fatal problem (file missing, YAML
syntax error, duplicate key, empty file, non-mapping root, and behaviour 5's
missing-variable error) is raised as a ``ConfigError`` carrying a
``ConfigReport`` with exactly one ERROR diagnostic.
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


@dataclass(frozen=True)
class LoadedConfig:
    """A successfully loaded config: raw data, path echo, and line info.

    Attributes:
        data: The parsed top-level mapping; line info is kept OUT of it.
        path: The path exactly as passed to ``load_config`` (not resolved).
        diagnostics: Non-fatal notes; ``[]`` on a clean load.
        _line_map: Dotted YAML path -> 1-based source line, for ``line_for``.
    """

    data: dict[str, Any]
    path: Path
    diagnostics: list[Diagnostic]
    _line_map: dict[str, int] = field(default_factory=dict)

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
) -> LoadedConfig:
    """Read, interpolate, and parse the YAML config at ``path``.

    Interpolation (behaviour 5) runs on the raw text BEFORE YAML parsing
    with the injected ``env`` mapping; ``env=None`` means the empty mapping
    and the ambient process environment is never read.  Parsing uses a
    ``SafeLoader`` subclass that records each mapping key's source line in
    a parallel structure, so the returned ``data`` stays clean for the
    schema layer.  Every fatal problem raises ``ConfigError`` carrying a
    ``ConfigReport`` with exactly one ERROR diagnostic: C000 missing file,
    C001 YAML syntax error, C002 duplicate key, C003 empty file, C004
    non-mapping root, or C010 (behaviour 5) missing variable.

    Args:
        path: Path of the config file (echoed back unresolved).
        env: Environment mapping for interpolation; keyword-only.

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

    env_mapping: Mapping[str, str] = env if env is not None else {}
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
    return LoadedConfig(data=data, path=path, diagnostics=[], _line_map=lines)

"""The ``tswap config show`` CLI command (behaviour 22).

The display twin of :mod:`tool_swap.cli.validate`: the same shared
load/resolve/rule chain (:func:`~tool_swap.cli._pipeline.run_pipeline`)
with a deterministic renderer over ``ResolvedTool.values`` +
:class:`~tool_swap.config.origin.OriginMap` instead of a diagnostic
report.  The contract is pinned in ``plans/m1-configuration.md``
behaviour 22, "Confirmed contract details (2026-08-20)", items 1-15; the
golden snapshot in ``tests/unit/cli/test_config_show_cli.py`` is the
byte-for-byte spec for the renderer.

The command body is the plain function :func:`show`, registered on the
``config`` sub-app :data:`config_app`; :mod:`tool_swap.cli.main` adds that
sub-app to the root app and stays the single registration point.  The
command keeps its own ``try``/``except ConfigError``/``except typer.Exit:
raise``/``except Exception`` guard, which owns the exit codes (plan item
12's table, minus the ``--strict`` / ``--allow-missing-descriptions``
rows).  The schema compiler is NOT run: this is a display command, and
``config show`` may therefore exit 0 where ``validate`` fails with an
``S1xx`` (plan item 11).
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Final

import typer

from tool_swap.cli._pipeline import Pipeline, _implicates, run_pipeline
from tool_swap.cli.validate import _unknown_tool
from tool_swap.config.defaults import BUILT_IN_DEFAULTS
from tool_swap.config.errors import (
    ConfigError,
    ConfigReport,
    Diagnostic,
)
from tool_swap.config.loader import LoadedConfig
from tool_swap.config.origin import Origin, OriginLevel
from tool_swap.config.resolver import ResolvedTool
from tool_swap.config.validate import ValidatedConfig, effective_groups, parse_mount

#: The fixed origin column every annotation aligns to (plan item 1).
_ORIGIN_COLUMN: Final[int] = 40

#: The built-in annotation, verbatim (``origin.py``'s ``_BUILT_IN_SOURCE``).
_BUILTIN_ANNOTATION: Final[str] = "built-in default"

#: The A12 redacted value (plan item 9).
_REDACTED: Final[str] = "***"

#: The defaulted-mount note, behaviour 17's pinned shared phrase (item 6).
_MODE_DEFAULTED_NOTE: Final[str] = "mode defaulted to ro"

#: The case-insensitive substring env-key secret match (plan item 9, A12).
_SECRET_ENV_RE: Final[re.Pattern[str]] = re.compile(
    r"TOKEN|SECRET|KEY|PASSWORD", re.IGNORECASE
)

#: The 9 ``router:`` and 8 ``backend:`` fields, identified by set so the
#: display ORDER always derives from ``BUILT_IN_DEFAULTS`` declaration
#: order (plan items 3 and 4) and can never drift from it.
_ROUTER_SET: Final[frozenset[str]] = frozenset(
    {
        "host",
        "port",
        "log_level",
        "log_dir",
        "log_json",
        "cors_origins",
        "auth_token",
        "status_page",
        "log_output",
    }
)
_BACKEND_SET: Final[frozenset[str]] = frozenset(
    {
        "type",
        "network",
        "container_prefix",
        "label_namespace",
        "gpu_runtime",
        "orphans",
        "port_range",
        "registry_prefix",
    }
)

#: The 9 router fields, in ``BUILT_IN_DEFAULTS`` declaration order.
ROUTER_FIELDS: Final[tuple[str, ...]] = tuple(
    field for field in BUILT_IN_DEFAULTS if field in _ROUTER_SET
)

#: The 8 backend fields, in ``BUILT_IN_DEFAULTS`` declaration order.
BACKEND_FIELDS: Final[tuple[str, ...]] = tuple(
    field for field in BUILT_IN_DEFAULTS if field in _BACKEND_SET
)

#: The 30 tool-level fields, derived — never hand-copied — in
#: ``BUILT_IN_DEFAULTS`` declaration order (plan item 3).
TOOL_FIELDS: Final[tuple[str, ...]] = tuple(
    field
    for field in BUILT_IN_DEFAULTS
    if field not in _ROUTER_SET and field not in _BACKEND_SET
)


# ---------------------------------------------------------------------------
# Pure value rendering (plan item 1)
# ---------------------------------------------------------------------------


def _render_value(obj: object) -> str:
    """Render one resolved value in the pinned YAML-ish form.

    ``None`` → ``null``; ``True`` / ``False`` → ``true`` / ``false``;
    strings as authored, unquoted; numbers via ``repr``; a list as
    ``[a, b, c]`` with each element rendered recursively; a mapping as
    ``{k: v, ...}`` (the ``env`` block renders its keys itself, this is
    the total fallback).

    Args:
        obj: The value to render, in any legal Python shape.

    Returns:
        The rendered string form.
    """
    if obj is None:
        return "null"
    if obj is True:
        return "true"
    if obj is False:
        return "false"
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (int, float)):
        return repr(obj)
    if isinstance(obj, Mapping):
        return "{" + ", ".join(f"{k}: {_render_value(v)}" for k, v in obj.items()) + "}"
    if isinstance(obj, (list, tuple)):
        return "[" + ", ".join(_render_value(e) for e in obj) + "]"
    return str(obj)


def _padded(left: str, annotation: str) -> str:
    """Align ``# <annotation>`` to the fixed origin column (plan item 1).

    The left half (``  <name>: <value>`` or an entry line) is padded to
    :data:`_ORIGIN_COLUMN`; when it is already ≥ 40 characters it is
    followed by exactly one space and then the ``#`` — never truncated.

    Args:
        left: The left half, value included, without the annotation.
        annotation: The origin annotation text (no leading ``#``).

    Returns:
        The complete rendered line, without a trailing newline.
    """
    if len(left) >= _ORIGIN_COLUMN:
        return left + " " + f"# {annotation}"
    return left.ljust(_ORIGIN_COLUMN) + f"# {annotation}"


# ---------------------------------------------------------------------------
# Origin annotation (plan item 1)
# ---------------------------------------------------------------------------


def _origin_of(tool: ResolvedTool, path: str) -> Origin:
    """The winning origin for ``path``, total over unrecorded paths.

    ``OriginMap.winning`` raises ``KeyError`` for an unrecorded path (the
    empty merged ``env`` and the empty ``mounts`` list are the two real
    cases); the built-in origin is the truth for them (plan item 1's
    totality pin).

    Args:
        tool: The resolved tool whose origin map is read.
        path: The dotted origin path, e.g. ``"ttl"``, ``"env.HF_HOME"``,
            ``"mounts[0]"``.

    Returns:
        The winning origin, or :meth:`Origin.built_in` when unrecorded.
    """
    try:
        return tool.origins.winning(path)
    except KeyError:
        return Origin.built_in()


def _origin_line(
    loaded: LoadedConfig, key: str, path: str, origin: Origin
) -> int | None:
    """The honest line number for a winning origin, or ``None``.

    ``INLINE`` reads ``tools.<key>.<path>`` from the root line map;
    ``DEFAULTS`` with the ``"defaults"`` source reads
    ``defaults.<path>``; a group source (``"groups.<n>.<f>"``) reads
    ``origin.source`` itself; the ``tool.yaml`` layer has no line map
    (pinned: the annotation carries the path, never a line).

    Args:
        loaded: The loaded config, for its ROOT-document line map.
        key: The ``tools:`` map key of the tool.
        path: The dotted suffix of the field, e.g. ``"ttl"`` or
            ``"env.HF_HOME"``.
        origin: The origin to locate.

    Returns:
        The 1-based source line, or ``None`` when unavailable.
    """
    if origin.level is OriginLevel.INLINE:
        return loaded.line_for(f"tools.{key}.{path}")
    if origin.level is OriginLevel.DEFAULTS:
        if origin.source.startswith("groups."):
            return loaded.line_for(origin.source)
        return loaded.line_for(f"defaults.{path}")
    return None


def _annotate(
    origin: Origin, *, file: str, line: int | None, tool_yaml_path: str | None
) -> str:
    """The origin annotation text (no leading ``#``) for a winning origin.

    A third renderer, deliberately: it reuses the WORDS of
    ``Origin.render`` — ``(inline)``, ``(tool.yaml)``, ``(defaults)``,
    ``built-in default`` — in the trailing-comment shape, with the
    honest line-number availability of plan item 1.

    Args:
        origin: The winning origin.
        file: The config path as the user typed it.
        line: The line from :func:`_origin_line`, or ``None`` (the
            annotation then degrades to the file alone).
        tool_yaml_path: The resolved ``tool.yaml`` path for a
            ``path:`` tool, or ``None``.

    Returns:
        The annotation, e.g. ``tools.yaml:14 (inline)`` or
        ``built-in default``.
    """
    if origin.level is OriginLevel.BUILT_IN:
        return _BUILTIN_ANNOTATION
    if origin.level is OriginLevel.TOOL_YAML:
        path = tool_yaml_path if tool_yaml_path is not None else origin.source
        return f"{path} (tool.yaml)"
    base = f"{file}:{line}" if line is not None else file
    if origin.level is OriginLevel.INLINE:
        return f"{base} (inline)"
    if origin.source.startswith("groups."):
        parts = origin.source.split(".", 2)
        group_name = parts[1] if len(parts) >= 2 else "unnamed"
        return f"{base} (group '{group_name}')"
    return f"{base} (defaults)"


# ---------------------------------------------------------------------------
# Redaction (plan item 9, A12)
# ---------------------------------------------------------------------------


def _redact(value: object, name: str | None, *, show_secrets: bool) -> object:
    """Apply the A12 redaction rule to one displayed value.

    A value is redacted to :data:`_REDACTED` iff its display name is
    exactly ``auth_token`` or matches :data:`_SECRET_ENV_RE` as a
    case-insensitive substring, and the value is not ``None`` (``None``
    prints ``null``, never ``***``), and ``--show-secrets`` is off.  The
    origin is untouched: redaction is a pure render-time function.

    Args:
        value: The resolved value.
        name: The display name — the router block field name or the
            ``env`` key; ``None`` when there is no name to test.
        show_secrets: Whether ``--show-secrets`` opts out globally.

    Returns:
        :data:`_REDACTED` when redacted, else the value unchanged.
    """
    if show_secrets or value is None or name is None:
        return value
    if name == "auth_token" or _SECRET_ENV_RE.search(name):
        return _REDACTED
    return value


# ---------------------------------------------------------------------------
# --verbose: the shadowed values (plan item 2)
# ---------------------------------------------------------------------------


def _shadow_value(
    origin: Origin, *, field: str | None, path: str, raw: dict[str, object]
) -> object:
    """Recover the value a shadowed layer contributed, or ``None``.

    Total over the three pinned cases (plan item 2): a
    ``DEFAULTS``/``"defaults"`` shadow is read from ``raw["defaults"]``
    (a per-``env``-key shadow from ``raw["defaults"]["env"][<key>]``);
    a group shadow from ``effective_groups(raw)[<n>][<field>]``; a
    ``TOOL_YAML`` shadow is deliberately NOT looked up (assumption A25:
    recovering it would need a second flattening implementation) and
    yields ``None``.  A ``None`` lookup failure renders ``null`` — an
    honest degradation, never a crash.

    Args:
        origin: The shadowed origin.
        field: The flat built-in field name, or ``None`` for a
            per-``env``-key path.
        path: The origin-map path, e.g. ``"ttl"`` or ``"env.HF_HOME"``.
        raw: The raw root YAML mapping.

    Returns:
        The shadowed value, or ``None`` when not recoverable.
    """
    if origin.level is not OriginLevel.DEFAULTS:
        return None
    if not origin.source.startswith("groups."):
        block = raw.get("defaults")
        if not isinstance(block, Mapping):
            return None
        if path.startswith("env."):
            env = block.get("env")
            env_key = path.split(".", 1)[1]
            if isinstance(env, Mapping) and env_key in env:
                return env[env_key]
            return None
        if field is not None and field in block:
            return block[field]
        return None
    parts = origin.source.split(".", 2)
    if len(parts) != 3:
        return None
    _prefix, group_name, group_field = parts
    group = effective_groups(raw).get(group_name)
    if not isinstance(group, Mapping):
        return None
    if group_field == "env" and path.startswith("env."):
        env = group.get("env")
        env_key = path.split(".", 1)[1]
        if isinstance(env, Mapping) and env_key in env:
            return env[env_key]
        return None
    if group_field in group:
        return group[group_field]
    return None


def _shadow_lines(
    *,
    tool: ResolvedTool,
    path: str,
    field: str | None,
    key: str,
    loaded: LoadedConfig,
    file_str: str,
    ty_path: str | None,
    raw: dict[str, object],
    show_secrets: bool,
) -> list[str]:
    """The ``--verbose`` shadow lines for one displayed value (item 2).

    Separate lines, indented to the origin column, one per shadow entry:
    ``# overrides <value> from <annotation-of-that-origin>``; a
    ``tool.yaml``-layer shadow omits its value by design (A25) and
    renders ``# overrides the value in <path> (tool.yaml)``.  Shadowed
    secret values are redacted exactly as the winning line's (item 9).

    Args:
        tool: The resolved tool.
        path: The origin-map path of the displayed value.
        field: The flat built-in field name, or ``None`` for a
            per-entry path (no built-in tail).
        key: The ``tools:`` map key of the tool.
        loaded: The loaded config, for the root line map.
        file_str: The config path as the user typed it.
        ty_path: The resolved ``tool.yaml`` path, or ``None``.
        raw: The raw root YAML mapping, for value recovery.
        show_secrets: Whether redaction is opted out.

    Returns:
        The shadow lines (possibly empty), without trailing newlines.
    """
    entries: list[tuple[Origin, object]] = []
    try:
        shadows = tool.origins.shadowed(path)
    except KeyError:
        shadows = []
    for origin in shadows:
        entries.append((origin, _shadow_value(origin, field=field, path=path, raw=raw)))
    winning = _origin_of(tool, path)
    if (
        field is not None
        and winning.level is not OriginLevel.BUILT_IN
        and field in BUILT_IN_DEFAULTS
    ):
        entries.append((Origin.built_in(), BUILT_IN_DEFAULTS[field]))
    lines: list[str] = []
    for origin, value in entries:
        if origin.level is OriginLevel.TOOL_YAML:
            target = ty_path if ty_path is not None else origin.source
            lines.append(
                " " * _ORIGIN_COLUMN + f"# overrides the value in {target} (tool.yaml)"
            )
            continue
        line = _origin_line(loaded, key, path, origin)
        annotation = _annotate(origin, file=file_str, line=line, tool_yaml_path=ty_path)
        if path.startswith("env."):
            value = _redact(value, path.split(".", 1)[1], show_secrets=show_secrets)
        elif field is not None:
            value = _redact(value, field, show_secrets=show_secrets)
        lines.append(
            " " * _ORIGIN_COLUMN
            + f"# overrides {_render_value(value)} from {annotation}"
        )
    return lines


# ---------------------------------------------------------------------------
# The human renderer (plan items 1, 3-7)
# ---------------------------------------------------------------------------


def _block_lines(
    raw: dict[str, object],
    block: str,
    fields: tuple[str, ...],
    loaded: LoadedConfig,
    file_str: str,
    show_secrets: bool,
) -> list[str]:
    """One top-level ``router:`` / ``backend:`` block (plan item 4).

    The value is ``raw[block].get(field, BUILT_IN_DEFAULTS[field])`` —
    a two-layer resolution done in the renderer, because no resolver
    layer can supply these keys.  Present in the raw block annotates
    ``<file>:<line> (<block>)`` with the root line map's line; absent
    annotates ``built-in default``.

    Args:
        raw: The raw root YAML mapping.
        block: ``"router"`` or ``"backend"``.
        fields: The block's fields, in display order.
        loaded: The loaded config, for the root line map.
        file_str: The config path as the user typed it.
        show_secrets: Whether redaction is opted out.

    Returns:
        The block's field lines, without a header or trailing newlines.
    """
    block_raw = raw.get(block)
    lines: list[str] = []
    for field in fields:
        present = isinstance(block_raw, Mapping) and field in block_raw
        value = (
            block_raw[field]
            if isinstance(block_raw, Mapping) and field in block_raw
            else BUILT_IN_DEFAULTS[field]
        )
        value = _redact(value, field, show_secrets=show_secrets)
        if present:
            line = loaded.line_for(f"{block}.{field}")
            annotation = (
                f"{file_str}:{line} ({block})"
                if line is not None
                else f"{file_str} ({block})"
            )
        else:
            annotation = _BUILTIN_ANNOTATION
        lines.append(_padded(f"  {field}: {_render_value(value)}", annotation))
    return lines


def _env_block(
    *,
    key: str,
    tool: ResolvedTool,
    loaded: LoadedConfig,
    raw: dict[str, object],
    file_str: str,
    ty_path: str | None,
    verbose: bool,
    show_secrets: bool,
) -> list[str]:
    """The ``env`` field: per-key lines, per-key origins (plan item 5).

    A non-empty merged mapping prints an unannotated ``  env:`` header
    then one line per key in the resolver's MERGED order (not sorted);
    an empty mapping prints ``env: {}`` on one line annotated
    ``built-in default`` (the totality pin); a non-mapping winner
    (``env: null``) prints the one-line form with the whole-block
    origin.

    Args:
        key: The ``tools:`` map key of the tool.
        tool: The resolved tool.
        loaded: The loaded config, for the root line map.
        raw: The raw root YAML mapping, for shadow value recovery.
        file_str: The config path as the user typed it.
        ty_path: The resolved ``tool.yaml`` path, or ``None``.
        verbose: Whether ``--verbose`` shadow lines are shown.
        show_secrets: Whether redaction is opted out.

    Returns:
        The env lines, without trailing newlines.
    """
    value = tool.values["env"]
    if isinstance(value, Mapping) and value:
        lines: list[str] = ["  env:"]
        for env_key, env_value in value.items():
            path = f"env.{env_key}"
            origin = _origin_of(tool, path)
            annotation = _annotate(
                origin,
                file=file_str,
                line=_origin_line(loaded, key, path, origin),
                tool_yaml_path=ty_path,
            )
            rendered = _render_value(
                _redact(env_value, str(env_key), show_secrets=show_secrets)
            )
            lines.append(_padded(f"    {env_key}: {rendered}", annotation))
            if verbose:
                lines += _shadow_lines(
                    tool=tool,
                    path=path,
                    field=None,
                    key=key,
                    loaded=loaded,
                    file_str=file_str,
                    ty_path=ty_path,
                    raw=raw,
                    show_secrets=show_secrets,
                )
        return lines
    origin = _origin_of(tool, "env")
    annotation = _annotate(
        origin,
        file=file_str,
        line=_origin_line(loaded, key, "env", origin),
        tool_yaml_path=ty_path,
    )
    rendered = "{}" if isinstance(value, Mapping) else _render_value(value)
    return [_padded(f"  env: {rendered}", annotation)]


def _mounts_block(
    *,
    key: str,
    tool: ResolvedTool,
    loaded: LoadedConfig,
    raw: dict[str, object],
    file_str: str,
    ty_path: str | None,
    verbose: bool,
    show_secrets: bool,
    config: ValidatedConfig,
) -> list[str]:
    """The ``mounts`` field: per entry, ``:ro`` default made explicit.

    Every entry renders ``<resolved_host>:<container>:<mode>`` with the
    mode ALWAYS shown (behaviour 17's :func:`parse_mount`, imported, not
    re-derived); a mode-less entry gets the pinned
    :data:`_MODE_DEFAULTED_NOTE` appended to its annotation after
    ``; ``.  An unparseable entry renders VERBATIM as authored with its
    origin and no note (the ``C540`` diagnostic on stderr says why).
    Entry order is the resolver's concatenation order — built-in first,
    inline LAST — and is never "fixed" into descending order.  An empty
    list prints ``mounts: []`` annotated ``built-in default``.

    Args:
        key: The ``tools:`` map key of the tool.
        tool: The resolved tool.
        loaded: The loaded config, for the root line map.
        raw: The raw root YAML mapping, for shadow value recovery.
        file_str: The config path as the user typed it.
        ty_path: The resolved ``tool.yaml`` path, or ``None``.
        verbose: Whether ``--verbose`` shadow lines are shown.
        show_secrets: Whether redaction is opted out (unused for mount
            entries; kept for the shared call shape).
        config: The validated config, for ``parse_mount``'s
            ``config_dir`` (the config file's directory) and ``home``.

    Returns:
        The mounts lines, without trailing newlines.
    """
    value = tool.values["mounts"]
    if not isinstance(value, list) or not value:
        origin = _origin_of(tool, "mounts")
        annotation = _annotate(
            origin,
            file=file_str,
            line=_origin_line(loaded, key, "mounts", origin),
            tool_yaml_path=ty_path,
        )
        rendered = "[]" if isinstance(value, list) else _render_value(value)
        return [_padded(f"  mounts: {rendered}", annotation)]
    lines: list[str] = ["  mounts:"]
    for index, entry in enumerate(value):
        path = f"mounts[{index}]"
        origin = _origin_of(tool, path)
        line = _origin_line(loaded, key, "mounts", origin)
        annotation = _annotate(origin, file=file_str, line=line, tool_yaml_path=ty_path)
        if isinstance(entry, str):
            parsed = parse_mount(entry, config_dir=config.path.parent, home=config.home)
            if parsed is not None:
                text = f"{parsed.resolved_host}:{parsed.container}:{parsed.mode}"
                if parsed.mode_defaulted:
                    annotation = f"{annotation}; {_MODE_DEFAULTED_NOTE}"
            else:
                text = entry
        else:
            text = _render_value(entry)
        lines.append(_padded(f"    - {text}", annotation))
        if verbose:
            lines += _shadow_lines(
                tool=tool,
                path=path,
                field=None,
                key=key,
                loaded=loaded,
                file_str=file_str,
                ty_path=ty_path,
                raw=raw,
                show_secrets=show_secrets,
            )
    return lines


def _tool_section(
    key: str,
    tool: ResolvedTool,
    *,
    loaded: LoadedConfig,
    raw: dict[str, object],
    file_str: str,
    verbose: bool,
    show_secrets: bool,
    config: ValidatedConfig,
) -> list[str]:
    """One tool section in the pinned order (plan item 3).

    The ``tool: <name>`` header (a bare ``<file>:<line>`` annotation,
    no level suffix), ``description`` (omitted when ``None``), the 30
    resolved fields in :data:`TOOL_FIELDS` order, then the
    ``tool.yaml`` carriers — ``inputs`` / ``outputs`` / ``params`` as a
    one-line count (singular at 1) and ``json_schema`` as
    ``present (passed through)`` — each omitted when absent.
    ``reserved_keys`` is never displayed.

    Args:
        key: The ``tools:`` map key of the tool.
        tool: The resolved tool.
        loaded: The loaded config.
        raw: The raw root YAML mapping, for shadow value recovery.
        file_str: The config path as the user typed it.
        verbose: Whether ``--verbose`` shadow lines are shown.
        show_secrets: Whether redaction is opted out.
        config: The validated config, for ``parse_mount``.

    Returns:
        The section's lines, without trailing newlines.
    """
    ty = loaded.tool_yaml(key)
    ty_path = str(ty[0]) if ty is not None else None
    lines: list[str] = []
    header_line = loaded.line_for(f"tools.{key}")
    header_annotation = (
        f"{file_str}:{header_line}" if header_line is not None else file_str
    )
    lines.append(_padded(f"tool: {key}", header_annotation))
    if tool.description is not None:
        origin = _origin_of(tool, "description")
        annotation = _annotate(
            origin,
            file=file_str,
            line=_origin_line(loaded, key, "description", origin),
            tool_yaml_path=ty_path,
        )
        lines.append(
            _padded(f"  description: {_render_value(tool.description)}", annotation)
        )
    for field in TOOL_FIELDS:
        if field == "env":
            lines += _env_block(
                key=key,
                tool=tool,
                loaded=loaded,
                raw=raw,
                file_str=file_str,
                ty_path=ty_path,
                verbose=verbose,
                show_secrets=show_secrets,
            )
            continue
        if field == "mounts":
            lines += _mounts_block(
                key=key,
                tool=tool,
                loaded=loaded,
                raw=raw,
                file_str=file_str,
                ty_path=ty_path,
                verbose=verbose,
                show_secrets=show_secrets,
                config=config,
            )
            continue
        value = tool.values[field]
        origin = _origin_of(tool, field)
        annotation = _annotate(
            origin,
            file=file_str,
            line=_origin_line(loaded, key, field, origin),
            tool_yaml_path=ty_path,
        )
        lines.append(_padded(f"  {field}: {_render_value(value)}", annotation))
        if verbose:
            lines += _shadow_lines(
                tool=tool,
                path=field,
                field=field,
                key=key,
                loaded=loaded,
                file_str=file_str,
                ty_path=ty_path,
                raw=raw,
                show_secrets=show_secrets,
            )
    for name, block in (
        ("inputs", tool.inputs),
        ("outputs", tool.outputs),
        ("params", tool.params),
    ):
        if block is None:
            continue
        origin = _origin_of(tool, name)
        annotation = _annotate(
            origin,
            file=file_str,
            line=_origin_line(loaded, key, name, origin),
            tool_yaml_path=ty_path,
        )
        count = len(block)
        rendered = f"{count} entries" if count != 1 else "1 entry"
        lines.append(_padded(f"  {name}: {rendered}", annotation))
    if tool.json_schema is not None:
        origin = _origin_of(tool, "json_schema")
        annotation = _annotate(
            origin,
            file=file_str,
            line=_origin_line(loaded, key, "json_schema", origin),
            tool_yaml_path=ty_path,
        )
        lines.append(_padded("  json_schema: present (passed through)", annotation))
    return lines


def _render_text(
    *, pipeline: Pipeline, tool: str | None, verbose: bool, show_secrets: bool
) -> str:
    """Render the whole resolved config as the pinned human text.

    Sections in order: ``router:``, ``backend:``, then the tool
    sections in config-declaration order with one blank line between
    (and only between) tool sections.  ``tswap config show <tool>``
    filters the tool sections only — the global blocks are still
    printed (plan item 4).  Ends with a single trailing newline.

    Args:
        pipeline: The shared pipeline result.
        tool: The requested tool name, or ``None`` for the whole file.
        verbose: Whether ``--verbose`` shadow lines are shown.
        show_secrets: Whether redaction is opted out.

    Returns:
        The complete stdout text.
    """
    loaded = pipeline.loaded
    validated = pipeline.config
    raw = validated.raw
    file_str = str(validated.path)
    lines: list[str] = []
    lines.append("router:")
    lines += _block_lines(raw, "router", ROUTER_FIELDS, loaded, file_str, show_secrets)
    lines.append("backend:")
    lines += _block_lines(
        raw, "backend", BACKEND_FIELDS, loaded, file_str, show_secrets
    )
    selected = [
        (key, t) for key, t in pipeline.tools.items() if tool is None or key == tool
    ]
    for index, (key, t) in enumerate(selected):
        if index > 0:
            lines.append("")
        lines += _tool_section(
            key,
            t,
            loaded=loaded,
            raw=raw,
            file_str=file_str,
            verbose=verbose,
            show_secrets=show_secrets,
            config=validated,
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The JSON view (plan item 8)
# ---------------------------------------------------------------------------


def _origin_object(
    tool: ResolvedTool, path: str, *, key: str, loaded: LoadedConfig
) -> dict[str, object]:
    """The structured ``{level, source, line}`` origin (never a phrase).

    ``level`` is ``OriginLevel.value`` verbatim; ``source`` the
    origin's source string; ``line`` the int or ``null``.

    Args:
        tool: The resolved tool.
        path: The origin-map path.
        key: The ``tools:`` map key of the tool.
        loaded: The loaded config, for the root line map.

    Returns:
        The structured origin object.
    """
    origin = _origin_of(tool, path)
    return {
        "level": origin.level.value,
        "source": origin.source,
        "line": _origin_line(loaded, key, path, origin),
    }


def _shadowed_object(
    tool: ResolvedTool,
    path: str,
    *,
    field: str | None,
    key: str,
    loaded: LoadedConfig,
    raw: dict[str, object],
    show_secrets: bool,
) -> list[dict[str, object]]:
    """The always-present ``shadowed`` list for one displayed value.

    The same entries the ``--verbose`` text view shows (recorded order,
    plus the synthesised built-in tail for flat fields), each as
    ``{"value", "origin"}``; a ``tool.yaml``-layer shadow carries
    ``null`` for its value (A25 — not looked up).  Secret values are
    redacted exactly as in the text view.  ``--verbose`` has no effect
    on the JSON: this list is always present, so the two forms are
    byte-identical with and without the flag (plan item 8).

    Args:
        tool: The resolved tool.
        path: The origin-map path.
        field: The flat built-in field name, or ``None`` for a
            per-entry path (no built-in tail).
        key: The ``tools:`` map key of the tool.
        loaded: The loaded config, for the root line map.
        raw: The raw root YAML mapping, for value recovery.
        show_secrets: Whether redaction is opted out.

    Returns:
        The shadowed entries, possibly an empty list.
    """
    try:
        shadows = tool.origins.shadowed(path)
    except KeyError:
        shadows = []
    entries: list[Origin] = list(shadows)
    winning = _origin_of(tool, path)
    if (
        field is not None
        and winning.level is not OriginLevel.BUILT_IN
        and field in BUILT_IN_DEFAULTS
    ):
        entries.append(Origin.built_in())
    out: list[dict[str, object]] = []
    for origin in entries:
        value = _shadow_value(origin, field=field, path=path, raw=raw)
        if path.startswith("env."):
            value = _redact(value, path.split(".", 1)[1], show_secrets=show_secrets)
        elif field is not None:
            value = _redact(value, field, show_secrets=show_secrets)
        out.append(
            {
                "value": value,
                "origin": {
                    "level": origin.level.value,
                    "source": origin.source,
                    "line": _origin_line(loaded, key, path, origin),
                },
            }
        )
    return out


def _block_object(
    raw: dict[str, object],
    block: str,
    fields: tuple[str, ...],
    loaded: LoadedConfig,
    path_str: str,
    show_secrets: bool,
) -> dict[str, object]:
    """The JSON half of one top-level ``router`` / ``backend`` block.

    Args:
        raw: The raw root YAML mapping.
        block: ``"router"`` or ``"backend"``.
        fields: The block's fields, in display order.
        loaded: The loaded config, for the root line map.
        path_str: The config path as the user typed it.
        show_secrets: Whether redaction is opted out.

    Returns:
        The block's ``{field: {value, origin}}`` mapping.
    """
    block_raw = raw.get(block)
    out: dict[str, object] = {}
    for field in fields:
        present = isinstance(block_raw, Mapping) and field in block_raw
        value = (
            block_raw[field]
            if isinstance(block_raw, Mapping) and field in block_raw
            else BUILT_IN_DEFAULTS[field]
        )
        value = _redact(value, field, show_secrets=show_secrets)
        if present:
            origin: dict[str, object] = {
                "level": block,
                "source": path_str,
                "line": loaded.line_for(f"{block}.{field}"),
            }
        else:
            origin = {
                "level": "built-in",
                "source": _BUILTIN_ANNOTATION,
                "line": None,
            }
        out[field] = {"value": value, "origin": origin}
    return out


def _tool_object(
    key: str,
    tool: ResolvedTool,
    *,
    loaded: LoadedConfig,
    raw: dict[str, object],
    path_str: str,
    show_secrets: bool,
    config: ValidatedConfig,
) -> dict[str, object]:
    """The JSON half of one tool section.

    Every field carries ``{value, origin, shadowed}`` in the pinned
    display order; ``env`` is a per-key mapping; ``mounts`` a list of
    ``{value, mode_defaulted, origin}``; the carriers carry the FULL
    blocks, not the count (plan item 7).

    Args:
        key: The ``tools:`` map key of the tool.
        tool: The resolved tool.
        loaded: The loaded config.
        raw: The raw root YAML mapping, for shadow value recovery.
        path_str: The config path as the user typed it.
        show_secrets: Whether redaction is opted out.
        config: The validated config, for ``parse_mount``.

    Returns:
        The tool's field mapping.
    """
    del path_str  # the tool-level origins carry their own source strings
    out: dict[str, object] = {}
    if tool.description is not None:
        out["description"] = {
            "value": tool.description,
            "origin": _origin_object(tool, "description", key=key, loaded=loaded),
        }
    for field in TOOL_FIELDS:
        if field == "env":
            value = tool.values["env"]
            if isinstance(value, Mapping) and value:
                env_obj: dict[str, object] = {}
                for env_key, env_value in value.items():
                    env_path = f"env.{env_key}"
                    env_obj[str(env_key)] = {
                        "value": _redact(
                            env_value, str(env_key), show_secrets=show_secrets
                        ),
                        "origin": _origin_object(
                            tool, env_path, key=key, loaded=loaded
                        ),
                        "shadowed": _shadowed_object(
                            tool,
                            env_path,
                            field=None,
                            key=key,
                            loaded=loaded,
                            raw=raw,
                            show_secrets=show_secrets,
                        ),
                    }
                out["env"] = env_obj
            else:
                out["env"] = {
                    "value": value,
                    "origin": _origin_object(tool, "env", key=key, loaded=loaded),
                    "shadowed": _shadowed_object(
                        tool,
                        "env",
                        field="env",
                        key=key,
                        loaded=loaded,
                        raw=raw,
                        show_secrets=show_secrets,
                    ),
                }
        elif field == "mounts":
            value = tool.values["mounts"]
            entries: list[dict[str, object]] = []
            if isinstance(value, list):
                for index, entry in enumerate(value):
                    entry_path = f"mounts[{index}]"
                    entry_value: object = entry
                    mode_defaulted: bool | None = None
                    if isinstance(entry, str):
                        parsed = parse_mount(
                            entry,
                            config_dir=config.path.parent,
                            home=config.home,
                        )
                        if parsed is not None:
                            mode_defaulted = parsed.mode_defaulted
                            entry_value = (
                                f"{parsed.resolved_host}:"
                                f"{parsed.container}:{parsed.mode}"
                            )
                    entries.append(
                        {
                            "value": entry_value,
                            "mode_defaulted": mode_defaulted,
                            "origin": _origin_object(
                                tool, entry_path, key=key, loaded=loaded
                            ),
                        }
                    )
            out["mounts"] = entries
        else:
            out[field] = {
                "value": _redact(tool.values[field], field, show_secrets=show_secrets),
                "origin": _origin_object(tool, field, key=key, loaded=loaded),
                "shadowed": _shadowed_object(
                    tool,
                    field,
                    field=field,
                    key=key,
                    loaded=loaded,
                    raw=raw,
                    show_secrets=show_secrets,
                ),
            }
    for name, block in (
        ("inputs", tool.inputs),
        ("outputs", tool.outputs),
        ("params", tool.params),
    ):
        if block is not None:
            out[name] = {
                "value": block,
                "origin": _origin_object(tool, name, key=key, loaded=loaded),
            }
    if tool.json_schema is not None:
        out["json_schema"] = {
            "value": tool.json_schema,
            "origin": _origin_object(tool, "json_schema", key=key, loaded=loaded),
        }
    return out


def _json_payload(
    *, pipeline: Pipeline, tool: str | None, show_secrets: bool
) -> dict[str, object]:
    """The ``{config, router, backend, tools}`` JSON envelope (item 8).

    Args:
        pipeline: The shared pipeline result.
        tool: The requested tool name, or ``None`` for the whole file.
        show_secrets: Whether redaction is opted out.

    Returns:
        The payload, in pinned display order (``sort_keys=False``).
    """
    validated = pipeline.config
    loaded = pipeline.loaded
    raw = validated.raw
    path_str = str(validated.path)
    tools_obj: dict[str, object] = {}
    for key, t in pipeline.tools.items():
        if tool is not None and key != tool:
            continue
        tools_obj[key] = _tool_object(
            key,
            t,
            loaded=loaded,
            raw=raw,
            path_str=path_str,
            show_secrets=show_secrets,
            config=validated,
        )
    return {
        "config": path_str,
        "router": _block_object(
            raw, "router", ROUTER_FIELDS, loaded, path_str, show_secrets
        ),
        "backend": _block_object(
            raw, "backend", BACKEND_FIELDS, loaded, path_str, show_secrets
        ),
        "tools": tools_obj,
    }


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------


config_app = typer.Typer(name="config", help="Inspect the effective configuration.")


@config_app.command("show")
def show(
    tool: Annotated[
        str | None, typer.Argument(metavar="TOOL", help="Show only this tool.")
    ] = None,
    config: Annotated[
        Path, typer.Option("--config", help="Config file to read.")
    ] = Path("tools.yaml"),
    env_file: Annotated[
        Path | None,
        typer.Option("--env-file", help="Env file, replacing .env discovery."),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="Also show the values each setting overrode."),
    ] = False,
    json_: Annotated[
        bool,
        typer.Option("--json", help="Emit the resolved config as JSON on stdout."),
    ] = False,
    show_secrets: Annotated[
        bool,
        typer.Option(
            "--show-secrets",
            help="Print secret values instead of ***. Local use only.",
        ),
    ] = False,
) -> None:
    """Show the fully-resolved effective configuration, value by value.

    Prints every value with its origin — the router and backend blocks
    once, as top-level raw blocks, then each tool's 30 resolved fields
    in fixed order with the ``tool.yaml`` carriers as counts.
    Diagnostics go to stderr and the resolved output stays on stdout
    even when the config has errors (exit 1), so ``tswap config show >
    snapshot.txt`` composes in a shell.
    """
    collected: list[Diagnostic] = []
    try:
        pipeline = run_pipeline(
            config, env=os.environ, env_file=env_file, collected=collected
        )
        tools = pipeline.tools
        if tool is not None and tool not in tools:
            _unknown_tool(tool, tools)
        # The per-tool filter reuses behaviour 21's shared helper, so
        # the two commands cannot disagree about what "restricted to one
        # tool" means.
        shown = list(pipeline.diagnostics)
        if tool is not None:
            shown = [d for d in shown if _implicates(d, tool)]
        report = ConfigReport(diagnostics=tuple(shown))
        failed = bool(report.errors)
        if json_:
            payload = _json_payload(
                pipeline=pipeline, tool=tool, show_secrets=show_secrets
            )
            typer.echo(json.dumps(payload, indent=2, sort_keys=False))
        else:
            typer.echo(
                _render_text(
                    pipeline=pipeline,
                    tool=tool,
                    verbose=verbose,
                    show_secrets=show_secrets,
                )
            )
        rendered = report.render()
        if rendered:
            typer.echo(rendered, err=True)
            error_count = len(report.errors)
            warning_count = len(report.warnings)
            typer.echo(
                f"{error_count} error(s), {warning_count} warning(s)"
                " — run 'tswap validate' for details",
                err=True,
            )
        raise typer.Exit(0 if not failed else 1)
    except ConfigError as exc:
        typer.echo(exc.report.render(), err=True)
        raise typer.Exit(2) from None
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001 — the last line of defence
        typer.echo(f"internal error while showing {config}: {exc}", err=True)
        if collected:
            typer.echo(
                "diagnostics gathered before the failure: "
                + ", ".join(sorted({d.code for d in collected})),
                err=True,
            )
        raise typer.Exit(2) from None

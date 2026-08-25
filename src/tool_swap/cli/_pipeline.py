"""The shared M1 configuration pipeline (behaviour 21b).

The load/resolve/validate call chain that the ``tswap validate`` command
runs, extracted verbatim so that ``tswap config show`` (behaviour 22) reuses
the exact same chain instead of a drifting copy — including the two-pass
group probe, the ``{**groups[gname], "name": gname}`` injection and the
discarded probe diagnostics (``plans/m1-configuration.md``, behaviour 22's
"Confirmed contract details (2026-08-20)", item 10).

The chain stops at the rule pass: schema compilation is a validation
concern the display command does not run, so ``validate`` adds
``_schema_diagnostics`` AFTER the call.  This module never catches: each
command keeps its own ``try``/``except ConfigError``/``except typer.Exit:
raise``/``except Exception`` guard, which owns the exit codes and the
"internal error while ..." message.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from tool_swap.config.errors import Diagnostic
from tool_swap.config.loader import LoadedConfig, load_config
from tool_swap.config.resolver import ResolvedTool, resolve_tool
from tool_swap.config.schema import validate_root
from tool_swap.config.validate import (
    ValidatedConfig,
    effective_groups,
    register_builtin_rules,
    validate_config,
)


@dataclass(frozen=True)
class Pipeline:
    """The result of the shared load/resolve/rule chain (behaviours 21b/22).

    A frozen container carrying everything the commands need to finish:
    the schema-layer step, the ``--allow-missing-descriptions`` downgrade,
    the per-tool filter and the report construction all read from it.

    Attributes:
        loaded: The loaded config (raw data, path echo, line map and the
            included ``tool.yaml`` layers).
        tools: The two-pass-resolved tools, in config-declaration order.
        config: The :class:`ValidatedConfig` the rule pass ran against.
        diagnostics: The loader + root-schema + resolver + rule-pass
            diagnostics, in collection order; the command appends the
            schema-layer diagnostics and sorts for the report.
    """

    loaded: LoadedConfig
    tools: dict[str, ResolvedTool]
    config: ValidatedConfig
    diagnostics: list[Diagnostic]


def _implicates(diagnostic: Diagnostic, tool: str) -> bool:
    """Whether a diagnostic is reported under ``tswap validate <tool>``.

    A pure yaml_path prefix test with a segment-boundary guard (A22): the
    path is ``tools.<tool>`` exactly or starts with ``tools.<tool>.``, so
    that ``validate app`` does not sweep up ``tools.app_v2``'s findings.  A
    ``None`` yaml_path (or a bare ``tools`` / ``groups.*`` path) is never
    implicated.

    Args:
        diagnostic: The diagnostic to test.
        tool: The requested tool name.

    Returns:
        True when the diagnostic's yaml_path names the tool (or a nested
        path under it), else False.
    """
    path = diagnostic.location.yaml_path
    if path is None:
        return False
    if path == f"tools.{tool}":
        return True
    return path.startswith(f"tools.{tool}.")


def run_pipeline(
    path: Path,
    *,
    env: Mapping[str, str],
    env_file: Path | None,
    collected: list[Diagnostic] | None = None,
) -> Pipeline:
    """Run the pinned call chain: register, load, root-check, resolve, rules.

    The chain is behaviour 21's item 1, lifted verbatim from the
    ``validate`` command: ``register_builtin_rules()`` first (once and
    idempotent, so every caller gets the same guarantee), ``load_config``
    with the given ``env``, ``validate_root`` before the resolver,
    ``resolve_tool`` twice per tool (the group-probe pass discards its
    diagnostics), then the ``ValidatedConfig`` and the rule pass.  It stops
    BEFORE the schema compiler: ``validate`` appends
    ``_schema_diagnostics`` after the call, and ``config show`` does not
    compile schemas at all.  No exception is caught here — the caller's
    guard owns the exit codes and the "internal error" message.

    Args:
        path: The config file path, passed through unresolved (the CLI
            echoes it as typed).
        env: The environment mapping for interpolation; the command reads
            ``os.environ`` exactly once and passes it here.
        env_file: Explicit env file, or ``None`` for auto-discovery.
        collected: If given, diagnostics are appended to this list in
            collection order as the chain progresses, so a caller whose
            ``try`` block wraps the call can still name the codes gathered
            before an unexpected failure (behaviour 21's item 13 codes
            line).  When ``None``, a fresh list is built internally.

    Returns:
        The :class:`Pipeline`; its ``diagnostics`` is the same list object
        as ``collected`` when one was given.

    Raises:
        ConfigError: From ``load_config`` for any of the C0xx fatal
            problems; the caller's ``except ConfigError`` handles it.
    """
    register_builtin_rules()
    if collected is None:
        collected = []
    loaded = load_config(path, env=env, env_file=env_file)
    collected += loaded.diagnostics
    collected += validate_root(loaded.data)

    raw = loaded.data
    groups = effective_groups(raw)
    defaults_raw = raw.get("defaults")
    defaults: dict[str, object] | None = (
        defaults_raw if isinstance(defaults_raw, dict) else None
    )
    tools: dict[str, ResolvedTool] = {}
    tools_raw = raw.get("tools")
    if isinstance(tools_raw, dict):
        for key, entry in tools_raw.items():
            # A non-mapping tool entry is reported by validate_root
            # (C104); the resolver is only called with a mapping.
            inline: dict[str, object] = entry
            layer = loaded.tool_yaml(key)
            tool_yaml = layer[1] if layer else None
            base_dir = layer[0].parent if layer else None
            probe = resolve_tool(
                key,
                inline=inline,
                tool_yaml=tool_yaml,
                defaults=defaults,
                base_dir=base_dir,
            )
            gname = probe.values["group"]
            gblock: dict[str, object] | None = None
            if isinstance(gname, str) and gname in groups:
                gblock = {**groups[gname], "name": gname}
            tools[key] = resolve_tool(
                key,
                inline=inline,
                tool_yaml=tool_yaml,
                defaults=defaults,
                group=gblock,
                base_dir=base_dir,
            )
            collected += tools[key].diagnostics

    validated = ValidatedConfig(
        tools=tools, raw=raw, line_for=loaded.line_for, path=path
    )
    collected += validate_config(validated).diagnostics
    return Pipeline(loaded=loaded, tools=tools, config=validated, diagnostics=collected)

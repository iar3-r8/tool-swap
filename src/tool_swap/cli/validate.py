"""The ``tswap validate`` CLI command (behaviour 21).

This module composes the whole M1 configuration pipeline into one
:class:`~tool_swap.config.errors.ConfigReport` and renders it per the pinned
contract (``plans/m1-configuration.md``, behaviour 21, "Confirmed contract
details (2026-08-20)").  The command is the ONLY layer that touches the
ambient environment: it reads ``os.environ`` exactly once and passes it down
to :func:`~tool_swap.config.loader.load_config`.  It never re-implements a
check — the five layers (loader, root schema, resolver, rules, schema
compiler) produce the diagnostics and the command concatenates them, applies
the ``--allow-missing-descriptions`` downgrade and the per-tool filter, then
decides the exit code.

The command body is the plain function :func:`validate`;
:mod:`tool_swap.cli.main` registers it on the shared ``typer.Typer`` app, so
the app (and the ``__main__`` re-export) stays the single registration point.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Final

import typer

from tool_swap.cli._pipeline import _implicates, run_pipeline
from tool_swap.config.errors import (
    ConfigError,
    ConfigReport,
    Diagnostic,
    Location,
    Severity,
)
from tool_swap.config.loader import LoadedConfig
from tool_swap.config.resolver import ResolvedTool
from tool_swap.config.suggest import nearest_alternative
from tool_swap.config.validate import (
    ValidatedConfig,
    downgrade_missing_descriptions,
)
from tool_swap.schema.compile import (
    SchemaDiagnostic,
    SchemaSeverity,
    compile_tool_schema,
    validate_against_metaschema,
)

#: The pinned command-level banner (plan item 11): printed once, first, on
#: stderr whenever ``--allow-missing-descriptions`` is present, whether or
#: not any diagnostic was actually downgraded — the flag being present is
#: what CI must not do.
_FLAG_BANNER: Final[str] = (
    "WARNING: --allow-missing-descriptions is for local prototyping "
    "and is never permitted in CI"
)


def _yaml_path(key: str, sd: SchemaDiagnostic) -> str:
    """Map a compiler diagnostic to the loader's dotted-numeric yaml_path.

    The exhaustive pinned table (plan item 2): block ``inputs``/``outputs``
    with an ``entry_index`` is ``tools.<key>.<block>.<i>``; the same block
    without an index is ``tools.<key>.<block>``; ``json_schema`` (any index)
    is ``tools.<key>.json_schema``; a ``None`` block is ``tools.<key>``.
    No ``.description`` suffix is appended: the entry itself is the honest
    location.

    Args:
        key: The ``tools:`` map key of the tool.
        sd: The compiler diagnostic to locate.

    Returns:
        The dotted yaml_path for the diagnostic's location.
    """
    if sd.block is None:
        return f"tools.{key}"
    if sd.block == "json_schema":
        return f"tools.{key}.json_schema"
    if sd.entry_index is not None:
        return f"tools.{key}.{sd.block}.{sd.entry_index}"
    return f"tools.{key}.{sd.block}"


def to_diagnostic(
    sd: SchemaDiagnostic, *, file: str, yaml_path: str, line: int | None
) -> Diagnostic:
    """Convert a compiler :class:`SchemaDiagnostic` into a located Diagnostic.

    ``code``, ``message`` and ``remedy`` are carried verbatim (the compiler
    already wrote an actionable sentence).  The severity is the one-to-two-arm
    enum map (``SchemaSeverity.ERROR`` -> ``Severity.ERROR``, else WARNING);
    the location carries the ROOT config path, the dotted yaml_path and the
    line from ``config.line_for``.

    Args:
        sd: The compiler diagnostic.
        file: The root config path, echoed into the location.
        yaml_path: The dotted YAML path for the location.
        line: The 1-based source line, or ``None``.

    Returns:
        The located config-layer :class:`Diagnostic`.
    """
    severity = (
        Severity.ERROR if sd.severity is SchemaSeverity.ERROR else Severity.WARNING
    )
    return Diagnostic(
        code=sd.code,
        severity=severity,
        message=sd.message,
        location=Location(file=file, yaml_path=yaml_path, line=line),
        remedy=sd.remedy,
    )


def _schema_diagnostics(
    config: ValidatedConfig, loaded: LoadedConfig
) -> list[Diagnostic]:
    """Compile and meta-validate every tool's schema, as Diagnostics.

    For each tool (in ``config.tools`` order) the schema is compiled first,
    then every non-``None`` half (compiled AND passed-through) is checked
    against the JSON Schema 2020-12 meta-schema, back-filling the ``block``
    the standalone meta-validator cannot know (``replace(sd, block=sd.block
    or block)``).  Every resulting :class:`SchemaDiagnostic` is converted via
    :func:`to_diagnostic` with the root config path, the dotted yaml_path and
    ``config.line_for``.

    Args:
        config: The resolved configuration; provides the schema carriers
            (``inputs``/``outputs``/``params``/``json_schema``) and
            ``line_for``/``path`` for the locations.
        loaded: The loaded config; part of the pinned seam (a future
            per-tool path improvement reads the ``tool.yaml`` path from
            here).  Unused in the current body.

    Returns:
        All schema-layer diagnostics, in tool-then-emission order (the
        report sorts them at rest).
    """
    out: list[Diagnostic] = []
    # The loaded argument is part of the pinned seam signature (item 4);
    # reference it so the parameter is not flagged unused.
    _ = loaded
    for key, tool in config.tools.items():
        compiled = compile_tool_schema(
            inputs=tool.inputs,
            outputs=tool.outputs,
            params=tool.params,
            json_schema=tool.json_schema,
        )
        sds: list[SchemaDiagnostic] = list(compiled.diagnostics)
        for half, block in (
            (compiled.inputs, "inputs"),
            (compiled.outputs, "outputs"),
        ):
            if half is not None:
                sds += [
                    replace(sd, block=sd.block or block)
                    for sd in validate_against_metaschema(half)
                ]
        out += [
            to_diagnostic(
                sd,
                file=str(config.path),
                yaml_path=_yaml_path(key, sd),
                line=config.line_for(_yaml_path(key, sd)),
            )
            for sd in sds
        ]
    return out


def _unknown_tool(tool: str, tools: dict[str, ResolvedTool]) -> None:
    """Report an unknown tool name (a usage error, not a config finding).

    Prints the nearest-name suggestion (or the list of defined tools when
    nothing is close) on stderr and exits 1.  It carries NO TSWAP- code: the
    config may be perfect and the *command line* is wrong.

    Args:
        tool: The unknown tool name as typed.
        tools: The resolved tools; its keys are the defined tool names.

    Raises:
        typer.Exit: With exit code 1, after printing the error line.
    """
    candidates = sorted(tools)
    suggestion = nearest_alternative(tool, candidates)
    if suggestion is not None:
        line = f"error: unknown tool '{tool}'; did you mean '{suggestion}'?"
    else:
        names = ", ".join(f"'{name}'" for name in candidates)
        line = f"error: unknown tool '{tool}'; defined tools are: {names}"
    typer.echo(line, err=True)
    raise typer.Exit(1)


def _note(hidden: int, path_str: str, tool: str) -> str:
    """The "elsewhere" note pointing at the whole-file run (plan item 6)."""
    return (
        f"note: {hidden} diagnostic(s) elsewhere in {path_str} "
        f"are not shown by 'tswap validate {tool}'; "
        "run 'tswap validate' for the whole file"
    )


def _ok_line(path_str: str, tool_count: int, warning_count: int) -> str:
    """The success line: ``OK <file> — <n> tools, ...`` (a real em-dash)."""
    if warning_count == 0:
        return f"OK {path_str} — {tool_count} tools, no problems found"
    return f"OK {path_str} — {tool_count} tools, {warning_count} warning(s)"


def _render_report(shown_report: ConfigReport) -> None:
    """Print the report's diagnostic blocks on stderr, if any (no summary).

    ``render()`` emits the blocks and a trailing newline (and ``""`` for an
    empty report); the summary line, when due, is composed by the caller.
    """
    rendered = shown_report.render()
    if rendered:
        typer.echo(rendered, err=True)


def _emit_failure_summary(error_count: int, warning_count: int, strict: bool) -> None:
    """Print the summary line on stderr, with the strict clause if due.

    ``<e> error(s), <w> warning(s)``; under ``--strict`` with zero errors
    the pinned ``— failing due to --strict`` clause is appended (the failure
    is caused by the gate, and no error is fabricated).
    """
    summary = f"{error_count} error(s), {warning_count} warning(s)"
    if strict and error_count == 0:
        summary += " — failing due to --strict"
    typer.echo(summary, err=True)


def _emit(
    *,
    shown_report: ConfigReport,
    failed: bool,
    strict: bool,
    error_count: int,
    warning_count: int,
    path_str: str,
    tool_count: int,
    banner: bool,
    note: str | None,
    as_json: bool,
) -> None:
    """Render the report per the pinned four-string contract.

    The banner (if ``banner``) is always the FIRST line on stderr.  In JSON
    mode the filtered report's ``to_json()`` is the sole stdout content and
    every human line (diagnostics, summary, success line) goes to stderr;
    otherwise the success line goes to stdout, the rendered diagnostics to
    stderr — on the success path the warnings are rendered so they stay
    visible — and the summary line goes to stderr on failure.  The
    "elsewhere" note (if any) is appended to stderr in both modes.

    Args:
        shown_report: The (possibly tool-filtered) report to render.
        failed: Whether the exit decision is a failure.
        strict: Whether ``--strict`` is on (controls the summary clause).
        error_count: Number of ERROR diagnostics in the shown set.
        warning_count: Number of WARNING diagnostics in the shown set.
        path_str: The config path as typed, for the ``<file>`` in the output.
        tool_count: The ``<n>`` for the success line: 1 when a single tool
            is requested, else the whole-file tool count.
        banner: Whether to print the never-in-CI banner first.
        note: The "elsewhere" note line, or ``None``.
        as_json: Whether to emit JSON on stdout.
    """
    if banner:
        typer.echo(_FLAG_BANNER, err=True)

    if as_json:
        typer.echo(shown_report.to_json())
        if failed:
            _render_report(shown_report)
            _emit_failure_summary(error_count, warning_count, strict)
        else:
            typer.echo(_ok_line(path_str, tool_count, warning_count), err=True)
    elif failed:
        _render_report(shown_report)
        _emit_failure_summary(error_count, warning_count, strict)
    else:
        _render_report(shown_report)  # warnings (if any) stay visible
        typer.echo(_ok_line(path_str, tool_count, warning_count))

    if note is not None:
        typer.echo(note, err=True)


def validate(
    tool: Annotated[
        str | None,
        typer.Argument(metavar="TOOL", help="Validate only this tool."),
    ] = None,
    config: Annotated[
        Path, typer.Option("--config", help="Config file to read.")
    ] = Path("tools.yaml"),
    env_file: Annotated[
        Path | None,
        typer.Option("--env-file", help="Env file, replacing .env discovery."),
    ] = None,
    all_: Annotated[
        bool, typer.Option("--all", help="Validate every tool (the default).")
    ] = False,
    strict: Annotated[
        bool, typer.Option("--strict", help="Treat warnings as errors.")
    ] = False,
    json_: Annotated[
        bool, typer.Option("--json", help="Emit the report as JSON on stdout.")
    ] = False,
    allow_missing_descriptions: Annotated[
        bool,
        typer.Option(
            "--allow-missing-descriptions",
            help="Downgrade missing-description errors. "
            "Local prototyping only; never in CI.",
        ),
    ] = False,
) -> None:
    """Validate a tool-swap config file.

    Loads, resolves and validates the WHOLE config (cross-tool rules cannot
    run otherwise), then reports every diagnostic — or, under ``tswap
    validate <tool>``, only that tool's.  Diagnostics go to stderr, the
    success line to stdout, so ``tswap validate && deploy`` composes in a
    shell.
    """
    if all_ and tool is not None:
        typer.echo("error: --all cannot be combined with a tool name", err=True)
        raise typer.Exit(2)

    collected: list[Diagnostic] = []
    try:
        pipeline = run_pipeline(
            config, env=os.environ, env_file=env_file, collected=collected
        )
        loaded = pipeline.loaded
        tools = pipeline.tools
        validated = pipeline.config
        # The shared chain stops at the rule pass; the schema-layer step is
        # a validation concern kept in this module (behaviour 21b, plan item
        # 10) and is appended AFTER the pipeline call.
        collected += _schema_diagnostics(validated, loaded)
        report = ConfigReport(diagnostics=tuple(sorted(collected)))

        if allow_missing_descriptions:
            report = downgrade_missing_descriptions(report)

        if tool is not None and tool not in tools:
            _unknown_tool(tool, tools)

        if tool is None:
            shown = list(report.diagnostics)
            hidden = 0
        else:
            shown = [d for d in report.diagnostics if _implicates(d, tool)]
            hidden = len(report.diagnostics) - len(shown)

        errors = [d for d in shown if d.severity is Severity.ERROR]
        warnings = [d for d in shown if d.severity is Severity.WARNING]
        failed = bool(errors) or (strict and bool(warnings))
        shown_report = ConfigReport(diagnostics=tuple(shown))
        note: str | None = None
        if tool is not None and hidden > 0:
            note = _note(hidden, str(config), tool)
        _emit(
            shown_report=shown_report,
            failed=failed,
            strict=strict,
            error_count=len(errors),
            warning_count=len(warnings),
            path_str=str(config),
            tool_count=1 if tool is not None else len(tools),
            banner=allow_missing_descriptions,
            note=note,
            as_json=json_,
        )
        raise typer.Exit(0 if not failed else 1)
    except ConfigError as exc:
        typer.echo(exc.report.render(), err=True)
        raise typer.Exit(2) from None
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001 — the last line of defence
        typer.echo(f"internal error while validating {config}: {exc}", err=True)
        if collected:
            typer.echo(
                "diagnostics gathered before the failure: "
                + ", ".join(sorted({d.code for d in collected})),
                err=True,
            )
        raise typer.Exit(2) from None

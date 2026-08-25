"""Typer application for the ``tswap`` CLI.

The app, its no-subcommand callback and the ``version`` command live here;
the ``validate`` command body lives in :mod:`tool_swap.cli.validate` and is
registered on this same app below; the ``config`` sub-group is defined
in :mod:`tool_swap.cli.config_show` and added below.  ``tool_swap.__main__``
re-exports ``app`` and ``main`` so the ``python -m tool_swap`` and ``tswap``
entry points keep pointing at the same object.
"""

from __future__ import annotations

import typer

from tool_swap.cli.config_show import config_app
from tool_swap.cli.validate import validate as _validate

app = typer.Typer(
    name="tswap",
    help="tswap — router CLI for managing AI agent tool contexts.\n\n"
    "Commands: version    Print the tool-swap version.\n"
    "         validate   Validate a tool-swap config file.\n"
    "         config     Inspect the effective configuration.",
)


@app.callback(invoke_without_command=True)
def cli(ctx: typer.Context) -> None:
    """Tool-swap router CLI for managing AI agent tool contexts."""
    if ctx is not None and ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise SystemExit(0)


@app.command()
def version() -> None:
    """Print the tool-swap version."""
    from tool_swap import __version__

    print(__version__)


# The command body, its flags and its help strings are defined in
# tool_swap/cli/validate.py; registering the function here (rather than
# decorating it there) keeps this app the single registration point and
# avoids an import cycle back to this module.
app.command()(_validate)

# The ``config`` sub-group (behaviour 22) is constructed in
# tool_swap/cli/config_show.py — ``config show`` is its ``show``
# command — and added here, keeping this app the single
# registration point.
app.add_typer(config_app, name="config")


def main() -> None:
    """CLI entry point."""
    app()

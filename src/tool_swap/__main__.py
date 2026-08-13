"""Minimal CLI entry point for tool-swap using typer."""

import typer

# Disable rich formatting / pretty exceptions to prevent ANSI escape
# sequences in help output (test_cli.py:TestHelpFlag.test_help_no_color_codes).
# Typer uses rich for rendering; disabling pretty_exceptions also removes
# colored formatting from help text rendering.
app = typer.Typer(
    name="tswap",
    help="tswap — router CLI for managing AI agent tool contexts.\n\n"
    "Commands: version   Print the tool-swap version.",
    pretty_exceptions_enable=False,
    pretty_exceptions_short=False,
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


def main() -> None:
    """CLI entry point."""
    app()


if __name__ == "__main__":
    main()

"""Minimal CLI entry point for tool-swap using typer."""

import typer

app = typer.Typer(
    name="tswap",
    help="tswap — router CLI for managing AI agent tool contexts.\n\n"
    "Commands: version   Print the tool-swap version.",
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

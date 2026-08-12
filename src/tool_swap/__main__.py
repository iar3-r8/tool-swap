"""Minimal CLI entry point for tool-swap using typer."""

import typer

app = typer.Typer(
    name="tswap",
    help="Tool-swap router CLI for managing AI agent tool contexts.",
)


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

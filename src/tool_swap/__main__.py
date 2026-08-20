"""Minimal CLI entry point for tool-swap using typer."""

from tool_swap.cli.main import app, main  # noqa: F401  (re-export)

if __name__ == "__main__":
    main()

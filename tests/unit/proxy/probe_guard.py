"""AST detector for the no-HTTP-import guard over
``src/tool_swap/proxy/probes.py`` (m2b plan §3 behaviour 9, §5 D-B).

Pure functions over an ``ast.Module``, driven by the in-memory decoys in
``test_probes.py``.  The detector scans the source for *written* import
forms — ``import x``, ``from x import y`` and ``__import__("x")`` —
because D-B forbids an HTTP dependency in the module, not merely one
that happens to execute.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repository root
PROBES_PATH = ROOT / "src" / "tool_swap" / "proxy" / "probes.py"

#: The HTTP libraries forbidden in probes.py; none is a declared
#: dependency of tool-swap (pyproject.toml).
HTTP_MODULES: frozenset[str] = frozenset({"requests", "httpx", "urllib3", "aiohttp"})


def probes_source() -> str:
    """The source text of probes.py, read-only.

    The guard's primary subject; the caller gates on the file's
    existence first, so a missing file fails informatively rather than
    as an uncaught FileNotFoundError.
    """
    return PROBES_PATH.read_text(encoding="utf-8")


def _top_level(module_name: str) -> str:
    """The top-level package of a (possibly dotted) module name."""
    return module_name.split(".")[0]


def _message(lineno: int, name: str) -> str:
    return (
        f"line {lineno}: imports {name!r} — an HTTP library probes.py "
        "must not import: the probe is a seam with no client (m2b plan "
        "§5 D-B)"
    )


def http_import_messages(tree: ast.Module) -> list[str]:
    """One message per forbidden HTTP import in *tree*, with its line.

    Flags ``import requests``, ``import urllib3.util``,
    ``from httpx import AsyncClient`` and ``__import__("aiohttp")``.
    Matching is on the exact top-level module name, so ``urllib.parse``
    and ``requests_mock`` are not flagged.
    """
    messages: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = _top_level(alias.name)
                if top in HTTP_MODULES:
                    messages.append(_message(node.lineno, top))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = _top_level(node.module)
                if top in HTTP_MODULES:
                    messages.append(_message(node.lineno, top))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "__import__"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and _top_level(node.args[0].value) in HTTP_MODULES
        ):
            messages.append(_message(node.lineno, _top_level(node.args[0].value)))
    return messages

"""AST detectors for the spec-builder boundary guards (m2b plan §3, §6.3).

Pure functions over an ``ast.Module`` or ``(filename, source)`` pairs,
driven by the in-memory decoys in ``test_spec_builder_guards.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repository root
LIFECYCLE_DIR = ROOT / "src" / "tool_swap" / "lifecycle"

#: The separator every mount-string parser in this repository splits on.
SEPARATOR = ":"

#: The four keys the spec builder consumes from BackendConfig; all four
#: are present-but-wrong in ResolvedTool.values (m2b plan §6.3).
BACKEND_KEYS: frozenset[str] = frozenset(
    {"network", "container_prefix", "label_namespace", "gpu_runtime"}
)


def lifecycle_py_files() -> list[Path]:
    """Every ``.py`` file under the lifecycle package, in sorted order.

    ``__pycache__`` is excluded so a stale bytecode copy of any module
    cannot trip the guard (and the guard never reads generated artifacts).
    """
    return sorted(
        p for p in LIFECYCLE_DIR.rglob("*.py") if "__pycache__" not in p.parts
    )


def spec_builder_source() -> str:
    """The source text of the config-to-spec builder, read-only.

    The guard's primary subject; if the file moved, the subject-exists
    test fails on the walk instead of the detector passing against a
    vacuum.
    """
    return (LIFECYCLE_DIR / "spec_builder.py").read_text(encoding="utf-8")


def _first_arg_is_separator(node: ast.Call) -> bool:
    """True iff the first positional argument is the literal ``":"``.

    Only the FIRST positional argument counts: for ``split`` /
    ``partition`` / ``re.split`` it is the separator, and a later
    argument or a keyword carrying ``":"`` is not the idiom.
    """
    if not node.args:
        return False
    first = node.args[0]
    return (
        isinstance(first, ast.Constant)
        and isinstance(first.value, str)
        and first.value == SEPARATOR
    )


def _is_split_like_call(node: ast.Call) -> bool:
    """True for ``x.split(...)`` / ``x.partition(...)`` / ``re.split(...)``.

    ``re.split`` matches because its function is the ``Attribute`` node
    ``re.split`` (same shape as ``x.split``); a bare ``split`` with no
    receiver is not mount parsing and is not flagged.
    """
    return isinstance(node.func, ast.Attribute) and node.func.attr in (
        "split",
        "partition",
        "rpartition",
    )


def mount_split_messages(tree: ast.Module) -> list[str]:
    """One message per mount-splitting construct in *tree*, with its line.

    Flags a ``split`` / ``partition`` / ``rpartition`` call, or a
    ``re.split`` call, whose first positional argument is the literal
    ``":"``.  A ``parse_mount`` call is not a split and is not flagged.
    """
    messages: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _is_split_like_call(node) and _first_arg_is_separator(node):
            messages.append(
                f"line {node.lineno}: {ast.unparse(node)} splits on "
                f"the mount separator — mount-string parsing belongs "
                f"exclusively to tool_swap.config.validate.parse_mount"
            )
    return messages


def _parse_mount_defs(tree: ast.Module) -> list[tuple[int, str]]:
    """(lineno, name) of each callable in *tree* defined as parse_mount.

    A call to the legitimate config-layer parser is not an offender;
    only a definition is.
    """
    return [
        (node.lineno, node.name)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "parse_mount"
    ]


def parse_mount_name_offenders(tree: ast.Module) -> list[str]:
    """Names of callables defined in *tree* that are called parse_mount."""
    return [name for _, name in _parse_mount_defs(tree)]


def scan_mount_violations(
    sources: list[tuple[str, str]],
) -> dict[str, list[str]]:
    """Mount-split and parse_mount-name violations per (filename, source).

    The filename is the mapping key; each message carries its line, so
    a violation names both the offending file and line.
    """
    violations: dict[str, list[str]] = {}
    for filename, source in sources:
        tree = ast.parse(source, filename=filename)
        messages = mount_split_messages(tree)
        messages.extend(
            f"line {lineno}: defines {name} — a second mount parser "
            f"under src/tool_swap/lifecycle/ (mount-string parsing "
            f"belongs to tool_swap.config.validate.parse_mount)"
            for lineno, name in _parse_mount_defs(tree)
        )
        if messages:
            violations[filename] = messages
    return violations


def _values_read_offenders(tree: ast.Module) -> list[tuple[int, str]]:
    """(lineno, key) of each backend-named read out of a .values mapping.

    Only the attribute form ``x.values[key]`` counts: a bare local
    named ``values`` is a Subscript over a Name, not an Attribute, and
    tool-level keys are not in BACKEND_KEYS.
    """
    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        target = node.value
        if not (isinstance(target, ast.Attribute) and target.attr == "values"):
            continue
        key = node.slice
        if (
            isinstance(key, ast.Constant)
            and isinstance(key.value, str)
            and key.value in BACKEND_KEYS
        ):
            offenders.append((node.lineno, key.value))
    return offenders


def scan_values_reads(
    sources: list[tuple[str, str]],
) -> dict[str, list[str]]:
    """Backend-named .values reads per (filename, source), keyed by file.

    The four BACKEND_KEYS are present-but-wrong in ResolvedTool.values;
    tool-level keys (container_port, mounts, ...) are legitimate reads
    the builder makes and must not be flagged.
    """
    violations: dict[str, list[str]] = {}
    for filename, source in sources:
        tree = ast.parse(source, filename=filename)
        messages = [
            f"line {lineno}: reads backend-named key {key!r} out of "
            f"ResolvedTool.values — the backend-named values come from "
            f"BackendConfig, never from resolved.values"
            for lineno, key in _values_read_offenders(tree)
        ]
        if messages:
            violations[filename] = messages
    return violations

"""RED step for M2a behaviour 3 — the mount-parsing ownership boundary.

See ``plans/m2a-container-backend-seam.md`` §4.2 and behaviour 3 (§5,
**amended**): the repository has exactly ONE mount-string parser,
``tool_swap.config.validate.parse_mount``, and no module under
``src/tool_swap/backend/`` may split a mount string.  The amended
behaviour deliberately ships no backend-side ``parse_mount``; an
earlier draft of behaviour 3 would have added a second, subtly
different parser, and two parsers disagreeing about whether ``"RO"``
is a valid mode is how an author's intended read-only mount silently
becomes read-write (``TSWAP-C541`` is the only rule that may judge
modes).

The guard is a **source/AST-level test over the package directory**:
it walks every ``.py`` file under ``src/tool_swap/backend/`` —
including modules a *later* branch adds (``fake_backend.py``,
``docker_backend.py``) — and hardcodes no module list.  The walk is
strictly read-only: this test file writes nothing anywhere under
``src/``.

**What the splitting detector catches, and by deliberate choice does
not:**

It pins the concrete AST shape a mount-string parser has: a ``split``
/ ``partition`` / ``rpartition`` call, or a ``re.split`` call, whose
FIRST positional argument is the string literal ``":"`` —
``entry.split(":")``, ``entry.partition(":")``, ``re.split(":",
entry)``.  For every one of those calls the separator is the first
positional argument, so the detector checks exactly that slot and
nothing else.  The first form is the shape of the config-layer
parser; the regex variant is the shape a "simplified" second parser
most plausibly drifts into, and it is the one that can re-introduce
the exact ``"RO"`` disagreement this amendment removes.

It deliberately does **not** flag: a bare occurrence of the character
``":"`` (type annotations, dict literals, ``"key: value"`` docstrings);
splits on other separators (whitespace, ``"="``, commas); or
``split("::")`` / ``split(":" * 2)`` — non-literal separators.  Those
are other operations, not mount-string parsing; the detector is a
boundary tripwire for the specific idiom, not a static analyser of
all colon usage.  (Behaviour 1's guard on this branch was written
over-broad and tripped on a legitimate path; this one is the exact
shape, no wider.)

**Why the test is not vacuous:** the package currently contains only
``__init__.py`` (a docstring), so the walk-based assertion would
otherwise pass against nothing.  The detector helpers are pure
functions over an ``ast.Module``, so the non-vacuity proof feeds them
in-memory decoys — string constants parsed with ``ast.parse``, never
written to disk.  The decoys are one violation shape each, mirroring
the very duplicate parser the amendment removed, and one benign
module whose colons must *not* be flagged: reach and precision are
both proven without touching the production tree.  The subject-
exists test separately pins that the walked directory exists and
contains ``__init__.py``, so the walk never runs against a vacuum.

``__pycache__`` is skipped: a stale bytecode copy of any module must
not trip the guard (and the guard never reads generated artifacts).
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repository root
BACKEND_DIR = ROOT / "src" / "tool_swap" / "backend"

#: The separator every mount-string parser in this repository splits on.
SEPARATOR = ":"

#: DECOY — the very duplicate parser the behaviour-3 amendment removed.
_DECOY_PARSE_MOUNT = '''\
def parse_mount(entry: str) -> tuple[str, str]:
    """DECOY: the second mount parser behaviour 3 must never ship."""
    parts = entry.split(":")
    return parts[0], parts[1]
'''

#: DECOY — a regex variant of the mount-string split.
_DECOY_RE_SPLIT = '''\
def reparse(entry: str) -> list[str]:
    """DECOY: a regex variant of the mount-string split."""
    import re

    return re.split(":", entry)
'''

#: BENIGN — colons that must NOT be flagged: a docstring colon, a
#: dict-literal key, and a split on a different separator.
_BENIGN_MODULE = '''\
"""Docstring with a colon: and other benign punctuation."""

SEPARATORS = {":": "colon", "-": "dash"}


def split_fields(entry: str) -> list[str]:
    """Split on whitespace — not on the mount separator."""
    return entry.split(" ")
'''


def _backend_py_files() -> list[Path]:
    """Every ``.py`` file under the backend package, in sorted order.

    ``__pycache__`` is excluded so a stale bytecode copy of any module
    cannot trip the guard (and so the guard never reads generated
    artifacts).
    """
    return sorted(p for p in BACKEND_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def _violation_messages(tree: ast.Module) -> list[str]:
    """Return one message per mount-splitting construct in *tree*.

    Flags a ``split`` / ``partition`` / ``rpartition`` call, or a
    ``re.split`` call, whose first positional argument is the literal
    string ``":"``.
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


def _is_split_like_call(node: ast.Call) -> bool:
    """True for ``x.split(...)`` / ``x.partition(...)`` / ``re.split(...)``.

    ``re.split`` matches because its function is the ``Attribute``
    node ``re.split`` (same shape as ``x.split``); a bare ``split``
    with no receiver is not mount parsing and is not flagged.
    """
    return isinstance(node.func, ast.Attribute) and node.func.attr in (
        "split",
        "partition",
        "rpartition",
    )


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


def _parse_mount_name_offenders(tree: ast.Module) -> list[str]:
    """Names of callables defined in *tree* that are called ``parse_mount``."""
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "parse_mount"
    ]


# ---------------------------------------------------------------------------
# Subject-exists check (not a detector proof — those follow)
# ---------------------------------------------------------------------------


def test_backend_package_directory_exists_with_init() -> None:
    """The walked package directory exists and contains ``__init__.py``.

    A guard that asserts over a missing or empty directory proves
    nothing: if ``src/tool_swap/backend/`` disappeared, or contained
    no ``.py`` file at all, the walk would find zero modules and the
    other tests would pass against a vacuum.  ``__init__.py`` is the
    minimal real content; anything less means the guard has lost its
    subject.  This is a subject-exists check; the detector
    non-vacuity proofs are the in-memory-decoy tests below.
    """
    # Assert — existence
    assert BACKEND_DIR.is_dir(), (
        f"Guard subject missing: {BACKEND_DIR} — the boundary guard "
        "would pass vacuously."
    )
    # Assert — minimal content
    files = _backend_py_files()
    assert files, (
        f"No .py files under {BACKEND_DIR} — the boundary guard would pass vacuously."
    )
    assert any(p.name == "__init__.py" for p in files), (
        f"{BACKEND_DIR} lost its __init__.py — the backend package is "
        "no longer a package the guard can reason about."
    )


# ---------------------------------------------------------------------------
# Detector non-vacuity — in-memory decoys, nothing written to src/
# ---------------------------------------------------------------------------


def test_split_detector_reports_decoy_mount_splitters() -> None:
    """The splitting detector flags every violation shape it must catch.

    Reach side of the non-vacuity proof: one in-memory decoy per
    violation shape — mirroring the very duplicate parser the
    amendment removed — must each be reported.  The decoys are
    string constants parsed with ``ast.parse``; nothing is written
    to disk, so the test cannot leave artefacts under ``src/``.
    """
    # Arrange — decoys: the idiom and its regex drift
    decoys = {
        "entry.split(':')": _DECOY_PARSE_MOUNT,
        "re.split(':', entry)": _DECOY_RE_SPLIT,
    }
    # Act / Assert — each decoy is reported
    for label, source in decoys.items():
        messages = _violation_messages(ast.parse(source))
        assert messages, (
            "Guard is blind to a decoy mount split: "
            f"{label!r} was parsed but no violation was reported."
        )


def test_split_detector_ignores_non_mount_colon_usage() -> None:
    """The splitting detector does not flag bare ``":"`` or other separators.

    Precision side of the non-vacuity proof: a module whose colons
    are docstring content or dict keys, and which splits on a
    different separator, is a different operation, not
    mount-string parsing, and must produce no violation.  Without
    this, the reach test above could be satisfied by a detector
    that flags everything.
    """
    # Arrange — benign module: colons, but never the mount-split idiom
    tree = ast.parse(_BENIGN_MODULE)
    # Act
    messages = _violation_messages(tree)
    # Assert
    assert not messages, f"False positive on benign module: {messages}"


def test_parse_mount_name_detector_reports_decoy_definition() -> None:
    """The name detector finds ``parse_mount`` in a decoy module.

    Non-vacuity of the name check: the very function the amended
    behaviour forbids, defined in an in-memory decoy, must be found
    by the same walk the real-package check performs.
    """
    # Arrange — decoy: the function the amended behaviour forbids
    tree = ast.parse(_DECOY_PARSE_MOUNT)
    # Act
    offenders = _parse_mount_name_offenders(tree)
    # Assert — the decoy is seen, so a real one would be too
    assert offenders, (
        "Guard is blind: the decoy module defines parse_mount but the "
        "detector found nothing."
    )


# ---------------------------------------------------------------------------
# The walk over the real package — strictly read-only
# ---------------------------------------------------------------------------


def test_no_backend_module_defines_parse_mount() -> None:
    """No module under the backend package names a callable ``parse_mount``.

    ``tool_swap.config.validate.parse_mount`` is the repository's only
    mount-string parser; a same-named callable in the backend is the
    duplicate the behaviour-3 amendment removed.  The walk is read-
    only over the real package directory; the detector itself is
    proven on an in-memory decoy by
    ``test_parse_mount_name_detector_reports_decoy_definition``.
    """
    # Act
    offenders: dict[str, list[str]] = {}
    for path in _backend_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        named = _parse_mount_name_offenders(tree)
        if named:
            offenders[path.name] = named
    # Assert
    assert not offenders, (
        f"backend module defines a callable named parse_mount: "
        f"{offenders} — parsing mount strings belongs exclusively to "
        "tool_swap.config.validate.parse_mount (plan §4.2)."
    )


def test_no_backend_module_splits_a_mount_string() -> None:
    """No module under the backend package splits a mount string.

    The detector pins the AST shape of a mount-string parser — a
    ``split`` / ``partition`` / ``re.split`` call with the literal
    separator ``":"`` — and nothing wider.  The walk is read-only
    over the real package directory; the detector's reach and
    precision are proven separately on in-memory decoys.
    """
    # Act
    violations: dict[str, list[str]] = {}
    for path in _backend_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        messages = _violation_messages(tree)
        if messages:
            violations[path.name] = messages
    # Assert
    assert not violations, (
        "mount-string splitting detected under src/tool_swap/backend/: "
        f"{violations}\n"
        "Parsing mount strings belongs to tool_swap.config.validate."
        "parse_mount (plan §4.2)."
    )

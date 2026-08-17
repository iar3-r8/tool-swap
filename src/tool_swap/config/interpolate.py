"""${VAR} / ${VAR:-default} interpolation for M1 config text (behaviour 5).

This module is the interpolation step of the M1 configuration pipeline.  It
runs on the raw config text BEFORE YAML parsing, substitutes ``${VAR}`` and
``${VAR:-default}`` references using an injected environment mapping (it
never reads the ambient environment), and quotes every substituted value so
it can never inject YAML structure (plan line 117).  All problems found in a
single pass are returned together; when any error is present,
``Interpolated.text`` is the input verbatim and the caller must not use it.

Codes emitted here: ``TSWAP-C010`` (variable unset and no default) and
``TSWAP-C013`` (an unclosed ``${`` reference).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from tool_swap.config.errors import Diagnostic, Location, Severity

_CODE_MISSING = "TSWAP-C010"
_CODE_UNCLOSED = "TSWAP-C013"

#: Plain-safe scalar: non-empty, starts alnum/_/~, body alnum/_/~ . / -.
_PLAIN_RE = re.compile(r"[A-Za-z0-9_~][A-Za-z0-9_~./-]*")
#: A value YAML would coerce away from a string if left unquoted.
_NUMERIC_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
#: Reserved YAML scalars that would change type if left unquoted.
_RESERVED_SCALARS = frozenset(
    {"null", "Null", "NULL", "~", "true", "True", "TRUE", "false", "False", "FALSE"}
)


@dataclass(frozen=True)
class Interpolated:
    """Result of one interpolation pass over a block of raw config text.

    Attributes:
        text: The interpolated text. When ``errors`` is non-empty this is the
            input verbatim (references neither substituted nor blanked) and
            the caller must not use it.
        errors: All problems found in this pass; ``[]`` on success.
    """

    text: str
    errors: list[Diagnostic]


def _line_of(text: str, index: int) -> int:
    """Return the 1-based line number of the character at ``index``."""
    return text.count("\n", 0, index) + 1


def _is_isolated(text: str, start: int, end: int) -> bool:
    """Return True when ``text[start:end]`` is a standalone scalar region.

    A region is standalone when the character before it is whitespace or the
    start of the text, and the character after it is whitespace or the end of
    the text.  Only standalone regions are injection-quoted; a reference woven
    into a longer string substitutes in place.
    """
    left_ok = start == 0 or text[start - 1].isspace()
    right_ok = end >= len(text) or text[end].isspace()
    return left_ok and right_ok


def _is_plain_safe(value: str) -> bool:
    """Return True when ``value`` can be emitted as a plain YAML scalar."""
    if not value:
        return False
    if value in _RESERVED_SCALARS:
        return False
    if _NUMERIC_RE.fullmatch(value) is not None:
        return False
    return _PLAIN_RE.fullmatch(value) is not None


def _double_quote(value: str) -> str:
    """Escape ``value`` for a double-quoted YAML scalar."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
    )


def _render_value(value: str) -> str:
    """Render ``value`` so it round-trips as a single YAML scalar.

    Double-quoted (with escapes) when it holds a newline or carriage return,
    plain when it is safe to leave bare, otherwise single-quoted (an internal
    ``'`` is doubled to ``''``).
    """
    if "\n" in value or "\r" in value:
        return '"' + _double_quote(value) + '"'
    if _is_plain_safe(value):
        return value
    return "'" + value.replace("'", "''") + "'"


def _make_unclosed(text: str, ref_start: int, file: str) -> Diagnostic:
    """Build the ``TSWAP-C013`` diagnostic for an unclosed ``${`` reference."""
    line = _line_of(text, ref_start)
    return Diagnostic(
        code=_CODE_UNCLOSED,
        severity=Severity.ERROR,
        message=f"unclosed ${{...}} reference starting on line {line}",
        location=Location(file=file, line=line),
        remedy="add the missing } to close the reference",
    )


def _make_missing(name: str, text: str, ref_start: int, file: str) -> Diagnostic:
    """Build the ``TSWAP-C010`` diagnostic for an unset variable."""
    line = _line_of(text, ref_start)
    return Diagnostic(
        code=_CODE_MISSING,
        severity=Severity.ERROR,
        message=f"variable '{name}' is not set and no default was given",
        location=Location(file=file, line=line),
        remedy=(
            "set " + name + " in the environment or in .env, or give it "
            "a default: ${" + name + ":-}"
        ),
    )


def _resolve(
    inner: str,
    env: Mapping[str, str],
    text: str,
    ref_start: int,
    file: str,
) -> tuple[str, Diagnostic | None]:
    """Resolve the inside of one ``${...}`` reference.

    Returns the substituted value with ``None`` on success, or an empty value
    with a ``TSWAP-C010`` diagnostic when the variable is unset and has no
    default.  A variable present in ``env`` (even with an empty value) counts
    as set (assumption A10); a ``$$`` inside a default becomes a literal ``$``.
    """
    sep = inner.find(":-")
    if sep == -1:
        name, has_default, default = inner, False, ""
    else:
        name = inner[:sep]
        has_default = True
        default = inner[sep + 2 :]
    if name in env:
        return env[name], None
    if has_default:
        return default.replace("$$", "$"), None
    return "", _make_missing(name, text, ref_start, file)


def interpolate(
    text: str,
    env: Mapping[str, str],
    *,
    file: str = "<text>",
) -> Interpolated:
    """Interpolate ``${VAR}`` / ``${VAR:-default}`` references in ``text``.

    The scan runs once over the raw text (before YAML parsing) using only the
    injected ``env`` mapping; it never reads the ambient environment.  A
    variable present in ``env`` counts as set even when its value is empty
    (assumption A10).  ``$$`` becomes a literal ``$``, a bare ``$VAR`` without
    braces is left untouched, and when any diagnostic is produced ``text`` is
    returned verbatim and must not be used by the caller.

    Args:
        text: Raw config text to interpolate.
        env: The environment to draw variable values from; a key present (even
            with an empty value) means the variable is set.
        file: File name to cite in diagnostics; keyword-only, defaulting to
            ``<text>`` for the text-level API.

    Returns:
        An ``Interpolated`` holding the substituted text (or the input
        verbatim on error) and the full list of diagnostics from this pass.
    """
    parts: list[str] = []
    errors: list[Diagnostic] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "$" and i + 1 < n and text[i + 1] == "$":
            parts.append(_render_value("$") if _is_isolated(text, i, i + 2) else "$")
            i += 2
            continue
        if ch == "$" and i + 1 < n and text[i + 1] == "{":
            depth = 1
            j = i + 2
            closed = False
            while j < n:
                cj = text[j]
                if cj == "{":
                    depth += 1
                elif cj == "}":
                    depth -= 1
                    if depth == 0:
                        closed = True
                        break
                j += 1
            if not closed:
                errors.append(_make_unclosed(text, i, file))
                i = n
                continue
            value, error = _resolve(
                inner=text[i + 2 : j], env=env, text=text, ref_start=i, file=file
            )
            if error is not None:
                errors.append(error)
            else:
                parts.append(
                    _render_value(value) if _is_isolated(text, i, j + 1) else value
                )
            i = j + 1
            continue
        parts.append(ch)
        i += 1
    if errors:
        return Interpolated(text=text, errors=errors)
    return Interpolated(text="".join(parts), errors=[])

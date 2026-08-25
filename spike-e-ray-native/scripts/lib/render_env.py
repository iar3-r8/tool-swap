"""Render shell-style ``${VAR}`` placeholders in YAML files.

Ray loads configs via ``yaml.safe_load`` and performs **no** variable
substitution, so every config that references an environment variable
must be rendered *before* being passed to ``serve deploy``.

Three placeholder forms are supported:

- ``${VAR}`` — replaced with the environment value if it is set and
  non-empty; otherwise the literal placeholder is left verbatim so
  Ray's schema validator can reject it (fail loud, never silent).
- ``${VAR:-default}`` — environment value if set and non-empty, else
  *default*.
- ``${VAR:default}`` — same semantics as ``:-``.  POSIX shell gives a
  bare ``:`` no special meaning, but every config in this repo uses
  the single-colon form, and image URIs (``tool_torch:spike``) contain
  colons, so ``:`` and ``:-`` are treated identically on purpose.

A *default* may contain any character except ``}``.  No nesting is
supported — a ``${`` sequence inside a default is passed through
verbatim.  The entire placeholder, including the closing ``}``, is a
single match, so rendered output never contains a stray ``}``.

Usage (standalone):
    python -m scripts.lib.render_env apps/step1_config.yaml

Usage (library):
    from scripts.lib.render_env import render_file
    rendered = render_file("apps/step1_config.yaml")

The output is written to stdout so that Make targets can capture it
and pipe it to a temporary file, which is what ``apply_config`` does
internally.  When used as a library, ``render_file`` returns a bytes
object ready for ``yaml.safe_load``.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# ${VAR}  |  ${VAR:-default}  |  ${VAR:default}  — the whole
# placeholder (including the closing brace) is one match.
# Group 1: variable name, group 2: "-" if the default separator is
# present (distinguishes "${VAR}" from "${VAR:}"), group 3: default.
_PAT = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::(-?)([^}]*))?\}")


def render(text: str) -> str:
    """Replace ``${VAR}`` placeholders in *text*.

    Supported forms: ``${VAR}``, ``${VAR:-default}``, ``${VAR:default}``
    (the last two are semantically identical: environment value when
    the variable is set and non-empty, otherwise *default*).  Without
    a default, an unset or empty variable leaves the literal
    placeholder in place so the failure is loud, not silent.
    """
    def _replace(m: re.Match) -> str:
        var = m.group(1)
        has_default = m.group(2) is not None
        default = m.group(3)
        val = os.environ.get(var)
        if val is not None and val != "":
            return val
        if has_default:
            return default
        # No default and variable unset/empty — leave the literal
        # placeholder so Ray's schema validator can reject it.
        return m.group(0)

    return _PAT.sub(_replace, text)


def render_file(path: str) -> bytes:
    """Read *path*, render placeholders, return the bytes suitable for
    ``yaml.safe_load``."""
    text = Path(path).read_text(encoding="utf-8")
    return render(text).encode("utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: render_env.py <path-to-yaml>", file=sys.stderr)
        sys.exit(1)
    sys.stdout.buffer.write(render_file(sys.argv[1]))

"""Render shell-style ${VAR} and ${VAR:-default} placeholders in YAML files.

Ray loads configs via ``yaml.safe_load`` and performs **no** variable
substitution, so every config that references an environment variable
must be rendered *before* being passed to ``serve deploy``.

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

# Pattern: ${VAR}  or  ${VAR:-default_value}
_PAT = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-((?:[^}]|\}(?!\}))*))?")


def render(text: str) -> str:
    """Replace ``${VAR}`` with ``os.environ["VAR"]``, falling back to
    the optional default when the variable is unset or empty.

    Supports the common shell form ``${VAR:-default}`` where *default*
    may contain any character except ``}`` (to avoid nested-expansion
    ambiguity).  No nesting is supported — a ``${}`` inside *default*
    is passed through verbatim.
    """
    def _replace(m: re.Match) -> str:
        var = m.group(1)
        default = m.group(3)  # None when the :‑default part is absent
        val = os.environ.get(var)
        if val is not None and val != "":
            return val
        if default is not None:
            return default
        # No default and variable unset — leave the literal string so
        # Ray's schema validator can reject it (better than a silent
        # empty value).
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

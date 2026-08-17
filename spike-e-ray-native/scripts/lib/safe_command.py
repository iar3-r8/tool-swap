"""Safe command execution helpers.

Each function guards an external binary with ``shutil.which``, captures
stdout + stderr + return code, and returns a human-readable string
instead of raising ``FileNotFoundError``.

This is the single source of truth for "command not found" behaviour
across the spike, so that a missing binary is recorded as a string
(e.g. ``not present``) rather than a traceback that aborts the run.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional


def safe_run(
    cmd: list[str],
    desc: str = "",
    timeout: int = 30,
) -> str:
    """Run *cmd*, capture stdout + stderr + exit code.

    If the executable is not on PATH the caller never sees a traceback:
    the returned string is ``<desc>: not present``.

    Parameters
    ----------
    cmd:
        Command and arguments (must be a list, never a string — no shell).
    desc:
        Label shown in the output (e.g. ``"nvidia-smi"``).  Defaults to
        ``" ".join(cmd)``.
    timeout:
        Seconds before the subprocess is killed.

    Returns
    -------
    str
        Fenced markdown block with the command and its verbatim output.
        Includes the exit code.
    """
    if not desc:
        desc = " ".join(cmd)

    exe = shutil.which(cmd[0])
    if exe is None:
        return f"## {desc}\n\n```n\n{desc}: not present\n```\n"

    print(f"$ {desc}")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout or result.stderr or "(no output)"
        exit_code = result.returncode
        header = f"{desc}  [exit={exit_code}]"
        return f"## {header}\n\n```\n{output}\n```\n"
    except subprocess.TimeoutExpired:
        return f"## {desc}\n\n```n\n{desc}: timed out after {timeout}s\n```\n"
    except Exception as exc:
        return f"## {desc}\n\n```n\n{desc}: ERROR — {exc}\n```\n"


def safe_run_list(
    items: list[tuple[list[str], str]],
    timeout: int = 30,
) -> list[str]:
    """Run several commands and return their string outputs.

    Parameters
    ----------
    items:
        List of ``(cmd, desc)`` pairs.  *cmd* is a list; *desc* is
        optional.
    timeout:
        Seconds per command.

    Returns
    -------
    list[str]
        One output string per item, in the same order.
    """
    return [safe_run(cmd, desc=desc, timeout=timeout) for cmd, desc in items]


def which(cmd: str) -> Optional[str]:
    """Return the full path to the executable, or None."""
    return shutil.which(cmd)


def require_present(cmd: str, label: str) -> str:
    """Return ``not present`` if *cmd* is absent, else the full path.

    Convenience wrapper used by *preflight* and by steps that must not
    continue without a tool.
    """
    path = shutil.which(cmd)
    if path is None:
        return f"{label}: not present"
    return f"{label}: {path}"

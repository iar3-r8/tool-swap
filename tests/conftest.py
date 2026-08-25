"""Shared test fixtures for the tool-swap test suite.

Fakes (FakeBackend, FakeProbe, ManualClock) land here once M2 provides them.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repo root and src/ are on sys.path so that tests can import
# ``tool_swap`` (from src/) and ``tests.conftest`` (from repo root).
# This guard makes ``pytest tests/unit/test_clock.py`` and IDE runners work
# even when pyproject.toml's ``pythonpath`` is not picked up.
_ROOT = Path(__file__).resolve().parent.parent  # repo root
for _p in (str(_ROOT / "src"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
del _ROOT, _p

import asyncio
import re
import time
from typing import TYPE_CHECKING, runtime_checkable

import pytest

pytest_plugins = []


# ---------------------------------------------------------------------------
# ManualClock stub for behaviour 3 tests
# ---------------------------------------------------------------------------
# This minimal stub exists so that ``isinstance(ManualClock(), Clock)``
# exercises the runtime_checkable protocol without requiring the full
# implementation (which lands in behaviour 4).

if TYPE_CHECKING:
    from typing import Protocol
else:
    Protocol = object  # fallback — not used at runtime by this stub


# Raw string: ``\x1b`` is interpreted by the REGEX engine (the ESC
# character), not by the Python string parser, so no invalid-escape
# warnings (the suite runs with ``filterwarnings = ["error"]``).
#
# The CSI final byte must be the full ``[@-~]`` (0x40-0x7E) range, NOT
# just ``[A-Z]``: the SGR terminators are lowercase (``m``), so an
# uppercase-only class silently leaves ``ESC[1m``/``ESC[0m`` in place.
_ANSI_ESCAPE_RE = re.compile(
    r"\x1b\[[0-9;?]*[@-~]"  # CSI sequences, e.g. ESC[1m, ESC[0m, ESC[2J
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC ... BEL / OSC ... ST
    r"|\x1b[()][0-9A-B]"  # character-set selection
    r"|\x1b[>=]"  # keypad modes
    r"|\x1b[78]"  # save/restore cursor position
)


def normalize_help_output(text: str) -> str:
    """Strip ANSI escapes and collapse all whitespace runs to single spaces.

    Shared by the CLI ``--help`` smoke tests (imported via
    ``from conftest import normalize_help_output`` — see those modules).
    On GitHub Actions
    (``GITHUB_ACTIONS=true``) typer's ``rich_utils`` freezes
    ``FORCE_TERMINAL=True`` at module-import time, so Rich styles the help
    text — ``CliRunner(env=...)`` cannot stop it because the env is applied
    at ``invoke()`` time, long after import. Two independent things then
    break substring/line-anchor assertions, so BOTH must be normalised:

    1. ANSI escapes are injected mid-token (``\\x1b[1m--config\\x1b[0m``), so
       ``"--config" in stdout`` is literally ``False``;
    2. line wrapping moves a flag's description onto a continuation line, so
       ``(?m)^.*--config\\b.{10,}$``-style anchors fail even after the
       escapes are stripped.

    The result is a single whitespace-collapsed, escape-free line on which
    whole-token membership checks (``"flag" in normalized``) are stable for
    any terminal width or colour state.
    """
    stripped = _ANSI_ESCAPE_RE.sub("", text)
    return " ".join(stripped.split())


class ManualClock:
    """Minimal ManualClock stub satisfying the Clock protocol.

    This is NOT the real implementation — just enough to verify that
    ``isinstance(ManualClock(), Clock)`` works once the protocol is
    ``@runtime_checkable``.
    """

    def now(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("sleep duration must be non-negative")
        await asyncio.sleep(seconds)

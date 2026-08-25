"""Tests for M1 behaviour 4 — the pure edit-distance suggestion helper.

See ``plans/m1-configuration.md`` behaviour 4 (lines 88-105), edge case at
line 100: the distance threshold and its rationale are asserted by a
table-driven test (``batch_size``→``max_batch_size``,
``mount``→``mounts``, ``descripton``→``description``, ``xyzzy``→ no
suggestion), plus an obvious no-false-positive case.

This file is the RED step: the module under test,
``src/tool_swap/config/suggest.py``, does not exist yet, so this file
fails collection with ``ModuleNotFoundError``.  That is the *right* red
reason — every test body below pins a concrete behaviour the GREEN step
must satisfy, so the assertions (not just the import) are the contract.

Pinned public API (the contract the GREEN step must meet verbatim):

- ``nearest_alternative(name: str, candidates: Iterable[str]) -> str | None``
  — a pure function (no I/O): returns the candidate closest to ``name``
  by edit distance (Levenshtein) when it is within the documented
  threshold, else ``None``.  ``candidates`` may be any iterable of
  ``str`` (list or tuple); an empty iterable always yields ``None``.

The four pinned positive/negative cases plus the no-false-positive case
fix the threshold from both sides: the implementation must be loose
enough to bridge ``batch_size`` → ``max_batch_size`` (distance 4, a
prefix the user plausibly dropped) and strict enough to reject
``xyzzy`` and a single character ``q`` against realistic field names
(a confidently wrong suggestion is worse than none, plan line 96).

Conventions: pytest, AAA pattern, no ``warnings.warn`` (pyproject sets
``filterwarnings = "error"``).
"""

from __future__ import annotations

import pytest

from tool_swap.config.suggest import nearest_alternative


@pytest.mark.parametrize(
    ("name", "candidates", "expected"),
    [
        pytest.param(
            "batch_size",
            [
                "autostart",
                "devices",
                "env",
                "group",
                "keep_warm",
                "max_batch_size",
                "max_wait_ms",
                "mounts",
                "probe_interval",
                "shm_size",
                "ttl",
            ],
            "max_batch_size",
            id="dropped-prefix-suggests-max_batch_size",
        ),
        pytest.param(
            "mount",
            ("env", "group", "mounts", "ttl"),
            "mounts",
            id="one-insertion-suggests-mounts",
        ),
        pytest.param(
            "descripton",
            ["description", "handler", "name", "version"],
            "description",
            id="one-deletion-suggests-description",
        ),
        pytest.param(
            "xyzzy",
            ["description", "handler", "name", "path", "ttl"],
            None,
            id="obscure-name-no-suggestion",
        ),
        pytest.param(
            "q",
            [
                "autostart",
                "devices",
                "keep_warm",
                "max_batch_size",
                "max_wait_ms",
                "mounts",
                "probe_interval",
                "shm_size",
            ],
            None,
            id="single-character-no-false-positive",
        ),
        pytest.param(
            "ttl",
            (),
            None,
            id="empty-candidates-no-suggestion",
        ),
    ],
)
def test_nearest_alternative_threshold_rationale(
    name: str,
    candidates: list[str] | tuple[str, ...],
    expected: str | None,
) -> None:
    """Table-driven pin of the edit-distance threshold, plan line 100.

    Arrangement: a misspelled (or obscure) key name and a realistic set
    of candidate field names for one config block.
    Action: call ``nearest_alternative(name, candidates)``.
    Assertion: the returned value equals the expected candidate — or
    ``None`` when nothing is close enough (the threshold rationale).
    """
    assert nearest_alternative(name, candidates) == expected

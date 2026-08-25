"""Edit-distance helper that suggests the nearest valid key for unknown keys.

Pure function only: no I/O, no state.  The threshold rationale is pinned by
``tests/unit/config/test_suggest.py`` — loose enough to bridge a dropped
prefix (``batch_size`` → ``max_batch_size``) while rejecting unrelated names
(``xyzzy``, a stray ``q``): a confidently wrong suggestion is worse than none.
"""

from __future__ import annotations

from collections.abc import Iterable

#: A candidate is offered only when its Levenshtein distance to the typed
#: name is at most this fraction of the longer of the two names.  At 0.3 a
#: dropped 3-4 character prefix on a long field name still matches, while
#: short or unrelated names never do.
_SUGGESTION_FRACTION: float = 0.3


def _levenshtein(first: str, second: str) -> int:
    """Return the classic edit distance (insert, delete, substitute = 1).

    Args:
        first: The first string.
        second: The second string.

    Returns:
        The minimum number of single-character edits turning ``first`` into
        ``second``; two-row dynamic programming (O(shorter length) memory).
    """
    if len(first) < len(second):
        first, second = second, first
    previous = list(range(len(second) + 1))
    for i, char_a in enumerate(first, start=1):
        current = [i]
        for j, char_b in enumerate(second, start=1):
            cost = 0 if char_a == char_b else 1
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
            )
        previous = current
    return previous[-1]


def nearest_alternative(name: str, candidates: Iterable[str]) -> str | None:
    """Find the candidate closest to ``name`` within the suggestion threshold.

    Args:
        name: The unknown (presumably misspelled) key.
        candidates: Valid field names of the block containing the key; any
            iterable of ``str``, possibly empty.

    Returns:
        The closest candidate when its Levenshtein distance to ``name`` is at
        most ``_SUGGESTION_FRACTION`` times the longer name's length, else
        ``None`` (including when ``candidates`` is empty).  On equal
        distances the first candidate in iteration order wins, so the result
        is deterministic.
    """
    best: str | None = None
    best_distance = -1
    for candidate in candidates:
        threshold = _SUGGESTION_FRACTION * max(len(name), len(candidate))
        distance = _levenshtein(name, candidate)
        if distance <= threshold and (best is None or distance < best_distance):
            best, best_distance = candidate, distance
    return best

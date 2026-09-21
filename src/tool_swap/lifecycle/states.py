"""Tool-level lifecycle states (m2b plan §3, behaviours 5, 6 and 7).

Answers "can this tool serve traffic" (only ``READY`` does), which is
deliberately distinct from ``ContainerState`` in
``tool_swap.backend.base`` — that enum answers only "does a process
exist"; a container can be running while its tool is still ``LOADING``
and serving nothing. Both enums pin their exact member sets so they
cannot drift together, and ``ToolState``'s values stay disjoint from
``ContainerState``'s so a readiness concept is never smuggled into the
backend seam. A ``StrEnum`` so members compare equal to the bare
strings used in CLI output and persisted state.

Behaviour 7 pins the transition table: the ten legal edges of plan
§1.1 as data, ``is_legal_transition`` as the pure predicate over that
data, and ``apply_transition`` as the single entry point that mutates
a ``ModelRuntimeState`` in place, raising ``IllegalTransitionError``
on anything else.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from tool_swap.backend.base import ContainerHandle


class ToolState(StrEnum):
    """Readiness state of one tool instance; ``READY`` is the only
    member serving traffic (plan/01 §4).

    The exact six-member set is pinned by
    ``tests/unit/lifecycle/test_states.py``; adding or dropping a member
    silently changes what the transition table accepts.
    """

    STOPPED = "stopped"
    STARTING = "starting"
    LOADING = "loading"
    READY = "ready"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass
class ModelRuntimeState:
    """Mutable per-tool runtime facts, updated in place on every completion —
    frozen would mean reallocating each time. ``last_error`` holds the
    backend error's ``message`` verbatim, not ``str(err)``."""

    tool: str
    state: ToolState
    handle: ContainerHandle | None  # None unless a container exists
    last_used: float  # clock.now() on request completion
    became_ready_at: float | None
    inflight: int
    last_error: str | None  # the taxonomy member's message, verbatim


# The ten legal edges of m2b plan §1.1, in table order. Data, not a
# chain of branches: the exhaustive test compares against this exact
# set, and a missing or spurious edge cannot hide in an if-chain.
#
# Self-transitions and STARTING -> STOPPED are deliberately absent:
# a re-ready must never reset a serving tool's timers, and the
# vram_unavailable path needs the failure classification M6 owns
# (plan/06 §8.5b).
_LEGAL_TRANSITIONS: Final[frozenset[tuple[ToolState, ToolState]]] = frozenset(
    {
        (ToolState.STOPPED, ToolState.STARTING),  # ensure_ready, stopped
        (ToolState.STARTING, ToolState.LOADING),  # health probe true
        (ToolState.STARTING, ToolState.FAILED),  # start raised / start_timeout
        (ToolState.LOADING, ToolState.READY),  # ready probe true
        (ToolState.LOADING, ToolState.FAILED),  # ready_timeout elapsed
        (ToolState.READY, ToolState.STOPPING),  # stop requested
        (ToolState.READY, ToolState.FAILED),  # liveness sweep: container gone
        (ToolState.STOPPING, ToolState.STOPPED),  # backend stop returned
        (ToolState.FAILED, ToolState.STARTING),  # ensure_ready retries
        (ToolState.FAILED, ToolState.STOPPED),  # manual reset
    }
)


def is_legal_transition(from_state: ToolState, to_state: ToolState) -> bool:
    """True iff the pair is one of the ten §1.1 legal edges."""
    return (from_state, to_state) in _LEGAL_TRANSITIONS


class IllegalTransitionError(ValueError):
    """A pair outside the §1.1 table was passed to ``apply_transition``.

    Subclasses ``ValueError``: the fault is the pair the caller
    supplied, not a runtime failure of the process itself.
    """


def apply_transition(
    state: ModelRuntimeState, to_state: ToolState, *, reason: str
) -> ToolState:
    """Move the holder to ``to_state`` in place and return the new state.

    The from-state is read from ``state.state``, so the pair cannot be
    inconsistent with the holder. ``reason`` is accepted but not yet
    used; behaviour 8 logs it from this entry point. An illegal pair
    raises ``IllegalTransitionError`` and leaves the holder untouched.
    """
    from_state = state.state
    if (from_state, to_state) not in _LEGAL_TRANSITIONS:
        raise IllegalTransitionError(
            f"Illegal transition {from_state.name} -> {to_state.name}"
        )
    state.state = to_state
    return to_state

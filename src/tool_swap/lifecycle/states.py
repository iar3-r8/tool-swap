"""Tool-level lifecycle states (m2b plan §3, behaviours 5 and 6).

Answers "can this tool serve traffic" (only ``READY`` does), which is
deliberately distinct from ``ContainerState`` in
``tool_swap.backend.base`` — that enum answers only "does a process
exist"; a container can be running while its tool is still ``LOADING``
and serving nothing. Both enums pin their exact member sets so they
cannot drift together, and ``ToolState``'s values stay disjoint from
``ContainerState``'s so a readiness concept is never smuggled into the
backend seam. A ``StrEnum`` so members compare equal to the bare
strings used in CLI output and persisted state.
"""

from dataclasses import dataclass
from enum import StrEnum

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

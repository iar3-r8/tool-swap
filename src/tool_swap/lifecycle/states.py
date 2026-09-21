"""Tool-level lifecycle states (m2b plan §3, behaviour 5).

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

from enum import StrEnum


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

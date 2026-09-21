"""The readiness probe seam (m2b plan §3 behaviour 9, §1.5).

Declares ``Probe`` — the two async methods the manager calls while a
tool walks ``STARTING`` to ``LOADING`` to ``READY`` — and
``ProbeTarget``, the immutable address a probe receives. This is a
declaration, not an implementation: the module imports no HTTP library
(D-B); ``tests/unit/proxy/probe_guard.py`` walks this file's written
imports to keep it that way. A renamed, re-ordered or re-annotated
member here would make M3's real probe a different interface than the
manager's, so the tests pin both methods and the target's field set
exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class Probe(Protocol):
    """The two readiness questions, kept separate on purpose:
    ``health`` answers whether the process is up (``STARTING``),
    ``ready`` whether it serves (``LOADING``). Merging them into one
    method would collapse the distinction the state machine exists to
    express; a sync method would force an executor hop or a later
    signature change in M3.
    """

    async def health(self, target: ProbeTarget) -> bool: ...

    async def ready(self, target: ProbeTarget) -> bool: ...


@dataclass(frozen=True, slots=True)
class ProbeTarget:
    """The address of one tool — container name, port and the two
    probe paths — and nothing else: no URL, because the probe
    composes the URL and this type owns no client. ``host`` is the
    container name because tools are addressed by name on the shared
    network (D21, plan/01 §7). Dropping frozen or slots would let a
    probe or manager rewrite, or grow, the address mid-flight.
    """

    tool: str
    host: str
    port: int
    health_path: str
    ready_path: str

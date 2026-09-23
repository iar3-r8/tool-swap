"""The readiness probe seam.

Declares ``Probe`` — the two async methods the manager calls while a
tool walks ``STARTING`` to ``LOADING`` to ``READY`` — and
``ProbeTarget``, the immutable address a probe receives. Also holds
``FakeProbe``, the scripted double tests inject in place of a real
probe. The module imports no HTTP library;
``tests/unit/proxy/probe_guard.py`` walks this file's written imports
to keep it that way. A renamed, re-ordered or re-annotated member
here would make a real probe a different interface than the
manager's, so the tests pin both methods and the target's field set
exactly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class Probe(Protocol):
    """The two readiness questions, kept separate on purpose:
    ``health`` answers whether the process is up (``STARTING``),
    ``ready`` whether it serves (``LOADING``). Merging them into one
    method would collapse the distinction the state machine exists to
    express; a sync method would force an executor hop on every poll
    or a signature change when a real probe arrives.
    """

    async def health(self, target: ProbeTarget) -> bool: ...

    async def ready(self, target: ProbeTarget) -> bool: ...


@dataclass(frozen=True, slots=True)
class ProbeTarget:
    """The address of one tool — container name, port and the two
    probe paths — and nothing else: no URL, because the probe
    composes the URL and this type owns no client. ``host`` is the
    container name because tools are addressed by name on the shared
    network, so the probe needs neither config access nor container
    knowledge. Dropping frozen or slots would let a probe or manager
    rewrite, or grow, the address mid-flight.
    """

    tool: str
    host: str
    port: int
    health_path: str
    ready_path: str


class FakeProbe:
    """The scripted probe double.

    Answers ``health`` and ``ready`` from a per-tool, per-phase
    script — ``0`` true immediately, ``N > 0`` false for the first N
    calls then true and true thereafter, ``None`` never true — with a
    tool or phase absent from the script answering true immediately,
    so a test indifferent to probing scripts nothing. The double
    counts calls, not wall time: no clock, no socket, no container,
    and it never raises, so a manager deadline loop may poll it for
    as long as the simulated deadline lasts. A probe that raises on
    transport failure is the real probe's concern; that shape is
    deliberately not modelled here.

    ``calls`` is the call journal, following ``FakeBackend.calls`` in
    name and purpose: ``(method, tool)`` pairs in call order,
    recorded on entry and including calls that answered False, so a
    hung phase is diagnosable from how often the probe was asked.
    (The entry shape is the plan's pair, not the backend's triple.)
    """

    def __init__(
        self,
        script: Mapping[str, Mapping[str, int | None]] | None = None,
    ) -> None:
        """Create a double, optionally with a per-tool script.

        Args:
            script: Tool name to phase (``"health"``, ``"ready"``) to
                script entry, as declared by the test module
                docstring. ``None`` means no tool is scripted. The
                mapping is read, never mutated.
        """
        self._script: Mapping[str, Mapping[str, int | None]] = (
            script if script is not None else {}
        )
        self._counters: dict[tuple[str, str], int] = {}
        self.calls: list[tuple[str, str]] = []

    def _answer(self, method: str, target: ProbeTarget) -> bool:
        """Journal the call, then compute the scripted answer.

        The journal is appended before the answer is computed, so a
        call that answers False is counted as a call that answers
        True.

        Args:
            method: The probe member being called, as journaled.
            target: The addressed tool; only ``tool`` is read.

        Returns:
            The scripted bool for this tool and phase.
        """
        self.calls.append((method, target.tool))
        tool_script = self._script.get(target.tool)
        if tool_script is None or method not in tool_script:
            # Unscripted: a missing tool or phase answers true
            # immediately. The membership check keeps that distinct
            # from an explicit ``None`` entry, which means never true.
            return True
        entry = tool_script[method]
        if entry is None:
            return False
        count = self._counters.get((method, target.tool), 0) + 1
        self._counters[(method, target.tool)] = count
        return count > entry

    async def health(self, target: ProbeTarget) -> bool:
        """The scripted answer to the ``STARTING`` question."""
        return self._answer("health", target)

    async def ready(self, target: ProbeTarget) -> bool:
        """The scripted answer to the ``LOADING`` question."""
        return self._answer("ready", target)

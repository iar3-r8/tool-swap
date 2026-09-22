"""Pins FakeProbe, the scripted probe double (m2b plan §3 behaviour 10, §1.5).

The plan names three scripts per phase but no script API; the
contract this file declares, for the implementation to honour:

    FakeProbe(script={"t1": {"health": 0, "ready": 3}})

``script`` is an optional mapping of tool name to a mapping with
optional ``"health"`` and ``"ready"`` entries, each one of: ``0`` —
true immediately; ``N > 0`` — false for N calls, then true and stays
true; ``None`` — never true. A tool or phase absent from the script
answers true immediately. The ``.calls`` journal records
``(method, tool)`` pairs in call order, following ``FakeBackend.calls``
in name and purpose.

``FakeProbe`` does not exist in probes.py yet, so every test here
fails at the deferred gate that names the missing class rather than
aborting collection.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any, cast

import pytest


def _get_probes_module() -> ModuleType:
    """Import tool_swap.proxy.probes at call time, so a missing module
    fails as an informative assertion, not a collection error.

    Raises:
        AssertionError: the module is missing; the message names the
            file to create.
    """
    try:
        return importlib.import_module("tool_swap.proxy.probes")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.proxy.probes is missing — create src/tool_swap/proxy/probes.py"
        ) from exc


def _get_probe() -> type[Any]:
    """Return the Probe protocol; a missing name raises an informative
    AssertionError instead of a bare AttributeError.

    Raises:
        AssertionError: the name is missing from probes.py.
    """
    module = _get_probes_module()
    try:
        return cast("type[Any]", module.Probe)
    except AttributeError as exc:
        raise AssertionError(
            "Probe is missing from src/tool_swap/proxy/probes.py"
        ) from exc


def _get_probe_target() -> type[Any]:
    """Return the ProbeTarget dataclass; a missing name raises an
    informative AssertionError instead of a bare AttributeError.

    Raises:
        AssertionError: the name is missing from probes.py.
    """
    module = _get_probes_module()
    try:
        return cast("type[Any]", module.ProbeTarget)
    except AttributeError as exc:
        raise AssertionError(
            "ProbeTarget is missing from src/tool_swap/proxy/probes.py"
        ) from exc


def _get_fake_probe() -> type[Any]:
    """Return the FakeProbe class; a missing name raises an informative
    AssertionError instead of a bare AttributeError.

    Raises:
        AssertionError: the name is missing from probes.py.
    """
    module = _get_probes_module()
    try:
        return cast("type[Any]", module.FakeProbe)
    except AttributeError as exc:
        raise AssertionError(
            "FakeProbe is missing from src/tool_swap/proxy/probes.py — "
            "add the scripted double there"
        ) from exc


def _get_calls(probe: Any) -> list[tuple[str, str]]:
    """Fetch ``probe.calls``; a missing journal raises an informative
    AssertionError instead of a bare AttributeError.

    Raises:
        AssertionError: the probe has no ``calls`` attribute — the
            journal to add is named in the message.
    """
    try:
        return cast("list[tuple[str, str]]", probe.calls)
    except AttributeError as exc:
        raise AssertionError(
            "FakeProbe.calls is missing — add the (method, tool) call "
            "journal to FakeProbe in src/tool_swap/proxy/probes.py"
        ) from exc


def _target(target_cls: type[Any], tool: str) -> Any:
    """A minimal ProbeTarget for the named tool.

    Only ``tool`` is read by the assertions; the address fields exist
    because the dataclass requires them.
    """
    return target_cls(
        tool=tool,
        host=f"tswap-{tool}",
        port=8000,
        health_path="/health",
        ready_path="/ready",
    )


# ---------------------------------------------------------------------------
# The double satisfies the seam
# ---------------------------------------------------------------------------


def test_fake_probe_isinstance_of_probe() -> None:
    """A FakeProbe passes the runtime_checkable isinstance gate.

    The manager type-checks injected probes with isinstance; a double
    that failed the gate could not be injected at all.
    """
    # Arrange
    probe_cls = _get_fake_probe()
    probe_cls_interface = _get_probe()
    # Act
    checkable = isinstance(probe_cls(), probe_cls_interface)
    # Assert
    assert checkable is True, (
        "isinstance(FakeProbe(), Probe) is False — the double does not "
        "structurally satisfy the seam the manager checks for"
    )


# ---------------------------------------------------------------------------
# The three script shapes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", ["health", "ready"])
async def test_fake_probe_true_immediately_answers_true_on_first_call(
    method_name: str,
) -> None:
    """Script ``0`` answers True on the first call.

    A warm tool costs no simulated time in the readiness progression;
    a first-call False would consume a polling interval that plan
    §11's warm-tool edge case says is free.
    """
    # Arrange
    probe_cls = _get_fake_probe()
    target_cls = _get_probe_target()
    probe = probe_cls(script={"t1": {method_name: 0}})
    target = _target(target_cls, "t1")
    # Act
    answer = await getattr(probe, method_name)(target)
    # Assert
    assert answer is True, (
        f"{method_name} with script 0 answered {answer!r} on the first call"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", ["health", "ready"])
@pytest.mark.parametrize("n", [1, 2, 5])
async def test_fake_probe_true_after_n_answers_false_n_times_then_true(
    method_name: str, n: int
) -> None:
    """Script ``N`` answers False exactly N times, then True.

    This is the shape that makes a real LOADING window observable:
    one call short or one extra False would shift every deadline test
    built on top of this double.
    """
    # Arrange
    probe_cls = _get_fake_probe()
    target_cls = _get_probe_target()
    probe = probe_cls(script={"t1": {method_name: n}})
    target = _target(target_cls, "t1")
    # Act
    answers: list[bool] = []
    for _ in range(n + 1):
        answers.append(await getattr(probe, method_name)(target))
    # Assert
    assert answers == [False] * n + [True], (
        f"{method_name} with script {n} answered {answers}, expected "
        f"{[False] * n + [True]}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", ["health", "ready"])
async def test_fake_probe_true_after_n_stays_true_after_flipping(
    method_name: str,
) -> None:
    """Once the scripted probe flips true it stays true.

    The double models a deterministic environment, not a flapping
    container: a later False would silently re-open a LOADING window
    the progression already closed.
    """
    # Arrange
    probe_cls = _get_fake_probe()
    target_cls = _get_probe_target()
    probe = probe_cls(script={"t1": {method_name: 2}})
    target = _target(target_cls, "t1")
    # Act
    answers: list[bool] = []
    for _ in range(5):
        answers.append(await getattr(probe, method_name)(target))
    # Assert
    assert answers == [False, False, True, True, True], (
        f"{method_name} with script 2 answered {answers} — the probe "
        "flipped back to False after answering True"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method_name", ["health", "ready"])
async def test_fake_probe_never_true_answers_false_on_every_call(
    method_name: str,
) -> None:
    """Script ``None`` answers False on every call, repeated.

    The never-ready failure mode: the readiness timeout path is driven
    by a probe that keeps saying no, so a one-shot False followed by
    True would leave that path untestable.
    """
    # Arrange
    probe_cls = _get_fake_probe()
    target_cls = _get_probe_target()
    probe = probe_cls(script={"t1": {method_name: None}})
    target = _target(target_cls, "t1")
    # Act
    answers: list[bool] = []
    for _ in range(10):
        answers.append(await getattr(probe, method_name)(target))
    # Assert
    assert answers == [False] * 10, (
        f"{method_name} with script None answered {answers} — the "
        "never-true script must answer False on every call"
    )


# ---------------------------------------------------------------------------
# Script keys — phase and tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fake_probe_scripts_health_and_ready_independently() -> None:
    """health and ready take their own scripts for the same tool.

    The two phases are separate questions (§1.5): a script applied to
    only one must not leak into the other.
    """
    # Arrange
    probe_cls = _get_fake_probe()
    target_cls = _get_probe_target()
    probe = probe_cls(script={"t1": {"health": 0, "ready": 3}})
    target = _target(target_cls, "t1")
    # Act
    health_answer = await probe.health(target)
    ready_answers: list[bool] = [await probe.ready(target) for _ in range(4)]
    # Assert
    assert health_answer is True, (
        f"health with script 0 answered {health_answer!r}, the ready "
        "script must not leak into health"
    )
    assert ready_answers == [False, False, False, True]


@pytest.mark.asyncio
async def test_fake_probe_script_is_keyed_by_tool() -> None:
    """A script for one tool does not touch any other tool.

    A test scripting one tool's slow ready would corrupt the default
    true-immediately answers of every tool it did not script.
    """
    # Arrange
    probe_cls = _get_fake_probe()
    target_cls = _get_probe_target()
    probe = probe_cls(script={"t1": {"ready": 2}})
    target_t1 = _target(target_cls, "t1")
    target_t2 = _target(target_cls, "t2")
    # Act
    t2_ready = await probe.ready(target_t2)
    t1_ready_answers: list[bool] = [await probe.ready(target_t1) for _ in range(3)]
    # Assert
    assert t2_ready is True, (
        f"ready for unscripted tool t2 answered {t2_ready!r} — the "
        "script for t1 leaked across tools"
    )
    assert t1_ready_answers == [False, False, True]


@pytest.mark.asyncio
async def test_fake_probe_without_script_answers_true_immediately() -> None:
    """A probe built with no script answers True on the first call.

    A test that does not care about probing constructs a bare double;
    forcing it to script every tool would make the default invisible.
    """
    # Arrange
    probe_cls = _get_fake_probe()
    target_cls = _get_probe_target()
    probe = probe_cls()
    target = _target(target_cls, "t1")
    # Act
    health_answer = await probe.health(target)
    ready_answer = await probe.ready(target)
    # Assert
    assert health_answer is True
    assert ready_answer is True


@pytest.mark.asyncio
async def test_fake_probe_unscripted_phase_defaults_to_true_immediately() -> None:
    """Scripting only health leaves ready answering True immediately.

    The inner mapping is per phase: a missing phase is the same
    default as a missing tool.
    """
    # Arrange
    probe_cls = _get_fake_probe()
    target_cls = _get_probe_target()
    probe = probe_cls(script={"t1": {"health": None}})
    target = _target(target_cls, "t1")
    # Act
    health_answer = await probe.health(target)
    ready_answer = await probe.ready(target)
    # Assert
    assert health_answer is False, (
        f"health with script None answered {health_answer!r} — expected "
        "the never-true script on the scripted phase"
    )
    assert ready_answer is True, (
        f"ready for unscripted phase answered {ready_answer!r} — expected "
        "the true-immediately default"
    )


# ---------------------------------------------------------------------------
# The call journal
# ---------------------------------------------------------------------------


def test_fake_probe_calls_is_empty_before_any_call() -> None:
    """A fresh probe's journal is an empty list.

    Poll counts are only meaningful on a journal that starts empty —
    a pre-populated or shared journal would make every such count
    wrong.
    """
    # Arrange
    probe_cls = _get_fake_probe()
    probe = probe_cls()
    # Act
    calls = _get_calls(probe)
    # Assert
    assert isinstance(calls, list)
    assert calls == []


@pytest.mark.asyncio
async def test_fake_probe_calls_records_method_and_tool_in_order() -> None:
    """The journal holds (method, tool) pairs in call order.

    The deadline and timeout paths built on this double diagnose a
    hung phase by counting which method was called for which tool; a
    missing, reordered or swapped entry makes that diagnosis wrong.
    """
    # Arrange
    probe_cls = _get_fake_probe()
    target_cls = _get_probe_target()
    probe = probe_cls()
    target_t1 = _target(target_cls, "t1")
    target_t2 = _target(target_cls, "t2")
    # Act
    await probe.health(target_t1)
    await probe.ready(target_t1)
    await probe.health(target_t2)
    await probe.ready(target_t2)
    # Assert
    calls = _get_calls(probe)
    assert calls == [
        ("health", "t1"),
        ("ready", "t1"),
        ("health", "t2"),
        ("ready", "t2"),
    ], f"journal is {calls} — expected (method, tool) pairs in call order"


@pytest.mark.asyncio
async def test_fake_probe_calls_records_calls_that_answer_false() -> None:
    """A probe that keeps answering False is still journaled per call.

    The journal counts attempts, not successes: a hung phase is
    diagnosed from how many times the probe was asked, which is
    invisible in the answers themselves.
    """
    # Arrange
    probe_cls = _get_fake_probe()
    target_cls = _get_probe_target()
    probe = probe_cls(script={"t1": {"ready": None}})
    target = _target(target_cls, "t1")
    # Act
    for _ in range(3):
        await probe.ready(target)
    # Assert
    calls = _get_calls(probe)
    assert calls == [("ready", "t1")] * 3, (
        f"journal is {calls} — every asked-and-answered call must be "
        "recorded, false answers included"
    )


# ---------------------------------------------------------------------------
# The double never raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "script",
    [0, 1, 3, None],
    ids=["immediately", "after-1", "after-3", "never-true"],
)
async def test_fake_probe_never_raises_for_any_script_shape(script: int | None) -> None:
    """Repeated polling completes with a bool for every script shape.

    The double must absorb however long a deadline loop keeps polling
    it; an exception here would be a traceback in a manager test that
    was probing, not the scripted answer the test asked for.
    """
    # Arrange
    probe_cls = _get_fake_probe()
    target_cls = _get_probe_target()
    probe = probe_cls(script={"t1": {"health": script, "ready": script}})
    target = _target(target_cls, "t1")
    # Act / Assert
    for method_name in ("health", "ready"):
        for _ in range(5):
            try:
                answer = await getattr(probe, method_name)(target)
            except Exception as exc:
                pytest.fail(
                    f"FakeProbe.{method_name} raised {type(exc).__name__} "
                    f"({exc}) — the probe must answer a bool, never raise"
                )
            assert isinstance(answer, bool), (
                f"FakeProbe.{method_name} answered {answer!r}, expected a bool"
            )

"""Pins the Probe protocol and ProbeTarget (m2b plan §3 behaviour 9, §1.5).

The Probe/ProbeTarget import is deferred to call time, following the
deferred-import gate discipline (m2b plan §4), so the missing module
fails per test with an informative assertion rather than aborting
collection.  The no-HTTP guard is an AST scan of probes.py's source —
the module's *written* imports — with reach and precision proven on
in-memory decoys; the subject-missing case fails on the explicit
existence gate, not on an empty walk.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, Final, cast, get_type_hints

import pytest

# The exact field set of §1.5, in declaration order.
PROBE_TARGET_FIELDS: Final[tuple[str, ...]] = (
    "tool",
    "host",
    "port",
    "health_path",
    "ready_path",
)

PROBE_TARGET_ANNOTATIONS: Final[dict[str, Any]] = {
    "tool": str,
    "host": str,
    "port": int,
    "health_path": str,
    "ready_path": str,
}

# DECOY — every written import form the guard must catch: a plain
# import, a dotted import, a from-import and a runtime __import__.
_DECOY_HTTP_IMPORTS = """\
import requests
import urllib3.util
from httpx import AsyncClient


def load():
    return __import__("aiohttp")
"""

# BENIGN — stdlib imports and lookalike names that are not HTTP
# libraries and must not be flagged.
_BENIGN_IMPORTS = """\
import asyncio
import ssl
from urllib.parse import urlsplit
import requests_mock
"""


def _get_probes_module() -> ModuleType:
    """Import tool_swap.proxy.probes at call time, RED-safely.

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
    """Return the Probe protocol, RED-safely.

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
    """Return the ProbeTarget dataclass, RED-safely.

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


def _sig(signature: inspect.Signature) -> list[tuple[str, int]]:
    """(name, kind.value) pairs in declaration order, the comparable
    form of a signature (the m2a convention for signature pins)."""
    return [(p.name, int(p.kind.value)) for p in signature.parameters.values()]


_SourceReader = Callable[[], str]
_MessageScanner = Callable[[ast.Module], list[str]]


def _guard_detectors() -> tuple[Path, _SourceReader, _MessageScanner]:
    """(probes path, probes_source, http_import_messages) from the
    detector module, importing it at call time.

    The two detector slots are values, not callables: probes_source is
    a zero-arg source reader, http_import_messages takes an
    ast.Module. An Any slot would let a dropped call slip past the
    type checker.

    Raises:
        AssertionError: the detector module or a detector is missing.
    """
    try:
        module: ModuleType = importlib.import_module("tests.unit.proxy.probe_guard")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tests.unit.proxy.probe_guard is missing — create "
            "tests/unit/proxy/probe_guard.py with the import-scan "
            "detectors"
        ) from exc
    for name in ("PROBES_PATH", "probes_source", "http_import_messages"):
        if not hasattr(module, name):
            raise AssertionError(
                f"{name} is missing from tests/unit/proxy/probe_guard.py"
            )
    return module.PROBES_PATH, module.probes_source, module.http_import_messages


class _ConformantProbe:
    """A name-and-async stub of the two Probe members.

    runtime_checkable isinstance matches member *names* only, so the
    stub exists to pin that name-matching in the positive direction;
    the signature pins are the load-bearing assertions.
    """

    async def health(self, target: Any) -> bool:
        raise NotImplementedError("name-only stub; never called by the test")

    async def ready(self, target: Any) -> bool:
        raise NotImplementedError("name-only stub; never called by the test")


class _ProbeMissingReady:
    """A stub with only health — the negative half of the name-match."""

    async def health(self, target: Any) -> bool:
        raise NotImplementedError("name-only stub; never called by the test")


# ---------------------------------------------------------------------------
# The protocol — shape, signatures, asynchrony
# ---------------------------------------------------------------------------


def test_probe_is_runtime_checkable_protocol() -> None:
    """Probe is a Protocol decorated with @runtime_checkable.

    The manager type-checks injected probes with isinstance, which
    raises TypeError on a non-runtime-checkable protocol.
    """
    # Arrange
    probe_cls = _get_probe()
    # Act
    protocol_marker = getattr(probe_cls, "_is_protocol", False)
    checkable = isinstance(_ConformantProbe(), probe_cls)
    # Assert
    assert protocol_marker is True
    assert checkable is True


def test_probe_runtime_check_matches_on_member_names() -> None:
    """runtime_checkable isinstance accepts a conforming stub and
    rejects one missing ready.

    A second member renamed or dropped must fail here at the
    declaration, before any M3 implementer relies on the check.
    """
    # Arrange
    probe_cls = _get_probe()
    # Act
    conformant = isinstance(_ConformantProbe(), probe_cls)
    missing_ready = isinstance(_ProbeMissingReady(), probe_cls)
    # Assert
    assert conformant is True
    assert missing_ready is False


def test_probe_declares_exactly_the_two_methods() -> None:
    """The public surface is exactly health and ready — no more.

    A third method (say a merged is_ready) would collapse the
    STARTING/LOADING distinction §1.5 keeps separate.
    """
    # Arrange
    probe_cls = _get_probe()
    # Act
    public_names = sorted(n for n in dir(probe_cls) if not n.startswith("_"))
    # Assert
    assert public_names == ["health", "ready"]


@pytest.mark.parametrize("method_name", ["health", "ready"])
def test_probe_method_signature_is_pinned(method_name: str) -> None:
    """Each method is async def <name>(self, target: ProbeTarget) -> bool.

    The anti-drift pin for the seam M3 must implement: a renamed or
    re-ordered argument, a different annotation or a dropped async
    makes M3's real probe a different interface than the manager's.
    """
    # Arrange
    probe_cls = _get_probe()
    target_cls = _get_probe_target()
    method = getattr(probe_cls, method_name)
    # Act
    signature = inspect.signature(method)
    hints = get_type_hints(method)
    # Assert
    assert _sig(signature) == [
        ("self", inspect.Parameter.POSITIONAL_OR_KEYWORD.value),
        ("target", inspect.Parameter.POSITIONAL_OR_KEYWORD.value),
    ], f"{method_name} drifted from (self, target) — name, order or kind"
    assert hints == {"target": target_cls, "return": bool}, (
        f"{method_name} is annotated {hints}, expected "
        "(self, target: ProbeTarget) -> bool"
    )


@pytest.mark.parametrize("method_name", ["health", "ready"])
def test_probe_method_is_a_coroutine_function(method_name: str) -> None:
    """Both methods are coroutine functions.

    The seam is async by decision (§1.5): a sync method would force an
    executor hop in the manager or a signature change in M3.
    """
    # Arrange
    probe_cls = _get_probe()
    # Act
    is_async = inspect.iscoroutinefunction(getattr(probe_cls, method_name))
    # Assert
    assert is_async is True, (
        f"{method_name} is not async — the probe seam must stay async"
    )


# ---------------------------------------------------------------------------
# ProbeTarget — the address without the client
# ---------------------------------------------------------------------------


def test_probe_target_has_exactly_the_five_address_fields() -> None:
    """The exact §1.5 field set, in declaration order.

    A field no behaviour reads is a field whose meaning is guessed;
    an extra field smuggles vocabulary the target does not own.
    """
    # Act
    target_cls = _get_probe_target()
    fields = dataclasses.fields(target_cls)
    names = [f.name for f in fields]
    # Assert
    assert names == list(PROBE_TARGET_FIELDS), (
        f"ProbeTarget has fields {names}, expected {list(PROBE_TARGET_FIELDS)}"
    )


def test_probe_target_field_annotations_match_the_plan() -> None:
    """Each field carries §1.5's exact annotation.

    port as str or host as bytes would be a quiet type drift the
    signature pins on Probe cannot see.
    """
    # Act
    target_cls = _get_probe_target()
    hints = get_type_hints(target_cls)
    # Assert
    assert hints == PROBE_TARGET_ANNOTATIONS, (
        f"ProbeTarget annotations drifted: {hints}, expected {PROBE_TARGET_ANNOTATIONS}"
    )


def test_probe_target_carries_no_url_field() -> None:
    """No field name suggests a pre-composed URL.

    The probe composes the URL from host, port and the path fields; a
    url field would put HTTP vocabulary in a type that has no client
    (§1.5, D-B).
    """
    # Act
    target_cls = _get_probe_target()
    names = {f.name for f in dataclasses.fields(target_cls)}
    # Assert
    assert not {"url", "uri", "endpoint", "base_url"} & names, (
        f"ProbeTarget carries a URL-like field: "
        f"{sorted({'url', 'uri', 'endpoint', 'base_url'} & names)} — "
        "the probe composes the URL, the target holds only the address"
    )


def test_probe_target_is_frozen() -> None:
    """Mutating a ProbeTarget raises FrozenInstanceError.

    A target is an immutable address passed between components; a
    mutable one invites a probe (or manager) to rewrite it mid-flight.
    """
    # Arrange
    target_cls = _get_probe_target()
    target = target_cls(
        tool="t1",
        host="tswap-t1",
        port=8000,
        health_path="/health",
        ready_path="/ready",
    )
    # Act / Assert
    with pytest.raises(dataclasses.FrozenInstanceError):
        target.host = "other"  # type: ignore[misc]


def test_probe_target_is_a_slots_dataclass() -> None:
    """ProbeTarget is a slots=True dataclass: instances carry no
    __dict__.

    slots pin is cheap here and guards the declared shape: a
    slots-less refactor would allow attribute injection (t.url = ...),
    which the no-URL pin on the field set could not catch.
    """
    # Arrange
    target_cls = _get_probe_target()
    target = target_cls(
        tool="t1",
        host="tswap-t1",
        port=8000,
        health_path="/health",
        ready_path="/ready",
    )
    # Act / Assert
    assert dataclasses.is_dataclass(target_cls) is True
    assert hasattr(target, "__dict__") is False, (
        "ProbeTarget instances carry a __dict__ — slots=True was dropped"
    )


# ---------------------------------------------------------------------------
# The no-HTTP guard — detector non-vacuity, in-memory decoys
# ---------------------------------------------------------------------------


def test_http_import_detector_reports_decoy_imports() -> None:
    """The import scanner flags every written import form it must catch.

    Reach side of the non-vacuity proof: a plain import, a dotted
    import, a from-import and a runtime __import__ must each be
    reported with a line number.  The decoy is a string parsed with
    ast.parse; nothing is written to disk.
    """
    # Act
    _probes_path, _source, messages = _guard_detectors()
    found = messages(ast.parse(_DECOY_HTTP_IMPORTS))
    # Assert
    assert len(found) == 4, (
        "Guard is blind: the decoy carries four HTTP imports "
        "(requests, urllib3.util, httpx, aiohttp) but only these were "
        f"reported: {found}"
    )
    joined = " ".join(found)
    for name in ("requests", "urllib3", "httpx", "aiohttp"):
        assert name in joined, f"Guard is blind to {name!r}: no violation names it"


def test_http_import_detector_ignores_non_http_imports() -> None:
    """The import scanner does not flag stdlib or lookalike names.

    Precision side of the non-vacuity proof: urllib.parse is stdlib
    and requests_mock is a different top-level package; flagging
    either would disable the guard, which is worse than no guard.
    """
    # Act
    _probes_path, _source, messages = _guard_detectors()
    found = messages(ast.parse(_BENIGN_IMPORTS))
    # Assert
    assert not found, f"False positive on benign imports: {found}"


# ---------------------------------------------------------------------------
# The guard over the real module — strictly read-only
# ---------------------------------------------------------------------------


def test_probes_py_imports_no_http_library() -> None:
    """probes.py imports no HTTP library — D-B made executable.

    An M3 implementer satisfying the protocol with requests, httpx,
    urllib3 or aiohttp would add an undeclared dependency; the scan
    is over the module's written imports, so it catches an import that
    is present in the source even if no test executes it.
    """
    # Arrange — the subject-exists gate: an absence test that walks a
    # missing file would pass vacuously.
    probes_path, source, messages = _guard_detectors()
    assert probes_path.is_file(), (
        f"Guard subject missing: {probes_path} — create "
        "src/tool_swap/proxy/probes.py before the guard can police it"
    )
    # Act
    tree = ast.parse(source(), filename=str(probes_path))
    found = messages(tree)
    # Assert
    assert not found, (
        f"HTTP library imports found in src/tool_swap/proxy/probes.py: "
        f"{found}\n"
        "The probe is a seam with no client; the real probe arrives in "
        "M3 with the proxy's declared client (m2b plan §5 D-B)."
    )

"""M2b slice D, behaviour 12 — construction, injection, sixth contract.

Three claims, each failing for its own reason while the tree is red:

1. ``LifecycleManager`` holds exactly the injected ``backend``, ``probe``
   and ``clock`` — identity-wise, the way behaviour 20 pinned
   ``DockerBackend``'s client — and refuses ``None`` for the backend or
   the probe with ``TypeError`` at construction. The class does not
   exist yet, so these fail on a gate that names the missing class
   rather than on a module-level ``ImportError``. The three timeout
   arguments are plain scalars mirroring ``drive_readiness``: the plan's
   ``Timeouts`` type does not exist in ``src/`` and the decision is not
   to build one.

2. The sixth ``.importlinter`` contract — ``tool_swap.lifecycle`` and
   ``tool_swap.proxy`` must not import
   ``tool_swap.backend.docker_backend`` — ships with the pinned shape,
   and ``lint-imports`` reports all six contracts kept. Contract 5
   covers the SDK itself (``tool_swap -> docker``); nothing enforced
   the docker_backend direction until this contract. The non-vacuity
   half proves the shape has teeth on an in-memory grimp graph — the
   same differential behaviour 27 shipped — and bounds the source set
   to exactly the two named packages with a second decoy outside it.

3. The manager module, the probe seam and ``FakeBackend`` import, and
   the manager constructs, with the ``docker`` SDK blocked from the
   import system — the ``sys.meta_path`` blocker of behaviour 27, not a
   ``sys.modules`` deletion, which a fresh import would defeat.
"""

from __future__ import annotations

import configparser
import importlib
import os
import subprocess
import sys
from types import ModuleType
from typing import Any

import grimp
import pytest
from importlinter import configuration as _il_configuration
from importlinter.contracts.forbidden import ForbiddenContract

from tests.unit.test_docker_sdk_boundary import (
    ROOT,
    SRC_ROOT,
    _sdk_absent,
    _verify_blocker_live,
)
from tool_swap.backend.fake_backend import FakeBackend
from tool_swap.config.defaults import BUILT_IN_DEFAULTS
from tool_swap.config.schema import BackendConfig
from tool_swap.proxy.probes import FakeProbe
from tool_swap.utils.clock import ManualClock

# ForbiddenContract.check reads the application settings object, which
# the CLI populates once at import time; configuring here is a no-op
# where the boundary module already has.
_il_configuration.configure()  # type: ignore[no-untyped-call]

IMPORTLINTER_CONFIG = ROOT / ".importlinter"

#: The sixth contract's name, pinned from behaviour 12's ledger heading
#: (construction, injection, sixth contract).
LIFECYCLE_BACKEND_CONTRACT_NAME = (
    "The lifecycle and proxy layers never import the docker backend"
)

#: The two packages the sixth contract covers.
SIXTH_SOURCE_MODULES = ["tool_swap.lifecycle", "tool_swap.proxy"]

#: The module neither covered package may import.
SIXTH_FORBIDDEN_MODULE = "tool_swap.backend.docker_backend"

#: The decoy importer, inside the covered set.
DECOY_IMPORTER = "tool_swap.lifecycle.manager"

#: The decoy importer, outside the covered set.
_OUT_OF_SCOPE_IMPORTER = "tool_swap.api.ui"

#: The session options the in-process contract tests use: the shipped
#: root packages plus the top-level option the session requires
#: (import-linter 2.13, see test_docker_sdk_boundary's module docstring).
_SESSION_OPTIONS: dict[str, Any] = {
    "root_packages": ["tool_swap", "tool_swap_runtime"],
    "include_external_packages": "true",
}


def _pinned_sixth_contract_options() -> dict[str, Any]:
    """Return the sixth contract's options in the shipped INI shape.

    ``source_modules`` is the raw multi-line value exactly as the
    shipped section would carry it, so the shape-pinning test can
    compare it against a parsed section value-for-value.
    """
    return {
        "name": LIFECYCLE_BACKEND_CONTRACT_NAME,
        "type": "forbidden",
        "source_modules": "\n".join(SIXTH_SOURCE_MODULES),
        "forbidden_modules": SIXTH_FORBIDDEN_MODULE,
    }


def _sixth_contract_options() -> dict[str, Any]:
    """Return the pinned options in import-linter's raw shape.

    The in-memory non-vacuity tests build their contract from this
    literal so they prove the tool fact in the red phase, before the
    shape is in the tree: a multi-value option is a list, the way
    import-linter's INI reader (``_clean_section_config``) splits it.
    """
    options = _pinned_sixth_contract_options()
    options["source_modules"] = list(SIXTH_SOURCE_MODULES)
    return options


# ---------------------------------------------------------------------------
# Config-parsing helpers (mirrored from the M1/M2a boundary tests)
# ---------------------------------------------------------------------------


def _lint_imports_bin() -> list[str]:
    """Return the command to run lint-imports, the shared helper idiom."""
    venv_bin = ROOT / ".venv" / "bin" / "lint-imports"
    if venv_bin.exists():
        return [str(venv_bin)]
    import shutil

    path_bin = shutil.which("lint-imports")
    if path_bin:
        return [path_bin]
    return [
        sys.executable,
        "-c",
        "from importlinter.cli import lint_imports_command; lint_imports_command()",
    ]


def _parse_importlinter() -> configparser.ConfigParser:
    """Parse the shipped ``.importlinter`` into a ConfigParser."""
    parser = configparser.ConfigParser()
    parser.read_string(IMPORTLINTER_CONFIG.read_text())
    return parser


def _contract_sections(parser: configparser.ConfigParser) -> list[str]:
    """Return the names of every ``[importlinter:contract:N]`` section."""
    return [s for s in parser.sections() if s.startswith("importlinter:contract")]


def _section_for_name(
    parser: configparser.ConfigParser, contract_name: str
) -> configparser.SectionProxy:
    """Return the contract section whose ``name`` is ``contract_name``.

    Fails with a readable message listing the sections that DO exist
    when the wanted name is absent, so a red run is informative rather
    than a bare ``NoSectionError``.
    """
    for section in _contract_sections(parser):
        if parser.get(section, "name") == contract_name:
            return parser[section]
    existing = [f"{s} ({parser.get(s, 'name')!r})" for s in _contract_sections(parser)]
    pytest.fail(
        f"No contract section named {contract_name!r} in .importlinter. "
        f"Contract sections present: {existing}"
    )


def _clean_value(raw: str) -> Any:
    """Mirror import-linter's INI reader's multi-line handling."""
    if "\n" in raw:
        return [line.strip() for line in raw.strip().split("\n")]
    return raw


# ---------------------------------------------------------------------------
# Section 1 — construction and injection
# ---------------------------------------------------------------------------


def _manager_module() -> ModuleType:
    """Import ``tool_swap.lifecycle.manager`` at call time."""
    try:
        return importlib.import_module("tool_swap.lifecycle.manager")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.lifecycle.manager is missing — create "
            "src/tool_swap/lifecycle/manager.py"
        ) from exc


def _manager_class() -> type:
    """Return the ``LifecycleManager`` class from manager.py.

    Raises:
        AssertionError: the class is missing from manager.py; the
            message names the module and the expected name.
    """
    module = _manager_module()
    try:
        manager_class = module.LifecycleManager
    except AttributeError as exc:
        raise AssertionError(
            "LifecycleManager is missing from src/tool_swap/lifecycle/manager.py"
        ) from exc
    assert isinstance(manager_class, type), (
        f"LifecycleManager is not a class: {type(manager_class)!r}"
    )
    return manager_class


def _make_manager(manager_class: type, backend: Any, probe: Any, clock: Any) -> Any:
    """Construct the manager with a real ``BackendConfig`` and no timeouts.

    The timeout scalars are omitted so the constructor's own defaults
    apply; every test using this helper is indifferent to their values.
    """
    return manager_class(
        backend,
        probe=probe,
        clock=clock,
        backend_config=BackendConfig(),
    )


def test_constructor_stores_exactly_the_injected_backend() -> None:
    """The backend attribute IS the injected object, identity-wise.

    Arrange: a ``FakeBackend`` with nothing else to be confused with
    it. Act: construct the manager. Assert: the manager's ``backend``
    attribute is the same object, so a backend the constructor
    secretly built is not what the manager will use.
    """
    manager_class = _manager_class()
    backend = FakeBackend()
    manager = _make_manager(manager_class, backend, FakeProbe(), ManualClock())
    assert manager.backend is backend, (
        "the manager's backend attribute is not the injected object — "
        "the constructor constructed one instead of holding the injection"
    )


def test_constructor_stores_exactly_the_injected_probe() -> None:
    """The probe attribute IS the injected object, identity-wise."""
    manager_class = _manager_class()
    probe = FakeProbe()
    manager = _make_manager(manager_class, FakeBackend(), probe, ManualClock())
    assert manager.probe is probe, (
        "the manager's probe attribute is not the injected object — "
        "the constructor constructed one instead of holding the injection"
    )


def test_constructor_stores_exactly_the_injected_clock() -> None:
    """The clock attribute IS the injected object, identity-wise."""
    manager_class = _manager_class()
    clock = ManualClock()
    manager = _make_manager(manager_class, FakeBackend(), FakeProbe(), clock)
    assert manager.clock is clock, (
        "the manager's clock attribute is not the injected object — "
        "the constructor constructed one instead of holding the injection"
    )


def test_constructor_stores_backend_config_and_timeout_scalars() -> None:
    """backend_config is held by identity; the three timeouts by value.

    ``BackendConfig`` is a real object the constructor receives, so
    identity is its pin; the timeouts are plain numbers, so a manager
    that re-derives or re-packs them instead of holding the injection
    fails equality on the distinctive scalars passed here.
    """
    manager_class = _manager_class()
    backend_config = BackendConfig()
    manager = manager_class(
        FakeBackend(),
        probe=FakeProbe(),
        clock=ManualClock(),
        backend_config=backend_config,
        start_timeout=42.5,
        ready_timeout=31.5,
        probe_interval=0.25,
    )
    assert manager.backend_config is backend_config, (
        "the manager's backend_config attribute is not the injected object"
    )
    assert manager.start_timeout == 42.5, (
        "the manager's start_timeout is not the injected scalar: "
        f"{manager.start_timeout!r}"
    )
    assert manager.ready_timeout == 31.5, (
        "the manager's ready_timeout is not the injected scalar: "
        f"{manager.ready_timeout!r}"
    )
    assert manager.probe_interval == 0.25, (
        "the manager's probe_interval is not the injected scalar: "
        f"{manager.probe_interval!r}"
    )


def test_constructor_defaults_timeouts_to_the_built_in_values() -> None:
    """A manager built without timeouts carries the built-in values.

    The manager delegates to ``drive_readiness``, which already defaults
    its three scalars from ``BUILT_IN_DEFAULTS``; requiring them here
    would force every caller to re-state values with a single source of
    truth.
    """
    manager_class = _manager_class()
    manager = _make_manager(manager_class, FakeBackend(), FakeProbe(), ManualClock())
    assert manager.start_timeout == BUILT_IN_DEFAULTS["start_timeout"], (
        "a manager constructed without timeouts did not carry the built-in "
        "start_timeout"
    )
    assert manager.ready_timeout == BUILT_IN_DEFAULTS["ready_timeout"], (
        "a manager constructed without timeouts did not carry the built-in "
        "ready_timeout"
    )
    assert manager.probe_interval == BUILT_IN_DEFAULTS["probe_interval"], (
        "a manager constructed without timeouts did not carry the built-in "
        "probe_interval"
    )


def test_constructor_does_not_construct_anything_internally() -> None:
    """Construction performs no backend work and no clock movement.

    "No object is constructed internally" is observable through the
    two injected fakes' instruments: the backend's call journal must be
    empty and the manual clock must not have advanced. A constructor
    that pried the seam open, or slept, moves one of them.
    """
    manager_class = _manager_class()
    backend = FakeBackend()
    clock = ManualClock()
    _make_manager(manager_class, backend, FakeProbe(), clock)
    assert backend.calls == [], (
        f"constructing the manager made backend calls: {backend.calls}"
    )
    assert clock.now() == 0.0, (
        f"constructing the manager advanced the clock to {clock.now()}"
    )


def test_constructor_rejects_none_backend_with_type_error() -> None:
    """Constructing with ``None`` as the backend raises ``TypeError``.

    The ledger's error behaviour: a ``None`` backend is a programming
    error refused loudly at construction rather than at the first
    call, and ``TypeError`` is the type Python itself raises for a
    ``None`` where a concrete object is required.
    """
    manager_class = _manager_class()
    with pytest.raises(TypeError) as excinfo:
        _make_manager(manager_class, None, FakeProbe(), ManualClock())
    assert "backend" in str(excinfo.value), (
        f"the TypeError does not name the offending argument: {excinfo.value!s}"
    )


def test_constructor_rejects_none_probe_with_type_error() -> None:
    """Constructing with ``None`` as the probe raises ``TypeError``.

    The same refusal for the probe half of the seam, at construction
    time: a manager that only noticed the ``None`` on its first probe
    would have already decided readiness on nothing.
    """
    manager_class = _manager_class()
    with pytest.raises(TypeError) as excinfo:
        _make_manager(manager_class, FakeBackend(), None, ManualClock())
    assert "probe" in str(excinfo.value), (
        f"the TypeError does not name the offending argument: {excinfo.value!s}"
    )


# ---------------------------------------------------------------------------
# Section 2 — the sixth contract in .importlinter
# ---------------------------------------------------------------------------


def test_the_sixth_contract_pins_the_pinned_shape() -> None:
    """The sixth contract's section equals the pinned options exactly.

    Assert: it is a ``forbidden`` contract whose ``source_modules`` is
    exactly the two covered packages and whose ``forbidden_modules``
    is exactly ``tool_swap.backend.docker_backend`` — no option
    missing, none unexpected (in particular no ``ignore_imports``:
    unlike contract 5, nothing imports docker_backend legitimately).
    """
    parser = _parse_importlinter()
    section = _section_for_name(parser, LIFECYCLE_BACKEND_CONTRACT_NAME)
    shipped = {key: _clean_value(value) for key, value in section.items()}
    expected = {
        key: _clean_value(value)
        for key, value in _pinned_sixth_contract_options().items()
    }
    for key, value in expected.items():
        assert key in section, (
            f"contract {LIFECYCLE_BACKEND_CONTRACT_NAME!r} is missing {key!r}"
        )
        assert shipped[key] == value, (
            f"contract {LIFECYCLE_BACKEND_CONTRACT_NAME!r} option {key!r} "
            f"mismatch: shipped {shipped[key]!r}, pinned {value!r}"
        )
    unexpected = set(shipped) - set(expected)
    assert not unexpected, (
        f"contract {LIFECYCLE_BACKEND_CONTRACT_NAME!r} carries unpinned "
        f"options: {sorted(unexpected)}"
    )


def test_lint_imports_keeps_all_six_contracts() -> None:
    """lint-imports keeps all six contracts and reports ``6 kept``.

    Assert: exit 0, the sixth contract name appears in the output, and
    the tool's own summary line reads ``6 kept, 0 broken`` — so a
    silently-dropped or silently-matching-nothing contract fails here
    even if the name check were relaxed. The exact summary line is
    this file's to own, the way contract 5's is the boundary file's.
    """
    env = {**os.environ, "PYTHONPATH": str(SRC_ROOT)}
    result = subprocess.run(
        _lint_imports_bin() + ["--config", str(IMPORTLINTER_CONFIG)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"lint-imports failed with exit code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert LIFECYCLE_BACKEND_CONTRACT_NAME in combined, (
        f"Contract {LIFECYCLE_BACKEND_CONTRACT_NAME!r} is not named in "
        f"the lint-imports output.\nstdout: {result.stdout}"
        f"\nstderr: {result.stderr}"
    )
    assert "6 kept, 0 broken" in combined, (
        f"Expected the summary line to read '6 kept, 0 broken'.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Section 3 — the pinned shape has teeth (in-memory, nothing in src/)
# ---------------------------------------------------------------------------


def _build_graph() -> grimp.ImportGraph:
    """Build the real import graph with external packages included."""
    return grimp.build_graph(
        "tool_swap",
        "tool_swap_runtime",
        include_external_packages=True,
        cache_dir=None,
    )


def _sixth_contract() -> ForbiddenContract:
    """Construct the pinned contract from the pinned literal options."""
    options = _sixth_contract_options()
    return ForbiddenContract(
        name=options["name"],
        session_options=_SESSION_OPTIONS,
        contract_options=options,
    )


def _decoy_chains(check: Any, decoy_importer: str) -> list[list[dict[str, Any]]]:
    """Return the reported chains naming the decoy importer."""
    return [
        chain
        for data in check.metadata["invalid_chains"]
        for chain in data["chains"]
        if any(step["importer"] == decoy_importer for step in chain)
    ]


def test_the_sixth_contract_catches_a_decoy_violation() -> None:
    """The contract fails on a real violation and names the violator.

    The non-vacuity proof, in-memory only: the decoy is a graph-level
    edge — ``tool_swap.lifecycle.manager -> docker_backend`` — added
    to a throwaway graph via ``ImportGraph.add_import``. The
    differential (kept on the clean graph, broken with the decoy)
    isolates it as the sole cause of the failure, and the reported
    chain must name both the decoy importer and the forbidden module.
    A contract that would still pass with the forbidden import
    present is the vacuous version of behaviour 12's guard.
    """
    assert _sixth_contract().check(_build_graph(), False).kept, (
        "baseline: the pinned contract does not keep on the clean tree — "
        "the pinned options themselves are wrong"
    )

    decoy_graph = _build_graph()
    decoy_graph.add_import(
        importer=DECOY_IMPORTER,
        imported=SIXTH_FORBIDDEN_MODULE,
        line_number=999,
        line_contents="from tool_swap.backend.docker_backend import DockerBackend",
    )
    assert decoy_graph.find_matching_direct_imports(
        f"{DECOY_IMPORTER} -> {SIXTH_FORBIDDEN_MODULE}"
    ), "the decoy edge is not in the raw graph — this test would prove nothing"

    check = _sixth_contract().check(decoy_graph, False)
    assert not check.kept, (
        "the contract kept despite tool_swap.lifecycle.manager importing "
        "docker_backend — the contract is VACUOUS"
    )
    decoy_chains = _decoy_chains(check, DECOY_IMPORTER)
    assert decoy_chains, (
        f"no reported chain names the decoy importer {DECOY_IMPORTER}: "
        f"{check.metadata['invalid_chains']}"
    )
    assert any(
        step["imported"] == SIXTH_FORBIDDEN_MODULE
        for chain in decoy_chains
        for step in chain
    ), (
        "no reported chain names the forbidden module "
        f"{SIXTH_FORBIDDEN_MODULE}: {decoy_chains}"
    )


def test_the_sixth_contract_ignores_importers_outside_the_covered_packages() -> None:
    """The source set is exactly the two named packages, no wider.

    The mirror half of the differential: a decoy edge from a module
    outside the covered packages (``tool_swap.api.ui``) must NOT break
    the contract. If it did, the source would be the whole
    ``tool_swap`` package — contract 5's shape — and this contract
    would duplicate contract 5 instead of pinning the direction it was
    added for.
    """
    decoy_graph = _build_graph()
    decoy_graph.add_import(
        importer=_OUT_OF_SCOPE_IMPORTER,
        imported=SIXTH_FORBIDDEN_MODULE,
        line_number=999,
        line_contents="from tool_swap.backend.docker_backend import DockerBackend",
    )
    assert decoy_graph.find_matching_direct_imports(
        f"{_OUT_OF_SCOPE_IMPORTER} -> {SIXTH_FORBIDDEN_MODULE}"
    ), "the decoy edge is not in the raw graph — this test would prove nothing"

    check = _sixth_contract().check(decoy_graph, False)
    assert check.kept, (
        "the contract breaks on an importer outside "
        "tool_swap.lifecycle and tool_swap.proxy — its source set is "
        f"broader than the pinned two: {check.metadata}"
    )


# ---------------------------------------------------------------------------
# Section 4 — the manager is usable with the docker SDK blocked
# ---------------------------------------------------------------------------


def test_the_manager_constructs_with_the_sdk_absent() -> None:
    """manager, probes and FakeBackend work with the SDK blocked.

    The named guard, driven by ``FakeBackend``: the manager module
    fresh-imports (its package included — a lifecycle module that
    imported docker_backend would die on the fresh import), the probe
    seam imports, and the manager constructs with a ``FakeBackend``
    and a ``FakeProbe``. No ``docker*`` module may enter
    ``sys.modules`` as a result, and the pre-existing entries are
    restored identity-wise after the block.
    """
    snapshot = {
        key: module
        for key, module in sys.modules.items()
        if key == "docker" or key.startswith("docker.") or key.startswith("tool_swap")
    }
    with _sdk_absent():
        _verify_blocker_live()  # the decoys, re-run so the proof is not void
        with pytest.raises(ModuleNotFoundError) as excinfo:
            importlib.import_module("tool_swap.backend.docker_backend")
        assert excinfo.value.name == "docker", (
            f"the blocked import did not name the SDK: {excinfo.value.name!r}"
        )
        manager_module = importlib.import_module("tool_swap.lifecycle.manager")
        importlib.import_module("tool_swap.proxy.probes")
        backend = importlib.import_module(
            "tool_swap.backend.fake_backend"
        ).FakeBackend()
        probe = importlib.import_module("tool_swap.proxy.probes").FakeProbe()
        clock = importlib.import_module("tool_swap.utils.clock").ManualClock()
        manager = manager_module.LifecycleManager(
            backend,
            probe=probe,
            clock=clock,
            backend_config=object(),
        )
        assert manager.backend is backend

    leaked = {
        key for key in sys.modules if key == "docker" or key.startswith("docker.")
    } - {key for key in snapshot if key == "docker" or key.startswith("docker.")}
    assert not leaked, f"the manager import chain pulled in the SDK: {sorted(leaked)}"
    for key, module in snapshot.items():
        assert sys.modules.get(key) is module, (
            f"sys.modules[{key!r}] was not restored to the module it "
            "was — the global state leaked out of the test"
        )

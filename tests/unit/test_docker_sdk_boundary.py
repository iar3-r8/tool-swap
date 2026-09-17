"""RED step for M2a behaviour 27 — ``docker`` is importable from one
module only.

See ``plans/m2a-container-backend-seam.md`` behaviour 27 (§5): an
import-linter contract in ``.importlinter`` forbids the ``docker`` SDK
from every ``tool_swap`` module except
``tool_swap.backend.docker_backend``, mirroring the bentoml rule of
``plan/08_REPO_LAYOUT.md`` §2.  Two distinct claims are tested, and
they fail differently:

1. **The contract exists and ``lint-imports`` passes with it.**  The
   shape-pinning tests parse the shipped ``.importlinter`` (mirroring
   ``tests/unit/test_import_boundaries.py``'s configparser idiom and
   copied helpers); the subprocess test runs ``lint-imports`` and
   asserts all five contracts are kept.

2. **``fake_backend``, ``base`` and ``labels`` import with ``docker``
   blocked from the import system** — the load-bearing behavioural
   half: the fake must stay usable in an environment where the SDK is
   not installed at all.  ``docker`` is installed and already imported
   by the time this module runs (sibling test modules import it at
   module scope), so deleting it from ``sys.modules`` is not enough —
   a fresh import would just find it again on the path.  The method:
   a ``sys.meta_path`` finder that raises ``ModuleNotFoundError`` for
   the ``docker`` top level, installed ahead of the path finders,
   combined with evacuating the already-loaded ``docker*`` and
   ``tool_swap*`` entries so the subject imports are forced through
   the import system as *fresh* imports.  The decoy test proves the
   method with deliberately SDK-importing decoys (the technique of
   behaviour 20's guard,
   ``tests/unit/backend/test_docker_backend_ambient_env_guard.py``)
   plus a positive control that an unblocked module still resolves,
   and the subject test re-proves it before running.

**Proving the contract non-vacuous, without writing into ``src/``.**
The in-process tests build the real import graph with ``grimp``
(import-linter's own graph library; the build is a fraction of a
second) and construct the pinned-shape ``ForbiddenContract`` in
memory.  The decoy is a *graph-level* edge —
``tool_swap.backend.base -> docker`` — added via
``ImportGraph.add_import`` to a throwaway in-memory graph: no file is
written under ``src/`` and nothing is left behind.  The differential
(kept on the clean graph, broken with the decoy, chain naming the
decoy importer) isolates the decoy as the sole cause of the failure.
A second differential drops the ``ignore_imports`` line: the contract
must then break on the real, permitted ``docker_backend -> docker``
edge — proving the carve-out expression matches a real import (an
unmatched one would raise ``MissingImport`` under the default
``error`` alerting).

**Tool facts, established from the installed import-linter 2.13**
(``.venv/lib/python3.11/site-packages/importlinter/``), not from
memory:

- a ``forbidden`` contract may name an external module in
  ``forbidden_modules``, but only if the top-level session sets
  ``include_external_packages = true`` — otherwise ``check()`` raises
  ``ValueError("The top level configuration must have
  include_external_packages=True when there are external forbidden
  modules.")`` (``contracts/forbidden.py``,
  ``_check_external_forbidden_modules``);
- external forbidden modules must be the package's top-level name —
  subpackages raise ``ValueError`` — so the forbidden module is
  ``docker``, not ``docker.errors`` or ``docker.types``;
- the permitted module is carved out with the contract's
  ``ignore_imports`` option, an import expression in the form
  ``"importer -> imported"`` (``domain/fields.py``,
  ``ImportExpressionField``);
- with ``include_external_packages=True`` the external package enters
  the graph as a single squashed module — a probe of
  ``grimp.build_graph`` shows ``docker`` and only ``docker`` among
  the ``docker*`` names — so each importing module contributes one
  edge and the chain search sees it directly.

**The RED gate.**  The contract is not in the tree yet, so the
session-option, shape and five-names tests fail individually, and the
subprocess test fails on the ``5 kept`` summary line — with their
assertions present and reachable, never aborting pytest collection.
The non-vacuity tests (built from the pinned literal options) and the
SDK-absent tests guard machinery that already holds and are expected
to pass in the red phase, which is what makes the subject tests
trustworthy once the contract lands.

Conventions: pytest, AAA, Google-style docstrings, Black at 88
columns, ruff, ``filterwarnings = "error"`` — no fixture emits a
warning, and no test asserts a docker or import-linter fact from
memory.
"""

from __future__ import annotations

import configparser
import importlib
import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import grimp
import pytest
from importlinter import configuration as _il_configuration
from importlinter.contracts.forbidden import ForbiddenContract

# ``ForbiddenContract.check`` reads the application ``settings`` object
# (``settings.TIMER``), which the CLI and ``importlinter.api`` populate
# exactly once at import time; this module drives ``check()`` in
# process, so it configures the settings itself.  ``configure()`` only
# updates a dict, so calling it where the CLI already has is a no-op.
# import-linter 2.13 ships ``configuration.py`` untyped, hence the
# ignore under mypy strict.
_il_configuration.configure()  # type: ignore[no-untyped-call]

ROOT = Path(__file__).resolve().parents[2]  # repo root
SRC_ROOT = ROOT / "src"
IMPORTLINTER_CONFIG = ROOT / ".importlinter"

#: The fifth contract's name, pinned from behaviour 27's ledger heading
#: ("docker is importable from one module only").
DOCKER_CONTRACT_NAME = "The docker SDK is importable from one module only"

#: The four names pinned by behaviour 7 (``tests/unit/test_imports.py``)
#: and behaviour 26 (``tests/unit/test_import_boundaries.py``), quoted
#: verbatim.
_PREVIOUS_CONTRACT_NAMES = frozenset(
    {
        "Router and runtime are strictly separate",
        "Router and runtime are strictly separate (reverse)",
        "The config layer is a leaf",
        "The schema compiler does not depend on the pydantic config models",
    }
)

#: The module the SDK is forbidden from, and the one module it is
#: permitted from.
FORBIDDEN_MODULE = "docker"
ALLOWED_IMPORTER = "tool_swap.backend.docker_backend"

#: The three seam modules the plan names: they must import with the
#: SDK absent.
_SEAM_MODULES = (
    "tool_swap.backend.base",
    "tool_swap.backend.labels",
    "tool_swap.backend.fake_backend",
)

#: The session options the in-process contract tests use: the shipped
#: root packages plus the top-level option that makes an external
#: forbidden module legal (import-linter 2.13, see the module
#: docstring).
_SESSION_OPTIONS: dict[str, Any] = {
    "root_packages": ["tool_swap", "tool_swap_runtime"],
    "include_external_packages": "true",
}


def _pinned_contract_options() -> dict[str, Any]:
    """Return the contract options behaviour 27 pins, verbatim.

    The in-process non-vacuity tests build their contract from this
    literal so they prove the tool fact (the shape has teeth) in the
    red phase, before the shape is in the tree; the shape-pinning test
    asserts the shipped section equals it, so the two cannot drift.
    """
    return {
        "name": DOCKER_CONTRACT_NAME,
        "type": "forbidden",
        "source_modules": "tool_swap",
        "forbidden_modules": FORBIDDEN_MODULE,
        "ignore_imports": f"{ALLOWED_IMPORTER} -> {FORBIDDEN_MODULE}",
    }


# ---------------------------------------------------------------------------
# Config-parsing helpers (mirrored from tests/unit/test_import_boundaries.py)
# ---------------------------------------------------------------------------


def _lint_imports_bin() -> list[str]:
    """Return the command to run lint-imports.

    Returns a list suitable for ``subprocess.run``.

    Tries the venv path first (local development), then falls back to
    finding the executable on PATH (GitHub Actions CI where pip
    installs to the system Python location).  If neither works, uses
    ``python -c`` to invoke the CLI directly.

    Mirrored from ``tests/unit/test_import_boundaries.py`` (the M1
    file keeps its own copy; the M0 file's copy is what the M1 plan
    item pins as the precedent).
    """
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
    """Parse ``.importlinter`` into a ConfigParser.

    The file is INI-shaped: an ``[importlinter]`` section plus one
    ``[importlinter:contract:N]`` section per contract, with
    multi-line values on indented continuation lines (handled
    natively by configparser).
    """
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
    """Mirror import-linter's INI reader's multi-line handling.

    ``adapters/user_options.py`` (``_clean_section_config``) splits a
    value containing newlines into a stripped list; a single-line
    value stays a string.
    """
    if "\n" in raw:
        return [line.strip() for line in raw.strip().split("\n")]
    return raw


def _section_options(section: configparser.SectionProxy) -> dict[str, Any]:
    """Return a section's options in import-linter's raw shape."""
    return {key: _clean_value(value) for key, value in section.items()}


# ---------------------------------------------------------------------------
# Section 1 — the contract exists in .importlinter, with the pinned shape
# ---------------------------------------------------------------------------


def test_session_option_include_external_packages_is_true() -> None:
    """The shipped config sets ``include_external_packages = true``.

    Without it the external forbidden module ``docker`` makes
    ``lint-imports`` raise ``ValueError`` about the *configuration*
    (import-linter 2.13, ``contracts/forbidden.py``,
    ``_check_external_forbidden_modules``) rather than check anything.
    Pinning the option is the anti-drift anchor for that tool fact: a
    config that names an external module without the option is the
    silently-broken version of behaviour 27.

    Arrange: parse the shipped ``.importlinter``.
    Act: read the top-level ``include_external_packages`` option.
    Assert: it is present and ``true``.
    """
    parser = _parse_importlinter()
    assert parser.has_option("importlinter", "include_external_packages"), (
        ".importlinter must set include_external_packages = true at the "
        "top level; without it the external forbidden module 'docker' "
        "makes lint-imports raise ValueError instead of checking anything"
    )
    assert parser.get("importlinter", "include_external_packages").strip() == "true"


def test_the_docker_contract_pins_the_pinned_shape() -> None:
    """The fifth contract's section equals the pinned options exactly.

    Arrange: parse ``.importlinter`` and locate the section named
    ``The docker SDK is importable from one module only``.
    Act: read its options in import-linter's raw shape.
    Assert: it is a ``forbidden`` contract with source exactly
    ``tool_swap``, forbidden exactly ``docker`` (the top-level name —
    import-linter rejects subpackages of external packages), and the
    carve-out ``ignore_imports`` exactly
    ``tool_swap.backend.docker_backend -> docker`` — no option
    missing, none unexpected.
    """
    parser = _parse_importlinter()
    section = _section_for_name(parser, DOCKER_CONTRACT_NAME)
    shipped = _section_options(section)
    expected = _pinned_contract_options()
    for key, value in expected.items():
        assert key in section, f"contract {DOCKER_CONTRACT_NAME!r} is missing {key!r}"
        assert shipped[key] == value, (
            f"contract {DOCKER_CONTRACT_NAME!r} option {key!r} mismatch: "
            f"shipped {shipped[key]!r}, pinned {value!r}"
        )
    unexpected = set(shipped) - set(expected)
    assert not unexpected, (
        f"contract {DOCKER_CONTRACT_NAME!r} carries unpinned options: "
        f"{sorted(unexpected)}"
    )


def test_the_five_contract_names_are_exactly_the_pinned_set() -> None:
    """The contract names in .importlinter are exactly the pinned five.

    Arrange: parse the shipped ``.importlinter``.
    Act: collect the ``name`` value of every contract section.
    Assert: the SET of names equals the pinned five — M0's two,
    M1's two, and behaviour 27's one.  Prints missing and unexpected
    names separately, mirroring the M1 anti-drift pin.
    """
    parser = _parse_importlinter()
    shipped = {parser.get(s, "name") for s in _contract_sections(parser)}
    expected = _PREVIOUS_CONTRACT_NAMES | {DOCKER_CONTRACT_NAME}
    missing = expected - shipped
    unexpected = shipped - expected
    assert not missing and not unexpected, (
        f".importlinter contract names do not equal the expected five.\n"
        f"Missing: {sorted(missing)}\n"
        f"Unexpected: {sorted(unexpected)}\n"
        f"Shipped: {sorted(shipped)}"
    )


# ---------------------------------------------------------------------------
# Section 2 — lint-imports passes with the contract, all five kept
# ---------------------------------------------------------------------------


def test_lint_imports_keeps_all_five_contracts() -> None:
    """lint-imports keeps all five contracts and reports ``5 kept``.

    Arrange: locate the lint-imports binary (the M0/M1 helper idiom).
    Act: run ``lint-imports --config .importlinter`` with
    ``PYTHONPATH=src`` in the repo root.
    Assert: exit 0, each of the five contract names appears in the
    output, and the tool's own summary line reads ``5 kept, 0 broken``
    — so a silently-dropped or silently-matching-nothing contract
    fails here even if the name check were relaxed.
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
    for name in sorted(_PREVIOUS_CONTRACT_NAMES | {DOCKER_CONTRACT_NAME}):
        assert name in combined, (
            f"Contract {name!r} is not named in the lint-imports output.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    assert "5 kept, 0 broken" in combined, (
        f"Expected the summary line to read '5 kept, 0 broken'.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Section 3 — the pinned shape has teeth (in-memory, nothing written to src/)
# ---------------------------------------------------------------------------


def _build_graph() -> grimp.ImportGraph:
    """Build the real import graph with external packages included.

    Caching is disabled so every test sees a fresh graph; the build is
    a fraction of a second (rust grimp, ~63 modules).
    """
    return grimp.build_graph(
        "tool_swap",
        "tool_swap_runtime",
        include_external_packages=True,
        cache_dir=None,
    )


def _docker_contract() -> ForbiddenContract:
    """Construct the pinned contract from the pinned literal options."""
    options = _pinned_contract_options()
    return ForbiddenContract(
        name=options["name"],
        session_options=_SESSION_OPTIONS,
        contract_options=options,
    )


def test_the_docker_contract_is_kept_on_the_clean_tree() -> None:
    """The pinned options keep on the current real tree (no decoy).

    The baseline half of the non-vacuity differential: the contract
    as pinned must hold on the tree as shipped, i.e. the carve-out
    covers exactly the one permitted importer and nothing more is
    needed.  If a second module ever imports the SDK, this test
    breaks — which is the point.

    Arrange: the pinned contract and a fresh real graph.
    Act: run the contract's check on the graph.
    Assert: the check reports the contract kept.
    """
    check = _docker_contract().check(_build_graph(), False)
    assert check.kept, (
        "The pinned contract breaks on the clean tree — the pinned "
        f"options are wrong: {check.metadata}"
    )


def test_the_docker_contract_catches_a_decoy_violation() -> None:
    """The contract fails on a real violation and names the violator.

    The non-vacuity proof, in-memory only: the decoy is a *graph-level*
    edge — ``tool_swap.backend.base -> docker`` — added to a throwaway
    graph via ``ImportGraph.add_import``.  No file is written under
    ``src/`` and nothing is left behind: the decoy exists only in the
    in-memory graph, and the differential (kept on the clean graph,
    broken with the decoy) isolates it as the sole cause of the
    failure.  A contract that would still pass if ``base.py``
    imported ``docker`` is the vacuous version of behaviour 27, and
    this test fails it.

    Arrange: two fresh real graphs — one clean, one with the decoy
    edge, whose presence in the raw graph is asserted before the
    check so the "broken" result cannot be explained away.
    Act: run the pinned contract on each.
    Assert: clean keeps; decoy breaks, and a reported chain names the
    decoy importer and the forbidden module.
    """
    assert _docker_contract().check(_build_graph(), False).kept, (
        "baseline: the pinned contract does not keep on the clean tree — "
        "the pinned options themselves are wrong"
    )

    decoy_graph = _build_graph()
    decoy_graph.add_import(
        importer="tool_swap.backend.base",
        imported=FORBIDDEN_MODULE,
        line_number=999,
        line_contents="import docker",
    )
    assert decoy_graph.find_matching_direct_imports(
        "tool_swap.backend.base -> docker"
    ), "the decoy edge is not in the raw graph — this test would prove nothing"

    check = _docker_contract().check(decoy_graph, False)
    assert not check.kept, (
        "the contract kept despite tool_swap.backend.base importing "
        "docker — the contract is VACUOUS"
    )
    decoy_chains = [
        chain
        for data in check.metadata["invalid_chains"]
        for chain in data["chains"]
        if any(step["importer"] == "tool_swap.backend.base" for step in chain)
    ]
    assert decoy_chains, (
        "no reported chain names the decoy importer "
        f"tool_swap.backend.base: {check.metadata['invalid_chains']}"
    )
    assert any(
        step["imported"] == FORBIDDEN_MODULE for chain in decoy_chains for step in chain
    ), f"no reported chain names the forbidden module: {decoy_chains}"


def test_the_ignore_line_is_load_bearing() -> None:
    """Without ``ignore_imports`` the contract breaks on the permitted edge.

    The carve-out must match a *real* import: with the default
    unmatched-ignoring alerting (``error``), an expression matching
    nothing raises ``MissingImport`` at check time, and an expression
    matching the permitted ``docker_backend -> docker`` edge is what
    keeps the clean tree.  Dropping the option therefore breaks the
    contract — and the broken chain must name the permitted module,
    the differential that proves the line does real work instead of
    silently matching nothing.

    Arrange: the pinned contract minus its ``ignore_imports`` option,
    and a fresh real graph.
    Act: run the stripped contract.
    Assert: it breaks, and a reported chain names
    ``tool_swap.backend.docker_backend -> docker``.
    """
    options = {
        key: value
        for key, value in _pinned_contract_options().items()
        if key != "ignore_imports"
    }
    contract = ForbiddenContract(
        name=options["name"],
        session_options=_SESSION_OPTIONS,
        contract_options=options,
    )
    check = contract.check(_build_graph(), False)
    assert not check.kept, (
        "the contract without ignore_imports kept on the clean tree — "
        "the carve-out matches nothing and the contract enforces nothing"
    )
    chains = [
        chain for data in check.metadata["invalid_chains"] for chain in data["chains"]
    ]
    assert any(
        step["importer"] == ALLOWED_IMPORTER and step["imported"] == FORBIDDEN_MODULE
        for chain in chains
        for step in chain
    ), f"no reported chain names the permitted importer: {chains}"


# ---------------------------------------------------------------------------
# Section 4 — the seam modules import with the SDK absent
# ---------------------------------------------------------------------------


class _DockerImportBlocker:
    """A ``sys.meta_path`` finder that makes the ``docker`` SDK look absent.

    Raises ``ModuleNotFoundError`` for the ``docker`` top level and
    every submodule, and returns ``None`` for everything else so the
    normal finders handle all other imports.  Installed at the front
    of ``sys.meta_path`` it is consulted *before* the path finders, so
    a fresh import of ``docker`` cannot be satisfied from
    site-packages — which is the difference between this and deleting
    the module from ``sys.modules``, where the path finders would
    simply find it again.
    """

    def find_spec(
        self, fullname: str, path: object = None, target: object = None
    ) -> None:
        """Raise for the SDK, return ``None`` for everything else.

        Args:
            fullname: The name being imported.
            path: The path to search (unused; the import system
                supplies it).
            target: The module the import is for (unused).

        Raises:
            ModuleNotFoundError: ``fullname`` is ``docker`` or a
                ``docker.*`` submodule.
        """
        if fullname == FORBIDDEN_MODULE or fullname.startswith(FORBIDDEN_MODULE + "."):
            raise ModuleNotFoundError(
                f"No module named {fullname!r} (blocked by behaviour 27)",
                name=fullname,
            )
        return None


@contextmanager
def _sdk_absent() -> Iterator[None]:
    """Make the ``docker`` SDK look absent for the duration of the block.

    Saves and restores the exact ``sys.modules`` entries it touches
    (every ``docker*`` and ``tool_swap*`` module) and the meta_path
    blocker, so no other test can observe the evacuation.  The
    ``tool_swap*`` evacuation is what forces the subject imports to be
    *fresh* imports rather than handouts of already-imported module
    objects — a subject module already loaded would import "without
    the SDK" for the wrong reason.
    """
    saved: dict[str, Any] = {}
    for key in list(sys.modules):
        if (
            key == FORBIDDEN_MODULE
            or key.startswith(FORBIDDEN_MODULE + ".")
            or key == "tool_swap"
            or key.startswith("tool_swap.")
        ):
            saved[key] = sys.modules.pop(key)
    blocker = _DockerImportBlocker()
    sys.meta_path.insert(0, blocker)
    try:
        yield
    finally:
        try:
            sys.meta_path.remove(blocker)
        finally:
            sys.modules.update(saved)


def _verify_blocker_live() -> None:
    """Assert the blocker really blocks the SDK, before the subject runs.

    The decoys are deliberately SDK-importing — one per import form
    the seam could drift into — ``exec``ed in memory, the technique of
    behaviour 20's guard.  A blocker that had silently failed to block
    would make the subject test pass vacuously, so the proof is a
    separate step.  The positive control (an unblocked stdlib module
    still resolves) guards against the opposite failure — a blocker
    that fails *every* import and makes the subject pass because
    nothing can import anything.

    Raises:
        AssertionError: a decoy import did not raise
            ``ModuleNotFoundError`` naming ``docker``, or the
            positive control stopped resolving.
    """
    for label, source in (
        ("import docker", "import docker\n"),
        ("from docker import DockerClient", "from docker import DockerClient\n"),
    ):
        with pytest.raises(ModuleNotFoundError) as excinfo:
            exec(compile(source, f"<decoy:{label}>", "exec"), {})
        assert excinfo.value.name == FORBIDDEN_MODULE, (
            f"decoy {label!r} raised without naming {FORBIDDEN_MODULE!r} — "
            "the blocker is not the cause"
        )
    assert "mailcap" not in sys.modules, (
        "mailcap is already imported — the positive control below would be vacuous"
    )
    assert importlib.util.find_spec("mailcap") is not None, (
        "the blocker blocks unblocked modules too — it fails every "
        "import and the subject test would pass vacuously"
    )


def test_the_sdk_absent_blocker_blocks_docker_imports() -> None:
    """The blocker makes the SDK look absent, and only the SDK.

    Arrange: the blocker installed and the already-loaded ``docker*``
    entries evacuated (the ``_sdk_absent`` block), then the decoys and
    positive control.
    Act/Assert: a fresh ``import docker`` and
    ``from docker import DockerClient`` — the two forms the seam
    could drift into — each raise ``ModuleNotFoundError`` naming
    ``docker``; ``find_spec`` for an unblocked stdlib module still
    resolves.

    Expected to pass in the red phase — it verifies the guard's
    machinery, not the contract.
    """
    with _sdk_absent():
        _verify_blocker_live()


def test_the_seam_modules_import_with_the_sdk_absent() -> None:
    """``base``, ``labels`` and ``fake_backend`` import, and the fake
    constructs, with the SDK blocked from the import system.

    The load-bearing half of behaviour 27: the claim is *behavioural*,
    not structural — the fake must be usable in an environment where
    the SDK is not installed at all, which is what ``FakeBackend``
    exists for.  "Usable" is pinned to what this behaviour delivers:
    the three named modules fresh-import and ``FakeBackend()``
    constructs, with no ``docker*`` module entering ``sys.modules`` as
    a result — the protocol methods themselves are behaviour 10-13's
    and are not exercised here.

    Arrange: the ``_sdk_absent`` block, the blocker re-proven live
    with the decoys first (behaviour 20's guard pattern), and the
    pre-test ``sys.modules`` snapshot for the restoration assertion.
    Act: fresh-import the three seam modules and construct a
    ``FakeBackend``.
    Assert: the imports succeed and no ``docker*`` module was
    imported; after the block, every snapshot entry — the original
    ``docker*`` *and* ``tool_swap*`` module objects — is back in
    ``sys.modules`` identity-wise, and the ``docker*`` key set is
    exactly the pre-test one.
    """
    snapshot = {
        key: module
        for key, module in sys.modules.items()
        if key == FORBIDDEN_MODULE
        or key.startswith(FORBIDDEN_MODULE + ".")
        or key == "tool_swap"
        or key.startswith("tool_swap.")
    }
    with _sdk_absent():
        _verify_blocker_live()  # the decoys, re-run so the proof is not void
        imported = {name: importlib.import_module(name) for name in _SEAM_MODULES}
        backend = imported["tool_swap.backend.fake_backend"].FakeBackend()
        assert all(module is not None for module in imported.values())
        assert backend is not None

    leaked = {
        key
        for key in sys.modules
        if key == FORBIDDEN_MODULE or key.startswith(FORBIDDEN_MODULE + ".")
    } - {
        key
        for key in snapshot
        if key == FORBIDDEN_MODULE or key.startswith(FORBIDDEN_MODULE + ".")
    }
    assert not leaked, (
        f"the seam modules imported the SDK as a side effect: {sorted(leaked)}"
    )
    for key, module in snapshot.items():
        assert sys.modules.get(key) is module, (
            f"sys.modules[{key!r}] was not restored to the module it "
            "was — the global state leaked out of the test"
        )

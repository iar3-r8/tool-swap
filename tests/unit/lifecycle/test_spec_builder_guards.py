"""The two boundary guards on the config-to-spec builder (m2b plan §3,
behaviour 4 and §6.3).

Guard 1 extends M2a's one-parser boundary (m2a §4.2) to
``src/tool_swap/lifecycle/`` — the directory the backend walk does not
cover, and the only place the ``ParsedMount -> MountSpec`` conversion
happens.  Guard 2 pins that the builder reads no backend-named key out
of a ``.values`` mapping: those four keys are present-but-wrong there
(m2b §6.3).  The detectors are pure functions over an ``ast.Module``
shipped in ``spec_builder_guards.py``; the import is deferred to call
time so the missing module fails per test, not at collection.
Non-vacuity is proven with in-memory decoys — string constants parsed
with ``ast.parse``, never written to disk, so nothing lands under
``src/``.
"""

from __future__ import annotations

import ast
import importlib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from tool_swap.config.defaults import BUILT_IN_DEFAULTS

ROOT = Path(__file__).resolve().parents[3]  # repository root
LIFECYCLE_DIR = ROOT / "src" / "tool_swap" / "lifecycle"

# The keys the backend: block owns.  All four are present in
# ResolvedTool.values, always carrying the built-in value, because the
# backend: block is not a resolver layer (m2b plan §6.3).
BACKEND_KEYS = frozenset(
    {"network", "container_prefix", "label_namespace", "gpu_runtime"}
)

# DECOY — a second mount parser under lifecycle/: the duplicate
# tool_swap.config.validate.parse_mount that m2a §4.2 forbids.
_DECOY_SECOND_PARSE_MOUNT = '''\
def parse_mount(entry: str) -> tuple[str, str]:
    """DECOY: a second mount parser under src/tool_swap/lifecycle/."""
    parts = entry.split(":")
    return parts[0], parts[1]
'''

# DECOY — a mount-string split that does not reuse the name.
_DECOY_RE_SPLIT = '''\
def reparse(entry: str) -> list[str]:
    """DECOY: a regex variant of the mount-string split."""
    import re

    return re.split(":", entry)
'''

# DECOY — a helper that splits on the mount separator.
_DECOY_SPLIT_FIELDS = '''\
def split_fields(entry: str) -> tuple[str, str, str]:
    """DECOY: a helper that splits a mount string by hand."""
    host, _, container = entry.partition(":")
    return host, container, ""
'''

# BENIGN — a colons-and-splits module that is not mount parsing: a
# docstring colon, a dict-literal key, a split on another separator,
# and a literal ":" argument carried by a non-first argument.
_BENIGN_MODULE = '''\
"""Docstring with a colon: and other benign punctuation."""

SEPARATORS = {":": "colon", "-": "dash"}


def split_fields(entry: str) -> list[str]:
    """Split on whitespace — not on the mount separator."""
    return entry.split(" ")


def describe(text: str, limit: int = 1) -> list[str]:
    """A later argument or keyword carrying the separator is not the
    split idiom."""
    return text.split("::", limit)
'''

# DECOY — a builder that reads a backend-named key out of .values:
# the §6.3 trap, compiles and type-checks and stamps the built-in
# namespace on every container.
_DECOY_VALUES_READ = '''\
def build(resolved, cfg, image):
    """DECOY: a builder that reads a backend value from values."""
    port = resolved.values["container_port"]
    namespace = resolved.values["label_namespace"]
    return (port, namespace, image)
'''

# BENIGN — the builder's legitimate .values reads: a tool-level key
# and a bare local called values that is not a ResolvedTool attribute.
_BENIGN_VALUES_MODULE = '''\
def build(resolved, cfg, image):
    """Legitimate: tool-level keys from values, backend keys from cfg."""
    port = resolved.values["container_port"]
    mounts = resolved.values["mounts"]
    return (port, mounts, cfg.label_namespace, image)


def summarize(counts):
    """A bare local called values is not a ResolvedTool read."""
    values = counts["total"]
    return values
'''


def _guards() -> ModuleType:
    """Return the guard detector module, importing it at call time.

    Raises:
        AssertionError: the module or a detector is missing; the
            message names the file to create or amend.
    """
    try:
        module: ModuleType = importlib.import_module(
            "tests.unit.lifecycle.spec_builder_guards"
        )
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tests.unit.lifecycle.spec_builder_guards is missing — create "
            "tests/unit/lifecycle/spec_builder_guards.py with the guard "
            "detector functions"
        ) from exc
    for name in (
        "lifecycle_py_files",
        "spec_builder_source",
        "BACKEND_KEYS",
        "mount_split_messages",
        "parse_mount_name_offenders",
        "scan_mount_violations",
        "scan_values_reads",
    ):
        if not hasattr(module, name):
            raise AssertionError(
                f"{name} is missing from tests/unit/lifecycle/spec_builder_guards.py"
            )
    return module


def _detector(name: str) -> Callable[..., object]:
    """Return one named detector from the guard module."""
    return getattr(_guards(), name)


def _lifecycle_sources() -> list[tuple[str, str]]:
    """(relative path, source) for every lifecycle .py file, read-only."""
    files = _guards().lifecycle_py_files()
    return [(str(p.relative_to(ROOT)), p.read_text(encoding="utf-8")) for p in files]


# ---------------------------------------------------------------------------
# Guard 2's key set — pinned to the config layer's named source of truth
# ---------------------------------------------------------------------------


def test_backend_key_set_is_subset_of_builtin_defaults() -> None:
    """The four backend-named keys are a subset of BUILT_IN_DEFAULTS.

    Pins the guard's key set to the config layer's named source of
    truth rather than a restatement: it fails if BUILT_IN_DEFAULTS
    sheds one of the four, so the guard's scope must change with it.
    The check is a subset, not an exact match, because the four —
    the keys the spec builder consumes from BackendConfig — cannot
    be derived from BUILT_IN_DEFAULTS's eight backend keys without
    restating them.  A fifth backend key added to BUILT_IN_DEFAULTS
    does not fail this pin.
    """
    assert set(BUILT_IN_DEFAULTS) >= BACKEND_KEYS, (
        "The guard's backend key set no longer matches the keys "
        "present-but-wrong in ResolvedTool.values: "
        f"{sorted(BACKEND_KEYS - set(BUILT_IN_DEFAULTS))} is not a key of "
        "BUILT_IN_DEFAULTS (src/tool_swap/config/defaults.py)"
    )


# ---------------------------------------------------------------------------
# Subject-exists — the walk has a non-vacuous target
# ---------------------------------------------------------------------------


def test_lifecycle_package_exists_and_is_non_empty() -> None:
    """The walked lifecycle directory exists and contains .py files.

    A guard that asserts over a missing or empty directory proves
    nothing: if src/tool_swap/lifecycle/ disappeared, the walk would
    find zero modules and the violation tests would pass against a
    vacuum.
    """
    assert LIFECYCLE_DIR.is_dir(), (
        f"Guard subject missing: {LIFECYCLE_DIR} — the boundary guard "
        "would pass vacuously."
    )
    files = _guards().lifecycle_py_files()
    assert files, (
        f"No .py files under {LIFECYCLE_DIR} — the boundary guard would pass vacuously."
    )
    assert any(p.name == "__init__.py" for p in files), (
        f"{LIFECYCLE_DIR} lost its __init__.py — the lifecycle package "
        "is no longer a package the guard can reason about."
    )


def test_spec_builder_is_within_the_walked_directory() -> None:
    """spec_builder.py is one of the files the walk scans.

    The guards scan src/tool_swap/lifecycle/ as a directory walk; if
    the builder moved elsewhere, the walk would police the wrong
    tree and pass against a vacuum.
    """
    files = _guards().lifecycle_py_files()
    assert LIFECYCLE_DIR.joinpath("spec_builder.py") in files, (
        f"spec_builder.py is not under {LIFECYCLE_DIR} — the directory "
        "walk would no longer cover the config-to-spec builder."
    )


# ---------------------------------------------------------------------------
# Guard 1 — mount parsing — detector non-vacuity, in-memory decoys
# ---------------------------------------------------------------------------


def test_mount_split_detector_reports_decoy_splits() -> None:
    """The split detector flags every violation shape it must catch.

    Reach side of the non-vacuity proof: one in-memory decoy per
    mount-split shape — a split, a partition, and a regex drift —
    must each be reported.  The decoys are string constants parsed
    with ast.parse; nothing is written to disk, so the test cannot
    leave artefacts under src/.
    """
    decoys = {
        "entry.split(':')": """\
def second(entry: str) -> tuple[str, str]:
    parts = entry.split(":")
    return parts[0], parts[1]
""",
        "entry.partition(':')": _DECOY_SPLIT_FIELDS,
        "re.split(':', entry)": _DECOY_RE_SPLIT,
    }
    messages = _detector("mount_split_messages")
    for label, source in decoys.items():
        found = messages(ast.parse(source))
        assert found, (
            "Guard is blind to a decoy mount split: "
            f"{label!r} was parsed but no violation was reported."
        )


def test_parse_mount_name_detector_reports_decoy_definition() -> None:
    """The name detector finds a decoy parse_mount definition.

    Non-vacuity of the name check: the very callable the one-parser
    boundary forbids under lifecycle/, defined in an in-memory decoy,
    must be found by the same walk the real-package check performs.
    """
    tree = ast.parse(_DECOY_SECOND_PARSE_MOUNT)
    offenders = _detector("parse_mount_name_offenders")(tree)
    assert offenders, (
        "Guard is blind: the decoy module defines parse_mount but the "
        "name detector found nothing."
    )


def test_mount_split_detector_ignores_non_mount_colon_usage() -> None:
    """The split detector does not flag bare colons or other separators.

    Precision side of the non-vacuity proof: a module whose colons are
    docstring content or dict keys, which splits on another separator,
    and which carries ":" only in a non-first argument, is not mount
    parsing and must produce no violation.  Without this, the reach
    test could be satisfied by a detector that flags everything.
    """
    tree = ast.parse(_BENIGN_MODULE)
    messages = _detector("mount_split_messages")(tree)
    assert not messages, f"False positive on benign module: {messages}"


def test_mount_split_detector_ignores_the_builder_itself() -> None:
    """The split detector is silent on the shipped spec_builder.py.

    The builder calls parse_mount rather than splitting a string; a
    guard that flags correct code gets disabled, which is worse than
    no guard.  The decoy tests prove the detector sees the idiom;
    this one proves it does not see the legitimate module.
    """
    source = _detector("spec_builder_source")()
    messages = _detector("mount_split_messages")(ast.parse(source))
    assert not messages, (
        f"spec_builder.py flagged as mount-string splitting: "
        f"{messages} — the builder calls parse_mount, it does not split."
    )


# ---------------------------------------------------------------------------
# Guard 2 — .values reads — detector non-vacuity, in-memory decoys
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(BACKEND_KEYS))
def test_values_read_detector_reports_decoy_backend_key_reads(key: str) -> None:
    """The values-read detector flags each backend-named .values read.

    Reach side of the non-vacuity proof, one decoy per key: a read of
    any of the four keys — which are present in ResolvedTool.values
    but always the built-in value (m2b §6.3) — must be reported with
    the file and line, whatever variable name the builder binds the
    resolved tool to.
    """
    source = (
        "def build(resolved, cfg, image):\n"
        f"    value = resolved.values[{key!r}]\n"
        "    return value\n"
    )
    violations = _detector("scan_values_reads")([("decoy.py", source)])
    assert violations.get("decoy.py"), (
        "Guard is blind: the decoy reads values["
        f"{key!r}] but no violation was reported."
    )


def test_values_read_detector_flags_attribute_form_only() -> None:
    """The detector flags x.values[key] but not a bare local values.

    Precision side of the non-vacuity proof: a bare local called
    values is not a ResolvedTool read and must not be flagged, while
    the attribute form must be — the two forms differ in exactly one
    AST shape, and confusing them is how a guard flags the wrong code.
    """
    flagged = _detector("scan_values_reads")([("decoy.py", _DECOY_VALUES_READ)])
    assert flagged.get("decoy.py"), (
        "Guard is blind: the decoy reads resolved.values['label_namespace'] "
        "but no violation was reported."
    )
    ignored = _detector("scan_values_reads")([("benign.py", _BENIGN_VALUES_MODULE)])
    assert not ignored.get("benign.py"), (
        "False positive: the benign module was flagged for reading "
        f"a backend-named key out of values: {ignored}"
    )


def test_values_read_detector_ignores_non_backend_keys() -> None:
    """The detector ignores legitimate tool-level .values reads.

    Precision side of the non-vacuity proof: container_port and
    mounts are tool-level keys the builder legitimately reads out of
    ResolvedTool.values; flagging them would disable the guard, which
    is worse than no guard.
    """
    violations = _detector("scan_values_reads")([("benign.py", _BENIGN_VALUES_MODULE)])
    assert not violations, (
        f"False positive on legitimate values reads: {violations} — "
        "only the four backend-named keys are present-but-wrong in "
        "ResolvedTool.values."
    )


# ---------------------------------------------------------------------------
# The walks over the real package — strictly read-only
# ---------------------------------------------------------------------------


def test_no_lifecycle_module_splits_a_mount_string_or_renames_parse_mount() -> None:
    """No lifecycle module splits a mount string or defines parse_mount.

    tool_swap.config.validate.parse_mount is the repository's only
    mount-string parser (m2a §4.2); the ParsedMount -> MountSpec
    conversion moved into lifecycle/, and this walk is what keeps it
    there as a call rather than a copy.  The walk is read-only; the
    detector's reach and precision are proven on in-memory decoys.
    """
    violations = _detector("scan_mount_violations")(_lifecycle_sources())
    assert not violations, (
        f"Mount parsing found under src/tool_swap/lifecycle/: "
        f"{violations}\n"
        "Parsing mount strings belongs to tool_swap.config.validate."
        "parse_mount (m2a plan §4.2)."
    )


def test_builder_reads_no_backend_key_from_values() -> None:
    """No lifecycle module reads a backend-named key out of .values.

    Those four keys are present in ResolvedTool.values but always
    carry the built-in value — the backend: block is not a resolver
    layer (m2b plan §6.3) — so a read here silently ignores the
    authored backend block and stamps the wrong namespace on every
    container.  The walk is read-only; the detector's reach and
    precision are proven on in-memory decoys.
    """
    violations = _detector("scan_values_reads")(_lifecycle_sources())
    assert not violations, (
        f"Backend-named keys read out of ResolvedTool.values under "
        f"src/tool_swap/lifecycle/: {violations}\n"
        "The backend-named values come from BackendConfig, never from "
        "resolved.values (m2b plan §6.3)."
    )

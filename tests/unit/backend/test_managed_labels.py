"""RED step for M2a behaviour 6 — the ``managed_labels`` label set.

See ``plans/m2a-container-backend-seam.md`` behaviour 6 (§5, **amended on
two points**): ``managed_labels`` is the pure function producing the
exact label set every managed container carries.  Labels are
load-bearing (``plan/08_REPO_LAYOUT.md`` §2: reconciliation, ``tswap
ps``, ``prune`` and staleness detection all depend on them), so they are
defined once, in one module — ``src/tool_swap/backend/labels.py`` —
which behaviour 6 creates.

**Amendment 1 — the namespace is required, with no default.**  The
built-in label namespace already lives in
``BUILT_IN_DEFAULTS["label_namespace"]`` and
``BackendConfig.label_namespace``; a third copy in ``labels.py`` could
drift from both while every copy stayed self-consistent.  The caller
passes the resolved namespace, so this file **never restates the
configured value anywhere**: the snapshot tests use an arbitrary
namespace of their own choosing, the configured-namespace test reads
``BUILT_IN_DEFAULTS`` at call time, and the no-literal guard below
formats its in-memory decoys from the same constant.  The forbidden
value is read, never written, in this file.

**Amendment 2 — all five keys are in scope:** ``{ns}.model``,
``{ns}.managed-by``, ``{ns}.group``, ``{ns}.config-hash`` and
``{ns}.runtime-version``, per the naming table of
``plan/08_REPO_LAYOUT.md`` §2.  An omitted group / config hash /
runtime version **omits its key** rather than emitting an empty value
(an empty label value is a silent reconciliation mismatch).  **No
``config-hash`` value is computed here** — the function stamps the hash
it is given; the hash function is a later milestone's.

**The ``managed-by`` value — pinned here, flagged in the RED report.**
The plan names the key but not its value, and behaviour 7 requires the
selector to match it without any extra input, so the value must be a
constant, independent of the namespace (the key already carries the
namespace).  This step pins ``"tool-swap"``: the stable product
identifier (repository, distribution and registry prefix), distinct
from the namespace so the two can never be confused, and stable across
namespace changes so containers labelled under an old namespace keep
reconciling.  The plan underspecifies this value; the choice is
deliberate, not a default re-statement.

Pinned public API — the GREEN step implements precisely this:

    def managed_labels(
        namespace: str,
        tool: str,
        *,
        group: str | None = None,
        config_hash: str | None = None,
        runtime_version: str | None = None,
    ) -> dict[str, str]: ...

- ``namespace`` and ``tool`` are required (positional or keyword);
  omitting ``namespace`` is a plain Python ``TypeError`` — there is no
  default namespace to fall back on.
- ``group`` / ``config_hash`` / ``runtime_version`` are **keyword-only**
  and default to ``None``: the three are interchangeable positional
  strings (swapping a group for a hash is a silent mislabel), so
  keyword-only makes each call self-documenting, matching the
  keyword-only style of the rest of the seam (behaviour 4's resolved
  fields, the protocol's ``stop`` / ``logs`` arguments).
- An empty ``namespace`` or empty ``tool`` raises ``ValueError``.

This file is the RED step: ``src/tool_swap/backend/labels.py`` does not
exist yet.  Every access to ``tool_swap`` is therefore deferred out of
module scope into call-time helpers, following ``test_mount_spec.py``
exactly: a module-level import would raise ``ModuleNotFoundError`` at
*collection* time and abort the whole suite — the same trap behaviour
3's first red attempt hit.  Each gate instead raises ``AssertionError``
naming the missing module, so every test fails individually; the
moment the GREEN step creates ``labels.py`` the call resolves and each
test proceeds to its own assertions.

The no-literal guard is an AST-level check (precedent:
``test_backend_mount_parsing_guard.py``): it flags any **string
constant** in ``labels.py`` equal to the configured namespace — the
exact shape of the third copy amendment 1 forbids — and nothing wider
(comments are not literals and cannot drift; near-miss strings are not
the forbidden value).  Its detector is proven non-vacuous on in-memory
decoys formatted from ``BUILT_IN_DEFAULTS`` at call time, so nothing is
written to disk and this file never carries the literal.  In the RED
state the file-level guard fails on a clear assertion naming the
missing module rather than an incidental exception; once the file
exists it cannot pass vacuously, because the detector's reach is proven
on a decoy carrying the live forbidden value.

No ``importorskip`` and no skip of any kind is used — a skipped test is
not a red step, it is a test that silently does not run.

Conventions: pytest, AAA pattern, Google-style docstrings, no
``warnings.warn`` (pyproject sets ``filterwarnings = "error"``).
"""

from __future__ import annotations

import ast
import importlib
import inspect
import typing
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[3]  # repository root
LABELS_FILE = ROOT / "src" / "tool_swap" / "backend" / "labels.py"

#: An arbitrary namespace for the snapshot tests — deliberately NOT the
#: configured default, so this file never restates a configured value.
_ARBITRARY_NS = "io.example.acme"
#: A second arbitrary namespace, proving the keys follow the argument.
_ARBITRARY_NS_2 = "org.other.project"

#: The value pinned for the ``{ns}.managed-by`` label (see the module
#: docstring for the choice and the flag).
PINNED_MANAGED_BY = "tool-swap"

#: In-memory decoy the literal detector must flag: a module that
#: hardcodes the configured namespace as a default.  The forbidden
#: value is formatted in at call time — this file never carries it.
_DECOY_WITH_LITERAL_TEMPLATE = (
    '"""A decoy module that hardcodes the namespace."""\n\nDEFAULT_NAMESPACE = "{ns}"\n'
)

#: In-memory decoy the literal detector must NOT flag: the forbidden
#: value only as a substring of a different string.
_DECOY_NEAR_MISS_TEMPLATE = 'TAG = "{ns}-x"\n'

#: In-memory decoy the literal detector must NOT flag: the namespace
#: arrives as a parameter — exactly the pattern amendment 1 wants.
_DECOY_BENIGN = '''\
def managed_labels(namespace: str, tool: str) -> dict[str, str]:
    """The caller passes the resolved namespace; no literal here."""
    return {f"{namespace}.model": tool}
'''


def _get_labels_module() -> ModuleType:
    """Import ``tool_swap.backend.labels`` at call time, RED-safely.

    Deferred out of module scope via ``importlib.import_module`` so
    that the not-yet-existing module cannot abort pytest *collection*
    of this file (and thereby of the whole suite), and so that
    ``mypy --strict`` stays clean while no ``tool_swap`` name is
    imported at module scope (the editable install carries no
    ``py.typed`` marker).

    Raises:
        AssertionError: ``tool_swap.backend.labels`` does not exist yet —
            the GREEN step must create it with ``managed_labels``.
    """
    try:
        return importlib.import_module("tool_swap.backend.labels")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.backend.labels is missing — the GREEN step must "
            "create src/tool_swap/backend/labels.py with managed_labels"
        ) from exc


def _get_managed_labels() -> Callable[..., dict[str, str]]:
    """Import and return ``managed_labels``, RED-safely.

    ``AttributeError`` is caught separately from the module-level
    failure handled by :func:`_get_labels_module`, mirroring
    ``test_container_spec.py``: a module that exists but lacks the name
    is a different RED failure mode and deserves its own message.

    Raises:
        AssertionError: ``managed_labels`` is not defined in
            ``tool_swap.backend.labels`` yet — the GREEN step must add it.
    """
    module = _get_labels_module()
    try:
        fn = module.managed_labels
    except AttributeError as exc:
        raise AssertionError(
            "tool_swap.backend.labels.managed_labels is missing — the "
            "GREEN step must add managed_labels to "
            "src/tool_swap/backend/labels.py"
        ) from exc
    return cast("Callable[..., dict[str, str]]", fn)


def _configured_label_namespace() -> str:
    """Return the configured label namespace, read from its single owner.

    ``BUILT_IN_DEFAULTS["label_namespace"]`` is the single named source
    of truth; this file reads it at call time rather than restating the
    value (amendment 1).  The import is deferred for the same mypy
    reason as the other gates; nothing about *what is read* changes.

    Raises:
        AssertionError: the constant or its ``label_namespace`` key is
            missing — the guard has no forbidden value to check for.
    """
    try:
        module = importlib.import_module("tool_swap.config.defaults")
        value = module.BUILT_IN_DEFAULTS["label_namespace"]
    except (ModuleNotFoundError, AttributeError, KeyError, TypeError) as exc:
        raise AssertionError(
            "BUILT_IN_DEFAULTS['label_namespace'] is missing — the "
            "no-literal guard reads the forbidden value from the "
            "single source of truth"
        ) from exc
    return cast("str", value)


def _string_constant_lines(tree: ast.AST, forbidden: str) -> list[int]:
    """Line numbers of string constants in *tree* equal to *forbidden*.

    Exact-value equality over string constants (including docstrings —
    any occurrence is a copy that could drift), and nothing wider: no
    substring matching, no comments, no other values.
    """
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value == forbidden
    ]


def _full_labels(ns: str) -> dict[str, str]:
    """The complete five-key label set, for snapshot comparison."""
    return {
        f"{ns}.model": "llama",
        f"{ns}.managed-by": PINNED_MANAGED_BY,
        f"{ns}.group": "vision",
        f"{ns}.config-hash": "abc123",
        f"{ns}.runtime-version": "2.1.0",
    }


# ---------------------------------------------------------------------------
# The pinned public API
# ---------------------------------------------------------------------------


def test_managed_labels_signature_is_pinned() -> None:
    """The public API is exactly the signature pinned in the docstring."""
    # Arrange
    fn = _get_managed_labels()
    # Act
    signature = inspect.signature(fn)
    hints = typing.get_type_hints(fn)
    # Assert — names and order
    assert list(signature.parameters) == [
        "namespace",
        "tool",
        "group",
        "config_hash",
        "runtime_version",
    ]
    # Assert — kinds: required pair positional-or-keyword, optionals keyword-only
    parameters = signature.parameters
    assert parameters["namespace"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["tool"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameters["group"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["config_hash"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["runtime_version"].kind is inspect.Parameter.KEYWORD_ONLY
    # Assert — defaults: none for the required pair, None for the optionals
    assert parameters["namespace"].default is inspect.Parameter.empty
    assert parameters["tool"].default is inspect.Parameter.empty
    assert parameters["group"].default is None
    assert parameters["config_hash"].default is None
    assert parameters["runtime_version"].default is None
    # Assert — annotations
    assert hints["namespace"] is str
    assert hints["tool"] is str
    assert hints["group"] == (str | None)
    assert hints["config_hash"] == (str | None)
    assert hints["runtime_version"] == (str | None)
    assert hints["return"] == dict[str, str]


# ---------------------------------------------------------------------------
# Outputs — the exact label set
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ns", [_ARBITRARY_NS, _ARBITRARY_NS_2])
def test_managed_labels_full_snapshot_with_all_optionals(ns: str) -> None:
    """All five keys with exact values, built from the passed namespace."""
    # Arrange
    fn = _get_managed_labels()
    # Act
    labels = fn(
        ns,
        "llama",
        group="vision",
        config_hash="abc123",
        runtime_version="2.1.0",
    )
    # Assert — exact dict: no more, no less, keys follow the argument
    assert isinstance(labels, dict)
    assert labels == _full_labels(ns)


@pytest.mark.parametrize("omitted", ["group", "config_hash", "runtime_version"])
def test_managed_labels_omitted_optional_omits_its_key(omitted: str) -> None:
    """An omitted optional drops its key; no empty value is emitted."""
    # Arrange
    fn = _get_managed_labels()
    kwargs: dict[str, str] = {
        "group": "vision",
        "config_hash": "abc123",
        "runtime_version": "2.1.0",
    }
    del kwargs[omitted]
    expected = _full_labels(_ARBITRARY_NS)
    key_suffix = {
        "group": "group",
        "config_hash": "config-hash",
        "runtime_version": "runtime-version",
    }[omitted]
    del expected[f"{_ARBITRARY_NS}.{key_suffix}"]
    # Act
    labels = fn(_ARBITRARY_NS, "llama", **kwargs)
    # Assert — the full set minus the omitted key, and nothing else
    assert labels == expected
    assert f"{_ARBITRARY_NS}.{key_suffix}" not in labels


def test_managed_labels_minimal_call_emits_exactly_model_and_managed_by() -> None:
    """With no optionals, the label set is exactly the two identifying keys."""
    # Arrange
    fn = _get_managed_labels()
    # Act
    labels = fn(_ARBITRARY_NS, "llama")
    # Assert
    assert labels == {
        f"{_ARBITRARY_NS}.model": "llama",
        f"{_ARBITRARY_NS}.managed-by": PINNED_MANAGED_BY,
    }


def test_managed_labels_works_with_the_configured_namespace() -> None:
    """The function works with the real configured namespace, read not restated.

    The namespace comes from ``BUILT_IN_DEFAULTS["label_namespace"]``
    at call time (importing ``tool_swap.config`` from a test is fine —
    no import-linter contract governs test imports), so this file
    carries the value no more than the config module does.
    """
    # Arrange
    fn = _get_managed_labels()
    ns = _configured_label_namespace()
    # Act
    labels = fn(ns, "llama")
    # Assert
    assert labels == {
        f"{ns}.model": "llama",
        f"{ns}.managed-by": PINNED_MANAGED_BY,
    }


def test_managed_labels_stamps_config_hash_verbatim() -> None:
    """The config hash is stamped, not computed: anything passed comes back.

    Behaviour 6 computes nothing — no hash function exists in the
    repository yet — so a non-hash value must round-trip unchanged.
    """
    # Arrange
    fn = _get_managed_labels()
    # Act
    labels = fn(_ARBITRARY_NS, "llama", config_hash="not-a-real-hash")
    # Assert
    assert labels[f"{_ARBITRARY_NS}.config-hash"] == "not-a-real-hash"


# ---------------------------------------------------------------------------
# Error behaviour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("namespace", "tool"),
    [("", "llama"), (_ARBITRARY_NS, "")],
)
def test_managed_labels_empty_namespace_or_tool_raises_value_error(
    namespace: str,
    tool: str,
) -> None:
    """An empty namespace or an empty tool name raises ValueError."""
    # Arrange
    fn = _get_managed_labels()
    # Act / Assert
    with pytest.raises(ValueError):
        fn(namespace, tool)


def test_managed_labels_omitted_namespace_raises_type_error() -> None:
    """Omitting namespace is Python's own TypeError: there is no default.

    Amendment 1 removed the fallback: ``BUILT_IN_DEFAULTS`` and
    ``BackendConfig`` own the default, so the function simply requires
    the argument.
    """
    # Arrange
    fn = _get_managed_labels()
    # Act / Assert
    with pytest.raises(TypeError):
        fn()


# ---------------------------------------------------------------------------
# The no-literal guard — detector non-vacuity (in-memory decoys)
# ---------------------------------------------------------------------------


def test_namespace_literal_detector_reports_decoy_module() -> None:
    """The detector flags a decoy that hardcodes the configured namespace.

    Reach side of the non-vacuity proof: the decoy is formatted from
    ``BUILT_IN_DEFAULTS`` at call time — the exact third copy amendment
    1 forbids — so the detector is proven against the live forbidden
    value, not a stale restatement of it.
    """
    # Arrange
    forbidden = _configured_label_namespace()
    tree = ast.parse(_DECOY_WITH_LITERAL_TEMPLATE.format(ns=forbidden))
    # Act
    lines = _string_constant_lines(tree, forbidden)
    # Assert
    assert lines, (
        "Guard is blind: a decoy module hardcoding the configured "
        "namespace produced no violation."
    )


def test_namespace_literal_detector_ignores_benign_and_near_miss() -> None:
    """The detector flags the forbidden value only, exactly.

    Precision side of the non-vacuity proof: a module where the
    namespace arrives as a parameter (the pattern amendment 1 wants)
    and a module carrying the value only as a substring of a different
    string must both produce no violation — the check is exact-value
    equality over string constants, not a substring tripwire.
    """
    # Arrange
    forbidden = _configured_label_namespace()
    benign = ast.parse(_DECOY_BENIGN)
    near_miss = ast.parse(_DECOY_NEAR_MISS_TEMPLATE.format(ns=forbidden))
    # Act
    benign_lines = _string_constant_lines(benign, forbidden)
    near_miss_lines = _string_constant_lines(near_miss, forbidden)
    # Assert
    assert not benign_lines, f"False positive on benign module: {benign_lines}"
    assert not near_miss_lines, (
        f"False positive on near-miss string: {near_miss_lines} — the "
        "guard must match the forbidden value exactly, not substrings."
    )


# ---------------------------------------------------------------------------
# The walk over labels.py — strictly read-only
# ---------------------------------------------------------------------------


def test_labels_module_contains_no_configured_namespace_literal() -> None:
    """labels.py carries no literal copy of the configured namespace.

    Amendment 1: the namespace has exactly two owners —
    ``BUILT_IN_DEFAULTS["label_namespace"]`` and
    ``BackendConfig.label_namespace`` — and a third copy in
    ``labels.py`` could drift from both while every copy stayed
    self-consistent.  The check is AST-level over string constants
    (comments are not literals and cannot drift), scoped to
    ``labels.py`` itself, so it keeps working as behaviour 7 adds
    functions to the same module.

    RED state: ``labels.py`` does not exist yet, and the failure is a
    clear assertion naming the missing module — not an incidental
    ``FileNotFoundError``.  Once the GREEN step creates the file the
    walk runs, and it cannot pass vacuously: the detector's reach is
    proven on a decoy carrying the live forbidden value, and the
    forbidden value itself is read live, so the guard tracks any
    future change to the configured namespace.
    """
    # Arrange — the guard's subject must exist
    assert LABELS_FILE.is_file(), (
        "src/tool_swap/backend/labels.py is missing — the GREEN step "
        "must create it; the no-literal guard has nothing to walk."
    )
    forbidden = _configured_label_namespace()
    tree = ast.parse(LABELS_FILE.read_text(encoding="utf-8"))
    # Act
    offending = _string_constant_lines(tree, forbidden)
    # Assert
    assert not offending, (
        f"labels.py contains a literal copy of the configured label "
        f"namespace on line(s) {offending} — the namespace is owned by "
        "BUILT_IN_DEFAULTS and BackendConfig; the caller passes the "
        "resolved value (plan behaviour 6, amendment 1)."
    )

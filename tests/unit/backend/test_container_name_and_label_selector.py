"""RED step for M2a behaviour 7 — ``container_name`` and ``label_selector``.

See ``plans/m2a-container-backend-seam.md`` behaviour 7 (§5, **amended on
two points**): two more pure functions in ``src/tool_swap/backend/
labels.py`` — the container *name* builder and the *selector* that finds
our containers.

**Amendment 1 — ``container_prefix`` is required, with no default**, for
the same reason as behaviour 6's namespace:
``BUILT_IN_DEFAULTS["container_prefix"]`` and
``BackendConfig.container_prefix`` are the two owners of the configured
prefix, and a third copy in ``labels.py`` could drift from both while
every copy stayed self-consistent.  The configured-prefix test below
therefore reads ``BUILT_IN_DEFAULTS`` at call time, and the no-literal
guard reads the forbidden value from the same constant — this file
never restates it.

**Amendment 2 — the hazard is the prefix, not the tool name.**  Tool
names are pinned by ``TSWAP-C210`` to ``^[a-z0-9][a-z0-9_-]*$``
(``src/tool_swap/config/validate.py``), and ``TSWAP-C211`` rejects
duplicates — so an illegal tool name is effectively unreachable
through validated config.  ``container_prefix`` is checked by no
config rule (plan §7, open assumption 10), so it is the only input
that can make the concatenation illegal: an authored prefix with a
character the TSWAP-C210 pattern forbids reaches
``container_name`` unjudged.  Its ``ValueError`` therefore names the
**prefix** (and the tool) — a diagnostic that blamed the tool name
would send a user to fix the wrong line of their config.  A tool name
that breaks ``TSWAP-C210`` is still rejected *defensively* (the
function must not assume its caller ran validation), but that is
``TSWAP-C210``'s primary responsibility, not a second gate — the tests
say so.

**Amendment 3 (2026-09-15 RED rework) — the name rule is
``TSWAP-C210``, applied to the whole concatenated name.**  The first
RED attempt judged the prefix by Docker's container-name charset —
recalled from memory, verified nowhere in
``plan/third-party-docs/`` — which made a leading underscore a
contradiction (the test rejected ``"_x"`` while Docker permits it)
and pinned a length limit as a probe ladder asserting only that
*some* limit exists below 4096, so any invented number satisfied it.
The rework replaces that with the rule this repository can verify:
the TSWAP-C210 tool-name pattern
(``[a-z0-9][a-z0-9_-]*``, ``src/tool_swap/config/validate.py`` line
310, read at call time from its owner) is enforced over the
**entire** concatenation.  It is a strict subset of Docker's legal
name charset, so being stricter than Docker is safe whatever
Docker's exact rule turns out to be — every name this rule accepts
is one Docker accepts — and the rule is verifiable from our own
source rather than from anyone's memory.  Judging the prefix by the
same rule as the tool name is coherent: the concatenation is what
becomes the container name.  A prefix ending in ``-`` (like the
configured one) is legal because ``-`` is allowed after the first
character.  **No length assertion exists**: the length ladder was
deleted outright; if a length limit later proves to matter it
arrives with saved documentation as its own behaviour.

**Return shape of ``label_selector`` — chosen here, flagged in the RED
report.**  The plan does not pin it, and the docker filter form is not
verified in this repository yet (behaviours 14–26 pin it against saved
documentation), so this step deliberately does **not** invent a
docker-specific structure.  The selector is a ``dict[str, str]`` — the
label map that selects our containers, exactly one entry — which any
backend can translate into its own filter form (behaviour 14's job).
What is pinned is the *key agreement*: the single key is exactly the
managed-by key that ``managed_labels`` emits, **derived from a
``managed_labels`` call** rather than restated, and the value is the
module's ``MANAGED_BY_VALUE`` constant read at call time — so
``list_managed`` and ``managed_labels`` cannot drift apart.

Pinned public API — the GREEN step implements precisely this:

    def container_name(container_prefix: str, tool: str) -> str: ...
    def label_selector(namespace: str) -> dict[str, str]: ...

- both arguments of both functions are required, positional-or-keyword,
  with **no defaults** — omitting one is a plain ``TypeError``;
- ``container_name`` returns ``prefix + tool`` for every legal input;
  an empty prefix is **legal** and yields the bare tool name;
  the name is judged by the TSWAP-C210 pattern over the whole
  concatenation (amendment 3), so uppercase — and a leading
  underscore or hyphen — is **illegal**;
- an unusable name raises ``ValueError``: for a bad prefix the message
  contains the prefix value, the tool value and the word ``prefix``;
  for a bad tool name (defensive ``TSWAP-C210`` gate) it contains the
  tool value and the word ``tool``;
- ``label_selector`` returns exactly one ``{key: value}`` pair, where
  the key is the managed-by key ``managed_labels`` emits for the same
  namespace and the value is ``MANAGED_BY_VALUE``.

This file is the RED step: ``labels.py`` exists (behaviour 6) but
defines neither function yet.  A module-level
``from tool_swap.backend.labels import container_name`` would raise
``ImportError`` on the missing *name* and abort pytest *collection* of
the whole suite (the trap behaviour 3's first red attempt hit), so
every access is deferred into call-time gates that raise
``AssertionError`` naming the missing name instead; the moment GREEN
adds the two functions each test proceeds to its own assertions.  No
``importorskip`` and no skip of any kind is used — a skipped test is
not a red step, it is a test that silently does not run.

The no-configured-prefix guard carries forward behaviour 6's guard
with one precision difference that a short value forces: the
configured prefix is a short string that is a **substring** of many
benign constants, so a substring check would false-positive where
behaviour 6's namespace check could not.  The guard is therefore,
exactly as behaviour 6's, **AST-level exact-value equality over
string constants** — nothing wider (comments and other values are not
the forbidden value) — and its detector is proven non-vacuous on
in-memory decoys: a hardcoded prefix is flagged, the prefix as a
substring of a longer constant is not, and a parameter is not.  The
forbidden value is read from ``BUILT_IN_DEFAULTS["container_prefix"]``
at call time, so nothing in this file carries it.

Conventions: pytest, AAA pattern, Google-style docstrings, no
``warnings.warn`` (pyproject sets ``filterwarnings = "error"``).
"""

from __future__ import annotations

import ast
import importlib
import inspect
import re
import typing
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Final, cast

import pytest

ROOT = Path(__file__).resolve().parents[3]  # repository root
LABELS_FILE = ROOT / "src" / "tool_swap" / "backend" / "labels.py"

#: Arbitrary namespaces for the selector tests — deliberately NOT the
#: configured default, so this file never restates a configured value.
_ARBITRARY_NS = "io.example.acme"
_ARBITRARY_NS_2 = "org.other.project"

#: A legal tool name used wherever one is needed.
_TOOL = "llama"

#: Legal (container_prefix, tool, expected) rows for the name table.
#: A deliberate mirror of TSWAP-C210 — the rule ``validate.py`` owns
#: (line 310) and the consistency guard below re-checks live: if the
#: pattern changes, the guard fails until these rows follow it.
#: The configured prefix is tested separately, read live from
#: ``BUILT_IN_DEFAULTS``; these rows use arbitrary prefixes.
_LEGAL_NAME_ROWS: Final[tuple[tuple[str, str, str], ...]] = (
    ("acme-", "cxr_to_embedding", "acme-cxr_to_embedding"),
    ("pre", "llama", "prellama"),
    ("v2_", "model_a", "v2_model_a"),
    # A prefix ending in "-" is legal: "-" is allowed after the
    # first character of the TSWAP-C210 pattern.
    ("pre-", "llama", "pre-llama"),
    # A digit tool name is legal (TSWAP-C210 allows a digit first).
    ("a-", "42", "a-42"),
    # The empty prefix is legal and yields the bare tool name.
    ("", "cxr_to_embedding", "cxr_to_embedding"),
)

#: Prefixes whose concatenation with the legal tool name fails
#: TSWAP-C210 — the unjudged-input side of the rule.
_REJECTED_PREFIXES: Final[tuple[str, ...]] = (
    # None of these concatenates with the legal tool name to
    # something matching TSWAP-C210; all fail on the prefix.
    "My Prefix",  # a space is outside the pattern's charset
    "My-",  # uppercase outside the pattern's charset (amendment 3
    # moved this from the legal table: the prefix is now judged by
    # the same rule as the tool name)
    "_x",  # a leading underscore fails the first-character rule
    "-x",  # a leading hyphen fails the first-character rule
    ".x",  # a dot is outside the pattern's charset
)

#: In-memory decoy the literal detector must flag: a module that
#: hardcodes the configured prefix as a default.  The forbidden value
#: is formatted in at call time — this file never carries it.
_DECOY_PREFIX_LITERAL_TEMPLATE = 'DEFAULT_PREFIX = "{prefix}"\n'

#: In-memory decoy the literal detector must NOT flag: the forbidden
#: value only as a substring of a different string.
_DECOY_PREFIX_NEAR_MISS_TEMPLATE = 'TAG = "{prefix}x"\n'

#: In-memory decoy the literal detector must NOT flag: the prefix
#: arrives as a parameter — exactly the pattern amendment 1 wants.
_DECOY_PREFIX_BENIGN = '''\
def container_name(container_prefix: str, tool: str) -> str:
    """The caller passes the resolved prefix; no literal here."""
    return container_prefix + tool
'''


def _get_labels_module() -> ModuleType:
    """Import ``tool_swap.backend.labels`` at call time, RED-safely.

    Deferred out of module scope via ``importlib.import_module`` so
    that a missing module cannot abort pytest *collection* of this
    file (and thereby of the whole suite), and so that
    ``mypy --strict`` stays clean while no ``tool_swap`` name is
    imported at module scope (the editable install carries no
    ``py.typed`` marker).

    Raises:
        AssertionError: ``tool_swap.backend.labels`` does not exist —
            it exists on this branch (behaviour 6); this guards
            against it ever being removed.
    """
    try:
        return importlib.import_module("tool_swap.backend.labels")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.backend.labels is missing — it must exist in "
            "src/tool_swap/backend/labels.py"
        ) from exc


def _get_container_name() -> Callable[..., str]:
    """Import and return ``container_name``, RED-safely.

    ``AttributeError`` is caught separately from the module-level
    failure handled by :func:`_get_labels_module`, mirroring
    ``test_container_spec.py``: a module that exists but lacks the
    name is a different RED failure mode and deserves its own message.

    Raises:
        AssertionError: ``container_name`` is not defined in
            ``tool_swap.backend.labels`` yet — the GREEN step must add
            it.
    """
    module = _get_labels_module()
    try:
        fn = module.container_name
    except AttributeError as exc:
        raise AssertionError(
            "tool_swap.backend.labels.container_name is missing — the "
            "GREEN step must add container_name to "
            "src/tool_swap/backend/labels.py"
        ) from exc
    return cast("Callable[..., str]", fn)


def _get_label_selector() -> Callable[..., dict[str, str]]:
    """Import and return ``label_selector``, RED-safely.

    Raises:
        AssertionError: ``label_selector`` is not defined in
            ``tool_swap.backend.labels`` yet — the GREEN step must add
            it.
    """
    module = _get_labels_module()
    try:
        fn = module.label_selector
    except AttributeError as exc:
        raise AssertionError(
            "tool_swap.backend.labels.label_selector is missing — the "
            "GREEN step must add label_selector to "
            "src/tool_swap/backend/labels.py"
        ) from exc
    return cast("Callable[..., dict[str, str]]", fn)


def _get_managed_labels() -> Callable[..., dict[str, str]]:
    """Return the committed behaviour-6 ``managed_labels`` function.

    Fetched at call time for the mypy reason given in
    :func:`_get_labels_module`; it exists on this branch and is the
    anti-drift key source for the selector tests.
    """
    module = _get_labels_module()
    try:
        fn = module.managed_labels
    except AttributeError as exc:
        raise AssertionError(
            "tool_swap.backend.labels.managed_labels is missing — "
            "behaviour 6 committed it; the anti-drift tests have no "
            "key source"
        ) from exc
    return cast("Callable[..., dict[str, str]]", fn)


def _get_managed_by_value() -> str:
    """Return the committed ``MANAGED_BY_VALUE`` constant, at call time.

    The selector's value is pinned against the constant rather than
    restating it: if behaviour 6's value ever changes, the selector
    tests track it instead of drifting.

    Raises:
        AssertionError: the constant is missing — behaviour 6
            committed it.
    """
    module = _get_labels_module()
    try:
        value = module.MANAGED_BY_VALUE
    except AttributeError as exc:
        raise AssertionError(
            "tool_swap.backend.labels.MANAGED_BY_VALUE is missing — "
            "behaviour 6's constant is the selector's value source"
        ) from exc
    return cast("str", value)


def _configured_container_prefix() -> str:
    """Return the configured prefix, read from its single owner.

    ``BUILT_IN_DEFAULTS["container_prefix"]`` is the single named
    source of truth; this file reads it at call time rather than
    restating the value (amendment 1).  The import is deferred for the
    same mypy reason as the other gates; nothing about *what is read*
    changes.

    Raises:
        AssertionError: the constant or its ``container_prefix`` key
            is missing — the guard has no forbidden value to check.
    """
    try:
        module = importlib.import_module("tool_swap.config.defaults")
        value = module.BUILT_IN_DEFAULTS["container_prefix"]
    except (ModuleNotFoundError, AttributeError, KeyError, TypeError) as exc:
        raise AssertionError(
            "BUILT_IN_DEFAULTS['container_prefix'] is missing — the "
            "no-literal guard reads the forbidden value from the "
            "single source of truth"
        ) from exc
    return cast("str", value)


def _configured_label_namespace() -> str:
    """Return the configured label namespace, read from its owner.

    ``BUILT_IN_DEFAULTS["label_namespace"]`` is the single named
    source of truth; read at call time so this file carries no
    configured value.

    Raises:
        AssertionError: the constant or its ``label_namespace`` key
            is missing — the configured-namespace test has no value.
    """
    try:
        module = importlib.import_module("tool_swap.config.defaults")
        value = module.BUILT_IN_DEFAULTS["label_namespace"]
    except (ModuleNotFoundError, AttributeError, KeyError, TypeError) as exc:
        raise AssertionError(
            "BUILT_IN_DEFAULTS['label_namespace'] is missing — the "
            "configured-namespace test reads the value from the single "
            "source of truth"
        ) from exc
    return cast("str", value)


def _get_name_pattern() -> re.Pattern[str]:
    """Return the ``TSWAP-C210`` tool-name pattern, read at call time.

    The pattern is owned by ``tool_swap.config.validate`` (TSWAP-C210,
    ``src/tool_swap/config/validate.py`` line 310): a lowercase letter
    or digit first, then lowercase letters, digits, ``_`` and ``-``.
    ``container_name`` enforces it over the *entire* concatenation
    (module docstring, amendment 3) — the same discipline the
    configured-prefix guard applies to its forbidden value: the rule
    is read from its single owner at call time, never restated, so
    this file cannot drift from the config rule.

    Raises:
        AssertionError: the pattern is missing — TSWAP-C210 is
            committed (M1 behaviour 12); the name tests have no rule.
    """
    try:
        module = importlib.import_module("tool_swap.config.validate")
        pattern = module._NAME_PATTERN
    except (ModuleNotFoundError, AttributeError) as exc:
        raise AssertionError(
            "tool_swap.config.validate._NAME_PATTERN is missing — the "
            "TSWAP-C210 rule is the name tests' rule source"
        ) from exc
    return cast("re.Pattern[str]", pattern)


def _string_constant_lines(tree: ast.AST, forbidden: str) -> list[int]:
    """Line numbers of string constants in *tree* equal to *forbidden*.

    Exact-value equality over string constants (including docstrings —
    any occurrence is a copy that could drift), and nothing wider: no
    substring matching, no comments, no other values.  For a short
    forbidden value like the configured prefix this precision is what
    keeps the guard free of false positives.
    """
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value == forbidden
    ]


# ---------------------------------------------------------------------------
# container_name — the pinned public API
# ---------------------------------------------------------------------------


def test_container_name_signature_is_pinned() -> None:
    """The public API is exactly the signature pinned in the docstring."""
    # Arrange
    fn = _get_container_name()
    # Act
    signature = inspect.signature(fn)
    hints = typing.get_type_hints(fn)
    # Assert — names and order
    assert list(signature.parameters) == ["container_prefix", "tool"]
    parameters = signature.parameters
    # Assert — kinds: both required, positional-or-keyword, no defaults
    for name in ("container_prefix", "tool"):
        assert parameters[name].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
        assert parameters[name].default is inspect.Parameter.empty
    # Assert — annotations
    assert hints["container_prefix"] is str
    assert hints["tool"] is str
    assert hints["return"] is str


@pytest.mark.parametrize("call_args", [((),), (["acme-"],)])
def test_container_name_omitted_argument_raises_type_error(
    call_args: tuple[object, ...],
) -> None:
    """Omitting either argument is Python's own TypeError: no defaults.

    Amendment 1 removed any fallback: the configured prefix has
    exactly two owners (``BUILT_IN_DEFAULTS`` and
    ``BackendConfig``), so the function simply requires the argument.
    """
    # Arrange
    fn = _get_container_name()
    # Act / Assert
    with pytest.raises(TypeError):
        fn(*call_args)


# ---------------------------------------------------------------------------
# container_name — outputs (the plan's table test)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("container_prefix", "tool", "expected"), _LEGAL_NAME_ROWS)
def test_container_name_table(
    container_prefix: str,
    tool: str,
    expected: str,
) -> None:
    """The name is exactly prefix + tool for every legal input.

    "Legal" means the whole concatenation matches the TSWAP-C210
    pattern (amendment 3) — the same rule the config layer pins every
    tool name to, read at call time from ``validate.py``.
    """
    # Arrange
    fn = _get_container_name()
    # Act
    name = fn(container_prefix, tool)
    # Assert
    assert name == expected


def test_container_name_with_configured_prefix_matches_plan_example() -> None:
    """The plan's worked example, with the prefix read, not restated.

    Behaviour 7's example pairs the configured prefix with
    ``cxr_to_embedding``; the prefix comes from
    ``BUILT_IN_DEFAULTS["container_prefix"]`` at call time, so at run
    time this is exactly the plan's example without the test carrying
    the configured value.
    """
    # Arrange
    fn = _get_container_name()
    prefix = _configured_container_prefix()
    # Act
    name = fn(prefix, "cxr_to_embedding")
    # Assert
    assert name == prefix + "cxr_to_embedding"


# ---------------------------------------------------------------------------
# container_name — error behaviour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("container_prefix", _REJECTED_PREFIXES)
def test_container_name_illegal_prefix_raises_value_error_naming_prefix(
    container_prefix: str,
) -> None:
    """An unusable name blames the prefix — the unvalidated input.

    ``container_prefix`` is checked by no config rule (plan §7, open
    assumption 10), so it is the only way the concatenation can fail
    the TSWAP-C210 pattern; a diagnostic that pointed at the tool name
    would send a user to fix the wrong line of their config.  The
    message must therefore name the prefix: its value, plus the tool,
    plus the word itself.
    """
    # Arrange
    fn = _get_container_name()
    # Act / Assert
    with pytest.raises(ValueError) as excinfo:
        fn(container_prefix, _TOOL)
    message = str(excinfo.value)
    # Assert — the message points at the unvalidated input
    assert container_prefix in message, (
        f"ValueError must name the prefix value {container_prefix!r}: {message!r}"
    )
    assert _TOOL in message, f"ValueError must name the tool: {message!r}"
    assert "prefix" in message.lower(), (
        f"ValueError must point at the prefix, not the tool: {message!r}"
    )


@pytest.mark.parametrize("tool", ["LLAMA", "_bad"])
def test_container_name_illegal_tool_name_rejected_defensively(
    tool: str,
) -> None:
    """A TSWAP-C210-breaking tool name is rejected defensively.

    NOTE: this is ``TSWAP-C210``'s primary responsibility — the
    config layer pins every tool name to ``^[a-z0-9][a-z0-9_-]*$`` —
    not a second gate.  The function must merely not *assume* its
    caller ran validation.  ``LLAMA`` fails the pattern on the
    uppercase; it is rejected because it breaks the *tool-name* rule,
    which is why the message names the tool.
    """
    # Arrange
    fn = _get_container_name()
    # Act / Assert
    with pytest.raises(ValueError) as excinfo:
        fn("a-", tool)
    message = str(excinfo.value)
    # Assert — the message points at the tool
    assert tool in message, f"ValueError must name the tool: {message!r}"
    assert "tool" in message.lower(), f"ValueError must point at the tool: {message!r}"


def test_container_name_empty_tool_raises_value_error() -> None:
    """An empty tool name raises ValueError — no container for no tool.

    Added for consistency with ``managed_labels``, which raises on an
    empty tool: without this, a legal prefix concatenated with
    ``""`` is a name that identifies no tool — a silent
    reconciliation mismatch.  It also falls out of the TSWAP-C210
    pattern naturally: the empty string fails the first-character
    rule.  Flagged in the RED report as an addition beyond the
    plan's explicit edge-case list.
    """
    # Arrange
    fn = _get_container_name()
    # Act / Assert
    with pytest.raises(ValueError):
        fn("acme-", "")


# ---------------------------------------------------------------------------
# container_name — the table mirrors the live TSWAP-C210 pattern
# ---------------------------------------------------------------------------


def test_name_table_rows_mirror_the_live_tswap_c210_pattern() -> None:
    """The table rows mirror the live TSWAP-C210 pattern, not a copy.

    The legal and rejected rows are a *deliberate mirror* of the rule
    ``validate.py`` owns — examples, not the rule itself.  This guard
    makes the mirror checkable: every legal row's concatenation must
    match the live pattern read at call time, and every rejected
    prefix must fail it.  If TSWAP-C210 changes, this test fails in
    the RED state too, telling a maintainer the table is stale before
    the GREEN step is even the question.  It is non-vacuous: a row
    added to the wrong table (uppercase in the legal rows, a legal
    concatenation among the rejected) fails it outright.  The
    defensive bad-tool rows (``LLAMA``, ``_bad``) are TSWAP-C210's
    own domain — covered by M1 behaviour 12's suite — and are not
    re-mirrored here.
    """
    # Arrange
    pattern = _get_name_pattern()
    # Act / Assert — every legal row matches the live pattern
    for prefix, tool, expected in _LEGAL_NAME_ROWS:
        assert expected == prefix + tool, (
            f"legal row's expected value is not the concatenation: "
            f"{expected!r} != {prefix + tool!r}"
        )
        assert pattern.fullmatch(prefix + tool) is not None, (
            f"legal row {prefix!r} + {tool!r} no longer matches the "
            "live TSWAP-C210 pattern — the table is stale"
        )
    # Act / Assert — every rejected prefix fails the live pattern
    for prefix in _REJECTED_PREFIXES:
        assert pattern.fullmatch(prefix + _TOOL) is None, (
            f"rejected prefix {prefix!r} now matches the live "
            "TSWAP-C210 pattern — the table is stale"
        )


# ---------------------------------------------------------------------------
# label_selector — the pinned public API
# ---------------------------------------------------------------------------


def test_label_selector_signature_is_pinned() -> None:
    """The public API is exactly the signature pinned in the docstring."""
    # Arrange
    fn = _get_label_selector()
    # Act
    signature = inspect.signature(fn)
    hints = typing.get_type_hints(fn)
    # Assert — name, order, kind, default
    assert list(signature.parameters) == ["namespace"]
    parameter = signature.parameters["namespace"]
    assert parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert parameter.default is inspect.Parameter.empty
    # Assert — annotations
    assert hints["namespace"] is str
    assert hints["return"] == dict[str, str]


def test_label_selector_omitted_namespace_raises_type_error() -> None:
    """Omitting namespace is Python's own TypeError: there is no default."""
    # Arrange
    fn = _get_label_selector()
    # Act / Assert
    with pytest.raises(TypeError):
        fn()


# ---------------------------------------------------------------------------
# label_selector — the anti-drift agreement with managed_labels
# ---------------------------------------------------------------------------


def _assert_selector_matches_managed_labels(ns: str) -> None:
    """The selector selects on exactly the key ``managed_labels`` emits.

    The key is *derived* from a ``managed_labels`` call — the one key
    whose value is ``MANAGED_BY_VALUE`` — and never restated: if the
    two functions ever disagreed about the key, this check would fail
    instead of two copies of a literal drifting in lockstep.  The
    value is read from the module constant, so the selector cannot
    drift from ``managed_labels``' managed-by value either.
    """
    # Arrange
    managed_labels_fn = _get_managed_labels()
    selector_fn = _get_label_selector()
    managed_by_value = _get_managed_by_value()
    labels = managed_labels_fn(ns, _TOOL)
    managed_by_keys = [
        key for key, value in labels.items() if value == managed_by_value
    ]
    assert len(managed_by_keys) == 1, (
        "managed_labels must emit exactly one key with the "
        f"MANAGED_BY_VALUE, got {managed_by_keys}"
    )
    expected_key = managed_by_keys[0]
    # Act
    selector = selector_fn(ns)
    # Assert — exactly one entry, on the derived key, with the live value
    assert set(selector) == {expected_key}, (
        f"label_selector must select on the managed-by key "
        f"{expected_key!r}, got {set(selector)}"
    )
    assert selector[expected_key] == managed_by_value


@pytest.mark.parametrize("ns", [_ARBITRARY_NS, _ARBITRARY_NS_2])
def test_label_selector_key_is_exactly_managed_labels_managed_by_key(
    ns: str,
) -> None:
    """The selector key is exactly the key behaviour 6 emits."""
    _assert_selector_matches_managed_labels(ns)


def test_label_selector_key_matches_managed_labels_for_configured_namespace() -> None:
    """The anti-drift agreement holds for the real configured namespace.

    Both values are read at call time — the namespace from
    ``BUILT_IN_DEFAULTS`` and the key from a ``managed_labels`` call —
    so this file carries no configured value.
    """
    _assert_selector_matches_managed_labels(_configured_label_namespace())


# ---------------------------------------------------------------------------
# The no-configured-prefix guard — detector non-vacuity (in-memory decoys)
# ---------------------------------------------------------------------------


def test_container_prefix_literal_detector_reports_decoy_module() -> None:
    """The detector flags a decoy that hardcodes the configured prefix.

    Reach side of the non-vacuity proof: the decoy is formatted from
    ``BUILT_IN_DEFAULTS`` at call time — the exact third copy
    amendment 1 forbids — so the detector is proven against the live
    forbidden value, not a stale restatement of it.
    """
    # Arrange
    forbidden = _configured_container_prefix()
    tree = ast.parse(_DECOY_PREFIX_LITERAL_TEMPLATE.format(prefix=forbidden))
    # Act
    lines = _string_constant_lines(tree, forbidden)
    # Assert
    assert lines, (
        "Guard is blind: a decoy module hardcoding the configured "
        "container prefix produced no violation."
    )


def test_container_prefix_literal_detector_ignores_benign_and_near_miss() -> None:
    """The detector flags the configured prefix only, exactly.

    Precision side of the non-vacuity proof — and the point that
    differs from behaviour 6's namespace guard: the configured prefix
    is a short string, so a substring check would false-positive on
    any longer constant merely containing it.  A module where the
    prefix arrives as a parameter (the pattern amendment 1 wants) and
    a module carrying the value only as a substring of a different
    string must both produce no violation: the check is exact-value
    equality over string constants, not a substring tripwire.
    """
    # Arrange
    forbidden = _configured_container_prefix()
    benign = ast.parse(_DECOY_PREFIX_BENIGN)
    near_miss = ast.parse(_DECOY_PREFIX_NEAR_MISS_TEMPLATE.format(prefix=forbidden))
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


def test_labels_module_contains_no_configured_container_prefix_literal() -> None:
    """labels.py carries no literal copy of the configured prefix.

    Amendment 1: the configured prefix has exactly two owners —
    ``BUILT_IN_DEFAULTS["container_prefix"]`` and
    ``BackendConfig.container_prefix`` — and a third copy in
    ``labels.py`` could drift from both while every copy stayed
    self-consistent.  The check is AST-level exact-value equality over
    string constants (comments are not literals and cannot drift),
    scoped to ``labels.py`` itself, so it keeps working as later
    behaviours add functions to the same module.

    The guard passes in the RED state (behaviour 6's ``labels.py``
    carries no configured prefix) and locks the invariant for GREEN;
    it cannot pass vacuously: the detector's reach is proven on a
    decoy carrying the live forbidden value, and the forbidden value
    is read live, so the guard tracks any future change to the
    configured prefix.
    """
    # Arrange — the guard's subject must exist
    assert LABELS_FILE.is_file(), (
        "src/tool_swap/backend/labels.py is missing — the no-literal "
        "guard has nothing to walk."
    )
    forbidden = _configured_container_prefix()
    tree = ast.parse(LABELS_FILE.read_text(encoding="utf-8"))
    # Act
    offending = _string_constant_lines(tree, forbidden)
    # Assert
    assert not offending, (
        f"labels.py contains a literal copy of the configured "
        f"container prefix on line(s) {offending} — the prefix is "
        "owned by BUILT_IN_DEFAULTS and BackendConfig; the caller "
        "passes the resolved value (plan behaviour 7, amendment 1)."
    )

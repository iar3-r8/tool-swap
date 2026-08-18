"""Tests for M1 behaviour 14 — withdrawn and reserved keys (§6 rules 4, 1c).

See ``plans/m1-configuration.md`` §1, behaviour 14 (lines 439-450), and its
"Confirmed contract details (2026-08-18)" block (lines 452-644).  This file
is the executable form of that contract: the six rule constants
(``TSWAP_C400_RULE`` … ``TSWAP_C405_RULE``) and the ``RESERVED_KEYS``
mapping do not exist yet in ``src/tool_swap/config/validate.py``
(behaviour 13 shipped the C3xx rules only), and the ``reserved_keys``
carrier field does not exist yet on ``ResolvedTool``.  This module
therefore fails collection with a single clean ``ImportError`` naming
exactly one missing name:

    ImportError: cannot import name 'TSWAP_C400_RULE'
        from 'tool_swap.config.validate'

(``TSWAP_C400_RULE`` is the first missing name in the import list; Python
reports the first one it fails on.)  Every test body below pins a concrete
behaviour the GREEN step must satisfy, so the assertions — not just the
import — are the contract.

Pinned public API (the names the GREEN step must add to ``validate.py``):

- ``TSWAP_C400_RULE`` … ``TSWAP_C405_RULE`` — module-level ``Rule``
  constants whose ids are the matching codes; all six ``Severity.ERROR``;
  every ``remedy`` non-empty; no import-time self-registration — all six
  are appended to ``BUILTIN_RULES`` in code order after the four
  behaviour-13 rules (16 landed rules in total).
- ``RESERVED_KEYS`` — the withdrawn/reserved keys mapped to the layers the
  schema reserves them at (plan block 2, mirroring the block-1 placement
  table): ``soft_ttl`` at inline / ``tool.yaml`` / defaults;
  ``scalar_inputs`` at inline / ``tool.yaml``; ``max_batch_bytes`` at
  inline / ``tool.yaml`` / defaults.  The group layer is never a
  reserved-key source (``GroupConfig`` gains none of the keys, block 1).

The rules read ONLY ``ResolvedTool`` fields (plan block 10):
``tool.reserved_keys`` (a trailing carrier tuple of ``(key, layer)``
pairs, most-specific-first then key-sorted — the tests build it directly),
``tool.values["runtime_server"]``, and ``tool.inputs`` entry dicts.  No
loader, no raw, no filesystem.

The ADR citations are pinned verbatim (path AND title, plan block 7),
verified against the ADR files' own ``# `` titles:

    plan/adr/0004-hard-stop-only-in-v1.md (ADR-0004 — v1 reclaims
    resources by stopping containers; soft unload is deferred)
    plan/adr/0005-one-uniform-batched-calling-convention.md (ADR-0005 —
    One uniform calling convention: every handler takes and returns a list)

Locations follow the behaviour-12/13 form:
``Location(file=str(config.path), yaml_path=<dotted path>,
line=config.line_for(<the same string>))`` — pinned relationally (both a
fixed-int ``line_for`` and a ``None``-returning one), never a hardcoded
line number; ``tools.<name>.inputs.<i>.batchable`` uses the loader's
dotted-numeric convention while the C404 message names the entry
``inputs[<i>]`` (the two conventions deliberately differ, plan block 6).

Conventions mirror ``tests/unit/config/test_validate_descriptions.py``:
pytest, AAA, snake_case, Google docstrings, an autouse fixture calling
``unregister_all()`` before AND after every test (the registry is shared
module state), and the C4xx rules registered explicitly per test.  No
``importlib.reload`` anywhere.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest
from tool_swap import __version__
from tool_swap.config.errors import ConfigReport, Diagnostic, Severity
from tool_swap.config.origin import OriginMap
from tool_swap.config.resolver import ResolvedTool
from tool_swap.config.validate import (  # noqa: E501  (names absent in RED step)
    TSWAP_C400_RULE,
    TSWAP_C401_RULE,
    TSWAP_C402_RULE,
    TSWAP_C403_RULE,
    TSWAP_C404_RULE,
    TSWAP_C405_RULE,
    BUILTIN_RULES,
    RESERVED_KEYS,
    Rule,
    ValidatedConfig,
    register,
    unregister_all,
    validate_config,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The six behaviour-12 rule ids (§6 rules 2 and 3), in code order — the
#: block immediately before the behaviour-13 append (mirrors
#: ``_BEHAVIOUR_12_IDS`` in ``test_validate_names_groups.py`` and
#: ``test_validate_descriptions.py``).
_BEHAVIOUR_12_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C210",
    "TSWAP-C211",
    "TSWAP-C220",
    "TSWAP-C221",
    "TSWAP-C222",
    "TSWAP-C223",
)

#: The four behaviour-13 rule ids (§6 rule 6b), in code order (mirrors
#: ``_BEHAVIOUR_13_IDS`` in ``test_validate_descriptions.py``).
_BEHAVIOUR_13_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C300",
    "TSWAP-C301",
    "TSWAP-C302",
    "TSWAP-C303",
)

#: The six behaviour-14 rule ids (§6 rules 4 and 1c), in code order.
_BEHAVIOUR_14_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C400",
    "TSWAP-C401",
    "TSWAP-C402",
    "TSWAP-C403",
    "TSWAP-C404",
    "TSWAP-C405",
)

#: The pinned ADR-0004 citation — path AND title, verbatim (plan block 7),
#: verified against the ADR file's own ``# `` heading.
_ADR_0004_CITATION: Final[str] = (
    "plan/adr/0004-hard-stop-only-in-v1.md (ADR-0004 — v1 reclaims "
    "resources by stopping containers; soft unload is deferred)"
)

#: The pinned ADR-0005 citation — path AND title, verbatim (plan block 7),
#: verified against the ADR file's own ``# `` heading.  Both C403 and C404
#: must cite this same string so the two consumers cannot drift.
_ADR_0005_CITATION: Final[str] = (
    "plan/adr/0005-one-uniform-batched-calling-convention.md "
    "(ADR-0005 — One uniform calling convention: every handler takes "
    "and returns a list)"
)

#: The pinned C400 remedy (plan block 7): it names both keys.
_C400_REMEDY: Final[str] = (
    "remove soft_ttl; use ttl: — it is the only idle timer in v1"
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _tool(
    name: str,
    *,
    reserved_keys: tuple[tuple[str, str], ...] = (),
    values: dict[str, object] | None = None,
    inputs: list[dict[str, object]] | None = None,
    outputs: list[dict[str, object]] | None = None,
    params: list[dict[str, object]] | None = None,
) -> ResolvedTool:
    """Build a ``ResolvedTool`` carrying behaviour-14's read surface.

    Args:
        name: the tool name (used as both the ``tools`` dict key and the
            ``ResolvedTool.name`` in every fixture, so the two namespaces
            agree).
        reserved_keys: the ``reserved_keys`` trailing carrier — a tuple of
            ``(key, layer)`` pairs, most-specific-first then key-sorted.
            The tests build it DIRECTLY exactly as the resolver's scan
            would emit it (no loader, no raw).
        values: flat field name -> value; defaults to ``{}`` (the reserved
            keys are never resolvable fields, so they never appear here).
        inputs: the ``inputs`` carrier field (behaviour 13's carrier);
            ``None`` = absent, ``[]`` = declared empty.
        outputs: the ``outputs`` carrier field.
        params: the ``params`` carrier field.

    Returns:
        A frozen ``ResolvedTool`` with ``origins=OriginMap()`` and no
        diagnostics.
    """
    return ResolvedTool(
        name=name,
        values=values if values is not None else {},
        origins=OriginMap(),
        diagnostics=[],
        reserved_keys=reserved_keys,  # type: ignore[call-arg]
        inputs=inputs,
        outputs=outputs,
        params=params,
    )


def _config(
    tools: dict[str, ResolvedTool],
    line_for: Callable[[str], int | None] | None = None,
    path: Path | None = None,
) -> ValidatedConfig:
    """Build a ``ValidatedConfig`` fake (no loader, no filesystem).

    The C4xx rules read only the carrier fields on the tools and
    ``values["runtime_server"]``, so the raw block is an inert
    placeholder.

    Args:
        tools: name -> ``ResolvedTool`` (positional field).
        line_for: dotted YAML path -> 1-based line or ``None``; defaults
            to a ``None``-returning mapping.
        path: the config file path; defaults to ``Path("tools.yaml")``.

    Returns:
        The frozen ``ValidatedConfig``.
    """
    return ValidatedConfig(
        tools=tools,
        raw={"tools": {}},
        line_for=line_for if line_for is not None else (lambda _p: None),
        path=path if path is not None else Path("tools.yaml"),
    )


def _diagnostics_by_code(report: ConfigReport) -> dict[str, list[Diagnostic]]:
    """Group a report's diagnostics by code for set-based assertions.

    Args:
        report: a ``ConfigReport``.

    Returns:
        Code -> the diagnostics carrying that code.
    """
    by_code: dict[str, list[Diagnostic]] = {}
    for d in report.diagnostics:
        by_code.setdefault(d.code, []).append(d)
    return by_code


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Start and end every test with an empty, known registry.

    The registry is shared module state: each test registers exactly the
    C4xx rules it exercises (explicitly, like the behaviour-13 file) and
    must not depend on — and must not leak — registration state.
    """
    unregister_all()
    try:
        yield
    finally:
        unregister_all()


# ---------------------------------------------------------------------------
# 1. The rule objects and the RESERVED_KEYS mapping
# ---------------------------------------------------------------------------


def test_rule_objects_carry_expected_ids_and_severities() -> None:
    """Each rule instance carries its id, ERROR severity, and a remedy.

    Plan block 7: "All six rules are Severity.ERROR.  Every remedy is
    non-empty."

    Arrangement: the six rule objects imported from ``validate``.
    Action: read back ``id``, ``severity`` and ``remedy``.
    Assertion: ids are ``TSWAP-C400``…``TSWAP-C405`` in that order; all
    six are ERROR; every remedy is a non-empty string.
    """
    rules = (
        TSWAP_C400_RULE,
        TSWAP_C401_RULE,
        TSWAP_C402_RULE,
        TSWAP_C403_RULE,
        TSWAP_C404_RULE,
        TSWAP_C405_RULE,
    )

    assert [rule.id for rule in rules] == list(_BEHAVIOUR_14_IDS)
    assert [rule.severity for rule in rules] == [Severity.ERROR] * 6
    for rule in rules:
        assert isinstance(rule.remedy, str)
        assert rule.remedy.strip() != ""


def test_builtin_rules_append_the_behaviour_14_codes_in_code_order() -> None:
    """The six rules are appended to ``BUILTIN_RULES`` after behaviour 13.

    Plan block 9: all six are appended to ``BUILTIN_RULES`` in code order
    after behaviour 13's four, and their *identity* is what
    ``register_builtin_rules()`` relies on for idempotency, so the tuple
    must hold the very module-level singletons, not equal stand-ins.

    The position is asserted **relative to the behaviour-12/13 blocks**,
    not tail-anchored: the append order is cumulative — behaviours 15-19
    each append after the previous one — so "the last six ids" (or a
    total-count pin) would be false as soon as behaviour 15's seven C5xx
    rules land.  The C4xx block's position, immediately after the four
    behaviour-13 codes, is stable under every future append.

    Arrangement: the ``BUILTIN_RULES`` tuple.
    Action: locate the first behaviour-14 id; check object identity per
    rule.
    Assertion: the first C4xx id sits at index
    ``len(_BEHAVIOUR_12_IDS) + len(_BEHAVIOUR_13_IDS)`` (immediately after
    the behaviour-12 and behaviour-13 codes), the six ids from there are
    a contiguous, in-code-order block, and each rule constant is an
    element of the tuple.
    """
    ids = [rule.id for rule in BUILTIN_RULES]

    first_c400 = ids.index(_BEHAVIOUR_14_IDS[0])
    assert first_c400 == len(_BEHAVIOUR_12_IDS) + len(_BEHAVIOUR_13_IDS)
    assert ids[first_c400 : first_c400 + len(_BEHAVIOUR_14_IDS)] == list(
        _BEHAVIOUR_14_IDS
    )
    for constant in (
        TSWAP_C400_RULE,
        TSWAP_C401_RULE,
        TSWAP_C402_RULE,
        TSWAP_C403_RULE,
        TSWAP_C404_RULE,
        TSWAP_C405_RULE,
    ):
        assert any(rule is constant for rule in BUILTIN_RULES)


def test_reserved_keys_mapping_is_pinned_verbatim() -> None:
    """``RESERVED_KEYS`` maps each key to exactly its reserved layers.

    Plan block 2: the mapping mirrors the schema placement table (block 1)
    — ``soft_ttl`` and ``max_batch_bytes`` at inline / ``tool.yaml`` /
    defaults; ``scalar_inputs`` at inline / ``tool.yaml`` only.

    Arrangement: the module constant.
    Action: compare the key set and each layer frozenset.
    Assertion: exact equality for all three entries and no fourth key.
    """
    assert set(RESERVED_KEYS) == {
        "soft_ttl",
        "scalar_inputs",
        "max_batch_bytes",
    }
    assert RESERVED_KEYS["soft_ttl"] == frozenset(
        {"inline", "tool.yaml", "defaults"}
    )
    assert RESERVED_KEYS["scalar_inputs"] == frozenset({"inline", "tool.yaml"})
    assert RESERVED_KEYS["max_batch_bytes"] == frozenset(
        {"inline", "tool.yaml", "defaults"}
    )


# ---------------------------------------------------------------------------
# 2. TSWAP-C400 — soft_ttl (plan lines 443, 449; blocks 1, 2, 6, 7)
# ---------------------------------------------------------------------------


def test_c400_emits_one_error_per_key_layer_pair() -> None:
    """A ``soft_ttl`` present at each layer yields one error per pair.

    Plan block 2: the same key present in two reserved layers yields two
    ``(key, layer)`` pairs and therefore two diagnostics — an author who
    wrote it twice has two places to delete it.  The inline and
    ``tool.yaml`` layers both resolve to ``tools.<name>.soft_ttl`` (the
    line map belongs to the root config, so a ``tool.yaml``-authored key
    has no line here); the ``defaults:`` layer resolves to
    ``defaults.soft_ttl``.

    Arrangement: one tool whose carrier holds ``soft_ttl`` at all three
    layers; only ``TSWAP_C400_RULE`` registered.
    Action: run ``validate_config``.
    Assertion: exactly three ``TSWAP-C400`` ERROR diagnostics — two at
    ``tools.t1.soft_ttl`` and one at ``defaults.soft_ttl`` — and no other
    codes.
    """
    register(TSWAP_C400_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                reserved_keys=(
                    ("soft_ttl", "inline"),
                    ("soft_ttl", "tool.yaml"),
                    ("soft_ttl", "defaults"),
                ),
            )
        }
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C400"}
    diagnostics = by_code["TSWAP-C400"]
    assert len(diagnostics) == 3
    assert all(d.severity is Severity.ERROR for d in diagnostics)
    paths = [d.location.yaml_path for d in diagnostics]
    assert paths.count("tools.t1.soft_ttl") == 2
    assert paths.count("defaults.soft_ttl") == 1


def test_c400_message_names_the_layer_in_words() -> None:
    """The ``layer`` element of the pair is load-bearing for the message.

    Plan block 6: a ``tool.yaml``-authored key has no line in the root
    config's map, so the message must name the layer in words (e.g.
    "written in the tool's ``tool.yaml``") instead of sending the author
    to the wrong file — the same self-sufficiency requirement as
    behaviour 13's C301–C303.

    Arrangement: one tool whose carrier holds ``soft_ttl`` at the
    ``tool.yaml`` and the ``defaults`` layers; only C400 registered.
    Action: run ``validate_config`` and select each diagnostic by its
    location path.
    Assertion: the ``tools.t1.soft_ttl`` diagnostic's message mentions
    ``tool.yaml``; the ``defaults.soft_ttl`` diagnostic's message mentions
    ``defaults``.
    """
    register(TSWAP_C400_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                reserved_keys=(
                    ("soft_ttl", "tool.yaml"),
                    ("soft_ttl", "defaults"),
                ),
            )
        }
    )

    report = validate_config(cfg)

    by_path: dict[str, list[Diagnostic]] = {}
    for d in _diagnostics_by_code(report)["TSWAP-C400"]:
        by_path.setdefault(d.location.yaml_path, []).append(d)
    (tool_yaml,) = by_path["tools.t1.soft_ttl"]
    (defaults,) = by_path["defaults.soft_ttl"]

    assert "tool.yaml" in tool_yaml.message
    assert "defaults" in defaults.message


def test_c400_message_cites_adr_0004_by_path_and_title() -> None:
    """The C400 message carries the ADR-0004 citation verbatim.

    Plan line 443 / block 7: the citation — path AND title, verified
    against the ADR file's own ``# `` heading — goes in the message (not
    only the remedy), so it survives ``--json`` for the same reason
    behaviour 13's banner does.

    Arrangement: one tool with ``soft_ttl`` at the inline layer; only C400
    registered.
    Action: run ``validate_config``.
    Assertion: the pinned citation string appears verbatim in the message.
    """
    register(TSWAP_C400_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", reserved_keys=(("soft_ttl", "inline"),))}
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    (d,) = by_code["TSWAP-C400"]
    assert _ADR_0004_CITATION in d.message


def test_c400_message_states_ttl_is_the_only_idle_timer() -> None:
    """The C400 message states that TTL is the only idle timer in v1.

    Plan line 443 / block 7: besides the ADR citation, the message states
    that ``ttl`` is the only idle timer.

    Arrangement: one tool with ``soft_ttl`` at the inline layer; only C400
    registered.
    Action: run ``validate_config``.
    Assertion: the message contains the "only idle timer" statement.
    """
    register(TSWAP_C400_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", reserved_keys=(("soft_ttl", "inline"),))}
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    (d,) = by_code["TSWAP-C400"]
    assert "only idle timer" in d.message


def test_c400_remedy_is_pinned_verbatim() -> None:
    """The C400 remedy is the pinned string (plan block 7).

    The direction names both keys: remove ``soft_ttl``, use ``ttl:``.

    Arrangement: the rule constant.
    Action: compare the remedy to the pinned text.
    Assertion: exact equality.
    """
    assert TSWAP_C400_RULE.remedy == _C400_REMEDY


def test_c400_surfaces_as_c400_not_c101() -> None:
    """The withdrawn key is C400's job, not the generic unknown-key code.

    Plan line 443 / block 1 (§5.3): the key is *accepted by the schema and
    rejected at load* so that re-promotion stays additive.  The
    schema-level acceptance is the schema's job (behaviour 14's
    ``schema.py`` edit, tested in ``test_schema.py``); this test pins the
    RULE side of that contract: the diagnostic code is ``TSWAP-C400``,
    and a ``TSWAP-C101`` must not be what surfaces.

    Arrangement: one tool with ``soft_ttl`` at the inline layer; only C400
    registered (C101 is a schema-layer code with no rule here, so the pin
    is on the codes present in the report).
    Action: run ``validate_config``.
    Assertion: the only code present is ``TSWAP-C400``; no
    ``TSWAP-C101``.
    """
    register(TSWAP_C400_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", reserved_keys=(("soft_ttl", "inline"),))}
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C400"}
    assert "TSWAP-C101" not in by_code


def test_c400_null_value_still_fires() -> None:
    """``soft_ttl: null`` is still PRESENT and still rejected.

    Plan line 449 / block 2: the key's presence is the signal, not its
    value — ``None`` is both the schema default and a legal authored
    value, so only the resolver's raw-presence scan can tell them apart,
    and the scan emits the ``(key, layer)`` pair regardless of the value.
    The value never reaches the rule (the field is ``Any`` and never
    read), so the test builds the carrier with the pair exactly as the
    resolver would for a null value and asserts the diagnostic fires.

    Arrangement: one tool whose carrier holds the pair for a null value;
    only C400 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C400`` ERROR at
    ``tools.t1.soft_ttl``.
    """
    register(TSWAP_C400_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", reserved_keys=(("soft_ttl", "inline"),))}
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C400"}
    (d,) = by_code["TSWAP-C400"]
    assert d.severity is Severity.ERROR
    assert d.location.yaml_path == "tools.t1.soft_ttl"


def test_reserved_keys_never_include_the_group_layer() -> None:
    """A ``soft_ttl`` under ``groups:`` is NOT a C400 source (block 1).

    ``GroupConfig`` gets none of the reserved keys on purpose: a
    misspelled or withdrawn lifecycle key inside ``groups:`` stays an
    honest schema-level ``TSWAP-C101`` (its docstring already states the
    reason for ``ttl``, and the same argument applies verbatim to
    ``soft_ttl``).  Pinned structurally, as the plan prescribes:
    ``"groups"`` is not a member of any of ``RESERVED_KEYS``' layer
    frozensets, so the resolver's scan can never emit a pair whose layer
    is ``"groups"`` — a ``groups.g1.soft_ttl`` is therefore a C101 and
    not a C400, and this test exists so nobody "fixes" that later.

    Arrangement: the ``RESERVED_KEYS`` constant.
    Action: inspect every layer frozenset.
    Assertion: ``"groups"`` is absent from all of them.
    """
    for layers in RESERVED_KEYS.values():
        assert "groups" not in layers


# ---------------------------------------------------------------------------
# 3. TSWAP-C401 / C402 — runtime.server (plan lines 444-445; block 3)
# ---------------------------------------------------------------------------


def test_c401_flags_native_runtime_server() -> None:
    """``runtime.server: native`` is a C401 error naming the version.

    Plan line 444 / block 7: the message must contain "not implemented in
    this version", the current version from ``tool_swap.__version__``
    (imported here, never hardcoded — the package's single public version
    string, not ``schema.py``'s private duplicate) and state that
    ``bentoml`` is the only implemented backend.

    Arrangement: one tool resolving ``runtime_server`` to ``"native"``;
    only ``TSWAP_C401_RULE`` registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C401`` ERROR at
    ``tools.t1.runtime_server`` whose message carries all three pins.
    """
    register(TSWAP_C401_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", values={"runtime_server": "native"})}
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C401"}
    (d,) = by_code["TSWAP-C401"]
    assert d.severity is Severity.ERROR
    assert "not implemented in this version" in d.message
    assert __version__ in d.message
    assert "bentoml" in d.message
    assert d.location.yaml_path == "tools.t1.runtime_server"


@pytest.mark.parametrize("value", ["ray", "spark", "kubernetes"])
def test_c402_flags_unknown_runtime_server_value(value: str) -> None:
    """A ``runtime.server`` outside {bentoml, native} is a C402 error.

    Plan line 445 / block 7: the unknown-value error names the offending
    value and LISTS the valid ones (``bentoml`` and ``native``).

    Arrangement: one tool resolving ``runtime_server`` to the parametrized
    value; only ``TSWAP_C402_RULE`` registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C402`` ERROR at
    ``tools.t1.runtime_server`` naming the offending value and both valid
    values.
    """
    register(TSWAP_C402_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", values={"runtime_server": value})}
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C402"}
    (d,) = by_code["TSWAP-C402"]
    assert d.severity is Severity.ERROR
    assert value in d.message
    assert "bentoml" in d.message
    assert "native" in d.message
    assert d.location.yaml_path == "tools.t1.runtime_server"


def test_c401_and_c402_accept_bentoml() -> None:
    """``runtime.server: bentoml`` fires neither C401 nor C402.

    Plan block 8: the resolved built-in default ``"bentoml"`` is the
    commonest case in the whole suite, and an over-eager C402 would break
    it everywhere at once.

    Arrangement: one tool resolving ``runtime_server`` to ``"bentoml"``;
    both rules registered.
    Action: run ``validate_config``.
    Assertion: no diagnostics at all.
    """
    register(TSWAP_C401_RULE)
    register(TSWAP_C402_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", values={"runtime_server": "bentoml"})}
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# 4. TSWAP-C403 — scalar_inputs (plan line 446; blocks 1, 2, 7)
# ---------------------------------------------------------------------------


def test_c403_flags_scalar_inputs_citing_adr_0005() -> None:
    """A reserved ``scalar_inputs`` is a C403 error citing ADR-0005.

    Plan line 446 / block 7: the error cites ADR-0005 by path AND title
    verbatim and states that every handler takes and returns a list.
    Same accepted-then-rejected treatment as C400, for the same reason.

    Arrangement: one tool whose carrier holds ``scalar_inputs`` at the
    ``tool.yaml`` layer; only ``TSWAP_C403_RULE`` registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C403`` ERROR at
    ``tools.t1.scalar_inputs`` whose message carries the pinned citation
    and the uniform-convention statement.
    """
    register(TSWAP_C403_RULE)
    cfg = _config(
        tools={
            "t1": _tool("t1", reserved_keys=(("scalar_inputs", "tool.yaml"),))
        }
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C403"}
    (d,) = by_code["TSWAP-C403"]
    assert d.severity is Severity.ERROR
    assert _ADR_0005_CITATION in d.message
    assert "takes and returns a list" in d.message
    assert d.location.yaml_path == "tools.t1.scalar_inputs"


def test_reserved_keys_scalar_inputs_excludes_the_defaults_layer() -> None:
    """``defaults.scalar_inputs`` is NOT a C403 source (block 2).

    The scan is layer-scoped per key, exactly mirroring the schema
    placement table: ``scalar_inputs`` is never a ``defaults:`` key
    (ADR-0005 removed it from the per-tool authoring surface), so
    ``RESERVED_KEYS["scalar_inputs"]`` does not contain ``"defaults"``.
    ``defaults.scalar_inputs`` therefore stays an honest ``TSWAP-C101``
    unknown key, and scanning for it in ``defaults:`` too would make one
    mistake produce two diagnostics (C101 *and* C403) — the exact
    double-reporting behaviour 13 avoided with its
    non-string-description rule.  One mistake, one diagnostic.

    Arrangement: the ``RESERVED_KEYS`` constant.
    Action: inspect the ``scalar_inputs`` layer set.
    Assertion: ``"defaults"`` absent; exactly {inline, tool.yaml}.
    """
    assert "defaults" not in RESERVED_KEYS["scalar_inputs"]
    assert RESERVED_KEYS["scalar_inputs"] == frozenset({"inline", "tool.yaml"})


# ---------------------------------------------------------------------------
# 5. TSWAP-C404 — per-input batchable: (plan line 447; block 4)
# ---------------------------------------------------------------------------


def test_c404_flags_batchable_input_entry_naming_the_entry() -> None:
    """A per-input ``batchable:`` key is a C404 error naming the entry.

    Plan line 447 / block 4: one diagnostic per offending entry, named by
    the behaviour-13 convention (the entry's ``name`` when it is a
    non-empty string, else the positional label) and citing ADR-0005 —
    batching is a property of the tool, not of an input.

    Arrangement: one input entry named ``payload`` carrying
    ``batchable: true``; only ``TSWAP_C404_RULE`` registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C404`` ERROR naming ``payload`` and
    carrying the pinned ADR-0005 citation, at
    ``tools.t1.inputs.0.batchable`` (dotted-numeric index).
    """
    register(TSWAP_C404_RULE)
    entry: dict[str, object] = {
        "name": "payload",
        "type": "string",
        "description": "A payload.",
        "batchable": True,
    }
    cfg = _config(tools={"t1": _tool("t1", inputs=[entry])})

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C404"}
    (d,) = by_code["TSWAP-C404"]
    assert d.severity is Severity.ERROR
    assert "payload" in d.message
    assert _ADR_0005_CITATION in d.message
    assert d.location.yaml_path == "tools.t1.inputs.0.batchable"


def test_c404_batchable_false_still_fires() -> None:
    """``batchable: false`` is as withdrawn as ``batchable: true``.

    Plan block 4: presence-not-value — the key being present in the entry
    is the signal, whatever its value.  Same rule as C400, for the same
    reason.

    Arrangement: one input entry named ``payload`` carrying
    ``batchable: false``; only C404 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C404`` ERROR naming ``payload``.
    """
    register(TSWAP_C404_RULE)
    entry: dict[str, object] = {
        "name": "payload",
        "type": "string",
        "description": "A payload.",
        "batchable": False,
    }
    cfg = _config(tools={"t1": _tool("t1", inputs=[entry])})

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C404"}
    (d,) = by_code["TSWAP-C404"]
    assert "payload" in d.message


def test_c404_names_unnamed_entries_positionally() -> None:
    """An entry without a usable name is named ``inputs[<i>]``.

    Plan block 4: C404 reuses behaviour 13's existing entry-label helper
    rather than growing a second one, so the two rules produce the same
    label for the same entry.  The message label (``inputs[<i>]``) and
    the location path (``inputs.<i>.batchable``, dotted-numeric)
    deliberately differ (plan block 6).

    Arrangement: two input entries — index 0 clean, index 1 an unnamed
    entry carrying ``batchable``.
    Action: run only ``TSWAP_C404_RULE``.
    Assertion: exactly one C404 whose message names ``inputs[1]`` and
    whose location is ``tools.t1.inputs.1.batchable``.
    """
    register(TSWAP_C404_RULE)
    clean: dict[str, object] = {
        "name": "a",
        "type": "string",
        "description": "First.",
    }
    unnamed: dict[str, object] = {
        "type": "string",
        "description": "Second.",
        "batchable": True,
    }
    cfg = _config(tools={"t1": _tool("t1", inputs=[clean, unnamed])})

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C404"}
    (d,) = by_code["TSWAP-C404"]
    assert "inputs[1]" in d.message
    assert d.location.yaml_path == "tools.t1.inputs.1.batchable"


def test_c404_does_not_scan_outputs_or_params() -> None:
    """A ``batchable`` key under ``outputs:`` or ``params:`` does NOT fire.

    Plan block 4: ``batchable`` was only ever an ``inputs:`` flag
    (ADR-0005), and a ``batchable`` under ``params:`` is a different
    mistake with no spec answer.  The scope is a decision rather than an
    omission, so it is pinned.

    Arrangement: one tool with ``batchable`` entries in ``outputs`` and
    ``params`` but none in ``inputs``; only C404 registered.
    Action: run ``validate_config``.
    Assertion: no diagnostics at all.
    """
    register(TSWAP_C404_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                outputs=[{"name": "out", "type": "string", "batchable": True}],
                params=[{"name": "p", "type": "string", "batchable": True}],
            )
        }
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


@pytest.mark.parametrize("inputs_value", [None, []])
def test_c404_inputs_absent_or_empty(inputs_value: object) -> None:
    """``inputs:`` absent (``None``) or empty (``[]``) yields nothing.

    Plan block 4: the rule iterates ``tool.inputs`` when it is a list;
    the two empty forms stay distinct from an offending list.

    Arrangement: one tool whose ``inputs`` carrier is the parametrized
    value; only C404 registered.
    Action: run ``validate_config``.
    Assertion: no diagnostics at all.
    """
    register(TSWAP_C404_RULE)
    cfg = _config(tools={"t1": _tool("t1", inputs=inputs_value)})

    report = validate_config(cfg)

    assert report.diagnostics == ()


@pytest.mark.parametrize(
    "inputs_value",
    [
        "not a list",
        42,
        [{"name": "a", "type": "string"}, "not a mapping"],
    ],
)
def test_c404_skips_malformed_shapes_silently(inputs_value: object) -> None:
    """A non-list block or a non-mapping entry is skipped silently.

    Plan block 4 mirrors behaviour 13's robustness: a non-list block is
    skipped silently, and a non-mapping entry is skipped silently
    (malformed shapes are behaviour 20's ``TSWAP-S1xx``) — C404 must not
    double-report or crash on them.

    Arrangement: one tool whose ``inputs`` carrier is the parametrized
    malformed shape; only C404 registered.
    Action: run ``validate_config``.
    Assertion: no diagnostics at all (no C404, no internal
    ``TSWAP-C999``).
    """
    register(TSWAP_C404_RULE)
    cfg = _config(tools={"t1": _tool("t1", inputs=inputs_value)})

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# 6. TSWAP-C405 — max_batch_bytes (plan line 448; blocks 5, 7)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("layer", "expected_path"),
    [
        ("inline", "tools.t1.max_batch_bytes"),
        ("tool.yaml", "tools.t1.max_batch_bytes"),
        ("defaults", "defaults.max_batch_bytes"),
    ],
)
def test_c405_flags_max_batch_bytes_in_each_layer(
    layer: str, expected_path: str
) -> None:
    """A reserved ``max_batch_bytes`` is a C405 error naming the remedy.

    Plan line 448 (corrected 2026-08-18) / block 5: the key is reserved in
    the schema and rejected by this rule, so the author gets the spec's
    answer instead of a bare unknown-key error — the message states the
    key does not exist and names the mitigation: it contains
    ``max_batch_size`` ("set ``max_batch_size`` low for large payloads",
    §5.5).  C405 fires from ``reserved_keys`` like C400/C403 (block 5's
    resolution of the plan's internal contradiction).

    Arrangement: one tool whose carrier holds ``max_batch_bytes`` at the
    parametrized layer; only ``TSWAP_C405_RULE`` registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C405`` ERROR at the parametrized
    ``yaml_path`` whose message names the mitigation key.
    """
    register(TSWAP_C405_RULE)
    cfg = _config(
        tools={
            "t1": _tool("t1", reserved_keys=(("max_batch_bytes", layer),))
        }
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C405"}
    (d,) = by_code["TSWAP-C405"]
    assert d.severity is Severity.ERROR
    assert "max_batch_size" in d.message
    assert d.location.yaml_path == expected_path


# ---------------------------------------------------------------------------
# 7. Cross-cutting pins: locations, only-own-codes, one-report
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "tool_kwargs", "yaml_path"),
    [
        (
            TSWAP_C400_RULE,
            {"reserved_keys": (("soft_ttl", "inline"),)},
            "tools.t1.soft_ttl",
        ),
        (
            TSWAP_C401_RULE,
            {"values": {"runtime_server": "native"}},
            "tools.t1.runtime_server",
        ),
        (
            TSWAP_C402_RULE,
            {"values": {"runtime_server": "ray"}},
            "tools.t1.runtime_server",
        ),
        (
            TSWAP_C403_RULE,
            {"reserved_keys": (("scalar_inputs", "inline"),)},
            "tools.t1.scalar_inputs",
        ),
        (
            TSWAP_C404_RULE,
            {"inputs": [{"name": "p", "type": "string", "batchable": True}]},
            "tools.t1.inputs.0.batchable",
        ),
        (
            TSWAP_C405_RULE,
            {"reserved_keys": (("max_batch_bytes", "inline"),)},
            "tools.t1.max_batch_bytes",
        ),
    ],
)
@pytest.mark.parametrize("line", [42, None])
def test_location_contract_per_code(
    rule: Rule,
    tool_kwargs: dict[str, object],
    yaml_path: str,
    line: int | None,
) -> None:
    """Every C4xx location consults ``line_for`` and ``config.path``.

    Plan block 6: ``Location(file=str(config.path), yaml_path=<pinned>,
    line=config.line_for(<the same string>))`` — the file is never
    hardcoded and ``line=None`` is a legal outcome, so the test asserts
    the RELATION ``location.line == line_for(location.yaml_path)``, never
    a hardcoded line number; both a fixed-int ``line_for`` and a
    ``None``-returning one are pinned.

    Arrangement: one offending tool per code, a non-default path, and a
    ``line_for`` returning the parametrized value for any dotted path.
    Action: run only the parametrized rule.
    Assertion: exactly one diagnostic; its file is ``str(config.path)``,
    its yaml_path is the pinned path, and its line equals
    ``config.line_for(yaml_path)``.
    """
    register(rule)
    cfg = _config(
        tools={"t1": _tool("t1", **tool_kwargs)},  # type: ignore[arg-type]
        line_for=(lambda _p, _line=line: _line),
        path=Path("my-config.yaml"),
    )

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert d.location.file == "my-config.yaml"
    assert d.location.yaml_path == yaml_path
    assert d.location.line == cfg.line_for(d.location.yaml_path)


def test_clean_tool_produces_no_c4xx_diagnostics() -> None:
    """A config with none of the reserved keys produces no ``C4xx``.

    Plan block 8 (only-own-codes): a tool with no reserved keys,
    ``runtime_server`` the resolved built-in default ``"bentoml"``, and
    well-described inputs must not trip any C4xx.  This includes the
    five-line minimal config (behaviour 23 requires zero diagnostics, and
    a C4xx firing on an empty tool would break it) and the commonest case
    in the whole suite, which an over-eager C402 would break everywhere
    at once.

    Arrangement: one such tool; all six C4xx rules registered.
    Action: run ``validate_config``.
    Assertion: no code starting ``TSWAP-C4`` appears in the report.
    """
    for rule in (
        TSWAP_C400_RULE,
        TSWAP_C401_RULE,
        TSWAP_C402_RULE,
        TSWAP_C403_RULE,
        TSWAP_C404_RULE,
        TSWAP_C405_RULE,
    ):
        register(rule)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                values={"runtime_server": "bentoml"},
                inputs=[
                    {
                        "name": "payload",
                        "type": "string",
                        "description": "A payload.",
                    }
                ],
            )
        }
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert not any(code.startswith("TSWAP-C4") for code in by_code)


def test_multiple_reserved_problems_are_all_reported_in_one_pass() -> None:
    """Every C4xx finding for one tool lands in a single report.

    The "report every finding at once" contract (behaviour 11) applied to
    behaviour 14: a tool carrying ``soft_ttl`` + ``scalar_inputs`` +
    ``max_batch_bytes`` (three layers), a ``native`` runtime, and two
    ``batchable`` inputs yields ALL of them from one ``validate_config``
    call — no rule masks or shadows another.

    Arrangement: one such tool; all six C4xx rules registered.
    Action: run ``validate_config``.
    Assertion: one C400, one C401, one C403, two C404 (presence-not-value:
    the second entry is ``batchable: false``) and one C405 — six
    diagnostics, no C402 and no other codes.
    """
    for rule in (
        TSWAP_C400_RULE,
        TSWAP_C401_RULE,
        TSWAP_C402_RULE,
        TSWAP_C403_RULE,
        TSWAP_C404_RULE,
        TSWAP_C405_RULE,
    ):
        register(rule)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                reserved_keys=(
                    ("soft_ttl", "inline"),
                    ("scalar_inputs", "tool.yaml"),
                    ("max_batch_bytes", "defaults"),
                ),
                values={"runtime_server": "native"},
                inputs=[
                    {
                        "name": "a",
                        "type": "string",
                        "description": "First.",
                        "batchable": True,
                    },
                    {
                        "name": "b",
                        "type": "string",
                        "description": "Second.",
                        "batchable": False,
                    },
                ],
            )
        }
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {
        "TSWAP-C400",
        "TSWAP-C401",
        "TSWAP-C403",
        "TSWAP-C404",
        "TSWAP-C405",
    }
    assert len(by_code["TSWAP-C400"]) == 1
    assert len(by_code["TSWAP-C401"]) == 1
    assert len(by_code["TSWAP-C403"]) == 1
    assert len(by_code["TSWAP-C404"]) == 2
    assert len(by_code["TSWAP-C405"]) == 1
    assert len(report.diagnostics) == 6

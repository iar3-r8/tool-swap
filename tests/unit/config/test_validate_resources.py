"""Tests for M1 behaviour 16 — devices, workers, ports (§6 rules 4c, 7, 8).

See ``plans/m1-configuration.md`` behaviour 16 (lines 890-903) and its
"Confirmed contract details (2026-08-19)" block (items 1-11, lines
905-1083).  This file is the executable form of that contract: the seven
rule constants (``TSWAP_C520_RULE`` … ``TSWAP_C532_RULE``), the
``effective_port_range`` helper and the trailing ``gpu_count`` field on
``ValidatedConfig`` do not exist yet in
``src/tool_swap/config/validate.py`` (behaviour 15 shipped the C51x rules
and the 23-rule ``BUILTIN_RULES`` only).  This module therefore fails
collection with a single clean ``ImportError`` naming exactly one
missing name:

    ImportError: cannot import name 'TSWAP_C520_RULE'
        from 'tool_swap.config.validate'

(``TSWAP_C520_RULE`` is the first missing name in the import list; Python
reports the first one it fails on.)  Every test body below pins a
concrete behaviour the GREEN step must satisfy, so the assertions — not
just the import — are the contract.

Pinned public API (the names the GREEN step must add):

- ``TSWAP_C520_RULE`` — ERROR — a negative or non-integer device index
  (per offending entry; ``bool`` is excluded before the ``int`` test).
- ``TSWAP_C521_RULE`` — WARNING — a device index at or above the injected
  ``gpu_count``; skipped ENTIRELY and silently when ``gpu_count is None``
  (the M1 production default); ``gpu_count == 0`` is a legitimate
  "no GPUs on this host" value, not "unknown".
- ``TSWAP_C522_RULE`` — WARNING — a duplicate index within one tool's
  ``devices``; one diagnostic per tool, located at the LIST.
- ``TSWAP_C523_RULE`` — WARNING — ``workers > 1`` AND ``devices``
  non-empty; the message states the VRAM-multiplies mechanism and the
  remedy names BOTH options (reduce ``workers`` OR size the group's
  ``max_resident``).
- ``TSWAP_C530_RULE`` — ERROR — two tools sharing an explicit
  ``expose_host_port``; one diagnostic per colliding port at ``tools``,
  naming the port and every claiming tool.  ``bool`` values participate
  in neither C530 nor C531 (D21: nothing is allocated at validate
  time).
- ``TSWAP_C531_RULE`` — ERROR — an explicit port outside the effective
  ``backend.port_range`` (boundaries inclusive); ``expose_host_port: 0``
  fires UNCONDITIONALLY with the dedicated "0 means pick one" clause.
  Suppressed for the run by a ``C532``.
- ``TSWAP_C532_RULE`` — ERROR — an inverted or malformed
  ``backend.port_range`` (length ≠ 2, non-int/bool entry, ``low > high``,
  endpoint outside 1..65535); a non-LIST value is skipped silently
  (the schema's ``TSWAP-C105`` owns it).  ``low == high`` is legal.
  Suppresses ``C531`` (not ``C530``).
- ``effective_port_range(raw)`` — the behaviour-12 ``effective_groups``
  precedent applied to ``backend.port_range``: returns the value as
  authored (shape judgement is C532's job) and, when the ``backend:``
  block or its ``port_range`` key is absent, a FRESH copy of the schema
  default ``[7000, 7999]`` read from ``BackendConfig``'s own field
  default.  ``C531``/``C532`` must never read ``values["port_range"]``
  (plan item 3(a): that key is one of the 47 and is a lie).
- ``ValidatedConfig.gpu_count`` — trailing, keyword-only, defaulted to
  ``None``; nothing in M1 populates it, so C521 never fires in
  production.

The rules read ONLY ``tool.values["devices" | "workers" |
"expose_host_port"]``, ``config.raw`` (through ``effective_port_range``),
``config.gpu_count``, ``config.tools``, ``config.path`` and
``config.line_for``.  No rule touches the filesystem (``config.probe``
is never read) and none reads ``values["port_range"]``.

Conventions mirror ``tests/unit/config/test_validate_image_source.py``:
pytest, AAA, snake_case, Google docstrings, an autouse fixture calling
``unregister_all()`` before AND after every test (the registry is shared
module state), the C52x/C53x rules registered explicitly per test.  No
``importlib.reload`` anywhere.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest
from tool_swap.config.errors import ConfigReport, Diagnostic, Severity
from tool_swap.config.origin import OriginMap
from tool_swap.config.resolver import ResolvedTool
from tool_swap.config.validate import (  # noqa: E501  (names absent in RED step)
    TSWAP_C520_RULE,
    TSWAP_C521_RULE,
    TSWAP_C522_RULE,
    TSWAP_C523_RULE,
    TSWAP_C530_RULE,
    TSWAP_C531_RULE,
    TSWAP_C532_RULE,
    BUILTIN_RULES,
    Rule,
    ValidatedConfig,
    effective_port_range,
    register,
    unregister_all,
    validate_config,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The six behaviour-12 rule ids (§6 rules 2 and 3), in code order (mirrors
#: ``_BEHAVIOUR_12_IDS`` in ``test_validate_names_groups.py``).
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

#: The six behaviour-14 rule ids (§6 rules 4 and 1c), in code order
#: (mirrors ``_BEHAVIOUR_14_IDS`` in ``test_validate_reserved.py``).
_BEHAVIOUR_14_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C400",
    "TSWAP-C401",
    "TSWAP-C402",
    "TSWAP-C403",
    "TSWAP-C404",
    "TSWAP-C405",
)

#: The seven behaviour-15 rule ids (§6 rules 5 and 6), in code order
#: (mirrors ``_BEHAVIOUR_15_IDS`` in ``test_validate_image_source.py``).
_BEHAVIOUR_15_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C510",
    "TSWAP-C511",
    "TSWAP-C512",
    "TSWAP-C513",
    "TSWAP-C514",
    "TSWAP-C515",
    "TSWAP-C516",
)

#: The seven behaviour-16 rule ids (§6 rules 4c, 7, 8), in code order
#: (plan block 9).
_BEHAVIOUR_16_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C520",
    "TSWAP-C521",
    "TSWAP-C522",
    "TSWAP-C523",
    "TSWAP-C530",
    "TSWAP-C531",
    "TSWAP-C532",
)

#: The seven behaviour-16 rule constants, in code order.
_ALL_C52X_C53X_RULES: Final[tuple[Rule, ...]] = (
    TSWAP_C520_RULE,
    TSWAP_C521_RULE,
    TSWAP_C522_RULE,
    TSWAP_C523_RULE,
    TSWAP_C530_RULE,
    TSWAP_C531_RULE,
    TSWAP_C532_RULE,
)

#: The schema's own ``BackendConfig.port_range`` default (verified
#: against ``src/tool_swap/config/schema.py``: ``port_range: list[int]
#: = [7000, 7999]``).  ``effective_port_range`` must return a copy of
#: this when the block or key is absent (plan item 3(b)).
_DEFAULT_PORT_RANGE: Final[tuple[int, ...]] = (7000, 7999)

#: The pinned C520 remedy direction (plan block 4): the remedy must name
#: every place the device list could have come from — the tool's own
#: ``devices:`` entry, the ``defaults:`` block, or the tool's group.
_C520_LAYER_PHRASES: Final[tuple[str, ...]] = ("defaults", "group")

#: The pinned C523 remedy options (plan block 5): the remedy names BOTH
#: options — reduce ``workers``, or keep it and size the group's
#: ``max_resident`` accordingly.
_C523_REMEDY_KEYWORDS: Final[tuple[str, ...]] = ("workers", "max_resident")

#: The pinned ``expose_host_port: 0`` clause (plan block 6(b)): the
#: message names what 0 means to Docker ("pick one") and that tool-swap
#: does not support that spelling — write ``true`` to auto-allocate or an
#: explicit port.
_C531_ZERO_KEYWORDS: Final[tuple[str, ...]] = ("pick", "true")

#: The ``yaml_path`` each code must emit (plan block 7), per offending
#: tool key ``t1`` / colliding port.  Used by the location-contract test.
_PINNED_YAML_PATHS: Final[dict[str, str]] = {
    "TSWAP-C520": "tools.t1.devices.0",
    "TSWAP-C521": "tools.t1.devices.0",
    "TSWAP-C522": "tools.t1.devices",
    "TSWAP-C523": "tools.t1.workers",
    "TSWAP-C530": "tools",
    "TSWAP-C531": "tools.t1.expose_host_port",
    "TSWAP-C532": "backend.port_range",
}


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _tool(
    name: str,
    *,
    devices: object = None,
    workers: object = None,
    expose_host_port: object = None,
) -> ResolvedTool:
    """Build a minimal frozen ``ResolvedTool`` for behaviour 16.

    The three fields ride the resolved 47-key ``values`` mapping exactly
    as the resolver would place them (plan item 2(a)/(b)); the tests
    build the mapping directly, so a ``None`` argument means "no layer
    supplied it".

    Args:
        name: the tool name (used as both the ``tools`` dict key and the
            ``ResolvedTool.name`` in every fixture, so the two
            namespaces agree).
        devices: the ``devices`` value as authored (uncoerced).
        workers: the ``workers`` value as authored.
        expose_host_port: the ``expose_host_port`` value as authored
            (``bool | int | None``).

    Returns:
        A ``ResolvedTool`` with ``origins=OriginMap()`` and no
        diagnostics.
    """
    return ResolvedTool(
        name=name,
        values={
            "devices": devices,
            "workers": workers,
            "expose_host_port": expose_host_port,
        },
        origins=OriginMap(),
        diagnostics=[],
    )


def _config(
    tools: dict[str, ResolvedTool],
    line_for: Callable[[str], int | None] | None = None,
    path: Path | None = None,
    raw: dict[str, object] | None = None,
    gpu_count: int | None = None,
) -> ValidatedConfig:
    """Build a ``ValidatedConfig`` fake (no loader, no filesystem).

    The C52x/C53x rules read only ``tool.values``, ``config.raw``
    (through ``effective_port_range``), ``config.gpu_count`` and the
    location seam; the probe field stays at its default and is never
    consulted.

    Args:
        tools: name -> ``ResolvedTool`` (positional field).
        line_for: dotted YAML path -> 1-based line or ``None``; defaults
            to a ``None``-returning mapping.
        path: the config file path; defaults to ``Path("tools.yaml")``.
        raw: the raw root YAML mapping; defaults to ``{"tools": {}}``
            (no ``backend:`` block, so the schema default range applies).
        gpu_count: the injected GPU count (``None`` = unknown, the M1
            production default; C521 skips silently).

    Returns:
        The frozen ``ValidatedConfig``.
    """
    return ValidatedConfig(
        tools=tools,
        raw=raw if raw is not None else {"tools": {}},
        line_for=line_for if line_for is not None else (lambda _p: None),
        path=path if path is not None else Path("tools.yaml"),
        # ``gpu_count`` is the trailing, keyword-only, defaulted field the
        # GREEN step adds (plan item 1); naming it here is the same red
        # pattern as the missing rule constants above.
        gpu_count=gpu_count,  # type: ignore[call-arg]
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
    C52x/C53x rules it exercises (explicitly, like the behaviour-13/14/15
    files) and must not depend on — and must not leak — registration
    state.
    """
    unregister_all()
    try:
        yield
    finally:
        unregister_all()


# ---------------------------------------------------------------------------
# 1. The rule objects and the append order
# ---------------------------------------------------------------------------


def test_rule_objects_carry_expected_ids_and_severities() -> None:
    """Each rule instance carries its id, severity, and a remedy.

    Plan block 8: "``C520`` ERROR; ``C521`` WARNING; ``C522`` WARNING;
    ``C523`` WARNING; ``C530`` ERROR; ``C531`` ERROR; ``C532`` ERROR.
    Every ``remedy`` is non-empty."

    Arrangement: the seven rule objects imported from ``validate``.
    Action: read back ``id``, ``severity`` and ``remedy``.
    Assertion: ids are ``TSWAP-C520``…``TSWAP-C532`` in that order;
    ``C520``, ``C530``, ``C531`` and ``C532`` are ERROR, the three ``C52x``
    warnings are WARNING, and every remedy is a non-empty string.
    """
    rules = _ALL_C52X_C53X_RULES

    assert [rule.id for rule in rules] == list(_BEHAVIOUR_16_IDS)
    assert [rule.severity for rule in rules] == [
        Severity.ERROR,
        Severity.WARNING,
        Severity.WARNING,
        Severity.WARNING,
        Severity.ERROR,
        Severity.ERROR,
        Severity.ERROR,
    ]
    for rule in rules:
        assert isinstance(rule.remedy, str)
        assert rule.remedy.strip() != ""


def test_builtin_rules_append_the_behaviour_16_codes_in_code_order() -> None:
    """The seven rules are appended to ``BUILTIN_RULES`` after 15.

    Plan block 9: all seven are appended to ``BUILTIN_RULES`` in code
    order after behaviour 15's seven — 30 landed rules in total (6 + 4 +
    6 + 7 + 7) — and their *identity* is what
    ``register_builtin_rules()`` relies on for idempotency, so the tuple
    must hold the very module-level singletons, not equal stand-ins.

    The position is asserted **relative to the earlier blocks**, not
    tail-anchored or by total count (the index-anchored pattern of
    behaviours 13/14/15): a later behaviour may append more rules
    without breaking this pin.

    Arrangement: the ``BUILTIN_RULES`` tuple.
    Action: locate the first behaviour-16 id; check object identity per
    rule.
    Assertion: the first C520 id sits at index
    ``len(_BEHAVIOUR_12_IDS) + len(_BEHAVIOUR_13_IDS) +
    len(_BEHAVIOUR_14_IDS) + len(_BEHAVIOUR_15_IDS)`` (immediately after
    the seven C51x codes), the seven ids from there are a contiguous,
    in-code-order block, and each rule constant is an element of the
    tuple.
    """
    ids = [rule.id for rule in BUILTIN_RULES]

    first_c520 = ids.index(_BEHAVIOUR_16_IDS[0])
    assert first_c520 == (
        len(_BEHAVIOUR_12_IDS)
        + len(_BEHAVIOUR_13_IDS)
        + len(_BEHAVIOUR_14_IDS)
        + len(_BEHAVIOUR_15_IDS)
    )
    assert ids[first_c520 : first_c520 + len(_BEHAVIOUR_16_IDS)] == list(
        _BEHAVIOUR_16_IDS
    )
    for constant in _ALL_C52X_C53X_RULES:
        assert any(rule is constant for rule in BUILTIN_RULES)


# ---------------------------------------------------------------------------
# 2. effective_port_range (plan item 3)
# ---------------------------------------------------------------------------


def test_effective_port_range_returns_the_authored_value_unchanged() -> None:
    """An authored ``backend.port_range`` is returned as authored.

    Plan item 3(b): the value is returned **as authored** — deliberately
    not narrowed to ``list[int]`` — because judging its shape is C532's
    entire job (a malformed value must reach C532 verbatim, and a
    non-int entry must not be coerced away).

    Arrangement: a raw mapping whose ``backend`` block carries
    ``port_range: [8000, 8999]`` and one carrying the malformed
    ``[8000, "8999"]``.
    Action: call ``effective_port_range`` on both.
    Assertion: the returned value is exactly what was authored in both
    cases.
    """
    raw = {"backend": {"port_range": [8000, 8999]}}

    assert effective_port_range(raw) == [8000, 8999]

    raw_malformed = {"backend": {"port_range": [8000, "8999"]}}

    assert effective_port_range(raw_malformed) == [8000, "8999"]


def test_effective_port_range_falls_back_to_the_schema_default() -> None:
    """A missing block or key yields the schema default ``[7000, 7999]``.

    Plan item 3(b): when ``raw`` has no ``backend:`` block, or the block
    has no ``port_range`` key, the default is read **from the schema's
    own field default** (``BackendConfig.port_range`` —
    ``[7000, 7999]``, verified at
    ``src/tool_swap/config/schema.py``) so the helper cannot drift from
    the schema.

    Arrangement: raw mappings with (a) no ``backend`` key, (b) a
    non-dict ``backend``, and (c) a ``backend`` dict without
    ``port_range``.
    Action: call ``effective_port_range`` on each.
    Assertion: each returns the verified default ``[7000, 7999]``.
    """
    assert effective_port_range({}) == list(_DEFAULT_PORT_RANGE)
    assert effective_port_range({"tools": {}}) == list(_DEFAULT_PORT_RANGE)
    assert effective_port_range({"backend": "nope"}) == list(_DEFAULT_PORT_RANGE)
    assert effective_port_range({"backend": {}}) == list(_DEFAULT_PORT_RANGE)
    assert effective_port_range(
        {"backend": {"registry_prefix": "x"}}
    ) == list(_DEFAULT_PORT_RANGE)


def test_effective_port_range_returns_a_fresh_copy_not_an_alias() -> None:
    """The default answer is a copy; mutating it cannot corrupt the schema.

    Plan item 3(b): the default is **copied, not aliased**, so a rule
    can never mutate a Pydantic default (the ``port_range``
    mutable-default hazard behaviour 3 has a dedicated test for), and an
    authored block is returned without mutation exposure into the schema
    either.

    Arrangement: two successive calls with no ``backend:`` block.
    Action: mutate the first result.
    Assertion: the two results are distinct objects and the second is
    still the untouched default.
    """
    first = effective_port_range({})

    first.append(9999)

    second = effective_port_range({})

    assert first is not second
    assert second == list(_DEFAULT_PORT_RANGE)


def test_effective_port_range_does_not_mutate_raw() -> None:
    """The helper is pure: the ``raw`` mapping is left untouched.

    Plan item 3(b): "Pure, no mutation of ``raw``", and the authored
    value is returned **as authored** — the plan's reference form hands
    the authored list back by reference (only the *default* is copied,
    so the schema's field default can never be mutated).

    Arrangement: a raw mapping carrying an authored ``port_range``.
    Action: call the helper, then inspect ``raw`` again.
    Assertion: ``raw`` is byte-for-byte unchanged and the returned value
    IS the authored list object.
    """
    raw = {"backend": {"port_range": [8000, 8999]}}
    snapshot = {"backend": {"port_range": [8000, 8999]}}

    result = effective_port_range(raw)

    assert raw == snapshot
    assert result == [8000, 8999]
    # The helper did not replace the authored list object inside raw
    # (pure: no mutation, and the authored value is handed back by
    # reference, not by a fresh copy).
    assert raw["backend"]["port_range"] is result  # type: ignore[index]


# ---------------------------------------------------------------------------
# 3. TSWAP-C520 — negative or non-integer device index (plan item 4)
# ---------------------------------------------------------------------------


def test_c520_negative_index_is_an_error_naming_the_offending_entry() -> None:
    """``devices: [-1]`` → one C520 at ``tools.t1.devices.0``.

    Plan block 4: the rule fires per offending entry and the message
    names the tool, the offending entry (``repr``) and its position.

    Arrangement: one tool with ``devices=[-1]``; only C520 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C520`` ERROR at
    ``tools.t1.devices.0`` naming the tool, the entry and its position.
    """
    register(TSWAP_C520_RULE)
    cfg = _config(tools={"t1": _tool("t1", devices=[-1])})

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C520"}
    (d,) = by_code["TSWAP-C520"]
    assert d.severity is Severity.ERROR
    assert "t1" in d.message
    assert "-1" in d.message
    assert "0" in d.message
    assert d.location.yaml_path == "tools.t1.devices.0"


def test_c520_second_entry_offending_names_that_position() -> None:
    """``devices: [0, -2]`` → one C520 at ``tools.t1.devices.1``.

    Arrangement: one tool with ``devices=[0, -2]``; only C520 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C520`` located at index ``1`` naming
    the offending entry ``-2`` (the valid entry ``0`` is not reported).
    """
    register(TSWAP_C520_RULE)
    cfg = _config(tools={"t1": _tool("t1", devices=[0, -2])})

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C520"}
    (d,) = by_code["TSWAP-C520"]
    assert d.location.yaml_path == "tools.t1.devices.1"
    assert "-2" in d.message
    assert "1" in d.message


def test_c520_string_index_is_an_error_via_lax_coercion() -> None:
    """``devices: ["0"]`` → C520: the rule handles lax coercion.

    Plan block 4: Pydantic's lax mode coerces ``"0"`` → ``0`` and
    produces NO schema diagnostic, so the rule must check the entry
    itself; the message uses ``repr`` so ``"0"`` is visibly a string.

    Arrangement: one tool with ``devices=["0"]``; only C520 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C520`` at ``tools.t1.devices.0``
    naming the string entry (its ``repr``).
    """
    register(TSWAP_C520_RULE)
    cfg = _config(tools={"t1": _tool("t1", devices=["0"])})

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C520"}
    (d,) = by_code["TSWAP-C520"]
    assert d.location.yaml_path == "tools.t1.devices.0"
    assert "'0'" in d.message


def test_c520_float_index_is_an_error_alongside_the_schema_c105() -> None:
    """``devices: [1.5]`` → C520; a ``TSWAP-C105`` may coexist.

    Plan block 4 (overlap pinned honestly): ``devices: [1.5]`` is
    rejected by the schema's ``list[int]`` as ``TSWAP-C105`` **and**
    flagged by C520 — the two layers run independently and the
    double-report is accepted, not suppressed.  This test exercises the
    rule layer only (the rules never see the schema's findings), so the
    pin is that C520 fires on the float entry.

    Arrangement: one tool with ``devices=[1.5]``; only C520 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C520`` at ``tools.t1.devices.0``
    naming the entry.
    """
    register(TSWAP_C520_RULE)
    cfg = _config(tools={"t1": _tool("t1", devices=[1.5])})

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C520"}
    (d,) = by_code["TSWAP-C520"]
    assert d.location.yaml_path == "tools.t1.devices.0"
    assert "1.5" in d.message


def test_c520_bool_entry_is_an_error_before_the_int_test() -> None:
    """``devices: [True]`` → C520: ``bool`` is not a valid index.

    Plan block 4: ``bool`` is excluded by an explicit
    ``isinstance(value, bool)`` test **before** the ``int`` test —
    ``True`` is an ``int`` in Python, and ``devices: [true]`` is a
    mistake, not GPU 1.

    Arrangement: one tool with ``devices=[True]``; only C520 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C520`` at ``tools.t1.devices.0``.
    """
    register(TSWAP_C520_RULE)
    cfg = _config(tools={"t1": _tool("t1", devices=[True])})

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C520"}
    (d,) = by_code["TSWAP-C520"]
    assert d.location.yaml_path == "tools.t1.devices.0"
    assert "True" in d.message


def test_c520_valid_indices_produce_nothing() -> None:
    """``devices: [0, 1]`` → nothing.

    Arrangement: one tool with ``devices=[0, 1]``; only C520 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C520_RULE)
    cfg = _config(tools={"t1": _tool("t1", devices=[0, 1])})

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c520_absent_devices_produces_nothing() -> None:
    """No ``devices`` entry (``None``) → nothing.

    Arrangement: one tool with no ``devices`` key; only C520 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C520_RULE)
    cfg = _config(tools={"t1": _tool("t1")})

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c520_non_list_devices_is_skipped_silently() -> None:
    """``devices: "gpu"`` (not a list) → C520 skips; C104 owns it.

    Plan block 4: ``devices`` that is **not a list** is skipped silently
    by all of C520/C521/C522/C523 — ``TSWAP-C104`` owns it with a
    bespoke message, and re-reporting it per rule would bury that
    message.

    Arrangement: one tool with ``devices="gpu"``; only C520 registered.
    Action: run ``validate_config``.
    Assertion: an empty report (no C520, no crash).
    """
    register(TSWAP_C520_RULE)
    cfg = _config(tools={"t1": _tool("t1", devices="gpu")})

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c520_group_supplied_devices_yield_one_diagnostic_per_member() -> None:
    """A shared bad device list → one C520 per member tool.

    Plan block 4: group values land in each member's ``values``, so a
    ``groups.gpu0.devices: [-1]`` shared by three tools produces three
    C520s at three tool locations (the rule is per-tool by
    construction).  In tests the member picture is built directly: three
    tools whose ``values`` each carry the same offending list.  The
    remedy must be self-sufficient and name every layer the list could
    have come from (the tool's ``devices:``, the ``defaults:`` block, or
    the tool's group).

    Arrangement: three tools with ``devices=[-1]``; only C520
    registered.
    Action: run ``validate_config``.
    Assertion: exactly three ``TSWAP-C520`` at
    ``tools.t1.devices.0`` / ``tools.t2.devices.0`` /
    ``tools.t3.devices.0``, and each remedy names the possible layers
    (``defaults`` and ``group``).
    """
    register(TSWAP_C520_RULE)
    cfg = _config(
        tools={
            key: _tool(key, devices=[-1])
            for key in ("t1", "t2", "t3")
        }
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C520"}
    assert sorted(d.location.yaml_path for d in by_code["TSWAP-C520"]) == [
        "tools.t1.devices.0",
        "tools.t2.devices.0",
        "tools.t3.devices.0",
    ]
    for d in by_code["TSWAP-C520"]:
        for phrase in _C520_LAYER_PHRASES:
            assert phrase in d.remedy


# ---------------------------------------------------------------------------
# 4. TSWAP-C521 — device index exceeds visible GPUs (plan item 5)
# ---------------------------------------------------------------------------


def test_c521_index_at_or_above_count_is_a_warning_naming_both() -> None:
    """``gpu_count=2``, ``devices=[3]`` → WARNING naming index and count.

    Plan block 5: with an injected count the rule fires for every entry
    that is an ``int``, not a ``bool``, ``>= 0`` and ``>= gpu_count``;
    the message names the index, the count seen, and that the config may
    target another machine (§6 rule 7's own reason).

    Arrangement: one tool with ``devices=[3]``; ``gpu_count=2``; only
    C521 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C521`` WARNING at
    ``tools.t1.devices.0`` naming the index ``3`` and the count ``2``.
    """
    register(TSWAP_C521_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", devices=[3])},
        gpu_count=2,
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C521"}
    (d,) = by_code["TSWAP-C521"]
    assert d.severity is Severity.WARNING
    assert d.location.yaml_path == "tools.t1.devices.0"
    assert "3" in d.message
    assert "2" in d.message


def test_c521_zero_visible_gpus_warns_for_any_index() -> None:
    """``gpu_count=0`` (legitimate, NOT unknown) + ``devices=[0]`` → WARNING.

    Plan block 5: ``gpu_count: 0`` is a legitimate injected value
    meaning "this host has no GPUs" and warns for every device index —
    it is not conflated with ``None``.  Index ``0`` is ``>= 0`` visible
    GPUs, so it fires (0-visible + any index fires).

    Arrangement: one tool with ``devices=[0]``; ``gpu_count=0``; only
    C521 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C521`` WARNING at
    ``tools.t1.devices.0``.
    """
    register(TSWAP_C521_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", devices=[0])},
        gpu_count=0,
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C521"}
    (d,) = by_code["TSWAP-C521"]
    assert d.severity is Severity.WARNING
    assert d.location.yaml_path == "tools.t1.devices.0"


def test_c521_unknown_gpu_count_is_skipped_silently() -> None:
    """``gpu_count=None`` → the rule is skipped entirely (M1 default).

    Plan item 1 / block 5: ``None`` means "unknown" and the rule is
    skipped **entirely and silently** — no diagnostic at all.  This is
    the M1 production default: nothing in M1 populates ``gpu_count``, so
    C521 never fires in a real ``tswap validate`` run.

    Arrangement: one tool with ``devices=[3]``; ``gpu_count=None``
    (the field default); only C521 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C521_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", devices=[3])},
        gpu_count=None,
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c521_in_range_indices_produce_nothing() -> None:
    """``gpu_count=2``, ``devices=[0, 1]`` → nothing (in range).

    Arrangement: one tool with ``devices=[0, 1]``; ``gpu_count=2``; only
    C521 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C521_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", devices=[0, 1])},
        gpu_count=2,
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c521_negative_indices_do_not_reach_c521() -> None:
    """``gpu_count=2``, ``devices=[-1]`` → C520 only, no C521.

    Plan block 5: negatives belong to ``C520`` — one mistake, one
    diagnostic.  C521 fires only for entries ``>= 0``.

    Arrangement: one tool with ``devices=[-1]``; ``gpu_count=2``; BOTH
    C520 and C521 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C520`` and no ``TSWAP-C521``.
    """
    register(TSWAP_C520_RULE)
    register(TSWAP_C521_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", devices=[-1])},
        gpu_count=2,
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C520"}
    (d,) = by_code["TSWAP-C520"]
    assert d.location.yaml_path == "tools.t1.devices.0"


def test_c521_non_list_devices_is_skipped_like_c520() -> None:
    """``devices`` that is not a list → C521 skips silently.

    Plan block 4: the skip applies to C520/C521/C522/C523 alike
    (``TSWAP-C104`` owns it).

    Arrangement: one tool with ``devices=3`` (the R8 flaw);
    ``gpu_count=2``; only C521 registered.
    Action: run ``validate_config``.
    Assertion: an empty report (no crash, no diagnostic).
    """
    register(TSWAP_C521_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", devices=3)},
        gpu_count=2,
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# 5. TSWAP-C522 — duplicate index within one tool's devices (plan item 5)
# ---------------------------------------------------------------------------


def test_c522_duplicate_index_is_one_warning_at_the_list() -> None:
    """``devices: [1, 1]`` → one WARNING at ``tools.t1.devices``.

    Plan block 5: **one diagnostic per tool**, naming every duplicated
    index, located at the **list** rather than at an entry — the
    duplication is a property of the list, and picking "the second
    occurrence" would be arbitrary.

    Arrangement: one tool with ``devices=[1, 1]``; only C522 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C522`` WARNING at
    ``tools.t1.devices`` (not ``tools.t1.devices.0``/``.1``) naming the
    duplicated index ``1``.
    """
    register(TSWAP_C522_RULE)
    cfg = _config(tools={"t1": _tool("t1", devices=[1, 1])})

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C522"}
    (d,) = by_code["TSWAP-C522"]
    assert d.severity is Severity.WARNING
    assert d.location.yaml_path == "tools.t1.devices"
    assert "1" in d.message


def test_c522_distinct_indices_produce_nothing() -> None:
    """``devices: [0, 1, 2]`` → nothing.

    Arrangement: one tool with ``devices=[0, 1, 2]``; only C522
    registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C522_RULE)
    cfg = _config(tools={"t1": _tool("t1", devices=[0, 1, 2])})

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c522_non_list_devices_is_skipped() -> None:
    """``devices`` that is not a list → C522 skips silently.

    Plan block 4: the skip applies to C520/C521/C522/C523 alike.

    Arrangement: one tool with ``devices="all"``; only C522 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C522_RULE)
    cfg = _config(tools={"t1": _tool("t1", devices="all")})

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# 6. TSWAP-C523 — workers > 1 AND devices non-empty (plan item 5)
# ---------------------------------------------------------------------------


def test_c523_workers_above_one_with_devices_is_a_warning() -> None:
    """``workers=4``, ``devices=[0]`` → WARNING with the pinned message.

    Plan block 5: the message must state the mechanism — *VRAM
    multiplies by the worker count, invisibly to the scheduler* — and
    the remedy names BOTH options: reduce ``workers``, **or** keep it
    and size the group's ``max_resident`` accordingly.  A remedy
    offering only "reduce workers" would be telling a user their
    deliberate choice is wrong.

    Arrangement: one tool with ``workers=4``, ``devices=[0]``; only C523
    registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C523`` WARNING at
    ``tools.t1.workers`` whose message carries the VRAM/multiply
    mechanism and whose remedy names both options (``workers`` and
    ``max_resident``).
    """
    register(TSWAP_C523_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", workers=4, devices=[0])},
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C523"}
    (d,) = by_code["TSWAP-C523"]
    assert d.severity is Severity.WARNING
    assert d.location.yaml_path == "tools.t1.workers"
    assert "VRAM" in d.message
    assert "multiply" in d.message
    for keyword in _C523_REMEDY_KEYWORDS:
        assert keyword in d.remedy


def test_c523_workers_above_one_with_empty_devices_is_nothing() -> None:
    """``workers=4``, ``devices=[]`` → nothing (the pinned CPU case).

    Plan block 5: ``devices: []`` with ``workers: 4`` → **nothing**,
    explicitly pinned and explicitly tested; that is the CPU case, where
    multiple workers are the intended way to use more cores.

    Arrangement: one tool with ``workers=4``, ``devices=[]``; only C523
    registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C523_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", workers=4, devices=[])},
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c523_workers_above_one_with_absent_devices_is_nothing() -> None:
    """``workers=4``, no ``devices`` key → nothing.

    Arrangement: one tool with ``workers=4`` and no ``devices``; only
    C523 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C523_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", workers=4)},
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c523_workers_equal_to_one_is_nothing() -> None:
    """``workers=1``, ``devices=[0]`` → nothing (``workers > 1`` is the
    condition).

    Arrangement: one tool with ``workers=1``, ``devices=[0]``; only C523
    registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C523_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", workers=1, devices=[0])},
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c523_absent_workers_is_nothing() -> None:
    """No ``workers`` key, ``devices=[0]`` → nothing.

    Arrangement: one tool with no ``workers``, ``devices=[0]``; only
    C523 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C523_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", devices=[0])},
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# 7. TSWAP-C530 — two tools sharing an explicit host port (plan item 6(d))
# ---------------------------------------------------------------------------


def test_c530_shared_explicit_port_is_one_error_naming_both_tools_and_port() -> (
    None
):
    """Two tools both at ``expose_host_port=8080`` → one C530 at ``tools``.

    Plan block 6(d): collect ``(tool key, port)`` for every tool whose
    ``expose_host_port`` is an ``int`` and not a ``bool``; emit **one
    diagnostic per colliding port**, naming the port and **every** tool
    claiming it (not one per pair, and not one per tool).  Located at
    ``tools`` — the collision belongs to no single tool (the ``_C211Rule``
    duplicate-name precedent).

    Arrangement: two tools both with ``expose_host_port=8080``; only C530
    registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C530`` ERROR at ``tools`` whose
    message names BOTH tools and the port.
    """
    register(TSWAP_C530_RULE)
    cfg = _config(
        tools={
            "t1": _tool("t1", expose_host_port=8080),
            "t2": _tool("t2", expose_host_port=8080),
        },
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C530"}
    (d,) = by_code["TSWAP-C530"]
    assert d.severity is Severity.ERROR
    assert d.location.yaml_path == "tools"
    assert "t1" in d.message
    assert "t2" in d.message
    assert "8080" in d.message


def test_c530_different_ports_produce_nothing() -> None:
    """Two tools with different explicit ports → nothing.

    Arrangement: ``t1`` at 8080, ``t2`` at 8081; only C530 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C530_RULE)
    cfg = _config(
        tools={
            "t1": _tool("t1", expose_host_port=8080),
            "t2": _tool("t2", expose_host_port=8081),
        },
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c530_auto_allocate_bools_participate_in_neither_check() -> None:
    """Two tools with ``expose_host_port=True`` → NOTHING at all.

    Plan block 6(a): ``true`` participates in **neither** C530 **nor**
    C531 — nothing is allocated at validate time (D21: normal operation
    publishes nothing and allocates nothing).  The ``isinstance(value,
    bool)``-before-``int`` pin: a naive ``isinstance(value, int)`` would
    treat ``true`` as **port 1** and collide the two tools.

    Arrangement: two tools both with ``expose_host_port=True``; C530 AND
    C531 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C530_RULE)
    register(TSWAP_C531_RULE)
    cfg = _config(
        tools={
            "t1": _tool("t1", expose_host_port=True),
            "t2": _tool("t2", expose_host_port=True),
        },
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c530_false_produces_nothing() -> None:
    """``expose_host_port=False`` (publish nothing) → nothing.

    Plan block 6(a) table row 1: the default publishes nothing and
    trips neither check.

    Arrangement: two tools both with ``expose_host_port=False``; C530
    and C531 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C530_RULE)
    register(TSWAP_C531_RULE)
    cfg = _config(
        tools={
            "t1": _tool("t1", expose_host_port=False),
            "t2": _tool("t2", expose_host_port=False),
        },
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c530_two_tools_both_at_zero_is_a_collision_and_two_c531s() -> None:
    """Two tools both at ``expose_host_port=0`` → C530 AND C531×2.

    Two-0s question, pinned from the plan: item 6(a) defines C530's
    operand set as "every tool whose ``expose_host_port`` is an ``int``
    and not a ``bool``" with no 0-exemption, and item 6(d) says "one
    diagnostic per colliding port, naming the port and every tool
    claiming it" — so the two 0s collide for C530.  ``0`` is an
    unconditionally-out-of-range port (item 6(b)), so each tool also
    gets its own C531; C530 and C531 are independent checks (item 6(d):
    "neither suppresses the other").

    Arrangement: two tools both with ``expose_host_port=0``; C530 and
    C531 registered; default (well-formed) range.
    Action: run ``validate_config``.
    Assertion: exactly ONE ``TSWAP-C530`` at ``tools`` naming port 0 and
    both tools, and exactly TWO ``TSWAP-C531`` (one per tool at
    ``tools.t1.expose_host_port`` / ``tools.t2.expose_host_port``).
    """
    register(TSWAP_C530_RULE)
    register(TSWAP_C531_RULE)
    cfg = _config(
        tools={
            "t1": _tool("t1", expose_host_port=0),
            "t2": _tool("t2", expose_host_port=0),
        },
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C530", "TSWAP-C531"}
    (c530,) = by_code["TSWAP-C530"]
    assert c530.location.yaml_path == "tools"
    assert "0" in c530.message
    assert "t1" in c530.message
    assert "t2" in c530.message
    assert sorted(d.location.yaml_path for d in by_code["TSWAP-C531"]) == [
        "tools.t1.expose_host_port",
        "tools.t2.expose_host_port",
    ]


# ---------------------------------------------------------------------------
# 8. TSWAP-C531 — explicit port outside backend.port_range (plan item 6(b))
# ---------------------------------------------------------------------------

_RANGED_RAW: Final[dict[str, object]] = {
    "backend": {"port_range": [8000, 8999]}
}


@pytest.mark.parametrize(
    ("port", "yaml_path"),
    [(9000, "tools.t1.expose_host_port"), (7999, "tools.t1.expose_host_port")],
)
def test_c531_port_outside_the_range_is_an_error_naming_port_and_range(
    port: int,
    yaml_path: str,
) -> None:
    """A port above (9000) or below (7999) ``[8000, 8999]`` → error.

    Plan block 6(b): fires when the value is an ``int`` (not a ``bool``)
    and falls outside the effective range; the message names **the port
    and the range, both**.

    Arrangement: one tool at the parametrized port;
    ``backend.port_range = [8000, 8999]`` in ``raw``; C531 and C532
    registered (the range is well-formed, so C532 must stay out).
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C531`` ERROR at the parametrized path
    whose message names the port and both range endpoints.
    """
    register(TSWAP_C531_RULE)
    register(TSWAP_C532_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", expose_host_port=port)},
        raw=_RANGED_RAW,
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C531"}
    (d,) = by_code["TSWAP-C531"]
    assert d.severity is Severity.ERROR
    assert d.location.yaml_path == yaml_path
    assert str(port) in d.message
    assert "8000" in d.message
    assert "8999" in d.message


@pytest.mark.parametrize("port", [8000, 8999])
def test_c531_range_boundaries_are_inclusive(port: int) -> None:
    """Ports 8000 and 8999 are INSIDE ``[8000, 8999]`` → nothing.

    Plan block 6(b) (inclusivity pinned): the range is ``[low, high]``
    with both endpoints legal.

    Arrangement: one tool at the parametrized boundary port;
    ``backend.port_range = [8000, 8999]``; C531 and C532 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C531_RULE)
    register(TSWAP_C532_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", expose_host_port=port)},
        raw=_RANGED_RAW,
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c531_auto_allocate_true_is_skipped() -> None:
    """``expose_host_port=True`` → C531 skips (auto; participates in
    neither check).

    Plan block 6(a): ``true`` means "auto-allocate from
    ``backend.port_range``" and is never a port to range-check.

    Arrangement: one tool with ``expose_host_port=True``;
    ``backend.port_range = [8000, 8999]``; only C531 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C531_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", expose_host_port=True)},
        raw=_RANGED_RAW,
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c531_port_zero_is_unconditional_with_the_dedicated_clause() -> None:
    """``expose_host_port=0`` → C531 UNCONDITIONALLY, with the 0 clause.

    Plan block 6(b): the objection is not arithmetic — ``0`` fires even
    if an authored ``port_range`` somehow contained 0 (it is not).  The
    message carries a dedicated clause: ``0`` tells Docker "pick any
    free port" and tool-swap does not support that spelling — write
    ``true`` to auto-allocate, or an explicit port.

    Arrangement: one tool at ``expose_host_port=0`` with the range
    ``[0, 65535]`` (which contains 0 — proving the clause is not
    arithmetic); only C531 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C531`` at
    ``tools.t1.expose_host_port`` whose message carries the
    "pick-one" / "write true" direction.
    """
    register(TSWAP_C531_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", expose_host_port=0)},
        raw={"backend": {"port_range": [0, 65535]}},
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C531"}
    (d,) = by_code["TSWAP-C531"]
    assert d.severity is Severity.ERROR
    assert d.location.yaml_path == "tools.t1.expose_host_port"
    for keyword in _C531_ZERO_KEYWORDS:
        assert keyword in d.message


def test_c531_without_a_backend_block_the_schema_default_range_applies() -> (
    None
):
    """No ``backend:`` block → the DEFAULT ``[7000, 7999]`` range applies.

    Plan item 3(b): ``effective_port_range`` returns a copy of the
    schema's own ``BackendConfig.port_range`` default
    (``[7000, 7999]``, verified at ``src/tool_swap/config/schema.py``)
    when the block is absent — so a port outside that default is an
    error even though the author wrote no ``backend:`` at all.

    Arrangement: one tool at port 8000 (inside the authored-range test
    above, but OUTSIDE the default); NO ``backend:`` block in ``raw``;
    C531 and C532 registered (the default range is well-formed, so C532
    must stay out).
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C531`` whose message names the port
    and the default range endpoints.
    """
    register(TSWAP_C531_RULE)
    register(TSWAP_C532_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", expose_host_port=8000)},
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C531"}
    (d,) = by_code["TSWAP-C531"]
    assert d.location.yaml_path == "tools.t1.expose_host_port"
    assert "8000" in d.message
    assert "7000" in d.message
    assert "7999" in d.message


def test_c532_suppresses_c531_for_the_run() -> None:
    """A malformed range + an out-of-range port → EXACTLY the C532.

    Plan block 6(c): ``C532`` suppresses ``C531`` for the whole run — a
    malformed range cannot judge any port, and emitting "port X is
    outside ``[9000, 8000]``" alongside "the range is inverted" is two
    diagnostics for one mistake (the ``C512``-suppresses-``C513``
    pattern from behaviour 15).

    Arrangement: one tool at port 1234 (outside any reading of the
    inverted range) and ``backend.port_range = [9000, 8000]`` (inverted);
    C531 and C532 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C532`` at ``backend.port_range`` and
    NO ``TSWAP-C531``.
    """
    register(TSWAP_C531_RULE)
    register(TSWAP_C532_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", expose_host_port=1234)},
        raw={"backend": {"port_range": [9000, 8000]}},
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C532"}
    (d,) = by_code["TSWAP-C532"]
    assert d.location.yaml_path == "backend.port_range"


# ---------------------------------------------------------------------------
# 9. TSWAP-C532 — port_range inverted or malformed (plan item 6(c))
# ---------------------------------------------------------------------------


def test_c532_inverted_range_is_an_error_naming_both_values() -> None:
    """``port_range: [9000, 8000]`` → error naming both values.

    Plan block 6(c) table row: ``low > high`` (inverted) → yes — naming
    both values.

    Arrangement: ``raw`` with ``backend.port_range = [9000, 8000]``; one
    tool (no port of its own, so C531 has nothing to fire on); only C532
    registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C532`` ERROR at ``backend.port_range``
    naming both values.
    """
    register(TSWAP_C532_RULE)
    cfg = _config(
        tools={"t1": _tool("t1")},
        raw={"backend": {"port_range": [9000, 8000]}},
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C532"}
    (d,) = by_code["TSWAP-C532"]
    assert d.severity is Severity.ERROR
    assert d.location.yaml_path == "backend.port_range"
    assert "9000" in d.message
    assert "8000" in d.message


@pytest.mark.parametrize(
    "bad_range",
    [[], [8000], [8000, 8999, 9999]],
    ids=["empty", "length-1", "length-3"],
)
def test_c532_wrong_length_is_an_error(bad_range: list[int]) -> None:
    """``port_range`` of length ≠ 2 → error naming the length found.

    Plan block 6(c) table row: "length ≠ 2 (``[]``, ``[7000]``,
    ``[7000, 7999, 8000]``) → yes — naming the length found."  The
    schema's ``list[int]`` does not check the length, so C532 owns it.
    One diagnostic per problem: a wrong length is the single problem
    with the block here.

    Arrangement: ``raw`` with the parametrized malformed list; only C532
    registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C532`` at ``backend.port_range``
    naming the length found.
    """
    register(TSWAP_C532_RULE)
    cfg = _config(
        tools={"t1": _tool("t1")},
        raw={"backend": {"port_range": list(bad_range)}},
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C532"}
    (d,) = by_code["TSWAP-C532"]
    assert d.location.yaml_path == "backend.port_range"
    assert str(len(bad_range)) in d.message


def test_c532_non_int_entry_is_an_error() -> None:
    """``port_range: [8000, "8999"]`` → error (a non-int entry).

    Plan block 6(c) table row: "a non-``int`` (or ``bool``) entry that
    survived coercion → yes."  (Pydantic's lax mode coerces ``"8999"``
    → ``8999`` in the schema layer, but ``values``/``raw`` carry the
    value as authored; the helper returns it unchanged — plan item
    3(b) — so the rule must judge the entry itself.)

    Arrangement: ``raw`` with ``port_range = [8000, "8999"]``; only C532
    registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C532`` at ``backend.port_range``.
    """
    register(TSWAP_C532_RULE)
    cfg = _config(
        tools={"t1": _tool("t1")},
        raw={"backend": {"port_range": [8000, "8999"]}},
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C532"}
    (d,) = by_code["TSWAP-C532"]
    assert d.location.yaml_path == "backend.port_range"


def test_c532_bool_entry_is_an_error() -> None:
    """``port_range: [8000, True]`` → error (bool is not an int here).

    Plan block 6(c) table row names ``bool`` explicitly, mirroring the
    bool-before-int pin of C520.

    Arrangement: ``raw`` with ``port_range = [8000, True]``; only C532
    registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C532`` at ``backend.port_range``.
    """
    register(TSWAP_C532_RULE)
    cfg = _config(
        tools={"t1": _tool("t1")},
        raw={"backend": {"port_range": [8000, True]}},
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C532"}
    (d,) = by_code["TSWAP-C532"]
    assert d.location.yaml_path == "backend.port_range"


@pytest.mark.parametrize(
    "bad_range",
    [[0, 100], [100, 70000]],
    ids=["endpoint-below-1", "endpoint-above-65535"],
)
def test_c532_endpoint_outside_1_to_65535_is_an_error(
    bad_range: list[int],
) -> None:
    """An endpoint outside ``1..65535`` → error (not a port number).

    Plan block 6(c) table row: "an endpoint outside ``1..65535`` → yes —
    not a port number."

    Arrangement: ``raw`` with the parametrized two-int range; only C532
    registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C532`` at ``backend.port_range``.
    """
    register(TSWAP_C532_RULE)
    cfg = _config(
        tools={"t1": _tool("t1")},
        raw={"backend": {"port_range": list(bad_range)}},
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C532"}
    (d,) = by_code["TSWAP-C532"]
    assert d.location.yaml_path == "backend.port_range"


def test_c532_one_port_range_is_legal() -> None:
    """``port_range: [8000, 8000]`` (``low == high``) → LEGAL, no error.

    Plan block 6(c) table row: "``low == high`` → **no** — a one-port
    range is tight but legitimate."

    Arrangement: ``raw`` with ``port_range = [8000, 8000]`` and one tool
    at port 8000 (which must then be inside the range, so C531 also stays
    out); C531 and C532 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C531_RULE)
    register(TSWAP_C532_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", expose_host_port=8000)},
        raw={"backend": {"port_range": [8000, 8000]}},
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


@pytest.mark.parametrize(
    "bad_range",
    ["7000-7999", 8000],
    ids=["string", "single-int"],
)
def test_c532_non_list_range_is_skipped_silently(bad_range: object) -> None:
    """A non-list ``port_range`` → C532 skips; the schema's C105 owns it.

    Plan block 6(c) table row: "not a list at all → **no** — skipped
    silently; the schema's ``TSWAP-C105`` owns it" (no spelling other
    than the two-element list is accepted, and none is parsed).

    Arrangement: ``raw`` with the parametrized non-list value; only C532
    registered.
    Action: run ``validate_config``.
    Assertion: an empty report (no C532, no crash).
    """
    register(TSWAP_C532_RULE)
    cfg = _config(
        tools={"t1": _tool("t1")},
        raw={"backend": {"port_range": bad_range}},
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c532_no_backend_block_produces_nothing() -> None:
    """No ``backend:`` block / no ``port_range`` → nothing.

    The default is well-formed by construction (``[7000, 7999]``), so
    the rule stays silent when the author wrote nothing.

    Arrangement: ``raw`` without a ``backend:`` block (and,
    parametrized-style, with an empty ``backend:`` block); only C532
    registered.
    Action: run ``validate_config`` on both.
    Assertion: empty reports in both cases.
    """
    register(TSWAP_C532_RULE)
    cfg_no_block = _config(tools={"t1": _tool("t1")})
    cfg_empty_block = _config(
        tools={"t1": _tool("t1")},
        raw={"backend": {}},
    )

    assert validate_config(cfg_no_block).diagnostics == ()
    assert validate_config(cfg_empty_block).diagnostics == ()


# ---------------------------------------------------------------------------
# 10. Cross-rule pins
# ---------------------------------------------------------------------------


def test_single_clean_tool_yields_no_c5xx_at_all() -> None:
    """A single clean tool trips no C5xx (only-own-codes pin).

    One tool, ``devices=[0]``, ``workers=1``, ``expose_host_port=None``,
    ``gpu_count=None``, no ``backend:`` block — every C52x/C53x
    condition is false, so ALL SEVEN rules together must stay silent.

    Arrangement: exactly that tool; ALL seven C52x/C53x rules
    registered; ``gpu_count=None`` (the M1 production default).
    Action: run ``validate_config``.
    Assertion: no ``TSWAP-C52x``/``TSWAP-C53x`` code (and no ``TSWAP-C999``)
    appears in the report.
    """
    for rule in _ALL_C52X_C53X_RULES:
        register(rule)
    cfg = _config(
        tools={
            "t1": _tool("t1", devices=[0], workers=1, expose_host_port=None)
        },
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert not any(code.startswith("TSWAP-C5") for code in by_code)
    assert "TSWAP-C999" not in by_code


def test_multiple_problems_in_one_report_full_set() -> None:
    """Two bad tools yield the FULL expected set in one report.

    Multiple-problems-in-one-report pin: ``t1`` carries
    ``devices=[3]``, ``workers=4``, ``expose_host_port=9000``; ``t2``
    carries ``devices=[3]``, ``expose_host_port=9000``;
    ``gpu_count=2`` and the DEFAULT (well-formed) range apply.  The
    expected set:

    - ``TSWAP-C521`` ×2 — both tools' index 3 exceeds 2 visible GPUs
      (``tools.t1.devices.0`` and ``tools.t2.devices.0``);
    - ``TSWAP-C523`` ×1 — t1 only (``workers=4`` with non-empty
      ``devices``); t2 has no ``workers`` entry;
    - ``TSWAP-C530`` ×1 — port 9000 shared by t1 and t2, at ``tools``;
    - ``TSWAP-C531`` ×2 — 9000 is outside the default ``[7000, 7999]``
      for EACH tool; C530 and C531 are independent checks (plan item
      6(d): "neither suppresses the other"), so both fire for the same
      port.

    No C520 (all indices are valid ints ≥ 0), no C522 (no duplicates),
    no C532 (the default range is well-formed).

    Arrangement: the two tools; ALL seven C52x/C53x rules registered;
    ``gpu_count=2``; default range.
    Action: run ``validate_config``.
    Assertion: exactly the pinned counts per code and the pinned
    locations.
    """
    for rule in _ALL_C52X_C53X_RULES:
        register(rule)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                devices=[3],
                workers=4,
                expose_host_port=9000,
            ),
            "t2": _tool("t2", devices=[3], expose_host_port=9000),
        },
        gpu_count=2,
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {
        "TSWAP-C521",
        "TSWAP-C523",
        "TSWAP-C530",
        "TSWAP-C531",
    }
    assert sorted(d.location.yaml_path for d in by_code["TSWAP-C521"]) == [
        "tools.t1.devices.0",
        "tools.t2.devices.0",
    ]
    (c523,) = by_code["TSWAP-C523"]
    assert c523.location.yaml_path == "tools.t1.workers"
    (c530,) = by_code["TSWAP-C530"]
    assert c530.location.yaml_path == "tools"
    assert sorted(d.location.yaml_path for d in by_code["TSWAP-C531"]) == [
        "tools.t1.expose_host_port",
        "tools.t2.expose_host_port",
    ]
    assert len(report.diagnostics) == 6


@pytest.mark.parametrize(
    ("rule", "tools", "raw", "yaml_path"),
    [
        (
            TSWAP_C520_RULE,
            {"t1": _tool("t1", devices=[-1])},
            None,
            "tools.t1.devices.0",
        ),
        (
            TSWAP_C521_RULE,
            {"t1": _tool("t1", devices=[3])},
            None,
            "tools.t1.devices.0",
        ),
        (
            TSWAP_C522_RULE,
            {"t1": _tool("t1", devices=[1, 1])},
            None,
            "tools.t1.devices",
        ),
        (
            TSWAP_C523_RULE,
            {"t1": _tool("t1", workers=4, devices=[0])},
            None,
            "tools.t1.workers",
        ),
        (
            TSWAP_C530_RULE,
            {
                "t1": _tool("t1", expose_host_port=8080),
                "t2": _tool("t2", expose_host_port=8080),
            },
            None,
            "tools",
        ),
        (
            TSWAP_C531_RULE,
            {"t1": _tool("t1", expose_host_port=9000)},
            _RANGED_RAW,
            "tools.t1.expose_host_port",
        ),
        (
            TSWAP_C532_RULE,
            {"t1": _tool("t1")},
            {"backend": {"port_range": [9000, 8000]}},
            "backend.port_range",
        ),
    ],
)
@pytest.mark.parametrize("line", [42, None])
def test_location_contract_per_code(
    rule: Rule,
    tools: dict[str, ResolvedTool],
    raw: dict[str, object] | None,
    yaml_path: str,
    line: int | None,
) -> None:
    """Every C52x/C53x location consults ``line_for`` and ``config.path``.

    Plan block 7: ``Location(file=str(config.path), yaml_path=<pinned>,
    line=config.line_for(<the same string>))`` — the file is never
    hardcoded and ``line=None`` is a legal outcome, so the test asserts
    the RELATION ``location.line == config.line_for(location.yaml_path)``,
    never a hardcoded line number; both a fixed-int ``line_for`` and a
    ``None``-returning one are pinned.  ``C521`` needs the injected
    ``gpu_count`` (here 2, so index 3 fires); the ``<i>`` indices are
    0-based and dotted-numeric.

    Arrangement: one offending scenario per code, a non-default path,
    and a ``line_for`` returning the parametrized value for any dotted
    path.
    Action: run only the parametrized rule.
    Assertion: exactly one diagnostic; its file is ``str(config.path)``,
    its yaml_path is the pinned path, and its line equals
    ``config.line_for(yaml_path)``.
    """
    register(rule)
    cfg = _config(
        tools=tools,
        raw=raw,
        line_for=(lambda _p, _line=line: _line),
        path=Path("my-config.yaml"),
        gpu_count=2 if rule is TSWAP_C521_RULE else None,
    )

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert d.location.file == "my-config.yaml"
    assert d.location.yaml_path == yaml_path
    assert d.location.line == cfg.line_for(d.location.yaml_path)

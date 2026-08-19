"""Tests for M1 behaviour 18 — contradictions (§6 rule 11, D9).

See ``plans/m1-configuration.md`` behaviour 18 (lines 1284-1293) and its
"Confirmed contract details (2026-08-19)" block (items 1-12, lines
1295-1548).  This file is the executable form of that contract: the four
rule constants (``TSWAP_C600_RULE`` … ``TSWAP_C603_RULE``) do not exist
yet in ``src/tool_swap/config/validate.py`` (behaviour 17 shipped the
C54x rules and the 34-rule ``BUILTIN_RULES`` only).  This module
therefore fails collection with a single clean ``ImportError`` naming
exactly one missing name:

    ImportError: cannot import name 'TSWAP_C600_RULE'
        from 'tool_swap.config.validate'

(``TSWAP_C600_RULE`` is the first missing name in the import list; Python
reports the first one it fails on.)  Every test body below pins a
concrete behaviour the GREEN step must satisfy, so the assertions — not
just the import — are the contract.

Pinned public API (the names the GREEN step must add):

- ``TSWAP_C600_RULE`` … ``TSWAP_C603_RULE`` — C600 ERROR, C601 WARNING,
  C602 ERROR, C603 ERROR; non-empty remedies; appended to
  ``BUILTIN_RULES`` in code order after behaviour 17's four (38 total).
- One shared total origin-phrase helper inside the rules: the accessor
  is ``tool.origins.winning(field)``, and the pinned phrases a message
  must contain are: ``INLINE`` → ``set inline``; ``TOOL_YAML`` →
  ``set in the tool's tool.yaml``; ``DEFAULTS`` (non-group source) →
  ``set in the defaults: block``; ``DEFAULTS`` (source
  ``groups.<name>.<field>``) → ``set in group '<name>'``; ``BUILT_IN``
  → ``the built-in default``; unrecorded (``KeyError``) →
  ``origin unrecorded``.  ``Origin.render()`` is NOT the prose.

The rules read ONLY ``tool.values[<key>]`` and ``tool.origins`` (plus
``config.path`` / ``config.line_for`` for the location).  In this file
the ``ResolvedTool`` fakes are built directly with the 47-key
``values`` mapping and a REAL, origin-recording ``OriginMap`` (built
from the genuine ``Origin`` / ``OriginLevel`` types in
``src/tool_swap/config/origin.py``), so the origin citation is
exercised rather than stubbed.

The ``batching.enabled`` resolution (item 6(b)) is a RESOLVER
behaviour, tested at the resolver level by calling ``resolve_tool``
directly — no C6xx name is imported by those tests, so in the red
window they fail on the VALUE assertion (``max_batch_size`` is 8, not
1), not on the import.

Location contract: ``Location(file=str(config.path),
yaml_path=<pinned>, line=config.line_for(<the same string>))``;
``C600``/``C601`` locate at ``tools.<key>.keep_warm``, ``C602`` at
``tools.<key>.max_concurrent``, ``C603`` at ``tools.<key>.<offending
field>``.  Pinned relationally with a fixed-int ``line_for`` AND a
``None``-returning ``line_for``.

Conventions mirror ``tests/unit/config/test_validate_mounts.py``:
pytest, AAA, snake_case, Google docstrings, ``from __future__ import
annotations``, an autouse fixture calling ``unregister_all()`` before
AND after every test (the registry is shared module state), the C6xx
rules registered explicitly per test.  No ``importlib.reload``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest
from tool_swap.config.defaults import BUILT_IN_DEFAULTS
from tool_swap.config.errors import ConfigReport, Diagnostic, Severity
from tool_swap.config.origin import Origin, OriginLevel, OriginMap
from tool_swap.config.resolver import ResolvedTool, resolve_tool
from tool_swap.config.validate import (  # noqa: E501  (names absent in RED step)
    TSWAP_C600_RULE,
    TSWAP_C601_RULE,
    TSWAP_C602_RULE,
    TSWAP_C603_RULE,
    BUILTIN_RULES,
    Rule,
    ValidatedConfig,
    register,
    unregister_all,
    validate_config,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The four behaviour-12 rule ids (§6 rules 2 and 3), in code order
#: (mirrors ``_BEHAVIOUR_12_IDS`` in ``test_validate_names_groups.py``).
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

#: The seven behaviour-16 rule ids (§6 rules 4c, 7 and 8), in code order
#: (mirrors ``_BEHAVIOUR_16_IDS`` in ``test_validate_resources.py``).
_BEHAVIOUR_16_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C520",
    "TSWAP-C521",
    "TSWAP-C522",
    "TSWAP-C523",
    "TSWAP-C530",
    "TSWAP-C531",
    "TSWAP-C532",
)

#: The four behaviour-17 rule ids (§6 rule 9), in code order (mirrors
#: ``_BEHAVIOUR_17_IDS`` in ``test_validate_mounts.py``).
_BEHAVIOUR_17_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C540",
    "TSWAP-C541",
    "TSWAP-C542",
    "TSWAP-C543",
)

#: The four behaviour-18 rule ids (§6 rule 11), in code order.
_BEHAVIOUR_18_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C600",
    "TSWAP-C601",
    "TSWAP-C602",
    "TSWAP-C603",
)

#: The four behaviour-18 rule constants, in code order.
_ALL_C6XX_RULES: Final[tuple[Rule, ...]] = (
    TSWAP_C600_RULE,
    TSWAP_C601_RULE,
    TSWAP_C602_RULE,
    TSWAP_C603_RULE,
)

#: The C603 range table, in plan table order (item 6(a)): (key, range
#: phrase the message must state).  ``max_wait_ms`` is ``>= 0`` (0 =
#: flush immediately, legal); ``workers`` and ``max_batch_size`` are
#: ``>= 1``; the six timeouts are ``> 0``.
_C603_RANGES: Final[tuple[tuple[str, str], ...]] = (
    ("max_batch_size", ">= 1"),
    ("max_wait_ms", ">= 0"),
    ("workers", ">= 1"),
    ("start_timeout", "> 0"),
    ("ready_timeout", "> 0"),
    ("queue_timeout", "> 0"),
    ("request_timeout", "> 0"),
    ("drain_timeout", "> 0"),
    ("stop_timeout", "> 0"),
)

#: The six timeout keys — exactly these, and no others (``ttl``,
#: ``probe_interval`` and ``max_queue_depth`` are out of scope, item 1).
_TIMEOUT_KEYS: Final[tuple[str, ...]] = (
    "start_timeout",
    "ready_timeout",
    "queue_timeout",
    "request_timeout",
    "drain_timeout",
    "stop_timeout",
)

#: The pinned C600 remedy directives (item 3, assertable substrings).
_C600_REMEDY_KEEP_WARM: Final[str] = "set keep_warm: false"
_C600_REMEDY_AUTOSTART: Final[str] = "set autostart: true"

#: The pinned C602 remedy redirection (item 5, near-verbatim).
_C602_REMEDY: Final[str] = "use autostart: false to disable a tool"

#: The config file path every location test uses.
_CFG_PATH: Final[Path] = Path("cfg/tools.yaml")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _origins(**fields: Origin) -> OriginMap:
    """Build an ``OriginMap`` that RECORDS a real origin per field.

    Unlike the ``origins=OriginMap()`` stub used by earlier behaviour
    files, the map built here genuinely records a ``(level, source)``
    per dotted field path, so ``winning(field)`` returns a real
    ``Origin`` and the rules' origin citation is exercised.

    Args:
        **fields: flat field name (as the resolver records it, e.g.
            ``"keep_warm"``) -> the winning ``Origin`` for that field.

    Returns:
        The populated ``OriginMap``.
    """
    origins = OriginMap()
    for field, origin in fields.items():
        origins.record(field, origin)
    return origins


def _full_values(**overrides: object) -> dict[str, object]:
    """A full 47-key ``values`` mapping at built-in values, overridden.

    The rules read the RESOLVED value, and a resolved tool always
    carries the complete 47-key set — so every fixture builds one,
    overriding only the keys under test.

    Args:
        **overrides: flat field name -> value replacing the built-in.

    Returns:
        The 47-key dict (a copy; mutating it never touches
        ``BUILT_IN_DEFAULTS``).
    """
    values = dict(BUILT_IN_DEFAULTS)
    values.update(overrides)
    return values


def _tool(name: str, values: dict[str, object], origins: OriginMap) -> ResolvedTool:
    """Build a frozen ``ResolvedTool`` from a full 47-key ``values`` map.

    Args:
        name: the tool name (used as both the ``tools`` dict key and the
            ``ResolvedTool.name`` in every fixture, so the two
            namespaces agree).
        values: the resolved 47-key field mapping (see
            :func:`_full_values`).
        origins: the origin-recording ``OriginMap`` for the fields the
            rule cites (see :func:`_origins`).

    Returns:
        A ``ResolvedTool`` with no diagnostics.
    """
    return ResolvedTool(name=name, values=values, origins=origins, diagnostics=[])


def _config(
    tools: dict[str, ResolvedTool],
    line_for: Callable[[str], int | None] | None = None,
    path: Path | None = None,
) -> ValidatedConfig:
    """Build a ``ValidatedConfig``; the C6xx rules' read surface only.

    Every C60x rule reads only ``tool.values``, ``tool.origins``,
    ``config.path`` and ``config.line_for`` — no probe, no raw, no
    environment, no clock — so nothing else is carried.

    Args:
        tools: name -> ``ResolvedTool`` (positional field).
        line_for: dotted YAML path -> 1-based line or ``None``; defaults
            to a ``None``-returning mapping.
        path: the config file path; defaults to ``_CFG_PATH``.

    Returns:
        The frozen ``ValidatedConfig``.
    """
    return ValidatedConfig(
        tools=tools,
        raw={"tools": {}},
        line_for=line_for if line_for is not None else (lambda _p: None),
        path=path if path is not None else _CFG_PATH,
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


def _line_for(paths: dict[str, int]) -> Callable[[str], int | None]:
    """A fixed-int ``line_for`` answering from ``paths``.

    Args:
        paths: dotted YAML path -> 1-based line (unknown paths answer
            ``None``).

    Returns:
        The ``line_for`` callable.
    """
    return lambda path: paths.get(path)  # noqa: E731 (test-only)


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Start and end every test with an empty, known registry.

    The registry is shared module state: nothing registers itself at
    import time, and each test registers exactly the C6xx rules it
    exercises (explicitly) and must not depend on — and must not leak —
    registration state.
    """
    unregister_all()
    try:
        yield
    finally:
        unregister_all()


# ---------------------------------------------------------------------------
# TSWAP-C600 — keep_warm: true + autostart: false (ERROR; item 3)
# ---------------------------------------------------------------------------


def test_c600_keep_warm_with_autostart_false_is_error_citing_both_origins() -> None:
    """``keep_warm: true`` + ``autostart: false`` is one C600 ERROR.

    The message must name BOTH values and cite the origin of EACH, and
    the one test this whole block exists for sets the two halves in
    DIFFERENT layers and asserts both phrases appear: ``keep_warm``
    recorded INLINE, ``autostart`` recorded DEFAULTS.

    Arrangement: full 47-key values (``keep_warm=True``,
    ``autostart=False``; everything else clean, so no other rule fires);
    origins recording ``keep_warm`` INLINE and ``autostart`` DEFAULTS;
    only C600 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C600`` ERROR at
    ``tools.t1.keep_warm`` whose message contains ``keep_warm``,
    ``autostart``, ``set inline`` and ``set in the defaults: block``;
    the remedy carries both assertable directives.
    """
    register(TSWAP_C600_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(keep_warm=True, autostart=False),
                _origins(
                    keep_warm=Origin(OriginLevel.INLINE, "inline"),
                    autostart=Origin(OriginLevel.DEFAULTS, "defaults"),
                ),
            )
        },
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C600"}
    (d,) = by_code["TSWAP-C600"]
    assert d.severity is Severity.ERROR
    assert "keep_warm" in d.message
    assert "autostart" in d.message
    assert "set inline" in d.message
    assert "set in the defaults: block" in d.message
    assert _C600_REMEDY_KEEP_WARM in d.remedy
    assert _C600_REMEDY_AUTOSTART in d.remedy
    assert d.location.yaml_path == "tools.t1.keep_warm"
    assert d.location.file == str(_CFG_PATH)


def test_c600_is_silent_when_both_halves_agree() -> None:
    """No contradiction when the halves agree — no C600.

    Plan item 3 fires on ``keep_warm is True`` AND ``autostart is
    False``; both agreeing (True/True or False/False) is the clean case.

    Arrangement: a tool per agreeing combination, everything else
    clean; only C600 registered.
    Action: run ``validate_config`` per tool.
    Assertion: an empty report in both cases.
    """
    register(TSWAP_C600_RULE)
    for keep_warm, autostart in ((True, True), (False, False)):
        cfg = _config(
            tools={
                "t1": _tool(
                    "t1",
                    _full_values(keep_warm=keep_warm, autostart=autostart),
                    _origins(
                        keep_warm=Origin(OriginLevel.INLINE, "inline"),
                        autostart=Origin(OriginLevel.INLINE, "inline"),
                    ),
                )
            },
        )

        report = validate_config(cfg)

        assert report.diagnostics == ()


@pytest.mark.parametrize(
    ("keep_warm", "autostart"),
    [
        ("yes", False),
        (1, False),
        (True, "no"),
    ],
    ids=["keep-warm-str", "keep-warm-int", "autostart-str"],
)
def test_c600_skips_non_bool_values_silently(
    keep_warm: object,
    autostart: object,
) -> None:
    """A non-bool on either key is skipped silently — no C600, no C999.

    Plan item 3: identity against the bool singletons, not truthiness;
    "a value of the wrong shape is skipped silently" (behaviour 13),
    applied for the fifth time.  A rule that raised on a non-bool would
    surface as ``TSWAP-C999`` instead of silence.

    Arrangement: one non-bool per half, the other half in the
    contradicting state; only C600 registered.
    Action: run ``validate_config``.
    Assertion: an empty report (no C600, no C999, nothing).
    """
    register(TSWAP_C600_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(keep_warm=keep_warm, autostart=autostart),
                _origins(
                    keep_warm=Origin(OriginLevel.INLINE, "inline"),
                    autostart=Origin(OriginLevel.INLINE, "inline"),
                ),
            )
        },
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# TSWAP-C601 — keep_warm: true + EXPLICIT ttl > 0 (WARNING; item 4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ttl_value", "ttl_level"),
    [
        (3600, OriginLevel.INLINE),
        (3600, OriginLevel.TOOL_YAML),
    ],
    ids=["inline", "tool-yaml"],
)
def test_c601_warns_when_ttl_authored_on_the_tool(
    ttl_value: int,
    ttl_level: OriginLevel,
) -> None:
    """``keep_warm: true`` + a ``ttl > 0`` authored ON THIS TOOL warns.

    Plan item 4, condition 3 (the pin): the ttl's winning origin must
    be ``INLINE`` or ``TOOL_YAML`` — set on this tool, not inherited.
    The message states the mechanism (keep_warm exempts the tool from
    TTL, so the ttl value has no effect) and cites the origin of both
    halves.

    Arrangement: ``keep_warm=True`` (INLINE), ``ttl=ttl_value`` with the
    ttl's winning origin at ``ttl_level``; only C601 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C601`` WARNING at
    ``tools.t1.keep_warm`` whose message contains ``keep_warm``, ``ttl``,
    the ttl's origin phrase and the "no effect" mechanism.
    """
    register(TSWAP_C601_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(keep_warm=True, ttl=ttl_value),
                _origins(
                    keep_warm=Origin(OriginLevel.INLINE, "inline"),
                    ttl=Origin(ttl_level, "tool.yaml" if ttl_level is OriginLevel.TOOL_YAML else "inline"),
                ),
            )
        },
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C601"}
    (d,) = by_code["TSWAP-C601"]
    assert d.severity is Severity.WARNING
    assert "keep_warm" in d.message
    assert "ttl" in d.message
    assert "set inline" in d.message
    assert "no effect" in d.message
    assert d.location.yaml_path == "tools.t1.keep_warm"


@pytest.mark.parametrize(
    ("ttl_value", "ttl_origin"),
    [
        (900, Origin(OriginLevel.DEFAULTS, "defaults")),
        (900, Origin.built_in()),
    ],
    ids=["defaults", "built-in"],
)
def test_c601_is_silent_when_ttl_not_authored_on_the_tool(
    ttl_value: int,
    ttl_origin: Origin,
) -> None:
    """A ``DEFAULTS`` or ``BUILT_IN`` ttl does NOT warn, however large.

    Plan item 4's rejected reading (b): a ``defaults.ttl`` written once
    for a dozen tools expresses no expectation about the keep-warm one,
    and the built-in 900 is the plain default.  This is the pin that
    keeps the specification's own reference config clean (behaviour 24
    with ``--strict``).

    Arrangement: ``keep_warm=True`` (INLINE) + ``ttl`` at the given
    non-tool origin; only C601 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C601_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(keep_warm=True, ttl=ttl_value),
                _origins(
                    keep_warm=Origin(OriginLevel.INLINE, "inline"),
                    ttl=ttl_origin,
                ),
            )
        },
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c601_is_silent_when_keep_warm_is_false() -> None:
    """An inline ``ttl: 3600`` beside ``keep_warm: false`` does not warn.

    Plan item 4, condition 1: ``values["keep_warm"] is True`` must hold;
    without keep_warm the ttl is a live idle timeout, not dead weight.

    Arrangement: ``keep_warm=False`` (INLINE), ``ttl=3600`` INLINE.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C601_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(keep_warm=False, ttl=3600),
                _origins(
                    keep_warm=Origin(OriginLevel.INLINE, "inline"),
                    ttl=Origin(OriginLevel.INLINE, "inline"),
                ),
            )
        },
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c601_is_silent_when_ttl_is_zero_sentinel() -> None:
    """``ttl: 0`` is the "never idle-stop" sentinel, not ``> 0`` — silent.

    Plan item 4's table: ``ttl: 0`` **agrees** with ``keep_warm`` (both
    say the tool never stops on its own), so the ``> 0`` clause fails
    and no warning fires.

    Arrangement: ``keep_warm=True`` (INLINE), ``ttl=0`` INLINE.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C601_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(keep_warm=True, ttl=0),
                _origins(
                    keep_warm=Origin(OriginLevel.INLINE, "inline"),
                    ttl=Origin(OriginLevel.INLINE, "inline"),
                ),
            )
        },
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c601_is_silent_when_inline_ttl_minus_one_inherited() -> None:
    """An inline ``ttl: -1`` that inherited the layer's origin: silent.

    Bonus pin (plan item 4, last paragraph): the resolver's
    ``_resolve_ttl`` records the origin of the layer the ``-1``
    sentinel INHERITED FROM, not of the layer holding the ``-1``.  So an
    inline ``ttl: -1`` beside ``defaults: {ttl: 900}`` resolves with a
    ``DEFAULTS`` origin and does not warn — the correct answer, since
    ``-1`` means "whatever the defaults say", i.e. no per-tool
    expectation.  This test EXERCISES THE RESOLVER'S INHERITANCE, NOT
    THE RULE: the ``ResolvedTool`` is built directly with ``ttl=-1``
    and the ttl's winning origin at the inherited (``DEFAULTS``) level,
    exactly as the landed resolver records it.

    Arrangement: ``keep_warm=True`` (INLINE), ``ttl=-1`` with a
    ``DEFAULTS``-level winning origin.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C601_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(keep_warm=True, ttl=-1),
                _origins(
                    keep_warm=Origin(OriginLevel.INLINE, "inline"),
                    ttl=Origin(OriginLevel.DEFAULTS, "defaults"),
                ),
            )
        },
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c601_skips_non_numeric_ttl_silently() -> None:
    """A non-numeric ``ttl`` is skipped silently (C105 owns it).

    Plan item 4, condition 2: ``ttl`` must be an ``int``/``float``, not
    a ``bool``; a value of the wrong shape is skipped silently rather
    than raised (which would surface as ``TSWAP-C999``).

    Arrangement: ``keep_warm=True`` (INLINE), ``ttl="soon"`` INLINE.
    Action: run ``validate_config``.
    Assertion: an empty report (no C601, no C999, nothing).
    """
    register(TSWAP_C601_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(keep_warm=True, ttl="soon"),
                _origins(
                    keep_warm=Origin(OriginLevel.INLINE, "inline"),
                    ttl=Origin(OriginLevel.INLINE, "inline"),
                ),
            )
        },
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# TSWAP-C602 — max_concurrent <= 0 (ERROR; item 5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "value_str"),
    [
        (0, "0"),
        (-1, "-1"),
    ],
    ids=["zero", "negative"],
)
def test_c602_caps_at_or_below_zero_are_errors(value: int, value_str: str) -> None:
    """``max_concurrent <= 0`` (widened from ``== 0``) is a C602 ERROR.

    The message names the field, the ACTUAL value found, and its origin
    phrase; the remedy carries the plan's own redirection verbatim
    enough to assert: ``use autostart: false to disable a tool``.

    Arrangement: ``max_concurrent=value`` (INLINE origin); only C602
    registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C602`` ERROR at
    ``tools.t1.max_concurrent`` naming the field and the value, with the
    pinned remedy substring.
    """
    register(TSWAP_C602_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(max_concurrent=value),
                _origins(
                    max_concurrent=Origin(OriginLevel.INLINE, "inline"),
                ),
            )
        },
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C602"}
    (d,) = by_code["TSWAP-C602"]
    assert d.severity is Severity.ERROR
    assert "max_concurrent" in d.message
    assert value_str in d.message
    assert _C602_REMEDY in d.remedy
    assert d.location.yaml_path == "tools.t1.max_concurrent"


def test_c602_is_silent_when_max_concurrent_is_none_or_positive() -> None:
    """``None`` (the documented "uncapped") and a positive cap: no C602.

    Plan item 5: ``None`` is the built-in value every clean tool hits,
    and a positive cap is a working setting.

    Arrangement: a tool per value (``None`` and ``3``), INLINE origin
    in both cases; only C602 registered.
    Action: run ``validate_config`` per tool.
    Assertion: an empty report in both cases.
    """
    register(TSWAP_C602_RULE)
    for value in (None, 3):
        cfg = _config(
            tools={
                "t1": _tool(
                    "t1",
                    _full_values(max_concurrent=value),
                    _origins(
                        max_concurrent=Origin(OriginLevel.INLINE, "inline"),
                    ),
                )
            },
        )

        report = validate_config(cfg)

        assert report.diagnostics == ()


def test_c602_skips_non_int_values_silently() -> None:
    """A non-int ``max_concurrent`` (e.g. ``"0"``) is skipped silently.

    Plan item 5: the ``bool``-before-``int`` discipline — a value of the
    wrong shape is the schema's ``TSWAP-C105`` to own, skipped silently
    here rather than re-reported as a cap-of-zero (which would name a
    number the author never wrote).

    Arrangement: ``max_concurrent="0"`` (INLINE origin).
    Action: run ``validate_config``.
    Assertion: an empty report (no C602, no C999, nothing).
    """
    register(TSWAP_C602_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(max_concurrent="0"),
                _origins(
                    max_concurrent=Origin(OriginLevel.INLINE, "inline"),
                ),
            )
        },
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# TSWAP-C603 — out-of-range numbers (ERROR; item 6(a)), one table rule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "value", "range_phrase"),
    [
        ("max_batch_size", 0, ">= 1"),
        ("max_batch_size", -2, ">= 1"),
        ("max_wait_ms", -1, ">= 0"),
        ("workers", 0, ">= 1"),
        ("workers", -1, ">= 1"),
        *[(field, 0, "> 0") for field in _TIMEOUT_KEYS],
        *[(field, -5, "> 0") for field in _TIMEOUT_KEYS],
    ],
    ids=[
        "batch-size-zero",
        "batch-size-negative",
        "wait-ms-negative",
        "workers-zero",
        "workers-negative",
        *["zero-" + field for field in _TIMEOUT_KEYS],
        *["negative-" + field for field in _TIMEOUT_KEYS],
    ],
)
def test_c603_out_of_range_value_is_error_naming_field_and_range(
    field: str,
    value: int,
    range_phrase: str,
) -> None:
    """One out-of-range value is one C603 naming the field and the range.

    Plan item 6(a): one table-driven rule over the nine fields; the
    message names the offending FIELD, its range phrase and its origin
    (this test records every field INLINE, so ``set inline`` is the
    assertable phrase).

    Arrangement: the single field at ``value`` (INLINE origin), every
    other C603 field legal; only C603 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C603`` ERROR at
    ``tools.t1.<field>`` naming the field, the value and the range
    phrase.
    """
    register(TSWAP_C603_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(**{field: value}),
                _origins(**{field: Origin(OriginLevel.INLINE, "inline")}),
            )
        },
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C603"}
    (d,) = by_code["TSWAP-C603"]
    assert d.severity is Severity.ERROR
    assert field in d.message
    assert str(value) in d.message
    assert range_phrase in d.message
    assert "set inline" in d.message
    assert d.location.yaml_path == f"tools.t1.{field}"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_batch_size", 1),
        ("max_wait_ms", 0),  # 0 = flush immediately: legal, not an error
        ("workers", 1),
        *[(field, 1) for field in _TIMEOUT_KEYS],
    ],
    ids=[
        "batch-size-one",
        "wait-ms-zero",
        "workers-one",
        *["one-" + field for field in _TIMEOUT_KEYS],
    ],
)
def test_c603_legal_boundary_values_are_silent(field: str, value: int) -> None:
    """The legal boundary of each field is silent — no C603.

    Plan item 6(a): ``max_wait_ms: 0`` is explicitly legal (``>= 0``);
    ``1`` is the floor for ``max_batch_size`` / ``workers`` / the
    timeouts.

    Arrangement: the single field at its legal boundary (INLINE origin);
    only C603 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C603_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(**{field: value}),
                _origins(**{field: Origin(OriginLevel.INLINE, "inline")}),
            )
        },
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c603_emits_one_diagnostic_per_offending_key() -> None:
    """Three offending keys in one tool are THREE C603s, at their fields.

    Plan item 6(a): one diagnostic PER offending key, each naming its
    own field, its own range and its own origin — each is a separate
    edit.  Order within a tool is table order (deterministic,
    values-independent).

    Arrangement: ``max_batch_size=0``, ``workers=0`` and
    ``start_timeout=0`` in one tool, all INLINE origins; only C603
    registered.
    Action: run ``validate_config``.
    Assertion: exactly three ``TSWAP-C603`` diagnostics, at
    ``tools.t1.max_batch_size``, ``tools.t1.workers`` and
    ``tools.t1.start_timeout`` (table order), each naming its own field
    and range.
    """
    register(TSWAP_C603_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(
                    max_batch_size=0,
                    workers=0,
                    start_timeout=0,
                ),
                _origins(
                    max_batch_size=Origin(OriginLevel.INLINE, "inline"),
                    workers=Origin(OriginLevel.INLINE, "inline"),
                    start_timeout=Origin(OriginLevel.INLINE, "inline"),
                ),
            )
        },
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C603"}
    (first, second, third) = by_code["TSWAP-C603"]
    assert [d.location.yaml_path for d in by_code["TSWAP-C603"]] == [
        "tools.t1.max_batch_size",
        "tools.t1.workers",
        "tools.t1.start_timeout",
    ]
    assert "max_batch_size" in first.message
    assert ">= 1" in first.message
    assert "workers" in second.message
    assert ">= 1" in second.message
    assert "start_timeout" in third.message
    assert "> 0" in third.message


def test_c603_skips_non_numeric_values_silently() -> None:
    """A non-numeric on any C603 field is skipped silently (C105 owns it).

    Plan item 6(a): every check is ``bool``-before-``int``; a value of
    the wrong shape is skipped silently rather than raised (which would
    surface as ``TSWAP-C999``).

    Arrangement: ``max_batch_size="big"`` and ``start_timeout="soon"``;
    only C603 registered.
    Action: run ``validate_config``.
    Assertion: an empty report (no C603, no C999, nothing).
    """
    register(TSWAP_C603_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(max_batch_size="big", start_timeout="soon"),
                _origins(
                    max_batch_size=Origin(OriginLevel.INLINE, "inline"),
                    start_timeout=Origin(OriginLevel.INLINE, "inline"),
                ),
            )
        },
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# Location contract — pinned relationally (item 7)
# ---------------------------------------------------------------------------


def test_location_uses_line_for_and_config_path_with_known_line() -> None:
    """The location is ``file=str(config.path)`` + ``line_for(yaml_path)``.

    Plan item 7: ``Location(file=str(config.path), yaml_path=<pinned>,
    line=config.line_for(<the same string>))`` — the file is never
    hardcoded and the line comes from ``line_for`` on the SAME dotted
    path.  This test pins the known-line half with a fixed-int
    ``line_for``.

    Arrangement: the C600-firing tool; ``line_for`` answering 42 for
    ``tools.t1.keep_warm``; the config path ``cfg/tools.yaml``.
    Action: run ``validate_config``.
    Assertion: ``location.file == "cfg/tools.yaml"``,
    ``location.yaml_path == "tools.t1.keep_warm"`` and
    ``location.line == 42`` — i.e. ``line == line_for(yaml_path)``.
    """
    register(TSWAP_C600_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(keep_warm=True, autostart=False),
                _origins(
                    keep_warm=Origin(OriginLevel.INLINE, "inline"),
                    autostart=Origin(OriginLevel.DEFAULTS, "defaults"),
                ),
            )
        },
        line_for=_line_for({"tools.t1.keep_warm": 42}),
    )

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert d.location.file == "cfg/tools.yaml"
    assert d.location.yaml_path == "tools.t1.keep_warm"
    assert d.location.line == 42
    assert d.location.line == cfg.line_for(d.location.yaml_path)


def test_location_line_is_none_when_line_for_answers_none() -> None:
    """A ``None``-returning ``line_for`` surfaces ``line=None``.

    Plan item 7: ``line=None`` is a legal outcome (e.g. ``keep_warm``
    came from ``defaults:`` and the tools entry never wrote it).

    Arrangement: the same C600-firing tool; the default
    ``None``-returning ``line_for``.
    Action: run ``validate_config``.
    Assertion: the yaml_path is still pinned and ``line is None``.
    """
    register(TSWAP_C600_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(keep_warm=True, autostart=False),
                _origins(
                    keep_warm=Origin(OriginLevel.INLINE, "inline"),
                    autostart=Origin(OriginLevel.DEFAULTS, "defaults"),
                ),
            )
        },
    )

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert d.location.yaml_path == "tools.t1.keep_warm"
    assert d.location.line is None
    assert d.location.line == cfg.line_for(d.location.yaml_path)


# ---------------------------------------------------------------------------
# Severity and remedy pins (item 8)
# ---------------------------------------------------------------------------


def test_rule_objects_carry_expected_ids_severities_and_nonempty_remedies() -> None:
    """Each C60x rule carries its id, pinned severity, non-empty remedy.

    Plan item 8: C600 ERROR, C601 WARNING, C602 ERROR, C603 ERROR; every
    remedy non-empty (the ``Rule`` constructor enforces this, but the
    test names the four so a silent re-wiring is caught at a glance).

    Arrangement: the four rule constants imported from ``validate``.
    Action: read back ``id``, ``severity`` and ``remedy``.
    Assertion: ids/severities per the pin; every remedy a non-empty,
    non-whitespace string.
    """
    assert TSWAP_C600_RULE.id == "TSWAP-C600"
    assert TSWAP_C600_RULE.severity is Severity.ERROR
    assert TSWAP_C601_RULE.id == "TSWAP-C601"
    assert TSWAP_C601_RULE.severity is Severity.WARNING
    assert TSWAP_C602_RULE.id == "TSWAP-C602"
    assert TSWAP_C602_RULE.severity is Severity.ERROR
    assert TSWAP_C603_RULE.id == "TSWAP-C603"
    assert TSWAP_C603_RULE.severity is Severity.ERROR
    for rule in _ALL_C6XX_RULES:
        assert isinstance(rule.remedy, str)
        assert rule.remedy.strip()


def test_c6xx_rules_are_appended_to_builtin_rules_after_behaviour_17() -> None:
    """The four C60x ids are appended to ``BUILTIN_RULES`` in code order.

    Plan item 9: appended after behaviour 17's four — 38 landed rules in
    total — anchored by INDEX, never by tail slice or total count
    (mirrors behaviour 17's index-anchored append test).

    Arrangement: the ``BUILTIN_RULES`` tuple.
    Action: locate behaviour 17's first id, check the four preceding
    block lengths, slice forward by four.
    Assertion: the slice is exactly the four C60x ids in code order, and
    each element IS the corresponding module constant (identity).
    """
    ids = [rule.id for rule in BUILTIN_RULES]
    preceding = (
        len(_BEHAVIOUR_12_IDS)
        + len(_BEHAVIOUR_13_IDS)
        + len(_BEHAVIOUR_14_IDS)
        + len(_BEHAVIOUR_15_IDS)
        + len(_BEHAVIOUR_16_IDS)
    )
    first_c600 = ids.index(_BEHAVIOUR_17_IDS[0])

    assert first_c600 == preceding + len(_BEHAVIOUR_17_IDS)
    assert ids[first_c600 + len(_BEHAVIOUR_17_IDS) : first_c600 + len(_BEHAVIOUR_17_IDS) + 4] == list(
        _BEHAVIOUR_18_IDS
    )
    base = first_c600 + len(_BEHAVIOUR_17_IDS)
    assert BUILTIN_RULES[base] is TSWAP_C600_RULE
    assert BUILTIN_RULES[base + 1] is TSWAP_C601_RULE
    assert BUILTIN_RULES[base + 2] is TSWAP_C602_RULE
    assert BUILTIN_RULES[base + 3] is TSWAP_C603_RULE


# ---------------------------------------------------------------------------
# Cross-rule pins
# ---------------------------------------------------------------------------


def test_clean_tool_produces_no_c6xx_diagnostics() -> None:
    """A clean resolved tool emits no C6xx diagnostic (only-own-codes pin).

    Plan item 11's five-line-config property at rule level: every C60x
    rule stays silent when nothing contradicts — and, just as
    important, when the tool has NO origin recorded for a field it
    reads (the ``KeyError`` hazard, item 2(a)): the rules go through the
    shared total helper and an unrecorded origin yields the
    ``origin unrecorded`` phrase, never a ``TSWAP-C999`` crash.

    Arrangement: ``keep_warm=False``, ``autostart=True``,
    ``max_concurrent=None``, ``max_batch_size=8``, ``max_wait_ms=20``,
    ``workers=1``, all six timeouts ``30``, ``ttl=900`` with a
    ``DEFAULTS``-level origin (so even C601's origin lookup has a
    recorded entry); an EMPTY ``OriginMap`` would not be a valid
    fixture for the citation path, so origins are recorded per field;
    all four C60x rules registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    for rule in _ALL_C6XX_RULES:
        register(rule)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(
                    keep_warm=False,
                    autostart=True,
                    max_concurrent=None,
                    max_batch_size=8,
                    max_wait_ms=20,
                    workers=1,
                    start_timeout=30,
                    ready_timeout=30,
                    queue_timeout=30,
                    request_timeout=30,
                    drain_timeout=30,
                    stop_timeout=30,
                    ttl=900,
                ),
                _origins(
                    keep_warm=Origin.built_in(),
                    autostart=Origin.built_in(),
                    ttl=Origin(OriginLevel.DEFAULTS, "defaults"),
                ),
            )
        },
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_multiple_contradictions_are_all_reported_in_one_pass() -> None:
    """C600 + C602 + C603 all fire in one report for one tool.

    The multiple-in-one-report pin: a tool with
    ``keep_warm=True`` (INLINE) + ``autostart=False`` (DEFAULTS) +
    ``max_concurrent=0`` + ``max_batch_size=0`` produces C600, C602 and
    C603 together — nothing suppresses the other findings, and C601
    does NOT fire (the ``DEFAULTS``-origin ``ttl`` is the item-4 pin).

    Arrangement: the four-offence tool, every other value clean and
    legal, origins recorded for the cited fields; all four C60x rules
    registered.
    Action: run ``validate_config``.
    Assertion: exactly one diagnostic each of C600, C602 and C603 — and
    no C601, no C999.
    """
    for rule in _ALL_C6XX_RULES:
        register(rule)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                _full_values(
                    keep_warm=True,
                    autostart=False,
                    max_concurrent=0,
                    max_batch_size=0,
                    ttl=900,
                ),
                _origins(
                    keep_warm=Origin(OriginLevel.INLINE, "inline"),
                    autostart=Origin(OriginLevel.DEFAULTS, "defaults"),
                    max_concurrent=Origin(OriginLevel.INLINE, "inline"),
                    max_batch_size=Origin(OriginLevel.INLINE, "inline"),
                    ttl=Origin(OriginLevel.DEFAULTS, "defaults"),
                ),
            )
        },
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C600", "TSWAP-C602", "TSWAP-C603"}
    assert len(by_code["TSWAP-C600"]) == 1
    assert len(by_code["TSWAP-C602"]) == 1
    assert len(by_code["TSWAP-C603"]) == 1


# ---------------------------------------------------------------------------
# batching.enabled: false -> max_batch_size: 1 (item 6(b)) — RESOLVER
# behaviour, asserted as a resolution OUTCOME (item 6(c))
#
# These tests call ``resolve_tool`` directly and import NO C6xx name, so
# in the red window they fail on the VALUE assertion (max_batch_size is
# the authored 8, not the overridden 1) — the right red reason, an
# assertion, not an import.
# ---------------------------------------------------------------------------


def test_batching_enabled_false_overrides_authored_max_batch_size_to_one() -> None:
    """``batching: {enabled: false}`` resolves ``max_batch_size`` to 1.

    Pinned (item 6(b)): when the effective ``batching.enabled`` is
    exactly ``False``, ``values["max_batch_size"]`` becomes ``1``
    REGARDLESS of any authored ``max_batch_size`` at any layer — here an
    authored ``8`` in the SAME tool.yaml block, proving the override
    wins over the authored value.

    Arrangement: ``resolve_tool`` with ``tool_yaml`` carrying
    ``batching: {enabled: false, max_batch_size: 8}``.
    Action: resolve.
    Assertion: ``values["max_batch_size"] == 1`` (and the resolution is
    clean — no diagnostic of its own; C603 would accept 1 anyway).
    """
    result = resolve_tool(
        "t1",
        inline={},
        tool_yaml={"batching": {"enabled": False, "max_batch_size": 8}},
    )

    assert result.values["max_batch_size"] == 1
    assert result.diagnostics == ()


def test_batching_enabled_false_overrides_authored_max_batch_size_at_any_layer() -> None:
    """The override beats an inline-authored ``max_batch_size`` too.

    Item 6(b): "regardless of any authored ``max_batch_size`` at ANY
    layer" — inline is the most specific layer, and the translation
    still wins (``enabled: false`` means ``max_batch_size: 1`` and
    NOTHING ELSE).

    Arrangement: ``inline={"max_batch_size": 32}`` over
    ``tool_yaml={"batching": {"enabled": False}}``.
    Action: resolve.
    Assertion: ``values["max_batch_size"] == 1``.
    """
    result = resolve_tool(
        "t1",
        inline={"max_batch_size": 32},
        tool_yaml={"batching": {"enabled": False}},
    )

    assert result.values["max_batch_size"] == 1


def test_batching_enabled_true_does_not_override_max_batch_size() -> None:
    """``enabled: true`` is a no-op — the authored value resolves as is.

    Item 6(b): the override fires on ``is False`` only; ``true``
    changes nothing (``1`` would be a silent shrink of a deliberate
    setting).

    Arrangement: ``tool_yaml`` carrying
    ``batching: {enabled: true, max_batch_size: 8}``.
    Action: resolve.
    Assertion: ``values["max_batch_size"] == 8``.
    """
    result = resolve_tool(
        "t1",
        inline={},
        tool_yaml={"batching": {"enabled": True, "max_batch_size": 8}},
    )

    assert result.values["max_batch_size"] == 8


def test_batching_absent_resolves_max_batch_size_normally() -> None:
    """No ``batching`` block at all: the built-in default stands.

    Item 6(b): "Absent means absent" — a ``batching:`` block the
    tool.yaml never writes never fires the override.

    Arrangement: ``resolve_tool`` with no ``tool_yaml`` at all.
    Action: resolve.
    Assertion: ``values["max_batch_size"] == 8`` (the built-in).
    """
    result = resolve_tool("t1", inline={})

    assert result.values["max_batch_size"] == 8


def test_batching_enabled_false_touches_nothing_else() -> None:
    """``enabled: false`` changes ONLY ``max_batch_size`` — "nothing else".

    Item 6(b): ``max_wait_ms``, ``workers`` and every other
    batching-adjacent field are untouched — the translation is
    ``max_batch_size: 1`` and nothing else.  ``max_wait_ms`` and
    ``workers`` are FLAT tool.yaml keys (they are not nested under
    ``batching:``), so they are passed as top-level ``tool_yaml`` keys.

    Arrangement: ``tool_yaml`` carrying
    ``batching: {enabled: false, max_batch_size: 8}`` (the 8 overridden)
    plus flat ``max_wait_ms: 44`` and ``workers: 3``.
    Action: resolve.
    Assertion: ``max_batch_size == 1`` while ``max_wait_ms == 44`` and
    ``workers == 3`` (their authored values) and ``ttl`` / ``cpus``
    keep their built-in values.
    """
    result = resolve_tool(
        "t1",
        inline={},
        tool_yaml={
            "batching": {
                "enabled": False,
                "max_batch_size": 8,
            },
            "max_wait_ms": 44,
            "workers": 3,
        },
    )

    assert result.values["max_batch_size"] == 1
    assert result.values["max_wait_ms"] == 44
    assert result.values["workers"] == 3
    assert result.values["ttl"] == BUILT_IN_DEFAULTS["ttl"]
    assert result.values["cpus"] == BUILT_IN_DEFAULTS["cpus"]


def test_batching_enabled_key_never_enters_values_and_47_key_set_is_unchanged() -> None:
    """``enabled`` never enters ``values``; the 47-key set does not change.

    Item 6(b): ``enabled`` is read from the layers, used, and DISCARDED
    — the ``soft_ttl``-scan precedent, one layer down.  ``BUILT_IN_DEFAULTS``
    stays 47 and so does ``values``.

    Arrangement: ``tool_yaml`` carrying
    ``batching: {enabled: false, max_batch_size: 8}``.
    Action: resolve.
    Assertion: ``"enabled" not in result.values`` and
    ``set(result.values) == set(BUILT_IN_DEFAULTS)``.
    """
    result = resolve_tool(
        "t1",
        inline={},
        tool_yaml={"batching": {"enabled": False, "max_batch_size": 8}},
    )

    assert "enabled" not in result.values
    assert set(result.values) == set(BUILT_IN_DEFAULTS)


def test_batching_disabled_records_max_batch_size_origin_from_enabled_key() -> None:
    """The overridden ``max_batch_size``'s origin is the ``enabled`` key's.

    Pinned (item 6(b)): the origin recorded for the overridden
    ``max_batch_size`` is the origin of the ``enabled`` key that caused
    it, because that is the line the author must edit to change the
    outcome — pointing at a shadowed ``max_batch_size:`` would be
    actively misleading.  ``enabled`` is tool.yaml-only (item 6(b),
    "tool.yaml only"), so the recorded level is ``TOOL_YAML``.

    Arrangement: ``tool_yaml`` carrying
    ``batching: {enabled: false, max_batch_size: 8}``.
    Action: resolve.
    Assertion: ``origins.winning("max_batch_size").level`` is
    ``TOOL_YAML`` (the level of the ``enabled`` key's origin, NOT
    ``BUILT_IN``, which the authored-8 resolution would record only if
    the override never fired).
    """
    result = resolve_tool(
        "t1",
        inline={},
        tool_yaml={"batching": {"enabled": False, "max_batch_size": 8}},
    )

    assert result.origins.winning("max_batch_size").level is OriginLevel.TOOL_YAML

"""Tests for M1 behaviour 11a — the registration entry point.

See ``plans/m1-configuration.md`` §1, "Registration mechanism — DECIDED
(2026-08-18)" (lines 211-235) and behaviour 11a (lines 237-252).

This file is the RED step: ``BUILTIN_RULES`` and ``register_builtin_rules``
do not exist yet in ``src/tool_swap/config/validate.py`` (behaviour 11
shipped the empty-registry skeleton only; importing the module registers
nothing).  This module therefore fails collection with a single clean
``ImportError`` naming exactly one missing name:

    ImportError: cannot import name 'BUILTIN_RULES'
        from 'tool_swap.config.validate'

(``BUILTIN_RULES`` is the first missing name in the import list; Python
reports the first one it fails on.)  Every test body below pins a concrete
behaviour the GREEN step must satisfy, so the assertions — not just the
import — are the contract.

Pinned public API (the contract the GREEN step must meet verbatim):

- ``BUILTIN_RULES: tuple[Rule, ...]`` — every rule M1 ships, in **code
  order**; importing ``validate.py`` registers nothing, this constant is
  the list M5 moves.  At this step it holds exactly behaviour 12's six
  rules (``TSWAP-C210`` … ``TSWAP-C223``); behaviours 13-19 each append
  their own rules.
- ``register_builtin_rules() -> None`` — registers every rule in
  ``BUILTIN_RULES``.  **Idempotent:** a rule already registered *as the
  same object* is skipped, so calling it twice raises nothing and never
  duplicates ids; an id registered by a *different* object still raises
  ``ValueError`` through the existing ``register()`` guard — only
  same-object re-entry is a no-op, a genuine id clash is never swallowed.

Edge cases: no module-reload of ``validate.py`` anywhere in this
suite (the registry is live module-level state and a reload would
rebind it to a new object, detaching every ``from ... import RULES``
binding); the correct, non-destructive form is an ordinary re-import via
``importlib.import_module``.

Conventions mirror ``tests/unit/config/test_validate_registry.py``:
pytest, AAA, snake_case, Google docstrings, an autouse fixture calling
``unregister_all()`` before AND after every test (the registry is shared
module state).
"""

from __future__ import annotations

import importlib
from typing import Final

import pytest
from tool_swap.config.validate import (  # noqa: E501  (names absent in RED step)
    BUILTIN_RULES,
    Rule,
    register_builtin_rules,
    registered_rule_ids,
    unregister_all,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The §6 rule codes in scope for M1 as of this step — behaviour 12's six
#: (plan lines 254-265).  ``TSWAP-C999`` (the internal "a rule raised"
#: diagnostic, plan line 206) is OUTSIDE the §6 rule set and is excluded:
#: it is not a rule id, it is the code ``validate_config`` emits for a
#: failing rule.
#:
#: BEHAVIOURS 14-19 EXTEND THIS CONSTANT FURTHER: add each behaviour's
#: codes here (in code order) when that behaviour's rules land in
#: ``BUILTIN_RULES`` — the completeness test below then enforces "no
#: silent drop" mechanically.
_EXPECTED_BUILTIN_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C210",
    "TSWAP-C211",
    "TSWAP-C220",
    "TSWAP-C221",
    "TSWAP-C222",
    "TSWAP-C223",
    # Behaviour 13 (D19 mandatory descriptions) extends the set here.
    "TSWAP-C300",
    "TSWAP-C301",
    "TSWAP-C302",
    "TSWAP-C303",
    # Behaviour 14 (withdrawn/reserved keys) extends the set here.
    "TSWAP-C400",
    "TSWAP-C401",
    "TSWAP-C402",
    "TSWAP-C403",
    "TSWAP-C404",
    "TSWAP-C405",
)


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Start and end every test with an empty, known registry.

    The registry is shared module state: nothing registers itself at import
    time (Option B), and each test must not depend on — and must not leak —
    registration state (same isolation contract as the behaviour-11 file).
    """
    unregister_all()
    try:
        yield
    finally:
        unregister_all()


# ---------------------------------------------------------------------------
# 1. The BUILTIN_RULES constant (shape, membership, order)
# ---------------------------------------------------------------------------


def test_builtin_rules_is_a_tuple_of_rules_with_unique_ids() -> None:
    """``BUILTIN_RULES`` is a tuple of ``Rule`` instances with unique ids.

    Arrangement: the module constant itself.
    Action: inspect the container type, the element types and the id set.
    Assertion: the container is a ``tuple`` (not a list or a registry),
    every entry is an instance of ``Rule``, and no id appears twice.
    """
    assert isinstance(BUILTIN_RULES, tuple)
    for rule in BUILTIN_RULES:
        assert isinstance(rule, Rule)
    ids = [rule.id for rule in BUILTIN_RULES]
    assert len(ids) == len(set(ids))


def test_builtin_rules_carries_the_behaviour_12_codes_in_code_order() -> None:
    """``BUILTIN_RULES`` pins the six behaviour-12 codes in code order.

    Arrangement: the module constant itself.
    Action: read the ids back in tuple order.
    Assertion: the id sequence is exactly ``TSWAP-C210, TSWAP-C211,
    TSWAP-C220, TSWAP-C221, TSWAP-C222, TSWAP-C223`` — code order, so the
    constant is a stable, greppable list of "the rules M1 ships" that M5
    moves rather than re-derives.
    """
    assert [rule.id for rule in BUILTIN_RULES] == list(_EXPECTED_BUILTIN_IDS)


# ---------------------------------------------------------------------------
# 2. register_builtin_rules(): the entry point
# ---------------------------------------------------------------------------


def test_register_builtin_rules_registers_exactly_the_builtin_ids_in_order() -> None:
    """Calling the entry point registers ``BUILTIN_RULES``, in its order.

    Arrangement: the registry cleared by the autouse fixture.
    Action: call ``register_builtin_rules()`` once.
    Assertion: ``registered_rule_ids()`` is EXACTLY ``[rule.id for rule in
    BUILTIN_RULES]`` — same ids, same order, nothing added and nothing
    dropped (plan line 244).
    """
    register_builtin_rules()

    assert registered_rule_ids() == [rule.id for rule in BUILTIN_RULES]


def test_register_builtin_rules_is_idempotent() -> None:
    """A second call raises nothing and does not duplicate ids.

    Behaviour 21 and the test suite may both reach the entry point, so
    same-object re-entry must be a silent no-op (plan line 245): ``register()``
    keeps its strict duplicate guard, but ``register_builtin_rules()``
    skips rules already registered as the same object.

    Arrangement: the registry cleared, then the entry point called once.
    Action: call ``register_builtin_rules()`` a second time.
    Assertion: no exception, and the id list is unchanged (no duplicates).
    """
    register_builtin_rules()
    first = registered_rule_ids()

    register_builtin_rules()

    assert registered_rule_ids() == first
    assert len(registered_rule_ids()) == len(set(registered_rule_ids()))


def test_register_builtin_rules_restores_after_unregister_all() -> None:
    """After ``unregister_all()``, the entry point restores the same ids.

    The fixture-friendly property that makes Option B work with the autouse
    reset fixtures (plan line 246): wiping the registry and re-calling the
    entry point brings back exactly the same ids.

    Arrangement: the entry point called once, then the registry wiped.
    Action: call ``register_builtin_rules()`` again.
    Assertion: the ids equal ``[rule.id for rule in BUILTIN_RULES]`` again.
    """
    register_builtin_rules()
    expected = registered_rule_ids()

    unregister_all()
    assert registered_rule_ids() == []

    register_builtin_rules()
    assert registered_rule_ids() == expected


def test_register_builtin_rules_raises_on_genuine_id_clash() -> None:
    """A DIFFERENT rule object claiming a builtin id is still fatal.

    Only same-object re-entry is a skip; a real id clash — e.g. a test
    fixture or a user rule registering ``TSWAP-C210`` with its own object
    before the entry point runs — must raise through the existing
    ``register()`` guard, never be swallowed (plan line 234, decision
    table row "Duplicate-registration RAISING").

    Arrangement: the registry cleared; a distinct ``Rule`` instance whose
    ``id`` equals the first builtin rule's id, registered directly.
    Action: call ``register_builtin_rules()``.
    Assertion: ``ValueError`` whose message contains the clashing id.
    """
    clashing_id = BUILTIN_RULES[0].id
    impostor = Rule(
        id=clashing_id,
        severity=BUILTIN_RULES[0].severity,
        remedy="An impostor rule that must not displace the builtin.",
    )
    assert impostor is not BUILTIN_RULES[0]
    from tool_swap.config.validate import register

    register(impostor)

    with pytest.raises(ValueError, match=clashing_id):
        register_builtin_rules()


# ---------------------------------------------------------------------------
# 3. No import side effects (plan line 235, behaviour 11 line 250)
# ---------------------------------------------------------------------------


def test_ordinary_re_import_leaves_the_registry_unchanged() -> None:
    """Re-importing ``validate.py`` registers nothing (no reload anywhere).

    The non-destructive counterpart of behaviour 11's ``import_module``
    test: an ordinary re-import of the already-loaded module must not
    change registration state, even after the entry point has run.  This
    file deliberately never reloads the module — a reload would
    rebind the module-level registry to a new object while other test
    modules keep their original ``from ... import RULES`` binding.

    Arrangement: the entry point called once, ids captured.
    Action: ``importlib.import_module("tool_swap.config.validate")``.
    Assertion: ``registered_rule_ids()`` is unchanged.
    """
    register_builtin_rules()
    before = registered_rule_ids()

    importlib.import_module("tool_swap.config.validate")

    assert registered_rule_ids() == before
    assert before == [rule.id for rule in BUILTIN_RULES]


# ---------------------------------------------------------------------------
# 4. Line-205 completeness: no rule is quietly dropped
# ---------------------------------------------------------------------------


def test_builtin_rules_cover_every_rule_behaviour_landed_so_far() -> None:
    """The set of ``BUILTIN_RULES`` ids equals the §6 codes in scope.

    This is behaviour 11's line-205 no-silent-drop guarantee, made
    mechanical (plan lines 249, 225): at this step the rule behaviours
    landed so far are exactly behaviour 12's six (C210, C211, C220, C221,
    C222, C223), so the id SET must equal ``_EXPECTED_BUILTIN_IDS``.
    ``TSWAP-C999`` — the internal "a rule raised" diagnostic emitted by
    ``validate_config`` — is OUTSIDE the §6 rule set and must NOT appear
    in ``BUILTIN_RULES``.

    Behaviours 13-19 extend ``_EXPECTED_BUILTIN_IDS`` as they land;
    extending the constant is a one-line change, and any rule added to
    ``BUILTIN_RULES`` without an expected-set entry (or vice versa)
    fails here.

    Arrangement: the module constant and the expected-set constant.
    Action: compare the two sets.
    Assertion: set equality in both directions, with C999 explicitly
    absent.
    """
    builtin_ids = {rule.id for rule in BUILTIN_RULES}

    assert builtin_ids == set(_EXPECTED_BUILTIN_IDS)
    assert "TSWAP-C999" not in builtin_ids

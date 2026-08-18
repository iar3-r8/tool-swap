"""Validator skeleton: a rule registry that reports every finding at once.

M1 behaviour 11 (``plans/m1-configuration.md`` §1): validation is a set of
rules over the resolved config, and ``validate_config`` runs **every**
registered rule, aggregates **all** diagnostics into ONE ``ConfigReport``
(never stopping at the first error), and serves them in the behaviour-2
``(file, line or 0, code)`` order.  A rule whose ``check`` raises is caught
and reported as a single internal diagnostic instead of crashing the whole
command.  This behaviour ships the SKELETON only — the registry starts empty;
behaviours 12-19 register the real ``§6`` rules, which M5 *moves* into
preflight rather than reimplementing (guardrail 13).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from tool_swap.config.errors import (
    ConfigReport,
    Diagnostic,
    Location,
    Severity,
)
from tool_swap.config.resolver import ResolvedTool

#: Diagnostic code format; a rule id IS the code its diagnostics carry
#: (mirrors :class:`~tool_swap.config.errors.Diagnostic`).
_CODE_PATTERN: Final[re.Pattern[str]] = re.compile(r"TSWAP-[CS]\d{3}")

#: Internal diagnostic emitted when a rule's ``check`` raises (behaviour 11).
_INTERNAL_RULE_CODE: Final[str] = "TSWAP-C999"

#: Location of the internal diagnostic: the config file as a whole.
_INTERNAL_REMEDY: Final[str] = (
    "Re-run tool-swap after fixing the validator rule, or file a bug naming "
    "the failing rule id; the config itself may still be valid."
)


class _RuleRegistry:
    """The live module-level rule registry (``RULES``).

    A single mutable object, mutated in place by :func:`register` and
    :func:`unregister_all`, so every reference to the module-global
    ``RULES`` — including names captured earlier by ``from ... import
    RULES`` — always observes the current contents.  Compares equal to a
    tuple exactly when its contents equal that tuple (in both comparison
    directions).
    """

    def __init__(self) -> None:
        """Start with no rules registered."""
        self._rules: list[Rule] = []

    def __eq__(self, other: object) -> bool:
        """Compare against a tuple of rules by contents, in order.

        Args:
            other: the object to compare against.

        Returns:
            True when ``other`` is a sequence of the same rules in the
            same order; NotImplemented otherwise.
        """
        if not isinstance(other, Sequence) or isinstance(other, (str, bytes)):
            return NotImplemented
        return tuple(self._rules) == tuple(other)

    def __iter__(self) -> Iterator[Rule]:
        """Yield the registered rules in registration order."""
        return iter(self._rules)

    def __len__(self) -> int:
        """Return the number of registered rules."""
        return len(self._rules)

    def __bool__(self) -> bool:
        """True iff at least one rule is registered."""
        return bool(self._rules)

    def __repr__(self) -> str:
        """Render as the tuple of the registered rules."""
        return f"({', '.join(repr(rule) for rule in self._rules)})"


@dataclass(frozen=True)
class Rule:
    """One validation rule over a :class:`ValidatedConfig`.

    A rule is a registered object with an ``id`` (which IS its diagnostic
    code), a mandatory non-empty ``remedy``, a default ``severity``, and a
    ``check`` method.  This is deliberately the shape M5's preflight
    ``Check`` protocol uses, so M5 *moves* these rules instead of
    reimplementing them (guardrail 13).  Field order is pinned so
    subclasses may add trailing defaulted fields.

    Attributes:
        id: Diagnostic code matching ``TSWAP-[CS]\\d{3}``.
        remedy: The rule's default remedy text; mandatory, non-empty.
        severity: The rule's default severity (``Severity.ERROR``).
    """

    id: str
    remedy: str
    severity: Severity = Severity.ERROR

    def __post_init__(self) -> None:
        """Validate the ``id`` code format and mandatory ``remedy``.

        Raises:
            ValueError: if ``id`` does not match ``TSWAP-[CS]\\d{3}`` or
                ``remedy`` is empty or whitespace-only.
        """
        if _CODE_PATTERN.fullmatch(self.id) is None:
            raise ValueError(
                "Rule id must match pattern 'TSWAP-[CS]\\d{3}' "
                f"(a code starting with 'TSWAP-'); got {self.id!r}"
            )
        if not self.remedy.strip():
            raise ValueError("Rule 'remedy' must be a non-empty string.")

    def check(self, config: ValidatedConfig) -> list[Diagnostic]:
        """Run the rule; the base implementation finds nothing.

        Args:
            config: the validated configuration to check.

        Returns:
            The diagnostics this rule found (``[]`` by default).
        """
        del config
        return []


def _no_line(_path: str) -> int | None:
    """Default ``line_for``: no line information is available."""
    return None


@dataclass(frozen=True)
class ValidatedConfig:
    """The resolved configuration a rule's ``check`` is run against.

    Frozen and constructible directly (no loader, no filesystem), so tests
    can build fakes.  ``validate_config`` must not mutate it or its nested
    data.

    Attributes:
        tools: name -> :class:`~tool_swap.config.resolver.ResolvedTool`.
        raw: the raw root YAML mapping.
        line_for: maps a dotted YAML path to a 1-based source line or
            ``None``.
        path: the config file path.
    """

    tools: dict[str, ResolvedTool]
    raw: dict[str, object]
    line_for: Callable[[str], int | None] = field(default=_no_line, kw_only=True)
    path: Path = field(default=Path("tools.yaml"), kw_only=True)


#: The module-level registry of rules.  A single live object (not a
#: rebindable tuple): ``register`` / :func:`unregister_all` mutate it in
#: place, so ``from tool_swap.config.validate import RULES`` always
#: reflects the current contents; it compares equal to a tuple of the
#: registered rules.
RULES: Final[_RuleRegistry] = _RuleRegistry()


def register(rule: Rule) -> None:
    """Register a rule; a duplicate id is rejected.

    Args:
        rule: the rule to append to the registry.

    Raises:
        ValueError: if ``rule.id`` is already registered; the registry is
            left unchanged.
    """
    if rule.id in (r.id for r in RULES):
        raise ValueError(
            f"Rule with id {rule.id!r} is already registered; "
            "each rule id may be registered only once."
        )
    RULES._rules.append(rule)


def registered_rule_ids() -> list[str]:
    """Return the registered rule ids in registration order.

    Returns:
        A fresh list of the rule ids; mutating the result does not mutate
        the registry.
    """
    return [rule.id for rule in RULES]


def unregister_all() -> None:
    """Clear the registry in place (deterministic test isolation)."""
    RULES._rules.clear()


def _internal_diagnostic(
    rule: Rule, exception: Exception, config: ValidatedConfig
) -> Diagnostic:
    """Build the one internal diagnostic for a rule whose ``check`` raised.

    Args:
        rule: the failing rule (its id is named in the message).
        exception: the exception the rule raised (its text is named).
        config: the config being validated (its path is the location).

    Returns:
        A ``TSWAP-C999`` ERROR diagnostic with a non-empty remedy.
    """
    return Diagnostic(
        code=_INTERNAL_RULE_CODE,
        severity=Severity.ERROR,
        message=(
            f"Validator rule {rule.id} raised {type(exception).__name__}: "
            f"{exception}; its findings may be incomplete."
        ),
        location=Location(file=str(config.path)),
        remedy=_INTERNAL_REMEDY,
    )


def validate_config(config: ValidatedConfig) -> ConfigReport:
    """Run every registered rule and aggregate all findings in one report.

    Pure with respect to its input: no filesystem, no clock, no
    environment reads, and no mutation of ``config`` or its nested data.
    Runs **every** rule (never stopping at the first error); a rule whose
    ``check`` raises an unexpected exception is caught and reported as one
    internal ``TSWAP-C999`` diagnostic, while the other rules' diagnostics
    are still present.  Registration order does not affect the outcome:
    the report's diagnostics are passed pre-sorted in the behaviour-2
    ``(file, line or 0, code)`` order.

    Args:
        config: the validated configuration to run the rules against.

    Returns:
        One :class:`~tool_swap.config.errors.ConfigReport` holding every
        diagnostic; an empty (ok, exit code 0) report when no rules are
        registered or none find anything.
    """
    diagnostics: list[Diagnostic] = []
    for rule in RULES:
        try:
            diagnostics.extend(rule.check(config))
        except Exception as exception:
            diagnostics.append(_internal_diagnostic(rule, exception, config))
    return ConfigReport(diagnostics=tuple(sorted(diagnostics)))

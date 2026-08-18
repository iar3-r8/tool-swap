"""Validator skeleton: a rule registry that reports every finding at once.

M1 behaviour 11 (``plans/m1-configuration.md`` §1): validation is a set of
rules over the resolved config, and ``validate_config`` runs **every**
registered rule, aggregates **all** diagnostics into ONE ``ConfigReport``
(never stopping at the first error), and serves them in the behaviour-2
``(file, line or 0, code)`` order.  A rule whose ``check`` raises is caught
and reported as a single internal diagnostic instead of crashing the whole
command.  Behaviour 12 lands the name and group rules (``TSWAP-C210`` …
``TSWAP-C223``) as the first entries of ``BUILTIN_RULES``; behaviours 13-19
add the rest of the real ``§6`` rules, which M5 *moves* into preflight
rather than reimplementing (guardrail 13).  Importing this module still
registers nothing (behaviour 11a, Option B).
"""

from __future__ import annotations

import copy
import re
import string
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final

from tool_swap.config.errors import (
    ConfigReport,
    Diagnostic,
    Location,
    Severity,
)
from tool_swap.config.resolver import ResolvedTool
from tool_swap.config.schema import GroupConfig
from tool_swap.config.suggest import nearest_alternative

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


# ---------------------------------------------------------------------------
# Behaviour 12 — names, duplicates and group references (§6 rules 2, 3)
# ---------------------------------------------------------------------------

#: The pinned C210 reason phrase (plan, behaviour 12).
_URLS_REASON: Final[str] = "used in URLs, container names and log directory names"

#: A valid tool name: a lowercase letter or digit first, then a run of
#: lowercase letters, digits, ``_`` and ``-`` (TSWAP-C210).
_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"[a-z0-9][a-z0-9_-]*")

#: Every character a tool name may contain.
_ALLOWED_NAME_CHARS: Final[frozenset[str]] = frozenset(
    string.ascii_lowercase + string.digits + "_-"
)

#: The group a tool resolves to when its ``group`` entry is absent.
_DEFAULT_GROUP: Final[str] = "default"

#: The synthesized ``default`` group used when ``groups:`` is absent; the
#: values are read from :class:`~tool_swap.config.schema.GroupConfig`'s
#: field defaults so the synthesis cannot drift from the schema.
_SYNTHESISED_DEFAULT_GROUP: Final[dict[str, int | str]] = {
    "max_resident": int(GroupConfig.model_fields["max_resident"].default),
    "eviction": str(GroupConfig.model_fields["eviction"].default),
}

#: The legal ``groups.*.eviction`` values (TSWAP-C222).
_VALID_EVICTIONS: Final[tuple[str, ...]] = ("lru", "lifo", "none")


def effective_groups(raw: dict[str, object]) -> dict[str, dict[str, object]]:
    """The groups block a rule should check against (behaviour 12).

    Pure helper: no mutation of ``raw``.  When ``raw`` has no
    ``"groups"`` key at all it returns the synthesized
    ``{"default": {"max_resident": 4, "eviction": "lru"}}`` (the
    five-line config works, and the values match
    :class:`~tool_swap.config.schema.GroupConfig`'s field defaults);
    when ``"groups"`` IS present it returns that block deep-copied and
    otherwise unchanged — never inserting a ``default`` entry into a
    hand-written block, since silently synthesising there would hide a
    typo.

    Args:
        raw: the raw root YAML mapping.

    Returns:
        The effective ``groups`` mapping (a fresh copy, safe to mutate).
    """
    if "groups" not in raw:
        return {_DEFAULT_GROUP: dict(_SYNTHESISED_DEFAULT_GROUP)}
    block = raw["groups"]
    if not isinstance(block, dict):
        return {}
    return copy.deepcopy(block)


def _effective_group(tool: ResolvedTool) -> str | None:
    """The group a tool references, or ``None`` for a non-string value.

    A tool with no ``group`` entry resolves to the implicit
    ``default`` group; a non-string value is a schema-level problem and
    is left to other rules.

    Args:
        tool: the resolved tool whose ``group`` entry is read.

    Returns:
        The referenced group name, or ``None`` when the value is not a
        string.
    """
    group = tool.values.get("group", _DEFAULT_GROUP)
    return group if isinstance(group, str) else None


class _C210Rule(Rule):
    """``TSWAP-C210``: a tool name outside ``^[a-z0-9][a-z0-9_-]*$``."""

    def check(self, config: ValidatedConfig) -> list[Diagnostic]:
        """Flag every tool whose effective name breaks the charset.

        Args:
            config: the validated configuration to check.

        Returns:
            One diagnostic per offending name, naming the tool, every
            offending character and the pinned reason phrase.
        """
        findings: list[Diagnostic] = []
        for key, tool in config.tools.items():
            name = tool.name
            if _NAME_PATTERN.fullmatch(name) is not None:
                continue
            if name:
                offending = sorted(
                    {
                        char
                        for index, char in enumerate(name)
                        if (
                            char not in _ALLOWED_NAME_CHARS
                            or (index == 0 and char in "_-")
                        )
                    }
                )
                chars = ", ".join(repr(char) for char in offending)
                message = (
                    f"Tool {name!r} is not a valid tool name (it must "
                    f"match ^[a-z0-9][a-z0-9_-]*$); offending "
                    f"character(s): {chars}. Tool names are "
                    f"{_URLS_REASON}."
                )
            else:
                message = (
                    "A tool with an empty name is invalid: a name must "
                    f"match ^[a-z0-9][a-z0-9_-]*$. Tool names are "
                    f"{_URLS_REASON}."
                )
            yaml_path = f"tools.{key}"
            findings.append(
                Diagnostic(
                    code=self.id,
                    severity=self.severity,
                    message=message,
                    location=Location(
                        file=str(config.path),
                        yaml_path=yaml_path,
                        line=config.line_for(yaml_path),
                    ),
                    remedy=self.remedy,
                )
            )
        return findings


class _C211Rule(Rule):
    """``TSWAP-C211``: two or more tools resolve to the same name."""

    def check(self, config: ValidatedConfig) -> list[Diagnostic]:
        """Flag every effective name claimed by more than one entry.

        This is the behaviour-12 duplicate: a duplicate arising across
        layers or after ``tool.yaml`` name resolution (distinct from the
        behaviour-6 duplicate-YAML-key loader error).

        Args:
            config: the validated configuration to check.

        Returns:
            One diagnostic per duplicated name, naming every entry that
            resolves to it.
        """
        by_name: dict[str, list[str]] = {}
        for key, tool in config.tools.items():
            by_name.setdefault(tool.name, []).append(key)
        findings: list[Diagnostic] = []
        for effective_name, keys in by_name.items():
            if len(keys) < 2:
                continue
            entries = ", ".join(repr(key) for key in keys)
            message = (
                f"Tool {effective_name!r} is defined more than once: "
                f"entries {entries} all resolve to the same name."
            )
            findings.append(
                Diagnostic(
                    code=self.id,
                    severity=self.severity,
                    message=message,
                    location=Location(
                        file=str(config.path),
                        yaml_path="tools",
                        line=config.line_for("tools"),
                    ),
                    remedy=self.remedy,
                )
            )
        return findings


class _C220Rule(Rule):
    """``TSWAP-C220``: a tool references a group absent from ``groups:``."""

    def check(self, config: ValidatedConfig) -> list[Diagnostic]:
        """Flag every tool whose group is not defined.

        Args:
            config: the validated configuration to check.

        Returns:
            One diagnostic per dangling reference, naming the group, the
            tool, the nearest existing group (via
            :func:`~tool_swap.config.suggest.nearest_alternative`) and
            the full list of defined groups.
        """
        groups = effective_groups(config.raw)
        findings: list[Diagnostic] = []
        for key, tool in config.tools.items():
            group = _effective_group(tool)
            if group is None or group in groups:
                continue
            defined = ", ".join(repr(name) for name in sorted(groups))
            message = (
                f"Tool {key!r} references group {group!r}, which is not "
                f"defined in 'groups:' (defined groups: {defined})"
            )
            nearest = nearest_alternative(group, sorted(groups))
            if nearest is not None:
                message += f"; did you mean {nearest!r}?"
            yaml_path = f"tools.{key}"
            findings.append(
                Diagnostic(
                    code=self.id,
                    severity=self.severity,
                    message=message,
                    location=Location(
                        file=str(config.path),
                        yaml_path=yaml_path,
                        line=config.line_for(yaml_path),
                    ),
                    remedy=self.remedy,
                )
            )
        return findings


class _C221Rule(Rule):
    """``TSWAP-C221``: ``groups.*.max_resident`` below 1."""

    def check(self, config: ValidatedConfig) -> list[Diagnostic]:
        """Flag every group whose ``max_resident`` is below 1.

        Args:
            config: the validated configuration to check.

        Returns:
            One diagnostic per offending group, naming the group and the
            value.
        """
        groups = effective_groups(config.raw)
        findings: list[Diagnostic] = []
        for group_name, block in groups.items():
            if not isinstance(block, dict):
                continue
            value = block.get("max_resident")
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            if value >= 1:
                continue
            message = (
                f"Group {group_name!r} has max_resident {value}, which "
                "must be at least 1."
            )
            yaml_path = f"groups.{group_name}.max_resident"
            findings.append(
                Diagnostic(
                    code=self.id,
                    severity=self.severity,
                    message=message,
                    location=Location(
                        file=str(config.path),
                        yaml_path=yaml_path,
                        line=config.line_for(yaml_path),
                    ),
                    remedy=self.remedy,
                )
            )
        return findings


class _C222Rule(Rule):
    """``TSWAP-C222``: ``groups.*.eviction`` outside the valid set."""

    def check(self, config: ValidatedConfig) -> list[Diagnostic]:
        """Flag every group whose ``eviction`` is not a valid value.

        Args:
            config: the validated configuration to check.

        Returns:
            One diagnostic per offending group, naming the value and
            listing the valid values.
        """
        groups = effective_groups(config.raw)
        findings: list[Diagnostic] = []
        for group_name, block in groups.items():
            if not isinstance(block, dict):
                continue
            value = block.get("eviction")
            if not isinstance(value, str) or value in _VALID_EVICTIONS:
                continue
            valid = ", ".join(_VALID_EVICTIONS)
            message = (
                f"Group {group_name!r} has eviction {value!r}, which is "
                f"not one of: {valid}."
            )
            yaml_path = f"groups.{group_name}.eviction"
            findings.append(
                Diagnostic(
                    code=self.id,
                    severity=self.severity,
                    message=message,
                    location=Location(
                        file=str(config.path),
                        yaml_path=yaml_path,
                        line=config.line_for(yaml_path),
                    ),
                    remedy=self.remedy,
                )
            )
        return findings


class _C223Rule(Rule):
    """``TSWAP-C223``: a group defined but referenced by no tool."""

    def check(self, config: ValidatedConfig) -> list[Diagnostic]:
        """Warn about defined groups no tool references (probably a rename).

        A tool "references" a group when its resolved ``group`` equals
        the group name, or when it has no ``group`` entry at all (meaning
        ``default``).  The warning is a single diagnostic naming every
        orphan; it is suppressed when NO defined group is referenced at
        all (a hand-written block omitting ``default`` is a C220 typo
        scenario, not a rename signal).

        Args:
            config: the validated configuration to check.

        Returns:
            At most one WARNING diagnostic naming the orphan groups.
        """
        groups = effective_groups(config.raw)
        referenced: set[str] = set()
        for tool in config.tools.values():
            group = _effective_group(tool)
            if group is not None:
                referenced.add(group)
        if not referenced.intersection(groups):
            return []
        orphans = sorted(group for group in groups if group not in referenced)
        if not orphans:
            return []
        names = ", ".join(repr(group) for group in orphans)
        message = (
            f"Group(s) defined but referenced by no tool: {names}; probably a rename."
        )
        return [
            Diagnostic(
                code=self.id,
                severity=self.severity,
                message=message,
                location=Location(
                    file=str(config.path),
                    yaml_path="groups",
                    line=config.line_for("groups"),
                ),
                remedy=self.remedy,
            )
        ]


#: ``TSWAP-C210`` — tool name outside the allowed charset (§6 rule 2).
TSWAP_C210_RULE: Final[Rule] = _C210Rule(
    id="TSWAP-C210",
    remedy=(
        "Rename the tool to match ^[a-z0-9][a-z0-9_-]*$: start with a "
        "lowercase letter or digit, then lowercase letters, digits, '_' "
        "and '-' only."
    ),
)

#: ``TSWAP-C211`` — duplicate tool names (§6 rule 2).
TSWAP_C211_RULE: Final[Rule] = _C211Rule(
    id="TSWAP-C211",
    remedy=(
        "Give each tool a unique name: a name may resolve to at most one "
        "tool, across every config layer."
    ),
)

#: ``TSWAP-C220`` — a tool references a group absent from ``groups:``.
TSWAP_C220_RULE: Final[Rule] = _C220Rule(
    id="TSWAP-C220",
    remedy=(
        "Either define the group under 'groups:' or point the tool's "
        "'group' field at an existing one (or drop it to use 'default')."
    ),
)

#: ``TSWAP-C221`` — ``groups.*.max_resident`` below 1.
TSWAP_C221_RULE: Final[Rule] = _C221Rule(
    id="TSWAP-C221",
    remedy=(
        "Set the group's max_resident to 1 or higher; a group must be "
        "able to hold at least one tool."
    ),
)

#: ``TSWAP-C222`` — ``groups.*.eviction`` outside the valid set.
TSWAP_C222_RULE: Final[Rule] = _C222Rule(
    id="TSWAP-C222",
    remedy="Set the group's eviction to one of: lru, lifo or none.",
)

#: ``TSWAP-C223`` — a group defined but referenced by no tool (WARNING).
TSWAP_C223_RULE: Final[Rule] = _C223Rule(
    id="TSWAP-C223",
    severity=Severity.WARNING,
    remedy=(
        "If the group is still needed, point at least one tool's "
        "'group' field at it; otherwise remove it from 'groups:'."
    ),
)

# ---------------------------------------------------------------------------
# Behaviour 13 — D19 mandatory descriptions (§6 rule 6b)
# ---------------------------------------------------------------------------

#: The pinned C300 WHY phrase (plan, behaviour 13).
_C300_WHY: Final[str] = (
    "the description is what an LLM agent reads to decide whether to call this tool"
)

#: The self-sufficient remedy direction shared by the C3xx rules (the
#: ``ValidatedConfig`` carries no per-tool ``tool.yaml`` path, so the
#: remedy must not pretend to know which file was authored).
_C3XX_REMEDY_TARGET: Final[str] = (
    "add it to the tool's 'tool.yaml', or its inline 'tools.<name>' entry"
)


def _is_blank(value: object) -> bool:
    """Whether a description value counts as missing (plan, behaviour 13).

    Missing is ``None`` or a ``str`` whose ``strip()`` is empty; any
    non-string value (e.g. ``description: 123``) counts as PRESENT and is
    left to the schema layer's ``TSWAP-C105``, so one mistake yields one
    diagnostic rather than two.

    Args:
        value: the description value from a carrier field or entry.

    Returns:
        True when the value is missing (``None`` or blank string).
    """
    return value is None or (isinstance(value, str) and value.strip() == "")


def _entry_label(entry: Mapping[str, object], block: str, index: int) -> str:
    """The name an entry carries in a C301/C302/C303 message.

    The entry's ``name`` is used when it is a non-empty string; otherwise
    the entry is named positionally (``inputs[<i>]`` and friends) so the
    message stays actionable.

    Args:
        entry: the mapping entry being checked.
        block: the block name (``inputs`` / ``outputs`` / ``params``).
        index: the 0-based position of the entry in the block.

    Returns:
        The entry's name, or its positional label.
    """
    name = entry.get("name")
    if isinstance(name, str) and name.strip():
        return name
    return f"{block}[{index}]"


def _tool_location(config: ValidatedConfig, yaml_path: str) -> Location:
    """The behaviour-12 location form for a tool-level diagnostic.

    Args:
        config: the validated configuration.
        yaml_path: the dotted YAML path; the same string is handed to
            ``config.line_for`` (``line=None`` is a legal outcome).

    Returns:
        The :class:`~tool_swap.config.errors.Location` at that path.
    """
    return Location(
        file=str(config.path),
        yaml_path=yaml_path,
        line=config.line_for(yaml_path),
    )


def _check_entry_descriptions(
    rule: Rule,
    config: ValidatedConfig,
    tool_key: str,
    block: str,
    block_value: object,
) -> list[Diagnostic]:
    """One missing/blank ``description`` diagnostic per block entry.

    Shared by C301/C302/C303.  A block whose value is not a list is
    skipped silently, and a non-mapping entry is skipped silently:
    malformed shapes belong to behaviour 20's ``TSWAP-S1xx``.

    Args:
        rule: the emitting rule (its ``id`` and ``severity`` are used).
        config: the validated configuration.
        tool_key: the ``tools:`` map key of the tool.
        block: the block name (``inputs`` / ``outputs`` / ``params``),
            used in the positional entry label.
        block_value: the block's carrier value (``None`` or a list).

    Returns:
        The diagnostics, one per missing or blank entry description.
    """
    if not isinstance(block_value, list):
        return []
    findings: list[Diagnostic] = []
    for index, entry in enumerate(block_value):
        if not isinstance(entry, Mapping):
            continue
        if not _is_blank(entry.get("description")):
            continue
        label = _entry_label(entry, block, index)
        yaml_path = f"tools.{tool_key}.{block}.{index}.description"
        findings.append(
            Diagnostic(
                code=rule.id,
                severity=rule.severity,
                message=(
                    f"Entry {label!r} in the tool's '{block}' block is "
                    "missing a description."
                ),
                location=_tool_location(config, yaml_path),
                remedy=rule.remedy,
            )
        )
    return findings


class _C300Rule(Rule):
    """``TSWAP-C300``: a tool whose own description is missing or blank."""

    def check(self, config: ValidatedConfig) -> list[Diagnostic]:
        """Flag every tool whose ``description`` carrier is missing/blank.

        Applies to **every** tool — there is no escape — and reads only
        the carrier field (no filesystem, no loader, no ``raw`` parsing).

        Args:
            config: the validated configuration to check.

        Returns:
            One ERROR diagnostic per undescribed tool, stating the pinned
            WHY phrase and naming the key to add in the remedy.
        """
        findings: list[Diagnostic] = []
        for key, tool in config.tools.items():
            if not _is_blank(tool.description):
                continue
            yaml_path = f"tools.{key}"
            findings.append(
                Diagnostic(
                    code=self.id,
                    severity=self.severity,
                    message=(f"Tool {key!r} is missing a description: {_C300_WHY}."),
                    location=_tool_location(config, yaml_path),
                    remedy=self.remedy,
                )
            )
        return findings


class _C301Rule(Rule):
    """``TSWAP-C301``: an ``inputs:`` entry missing its description."""

    def check(self, config: ValidatedConfig) -> list[Diagnostic]:
        """Flag every ``inputs`` entry whose description is missing/blank.

        Absent (``None``) or empty (``[]``) blocks yield nothing; entries
        that are not mappings are skipped silently.

        Args:
            config: the validated configuration to check.

        Returns:
            One ERROR diagnostic per undescribed input entry.
        """
        findings: list[Diagnostic] = []
        for key, tool in config.tools.items():
            findings.extend(
                _check_entry_descriptions(self, config, key, "inputs", tool.inputs)
            )
        return findings


class _C302Rule(Rule):
    """``TSWAP-C302``: an ``outputs:`` entry missing its description."""

    def check(self, config: ValidatedConfig) -> list[Diagnostic]:
        """Flag every ``outputs`` entry whose description is missing/blank.

        Absent (``None``) or empty (``[]``) blocks yield nothing; entries
        that are not mappings are skipped silently.

        Args:
            config: the validated configuration to check.

        Returns:
            One WARNING diagnostic per undescribed output entry.
        """
        findings: list[Diagnostic] = []
        for key, tool in config.tools.items():
            findings.extend(
                _check_entry_descriptions(self, config, key, "outputs", tool.outputs)
            )
        return findings


class _C303Rule(Rule):
    """``TSWAP-C303``: a ``params:`` entry missing its description."""

    def check(self, config: ValidatedConfig) -> list[Diagnostic]:
        """Flag every ``params`` entry whose description is missing/blank.

        §5.5.1 requires ``name``, ``type`` and ``description`` on every
        param.  Absent (``None``) or empty (``[]``) blocks yield nothing;
        entries that are not mappings are skipped silently.

        Args:
            config: the validated configuration to check.

        Returns:
            One ERROR diagnostic per undescribed param entry.
        """
        findings: list[Diagnostic] = []
        for key, tool in config.tools.items():
            findings.extend(
                _check_entry_descriptions(self, config, key, "params", tool.params)
            )
        return findings


#: ``TSWAP-C300`` — a tool's own description is missing or blank (§6 rule 6b).
TSWAP_C300_RULE: Final[Rule] = _C300Rule(
    id="TSWAP-C300",
    remedy=(
        "Add a non-blank 'description' field for the tool — "
        + _C3XX_REMEDY_TARGET
        + "."
    ),
)

#: ``TSWAP-C301`` — an ``inputs:`` entry is missing its description.
TSWAP_C301_RULE: Final[Rule] = _C301Rule(
    id="TSWAP-C301",
    remedy=(
        "Add a non-blank 'description' to the input entry — "
        + _C3XX_REMEDY_TARGET
        + "."
    ),
)

#: ``TSWAP-C302`` — an ``outputs:`` entry is missing its description
#: (WARNING; outputs are advisory, unlike inputs and params).
TSWAP_C302_RULE: Final[Rule] = _C302Rule(
    id="TSWAP-C302",
    severity=Severity.WARNING,
    remedy=(
        "Add a non-blank 'description' to the output entry — "
        + _C3XX_REMEDY_TARGET
        + "."
    ),
)

#: ``TSWAP-C303`` — a ``params:`` entry is missing its description.
TSWAP_C303_RULE: Final[Rule] = _C303Rule(
    id="TSWAP-C303",
    remedy=(
        "Add a non-blank 'description' to the param entry — "
        + _C3XX_REMEDY_TARGET
        + "."
    ),
)


#: The codes ``--allow-missing-descriptions`` downgrades (plan block 6):
#: the three ERROR description codes.  ``TSWAP-C302`` is deliberately
#: excluded — it is already a warning, and appending "downgraded by" to a
#: diagnostic the flag did not change would be a lie.
MISSING_DESCRIPTION_CODES: Final[frozenset[str]] = frozenset(
    {"TSWAP-C300", "TSWAP-C301", "TSWAP-C303"}
)

#: The pinned downgrade banner, appended to each downgraded diagnostic's
#: ``message`` (which is what makes it survive ``--json``).
ALLOW_MISSING_DESCRIPTIONS_BANNER: Final[str] = (
    "downgraded by --allow-missing-descriptions; this flag is for local "
    "prototyping and is never permitted in CI"
)

#: Every rule M1 ships, in code order (behaviour 11a): the single list
#: M5 moves into preflight.  Behaviours 13-19 append their rules here,
#: in code order, as they land.
BUILTIN_RULES: Final[tuple[Rule, ...]] = (
    TSWAP_C210_RULE,
    TSWAP_C211_RULE,
    TSWAP_C220_RULE,
    TSWAP_C221_RULE,
    TSWAP_C222_RULE,
    TSWAP_C223_RULE,
    TSWAP_C300_RULE,
    TSWAP_C301_RULE,
    TSWAP_C302_RULE,
    TSWAP_C303_RULE,
)


def register_builtin_rules() -> None:
    """Register every rule in :data:`BUILTIN_RULES` (idempotent).

    A rule already registered *as the same object* is skipped, so a
    second call is a silent no-op and never duplicates ids; a rule id
    registered by a *different* object still raises ``ValueError``
    through :func:`register`, so the duplicate-id guard is preserved
    rather than weakened.  This is the one call site the CLI (behaviour
    21) and the test suite reach; importing this module still registers
    nothing.

    Raises:
        ValueError: if a rule id is claimed by a different object.
    """
    registered_by_id: dict[str, Rule] = {rule.id: rule for rule in RULES}
    for rule in BUILTIN_RULES:
        if registered_by_id.get(rule.id) is rule:
            continue
        register(rule)


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


def downgrade_missing_descriptions(report: ConfigReport) -> ConfigReport:
    """Downgrade the missing-description diagnostics of a report.

    The ``--allow-missing-descriptions`` post-processor (plan block 6,
    mechanism (a)): the rules always emit their documented severities and
    this pure function rewrites the report, so it is unit-testable before
    the CLI (behaviour 21) exists.

    Every diagnostic whose code is in :data:`MISSING_DESCRIPTION_CODES`
    (``C300``, ``C301``, ``C303`` — but never ``C302``, which is already a
    warning) is returned with severity :attr:`Severity.WARNING` and the
    pinned banner appended to its ``message`` as
    ``f"{original} — {ALLOW_MISSING_DESCRIPTIONS_BANNER}"``, so the banner
    is part of the diagnostic and survives ``--json``.  Every other
    diagnostic passes through untouched and the input report is not
    mutated.

    Idempotent: a diagnostic already carrying the banner is returned
    unchanged, so a double call (e.g. a CLI refactor calling this twice)
    yields the same report.  ``--strict`` + ``--allow-missing-descriptions``
    is contradictory and ``--strict`` wins: the downgrade runs first, then
    ``--strict`` promotes warnings back to errors.

    Args:
        report: the report to downgrade (never mutated).

    Returns:
        A NEW :class:`~tool_swap.config.errors.ConfigReport` with the
        rewritten diagnostics in the original order.
    """
    new_diagnostics: list[Diagnostic] = []
    for diagnostic in report.diagnostics:
        if diagnostic.code not in MISSING_DESCRIPTION_CODES:
            new_diagnostics.append(diagnostic)
            continue
        if ALLOW_MISSING_DESCRIPTIONS_BANNER in diagnostic.message:
            new_diagnostics.append(replace(diagnostic, severity=Severity.WARNING))
            continue
        new_diagnostics.append(
            replace(
                diagnostic,
                severity=Severity.WARNING,
                message=(f"{diagnostic.message} — {ALLOW_MISSING_DESCRIPTIONS_BANNER}"),
            )
        )
    return ConfigReport(diagnostics=tuple(new_diagnostics))

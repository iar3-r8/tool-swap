"""Tests for M1 behaviour 15 — image source, handler and file existence.

See ``plans/m1-configuration.md`` behaviour 15 (lines 646-658) and its
"Confirmed contract details (2026-08-18)" block (items 0-10, lines
660-888).  This file is the executable form of that contract: the seven
rule constants (``TSWAP_C510_RULE`` … ``TSWAP_C516_RULE``), the
``FileProbe`` dataclass, ``REAL_FILESYSTEM`` and the five trailing
``ResolvedTool`` carrier fields (``image``, ``handler``,
``requirements``, ``build``, ``base_dir``) do not exist yet in
``src/tool_swap/config/validate.py`` (behaviour 14 shipped the C4xx rules
and the 16-rule ``BUILTIN_RULES`` only).  This module therefore fails
collection with a single clean ``ImportError`` naming exactly one
missing name:

    ImportError: cannot import name 'FileProbe'
        from 'tool_swap.config.validate'

(``FileProbe`` is the first missing name in the import list; Python
reports the first one it fails on.)  Every test body below pins a
concrete behaviour the GREEN step must satisfy, so the assertions — not
just the import — are the contract.

Pinned public API (the names the GREEN step must add):

- ``FileProbe`` — a frozen dataclass with two fields, both defaulted to
  the REAL filesystem predicates (``Path.is_file`` / ``Path.is_dir``
  semantics, ``OSError`` swallowed to ``False``): a no-arg
  ``FileProbe()`` IS the real filesystem.  Tests inject dict-backed
  fakes to stay hermetic; exactly ONE test (the static-only test) uses
  the real probe with a real ``tmp_path``.
- ``REAL_FILESYSTEM`` — the module-level ``FileProbe()`` singleton used
  as ``ValidatedConfig``'s default (the ``probe`` field is trailing,
  keyword-only, defaulted, so behaviour 11's ``ValidatedConfig`` pins
  stay green and are not amended).
- ``TSWAP_C510_RULE`` … ``TSWAP_C516_RULE`` — all ``Severity.ERROR``
  except ``TSWAP_C516_RULE`` which is ``Severity.WARNING`` (the escape
  is allowed); non-empty remedies; appended to ``BUILTIN_RULES`` in code
  order after the six C4xx rules (23 landed rules in total).

The rules read ONLY ``ResolvedTool`` carrier fields and the probe
carried on ``ValidatedConfig`` (``config.probe``), plus ``config.path``
and ``config.line_for`` for the location.  Every byte of disk knowledge
arrives through the probe; every path is computed LEXICALLY (normpath
semantics, never ``Path.resolve()``); the resolution base is
``tool.base_dir`` if set, else ``config.path.parent``.  The handler is
never imported — a structural fact, pinned by the ``sys.modules``
snapshot test against a real file.

Conventions mirror ``tests/unit/config/test_validate_reserved.py``:
pytest, AAA, snake_case, Google docstrings, an autouse fixture calling
``unregister_all()`` before AND after every test (the registry is shared
module state), the C5xx rules registered explicitly per test.  No
``importlib.reload`` anywhere.  Every test except the static-only test
uses a dict-backed fake probe — no ``tmp_path``, no disk.
"""

from __future__ import annotations

import dataclasses
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest
from tool_swap.config.errors import ConfigReport, Diagnostic, Severity
from tool_swap.config.origin import OriginMap
from tool_swap.config.resolver import ResolvedTool
from tool_swap.config.validate import (  # noqa: E501  (names absent in RED step)
    FileProbe,
    REAL_FILESYSTEM,
    TSWAP_C510_RULE,
    TSWAP_C511_RULE,
    TSWAP_C512_RULE,
    TSWAP_C513_RULE,
    TSWAP_C514_RULE,
    TSWAP_C515_RULE,
    TSWAP_C516_RULE,
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

#: The six behaviour-12 rule ids (§6 rules 2 and 3), in code order — the
#: block immediately before the behaviour-13 append (mirrors
#: ``_BEHAVIOUR_12_IDS`` in ``test_validate_names_groups.py`` and
#: ``test_validate_reserved.py``).
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

#: The seven behaviour-15 rule ids (§6 rules 5 and 6), in code order.
_BEHAVIOUR_15_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C510",
    "TSWAP-C511",
    "TSWAP-C512",
    "TSWAP-C513",
    "TSWAP-C514",
    "TSWAP-C515",
    "TSWAP-C516",
)

#: The seven behaviour-15 rule constants, in code order.
_ALL_C5XX_RULES: Final[tuple[Rule, ...]] = (
    TSWAP_C510_RULE,
    TSWAP_C511_RULE,
    TSWAP_C512_RULE,
    TSWAP_C513_RULE,
    TSWAP_C514_RULE,
    TSWAP_C515_RULE,
    TSWAP_C516_RULE,
)

#: The pinned expected handler form the C512 message must show (plan
#: block 4: "The C512 message shows the expected form
#: ``file.py:ClassName`` and the value found").
_EXPECTED_HANDLER_FORM: Final[str] = "file.py:ClassName"

#: The pinned C513 directory-case phrase (plan block 6).
_DIRECTORY_NOT_FILE_PHRASE: Final[str] = "is a directory, not a file"

#: The pinned C515 mirrored phrase (plan block 6).
_FILE_NOT_DIRECTORY_PHRASE: Final[str] = "is a file, not a directory"

#: A fake tool directory used as ``base_dir`` in the resolution tests
#: (never exists on any real filesystem; the probes are fakes).
_BASE: Final[Path] = Path("/srv/tools/t1")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeProbe:
    """A dict-backed ``FileProbe`` stand-in that never touches the disk.

    Attributes:
        files: path -> is-file answer (missing keys answer ``False``).
        dirs: path -> is-dir answer (missing keys answer ``False``).
        queries: every ``(predicate, path)`` call in order, so tests can
            pin WHICH path a rule resolved to.
    """

    def __init__(
        self,
        files: dict[Path, bool] | None = None,
        dirs: dict[Path, bool] | None = None,
    ) -> None:
        """Build the fake from its two dict-backed predicate answers.

        Args:
            files: paths that answer ``True`` to ``is_file``.
            dirs: paths that answer ``True`` to ``is_dir``.
        """
        self.files = dict(files or {})
        self.dirs = dict(dirs or {})
        self.queries: list[tuple[str, Path]] = []

    def is_file(self, path: Path) -> bool:
        """Answer from the dict and record the query.

        Args:
            path: the path the rule resolved.

        Returns:
            The dict-backed answer (``False`` for unknown paths).
        """
        self.queries.append(("is_file", path))
        return self.files.get(path, False)

    def is_dir(self, path: Path) -> bool:
        """Answer from the dict and record the query.

        Args:
            path: the path the rule resolved.

        Returns:
            The dict-backed answer (``False`` for unknown paths).
        """
        self.queries.append(("is_dir", path))
        return self.dirs.get(path, False)

    def queried(self, predicate: str) -> list[Path]:
        """The paths queried by one predicate, in order.

        Args:
            predicate: ``"is_file"`` or ``"is_dir"``.

        Returns:
            The matching query paths.
        """
        return [p for pred, p in self.queries if pred == predicate]


def _tool(
    name: str,
    *,
    image: str | None = None,
    handler: str | None = None,
    requirements: str | None = None,
    build: object = None,
    base_dir: Path | None = None,
) -> ResolvedTool:
    """Build a ``ResolvedTool`` carrying behaviour-15's read surface.

    The five keyword fields are the trailing carrier fields the GREEN
    step adds to ``ResolvedTool`` (plan item 3); the tests build them
    DIRECTLY exactly as the resolver would emit them (no loader, no
    raw).  ``build`` is the as-authored build block
    (``{"context": ..., "dockerfile": ...}``), or a non-dict value for
    the robustness case.

    Args:
        name: the tool name (used as both the ``tools`` dict key and the
            ``ResolvedTool.name`` in every fixture, so the two
            namespaces agree).
        image: the ``image`` carrier; ``None`` = no layer supplied it.
        handler: the ``handler`` carrier (the post-merge picture).
        requirements: the ``requirements`` carrier.
        build: the as-authored ``build`` block, ``None``, or a non-dict
            value for the robustness case.
        base_dir: the tool directory; ``None`` = "no ``path:``", resolve
            against ``config.path.parent``.

    Returns:
        A frozen ``ResolvedTool`` with ``origins=OriginMap()`` and no
        diagnostics.
    """
    return ResolvedTool(
        name=name,
        values={},
        origins=OriginMap(),
        diagnostics=[],
        image=image,  # type: ignore[call-arg]
        handler=handler,  # type: ignore[call-arg]
        requirements=requirements,  # type: ignore[call-arg]
        build=build,  # type: ignore[call-arg]
        base_dir=base_dir,  # type: ignore[call-arg]
    )


def _config(
    tools: dict[str, ResolvedTool],
    probe: _FakeProbe,
    line_for: Callable[[str], int | None] | None = None,
    path: Path | None = None,
    raw: dict[str, object] | None = None,
) -> ValidatedConfig:
    """Build a ``ValidatedConfig`` carrying an injected fake probe.

    The C5xx rules read only the carrier fields on the tools plus
    ``config.probe`` / ``config.path`` / ``config.line_for``; the raw
    block is an inert placeholder (and a dedicated test pins that the
    rules do not consult it).

    Args:
        tools: name -> ``ResolvedTool`` (positional field).
        probe: the dict-backed fake probe (every non-static test).
        line_for: dotted YAML path -> 1-based line or ``None``; defaults
            to a ``None``-returning mapping.
        path: the config file path; defaults to ``Path("tools.yaml")``.
        raw: the raw root YAML mapping; defaults to ``{"tools": {}}``.

    Returns:
        The frozen ``ValidatedConfig``.
    """
    return ValidatedConfig(
        tools=tools,
        raw=raw if raw is not None else {"tools": {}},
        line_for=line_for if line_for is not None else (lambda _p: None),
        path=path if path is not None else Path("tools.yaml"),
        probe=probe,
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
    C5xx rules it exercises (explicitly, like the behaviour-13 and
    behaviour-14 files) and must not depend on — and must not leak —
    registration state.
    """
    unregister_all()
    try:
        yield
    finally:
        unregister_all()


# ---------------------------------------------------------------------------
# 1. The rule objects, the append order, and the probe contract
# ---------------------------------------------------------------------------


def test_rule_objects_carry_expected_ids_and_severities() -> None:
    """Each rule instance carries its id, severity, and a remedy.

    Plan block 7: "``C510``, ``C511``, ``C512``, ``C513``, ``C514``,
    ``C515`` are ``Severity.ERROR``. ``C516`` is ``Severity.WARNING``
    (plan line 657: the escape is *allowed*). Every ``remedy`` is
    non-empty."

    Arrangement: the seven rule objects imported from ``validate``.
    Action: read back ``id``, ``severity`` and ``remedy``.
    Assertion: ids are ``TSWAP-C510``…``TSWAP-C516`` in that order; the
    first six are ERROR, ``TSWAP-C516`` is WARNING, and every remedy is
    a non-empty string.
    """
    rules = _ALL_C5XX_RULES

    assert [rule.id for rule in rules] == list(_BEHAVIOUR_15_IDS)
    assert [rule.severity for rule in rules] == [
        Severity.ERROR
    ] * 6 + [Severity.WARNING]
    for rule in rules:
        assert isinstance(rule.remedy, str)
        assert rule.remedy.strip() != ""


def test_builtin_rules_append_the_behaviour_15_codes_in_code_order() -> None:
    """The seven rules are appended to ``BUILTIN_RULES`` after 14.

    Plan block 8: all seven are appended to ``BUILTIN_RULES`` in code
    order after behaviour 14's six — 23 landed rules in total — and
    their *identity* is what ``register_builtin_rules()`` relies on for
    idempotency, so the tuple must hold the very module-level
    singletons, not equal stand-ins.

    The position is asserted **relative to the earlier blocks**, not
    tail-anchored (the index-anchored pattern of behaviour 13 and the
    repaired behaviour-14 test): "the last seven ids" (or a total-count
    pin) would be false as soon as behaviour 16's rules land.

    Arrangement: the ``BUILTIN_RULES`` tuple.
    Action: locate the first behaviour-15 id; check object identity per
    rule.
    Assertion: the first C5xx id sits at index
    ``len(_BEHAVIOUR_12_IDS) + len(_BEHAVIOUR_13_IDS) +
    len(_BEHAVIOUR_14_IDS)`` (immediately after the six C4xx codes), the
    seven ids from there are a contiguous, in-code-order block, and each
    rule constant is an element of the tuple.
    """
    ids = [rule.id for rule in BUILTIN_RULES]

    first_c510 = ids.index(_BEHAVIOUR_15_IDS[0])
    assert first_c510 == (
        len(_BEHAVIOUR_12_IDS)
        + len(_BEHAVIOUR_13_IDS)
        + len(_BEHAVIOUR_14_IDS)
    )
    assert ids[first_c510 : first_c510 + len(_BEHAVIOUR_15_IDS)] == list(
        _BEHAVIOUR_15_IDS
    )
    for constant in _ALL_C5XX_RULES:
        assert any(rule is constant for rule in BUILTIN_RULES)


def test_fileprobe_is_a_frozen_dataclass_with_two_defaulted_predicates() -> (
    None
):
    """``FileProbe`` is a frozen dataclass of two defaulted predicates.

    Plan item 1: one frozen ``FileProbe`` groups the two predicates the
    rules need (a single ``exists`` cannot distinguish "absent" from
    "present but a directory" for C513, and C515 checks a directory and
    a file in one rule); both fields are defaulted so a no-arg
    ``FileProbe()`` IS the real filesystem.

    Arrangement: the dataclass and a no-arg instance.
    Action: inspect its fields; try to mutate one.
    Assertion: exactly the two fields ``is_file`` and ``is_dir``, in
    that order, both with defaults; mutation raises
    ``FrozenInstanceError``.
    """
    fields = dataclasses.fields(FileProbe)
    assert [f.name for f in fields] == ["is_file", "is_dir"]
    assert all(f.default is not dataclasses.MISSING for f in fields)

    probe = FileProbe()
    with pytest.raises(dataclasses.FrozenInstanceError):
        probe.is_file = lambda path: False  # type: ignore[misc]


def test_fileprobe_defaults_are_the_real_filesystem_semantics() -> None:
    """A no-arg ``FileProbe()`` answers like ``Path.is_file``/``is_dir``.

    Plan item 1: the defaults are the REAL filesystem predicates
    (``path.is_file()`` / ``path.is_dir()``, ``OSError`` swallowed to
    ``False``).  Pinned against a known file and its parent directory
    (this test module's own source tree — read-only, no writes): the
    default probe reports the file as file-not-dir and the parent as
    dir-not-file, exactly the discrimination C513 and C515 rely on.

    Arrangement: a no-arg ``FileProbe()`` and two real, stable paths.
    Action: ask both predicates about both paths.
    Assertion: the answers match ``Path`` semantics on both paths.
    """
    probe = FileProbe()
    this_file = Path(__file__).resolve()
    this_dir = this_file.parent

    assert probe.is_file(this_file) is True
    assert probe.is_dir(this_file) is False
    assert probe.is_file(this_dir) is False
    assert probe.is_dir(this_dir) is True


def test_real_filesystem_is_the_validated_config_default_probe() -> None:
    """``REAL_FILESYSTEM`` is the singleton a default config carries.

    Plan item 1 (refinement): the field is typed ``FileProbe``, **not**
    ``Callable | None``, and its default is the real-filesystem probe
    object rather than ``None`` — so there is no unbranched path that
    could accidentally hit the disk without going through the probe.

    Arrangement: the module constant and a ``ValidatedConfig`` built
    without naming a probe.
    Action: read the constant's type and the config's default field.
    Assertion: ``REAL_FILESYSTEM`` is a ``FileProbe`` and the default
    config's ``probe`` IS that exact object.
    """
    assert isinstance(REAL_FILESYSTEM, FileProbe)

    config = ValidatedConfig(tools={}, raw={})

    assert config.probe is REAL_FILESYSTEM


# ---------------------------------------------------------------------------
# 2. TSWAP-C510 — more than one image source (plan line 650; item 3(b))
# ---------------------------------------------------------------------------


def test_c510_two_sources_yield_one_error_naming_both() -> None:
    """``image`` + ``build`` is one C510 naming both, requiring exactly one.

    Plan line 650 / item 3(b): sources are counted by presence —
    ``image is not None``, ``build is not None``, ``handler is not
    None`` — and more than one yields an error naming which ones were
    found and requiring exactly one.

    Arrangement: one tool with ``image`` and ``build`` set; only C510
    registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C510`` ERROR at ``tools.t1`` whose
    message names both sources and requires exactly one.
    """
    register(TSWAP_C510_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                image="example/tool:1",
                build={"context": "ctx", "dockerfile": "Dockerfile"},
            )
        },
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C510"}
    (d,) = by_code["TSWAP-C510"]
    assert d.severity is Severity.ERROR
    assert "image" in d.message
    assert "build" in d.message
    assert "exactly one" in d.message
    assert d.location.yaml_path == "tools.t1"


def test_c510_three_sources_still_yield_one_error_naming_all_three() -> None:
    """Three sources collapse to ONE diagnostic naming all three.

    Plan line 650 / item 3(b): the rule reports the SET of sources found
    — one diagnostic per tool, not one per pair.

    Arrangement: one tool with ``image``, ``build`` and ``handler``
    set; only C510 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C510`` whose message names all three
    sources.
    """
    register(TSWAP_C510_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                image="example/tool:1",
                build={"context": "ctx"},
                handler="handler.py:Cls",
            )
        },
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C510"}
    (d,) = by_code["TSWAP-C510"]
    assert "image" in d.message
    assert "build" in d.message
    assert "handler" in d.message


def test_c510_build_and_handler_together_is_a_c510() -> None:
    """``build:`` + ``handler:`` (no ``image:``) IS a C510 (pinned).

    Plan item 3(b): "A tool with both ``build:`` and ``handler:`` IS a
    C510. The XOR is three-way, and the message names both."  A
    config-level ``handler:`` alongside a ``build:`` block is genuinely
    ambiguous about who builds the image.

    Arrangement: one tool with ``build`` and ``handler`` set; only C510
    registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C510`` naming both.
    """
    register(TSWAP_C510_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                build={"context": "ctx"},
                handler="handler.py:Cls",
            )
        },
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C510"}
    (d,) = by_code["TSWAP-C510"]
    assert "build" in d.message
    assert "handler" in d.message


def test_c510_requirements_never_count_and_requirements_only_is_c511() -> (
    None
):
    """``requirements`` is an attribute, never a source (pinned).

    Plan item 3(b): "``requirements`` is **not** counted. It is an
    *attribute* of the managed source … A ``requirements:`` with no
    ``handler:`` contributes nothing to the count and is therefore
    covered by ``C511``, not ``C510``."

    Arrangement: two tools — ``t1`` has the managed source plus
    ``requirements`` (exactly one source), ``t2`` has ONLY
    ``requirements`` (zero sources); C510 and C511 registered.
    Action: run ``validate_config``.
    Assertion: no C510 anywhere; exactly one C511, on ``t2``.
    """
    register(TSWAP_C510_RULE)
    register(TSWAP_C511_RULE)
    probe = _FakeProbe(files={_BASE / "handler.py"})
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler="handler.py:Cls",
                requirements="requirements.txt",
                base_dir=_BASE,
            ),
            "t2": _tool(
                "t2",
                requirements="requirements.txt",
                base_dir=_BASE,
            ),
        },
        probe=probe,
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert "TSWAP-C510" not in by_code
    (d,) = by_code["TSWAP-C511"]
    assert d.location.yaml_path == "tools.t2"


def test_c510_exactly_one_source_produces_no_c510_or_c511() -> None:
    """A tool with exactly one source trips neither rule.

    Plan lines 650-651: C510 fires on MORE than one source, C511 on
    NONE; exactly one is the legal shape.

    Arrangement: one tool with only ``image`` set; C510 and C511
    registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C510_RULE)
    register(TSWAP_C511_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", image="example/tool:1")},
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# 3. TSWAP-C511 — no image source (plan line 651; item 3(c))
# ---------------------------------------------------------------------------


def test_c511_no_source_errors_listing_the_three_ways() -> None:
    """No image source at all → an error listing the three ways (pinned).

    Plan line 651: "``TSWAP-C511`` — none of them … → error listing the
    three ways to define a tool."  The direction is pinned on the
    message naming all three keys.

    Arrangement: one tool with ``image``, ``build`` and ``handler`` all
    ``None``; C510 and C511 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C511`` ERROR at ``tools.t1`` whose
    message contains "image", "build" and "handler"; no C510.
    """
    register(TSWAP_C510_RULE)
    register(TSWAP_C511_RULE)
    cfg = _config(tools={"t1": _tool("t1")}, probe=_FakeProbe())

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C511"}
    (d,) = by_code["TSWAP-C511"]
    assert d.severity is Severity.ERROR
    assert "image" in d.message
    assert "build" in d.message
    assert "handler" in d.message
    assert d.location.yaml_path == "tools.t1"


def test_c511_handler_carrier_set_from_tool_yaml_suppresses() -> None:
    """A ``path:`` tool's merged-in ``handler`` counts as a source.

    Plan item 3(c): "the resolver has *already merged* ``tool.yaml``'s
    ``handler`` into ``ResolvedTool.handler``, so a ``path:``-based tool
    arrives at the rule with ``handler`` set, and both ``C510`` and
    ``C511`` see the true, post-merge picture."  The rule does not
    special-case ``path:`` at all.

    Arrangement: one tool whose carrier ``handler`` is set (what the
    resolver produces for a ``path:`` tool) and nothing else; C510 and
    C511 registered; the handler file present in the fake probe.
    Action: run ``validate_config``.
    Assertion: an empty report — no C511, no C510.
    """
    register(TSWAP_C510_RULE)
    register(TSWAP_C511_RULE)
    probe = _FakeProbe(files={_BASE / "handler.py"})
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler="handler.py:Cls",
                base_dir=_BASE,
            )
        },
        probe=probe,
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c511_rule_does_not_consult_raw() -> None:
    """``config.raw`` must not be consulted for source presence (pinned).

    Plan item 3(c): "``config.raw`` is the **inline layer only**, so it
    must **not** be consulted for source presence — … reading ``raw``
    would resurrect a ``C511`` false positive on every ``path:`` tool."
    Pinned from the opposite side: a raw entry that claims a source the
    carriers do NOT carry must not silence C511.

    Arrangement: one tool with all three source carriers ``None`` while
    the raw ``tools.t1`` entry carries an ``image``; only C511
    registered.
    Action: run ``validate_config``.
    Assertion: C511 still fires — the rule reads the carriers, not raw.
    """
    register(TSWAP_C511_RULE)
    cfg = _config(
        tools={"t1": _tool("t1")},
        probe=_FakeProbe(),
        raw={"tools": {"t1": {"image": "example/tool:1"}}},
    )

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert d.code == "TSWAP-C511"
    assert d.location.yaml_path == "tools.t1"


# ---------------------------------------------------------------------------
# 4. TSWAP-C512 — the file.py:Name grammar (plan line 652; item 4)
# ---------------------------------------------------------------------------


def test_c512_valid_form_produces_nothing() -> None:
    """``handler.py:MyCls`` is the valid form (pinned).

    Plan item 4: split on the first colon; the file part is non-empty
    and ends with ``.py``; the name part is non-empty, an identifier and
    not a keyword.

    Arrangement: one tool with a valid handler, the file present; C512
    and C513 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C512_RULE)
    register(TSWAP_C513_RULE)
    probe = _FakeProbe(files={_BASE / "handler.py"})
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler="handler.py:MyCls",
                base_dir=_BASE,
            )
        },
        probe=probe,
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


@pytest.mark.parametrize(
    "value",
    [
        "handler.py",  # no colon
        ":Cls",  # no file
        "handler.py:",  # no name
        "handler.py:not-an-identifier",  # bad identifier
        "handler:Cls",  # missing .py (A16)
        "handler.py:class",  # keyword as class name (A16)
        "handler.py:module.Attr",  # dotted name fails
        "  ",  # whitespace
    ],
)
def test_c512_malformed_forms_are_each_flagged(value: str) -> None:
    """Every pinned malformed handler form yields exactly one C512.

    Plan item 4 pins the four bad cases (no colon, no file, no name, bad
    identifier) plus A16's missing-``.py`` and keyword-name rejections,
    the dotted-name failure, and a whitespace-only value (both halves
    must be non-empty after stripping).

    Arrangement: one tool whose handler is the parametrized value, no
    file present; only C512 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C512`` ERROR at
    ``tools.t1.handler`` whose message shows the expected form
    ``file.py:ClassName``.
    """
    register(TSWAP_C512_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler=value,
                base_dir=_BASE,
            )
        },
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C512"}
    (d,) = by_code["TSWAP-C512"]
    assert d.severity is Severity.ERROR
    assert _EXPECTED_HANDLER_FORM in d.message
    assert d.location.yaml_path == "tools.t1.handler"


def test_c512_message_shows_the_found_value() -> None:
    """The C512 message names what was found, not just the expected form.

    Plan line 652: "error showing the expected form **and what was
    found**."

    Arrangement: one tool with the malformed handler ``handler.py`` (no
    colon); only C512 registered.
    Action: run ``validate_config``.
    Assertion: the message contains both the expected form and the
    offending value.
    """
    register(TSWAP_C512_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler="handler.py",
                base_dir=_BASE,
            )
        },
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert _EXPECTED_HANDLER_FORM in d.message
    assert "handler.py" in d.message


def test_c512_suppresses_c513_and_c516_for_the_same_tool() -> None:
    """A malformed handler yields exactly C512 — no C513, no C516.

    Plan item 4: "``C512`` **suppresses ``C513``** for that tool: an
    unparseable handler string has no file part to look for, and
    emitting both would be two diagnostics for one mistake. When the
    string parses, ``C513`` checks the file part. ``C516`` is likewise
    evaluated only for a parseable handler."

    Arrangement: one tool with the malformed handler ``handler.py``, no
    file present anywhere; C512, C513 and C516 registered.
    Action: run ``validate_config``.
    Assertion: exactly the C512 — no C513 file-existence error and no
    C516 escape warning for the unparseable string.
    """
    register(TSWAP_C512_RULE)
    register(TSWAP_C513_RULE)
    register(TSWAP_C516_RULE)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler="handler.py",
                base_dir=_BASE,
            )
        },
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C512"}
    assert "TSWAP-C513" not in by_code
    assert "TSWAP-C516" not in by_code


# ---------------------------------------------------------------------------
# 5. TSWAP-C513 — the handler file (plan line 653; items 2, 6)
# ---------------------------------------------------------------------------


def test_c513_missing_handler_file_errors_with_resolved_path() -> None:
    """A missing handler file is an error naming the resolved path.

    Plan line 653 / block 2(c): the error carries ``str(resolved)`` —
    the lexically normalised path tried — in the MESSAGE (not only the
    remedy), since a relative-path misunderstanding is the likely cause.

    Arrangement: ``base_dir`` a fake tool dir, a valid handler, and a
    probe in which neither the file nor a directory exists there; only
    C513 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C513`` ERROR at ``tools.t1.handler``
    with the resolved path in the message, and the probe queried
    exactly that path.
    """
    register(TSWAP_C513_RULE)
    probe = _FakeProbe()
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler="handler.py:Cls",
                base_dir=_BASE,
            )
        },
        probe=probe,
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C513"}
    (d,) = by_code["TSWAP-C513"]
    assert d.severity is Severity.ERROR
    resolved = _BASE / "handler.py"
    assert str(resolved) in d.message
    assert resolved in probe.queried("is_file")
    assert d.location.yaml_path == "tools.t1.handler"


def test_c513_resolves_relative_to_base_dir_when_set() -> None:
    """``base_dir`` is the resolution root for ``path:`` tools (pinned).

    Plan item 2(a): "base = ``tool.base_dir`` if ``tool.base_dir`` is
    not None else ``config.path.parent``" — a relative handler resolves
    against the tool directory, not the config directory.

    Arrangement: ``base_dir`` = ``/srv/tools/t1`` while the config path
    sits in a DIFFERENT directory (``/etc/tswap/tools.yaml``); the probe
    knows the file only at the ``base_dir``-relative location; only C513
    registered.
    Action: run ``validate_config``.
    Assertion: no C513 — the probe was consulted at
    ``/srv/tools/t1/handler.py``, never at the config-directory root.
    """
    register(TSWAP_C513_RULE)
    probe = _FakeProbe(files={_BASE / "handler.py"})
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler="handler.py:Cls",
                base_dir=_BASE,
            )
        },
        probe=probe,
        path=Path("/etc/tswap/tools.yaml"),
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()
    assert _BASE / "handler.py" in probe.queried("is_file")
    assert Path("/etc/tswap/handler.py") not in probe.queried("is_file")


def test_c513_resolves_relative_to_config_path_parent_when_base_dir_none() -> (
    None
):
    """An inline tool resolves against ``config.path.parent`` (pinned).

    Plan item 2(a) table, second row: no ``path:`` (fully inline) → the
    root config's directory is the base.

    Arrangement: ``base_dir`` ``None``, config path
    ``/etc/tswap/tools.yaml``, the probe knows the file only at
    ``/etc/tswap/handler.py``; only C513 registered.
    Action: run ``validate_config``.
    Assertion: no C513, and the probe was queried at
    ``/etc/tswap/handler.py``.
    """
    register(TSWAP_C513_RULE)
    probe = _FakeProbe(files={Path("/etc/tswap/handler.py")})
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler="handler.py:Cls",
            )
        },
        probe=probe,
        path=Path("/etc/tswap/tools.yaml"),
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()
    assert Path("/etc/tswap/handler.py") in probe.queried("is_file")


def test_c513_default_config_path_resolves_against_path_dot() -> None:
    """``base_dir`` None + the default config path → base ``Path(".")``.

    Robustness pin (plan item 2(c)): with the default
    ``Path("tools.yaml")`` the base is ``Path(".")`` and the rendered
    path is relative — correct, not a bug; the rule must not call
    ``Path.cwd()`` to absolutise it.

    Arrangement: ``base_dir`` ``None``, the default config path, no file
    anywhere in the fake probe; only C513 registered.
    Action: run ``validate_config``.
    Assertion: one C513 whose message carries the RELATIVE resolved path
    — the path the probe was keyed on, rendered relative.
    """
    register(TSWAP_C513_RULE)
    probe = _FakeProbe()
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler="handler.py:Cls",
            )
        },
        probe=probe,
    )

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert d.code == "TSWAP-C513"
    base = Path("tools.yaml").parent  # Path(".")
    assert str(base / "handler.py") in d.message
    assert base / "handler.py" in probe.queried("is_file")


def test_c513_handler_path_that_is_a_directory_is_flagged() -> None:
    """A handler path that exists but is a DIRECTORY is a C513 (pinned).

    Plan line 657 / block 6: "A handler path that exists but is a
    DIRECTORY → ``C513`` fires (it is not a file)" with the pinned
    message direction "is a directory, not a file" alongside the same
    resolved path — the discrimination that is why ``FileProbe`` carries
    ``is_dir`` as well as ``is_file``.

    Arrangement: the probe answers file=False, directory=True for the
    resolved path; only C513 registered.
    Action: run ``validate_config``.
    Assertion: one C513 whose message carries BOTH the resolved path and
    the pinned phrase.
    """
    register(TSWAP_C513_RULE)
    resolved = _BASE / "handler.py"
    probe = _FakeProbe(dirs={resolved: True})
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler="handler.py:Cls",
                base_dir=_BASE,
            )
        },
        probe=probe,
    )

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert d.code == "TSWAP-C513"
    assert str(resolved) in d.message
    assert _DIRECTORY_NOT_FILE_PHRASE in d.message


def test_c513_existing_handler_file_produces_nothing() -> None:
    """A handler file that exists trips no C513.

    Arrangement: the probe answers file=True for the resolved path (the
    path stays inside the base, so C516 cannot fire either); C513 and
    C516 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C513_RULE)
    register(TSWAP_C516_RULE)
    probe = _FakeProbe(files={_BASE / "handler.py"})
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler="handler.py:Cls",
                base_dir=_BASE,
            )
        },
        probe=probe,
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c513_resolution_is_lexical_normpath_never_resolve() -> None:
    """``sub/../handler.py`` is normalised LEXICALLY, not resolved.

    Plan item 2(a): "Resolution is ``base / Path(value)``, then a purely
    lexical normalisation — never ``Path.resolve()``."  (``resolve()``
    touches the disk and is CWD-dependent.)  Pinned on WHICH path the
    probe is called with: the normalised one, not the raw join.

    Arrangement: ``base_dir`` set, handler ``sub/../handler.py:Cls``,
    the probe knows no file anywhere; only C513 registered.
    Action: run ``validate_config``.
    Assertion: the probe was queried with the NORMALISED
    ``/srv/tools/t1/handler.py`` and never with the raw
    ``/srv/tools/t1/sub/../handler.py``; the C513 message carries the
    normalised path.
    """
    register(TSWAP_C513_RULE)
    probe = _FakeProbe()
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler="sub/../handler.py:Cls",
                base_dir=_BASE,
            )
        },
        probe=probe,
    )

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert d.code == "TSWAP-C513"
    normalised = _BASE / "handler.py"
    raw = _BASE / "sub" / ".." / "handler.py"
    all_queried = [p for _pred, p in probe.queries]
    assert normalised in all_queried
    assert raw not in all_queried
    assert str(normalised) in d.message


# ---------------------------------------------------------------------------
# 6. TSWAP-C514 — the requirements file (plan line 654; item 2)
# ---------------------------------------------------------------------------


def test_c514_missing_requirements_errors_with_resolved_path() -> None:
    """A named requirements file that does not exist is a C514 (pinned).

    Plan line 654 / block 2(c): error with the resolved path in the
    message.

    Arrangement: ``requirements="requirements.txt"``, the probe knows no
    such file; only C514 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C514`` ERROR at
    ``tools.t1.requirements`` with ``str(base / "requirements.txt")`` in
    the message.
    """
    register(TSWAP_C514_RULE)
    probe = _FakeProbe()
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                requirements="requirements.txt",
                base_dir=_BASE,
            )
        },
        probe=probe,
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C514"}
    (d,) = by_code["TSWAP-C514"]
    assert d.severity is Severity.ERROR
    resolved = _BASE / "requirements.txt"
    assert str(resolved) in d.message
    assert resolved in probe.queried("is_file")
    assert d.location.yaml_path == "tools.t1.requirements"


def test_c514_existing_requirements_produces_nothing() -> None:
    """A requirements file that exists trips no C514.

    Arrangement: the probe answers file=True for the resolved path; only
    C514 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C514_RULE)
    probe = _FakeProbe(files={_BASE / "requirements.txt"})
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                requirements="requirements.txt",
                base_dir=_BASE,
            )
        },
        probe=probe,
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c514_absent_requirements_produces_nothing() -> None:
    """``requirements=None`` trips no C514 and queries no disk.

    Plan line 651 / item 3(b): "``C514`` only fires when it is named."

    Arrangement: one tool with ``requirements`` absent; only C514
    registered.
    Action: run ``validate_config``.
    Assertion: an empty report and NO probe queries at all.
    """
    register(TSWAP_C514_RULE)
    probe = _FakeProbe()
    cfg = _config(
        tools={"t1": _tool("t1", base_dir=_BASE)},
        probe=probe,
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()
    assert probe.queries == []


# ---------------------------------------------------------------------------
# 7. TSWAP-C515 — build context and dockerfile (plan line 655; item 6)
# ---------------------------------------------------------------------------


def test_c515_missing_context_directory_errors_with_resolved_path() -> None:
    """A ``build.context`` that is not a directory is a C515 (pinned).

    Plan line 655 / block 6: "``build.context`` must be a **directory**
    (``is_dir``)"; the error carries ``str(resolved)`` in the message.

    Arrangement: ``build={"context": "ctx", "dockerfile":
    "Dockerfile"}``, the probe knows no directory at ``base/"ctx"``;
    only C515 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C515`` ERROR at
    ``tools.t1.build.context`` with the resolved path in the message.
    """
    register(TSWAP_C515_RULE)
    probe = _FakeProbe()
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                build={"context": "ctx", "dockerfile": "Dockerfile"},
                base_dir=_BASE,
            )
        },
        probe=probe,
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C515"}
    (d,) = by_code["TSWAP-C515"]
    assert d.severity is Severity.ERROR
    resolved = _BASE / "ctx"
    assert str(resolved) in d.message
    assert d.location.yaml_path == "tools.t1.build.context"


def test_c515_context_that_is_a_file_is_flagged_with_the_mirrored_phrase() -> (
    None
):
    """A context pointing at a FILE says "is a file, not a directory".

    Plan block 6: "a context pointing at a file gets the mirrored message
    *'is a file, not a directory'*" (the phrase is pinned verbatim).

    Arrangement: the probe answers dir=False, file=True for
    ``base/"ctx"``; only C515 registered.
    Action: run ``validate_config``.
    Assertion: one C515 at ``tools.t1.build.context`` whose message
    carries BOTH the resolved path and the pinned phrase.
    """
    register(TSWAP_C515_RULE)
    ctx = _BASE / "ctx"
    probe = _FakeProbe(files={ctx: True})
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                build={"context": "ctx", "dockerfile": "Dockerfile"},
                base_dir=_BASE,
            )
        },
        probe=probe,
    )

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert d.code == "TSWAP-C515"
    assert str(ctx) in d.message
    assert _FILE_NOT_DIRECTORY_PHRASE in d.message
    assert d.location.yaml_path == "tools.t1.build.context"


def test_c515_missing_dockerfile_within_context_errors_with_resolved_path() -> (
    None
):
    """A missing dockerfile is resolved WITHIN the context (pinned).

    Plan line 655 / block 6: "``build.dockerfile`` must be a **file**,
    resolved **within the context directory** … ``context_resolved /
    dockerfile``".

    Arrangement: the context directory exists in the probe, the
    dockerfile does not; only C515 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C515`` ERROR at
    ``tools.t1.build.dockerfile`` with ``str(base/"ctx"/"Dockerfile")``
    in the message.
    """
    register(TSWAP_C515_RULE)
    ctx = _BASE / "ctx"
    probe = _FakeProbe(dirs={ctx: True})
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                build={"context": "ctx", "dockerfile": "Dockerfile"},
                base_dir=_BASE,
            )
        },
        probe=probe,
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C515"}
    (d,) = by_code["TSWAP-C515"]
    resolved = ctx / "Dockerfile"
    assert str(resolved) in d.message
    assert resolved in probe.queried("is_file")
    assert d.location.yaml_path == "tools.t1.build.dockerfile"


def test_c515_absent_dockerfile_key_defaults_to_dockerfile() -> None:
    """A build block without a ``dockerfile`` key checks "Dockerfile".

    Test requirement: the dockerfile absent from the build dict → the
    default ``Dockerfile`` is checked (pinned).

    Arrangement: ``build={"context": "ctx"}`` only, the context
    directory exists, the probe knows no dockerfile anywhere; only C515
    registered.
    Action: run ``validate_config``.
    Assertion: the probe WAS queried for ``base/"ctx"/"Dockerfile"`` and
    the C515 fires at ``tools.t1.build.dockerfile``.
    """
    register(TSWAP_C515_RULE)
    ctx = _BASE / "ctx"
    probe = _FakeProbe(dirs={ctx: True})
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                build={"context": "ctx"},
                base_dir=_BASE,
            )
        },
        probe=probe,
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C515"}
    (d,) = by_code["TSWAP-C515"]
    default_dockerfile = ctx / "Dockerfile"
    assert default_dockerfile in probe.queried("is_file")
    assert str(default_dockerfile) in d.message
    assert d.location.yaml_path == "tools.t1.build.dockerfile"


def test_c515_build_none_produces_nothing() -> None:
    """``build=None`` trips no C515 and queries no disk.

    Arrangement: one tool with ``build`` absent; only C515 registered.
    Action: run ``validate_config``.
    Assertion: an empty report and NO probe queries at all.
    """
    register(TSWAP_C515_RULE)
    probe = _FakeProbe()
    cfg = _config(
        tools={"t1": _tool("t1", base_dir=_BASE)},
        probe=probe,
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()
    assert probe.queries == []


def test_c515_build_not_a_dict_is_skipped_silently_without_c999() -> None:
    """A present-but-malformed ``build`` is skipped, never a C999 (pinned).

    Robustness pin: ``build="oops"`` is not a dict — C515 skips it
    silently (one mistake, one diagnostic; the schema layer owns the
    ``build`` shape), and the rule must not raise into the validator's
    C999 catch-all.  ``build`` presence IS a source for C510, but one
    source trips nothing.

    Arrangement: one tool with ``build="oops"``; ALL seven C5xx rules
    registered.
    Action: run ``validate_config``.
    Assertion: an empty report — no C515, no C510, no C999.
    """
    for rule in _ALL_C5XX_RULES:
        register(rule)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                build="oops",
                base_dir=_BASE,
            )
        },
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# 8. TSWAP-C516 — the escape warning (plan line 657; items 2(b), 7)
# ---------------------------------------------------------------------------


def test_c516_escaping_handler_yields_warning_naming_the_path() -> None:
    """A handler escaping the tool directory is a WARNING, not an error.

    Plan line 657 / block 2(b): "the escape is *allowed*" (block 7:
    ``Severity.WARNING``) since it breaks the portability that
    ``path:`` exists to provide.  The detection is the LEXICAL
    comparison on the NORMALISED path: the raw ``../`` prefix walks the
    tool out of its directory.

    Arrangement: ``base_dir`` set, handler ``../shared/handler.py:Cls``
    (normalises to the sibling directory, outside the base), the file
    absent; only C516 registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C516`` WARNING at
    ``tools.t1.handler`` whose message names the resolved path and
    points at the portability problem.
    """
    register(TSWAP_C516_RULE)
    probe = _FakeProbe()
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler="../shared/handler.py:Cls",
                base_dir=_BASE,
            )
        },
        probe=probe,
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C516"}
    (d,) = by_code["TSWAP-C516"]
    assert d.severity is Severity.WARNING
    resolved = _BASE.parent / "shared" / "handler.py"
    assert str(resolved) in d.message
    assert "portab" in d.message.lower() or (
        "tool directory" in d.message.lower()
    )
    assert d.location.yaml_path == "tools.t1.handler"


def test_c516_handler_inside_base_yields_no_warning() -> None:
    """A plain relative handler inside the base trips no C516.

    ``shared/handler.py`` resolves INSIDE the tool directory — the
    normal case; the escape is the ``../`` that walks OUT of it, not
    any subdirectory.

    Arrangement: the handler file exists at ``base/"shared/handler.py"``;
    C516 and C513 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C516_RULE)
    register(TSWAP_C513_RULE)
    probe = _FakeProbe(files={_BASE / "shared" / "handler.py"})
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler="shared/handler.py:Cls",
                base_dir=_BASE,
            )
        },
        probe=probe,
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c516_dotdot_that_cancels_out_yields_no_warning() -> None:
    """``sub/../handler.py`` normalises INSIDE the base — no C516 (pinned).

    Plan block 2(b): "A raw string check on ``'..' in value`` is
    **rejected**: it fires on the legitimate ``../`` that cancels out
    (``a/../handler.py`` never leaves the directory)" — the comparison
    is on the NORMALISED path, i.e. ``is_relative_to`` semantics, not a
    string check.

    Arrangement: handler ``sub/../handler.py:Cls``, the file present at
    the normalised location; C516 and C513 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C516_RULE)
    register(TSWAP_C513_RULE)
    probe = _FakeProbe(files={_BASE / "handler.py"})
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler="sub/../handler.py:Cls",
                base_dir=_BASE,
            )
        },
        probe=probe,
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c516_coexists_with_c513_for_an_escaping_missing_handler() -> None:
    """An escaping handler that also does not exist yields BOTH (pinned).

    Plan block 2(b): "``C516`` … does not suppress ``C513``/``C514``/
    ``C515`` — an escaping path that also does not exist yields both,
    since they are different problems."

    Arrangement: the escaping handler, the file absent; C513 and C516
    registered.
    Action: run ``validate_config``.
    Assertion: one C513 ERROR and one C516 WARNING in the same report.
    """
    register(TSWAP_C513_RULE)
    register(TSWAP_C516_RULE)
    probe = _FakeProbe()
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler="../shared/handler.py:Cls",
                base_dir=_BASE,
            )
        },
        probe=probe,
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C513", "TSWAP-C516"}
    (c513,) = by_code["TSWAP-C513"]
    (c516,) = by_code["TSWAP-C516"]
    assert c513.severity is Severity.ERROR
    assert c516.severity is Severity.WARNING


# ---------------------------------------------------------------------------
# 9. Static-only: the handler is never imported (plan line 656; item 6)
# ---------------------------------------------------------------------------


def test_validate_config_never_imports_the_handler(tmp_path: Path) -> None:
    """Validation is static-only: the handler is NEVER imported.

    Plan line 656 / block 6: "No import, ever." — ``tswap validate``
    must run with no Docker and none of the tool's dependencies
    installed, and importing a handler would pull in torch.  This is
    the ONE test that uses the real probe with a real ``tmp_path``: a
    ``handler.py`` whose contents raise at module top level, so any
    import — or even a compile or read of the contents — is caught by
    the module snapshot and the C999 catch-all.  With the probe
    injected, every OTHER test's fake never touches the disk at all, so
    "no import" is structural there; running against a real file with
    the real probe is what pins it end to end.

    Arrangement: a real ``handler.py`` in ``tmp_path`` containing
    ``raise RuntimeError("no import")`` at module top level; a tool with
    a valid handler pointing at it, ``base_dir`` the real directory, and
    the DEFAULT probe (``REAL_FILESYSTEM`` — the file genuinely exists,
    so C513 must not fire); all seven C5xx rules registered; the
    ``sys.modules`` snapshot taken before ``validate_config``.
    Action: run ``validate_config``.
    Assertion: no new modules (``set(sys.modules) - before == set()``),
    the handler's module name absent from ``sys.modules``, no C513 (the
    file exists), no C999 — an empty report.
    """
    handler_file = tmp_path / "handler.py"
    handler_file.write_text('raise RuntimeError("no import")\n')

    for rule in _ALL_C5XX_RULES:
        register(rule)
    config = ValidatedConfig(
        tools={
            "t1": _tool(
                "t1",
                handler="handler.py:Cls",
                base_dir=tmp_path,
            )
        },
        raw={"tools": {}},
        # The DEFAULT probe is REAL_FILESYSTEM — the real filesystem —
        # so the file genuinely exists and C513 does not fire.
        path=Path("tools.yaml"),
    )
    before = set(sys.modules)

    report = validate_config(config)

    assert "handler" not in sys.modules
    assert set(sys.modules) - before == set()
    by_code = _diagnostics_by_code(report)
    assert "TSWAP-C513" not in by_code
    assert "TSWAP-C999" not in by_code
    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# 10. Cross-cutting pins: locations, only-own-codes, one-report
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "tool_kwargs", "probe", "yaml_path"),
    [
        (
            TSWAP_C510_RULE,
            {"image": "example/tool:1", "build": {"context": "ctx"}},
            _FakeProbe(),
            "tools.t1",
        ),
        (
            TSWAP_C511_RULE,
            {},
            _FakeProbe(),
            "tools.t1",
        ),
        (
            TSWAP_C512_RULE,
            {"handler": "handler.py", "base_dir": _BASE},
            _FakeProbe(),
            "tools.t1.handler",
        ),
        (
            TSWAP_C513_RULE,
            {"handler": "handler.py:Cls", "base_dir": _BASE},
            _FakeProbe(),
            "tools.t1.handler",
        ),
        (
            TSWAP_C514_RULE,
            {"requirements": "requirements.txt", "base_dir": _BASE},
            _FakeProbe(),
            "tools.t1.requirements",
        ),
        (
            TSWAP_C515_RULE,
            {
                "build": {"context": "ctx", "dockerfile": "Dockerfile"},
                "base_dir": _BASE,
            },
            _FakeProbe(),
            "tools.t1.build.context",
        ),
        (
            TSWAP_C515_RULE,
            {
                "build": {"context": "ctx", "dockerfile": "Dockerfile"},
                "base_dir": _BASE,
            },
            _FakeProbe(dirs={_BASE / "ctx": True}),
            "tools.t1.build.dockerfile",
        ),
        (
            TSWAP_C516_RULE,
            {"handler": "../shared/handler.py:Cls", "base_dir": _BASE},
            _FakeProbe(),
            "tools.t1.handler",
        ),
    ],
)
@pytest.mark.parametrize("line", [42, None])
def test_location_contract_per_code(
    rule: Rule,
    tool_kwargs: dict[str, object],
    probe: _FakeProbe,
    yaml_path: str,
    line: int | None,
) -> None:
    """Every C5xx location consults ``line_for`` and ``config.path``.

    Plan block 5: ``Location(file=str(config.path), yaml_path=<pinned>,
    line=config.line_for(<the same string>))`` — the file is never
    hardcoded and ``line=None`` is a legal outcome, so the test asserts
    the RELATION ``location.line == config.line_for(location.yaml_path)``,
    never a hardcoded line number; both a fixed-int ``line_for`` and a
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
        probe=probe,
        line_for=(lambda _p, _line=line: _line),
        path=Path("my-config.yaml"),
    )

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert d.location.file == "my-config.yaml"
    assert d.location.yaml_path == yaml_path
    assert d.location.line == cfg.line_for(d.location.yaml_path)


def test_single_image_source_yields_no_c5xx_at_all() -> None:
    """A tool with exactly one valid source trips no C5xx at all (pinned).

    Only-own-codes pin: a tool with ``image`` set and no
    handler/requirements/build has exactly one source, no handler to
    parse and nothing missing on disk — so all seven rules together must
    stay silent.

    Arrangement: one such tool; ALL seven C5xx rules registered.
    Action: run ``validate_config``.
    Assertion: no code starting ``TSWAP-C5`` (and no C999) appears in
    the report.
    """
    for rule in _ALL_C5XX_RULES:
        register(rule)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                image="example/tool:1",
                base_dir=_BASE,
            )
        },
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert not any(code.startswith("TSWAP-C5") for code in by_code)
    assert "TSWAP-C999" not in by_code


def test_missing_handler_requirements_and_build_context_all_reported_once() -> (
    None
):
    """C513 + C514 + C515 for one tool all land in a single report (pinned).

    The "report every finding at once" contract (behaviour 11) applied
    to behaviour 15: a tool with a well-formed but MISSING handler file
    (C513), a missing requirements file (C514), and a build context that
    is not a directory (C515) yields ALL THREE from one
    ``validate_config`` call — C514 neither suppresses nor depends on
    C512/C513 (a tool can have both C513 and C514 in one report).

    Note: the tool carries ``handler`` AND ``build``, which is itself a
    pinned two-source C510 (plan item 3(b)) — the fourth diagnostic is
    the logical consequence of the other pins, not an extra behaviour.

    Arrangement: one such tool; every path inside the base, so C516
    stays out; ALL seven C5xx rules registered.
    Action: run ``validate_config``.
    Assertion: exactly one C513, one C514 and one C515 (the C510 for
    the handler+build pair included) — four diagnostics, no other codes.
    """
    for rule in _ALL_C5XX_RULES:
        register(rule)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1",
                handler="handler.py:Cls",
                requirements="requirements.txt",
                build={"context": "ctx", "dockerfile": "Dockerfile"},
                base_dir=_BASE,
            )
        },
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {
        "TSWAP-C510",
        "TSWAP-C513",
        "TSWAP-C514",
        "TSWAP-C515",
    }
    assert len(by_code["TSWAP-C513"]) == 1
    assert len(by_code["TSWAP-C514"]) == 1
    assert len(by_code["TSWAP-C515"]) == 1
    assert len(report.diagnostics) == 4

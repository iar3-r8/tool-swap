"""Tests for M1 behaviour 17 — mounts (§6 rule 9, §5.6).

See ``plans/m1-configuration.md`` behaviour 17 (lines 1085-1096) and its
"Confirmed contract details (2026-08-19)" block (items 1-13, lines
1098-1282).  This file is the executable form of that contract: the
pure parser (``ParsedMount`` + ``parse_mount``), the four rule constants
(``TSWAP_C540_RULE`` … ``TSWAP_C543_RULE``) and the trailing ``home``
field on ``ValidatedConfig`` do not exist yet in
``src/tool_swap/config/validate.py`` (behaviour 16 shipped the C52x/
C53x rules and the 30-rule ``BUILTIN_RULES`` only).  This module
therefore fails collection with a single clean ``ImportError`` naming
exactly one missing name:

    ImportError: cannot import name 'ParsedMount'
        from 'tool_swap.config.validate'

(``ParsedMount`` is the first missing name in the import list; Python
reports the first one it fails on.)  Every test body below pins a
concrete behaviour the GREEN step must satisfy, so the assertions — not
just the import — are the contract.

Pinned public API (the names the GREEN step must add):

- ``ParsedMount`` — frozen dataclass: ``host`` (as authored after ``~``
  expansion; may be relative), ``container``, ``mode`` (as authored, or
  ``"ro"`` when the entry omitted the third part), ``mode_defaulted``
  (True iff the authored entry had no third part), ``resolved_host``
  (host resolved against the config file's directory, lexically).
- ``parse_mount(entry, *, config_dir, home=None)`` — pure function;
  ``None`` for exactly the C540 cases.  ``home=None`` means the REAL
  home; every test injects a fake home through the parameter (never via
  ``os.environ``).
- ``TSWAP_C540_RULE`` … ``TSWAP_C543_RULE`` — C540 ERROR, C541 ERROR,
  C542 ERROR, C543 WARNING; non-empty remedies; appended to
  ``BUILTIN_RULES`` in code order after behaviour 16's seven (34 total).
- ``ValidatedConfig.home`` — trailing, keyword-only, defaulted to
  ``None`` (the real home); the rules use ``config.home`` for ``~``
  expansion.  In the red window the field does not exist yet, so the
  builder passes the ``home`` keyword with a type-ignore — the same
  pattern as behaviour 16's ``gpu_count`` (the collection ImportError
  masks it).

The rules read ONLY ``tool.values["mounts"]``, ``config.path``,
``config.line_for``, ``config.probe`` and ``config.home``.  Every byte
of disk knowledge arrives through the probe (dict-backed fakes); every
path is computed LEXICALLY (normpath semantics, never
``Path.resolve()``) against ``config.path.parent`` — the CONFIG
file's directory, never the tool's ``base_dir``.  Non-string entries
and non-list ``mounts`` are skipped silently (the schema's
``TSWAP-C105`` owns those).

Conventions mirror ``tests/unit/config/test_validate_image_source.py``:
pytest, AAA, snake_case, Google docstrings, an autouse fixture calling
``unregister_all()`` before AND after every test (the registry is
shared module state), the C54x rules registered explicitly per test.
No ``importlib.reload`` anywhere.  No ``tmp_path``: the probes are
fakes and the config directory is a fixed ``Path`` that never exists.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest
from tool_swap.config.errors import ConfigReport, Diagnostic, Severity
from tool_swap.config.origin import OriginMap
from tool_swap.config.resolver import ResolvedTool
from tool_swap.config.validate import (  # noqa: E501  (names absent in RED step)
    ParsedMount,
    parse_mount,
    TSWAP_C540_RULE,
    TSWAP_C541_RULE,
    TSWAP_C542_RULE,
    TSWAP_C543_RULE,
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

#: The four behaviour-17 rule ids (§6 rule 9), in code order.
_BEHAVIOUR_17_IDS: Final[tuple[str, ...]] = (
    "TSWAP-C540",
    "TSWAP-C541",
    "TSWAP-C542",
    "TSWAP-C543",
)

#: The four behaviour-17 rule constants, in code order.
_ALL_C54X_RULES: Final[tuple[Rule, ...]] = (
    TSWAP_C540_RULE,
    TSWAP_C541_RULE,
    TSWAP_C542_RULE,
    TSWAP_C543_RULE,
)

#: A fake config directory (never exists on any real filesystem; all
#: resolution is lexical and all probes are fakes).
_CFG: Final[Path] = Path("/cfg")

#: The config file path inside the fake directory; its ``parent`` is the
#: resolution base for relative host paths at rule time.
_CFG_PATH: Final[Path] = Path("/cfg/tools.yaml")

#: A fake home injected through ``parse_mount``'s ``home`` parameter (and
#: ``ValidatedConfig.home``) — never read from the environment.
_HOME: Final[Path] = Path("/fake/home")

#: A config directory that does not exist, used by the purity pin.
_MISSING_CFG: Final[Path] = Path("/does/not/exist")

#: The pinned C543 remedy phrase (plan item 7, near-verbatim from
#: ``plan/07_CLI_AND_OPS.md`` §5): the host-vs-router-container trap.
_C543_TRAP_PHRASE: Final[str] = (
    "host paths interpreted by the Docker daemon, not paths inside the "
    "router container"
)


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


def _tool(name: str, mounts: object = None) -> ResolvedTool:
    """Build a minimal frozen ``ResolvedTool`` carrying ``mounts``.

    The value rides the resolved 47-key ``values`` mapping exactly as
    the resolver would place it (the AUTHORED strings, concatenated,
    unchanged — plan item 1); ``None`` means "no layer supplied it".

    Args:
        name: the tool name (used as both the ``tools`` dict key and the
            ``ResolvedTool.name`` in every fixture, so the two
            namespaces agree).
        mounts: the resolved ``mounts`` value, as authored (usually a
            list of strings; a non-list value is the robustness case).

    Returns:
        A ``ResolvedTool`` with ``origins=OriginMap()`` and no
        diagnostics.
    """
    return ResolvedTool(
        name=name,
        values={"mounts": mounts},
        origins=OriginMap(),
        diagnostics=[],
    )


def _config(
    tools: dict[str, ResolvedTool],
    probe: _FakeProbe,
    line_for: Callable[[str], int | None] | None = None,
    path: Path | None = None,
    raw: dict[str, object] | None = None,
    home: Path | None = None,
) -> ValidatedConfig:
    """Build a ``ValidatedConfig`` carrying an injected fake probe and home.

    The C54x rules read only ``tool.values["mounts"]`` plus
    ``config.probe`` / ``config.home`` / ``config.path`` /
    ``config.line_for``; the raw block is an inert placeholder.

    Args:
        tools: name -> ``ResolvedTool`` (positional field).
        probe: the dict-backed fake probe (every test).
        line_for: dotted YAML path -> 1-based line or ``None``; defaults
            to a ``None``-returning mapping.
        path: the config file path; defaults to ``Path("tools.yaml")``.
            The relative host resolution base is ``path.parent``.
        raw: the raw root YAML mapping; defaults to ``{"tools": {}}``.
        home: the injected home for ``~`` expansion (``None`` = the real
            home; every test that parses ``~`` passes a fake).

    Returns:
        The frozen ``ValidatedConfig``.
    """
    return ValidatedConfig(
        tools=tools,
        raw=raw if raw is not None else {"tools": {}},
        line_for=line_for if line_for is not None else (lambda _p: None),
        path=path if path is not None else Path("tools.yaml"),
        probe=probe,
        # ``home`` is the trailing, keyword-only, defaulted field the
        # GREEN step adds (plan item 3); naming it here is the same red
        # pattern as behaviour 16's ``gpu_count``.
        home=home,  # type: ignore[call-arg]
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
    C54x rules it exercises (explicitly, like the behaviour-13 through
    behaviour-16 files) and must not depend on — and must not leak —
    registration state.
    """
    unregister_all()
    try:
        yield
    finally:
        unregister_all()


# ---------------------------------------------------------------------------
# 1. parse_mount — the pure parser (plan items 1, 3 and 4)
# ---------------------------------------------------------------------------


def test_parse_mount_two_part_defaults_mode_to_ro() -> None:
    """``"host:container"`` parses with ``mode="ro"``, ``mode_defaulted``.

    Plan item 4: a 2-part entry parses with ``mode="ro"`` and
    ``mode_defaulted=True`` — the DEFAULT is recorded, not hidden (the
    §5.6 "say so" requirement).  ``ParsedMount`` is a frozen dataclass
    (the parsed view is shared by four rules and behaviour 22, so it
    must not drift).

    Arrangement: the 2-part entry, the fake config dir, a fake home.
    Action: call ``parse_mount``.
    Assertion: every field holds the pinned value and mutation raises
    ``FrozenInstanceError``.
    """
    parsed = parse_mount("host:container", config_dir=_CFG, home=_HOME)

    assert isinstance(parsed, ParsedMount)
    assert parsed.host == "host"
    assert parsed.container == "container"
    assert parsed.mode == "ro"
    assert parsed.mode_defaulted is True
    assert parsed.resolved_host == _CFG / "host"

    with pytest.raises(dataclasses.FrozenInstanceError):
        parsed.host = "other"  # type: ignore[misc]


@pytest.mark.parametrize("mode", ["ro", "rw"])
def test_parse_mount_three_part_keeps_mode_as_authored(mode: str) -> None:
    """A 3-part entry keeps the mode AS AUTHORED, ``mode_defaulted=False``.

    Plan item 1: "``mode`` is the mode AS AUTHORED, not a validated one"
    — only the ABSENCE of a third part is filled in.

    Arrangement: the 3-part entry with each legal mode.
    Action: call ``parse_mount``.
    Assertion: ``mode`` is the authored spelling and ``mode_defaulted``
    is ``False``.
    """
    parsed = parse_mount(f"/h:/c:{mode}", config_dir=_CFG, home=_HOME)

    assert parsed is not None
    assert parsed.mode == mode
    assert parsed.mode_defaulted is False


@pytest.mark.parametrize("mode", ["RO", "BOGUS"])
def test_parse_mount_does_not_validate_or_rewrite_the_mode(mode: str) -> (
    None
):
    """``parse_mount`` never rejects or rewrites a bad mode spelling.

    Plan item 1: a ``"RO"`` survives into ``ParsedMount.mode`` and is
    ``C541``'s to reject — the parser judges only the colon count.

    Arrangement: a 3-part entry with a non-legal mode spelling.
    Action: call ``parse_mount``.
    Assertion: it parses (not ``None``) with the mode verbatim.
    """
    parsed = parse_mount(f"/h:/c:{mode}", config_dir=_CFG, home=_HOME)

    assert parsed is not None
    assert parsed.mode == mode
    assert parsed.mode_defaulted is False


def test_parse_mount_expands_leading_tilde_with_injected_home() -> None:
    """A LEADING ``~`` expands against the injected home (plan item 3).

    Arrangement: ``"~/x:/c"``, the fake home ``/fake/home``.
    Action: call ``parse_mount`` with the ``home`` parameter.
    Assertion: ``host`` is the expanded absolute path.
    """
    parsed = parse_mount("~/x:/c", config_dir=_CFG, home=_HOME)

    assert parsed is not None
    assert parsed.host == "/fake/home/x"
    assert parsed.resolved_host == Path("/fake/home/x")


def test_parse_mount_does_not_expand_mid_string_tilde() -> None:
    """A ``~`` anywhere but the start is a literal character (pinned).

    Plan item 3: "Only a LEADING ``~`` expands" — ``Path.expanduser``
    agrees, and a mid-string ``~`` is a legitimate directory name.

    Arrangement: ``"a~/b:/c"`` with a fake home.
    Action: call ``parse_mount``.
    Assertion: the host keeps the literal ``~`` untouched.
    """
    parsed = parse_mount("a~/b:/c", config_dir=_CFG, home=_HOME)

    assert parsed is not None
    assert parsed.host == "a~/b"
    assert parsed.resolved_host == _CFG / "a~/b"


def test_parse_mount_resolves_relative_host_against_config_dir() -> None:
    """A relative host resolves against the CONFIG dir, lexically.

    Plan item 3: relative hosts resolve against ``config.path.parent``
    (never the tool's ``base_dir``) with normpath semantics.

    Arrangement: ``"data/weights:/c"`` with ``config_dir=/cfg``.
    Action: call ``parse_mount``.
    Assertion: ``resolved_host`` is the absolute ``/cfg/data/weights``.
    """
    parsed = parse_mount("data/weights:/c", config_dir=_CFG, home=_HOME)

    assert parsed is not None
    assert parsed.host == "data/weights"
    assert parsed.resolved_host == Path("/cfg/data/weights")


def test_parse_mount_normalises_dotdot_in_relative_host() -> None:
    """``"a/../b"`` normalises — normpath semantics, no ``resolve()``.

    Arrangement: ``"a/../b:/c"`` with ``config_dir=/cfg``.
    Action: call ``parse_mount``.
    Assertion: ``resolved_host`` is the normalised ``/cfg/b``.
    """
    parsed = parse_mount("a/../b:/c", config_dir=_CFG, home=_HOME)

    assert parsed is not None
    assert parsed.resolved_host == Path("/cfg/b")


def test_parse_mount_absolute_host_resolves_to_itself() -> None:
    """An absolute host is unchanged by resolution (pinned).

    Arrangement: ``"/abs/host:/c"`` with ``config_dir=/cfg``.
    Action: call ``parse_mount``.
    Assertion: ``resolved_host`` equals the authored absolute path.
    """
    parsed = parse_mount("/abs/host:/c", config_dir=_CFG, home=_HOME)

    assert parsed is not None
    assert parsed.resolved_host == Path("/abs/host")


@pytest.mark.parametrize(
    "entry",
    [
        "host",  # 1 part: no colon
        "",  # 1 part: empty
        ":/x",  # 2 parts: empty host
        "/h:",  # 2 parts: empty container
        "/h:/c:",  # 3 parts: empty mode
        "/h:/c:ro:extra",  # 4 parts
        "C:/data:/weights:ro",  # 4 parts: the Windows trap at >=4 parts
    ],
)
def test_parse_mount_returns_none_exactly_for_the_c540_shapes(entry: str) -> (
    None
):
    """``None`` for exactly the seven C540 shapes, and nothing else.

    Plan item 4: the entry parses iff there are exactly 2 or 3 parts and
    every part is non-empty; anything else is unparseable (``TSWAP-C540``).

    Arrangement: each of the seven malformed shapes from the plan table.
    Action: call ``parse_mount``.
    Assertion: ``None`` in every case.
    """
    assert parse_mount(entry, config_dir=_CFG, home=_HOME) is None


def test_parse_mount_is_pure_given_home_and_missing_config_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``home`` injected, no disk and no environment is consulted.

    Plan item 3 and line 1273: the environment read is INJECTED, and the
    resolution is LEXICAL (no disk contact).  Pinned the only way that
    is observable: two identical calls with a fake home and a config
    directory that DOES NOT EXIST return identical results even when
    ``$HOME`` changes between the calls.

    Arrangement: the fake home, the missing config dir, ``$HOME``
    monkeypatched to two different values.
    Action: call ``parse_mount`` once per environment.
    Assertion: both calls return the same, fully-expanded result.
    """
    results: list[ParsedMount | None] = []
    for env_home in ("/somewhere/else", "/yet/another"):
        monkeypatch.setenv("HOME", env_home)
        results.append(
            parse_mount("~/x:/c", config_dir=_MISSING_CFG, home=_HOME)
        )

    assert results[0] is not None
    assert results[0] == results[1]
    assert results[0].host == "/fake/home/x"
    assert results[0].resolved_host == Path("/does/not/exist/x")


# ---------------------------------------------------------------------------
# 2. TSWAP-C540 — unparseable (ERROR; plan item 4)
# ---------------------------------------------------------------------------


def test_c540_unparseable_entry_yields_error_showing_both_forms() -> None:
    """One unparseable entry is one C540 showing BOTH expected forms.

    Plan item 4: the message shows the value found and both expected
    forms verbatim, ``host:container`` and ``host:container:ro|rw``.

    Arrangement: one tool with the colon-less entry; only C540
    registered.
    Action: run ``validate_config``.
    Assertion: exactly one ``TSWAP-C540`` ERROR at
    ``tools.t1.mounts.0`` whose message contains ``host:container`` and
    ``ro`` (both forms shown).
    """
    register(TSWAP_C540_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=["host"])},
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C540"}
    (d,) = by_code["TSWAP-C540"]
    assert d.severity is Severity.ERROR
    assert "host:container" in d.message
    assert "ro" in d.message
    assert d.location.yaml_path == "tools.t1.mounts.0"


@pytest.mark.parametrize(
    "entries",
    [
        ["host", "", ":/x", "/h:", "/h:/c:", "/h:/c:ro:extra",
         "C:/data:/weights:ro"],
    ],
)
def test_c540_each_unparseable_shape_yields_exactly_one_per_entry(
    entries: list[str],
) -> None:
    """Each of the seven shapes yields exactly ONE C540, at its index.

    Plan item 4: suppression is per ENTRY — seven malformed entries in
    one tool yield seven C540s at ``mounts.0``…``mounts.6``, and nothing
    else (all four rules are registered, so this also pins that none of
    the other codes can fire on an entry that did not parse).

    Arrangement: one tool with all seven malformed entries; ALL four
    C54x rules registered.
    Action: run ``validate_config``.
    Assertion: exactly seven diagnostics, all C540, at ``mounts.0``…
    ``mounts.6`` in list order; no C999.
    """
    for rule in _ALL_C54X_RULES:
        register(rule)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=entries)},
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C540"}
    assert len(by_code["TSWAP-C540"]) == 7
    assert [d.location.yaml_path for d in by_code["TSWAP-C540"]] == [
        f"tools.t1.mounts.{i}" for i in range(7)
    ]
    assert "TSWAP-C999" not in by_code


def test_c540_suppresses_c541_c542_and_c543_for_that_entry_only() -> None:
    """A 4-part entry that WOULD also be C541+C542+C543 yields only C540.

    Plan item 5: "``C540`` suppresses ``C541``, ``C542`` and ``C543``
    for that entry … Suppression is per entry, never per tool."  The
    4-part entry ``a:b:BOGUS`` would, if parsed as 3-part, carry a bad
    mode (C541), a relative container (C542) and a missing host (C543) —
    but it did not parse, so only C540 may fire.  The neighbouring
    VALID entry must still be judged (nothing fires on it here).

    Arrangement: one tool with ``["a:b:BOGUS", "/exists:/c"]``, the
    probe answering ``is_dir`` for ``/exists``; ALL four rules
    registered.
    Action: run ``validate_config``.
    Assertion: exactly one diagnostic — the C540 at ``mounts.0``; no
    C541, C542 or C543 anywhere; no C999.
    """
    for rule in _ALL_C54X_RULES:
        register(rule)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=["a:b:BOGUS", "/exists:/c"])},
        probe=_FakeProbe(dirs={Path("/exists"): True}),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C540"}
    (d,) = by_code["TSWAP-C540"]
    assert d.location.yaml_path == "tools.t1.mounts.0"
    assert "TSWAP-C999" not in by_code


def test_c540_non_string_entries_are_skipped_silently() -> None:
    """Non-string entries are skipped by all four rules (no C999).

    Plan item 4: non-string entries are a schema-layer ``TSWAP-C105``
    (``list[str]``); re-reporting them per rule would bury the schema's
    message.

    Arrangement: one tool with ``mounts=[123, "/exists:/c"]`` (an int
    entry alongside a valid one); the probe answers ``is_dir`` for
    ``/exists``; ALL four rules registered.
    Action: run ``validate_config``.
    Assertion: an empty report — the int is skipped silently and the
    valid entry is clean.
    """
    for rule in _ALL_C54X_RULES:
        register(rule)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=[123, "/exists:/c"])},
        probe=_FakeProbe(dirs={Path("/exists"): True}),
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_non_list_mounts_are_skipped_silently_by_all_four_rules() -> None:
    """A non-list ``mounts`` value is skipped silently (C105 owns it).

    Plan item 4: "a ``mounts: "x"`` is [a C105] too; re-reporting either
    per rule would bury the schema's message."

    Arrangement: one tool with ``mounts="x"`` (a string, not a list);
    ALL four rules registered.
    Action: run ``validate_config``.
    Assertion: an empty report and no C999.
    """
    for rule in _ALL_C54X_RULES:
        register(rule)
    cfg = _config(
        tools={"t1": _tool("t1", mounts="x")},
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


# ---------------------------------------------------------------------------
# 3. TSWAP-C541 — a mode outside {ro, rw} (ERROR; plan item 5)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["RO", "Rw", "rw2", "r"])
def test_c541_mode_outside_ro_rw_errors_naming_mode_and_legal_values(
    mode: str,
) -> None:
    """A non-legal mode is one C541 naming the mode and both legal values.

    Plan item 5 (A18): matched EXACTLY and case-sensitively — ``:RO`` is
    a C541, not a synonym.  The message names the offending mode with
    ``repr`` and lists the two legal values.

    Arrangement: one tool with ``/h:/c:<mode>``; only C541 registered.
    Action: run ``validate_config``.
    Assertion: exactly one C541 ERROR at ``tools.t1.mounts.0`` whose
    message contains ``repr(mode)`` and both ``ro`` and ``rw``.
    """
    register(TSWAP_C541_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=[f"/h:/c:{mode}"])},
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C541"}
    (d,) = by_code["TSWAP-C541"]
    assert d.severity is Severity.ERROR
    assert repr(mode) in d.message
    assert "ro" in d.message
    assert "rw" in d.message
    assert d.location.yaml_path == "tools.t1.mounts.0"


@pytest.mark.parametrize("mode", ["ro", "rw"])
def test_c541_legal_modes_produce_nothing(mode: str) -> None:
    """``:ro`` and ``:rw`` are the only legal modes — nothing fires.

    Arrangement: one tool with the 3-part entry in each legal mode;
    only C541 registered.
    Action: run ``validate_config``.
    Assertion: an empty report in both cases.
    """
    register(TSWAP_C541_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=[f"/h:/c:{mode}"])},
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c541_two_part_entry_with_defaulted_mode_never_fires() -> None:
    """A 2-part entry (mode defaulted) can NEVER be a C541 (pinned).

    Plan item 5: the rule judges the third part of a 3-part entry; when
    the mode was defaulted by the parser there is nothing to judge.

    Arrangement: one tool with ``/h:/c`` (2 parts); only C541
    registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C541_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=["/h:/c"])},
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c541_and_c542_are_independent_and_both_fire() -> None:
    """A bad mode AND a relative container on ONE entry yield BOTH.

    Plan item 6: "``C541`` and ``C542`` are independent and BOTH may
    fire on one entry — they judge different parts of the string."

    Arrangement: one tool with ``/h:relative-path:BOGUS``; C541 and
    C542 registered.
    Action: run ``validate_config``.
    Assertion: exactly one C541 and one C542, both at ``mounts.0``.
    """
    register(TSWAP_C541_RULE)
    register(TSWAP_C542_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=["/h:relative-path:BOGUS"])},
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C541", "TSWAP-C542"}
    assert [d.location.yaml_path for d in by_code["TSWAP-C541"]] == [
        "tools.t1.mounts.0"
    ]
    assert [d.location.yaml_path for d in by_code["TSWAP-C542"]] == [
        "tools.t1.mounts.0"
    ]


def test_c541_windows_three_part_entry_is_c541_not_c540() -> None:
    """``C:/data:/weights`` (3 parts) parses: C541 only, no C542, no C540.

    Plan item 5 (plan correction, 2026-08-19): the 3-part Windows
    spelling splits into ``host="C"``, ``container="/data"``,
    ``mode="/weights"`` — it is a C541 (the mode ``"/weights"`` is not
    ``ro``/``rw``), NOT a C540.  The container ``/data`` IS absolute, so
    no C542.  Detecting it as C540 would require a "drive letter?"
    heuristic the colon-count parser deliberately does not have.

    Arrangement: one tool with that entry; C540, C541 and C542
    registered.
    Action: run ``validate_config``.
    Assertion: exactly one diagnostic — the C541 at ``mounts.0`` naming
    the mode ``'/weights'`` and both legal values; no C540, no C542.
    """
    register(TSWAP_C540_RULE)
    register(TSWAP_C541_RULE)
    register(TSWAP_C542_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=["C:/data:/weights"])},
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C541"}
    (d,) = by_code["TSWAP-C541"]
    assert "'/weights'" in d.message
    assert "ro" in d.message
    assert "rw" in d.message
    assert d.location.yaml_path == "tools.t1.mounts.0"


def test_c541_and_c542_both_fire_on_windows_three_part_with_relative_container(
) -> None:
    """A 3-part Windows entry with a NON-absolute container: C541 + C542.

    The second Windows pin (task): ``C:dir:/weights`` splits into
    ``host="C"``, ``container="dir"``, ``mode="/weights"`` — the mode is
    not ``ro``/``rw`` AND the container is not absolute, so both errors
    fire on the same entry (the honest picture: a colon was eaten).

    Arrangement: one tool with that entry; C541 and C542 registered.
    Action: run ``validate_config``.
    Assertion: exactly one C541 and one C542, both at ``mounts.0``.
    """
    register(TSWAP_C541_RULE)
    register(TSWAP_C542_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=["C:dir:/weights"])},
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C541", "TSWAP-C542"}
    assert len(by_code["TSWAP-C541"]) == 1
    assert len(by_code["TSWAP-C542"]) == 1
    for d in report.diagnostics:
        assert d.location.yaml_path == "tools.t1.mounts.0"


# ---------------------------------------------------------------------------
# 4. TSWAP-C542 — a non-absolute container path (ERROR; plan item 6)
# ---------------------------------------------------------------------------


def test_c542_relative_container_path_errors() -> None:
    """A container part not starting with ``/`` is one C542.

    Plan item 6: Docker requires an absolute destination.

    Arrangement: one tool with ``/h:relative/path``; only C542
    registered.
    Action: run ``validate_config``.
    Assertion: exactly one C542 ERROR at ``tools.t1.mounts.0``.
    """
    register(TSWAP_C542_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=["/h:relative/path"])},
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C542"}
    (d,) = by_code["TSWAP-C542"]
    assert d.severity is Severity.ERROR
    assert d.location.yaml_path == "tools.t1.mounts.0"


def test_c542_absolute_container_path_produces_nothing() -> None:
    """An absolute container path is the legal shape — nothing fires.

    Arrangement: one tool with ``/h:/abs``; only C542 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C542_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=["/h:/abs"])},
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


@pytest.mark.parametrize(
    "entry",
    [
        "/h:C",  # the drive-letter part of a Windows-style "C:/x"
        "/h:data",  # bare relative name
        "/h:./data",  # dot-prefixed relative
        "/h:\\data",  # backslash path (no colon inside the part)
    ],
)
def test_c542_windows_style_and_relative_container_parts_error(
    entry: str,
) -> None:
    """Every non-``/``-prefixed container part is a C542 (pinned).

    Plan item 6: "Windows-style container paths are unsupported, and the
    message says so rather than pretending the value might work."  A
    Windows-style ``C:/x`` authored in the container position is split
    by the parser at the drive-letter colon, so the container PART is
    ``C`` (the remainder becomes the mode) — the part does not start
    with ``/`` and fails.  ``\\data`` is the plan's own example.

    Arrangement: one tool per container part; only C542 registered.
    Action: run ``validate_config``.
    Assertion: exactly one C542 at ``tools.t1.mounts.0`` in every case.
    """
    register(TSWAP_C542_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=[entry])},
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C542"}
    (d,) = by_code["TSWAP-C542"]
    assert d.location.yaml_path == "tools.t1.mounts.0"


# ---------------------------------------------------------------------------
# 5. TSWAP-C543 — the host path does not exist (WARNING; plan item 7)
# ---------------------------------------------------------------------------


def test_c543_missing_host_yields_warning_naming_resolved_path() -> None:
    """Both predicates False → one C543 WARNING naming the resolved host.

    Plan item 7: fires when ``probe.is_file`` AND ``probe.is_dir`` are
    both false; WARNING (never an error — the path may be created later);
    the message names the resolved host path.

    Arrangement: one tool with ``/missing:/c``; the probe answers
    False/False for everything; only C543 registered.
    Action: run ``validate_config``.
    Assertion: exactly one C543 WARNING at ``tools.t1.mounts.0`` whose
    message contains ``/missing``.
    """
    register(TSWAP_C543_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=["/missing:/c"])},
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {"TSWAP-C543"}
    (d,) = by_code["TSWAP-C543"]
    assert d.severity is Severity.WARNING
    assert "/missing" in d.message
    assert d.location.yaml_path == "tools.t1.mounts.0"


def test_c543_remedy_contains_pinned_host_vs_router_trap_phrase() -> None:
    """The C543 remedy names the host-vs-router-container trap (pinned).

    Plan item 7: the pinned assertable phrase is *host paths
    interpreted by the Docker daemon, not paths inside the router
    container* — without it the warning reads as "you typed the path
    wrong", when the actual cause is usually "the path is right, but
    you are reading it from inside the router".

    Arrangement: one tool with ``/missing:/c``; only C543 registered.
    Action: run ``validate_config`` and read the remedy.
    Assertion: the remedy contains the pinned phrase.
    """
    register(TSWAP_C543_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=["/missing:/c"])},
        probe=_FakeProbe(),
    )

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert _C543_TRAP_PHRASE in d.remedy


def test_c543_existing_directory_satisfies_no_warning() -> None:
    """A host that IS a directory satisfies existence — no C543.

    Plan item 7: "Either predicate satisfies existence" (weights caches
    are legitimately directories).

    Arrangement: one tool with ``/weights:/c``; the probe answers
    ``is_dir=True`` for ``/weights``; only C543 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C543_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=["/weights:/c"])},
        probe=_FakeProbe(dirs={Path("/weights"): True}),
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c543_existing_file_satisfies_no_warning() -> None:
    """A host that IS a file satisfies existence — no C543.

    Plan item 7: a single model file or socket path is a legitimate
    bind source.

    Arrangement: one tool with ``/var/run/docker.sock:/c``; the probe
    answers ``is_file=True`` for that path; only C543 registered.
    Action: run ``validate_config``.
    Assertion: an empty report.
    """
    register(TSWAP_C543_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=["/var/run/docker.sock:/c"])},
        probe=_FakeProbe(files={Path("/var/run/docker.sock"): True}),
    )

    report = validate_config(cfg)

    assert report.diagnostics == ()


def test_c543_relative_host_warning_names_the_absolute_resolution() -> None:
    """A relative host's warning names the ABSOLUTE resolved result.

    Plan item 7: the message names ``str(m.resolved_host)`` — so a
    relative resolution is visible in absolute form (pinned: the
    message contains the resolved absolute path, not the authored
    relative one).

    Arrangement: one tool with ``data/model:/c`` and the config at
    ``/cfg/tools.yaml`` (resolution base ``/cfg``); the probe answers
    False/False; only C543 registered.
    Action: run ``validate_config``.
    Assertion: one C543 whose message contains ``/cfg/data/model``.
    """
    register(TSWAP_C543_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=["data/model:/c"])},
        probe=_FakeProbe(),
        path=_CFG_PATH,
    )

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert d.code == "TSWAP-C543"
    assert "/cfg/data/model" in d.message


def test_c543_tilde_host_warning_names_the_expanded_path() -> None:
    """A ``~`` host's warning names the EXPANDED result (pinned).

    Plan item 7: the message names ``str(m.resolved_host)``, so the
    ``~`` expansion is visible too.

    Arrangement: one tool with ``~/models:/c``; ``home=/fake/home``
    injected; the probe answers False/False; only C543 registered.
    Action: run ``validate_config``.
    Assertion: one C543 whose message contains ``/fake/home/models``.
    """
    register(TSWAP_C543_RULE)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=["~/models:/c"])},
        probe=_FakeProbe(),
        home=_HOME,
    )

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert d.code == "TSWAP-C543"
    assert "/fake/home/models" in d.message


# ---------------------------------------------------------------------------
# 6. Cross-rule pins: only-own-codes, one report, and the location
# ---------------------------------------------------------------------------


def test_valid_mount_with_existing_host_trips_no_c54x() -> None:
    """A well-formed mount whose host exists trips no C54x (and no C999).

    Only-own-codes pin: all four rules together must stay silent on the
    legal shape — parseable, legal (defaulted) mode, absolute container,
    existing host.

    Arrangement: one tool with ``["/exists:/c"]``; the probe answers
    ``is_dir=True`` for ``/exists``; ALL four rules registered.
    Action: run ``validate_config``.
    Assertion: no C54x code (and no C999) in the report.
    """
    for rule in _ALL_C54X_RULES:
        register(rule)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=["/exists:/c"])},
        probe=_FakeProbe(dirs={Path("/exists"): True}),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert not any(code.startswith("TSWAP-C54") for code in by_code)
    assert "TSWAP-C999" not in by_code


def test_one_tool_yields_c540_c541_c542_and_c543_in_a_single_report() -> (
    None
):
    """All four codes from one tool land in ONE report, at mounts.0…3.

    The "report every finding at once" contract applied to behaviour
    17: each entry in the list trips exactly one different code —
    ``bad`` (C540, 1 part), ``/h:/c:RO`` (C541, bad case-sensitive
    mode), ``/h:rel`` (C542, relative container) and ``/missing:/c``
    (C543, missing host) — with ``/h`` existing so C543 stays out of
    entries 1 and 2.

    Arrangement: one tool with those four entries; the probe answers
    ``is_dir=True`` for ``/h``; ALL four rules registered.
    Action: run ``validate_config``.
    Assertion: exactly one diagnostic per code, at ``mounts.0``…
    ``mounts.3`` respectively; no other codes, no C999.
    """
    for rule in _ALL_C54X_RULES:
        register(rule)
    cfg = _config(
        tools={
            "t1": _tool(
                "t1", mounts=["bad", "/h:/c:RO", "/h:rel", "/missing:/c"]
            )
        },
        probe=_FakeProbe(dirs={Path("/h"): True}),
    )

    report = validate_config(cfg)

    by_code = _diagnostics_by_code(report)
    assert set(by_code) == {
        "TSWAP-C540",
        "TSWAP-C541",
        "TSWAP-C542",
        "TSWAP-C543",
    }
    assert len(report.diagnostics) == 4
    assert by_code["TSWAP-C540"][0].location.yaml_path == "tools.t1.mounts.0"
    assert by_code["TSWAP-C541"][0].location.yaml_path == "tools.t1.mounts.1"
    assert by_code["TSWAP-C542"][0].location.yaml_path == "tools.t1.mounts.2"
    assert by_code["TSWAP-C543"][0].location.yaml_path == "tools.t1.mounts.3"
    assert "TSWAP-C999" not in by_code


# ---------------------------------------------------------------------------
# 7. The rule objects and the append order (plan items 10 and 11)
# ---------------------------------------------------------------------------


def test_rule_objects_carry_expected_ids_and_severities() -> None:
    """Each rule instance carries its id, severity, and a remedy.

    Plan item 10: "``C540`` ERROR; ``C541`` ERROR; ``C542`` ERROR;
    ``C543`` WARNING … Every ``remedy`` is non-empty."

    Arrangement: the four rule objects imported from ``validate``.
    Action: read back ``id``, ``severity`` and ``remedy``.
    Assertion: ids are ``TSWAP-C540``…``TSWAP-C543`` in that order; the
    first three are ERROR, ``TSWAP-C543`` is WARNING, and every remedy
    is a non-empty string.
    """
    rules = _ALL_C54X_RULES

    assert [rule.id for rule in rules] == list(_BEHAVIOUR_17_IDS)
    assert [rule.severity for rule in rules] == [
        Severity.ERROR,
        Severity.ERROR,
        Severity.ERROR,
        Severity.WARNING,
    ]
    for rule in rules:
        assert isinstance(rule.remedy, str)
        assert rule.remedy.strip() != ""


def test_builtin_rules_append_the_behaviour_17_codes_in_code_order() -> (
    None
):
    """The four rules are appended to ``BUILTIN_RULES`` after 16.

    Plan item 11: all four are appended in code order after behaviour
    16's seven — 34 landed rules in total — and their *identity* is what
    ``register_builtin_rules()`` relies on for idempotency, so the tuple
    must hold the very module-level singletons.

    The position is asserted **relative to the earlier blocks**, not
    tail-anchored or by total count (the index-anchored pattern of
    behaviours 13/14/15/16): a later behaviour may append more rules
    without breaking this pin.

    Arrangement: the ``BUILTIN_RULES`` tuple.
    Action: locate the first behaviour-17 id; check object identity per
    rule.
    Assertion: the first C540 id sits at index
    ``len(_BEHAVIOUR_12_IDS) + len(_BEHAVIOUR_13_IDS) +
    len(_BEHAVIOUR_14_IDS) + len(_BEHAVIOUR_15_IDS) +
    len(_BEHAVIOUR_16_IDS)`` (immediately after the seven C52x/C53x
    codes), the four ids from there are a contiguous, in-code-order
    block, and each rule constant is an element of the tuple.
    """
    ids = [rule.id for rule in BUILTIN_RULES]

    first_c540 = ids.index(_BEHAVIOUR_17_IDS[0])
    assert first_c540 == (
        len(_BEHAVIOUR_12_IDS)
        + len(_BEHAVIOUR_13_IDS)
        + len(_BEHAVIOUR_14_IDS)
        + len(_BEHAVIOUR_15_IDS)
        + len(_BEHAVIOUR_16_IDS)
    )
    assert ids[first_c540 : first_c540 + len(_BEHAVIOUR_17_IDS)] == list(
        _BEHAVIOUR_17_IDS
    )
    for constant in _ALL_C54X_RULES:
        assert any(rule is constant for rule in BUILTIN_RULES)


# ---------------------------------------------------------------------------
# 8. The location contract (plan item 9)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "entry", "probe_dirs", "home"),
    [
        (TSWAP_C540_RULE, "host", {}, None),
        (TSWAP_C541_RULE, "/h:/c:RO", {Path("/h"): True}, None),
        (TSWAP_C542_RULE, "/h:rel", {Path("/h"): True}, None),
        (TSWAP_C543_RULE, "/missing:/c", {}, None),
    ],
)
@pytest.mark.parametrize("line", [42, None])
def test_location_contract_per_code(
    rule: Rule,
    entry: str,
    probe_dirs: dict[Path, bool],
    home: Path | None,
    line: int | None,
) -> None:
    """Every C54x location consults ``line_for`` and ``config.path``.

    Plan item 9: ``Location(file=str(config.path), yaml_path=
    tools.<key>.mounts.<i>, line=config.line_for(<the same string>))`` —
    the file is never hardcoded, ``line=None`` is a legal outcome, so
    the test asserts the RELATION
    ``location.line == config.line_for(location.yaml_path)``, never a
    hardcoded line number; both a fixed-int ``line_for`` and a
    ``None``-returning one are pinned.  ``<i>`` is the 0-based
    dotted-numeric index into the resolved list.

    Arrangement: one offending entry per code, a non-default path, and
    a ``line_for`` returning the parametrized value for any dotted path.
    Action: run only the parametrized rule.
    Assertion: exactly one diagnostic; its file is ``str(config.path)``,
    its yaml_path is ``tools.t1.mounts.0``, and its line equals
    ``config.line_for(yaml_path)``.
    """
    register(rule)
    cfg = _config(
        tools={"t1": _tool("t1", mounts=[entry])},
        probe=_FakeProbe(dirs=probe_dirs),
        line_for=(lambda _p, _line=line: _line),
        path=Path("my-config.yaml"),
        home=home,
    )

    report = validate_config(cfg)

    (d,) = report.diagnostics
    assert d.location.file == "my-config.yaml"
    assert d.location.yaml_path == "tools.t1.mounts.0"
    assert d.location.line == cfg.line_for(d.location.yaml_path)

"""
Behaviour 25 (RED) — the generated config reference and troubleshooting table.

Executable form of ``plans/m1-configuration.md`` behaviour 25 and its
"Confirmed contract details (2026-08-21)" block (items 3, 5, 6, 9).
Assumption A28 (recorded on the issue) pins the reading: the
troubleshooting table's cause/fix prose is AUTHORED data in the
generator; the code column is validated against the emitted set from
both directions, and the 41 rule rows' fix column is read verbatim
from ``Rule.remedy``.

Expected RED shape (plan item 9, pinned so red is verified, not
interpreted):

- ``test_the_reference_document_is_committed`` fails: ``docs/
  configuration.md`` is a GREEN artifact and is absent at red;
- ``test_the_generator_script_is_committed`` fails: ``scripts/
  gen_config_reference.py`` is a GREEN artifact and is absent at red;
- ``test_every_model_field_has_a_description`` fails as a 72-item
  assertion against the SHIPPED ``schema.py`` (85 fields across 8
  models, 13 already described, 72 not) — the D19 completeness guard;
- ``test_the_non_rule_code_literals_are_still_accurate`` PASSES at
  red by design: it re-derives the 21 non-rule ``TSWAP-C*`` codes
  from the five shipped modules' ``vars()`` and asserts the equality
  with the literal — a property of shipped code, the one test that
  turns green without any green-step work;
- the remaining five tests (identity, no absolute path or timestamp,
  both directions of table coverage, rule remedy verbatim, and the
  required-field em dash) fail with an ``ImportError`` raised INSIDE
  the test body — the HARD lazy-import rule: no module-level
  ``import scripts.*``, so the missing generator module is a failed
  test, never a collection error.

GREEN lands ``scripts/gen_config_reference.py``, the generated
``docs/configuration.md``, and the 72 ``Field(description=...)``
additions in ``src/tool_swap/config/schema.py`` — none of which
belongs in this file.
"""

from __future__ import annotations

import re
from pathlib import Path

from tool_swap.config.schema import (
    BackendConfig,
    BuildConfig,
    DefaultsConfig,
    GroupConfig,
    RootConfig,
    RouterConfig,
    ToolConfig,
    ToolYamlConfig,
)

ROOT = Path(__file__).resolve().parents[3]
GENERATOR = ROOT / "scripts" / "gen_config_reference.py"
REFERENCE = ROOT / "docs" / "configuration.md"

#: The models the reference must cover; top-level ``model_fields``
#: only, in declaration order (plan item 2: 85 fields across 8 models).
_MODELS = (
    RootConfig,
    RouterConfig,
    BackendConfig,
    DefaultsConfig,
    GroupConfig,
    ToolConfig,
    BuildConfig,
    ToolYamlConfig,
)

#: The 21 non-rule C-codes, copied verbatim from plan item 4's table:
#: 22 ``_CODE_*`` / ``_INTERNAL_RULE_CODE`` constants across five
#: modules, but ``TSWAP-C001`` is claimed by two emitters — the
#: loader's YAML-syntax error (loader.py:60) and the schema's
#: unsupported-version error (schema.py:37) — so 21 distinct codes.
NON_RULE_C_CODES = frozenset(
    {
        "TSWAP-C000",  # _CODE_NOT_FOUND (loader.py:59)
        "TSWAP-C001",  # _CODE_SYNTAX (loader.py:60) / _CODE_UNSUPPORTED_VERSION (schema.py:37)
        "TSWAP-C002",  # _CODE_DUPLICATE (loader.py:61)
        "TSWAP-C003",  # _CODE_EMPTY (loader.py:62)
        "TSWAP-C004",  # _CODE_NON_MAPPING (loader.py:63)
        "TSWAP-C005",  # _CODE_MISSING_TOOL_YAML (loader.py:64)
        "TSWAP-C006",  # _CODE_PATH_IS_FILE (loader.py:65)
        "TSWAP-C007",  # _CODE_RECURSION (loader.py:66)
        "TSWAP-C010",  # _CODE_MISSING (interpolate.py:23)
        "TSWAP-C011",  # _CODE_ENV_FILE_MISSING (loader.py:67)
        "TSWAP-C012",  # _CODE_ENV_PARSE (loader.py:68)
        "TSWAP-C013",  # _CODE_UNCLOSED (interpolate.py:24)
        "TSWAP-C101",  # _CODE_UNKNOWN_KEY (schema.py:38)
        "TSWAP-C104",  # _CODE_DEVICES_AS_COUNT (schema.py:39)
        "TSWAP-C105",  # _CODE_INVALID_SHAPE (schema.py:40)
        "TSWAP-C106",  # _CODE_UNMAPPED_KEY (resolver.py:25)
        "TSWAP-C201",  # _CODE_NAME_MISMATCH (loader.py:69)
        "TSWAP-C202",  # _CODE_SHARED_PATH (loader.py:70)
        "TSWAP-C501",  # _CODE_BAD_TTL (resolver.py:23)
        "TSWAP-C503",  # _CODE_DUPLICATE_MOUNT (resolver.py:24)
        "TSWAP-C999",  # _INTERNAL_RULE_CODE (validate.py:52)
    }
)

_TROUBLESHOOTING_HEADING = "## Troubleshooting: every diagnostic code"
_CODE_CELL = re.compile(r"TSWAP-[CS]\d{3}")
_C_CODE_VALUE = re.compile(r"TSWAP-C\d{3}")
_TIMESTAMP = re.compile(r"\b(?:19|20)\d{2}[/-]\d{1,2}[/-]\d{1,2}\b")
_GENERATED_WITH_DATE = re.compile(
    r"^.*[Gg]enerated.*\b(?:19|20)\d{2}\b.*$",
    re.MULTILINE,
)


def _derive_non_rule_codes() -> frozenset[str]:
    """Re-derive the non-rule C-code set from the shipped modules.

    Walks ``vars()`` of the five emitter modules for the private
    ``_CODE_*`` / ``_INTERNAL_RULE_CODE`` string constants whose value
    matches ``TSWAP-C\\d{3}`` (plan item 4's enumeration, kept
    complete by this re-derivation).

    Returns:
        The frozenset of non-rule C-codes the shipped code can emit.
    """
    from tool_swap.config import interpolate, loader, resolver, schema, validate

    derived: set[str] = set()
    for module in (loader, interpolate, schema, resolver, validate):
        for name, value in vars(module).items():
            is_code_name = name.startswith("_CODE_") or name == "_INTERNAL_RULE_CODE"
            if is_code_name and isinstance(value, str) and _C_CODE_VALUE.fullmatch(value):
                derived.add(value)
    return frozenset(derived)


def _emitted_codes() -> frozenset[str]:
    """Compute the emitted code set independently of the generator.

    Plan item 4: the 41 rule codes walked from ``BUILTIN_RULES``, the
    14 S-codes walked from ``compile``'s ``TSWAP_S*`` constants, and
    the 21 non-rule C-codes from the pinned literal — 76 distinct
    codes, which is why ``CODE_TABLE`` has 76 rows.

    Returns:
        The frozenset of every code the codebase can emit.
    """
    import tool_swap.schema.compile as compile_mod
    from tool_swap.config.validate import BUILTIN_RULES

    rule_codes = {rule.id for rule in BUILTIN_RULES}
    s_codes = {v for k, v in vars(compile_mod).items() if k.startswith("TSWAP_S")}
    return frozenset(rule_codes | s_codes | NON_RULE_C_CODES)


def _parse_troubleshooting_rows(text: str) -> dict[str, str]:
    """Extract the troubleshooting table from the rendered document.

    Args:
        text: The full rendered reference (``render_reference()``).

    Returns:
        A mapping of ``code -> fix`` for every row under the pinned
        heading; the code cell's backticks are stripped. Returns ``{}``
        when the heading is absent (a structural rot the identity
        test would also catch).
    """
    lines = text.splitlines()
    if _TROUBLESHOOTING_HEADING not in lines:
        return {}
    rows: dict[str, str] = {}
    started = lines.index(_TROUBLESHOOTING_HEADING)
    for line in lines[started + 1 :]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 3:
            continue
        code = cells[0].strip("`")
        if not _CODE_CELL.fullmatch(code):
            continue  # the header row and the ``|---|`` separator
        rows[code] = cells[2]
    return rows


# ---------------------------------------------------------------------------
# 1 and 3 — the committed GREEN artifacts exist and are non-empty
# ---------------------------------------------------------------------------


def test_the_reference_document_is_committed() -> None:
    """``docs/configuration.md`` is committed and non-empty (plan item 6)."""
    assert REFERENCE.is_file(), f"missing {REFERENCE.relative_to(ROOT)}"
    assert REFERENCE.read_text(encoding="utf-8").strip(), (
        f"{REFERENCE.name} is empty"
    )


def test_the_generator_script_is_committed() -> None:
    """``scripts/gen_config_reference.py`` is committed and non-empty."""
    assert GENERATOR.is_file(), f"missing {GENERATOR.relative_to(ROOT)}"
    assert GENERATOR.read_text(encoding="utf-8").strip(), (
        f"{GENERATOR.name} is empty"
    )


# ---------------------------------------------------------------------------
# 2 — the D19 completeness guard against the SHIPPED schema
# ---------------------------------------------------------------------------


def test_every_model_field_has_a_description() -> None:
    """Every field on every model carries a non-empty description.

    Walks only the top-level ``model_fields`` of the eight models (not
    sub-models), in declaration order. At red this fails with 72
    offenders against the shipped ``schema.py``.
    """
    offenders = [
        f"{model.__name__}.{name}"
        for model in _MODELS
        for name, field in model.model_fields.items()
        if not (field.description or "").strip()
    ]
    assert not offenders, (
        f"{len(offenders)} model fields lack a non-empty "
        f"Field(description=...): {', '.join(offenders)}"
    )


# ---------------------------------------------------------------------------
# 4 — the identity / anti-rot test
# ---------------------------------------------------------------------------


def test_the_committed_reference_is_up_to_date() -> None:
    """The committed document equals a fresh ``render_reference()``."""
    import scripts.gen_config_reference as gen  # noqa: PLC0415

    assert REFERENCE.is_file(), f"missing {REFERENCE}"
    rendered = gen.render_reference()
    assert rendered == REFERENCE.read_text(encoding="utf-8"), (
        "docs/configuration.md has drifted from the schema — run "
        "python scripts/gen_config_reference.py"
    )


# ---------------------------------------------------------------------------
# 5 — deterministic: no absolute paths, no timestamps
# ---------------------------------------------------------------------------


def test_the_reference_has_no_absolute_paths_or_timestamps() -> None:
    """The rendered reference names no absolute path and no timestamp.

    The mechanical form of *"generation must be deterministic"*: no
    ``/home/`` or ``/workspaces/`` prefix, no ``__file__``-derived
    absolute path, no ``YYYY-MM-DD``-style date, and no ``Generated``
    line carrying a year.
    """
    import scripts.gen_config_reference as gen  # noqa: PLC0415

    text = gen.render_reference()
    assert "/home/" not in text, "an absolute home path leaked into the reference"
    assert "/workspaces/" not in text, "a workspace path leaked into the reference"
    assert "__file__" not in text, "a __file__-derived path leaked into the reference"
    assert _TIMESTAMP.search(text) is None, "a timestamp leaked into the reference"
    assert _GENERATED_WITH_DATE.search(text) is None, (
        "a dated 'Generated' banner leaked into the reference"
    )


# ---------------------------------------------------------------------------
# 6 and 8 — table coverage in both directions (anti-rot)
# ---------------------------------------------------------------------------


def test_every_emitted_code_has_a_troubleshooting_row() -> None:
    """Every code the codebase can emit has a table row."""
    import scripts.gen_config_reference as gen  # noqa: PLC0415

    rows = _parse_troubleshooting_rows(gen.render_reference())
    missing = sorted(_emitted_codes() - set(rows))
    assert not missing, (
        "emitted codes with no troubleshooting row: " + ", ".join(missing)
    )


def test_every_troubleshooting_row_is_an_emitted_code() -> None:
    """No phantom rows: every table row is a code the codebase emits."""
    import scripts.gen_config_reference as gen  # noqa: PLC0415

    rows = _parse_troubleshooting_rows(gen.render_reference())
    phantom = sorted(set(rows) - _emitted_codes())
    assert not phantom, (
        "rows for codes the codebase never emits: " + ", ".join(phantom)
    )


# ---------------------------------------------------------------------------
# 7 — the literal's own anti-rot guard (PASSES AT RED by design)
# ---------------------------------------------------------------------------


def test_the_non_rule_code_literals_are_still_accurate() -> None:
    """``NON_RULE_C_CODES`` equals the codes the shipped modules emit.

    Re-derived from the five modules' ``vars()`` — a property of
    SHIPPED code, so this test passes at red without any green-step
    work: a new ``_CODE_*`` constant in ``loader.py`` would fail here
    by name.
    """
    assert _derive_non_rule_codes() == NON_RULE_C_CODES


# ---------------------------------------------------------------------------
# 9 — the 41 rule rows' fix column is ``Rule.remedy`` verbatim
# ---------------------------------------------------------------------------


def test_the_rule_rows_fix_matches_the_rule_remedy() -> None:
    """Each rule row's fix column equals ``rule.remedy`` verbatim.

    Pins item 5's *"the fix column is read from code"* claim: a remedy
    edit in ``validate.py`` shows up as a docs diff here.
    """
    import scripts.gen_config_reference as gen  # noqa: PLC0415
    from tool_swap.config.validate import BUILTIN_RULES

    rows = _parse_troubleshooting_rows(gen.render_reference())
    mismatches = [
        f"{rule.id}: table fix {rows.get(rule.id)!r} != remedy {rule.remedy!r}"
        for rule in BUILTIN_RULES
        if rows.get(rule.id) != rule.remedy
    ]
    assert not mismatches, "; ".join(mismatches)


# ---------------------------------------------------------------------------
# 10 — the one required field renders the em-dash "no default" marker
# ---------------------------------------------------------------------------


def test_the_single_required_field_renders_a_dash() -> None:
    """The em dash ``—`` appears exactly once in the rendered reference.

    ``BuildConfig.context`` is the only required field in the whole
    schema (detected with ``FieldInfo.is_required()``), so the
    "no default" marker appears exactly once — plan item 3.
    """
    import scripts.gen_config_reference as gen  # noqa: PLC0415

    text = gen.render_reference()
    assert text.count("—") == 1, (
        f"the em-dash 'no default' marker appears {text.count('—')} times; "
        "exactly one required field (BuildConfig.context) is expected"
    )

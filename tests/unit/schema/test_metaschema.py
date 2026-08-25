"""RED tests for M1 behaviour 20 — validate_against_metaschema (corpus 11).

Executable form of ``plans/m1-configuration.md`` behaviour 20's "Confirmed
contract details (2026-08-19)" block, item 9 (and the corpus-11 row of the
corpus table): ``validate_against_metaschema(schema)`` checks every
compiled schema — including a passed-through ``json_schema:`` — against
the JSON Schema 2020-12 meta-schema, one ``TSWAP-S140`` ERROR per yielded
meta-schema error, quoting the validator's own ``json_path`` and message.

Contract pinned here (item 9):

- Returns a **list**, empty when valid; never raises.
- Uses ``Draft202012Validator(Draft202012Validator.META_SCHEMA).
  iter_errors(schema)`` — **not** ``check_schema`` (which raises on the
  first problem).  Two independent mistakes yield two ``S140``s.
- Each message quotes the validator's ``json_path`` (the
  ``$.properties.x.type`` form) **and** its ``message``.
- ``compile_tool_schema`` does **not** call it internally — this is a
  separate, explicitly-invoked step (behaviour 21's: compile first, then
  meta-schema-validate whatever halves came back non-None).
- The **deprecation trap** (item 16, shipped-test survey): a
  passed-through block with an unknown ``$schema`` must validate with NO
  ``DeprecationWarning`` — the implementation must construct
  ``Draft202012Validator`` explicitly rather than going through
  ``validator_for``/``validate``, which would warn (verified against
  jsonschema 4.26: ``validators.validator_for`` does raise
  ``DeprecationWarning`` on an unknown ``$schema``; the explicit
  constructor does not).

``src/tool_swap/schema/compile.py`` does not exist yet, so this module
fails collection with a single clean ``ImportError`` naming exactly one
missing name (``TSWAP_S140``, the first import below).  Every test body
pins a concrete behaviour the GREEN step must satisfy.

Corpus-7 and corpus-9 snapshots are compiled here by importing the
authored blocks from ``test_compile_snapshots`` (the same module the
corpus-11 row applies to — "compiled **and** passed-through schemas");
corpus-10 pass-through blocks are constructed locally.

Conventions: AAA, Google docstrings, snake_case, ``from __future__ import
annotations``.  Pure-function tests only; no fixtures/registration; no
``importlib.reload``.
"""

from __future__ import annotations

import warnings
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from jsonschema import validators as _jsonschema_validators

from tests.unit.schema.test_compile_snapshots import (
    EMBEDDING_OUTPUTS,
    RAW_JSON_SCHEMA,
    SECTION_84_INPUTS,
)

from tool_swap.schema.compile import (
    TSWAP_S140,
    SchemaSeverity,
    compile_inputs,
    compile_outputs,
    compile_tool_schema,
    validate_against_metaschema,
)


def _assert_all_s140(diags: list) -> None:
    """Assert every diagnostic is an ERROR-severity S140 with a remedy."""
    assert all(d.code == TSWAP_S140 for d in diags)
    assert all(d.severity is SchemaSeverity.ERROR for d in diags)
    assert all(d.remedy for d in diags)


class TestValidSchemas:
    """Corpus 11 — every compiled schema validates clean."""

    def test_compiled_section_84_input_is_meta_valid(self) -> None:
        """Corpus 7's compiled input schema -> [] (valid)."""
        schema, diags = compile_inputs(SECTION_84_INPUTS)
        assert diags == []
        assert schema is not None
        assert validate_against_metaschema(schema) == []

    def test_compiled_embedding_output_is_meta_valid(self) -> None:
        """Corpus 9's compiled output schema -> [] (valid)."""
        schema, diags = compile_outputs(EMBEDDING_OUTPUTS)
        assert diags == []
        assert schema is not None
        assert validate_against_metaschema(schema) == []

    def test_compiled_empty_inputs_is_meta_valid(self) -> None:
        """The no-argument schema (item 13) is meta-schema-valid."""
        schema, _ = compile_inputs([])
        assert schema is not None
        assert validate_against_metaschema(schema) == []

    def test_handwritten_2020_12_schema_is_valid(self) -> None:
        """A valid hand-written 2020-12 schema -> []."""
        good = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"n": {"type": "integer", "description": "d"}},
            "required": ["n"],
            "additionalProperties": False,
        }
        assert validate_against_metaschema(good) == []

    def test_returns_a_list(self) -> None:
        """The return type is always list, even when non-empty (item 9)."""
        assert isinstance(validate_against_metaschema({"type": "object"}), list)
        assert isinstance(
            validate_against_metaschema({"type": "not-a-type"}), list
        )


class TestInvalidSchemas:
    """One S140 per yielded meta-schema error, quoting path and message."""

    def test_bad_property_type_yields_one_s140_with_json_path(self) -> None:
        """{"type": "not-a-type"} -> one S140 quoting $.properties.x.type (item 9)."""
        schema = {"type": "object", "properties": {"x": {"type": "not-a-type"}}}
        diags = validate_against_metaschema(schema)
        assert len(diags) == 1
        _assert_all_s140(diags)
        assert "$.properties.x.type" in diags[0].message
        # The validator's own message is quoted (distinctive substring,
        # not the full wording — jsonschema upgrades must not break this).
        expected_message = next(
            Draft202012Validator(Draft202012Validator.META_SCHEMA).iter_errors(schema)
        ).message
        assert expected_message in diags[0].message

    def test_type_list_with_unknown_member_yields_s140(self) -> None:
        """A list-form type including an unknown string -> S140 at the same path."""
        schema = {
            "type": "object",
            "properties": {"x": {"type": ["string", "not-a-type"]}},
        }
        diags = validate_against_metaschema(schema)
        assert len(diags) == 1
        _assert_all_s140(diags)
        assert "$.properties.x.type" in diags[0].message
        expected_message = next(
            Draft202012Validator(Draft202012Validator.META_SCHEMA).iter_errors(schema)
        ).message
        assert expected_message in diags[0].message

    def test_two_independent_mistakes_yield_two_s140s(self) -> None:
        """iter_errors, not check_schema: two mistakes -> two S140s (item 9)."""
        schema = {
            "type": "object",
            "properties": {
                "a": {"type": "nope"},
                "b": {"type": "alsobad"},
            },
        }
        diags = validate_against_metaschema(schema)
        assert len(diags) == 2
        _assert_all_s140(diags)
        paths = {d.message for d in diags}
        assert any("$.properties.a.type" in m for m in paths)
        assert any("$.properties.b.type" in m for m in paths)

    def test_passed_through_invalid_json_schema_also_gets_s140(self) -> None:
        """The meta-schema check runs on passed-through blocks too (item 9/16)."""
        raw = {
            "type": "object",
            "properties": {"x": {"type": "not-a-type"}},
            "additionalProperties": False,
        }
        result = compile_tool_schema(json_schema=raw)
        assert result.inputs is not None
        assert result.diagnostics == ()  # compilation itself is clean
        diags = validate_against_metaschema(result.inputs)
        assert len(diags) == 1
        _assert_all_s140(diags)
        assert "$.properties.x.type" in diags[0].message

    def test_passed_through_corpus_10_block_is_meta_valid(self) -> None:
        """The corpus-10 raw block is itself a valid 2020-12 schema."""
        result = compile_tool_schema(json_schema=dict(RAW_JSON_SCHEMA))
        assert result.inputs is not None
        assert validate_against_metaschema(result.inputs) == []


class TestDeprecationTrap:
    """The plan's named trap: unknown $schema must produce NO warning.

    ``jsonschema`` 4.26 raises ``DeprecationWarning`` from
    ``validators.validator_for`` when a schema carries a ``$schema`` the
    library does not know; the explicit
    ``Draft202012Validator(Draft202012Validator.META_SCHEMA)``
    construction (item 9) does not.  The test below fails if the
    implementation ever goes through ``validator_for``/``validate``:
    under ``filterwarnings = ["error"]`` (pyproject.toml) that warning
    would abort the suite — here it is caught explicitly and turned into
    a test failure.
    """

    def test_validator_for_would_warn_on_unknown_schema(self) -> None:
        """Guard: the trap is real — validator_for DOES warn (jsonschema 4.26)."""
        raw = {"$schema": "http://example.invalid/schema", "type": "object"}
        with pytest.raises(DeprecationWarning):
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                _jsonschema_validators.validator_for(raw)

    def test_unknown_schema_validates_with_no_deprecation_warning(self) -> None:
        """A passed-through block with an unknown $schema: no warning (item 16)."""
        raw = {"$schema": "http://example.invalid/schema", "type": "object"}
        # Act: validate_against_metaschema must construct the validator
        # explicitly; a DeprecationWarning here means it took the
        # validator_for path the plan forbids.
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = validate_against_metaschema(raw)
        # Assert: the result is a list.  An unknown $schema string is
        # still a syntactically valid schema document, so the outcome
        # (S140s or none) is asserted only as "a list" — the pin is the
        # absence of the warning, not the validation outcome.
        assert isinstance(result, list)

"""RED tests for M1 behaviour 20 — the schema compiler (corpus 7/9/10, input+output side).

Executable form of ``plans/m1-configuration.md`` behaviour 20 (lines 1820-1843)
and its "Confirmed contract details (2026-08-19)" block (lines 1845-2162),
items 1-16: ``compile_inputs`` / ``compile_outputs`` / ``compile_tool_schema``
over plain data, total and never raising, with the fourteen ``TSWAP-S1xx``
codes (A21), the ``SchemaDiagnostic`` / ``SchemaSeverity`` /
``CompiledSchemas`` carriers, and the module-level ``Final`` constants.

``src/tool_swap/schema/compile.py`` does not exist yet, so this module fails
collection with a single clean ``ImportError`` naming exactly one missing
name (``JSON_SCHEMA_2020_12``, the first import below).  Every test body
pins a concrete behaviour the GREEN step must satisfy, so the assertions —
not just the import — are the contract.

Snapshot assertions for the §8.4 worked example (corpus 7), the embedding
outputs block (corpus 9) and the ``json_schema:`` pass-through (corpus 10)
live in ``test_compile_snapshots.py``; meta-schema validation (corpus 11)
lives in ``test_metaschema.py``.

Conventions: AAA, Google docstrings, snake_case, ``from __future__ import
annotations``.  Pure-function tests only — the compiler registers no rules,
so no fixtures/registration; no ``importlib.reload``.
"""

from __future__ import annotations

import dataclasses
import keyword
from typing import Any

import pytest

from tool_swap.schema.compile import (
    JSON_SCHEMA_2020_12,
    SUPPORTED_TYPES,
    TSWAP_S100,
    TSWAP_S101,
    TSWAP_S102,
    TSWAP_S103,
    TSWAP_S104,
    TSWAP_S105,
    TSWAP_S106,
    TSWAP_S107,
    TSWAP_S108,
    TSWAP_S109,
    TSWAP_S110,
    TSWAP_S120,
    TSWAP_S130,
    CompiledSchemas,
    SchemaDiagnostic,
    SchemaSeverity,
    compile_inputs,
    compile_outputs,
    compile_tool_schema,
)

# The fourteen codes, by name (contract block item 15): the names are the
# codes with underscores, module-level Final[str] in compile.py.
ALL_SCODES = (
    TSWAP_S100,
    TSWAP_S101,
    TSWAP_S102,
    TSWAP_S103,
    TSWAP_S104,
    TSWAP_S105,
    TSWAP_S106,
    TSWAP_S107,
    TSWAP_S108,
    TSWAP_S109,
    TSWAP_S110,
    TSWAP_S120,
    TSWAP_S130,
)


def _entry(
    name: str,
    etype: str = "string",
    description: str = "d",
    **extra: Any,
) -> dict[str, Any]:
    """Build a minimal valid authored entry, plus ``extra`` keys."""
    entry: dict[str, Any] = {"name": name, "type": etype, "description": description}
    entry.update(extra)
    return entry


def _prop(schema: dict[str, Any], name: str) -> dict[str, Any]:
    """Return the compiled property dict for ``name``."""
    return schema["properties"][name]


def _assert_no_foreign_x_keys(obj: Any) -> None:
    """Recursively assert no key starting ``x-`` other than ``x-semantic``.

    Contract block item 5 (the plan/10_TESTING_STRATEGY.md:139 form):
    ``x-semantic`` is the only ``x-*`` keyword the compiler emits.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert not (key.startswith("x-") and key != "x-semantic"), (
                f"foreign x- keyword in compiled schema: {key!r}"
            )
            _assert_no_foreign_x_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            _assert_no_foreign_x_keys(item)


class TestConstants:
    """Module-level constants (contract block items 11 and 15)."""

    def test_json_schema_2020_12_uri(self) -> None:
        """JSON_SCHEMA_2020_12 is the 2020-12 meta-schema URI, verbatim."""
        assert JSON_SCHEMA_2020_12 == "https://json-schema.org/draft/2020-12/schema"

    def test_supported_types_is_the_six(self) -> None:
        """SUPPORTED_TYPES is the six, in the pinned order (item 11)."""
        assert SUPPORTED_TYPES == (
            "string",
            "number",
            "integer",
            "boolean",
            "array",
            "object",
        )

    def test_scode_constants_are_the_codes(self) -> None:
        """Each TSWAP_S1xx constant equals its code string (item 15)."""
        expected = tuple(f"TSWAP-S{number}" for number in range(100, 111)) + (
            "TSWAP-S120",
            "TSWAP-S130",
        )
        assert ALL_SCODES == expected

    def test_schema_severity_members(self) -> None:
        """SchemaSeverity has ERROR and WARNING (item 14's two-member enum)."""
        assert SchemaSeverity.ERROR is not SchemaSeverity.WARNING

    def test_schema_diagnostic_is_frozen_dataclass(self) -> None:
        """SchemaDiagnostic is a frozen dataclass (item 14)."""
        assert dataclasses.is_dataclass(SchemaDiagnostic)
        assert SchemaDiagnostic.__dataclass_params__.frozen  # type: ignore[attr-defined]
        diag = SchemaDiagnostic(
            code=TSWAP_S103,
            severity=SchemaSeverity.ERROR,
            message="m",
            remedy="r",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            diag.severity = SchemaSeverity.WARNING  # type: ignore[misc]

    def test_schema_diagnostic_field_order_and_defaults(self) -> None:
        """Fields are (code, severity, message, remedy, entry_index, block)."""
        fields = {f.name: f for f in dataclasses.fields(SchemaDiagnostic)}
        assert list(fields) == [
            "code",
            "severity",
            "message",
            "remedy",
            "entry_index",
            "block",
        ]
        assert fields["entry_index"].default is None
        assert fields["block"].default is None

    def test_compiled_schemas_is_frozen_dataclass(self) -> None:
        """CompiledSchemas is a frozen dataclass (item 7)."""
        assert dataclasses.is_dataclass(CompiledSchemas)
        assert CompiledSchemas.__dataclass_params__.frozen  # type: ignore[attr-defined]
        assert [f.name for f in dataclasses.fields(CompiledSchemas)] == [
            "inputs",
            "outputs",
            "diagnostics",
        ]


class TestCompileInputs:
    """compile_inputs: shape, order, and the per-entry S1xx table (items 2/3/6b/13)."""

    @pytest.mark.parametrize(
        "hostile",
        ["oops", [None], [[]], [{}], 42, {"name": "path"}],
        ids=["str", "list-None", "list-empty-list", "list-empty-dict", "int", "dict"],
    )
    def test_hostile_block_never_raises_and_yields_s105(self, hostile: Any) -> None:
        """Hostile corpus: no raise, tuple return, S105, schema half None (item 3)."""
        # Arrange: block shapes the plan's hostile corpus pins (line 1965).
        # Act: the compiler must be total.
        schema, diags = compile_inputs(hostile)
        # Assert.
        assert schema is None
        assert isinstance(diags, list)
        assert [d.code for d in diags] == [TSWAP_S105]
        assert diags[0].severity is SchemaSeverity.ERROR

    def test_single_mapping_entry_without_name_is_s106(self) -> None:
        """A mapping entry lacking a usable name is S106, not S105 (item 6b)."""
        schema, diags = compile_inputs([{"type": "string"}])
        assert schema is None
        assert [d.code for d in diags] == [TSWAP_S106]
        assert diags[0].severity is SchemaSeverity.ERROR
        assert "inputs[0]" in diags[0].message

    def test_empty_list_is_populated_schema(self) -> None:
        """inputs: [] -> the exact no-argument schema (item 13, corpus edge)."""
        schema, diags = compile_inputs([])
        assert schema == {
            "$schema": JSON_SCHEMA_2020_12,
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
        assert list(schema) == [
            "$schema",
            "type",
            "properties",
            "additionalProperties",
        ]
        assert "required" not in schema
        assert diags == []

    def test_none_is_distinct_from_empty_list(self) -> None:
        """inputs: None -> (None, []), and the three values are distinct (item 13)."""
        none_schema, none_diags = compile_inputs(None)
        list_schema, list_diags = compile_inputs([])
        assert none_schema is None
        assert none_diags == []
        assert list_schema is not None
        assert list_schema != {}
        assert list_schema is not None
        assert none_schema != list_schema
        assert list_diags == []

    def test_required_keeps_declaration_order(self) -> None:
        """required contains exactly the required:true names, in order (item 2)."""
        schema, diags = compile_inputs(
            [
                _entry("a", description="first"),
                _entry("b", required=False, description="second"),
                _entry("c", required=True, description="third"),
            ]
        )
        assert schema is not None
        assert diags == []
        assert schema["required"] == ["a", "c"]
        assert list(schema["properties"]) == ["a", "b", "c"]

    def test_single_optional_input_omits_required_key(self) -> None:
        """A single required:false input omits 'required' entirely (item 2)."""
        schema, diags = compile_inputs([_entry("a", required=False)])
        assert schema is not None
        assert diags == []
        assert "required" not in schema

    def test_additional_properties_false_on_every_compiled_schema(self) -> None:
        """additionalProperties is always False (§8.5, item 2 position 5)."""
        schema, _ = compile_inputs(
            [_entry("a", required=True), _entry("b", required=False)]
        )
        assert schema is not None
        assert schema["additionalProperties"] is False

    @pytest.mark.parametrize("etype", SUPPORTED_TYPES)
    def test_type_passthrough_for_all_six_types(self, etype: str) -> None:
        """All six types pass through verbatim (item 11)."""
        items = "number" if etype == "array" else None
        entry = _entry("x", etype)
        if items is not None:
            entry["items"] = items
        schema, diags = compile_inputs([entry])
        assert diags == []
        assert schema is not None
        assert _prop(schema, "x")["type"] == etype

    @pytest.mark.parametrize("etype", ["float", "dict", "enum", "null"])
    def test_type_outside_the_six_is_s103(self, etype: str) -> None:
        """type outside the six -> S103 ERROR; message lists six + json_schema (item 11)."""
        schema, diags = compile_inputs([_entry("threshold", etype)])
        assert schema is None
        assert [d.code for d in diags] == [TSWAP_S103]
        msg = diags[0].message
        for name in SUPPORTED_TYPES:
            assert name in msg
        assert "json_schema" in msg

    def test_missing_type_is_s103(self) -> None:
        """Missing type is S103 — the same code as a wrong type (item 6b)."""
        schema, diags = compile_inputs([{"name": "a", "description": "d"}])
        assert schema is None
        assert [d.code for d in diags] == [TSWAP_S103]

    def test_non_string_type_is_s103(self) -> None:
        """type present but not a string is S103 (item 6b)."""
        schema, diags = compile_inputs([{"name": "a", "type": 42, "description": "d"}])
        assert schema is None
        assert [d.code for d in diags] == [TSWAP_S103]

    def test_array_shorthand_items(self) -> None:
        """items: number (bare spelling) -> items: {"type": "number"} (item 12)."""
        schema, diags = compile_inputs([_entry("emb", "array", items="number")])
        assert diags == []
        assert schema is not None
        assert _prop(schema, "emb")["items"] == {"type": "number"}

    def test_array_mapping_items(self) -> None:
        """items: {type: number} (mapping spelling) -> the same thing (item 12)."""
        schema, diags = compile_inputs([_entry("emb", "array", items={"type": "number"})])
        assert diags == []
        assert schema is not None
        assert _prop(schema, "emb")["items"] == {"type": "number"}

    def test_array_without_items_is_s109(self) -> None:
        """type: array with no items -> S109 ERROR, entry skipped (item 12)."""
        schema, diags = compile_inputs([_entry("tags", "array")])
        assert schema is None
        assert [d.code for d in diags] == [TSWAP_S109]
        assert diags[0].severity is SchemaSeverity.ERROR

    def test_nested_items_beyond_one_level_is_s110(self) -> None:
        """items carrying its own items -> S110 directing to json_schema (item 12)."""
        schema, diags = compile_inputs(
            [
                _entry(
                    "matrix",
                    "array",
                    items={"type": "array", "items": {"type": "string"}},
                )
            ]
        )
        assert schema is None
        assert [d.code for d in diags] == [TSWAP_S110]
        assert diags[0].severity is SchemaSeverity.ERROR
        assert "json_schema" in diags[0].message

    def test_item_type_outside_the_six_is_s103_naming_element(self) -> None:
        """The element type must be one of the six -> S103 naming the element (item 12)."""
        schema, diags = compile_inputs([_entry("tags", "array", items="enum")])
        assert schema is None
        assert [d.code for d in diags] == [TSWAP_S103]
        assert "items" in diags[0].message

    def test_items_on_non_array_type_is_ignored(self) -> None:
        """items on a non-array type is ignored (item 12, pinned)."""
        schema, diags = compile_inputs([_entry("s", "string", items="number")])
        assert diags == []
        assert schema is not None
        prop = _prop(schema, "s")
        assert prop["type"] == "string"
        assert "items" not in prop

    def test_semantic_carried_verbatim_as_x_semantic(self) -> None:
        """semantic -> x-semantic verbatim; the authored key never leaks (item 4)."""
        schema, diags = compile_inputs([_entry("path", semantic="dicom_path")])
        assert diags == []
        assert schema is not None
        prop = _prop(schema, "path")
        assert prop["x-semantic"] == "dicom_path"
        assert "semantic" not in prop
        _assert_no_foreign_x_keys(schema)

    def test_unknown_semantic_value_survives(self) -> None:
        """No vocabulary check: any string passes unchanged (item 4)."""
        schema, diags = compile_inputs([_entry("p", semantic="banana")])
        assert diags == []
        assert schema is not None
        assert _prop(schema, "p")["x-semantic"] == "banana"

    def test_semantic_absent_means_no_x_semantic_key(self) -> None:
        """semantic: absent -> no x-semantic key at all (item 4)."""
        schema, diags = compile_inputs([_entry("p")])
        assert diags == []
        assert schema is not None
        assert "x-semantic" not in _prop(schema, "p")

    def test_non_string_semantic_is_s104(self) -> None:
        """semantic: 42 -> S104 ERROR, entry skipped (item 4)."""
        schema, diags = compile_inputs([_entry("path", semantic=42)])
        assert schema is None
        assert [d.code for d in diags] == [TSWAP_S104]
        assert diags[0].severity is SchemaSeverity.ERROR

    def test_batchable_key_is_ignored_with_no_s_code(self) -> None:
        """A per-input batchable key is ignored; C404 owns the rejection (item 5)."""
        schema, diags = compile_inputs([_entry("p", batchable=True)])
        assert diags == []
        assert schema is not None
        prop = _prop(schema, "p")
        assert "batchable" not in prop
        assert "x-batchable" not in prop
        _assert_no_foreign_x_keys(schema)

    def test_input_side_missing_description_is_s120_error_and_none(self) -> None:
        """Input-side S120 = ERROR, entry skipped, schema -> None (item 8)."""
        schema, diags = compile_inputs([{"name": "p", "type": "string"}])
        assert schema is None
        assert [d.code for d in diags] == [TSWAP_S120]
        assert diags[0].severity is SchemaSeverity.ERROR

    def test_input_side_blank_description_is_s120(self) -> None:
        """A blank description counts as missing (item 8)."""
        schema, diags = compile_inputs([_entry("p", description="   ")])
        assert schema is None
        assert [d.code for d in diags] == [TSWAP_S120]

    def test_one_error_nullifies_the_whole_inputs_schema(self) -> None:
        """A valid entry + a description-less entry -> still (None, [...]) (item 3)."""
        schema, diags = compile_inputs(
            [_entry("ok", description="fine"), {"name": "bad", "type": "string"}]
        )
        assert schema is None
        assert TSWAP_S120 in [d.code for d in diags]

    def test_non_string_description_is_s108(self) -> None:
        """description: 42 -> S108 ERROR, entry skipped (item 8)."""
        schema, diags = compile_inputs([_entry("p", description=42)])
        assert schema is None
        assert [d.code for d in diags] == [TSWAP_S108]
        assert diags[0].severity is SchemaSeverity.ERROR

    def test_required_non_bool_is_s107(self) -> None:
        """required: 'yes' -> S107 ERROR; the name is not added to required (item 6b)."""
        schema, diags = compile_inputs([_entry("p", required="yes")])
        assert [d.code for d in diags] == [TSWAP_S107]
        assert diags[0].severity is SchemaSeverity.ERROR
        # An ERROR forces the schema half to None (item 3).
        assert schema is None

    @pytest.mark.parametrize("name", ["2bad", "with space"])
    def test_non_identifier_name_is_s102_warning_but_emitted(self, name: str) -> None:
        """A non-identifier name warns (S102) but the property IS emitted (item 10)."""
        schema, diags = compile_inputs([_entry(name)])
        assert schema is not None  # all-WARNING diagnostics keep the schema
        assert [d.code for d in diags] == [TSWAP_S102]
        assert diags[0].severity is SchemaSeverity.WARNING
        assert name in schema["properties"]

    def test_python_keyword_name_is_s102_warning(self) -> None:
        """A Python keyword passes isidentifier but still warns (item 10)."""
        assert keyword.iskeyword("def")
        schema, diags = compile_inputs([_entry("def")])
        assert schema is not None
        assert [d.code for d in diags] == [TSWAP_S102]
        assert diags[0].severity is SchemaSeverity.WARNING

    def test_unicode_identifier_name_is_not_s102(self) -> None:
        """'café'.isidentifier() is True -> no S102 (item 10)."""
        assert "café".isidentifier() is True
        schema, diags = compile_inputs([_entry("café")])
        assert schema is not None
        assert diags == []
        assert "café" in schema["properties"]

    @pytest.mark.parametrize("bad_name", ["", None, 42])
    def test_bad_name_is_s106(self, bad_name: Any) -> None:
        """Empty-string / missing / non-string name -> S106 ERROR (item 6b)."""
        entry: dict[str, Any] = {"type": "string", "description": "d"}
        if bad_name is not None:
            entry["name"] = bad_name
        schema, diags = compile_inputs([entry])
        assert schema is None
        assert [d.code for d in diags] == [TSWAP_S106]

    def test_duplicate_names_are_s100(self) -> None:
        """Two entries named 'path' -> S100 ERROR, schema -> None (item 15 table)."""
        schema, diags = compile_inputs([_entry("path"), _entry("path")])
        assert schema is None
        assert TSWAP_S100 in [d.code for d in diags]
        assert SchemaSeverity.ERROR in [d.severity for d in diags]

    def test_compile_inputs_alone_cannot_emit_s101(self) -> None:
        """S101 needs params, which compile_inputs never sees (item 15, pinned)."""
        schema, diags = compile_inputs([_entry("n")])
        assert TSWAP_S101 not in [d.code for d in diags]

    def test_property_key_order_is_pinned(self) -> None:
        """Key order inside a property: type, items, description, x-semantic (item 2)."""
        schema, diags = compile_inputs(
            [_entry("emb", "array", items="number", semantic="vector")]
        )
        assert diags == []
        assert schema is not None
        assert list(_prop(schema, "emb")) == [
            "type",
            "items",
            "description",
            "x-semantic",
        ]

    def test_section_84_input_property_behaviours(self) -> None:
        """The §8.4 entry compiles with its pinned per-property content (corpus 7 side)."""
        schema, diags = compile_inputs(
            [
                {
                    "name": "path",
                    "type": "string",
                    "required": True,
                    "description": "Path to a DICOM chest X-ray image to embed.",
                    "semantic": "dicom_path",
                }
            ]
        )
        assert diags == []
        assert schema is not None
        assert schema["$schema"] == JSON_SCHEMA_2020_12
        assert schema["type"] == "object"
        assert list(schema) == [
            "$schema",
            "type",
            "properties",
            "required",
            "additionalProperties",
        ]
        assert schema["required"] == ["path"]
        prop = _prop(schema, "path")
        assert prop["type"] == "string"
        assert prop["description"] == "Path to a DICOM chest X-ray image to embed."
        assert prop["x-semantic"] == "dicom_path"
        assert list(prop) == ["type", "description", "x-semantic"]


class TestCompileOutputs:
    """compile_outputs: same shape minus required; S120 is a WARNING (item 8)."""

    def test_output_side_missing_description_is_s120_warning_and_emitted(self) -> None:
        """Output-side S120 = WARNING; property emitted without description (item 8)."""
        schema, diags = compile_outputs([{"name": "embedding", "type": "array"}])
        assert schema is not None
        assert [d.code for d in diags] == [TSWAP_S120]
        assert diags[0].severity is SchemaSeverity.WARNING
        prop = schema["properties"]["embedding"]
        assert "description" not in prop

    def test_outputs_never_carry_required_even_when_required_true(self) -> None:
        """'required' is ignored for outputs, even when written (item 8)."""
        schema, diags = compile_outputs([_entry("e", required=True)])
        assert diags == []
        assert schema is not None
        assert "required" not in schema

    def test_outputs_emit_additional_properties_false(self) -> None:
        """additionalProperties: false IS emitted for outputs (item 8)."""
        schema, _ = compile_outputs([_entry("e")])
        assert schema is not None
        assert schema["additionalProperties"] is False

    def test_empty_outputs(self) -> None:
        """outputs: [] -> the same no-argument shape as inputs (item 13)."""
        schema, diags = compile_outputs([])
        assert schema == {
            "$schema": JSON_SCHEMA_2020_12,
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
        assert diags == []

    def test_none_outputs(self) -> None:
        """outputs: None -> (None, [])."""
        schema, diags = compile_outputs(None)
        assert schema is None
        assert diags == []


class TestCompileToolSchema:
    """compile_tool_schema: the dispatcher, S130, and S101 (items 7/15)."""

    def test_json_schema_and_inputs_both_present_is_s130(self) -> None:
        """S130 names both keys; the inputs half is None (item 7 rule 1)."""
        result = compile_tool_schema(
            inputs=[_entry("p")],
            json_schema={"type": "object"},
        )
        assert result.inputs is None
        codes = [d.code for d in result.diagnostics]
        assert TSWAP_S130 in codes
        diag = next(d for d in result.diagnostics if d.code == TSWAP_S130)
        assert diag.severity is SchemaSeverity.ERROR
        assert "json_schema" in diag.message
        assert "inputs" in diag.message
        assert diag.entry_index is None

    def test_json_schema_alone_passes_through_as_inputs_half(self) -> None:
        """json_schema alone -> the inputs half is the pass-through (item 7 rule 2)."""
        raw = {"type": "object", "properties": {"p": {"type": "string"}}}
        result = compile_tool_schema(json_schema=raw)
        assert result.inputs == raw
        assert result.inputs is not raw
        assert result.outputs is None
        assert result.diagnostics == ()

    def test_inputs_alone_are_compiled(self) -> None:
        """inputs alone -> compiled; outputs None (item 7 rules 3/4)."""
        result = compile_tool_schema(inputs=[_entry("p", required=True)])
        assert result.inputs is not None
        assert result.inputs["required"] == ["p"]
        assert result.outputs is None
        assert result.diagnostics == ()

    def test_outputs_compiled_independently_of_json_schema(self) -> None:
        """json_schema + outputs -> outputs compiled, inputs pass-through (item 7)."""
        raw = {"type": "object"}
        result = compile_tool_schema(
            json_schema=raw, outputs=[_entry("e", description="an output")]
        )
        assert result.inputs == raw
        assert result.inputs is not raw
        assert result.outputs is not None
        assert result.outputs["properties"]["e"]["description"] == "an output"
        assert "required" not in result.outputs
        assert result.diagnostics == ()

    def test_params_collision_is_s101_with_deciding_question(self) -> None:
        """An inputs/params name collision -> S101 quoting §5.5.1's question (item 15)."""
        result = compile_tool_schema(
            inputs=[_entry("n")],
            params=[{"name": "n", "default": 0.5, "description": "a knob"}],
        )
        codes = [d.code for d in result.diagnostics]
        assert TSWAP_S101 in codes
        diag = next(d for d in result.diagnostics if d.code == TSWAP_S101)
        assert diag.severity is SchemaSeverity.ERROR
        assert "n" in diag.message
        assert (
            "does this value change what the batched forward pass computes?"
            in diag.message
        )
        assert result.inputs is None  # S101 is ERROR: schema -> None (item 3)

    def test_params_without_collision_produce_nothing(self) -> None:
        """params alone with no collision -> no diagnostics, no schema from params."""
        result = compile_tool_schema(
            inputs=[_entry("p")],
            params=[{"name": "threshold", "default": 0.5, "description": "knob"}],
        )
        assert result.inputs is not None
        assert TSWAP_S101 not in [d.code for d in result.diagnostics]
        assert result.diagnostics == ()

    def test_diagnostic_order_block_entry_cross_entry(self) -> None:
        """Order: block-level (S130), per-entry in declaration order, cross-entry (item 3)."""
        result = compile_tool_schema(
            inputs=[
                _entry("a", "float"),
                _entry("dup"),
                _entry("dup"),
            ],
            json_schema={"type": "object"},
        )
        codes = [d.code for d in result.diagnostics]
        assert codes[0] == TSWAP_S130
        assert codes[1] == TSWAP_S103
        assert TSWAP_S100 in codes[2:]
        assert TSWAP_S100 is not TSWAP_S130
        # entry_index: None for the block-level S130, 0-based for per-entry.
        s130 = next(d for d in result.diagnostics if d.code == TSWAP_S130)
        s103 = next(d for d in result.diagnostics if d.code == TSWAP_S103)
        assert s130.entry_index is None
        assert s103.entry_index == 0
        assert s130.block == "inputs"
        assert s103.block == "inputs"

    def test_schema_diagnostic_block_is_outputs_for_output_diags(self) -> None:
        """block is 'outputs' for compile_outputs diagnostics (item 14)."""
        _, diags = compile_outputs([{"name": "e", "type": "array"}])
        assert diags[0].block == "outputs"
        assert diags[0].entry_index == 0

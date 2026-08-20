"""RED tests for M1 behaviour 20 — the pinned schema snapshots (corpus 7/9/10).

Executable form of ``plans/m1-configuration.md`` behaviour 20's "Confirmed
contract details (2026-08-19)" block, items 1, 2 and 7:

- **Corpus 7** — the §8.4 worked example from
  ``plan/04_API_CONTRACT.md`` §8.4 (the authored ``inputs:`` list with
  ``name: path``) compiles to the exact pinned dict, including key order
  (item 1, A4: ``required: ["path"]``, the self-consistent form).
- **Corpus 9** — the embedding ``outputs:`` block from
  ``plan/02_CONFIGURATION.md`` §4 compiles to the pinned shape with
  ``items: {"type": "number"}`` and NO ``required`` key (items 1/8).
- **Corpus 10** — a raw ``json_schema:`` block is passed through
  byte-for-byte: deep equality **including key order**, ``deepcopy`` not
  identity, and nothing injected (no ``$schema``, no
  ``additionalProperties``) (item 7).

``src/tool_swap/schema/compile.py`` does not exist yet, so this module
fails collection with a single clean ``ImportError`` naming exactly one
missing name (``compile_inputs``, the first import below).  Every test
body pins a concrete behaviour the GREEN step must satisfy.

The per-property key order on the §8.4 entry and its behaviours are also
asserted in ``test_compile.py``; this file is the canonical home for the
full-dict equality assertions (plan: corpus 7 lives in the snapshot file).

Conventions: AAA, Google docstrings, snake_case, ``from __future__ import
annotations``.  Pure-function tests only; no fixtures/registration; no
``importlib.reload``.
"""

from __future__ import annotations

from typing import Any

from tool_swap.schema.compile import (
    JSON_SCHEMA_2020_12,
    compile_inputs,
    compile_outputs,
    compile_tool_schema,
)

# ---------------------------------------------------------------------------
# Corpus 7 — the §8.4 worked example (plan/04_API_CONTRACT.md §8.4, lines 459-466)
# ---------------------------------------------------------------------------

SECTION_84_INPUTS: list[dict[str, Any]] = [
    {
        "name": "path",
        "type": "string",
        "required": True,
        "description": "Path to a DICOM chest X-ray image to embed.",
        "semantic": "dicom_path",
    }
]

# The pinned snapshot (contract block item 1; A4 self-consistent
# ``required: ["path"]``; ``$schema`` emitted).
SECTION_84_SNAPSHOT: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to a DICOM chest X-ray image to embed.",
            "x-semantic": "dicom_path",
        }
    },
    "required": ["path"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# Corpus 9 — the embedding outputs block (plan/02_CONFIGURATION.md §4,
# lines 214-218; the only place the authored ``items:`` spelling appears)
# ---------------------------------------------------------------------------

EMBEDDING_OUTPUTS: list[dict[str, Any]] = [
    {
        "name": "embedding",
        "type": "array",
        "items": "number",
        "description": "Embedding vector of shape (768,) per input image.",
    }
]

EMBEDDING_OUTPUTS_SNAPSHOT: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "embedding": {
            "type": "array",
            "items": {"type": "number"},
            "description": "Embedding vector of shape (768,) per input image.",
        }
    },
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# Corpus 10 — a raw json_schema: block, non-default key order + an x- key
# ---------------------------------------------------------------------------

# Note the deliberate non-canonical key order ($schema last) and the
# ``x-`` custom key: the pass-through must preserve both, untouched.
RAW_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "DICOM paths to embed.",
            "x-semantic": "dicom_path",
        }
    },
    "required": ["paths"],
    "$schema": "https://json-schema.org/draft/2020-12/schema",
}


def _assert_key_order_equal(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    """Assert ``list()`` equality at every nested dict level (recursively).

    The plan's "deep equality including key order": ``copy.deepcopy``
    preserves insertion order, so the compiled/passed-through dict must
    match the pinned/authoring order at every level.
    """
    assert list(actual) == list(expected), (
        f"key order mismatch: {list(actual)} != {list(expected)}"
    )
    for key in expected:
        expected_value = expected[key]
        actual_value = actual[key]
        if isinstance(expected_value, dict):
            _assert_key_order_equal(expected_value, actual_value)
        elif isinstance(expected_value, list):
            assert isinstance(actual_value, list), (
                f"expected list at {key!r}, got {type(actual_value).__name__}"
            )
            assert len(expected_value) == len(actual_value)
            for index, (e_item, a_item) in enumerate(zip(expected_value, actual_value)):
                if isinstance(e_item, dict):
                    _assert_key_order_equal(e_item, a_item)
                else:
                    assert e_item == a_item


class TestCorpus7Section84InputSnapshot:
    """Corpus 7 — the §8.4 worked example compiles to the pinned dict."""

    def test_section_84_input_compiles_to_exact_pinned_dict(self) -> None:
        """Deep equality against the exact pinned snapshot (item 1)."""
        # Arrange: the §8.4 authored block, verbatim.
        # Act.
        schema, diags = compile_inputs(SECTION_84_INPUTS)
        # Assert.
        assert diags == []
        assert schema == SECTION_84_SNAPSHOT

    def test_section_84_input_key_order_top_level(self) -> None:
        """Top-level key order is the pinned five-key order (item 2)."""
        schema, _ = compile_inputs(SECTION_84_INPUTS)
        assert schema is not None
        assert list(schema) == [
            "$schema",
            "type",
            "properties",
            "required",
            "additionalProperties",
        ]

    def test_section_84_input_key_order_recursive(self) -> None:
        """Key order holds at every nested level (item 2, corpus 7)."""
        schema, _ = compile_inputs(SECTION_84_INPUTS)
        assert schema is not None
        _assert_key_order_equal(SECTION_84_SNAPSHOT, schema)

    def test_section_84_input_property_key_order(self) -> None:
        """Property key order: type, description, x-semantic (item 2)."""
        schema, _ = compile_inputs(SECTION_84_INPUTS)
        assert schema is not None
        assert list(schema["properties"]["path"]) == [
            "type",
            "description",
            "x-semantic",
        ]

    def test_section_84_required_is_self_consistent_path(self) -> None:
        """A4: required is ["path"], not the spec's typo'd ["paths"]."""
        schema, _ = compile_inputs(SECTION_84_INPUTS)
        assert schema is not None
        assert schema["required"] == ["path"]
        assert schema["$schema"] == JSON_SCHEMA_2020_12


class TestCorpus9EmbeddingOutputSnapshot:
    """Corpus 9 — the embedding outputs block compiles to the pinned shape."""

    def test_embedding_output_compiles_to_exact_pinned_dict(self) -> None:
        """Deep equality against the pinned outputs snapshot (items 1/8)."""
        # Arrange: the plan/02 §4 authored outputs block (bare items spelling).
        # Act.
        schema, diags = compile_outputs(EMBEDDING_OUTPUTS)
        # Assert.
        assert diags == []
        assert schema == EMBEDDING_OUTPUTS_SNAPSHOT

    def test_embedding_output_items_is_number(self) -> None:
        """The bare ``items: number`` spelling compiles to {"type": "number"}."""
        schema, _ = compile_outputs(EMBEDDING_OUTPUTS)
        assert schema is not None
        assert schema["properties"]["embedding"]["items"] == {"type": "number"}

    def test_embedding_output_has_no_required_key(self) -> None:
        """No ``required`` key, ever, for outputs (item 8)."""
        schema, _ = compile_outputs(EMBEDDING_OUTPUTS)
        assert schema is not None
        assert "required" not in schema

    def test_embedding_output_key_order_recursive(self) -> None:
        """Key order holds at every nested level (item 2, corpus 9)."""
        schema, _ = compile_outputs(EMBEDDING_OUTPUTS)
        assert schema is not None
        _assert_key_order_equal(EMBEDDING_OUTPUTS_SNAPSHOT, schema)
        assert list(schema["properties"]["embedding"]) == [
            "type",
            "items",
            "description",
        ]


class TestCorpus10JsonSchemaPassThrough:
    """Corpus 10 — the json_schema: block is passed through untouched."""

    def test_passthrough_deep_equals_raw(self) -> None:
        """compiled == raw, deep equality (item 7)."""
        raw = dict(RAW_JSON_SCHEMA)
        result = compile_tool_schema(json_schema=raw)
        assert result.inputs == raw

    def test_passthrough_key_order_equal_recursively(self) -> None:
        """list() order equal at every level, including the odd $schema last."""
        raw = dict(RAW_JSON_SCHEMA)
        result = compile_tool_schema(json_schema=raw)
        assert result.inputs is not None
        _assert_key_order_equal(raw, result.inputs)

    def test_passthrough_is_deepcopy_not_identity(self) -> None:
        """Deep, not shallow: no aliasing of the block or its properties (item 7)."""
        raw = dict(RAW_JSON_SCHEMA)
        result = compile_tool_schema(json_schema=raw)
        assert result.inputs is not raw
        assert result.inputs["properties"] is not raw["properties"]
        assert (
            result.inputs["properties"]["paths"] is not raw["properties"]["paths"]
        )

    def test_passthrough_injects_nothing(self) -> None:
        """No $schema or additionalProperties is added (item 7, corpus 10)."""
        raw_without_extras = {
            "type": "object",
            "properties": {"p": {"type": "string"}},
        }
        result = compile_tool_schema(json_schema=raw_without_extras)
        assert result.inputs is not None
        assert result.inputs == raw_without_extras
        assert "$schema" not in result.inputs
        assert "additionalProperties" not in result.inputs

    def test_passthrough_preserves_x_custom_key(self) -> None:
        """An x- custom key survives the pass-through untouched (item 7)."""
        result = compile_tool_schema(json_schema=dict(RAW_JSON_SCHEMA))
        assert result.inputs is not None
        assert result.inputs["properties"]["paths"]["x-semantic"] == "dicom_path"

    def test_passthrough_is_the_only_diagnostic_free_path(self) -> None:
        """A well-formed json_schema: alone yields zero diagnostics."""
        result = compile_tool_schema(json_schema=dict(RAW_JSON_SCHEMA))
        assert result.diagnostics == ()
        assert result.outputs is None

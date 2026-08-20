"""Compile authored ``inputs:``/``outputs:`` blocks into JSON Schema 2020-12.

Behaviour 20 of ``plans/m1-configuration.md``: the pure-function schema
compiler behind ``tswap validate``.  The compiler is TOTAL and never raises
for any input (hostile corpora included); it returns ``(schema,
diagnostics)`` tuples so behaviour 21 can report every problem in one
pass.  The schema half is ``None`` whenever any ERROR-severity diagnostic
was produced — emitting an invalid schema is worse than emitting none.

``json_schema:`` blocks are passed through as ``copy.deepcopy``: untouched
content, no aliasing, nothing injected.  ``validate_against_metaschema`` is
the separate, explicitly-invoked meta-schema step; it constructs
``Draft202012Validator`` explicitly so the ``validator_for``
DeprecationWarning path is never taken.
"""

from __future__ import annotations

import copy
import keyword
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

import jsonschema  # type: ignore[import-untyped]  # jsonschema 4.26 ships no py.typed

JSON_SCHEMA_2020_12: Final[str] = "https://json-schema.org/draft/2020-12/schema"

SUPPORTED_TYPES: Final[tuple[str, ...]] = (
    "string",
    "number",
    "integer",
    "boolean",
    "array",
    "object",
)

TSWAP_S100: Final[str] = "TSWAP-S100"
TSWAP_S101: Final[str] = "TSWAP-S101"
TSWAP_S102: Final[str] = "TSWAP-S102"
TSWAP_S103: Final[str] = "TSWAP-S103"
TSWAP_S104: Final[str] = "TSWAP-S104"
TSWAP_S105: Final[str] = "TSWAP-S105"
TSWAP_S106: Final[str] = "TSWAP-S106"
TSWAP_S107: Final[str] = "TSWAP-S107"
TSWAP_S108: Final[str] = "TSWAP-S108"
TSWAP_S109: Final[str] = "TSWAP-S109"
TSWAP_S110: Final[str] = "TSWAP-S110"
TSWAP_S120: Final[str] = "TSWAP-S120"
TSWAP_S130: Final[str] = "TSWAP-S130"
TSWAP_S140: Final[str] = "TSWAP-S140"


class SchemaSeverity(Enum):
    """Severity of one schema diagnostic."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class SchemaDiagnostic:
    """One problem found while compiling or meta-validating a schema."""

    code: str
    severity: SchemaSeverity
    message: str
    remedy: str
    entry_index: int | None = None
    block: str | None = None


@dataclass(frozen=True)
class CompiledSchemas:
    """The compiled input/output schemas for one tool, plus every diagnostic."""

    inputs: dict[str, Any] | None
    outputs: dict[str, Any] | None
    diagnostics: tuple[SchemaDiagnostic, ...]


def compile_inputs(
    inputs: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any] | None, list[SchemaDiagnostic]]:
    """Compile an authored ``inputs:`` block into a JSON Schema 2020-12 dict.

    Total and never raising: any shape (non-list block, non-mapping entry,
    missing keys) yields diagnostics instead of an exception.  A
    non-identifier name only warns (``TSWAP-S102``); an empty list yields
    the no-argument schema; ``None`` (absent) yields no schema and no
    diagnostics.

    Args:
        inputs: The block as authored, or ``None`` when absent.  Declared
            as the authored type; hostile shapes are handled, not raised.

    Returns:
        A ``(schema, diagnostics)`` tuple.  ``schema`` has the key order
        ``$schema``, ``type``, ``properties``, ``required`` (inputs only,
        omitted when empty), ``additionalProperties`` — or is ``None``
        when the block is absent or any ERROR-severity diagnostic fired.
    """
    return _compile_block(inputs, block_name="inputs", input_side=True)


def compile_outputs(
    outputs: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any] | None, list[SchemaDiagnostic]]:
    """Compile an authored ``outputs:`` block into a JSON Schema 2020-12 dict.

    Same machinery as :func:`compile_inputs` with the output-side rules:
    no ``required`` key is ever emitted (an authored ``required:`` is
    ignored); a missing/blank ``description`` is ``TSWAP-S120`` at WARNING
    severity and the property IS still emitted, without a ``description``
    key; a non-string ``description`` is ``TSWAP-S108`` ERROR and the
    property is skipped.

    Args:
        outputs: The block as authored, or ``None`` when absent.

    Returns:
        A ``(schema, diagnostics)`` tuple; ``schema`` is ``None`` only
        when the block is absent or any ERROR-severity diagnostic fired.
    """
    return _compile_block(outputs, block_name="outputs", input_side=False)


def compile_tool_schema(
    *,
    inputs: list[dict[str, Any]] | None = None,
    outputs: list[dict[str, Any]] | None = None,
    params: list[dict[str, Any]] | None = None,
    json_schema: dict[str, Any] | None = None,
) -> CompiledSchemas:
    """Compile every authored schema block of one tool (the behaviour-21 entry).

    Dispatch: ``json_schema`` and ``inputs`` both present is ``TSWAP-S130``
    and the inputs half is ``None`` (the authored ``inputs`` are still
    compiled, for their diagnostics); ``json_schema`` alone becomes the
    inputs half as a ``copy.deepcopy``; otherwise ``inputs`` is compiled.
    ``outputs`` is always compiled independently.  ``params`` is read only
    for the ``TSWAP-S101`` name-collision check (against the inputs half's
    property names) and produces no schema; an ``S101`` nulls the inputs
    half.  Diagnostic order: block-level (``S130``), per-entry in
    declaration order, then cross-entry (``S100``, ``S101``).

    Args:
        inputs: The authored ``inputs:`` block, or ``None``.
        outputs: The authored ``outputs:`` block, or ``None``.
        params: The authored ``params:`` block, or ``None``; never
            compiled, only scanned for name collisions.
        json_schema: The raw ``json_schema:`` block, or ``None``.

    Returns:
        A :class:`CompiledSchemas` with the two schema halves (``None``
        where no schema was produced) and every diagnostic in order.
    """
    diagnostics: list[SchemaDiagnostic] = []

    if json_schema is not None and inputs is not None:
        diagnostics.append(
            _diagnostic(
                code=TSWAP_S130,
                severity=SchemaSeverity.ERROR,
                message=(
                    "'json_schema:' and 'inputs:' are alternatives; this "
                    "tool declares both. Use `inputs:` for the simple form, "
                    "or `json_schema:` for enums, ranges, nested objects "
                    "and oneOf — not both."
                ),
                remedy="remove one of them from the tool's tool.yaml",
                block="inputs",
            )
        )
        inputs_schema: dict[str, Any] | None = None
        _, input_diags = compile_inputs(inputs)
        diagnostics.extend(input_diags)
    elif json_schema is not None:
        inputs_schema = copy.deepcopy(json_schema)
    else:
        inputs_schema, input_diags = compile_inputs(inputs)
        diagnostics.extend(input_diags)

    outputs_schema, output_diags = compile_outputs(outputs)
    diagnostics.extend(output_diags)

    if inputs_schema is not None and params is not None:
        properties = inputs_schema.get("properties")
        param_names = set(_param_names(params))
        s101_count = 0
        if isinstance(properties, dict) and param_names:
            for key in properties:
                if isinstance(key, str) and key in param_names:
                    diagnostics.append(
                        _diagnostic(
                            code=TSWAP_S101,
                            severity=SchemaSeverity.ERROR,
                            message=(
                                f"name '{key}' appears in both 'inputs:' "
                                "and 'params:'. Decide: does this value "
                                "change what the batched forward pass "
                                "computes? If yes it is an input; if no it "
                                "is a param."
                            ),
                            remedy=(
                                "remove the name from 'inputs:' or from "
                                "'params:' so it appears in only one block"
                            ),
                            block="inputs",
                        )
                    )
                    s101_count += 1
        if s101_count:
            inputs_schema = None

    return CompiledSchemas(
        inputs=inputs_schema,
        outputs=outputs_schema,
        diagnostics=tuple(diagnostics),
    )


def validate_against_metaschema(schema: dict[str, Any]) -> list[SchemaDiagnostic]:
    """Check one schema dict against the JSON Schema 2020-12 meta-schema.

    The validator is constructed explicitly as
    ``Draft202012Validator(Draft202012Validator.META_SCHEMA)`` and driven
    with ``iter_errors`` — never via ``jsonschema.validate`` /
    ``validator_for`` — so a passed-through block carrying an unknown
    ``$schema`` cannot trip the library's ``DeprecationWarning``, and two
    independent mistakes yield two diagnostics.

    Args:
        schema: Any schema dict, compiled or passed through.

    Returns:
        A list, empty when valid; one ``TSWAP-S140`` ERROR per yielded
        meta-schema error, each message quoting the validator's
        ``json_path`` and its own message.  Never raises.
    """
    meta_schema = jsonschema.Draft202012Validator.META_SCHEMA
    validator = jsonschema.Draft202012Validator(meta_schema)
    diagnostics: list[SchemaDiagnostic] = []
    for error in validator.iter_errors(schema):
        diagnostics.append(
            _diagnostic(
                code=TSWAP_S140,
                severity=SchemaSeverity.ERROR,
                message=(
                    "the schema is not valid JSON Schema 2020-12 at "
                    f"`{error.json_path}`: {error.message}"
                ),
                remedy=(
                    "fix the schema so it validates against the 2020-12 meta-schema"
                ),
            )
        )
    return diagnostics


def _compile_block(
    block: Any,
    *,
    block_name: str,
    input_side: bool,
) -> tuple[dict[str, Any] | None, list[SchemaDiagnostic]]:
    """Compile one authored list block; the shared machinery for both sides.

    Args:
        block: The authored value of ``inputs:`` or ``outputs:``, any
            shape.
        block_name: ``"inputs"`` or ``"outputs"``; the diagnostic ``block``
            field and the label used in messages.
        input_side: ``True`` for inputs (``required`` collected, omitted
            when empty; a missing description is an ERROR that skips the
            entry) and ``False`` for outputs (no ``required`` key ever; a
            missing description is a WARNING and the property is still
            emitted).

    Returns:
        The compiled schema (or ``None`` on absence / any ERROR) and the
        diagnostics in detection order: block-level, per-entry in
        declaration order, then cross-entry.
    """
    if block is None:
        return None, []

    diagnostics: list[SchemaDiagnostic] = []
    properties: dict[str, Any] = {}
    required_names: list[str] = []
    seen_names: set[str] = set()

    if not isinstance(block, list):
        diagnostics.append(
            _diagnostic(
                code=TSWAP_S105,
                severity=SchemaSeverity.ERROR,
                message=(
                    f"{block_name} must be a list of entries, got "
                    f"{type(block).__name__}"
                ),
                remedy=f"make '{block_name}:' a YAML list of entries",
                block=block_name,
            )
        )
    else:
        for index, entry in enumerate(block):
            if not isinstance(entry, dict) or not entry:
                diagnostics.append(
                    _diagnostic(
                        code=TSWAP_S105,
                        severity=SchemaSeverity.ERROR,
                        message=(
                            f"{block_name}[{index}] must be a non-empty "
                            f"mapping of entry keys, got "
                            f"{type(entry).__name__}"
                        ),
                        remedy=(
                            f"write '{block_name}[{index}]' as a mapping "
                            "with at least a 'name'"
                        ),
                        entry_index=index,
                        block=block_name,
                    )
                )
                continue
            result = _compile_entry(
                entry,
                index=index,
                block_name=block_name,
                input_side=input_side,
                diagnostics=diagnostics,
            )
            if result is None:
                continue
            name, prop, is_required = result
            if name in seen_names:
                diagnostics.append(
                    _diagnostic(
                        code=TSWAP_S100,
                        severity=SchemaSeverity.ERROR,
                        message=(
                            f"{block_name}[{index}]: duplicate name "
                            f"'{name}'; each name must appear once"
                        ),
                        remedy=(
                            f"rename one of the '{name}' entries so each "
                            "name appears once"
                        ),
                        entry_index=index,
                        block=block_name,
                    )
                )
                continue
            seen_names.add(name)
            properties[name] = prop
            if input_side and is_required:
                required_names.append(name)

    schema: dict[str, Any] = {
        "$schema": JSON_SCHEMA_2020_12,
        "type": "object",
        "properties": properties,
    }
    if input_side and required_names:
        schema["required"] = required_names
    schema["additionalProperties"] = False

    if any(d.severity is SchemaSeverity.ERROR for d in diagnostics):
        return None, diagnostics
    return schema, diagnostics


def _compile_entry(
    entry: dict[str, Any],
    *,
    index: int,
    block_name: str,
    input_side: bool,
    diagnostics: list[SchemaDiagnostic],
) -> tuple[str, dict[str, Any], bool] | None:
    """Validate and compile one non-empty mapping entry.

    Check order within the entry: ``name`` (``S106``/``S102``), ``type``
    (``S103``), ``description`` (``S120`` for missing/blank, ``S108`` for
    non-string), ``required`` (``S107``, inputs only), ``semantic``
    (``S104``), ``items`` (``S109``/``S110``/``S103``).  A ``S120`` or
    ``S108`` finding ends the entry's remaining checks (on the output
    side the property is still emitted, without a ``description`` key).
    Duplicate names are detected by the caller, which owns the properties
    bookkeeping.

    Args:
        entry: The mapping entry, known to be a non-empty dict.
        index: Its 0-based position in the authored block.
        block_name: ``"inputs"`` or ``"outputs"``.
        input_side: Whether the input-side ``required`` and
            missing-description rules apply (see :func:`_compile_block`).
        diagnostics: Accumulator, appended in detection order.

    Returns:
        ``(name, property, is_required)`` when the entry is emitted, or
        ``None`` when an ERROR-skipping diagnostic fired.  The property's
        key order is pinned: ``type``, ``items``, ``description``,
        ``x-semantic`` (absent ones omitted).
    """
    location = f"{block_name}[{index}]"

    name = entry.get("name")
    if not isinstance(name, str) or not name:
        diagnostics.append(
            _diagnostic(
                code=TSWAP_S106,
                severity=SchemaSeverity.ERROR,
                message=(f"{location}: every entry needs a non-empty string 'name'"),
                remedy=f"add a non-empty string 'name' to '{location}'",
                entry_index=index,
                block=block_name,
            )
        )
        return None
    if not name.isidentifier() or keyword.iskeyword(name):
        suggested = name.replace("-", "_").replace(" ", "_") or "unnamed"
        diagnostics.append(
            _diagnostic(
                code=TSWAP_S102,
                severity=SchemaSeverity.WARNING,
                message=(
                    f"{block_name} name '{name}' is not a valid Python "
                    "identifier; handlers receive inputs as keyword "
                    "arguments, so this input can never be passed"
                ),
                remedy=(f"rename it to a valid identifier, e.g. '{suggested}'"),
                entry_index=index,
                block=block_name,
            )
        )

    type_value = entry.get("type")
    if not isinstance(type_value, str) or type_value not in SUPPORTED_TYPES:
        shown = "missing" if type_value is None else repr(type_value)
        diagnostics.append(
            _diagnostic(
                code=TSWAP_S103,
                severity=SchemaSeverity.ERROR,
                message=(
                    f"{location}: type {shown} is not supported; the "
                    "simple form accepts "
                    + ", ".join(SUPPORTED_TYPES)
                    + ". For enums, ranges, oneOf or nested objects use "
                    "the raw `json_schema:` block."
                ),
                remedy=(
                    "use one of the six types, or move this tool to a "
                    "`json_schema:` block"
                ),
                entry_index=index,
                block=block_name,
            )
        )
        return None

    # An input is required only if it explicitly writes `required: true`
    # (opt-in, plan line 1826: "required contains exactly the inputs with
    # `required: true`"); the output side never carries `required`.
    is_required = entry.get("required") is True
    items: dict[str, Any] | None = None
    x_semantic: str | None = None

    description = entry.get("description")
    if description is None or (
        isinstance(description, str) and not description.strip()
    ):
        # Missing or blank: S120.  On the input side the entry is skipped;
        # on the output side the property is still emitted, without a
        # description key, and the remaining per-entry checks are skipped
        # for this entry (pinned: the output-side array case with no
        # items reports only S120).
        _emit_s120(
            name=name,
            location=location,
            block_name=block_name,
            index=index,
            input_side=input_side,
            diagnostics=diagnostics,
        )
        if input_side:
            return None
        return name, {"type": type_value}, False
    elif not isinstance(description, str):
        diagnostics.append(
            _diagnostic(
                code=TSWAP_S108,
                severity=SchemaSeverity.ERROR,
                message=(
                    f"{location}: 'description' must be a string, got "
                    f"{type(description).__name__}"
                ),
                remedy=f"write '{location}.description' as a string",
                entry_index=index,
                block=block_name,
            )
        )
        return None

    if input_side and "required" in entry:
        required_value = entry["required"]
        if not isinstance(required_value, bool):
            diagnostics.append(
                _diagnostic(
                    code=TSWAP_S107,
                    severity=SchemaSeverity.ERROR,
                    message=(
                        f"{location}: 'required' must be a boolean, got "
                        f"{type(required_value).__name__}"
                    ),
                    remedy=f"set '{location}.required' to true or false",
                    entry_index=index,
                    block=block_name,
                )
            )
            is_required = False
        elif required_value is False:
            is_required = False

    semantic = entry.get("semantic")
    if semantic is not None:
        if isinstance(semantic, str):
            x_semantic = semantic
        else:
            diagnostics.append(
                _diagnostic(
                    code=TSWAP_S104,
                    severity=SchemaSeverity.ERROR,
                    message=(
                        f"{location}: 'semantic' must be a string, got "
                        f"{type(semantic).__name__}"
                    ),
                    remedy=(f"write '{location}.semantic' as a string, or remove it"),
                    entry_index=index,
                    block=block_name,
                )
            )
            return None

    if type_value == "array":
        raw_items = entry.get("items")
        if raw_items is None:
            diagnostics.append(
                _diagnostic(
                    code=TSWAP_S109,
                    severity=SchemaSeverity.ERROR,
                    message=(
                        f"{location}: type 'array' requires an 'items:' "
                        "declaring the element type"
                    ),
                    remedy=f"add 'items: <one of the six types>' to '{location}'",
                    entry_index=index,
                    block=block_name,
                )
            )
            return None
        items = _compile_items(
            raw_items,
            location=location,
            block_name=block_name,
            index=index,
            diagnostics=diagnostics,
        )
        if items is None:
            return None

    # Pinned property key order: type, items, description, x-semantic.
    # ``description`` here is a non-empty string: the missing/blank
    # (S120) and non-string (S108) cases returned earlier.
    prop: dict[str, Any] = {"type": type_value}
    if items is not None:
        prop["items"] = items
    if description is not None:
        prop["description"] = description
    if x_semantic is not None:
        prop["x-semantic"] = x_semantic
    return name, prop, is_required


def _compile_items(
    raw_items: Any,
    *,
    location: str,
    block_name: str,
    index: int,
    diagnostics: list[SchemaDiagnostic],
) -> dict[str, Any] | None:
    """Compile an ``array`` entry's ``items:`` into ``{"type": ...}``.

    A bare type name (``items: number``) and the mapping spelling
    (``items: {type: number}``) both compile to the same thing; the
    element type must itself be one of the six, and an ``items`` mapping
    carrying its own ``items``/``properties`` is nesting beyond one
    level.

    Args:
        raw_items: The authored ``items`` value, known to be present and
            not ``None``.
        location: The ``<block>[<i>]`` label for messages.
        block_name: ``"inputs"`` or ``"outputs"``.
        index: 0-based entry position, for the diagnostics.
        diagnostics: Accumulator, appended in detection order.

    Returns:
        The compiled ``{"type": ...}`` dict, or ``None`` when a skipping
        ERROR (``S110`` or ``S103``) was appended.
    """
    if isinstance(raw_items, dict):
        if "items" in raw_items or "properties" in raw_items:
            diagnostics.append(
                _diagnostic(
                    code=TSWAP_S110,
                    severity=SchemaSeverity.ERROR,
                    message=(
                        f"{location}: nested arrays are not supported by "
                        "the simple form; use a raw `json_schema:` block"
                    ),
                    remedy=(
                        "move this tool to a `json_schema:` block to "
                        "describe nested items"
                    ),
                    entry_index=index,
                    block=block_name,
                )
            )
            return None
        element_type = raw_items.get("type")
    elif isinstance(raw_items, str):
        element_type = raw_items
    else:
        element_type = None

    if element_type not in SUPPORTED_TYPES:
        shown = "missing" if element_type is None else repr(element_type)
        diagnostics.append(
            _diagnostic(
                code=TSWAP_S103,
                severity=SchemaSeverity.ERROR,
                message=(
                    f"{location}: items type {shown} is not supported; "
                    "the simple form accepts "
                    + ", ".join(SUPPORTED_TYPES)
                    + ". For enums, ranges, oneOf or nested objects use "
                    "the raw `json_schema:` block."
                ),
                remedy=(
                    "use one of the six types for 'items', or move this "
                    "tool to a `json_schema:` block"
                ),
                entry_index=index,
                block=block_name,
            )
        )
        return None

    return {"type": element_type}


def _emit_s120(
    *,
    name: str,
    location: str,
    block_name: str,
    index: int,
    input_side: bool,
    diagnostics: list[SchemaDiagnostic],
) -> None:
    """Append the missing/blank-description diagnostic (``TSWAP-S120``).

    The one code with two severities: ERROR on the input side (the entry
    is skipped) and WARNING on the output side (the property is still
    emitted, without a ``description`` key) — the same split as the
    config layer's ``C301``/``C302``.

    Args:
        name: The entry's name, for the message.
        location: The ``<block>[<i>]`` label for the message.
        block_name: ``"inputs"`` or ``"outputs"``.
        index: 0-based entry position.
        input_side: Selects the severity (see above).
        diagnostics: Accumulator, appended to.
    """
    severity = SchemaSeverity.ERROR if input_side else SchemaSeverity.WARNING
    diagnostics.append(
        _diagnostic(
            code=TSWAP_S120,
            severity=severity,
            message=(f"{location}: entry '{name}' is missing a description"),
            remedy=f"add a non-blank 'description' to '{location}'",
            entry_index=index,
            block=block_name,
        )
    )


def _param_names(params: Any) -> list[str]:
    """Collect the string ``name:`` values of a ``params:`` block, in order.

    Args:
        params: The authored ``params:`` value, any shape; non-mapping
            entries are skipped silently (malformed params belong to the
            config layer, not the compiler).

    Returns:
        The distinct names, first-occurrence order preserved.
    """
    names: list[str] = []
    if isinstance(params, list):
        for entry in params:
            if isinstance(entry, dict):
                name = entry.get("name")
                if isinstance(name, str) and name and name not in names:
                    names.append(name)
    return names


def _diagnostic(
    *,
    code: str,
    severity: SchemaSeverity,
    message: str,
    remedy: str,
    entry_index: int | None = None,
    block: str | None = None,
) -> SchemaDiagnostic:
    """Build one :class:`SchemaDiagnostic` with keyword-only fields.

    Args:
        code: The ``TSWAP-S1xx`` code.
        severity: ERROR or WARNING.
        message: The human-readable finding, naming the entry.
        remedy: The fix to apply; never empty.
        entry_index: 0-based position in the authored block, when the
            finding is per-entry.
        block: ``"inputs"`` or ``"outputs"``, when known.

    Returns:
        The frozen diagnostic.
    """
    return SchemaDiagnostic(
        code=code,
        severity=severity,
        message=message,
        remedy=remedy,
        entry_index=entry_index,
        block=block,
    )

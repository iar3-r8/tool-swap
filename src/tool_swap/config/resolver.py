"""Layer precedence resolution with origin tracking for one tool.

``resolve_tool`` merges a tool's layers — ``inline`` > ``tool.yaml`` >
``defaults:`` > group > built-in (group-supplied fields sit between
``defaults:`` and built-in, assumption A11) — into exactly the flat
built-in fields, recording winning and shadowed origins.  It is a pure
function of the layer dicts: no filesystem, no environment, no clock.
See ``plans/m1-configuration.md`` §1, behaviour 10.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, cast

from tool_swap.config.defaults import BUILT_IN_DEFAULTS, builtin_defaults
from tool_swap.config.errors import Diagnostic, Location, Severity
from tool_swap.config.origin import Origin, OriginLevel, OriginMap

_CODE_BAD_TTL: Final[str] = "TSWAP-C501"
_CODE_DUPLICATE_MOUNT: Final[str] = "TSWAP-C503"
_CODE_UNMAPPED_KEY: Final[str] = "TSWAP-C106"

#: Pinned flattening table: tool.yaml (block, key) -> flat field.
_FLATTENING_TABLE: Final[dict[tuple[str, str], str]] = {
    ("batching", "max_batch_size"): "max_batch_size",
    ("resources", "group"): "group",
    ("lifecycle", "ttl"): "ttl",
    ("lifecycle", "ready_timeout"): "ready_timeout",
    ("runtime", "server"): "runtime_server",
}

#: tool.yaml blocks whose nested keys must map to a flat field; an
#: unmapped nested key inside one is ``TSWAP-C106``.
_KNOWN_BLOCKS: Final[frozenset[str]] = frozenset(
    block for block, _key in _FLATTENING_TABLE
)

#: tool.yaml blocks that flatten their mapped keys but silently ignore
#: their unmapped ones instead of emitting ``TSWAP-C106``: ``runtime``'s
#: other keys (``base_image`` and the rest of the image-build surface)
#: are M2 concerns M1 does not own (plan, behaviour 14, block 3).
_PARTIAL_BLOCKS: Final[frozenset[str]] = frozenset({"runtime"})

#: Withdrawn/reserved keys behaviour 14 rejects, mapped to the layers the
#: schema reserves them at (mirrors the schema placement table).  Detected
#: by PRESENCE in a layer mapping, never by value ("soft_ttl: null" is
#: still present).
RESERVED_KEYS: Final[dict[str, frozenset[str]]] = {
    "soft_ttl": frozenset({"inline", "tool.yaml", "defaults"}),
    "scalar_inputs": frozenset({"inline", "tool.yaml"}),
    "max_batch_bytes": frozenset({"inline", "tool.yaml", "defaults"}),
}

#: The fixed origin a non-empty ``reserved_keys`` carrier records, per
#: layer label (the most-specific layer present wins).
_RESERVED_KEY_ORIGINS: Final[dict[str, tuple[OriginLevel, str]]] = {
    "inline": (OriginLevel.INLINE, "inline"),
    "tool.yaml": (OriginLevel.TOOL_YAML, "tool.yaml"),
    "defaults": (OriginLevel.DEFAULTS, "defaults"),
}


@dataclass(frozen=True)
class ResolvedTool:
    """The fully resolved configuration of one tool.

    Attributes:
        name: the tool name passed to :func:`resolve_tool`.
        values: flat field name -> resolved value; the key set is exactly
            ``set(BUILT_IN_DEFAULTS)``.
        origins: winning and shadowed origins per dotted path.
        diagnostics: the ``TSWAP-C501`` / ``TSWAP-C503`` / ``TSWAP-C106``
            diagnostics this resolution emitted (empty when clean).
        description: the layered (inline > ``tool.yaml``) tool description;
            ``None`` when no layer supplied the key.
        inputs: the ``tool.yaml`` ``inputs:`` block, deep-copied as authored
            (behaviour 20 owns the entry shape); ``None`` when absent.
        outputs: the ``tool.yaml`` ``outputs:`` block, same contract.
        params: the ``tool.yaml`` ``params:`` block, same contract.
        json_schema: the ``tool.yaml`` ``json_schema:`` block, same contract.
        reserved_keys: the withdrawn/reserved keys (:data:`RESERVED_KEYS`)
            PRESENT in this tool's layers, as ``(key, layer)`` pairs with
            the layer label (``"inline"`` / ``"tool.yaml"`` /
            ``"defaults"``), most-specific-first then key-sorted.
            Outside ``values`` on purpose (behaviour 14): the keys are
            reserved, never resolved fields.
    """

    name: str
    values: dict[str, object]
    origins: OriginMap
    diagnostics: list[Diagnostic]
    # Behaviour 13 carrier fields; outside ``values`` on purpose (plan
    # "Why not flat keys"): authored content, not resolvable fields.
    description: str | None = None
    inputs: list[dict[str, object]] | None = None
    outputs: list[dict[str, object]] | None = None
    params: list[dict[str, object]] | None = None
    json_schema: dict[str, object] | None = None
    # Behaviour 14 carrier field; trailing on purpose so every existing
    # construction site stays valid.
    reserved_keys: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class _Layer:
    """One flat configuration layer (highest specificity first in the list).

    Attributes:
        data: flat field name -> value; a key present with value ``None``
            is an explicit null (it wins), an absent key is unset.
        origin_for: maps a flat field name to this layer's origin for it
            (the group layer bakes the group name into the source).
    """

    data: Mapping[str, object]
    origin_for: Callable[[str], Origin]


def resolve_tool(
    name: str,
    *,
    inline: dict[str, object],
    tool_yaml: dict[str, object] | None = None,
    defaults: dict[str, object] | None = None,
    group: dict[str, object] | None = None,
) -> ResolvedTool:
    """Resolve one tool's layers into values, origins, and diagnostics.

    Precedence, most specific first: ``inline`` > ``tool.yaml`` >
    ``defaults`` > group > built-in.  A key absent from a layer falls
    through to the next layer; a key present with value ``None`` is an
    explicit null that wins and resolves to ``None``.  ``env`` merges
    key-by-key, ``mounts`` concatenate (built-in first, inline last),
    and every other field is replaced wholesale by the highest present
    layer.

    Args:
        name: the tool name, carried into the result and used as the
            diagnostic location's file.
        inline: the tool's inline entry (required).
        tool_yaml: the tool's ``tool.yaml`` mapping, or ``None``.
        defaults: the user's ``defaults:`` block, or ``None``.
        group: the tool's group definition (``"name"`` plus its fields),
            or ``None``; only tool-level fields are taken from it and
            group-only fields (``max_resident``, ``eviction``) are
            ignored without a diagnostic.

    Returns:
        A frozen :class:`ResolvedTool` whose ``values`` cover exactly the
        flat built-in fields and whose carrier fields carry the authored
        ``description`` (layered inline > ``tool.yaml``) and the
        ``tool.yaml``-only ``inputs`` / ``outputs`` / ``params`` /
        ``json_schema`` blocks.  All inputs are deep-copied on entry, so
        mutating a caller's dicts after the call, or one tool's result,
        can never affect another resolution.
    """
    diagnostics: list[Diagnostic] = []
    inline_data = copy.deepcopy(inline)
    if tool_yaml is not None:
        tool_flat = _flatten_tool_yaml(tool_yaml, name, diagnostics)
        if "description" in tool_yaml:
            # Additive: ``description`` is not a flat built-in field, so
            # it stays out of ``values`` and of the 47-key flattening;
            # this only makes it visible to the description layering.
            tool_flat["description"] = copy.deepcopy(tool_yaml["description"])
    else:
        tool_flat = {}
    group_layer = _group_layer(group)

    layers: list[_Layer] = [
        _Layer(inline_data, _fixed_origin(OriginLevel.INLINE, "inline")),
        _Layer(tool_flat, _fixed_origin(OriginLevel.TOOL_YAML, "tool.yaml")),
        _Layer(
            copy.deepcopy(defaults) if defaults is not None else {},
            _fixed_origin(OriginLevel.DEFAULTS, "defaults"),
        ),
    ]
    if group_layer is not None:
        layers.append(group_layer)
    layers.append(_Layer(builtin_defaults(), lambda _field: Origin.built_in()))

    values: dict[str, object] = {}
    origins = OriginMap()
    for field in BUILT_IN_DEFAULTS:
        if field == "env":
            _resolve_env(layers, values, origins)
        elif field == "mounts":
            _resolve_mounts(layers, values, origins, name, diagnostics)
        elif field == "ttl":
            _resolve_ttl(layers, layers[2], values, origins, name, diagnostics)
        else:
            _resolve_wholesale(layers, values, origins, field)

    # --- behaviour 13 carrier fields (outside ``values`` on purpose) ---
    description_winner = _winner_index_safe(layers, "description")
    # --- behaviour 14: reserved-key presence scan (no diagnostic of its
    # own; every C4xx is a rule reading ``reserved_keys``) ---
    reserved_keys = _scan_reserved_keys(inline_data, tool_yaml, defaults)
    if reserved_keys:
        origins.record("reserved_keys", _reserved_key_origin(reserved_keys))
    if description_winner < 0:
        description: str | None = None
    else:
        description = cast("str | None", layers[description_winner].data["description"])
        origins.record(
            "description",
            layers[description_winner].origin_for("description"),
        )
    inputs = _tool_yaml_carrier_list(tool_yaml, "inputs")
    outputs = _tool_yaml_carrier_list(tool_yaml, "outputs")
    params = _tool_yaml_carrier_list(tool_yaml, "params")
    json_schema = _tool_yaml_carrier_dict(tool_yaml, "json_schema")
    for key, block in (
        ("inputs", inputs),
        ("outputs", outputs),
        ("params", params),
        ("json_schema", json_schema),
    ):
        if block is not None:
            origins.record(key, _tool_yaml_origin())

    return ResolvedTool(
        name=name,
        values=values,
        origins=origins,
        diagnostics=diagnostics,
        description=description,
        inputs=inputs,
        outputs=outputs,
        params=params,
        json_schema=json_schema,
        reserved_keys=reserved_keys,
    )


def _winner_index_safe(layers: Sequence[_Layer], field: str) -> int:
    """Like :func:`_winner_index`, but ``-1`` when no layer has ``field``.

    Unlike :func:`_winner_index` this does not raise: the built-in layer
    does not carry ``description``, so the no-provider case is legal and
    must resolve to "absent" (behaviour 13).

    Args:
        layers: the layers, most specific first.
        field: the field name.

    Returns:
        The index of the first layer containing ``field``, or ``-1``.
    """
    for index, layer in enumerate(layers):
        if field in layer.data:
            return index
    return -1


def _tool_yaml_origin() -> Origin:
    """The fixed origin for a ``tool.yaml`` carrier field."""
    return Origin(level=OriginLevel.TOOL_YAML, source="tool.yaml")


def _tool_yaml_carrier_list(
    tool_yaml: Mapping[str, object] | None, key: str
) -> list[dict[str, object]] | None:
    """Deep-copy one list-shaped ``tool.yaml`` carrier block.

    Args:
        tool_yaml: the tool's ``tool.yaml`` mapping, or ``None``.
        key: the carrier key (``inputs`` / ``outputs`` / ``params``).

    Returns:
        A deep copy of the block's value, or ``None`` when the mapping is
        ``None`` or does not contain the key (``None`` stays distinct
        from ``[]``).  The value's inner shape is stored as authored;
        behaviour 20 owns validation.
    """
    if tool_yaml is None or key not in tool_yaml:
        return None
    return cast("list[dict[str, object]]", copy.deepcopy(tool_yaml[key]))


def _tool_yaml_carrier_dict(
    tool_yaml: Mapping[str, object] | None, key: str
) -> dict[str, object] | None:
    """Deep-copy the dict-shaped ``json_schema`` carrier block.

    Args:
        tool_yaml: the tool's ``tool.yaml`` mapping, or ``None``.
        key: the carrier key (``json_schema``).

    Returns:
        A deep copy of the block's value, or ``None`` when the mapping is
        ``None`` or does not contain the key.  The value's inner shape is
        stored as authored; behaviour 20 owns validation.
    """
    if tool_yaml is None or key not in tool_yaml:
        return None
    return cast("dict[str, object]", copy.deepcopy(tool_yaml[key]))


def _fixed_origin(level: OriginLevel, source: str) -> Callable[[str], Origin]:
    """Return an origin factory that ignores the field name.

    Args:
        level: the layer's origin level.
        source: the fixed source string (the resolver is a pure function
            of dicts, so it has no file/line to report).

    Returns:
        A callable mapping any flat field name to that fixed origin.
    """

    def origin_for(_field: str) -> Origin:
        """Return the fixed origin for any field."""
        return Origin(level=level, source=source)

    return origin_for


def _group_layer(group: Mapping[str, object] | None) -> _Layer | None:
    """Build the group layer, which sits between ``defaults:`` and built-in.

    Only keys that are tool-level fields are kept; ``"name"`` and
    group-only fields such as ``max_resident`` and ``eviction`` are
    ignored without a diagnostic.  ``OriginLevel`` has no ``GROUP``
    member (assumption A11), so group-supplied values record level
    ``DEFAULTS`` with the source ``groups.<name>.<field>``.

    Args:
        group: the group's own definition dict, or ``None``.

    Returns:
        The group layer, or ``None`` when no tool-level field is given.
    """
    if group is None:
        return None
    flat = {
        key: copy.deepcopy(value)
        for key, value in group.items()
        if key in BUILT_IN_DEFAULTS
    }
    if not flat:
        return None
    raw_name = group.get("name")
    name = raw_name if isinstance(raw_name, str) and raw_name else "unnamed"
    prefix = f"groups.{name}."

    def origin_for(field: str) -> Origin:
        """Return the group-named origin for ``field``."""
        return Origin(level=OriginLevel.DEFAULTS, source=prefix + field)

    return _Layer(flat, origin_for)


def _flatten_tool_yaml(
    tool_yaml: Mapping[str, object],
    tool_name: str,
    diagnostics: list[Diagnostic],
) -> dict[str, object]:
    """Flatten tool.yaml's nested blocks onto the tool's flat fields.

    A nested key inside a known block that maps to no flat field is
    ``TSWAP-C106``; a top-level key that is a flat field passes through,
    and on conflict a top-level key wins over its flattened twin.

    Args:
        tool_yaml: the tool's ``tool.yaml`` mapping.
        tool_name: the tool name, used as the diagnostic location's file.
        diagnostics: diagnostics are appended here as they are found.

    Returns:
        A fresh (deep-copied) flat mapping for the tool.yaml layer.
    """
    flat: dict[str, object] = {}
    for block, value in tool_yaml.items():
        if block not in _KNOWN_BLOCKS or not isinstance(value, Mapping):
            continue
        for key, nested in value.items():
            target = _FLATTENING_TABLE.get((block, key))
            if target is None:
                if block in _PARTIAL_BLOCKS:
                    # Unmapped keys of a partial block are a later
                    # milestone's concern; ignore silently (no C106).
                    continue
                diagnostics.append(_unmapped_key(tool_name, block, str(key)))
            else:
                flat[target] = copy.deepcopy(nested)
    for key, value in tool_yaml.items():
        if key in BUILT_IN_DEFAULTS:
            flat[key] = copy.deepcopy(value)
    return flat


def _unmapped_key(tool_name: str, block: str, key: str) -> Diagnostic:
    """Build the ``TSWAP-C106`` diagnostic for an unmapped nested key.

    Args:
        tool_name: the tool name, used as the diagnostic location's file.
        block: the known tool.yaml block the key sits in.
        key: the nested key that maps to no flat field.

    Returns:
        The ERROR diagnostic naming the offending key.
    """
    known = ", ".join(
        sorted(
            known_key
            for block_name, known_key in _FLATTENING_TABLE
            if block_name == block
        )
    )
    return Diagnostic(
        code=_CODE_UNMAPPED_KEY,
        severity=Severity.ERROR,
        message=f"tool.yaml key '{block}.{key}' does not map to any tool field",
        location=Location(file=tool_name, yaml_path=f"{block}.{key}"),
        remedy=f"remove '{key}' from the '{block}' block or use a mapped key ({known})",
    )


def _scan_reserved_keys(
    inline: Mapping[str, object],
    tool_yaml: Mapping[str, object] | None,
    defaults: Mapping[str, object] | None,
) -> tuple[tuple[str, str], ...]:
    """Scan the raw layers for the PRESENCE of reserved keys (behaviour 14).

    The scan is layer-scoped per key, exactly mirroring the schema
    placement table in :data:`RESERVED_KEYS`: the ``tool.yaml`` layer is
    read RAW (pre-flattening, which would drop the keys), and
    ``defaults:`` is only scanned for the keys the schema reserves there
    (so ``defaults.scalar_inputs`` stays a schema-level ``TSWAP-C101``
    and never also a ``TSWAP-C403``).  The group layer is never a
    reserved-key source.  Order is layer order, most specific first,
    then key-sorted within a layer, so the diagnostic sequence is
    deterministic without the rule re-sorting.

    Args:
        inline: the tool's inline entry (already deep-copied on entry).
        tool_yaml: the tool's raw ``tool.yaml`` mapping, or ``None``.
        defaults: the user's ``defaults:`` block, or ``None``.

    Returns:
        The ``(key, layer)`` pairs, ``()`` when no reserved key is
        present in any reserved layer.
    """
    layers: tuple[tuple[str, Mapping[str, object] | None], ...] = (
        ("inline", inline),
        ("tool.yaml", tool_yaml),
        ("defaults", defaults),
    )
    pairs: list[tuple[str, str]] = []
    for layer, data in layers:
        if data is None:
            continue
        found = sorted(
            key for key in data if key in RESERVED_KEYS and layer in RESERVED_KEYS[key]
        )
        pairs.extend((key, layer) for key in found)
    return tuple(pairs)


def _reserved_key_origin(reserved_keys: tuple[tuple[str, str], ...]) -> Origin:
    """The origin recorded for a non-empty ``reserved_keys`` carrier.

    Follows behaviour 13's carrier-field pattern: the most-specific
    layer present (the first pair's layer, the scan's emission order)
    supplies the origin.

    Args:
        reserved_keys: the non-empty carrier tuple.

    Returns:
        The origin for the most-specific layer present.
    """
    level, source = _RESERVED_KEY_ORIGINS[reserved_keys[0][1]]
    return Origin(level=level, source=source)


def _winner_index(layers: Sequence[_Layer], field: str) -> int:
    """Find the index of the highest layer that has ``field``.

    Args:
        layers: the layers, most specific first.
        field: the flat field name.

    Returns:
        The index of the first (highest) layer containing ``field``; the
        built-in layer always has every field, so this never fails.
    """
    for index, layer in enumerate(layers):
        if field in layer.data:
            return index
    raise AssertionError(f"no layer provides field {field!r}")


def _shadowed(layers: Sequence[_Layer], winner_index: int, field: str) -> list[Origin]:
    """Collect the origins of the lower layers that also have ``field``.

    Ordered most specific first.  The built-in layer (always last) is the
    baseline, not a shadowed layer, so it is excluded.

    Args:
        layers: the layers, most specific first.
        winner_index: the index of the winning layer.
        field: the flat field name.

    Returns:
        The shadowed origins, most specific first.
    """
    return [
        layer.origin_for(field)
        for layer in layers[winner_index + 1 : -1]
        if field in layer.data
    ]


def _resolve_wholesale(
    layers: Sequence[_Layer],
    values: dict[str, object],
    origins: OriginMap,
    field: str,
) -> None:
    """Merge a replace-wholesale field: the highest present layer wins.

    A key present with value ``None`` wins too (explicit null).

    Args:
        layers: the layers, most specific first.
        values: the result mapping to fill in.
        origins: the origin map to record into.
        field: the flat field name.
    """
    winner_index = _winner_index(layers, field)
    winner = layers[winner_index]
    origins.record(
        field,
        winner.origin_for(field),
        overrides=_shadowed(layers, winner_index, field),
    )
    values[field] = winner.data[field]


def _resolve_ttl(
    layers: Sequence[_Layer],
    defaults_layer: _Layer,
    values: dict[str, object],
    origins: OriginMap,
    tool_name: str,
    diagnostics: list[Diagnostic],
) -> None:
    """Merge ``ttl`` honouring the ``-1`` / ``0`` / ``>0`` sentinels.

    ``-1`` inherits ``defaults.ttl`` (or the built-in value when
    ``defaults:`` gives none) with the origin of the layer it inherited
    from; ``0`` and ``>0`` resolve as-is; below ``-1`` is ``TSWAP-C501``.

    Args:
        layers: the layers, most specific first.
        defaults_layer: the ``defaults:`` layer (always present, possibly
            empty), the sentinel's inheritance source.
        values: the result mapping to fill in.
        origins: the origin map to record into.
        tool_name: the tool name, used as the diagnostic location's file.
        diagnostics: diagnostics are appended here as they are found.
    """
    winner_index = _winner_index(layers, "ttl")
    winner = layers[winner_index]
    value = winner.data["ttl"]
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value < -1:
        diagnostics.append(_bad_ttl(tool_name, value))
        origins.record(
            "ttl",
            winner.origin_for("ttl"),
            overrides=_shadowed(layers, winner_index, "ttl"),
        )
        values["ttl"] = value
        return
    if value == -1:
        if "ttl" in defaults_layer.data and defaults_layer.data["ttl"] != -1:
            source_value, source_layer = defaults_layer.data["ttl"], defaults_layer
        else:
            source_value, source_layer = layers[-1].data["ttl"], layers[-1]
        source_index = layers.index(source_layer)
        origins.record(
            "ttl",
            source_layer.origin_for("ttl"),
            overrides=_shadowed(layers, source_index, "ttl"),
        )
        values["ttl"] = source_value
        return
    origins.record(
        "ttl",
        winner.origin_for("ttl"),
        overrides=_shadowed(layers, winner_index, "ttl"),
    )
    values["ttl"] = value


def _bad_ttl(tool_name: str, value: int | float) -> Diagnostic:
    """Build the ``TSWAP-C501`` diagnostic for a ``ttl`` below ``-1``.

    Args:
        tool_name: the tool name, used as the diagnostic location's file.
        value: the offending ttl value.

    Returns:
        The ERROR diagnostic naming the three legal sentinels.
    """
    return Diagnostic(
        code=_CODE_BAD_TTL,
        severity=Severity.ERROR,
        message=(
            f"ttl must be -1 (inherit), 0 (never stop), or a positive "
            f"number of seconds (>0); got {value}"
        ),
        location=Location(file=tool_name, yaml_path="ttl"),
        remedy="set ttl to -1, 0, or a positive number of seconds",
    )


def _resolve_env(
    layers: Sequence[_Layer],
    values: dict[str, object],
    origins: OriginMap,
) -> None:
    """Merge ``env`` key-by-key, the highest layer winning per key.

    Per-key origins are recorded at ``env.<KEY>``.  An explicit null
    (or any non-mapping) at the highest present layer wins whole, with
    no per-key merge.

    Args:
        layers: the layers, most specific first.
        values: the result mapping to fill in.
        origins: the origin map to record into.
    """
    winner_index = _winner_index(layers, "env")
    winner = layers[winner_index]
    winner_value = winner.data["env"]
    if not isinstance(winner_value, Mapping):
        origins.record("env", winner.origin_for("env"))
        values["env"] = winner_value
        return
    mapping_layers: list[tuple[int, Mapping[str, object]]] = []
    for index, layer in enumerate(layers):
        env = layer.data.get("env")
        if isinstance(env, Mapping):
            mapping_layers.append((index, env))
    merged: dict[str, object] = {}
    for key in _union_of_keys(mapping_layers):
        entries = [(index, env) for index, env in mapping_layers if key in env]
        winning_index, winning_env = entries[0]
        merged[key] = winning_env[key]
        origins.record(
            f"env.{key}",
            layers[winning_index].origin_for("env"),
            overrides=[layers[index].origin_for("env") for index, _env in entries[1:]],
        )
    values["env"] = merged


def _union_of_keys(
    mapping_layers: Sequence[tuple[int, Mapping[str, object]]],
) -> list[str]:
    """Collect all keys across the layers, most specific first.

    Args:
        mapping_layers: (layer index, env mapping) pairs, most specific
            first.

    Returns:
        The union of keys, first-seen order, most specific layer first.
    """
    keys: list[str] = []
    for _index, env in mapping_layers:
        for key in env:
            if key not in keys:
                keys.append(key)
    return keys


def _resolve_mounts(
    layers: Sequence[_Layer],
    values: dict[str, object],
    origins: OriginMap,
    tool_name: str,
    diagnostics: list[Diagnostic],
) -> None:
    """Concatenate ``mounts`` built-in first, inline last.

    Each entry's origin is recorded at ``mounts[i]``; a container path
    mounted in more than one layer emits one ``TSWAP-C503`` warning
    (duplicates are preserved).

    Args:
        layers: the layers, most specific first.
        values: the result mapping to fill in.
        origins: the origin map to record into.
        tool_name: the tool name, used as the diagnostic location's file.
        diagnostics: diagnostics are appended here as they are found.
    """
    entries: list[tuple[int, object]] = []
    for index in reversed(range(len(layers))):
        raw = layers[index].data.get("mounts")
        if not isinstance(raw, list):
            continue
        for entry in raw:
            entries.append((index, entry))
    values["mounts"] = [entry for _index, entry in entries]
    for position, (index, _entry) in enumerate(entries):
        origins.record(f"mounts[{position}]", layers[index].origin_for("mounts"))
    diagnostics.extend(_duplicate_container_paths(entries, tool_name))


def _duplicate_container_paths(
    entries: Sequence[tuple[int, object]],
    tool_name: str,
) -> list[Diagnostic]:
    """One ``TSWAP-C503`` per container path mounted in more than one layer.

    Args:
        entries: (layer index, mount entry) pairs, built-in first.
        tool_name: the tool name, used as the diagnostic location's file.

    Returns:
        The WARNING diagnostics, one per duplicated container path.
    """
    hosts_by_path: dict[str, list[tuple[int, str]]] = {}
    for index, entry in entries:
        if isinstance(entry, str):
            host, container = _split_mount(entry)
            hosts_by_path.setdefault(container, []).append((index, host))
    diagnostics: list[Diagnostic] = []
    for container, hosts in hosts_by_path.items():
        distinct_layers = {index for index, _host in hosts}
        if len(distinct_layers) < 2:
            continue
        ordered: list[str] = []
        for _index, host in hosts:
            if host not in ordered:
                ordered.append(host)
        diagnostics.append(
            Diagnostic(
                code=_CODE_DUPLICATE_MOUNT,
                severity=Severity.WARNING,
                message=(
                    f"duplicate container path '{container}' mounted at "
                    + " and ".join(ordered)
                ),
                location=Location(file=tool_name, yaml_path="mounts"),
                remedy=(
                    "remove one of the duplicate mounts so each container "
                    "path is mounted by a single layer"
                ),
            )
        )
    return diagnostics


def _split_mount(entry: str) -> tuple[str, str]:
    """Split ``host:container[:mode]`` into (host, container path).

    Args:
        entry: one mount string.

    Returns:
        The host source and the container path; an entry without a
        ``:`` counts as its own container path.
    """
    parts = entry.split(":")
    if len(parts) >= 2:
        return parts[0], parts[1]
    return parts[0], parts[0]

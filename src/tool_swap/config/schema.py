"""Pydantic schema for the top-level config and its diagnostic translation.

Every model mirrors one block of the documented config
(``plan/02_CONFIGURATION.md`` §3–§5) and forbids extra keys, so a typo is a
diagnostic rather than a silent no-op.  ``validate_root`` is the single entry
point: it takes an already-parsed YAML dict and returns ``Diagnostic`` values
— it raises nothing for config content and never lets Pydantic's raw
"Input should be ..." text reach the caller.

Codes emitted here: ``TSWAP-C001`` (unsupported config version),
``TSWAP-C101`` (unknown key, with a nearest-legal-alternative suggestion),
``TSWAP-C104`` (``devices`` given as a count instead of a list of GPU
indices, the R8 flaw of §5.4) and ``TSWAP-C105`` (any other schema-shape
error).
"""

from __future__ import annotations

import types
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tool_swap.config.errors import Diagnostic, Location, Severity
from tool_swap.config.suggest import nearest_alternative

#: The tool-swap release that owns this schema (named in the version message).
_CURRENT_VERSION = "0.1.0"

#: The only config major this build understands.
_SUPPORTED_VERSION = 1

#: Placeholder file name for diagnostics; the loader (behaviour 6) supplies
#: the real path once it exists.
_DEFAULT_FILE = "tools.yaml"

_CODE_UNSUPPORTED_VERSION = "TSWAP-C001"
_CODE_UNKNOWN_KEY = "TSWAP-C101"
_CODE_DEVICES_AS_COUNT = "TSWAP-C104"
_CODE_INVALID_SHAPE = "TSWAP-C105"


class RouterConfig(BaseModel):
    """The ``router:`` block — the HTTP front door (``plan/02`` §3)."""

    model_config = ConfigDict(extra="forbid")

    host: str = "0.0.0.0"
    port: int = 8600
    log_level: str = "INFO"
    log_dir: str = "./logs"
    log_json: bool = True
    cors_origins: list[str] = ["*"]
    auth_token: str | None = None
    status_page: bool = True


class BackendConfig(BaseModel):
    """The ``backend:`` block — container-runtime knobs (``plan/02`` §3)."""

    model_config = ConfigDict(extra="forbid")

    type: str = "docker"
    network: str = "tool-swap-net"
    container_prefix: str = "ms-"
    label_namespace: str = "com.tool-swap"
    gpu_runtime: str = "nvidia"
    orphans: str = "stop"
    port_range: list[int] = [7000, 7999]
    registry_prefix: str = "tool-swap"


class DefaultsConfig(BaseModel):
    """The ``defaults:`` block — values applied to every tool (``plan/02`` §3)."""

    model_config = ConfigDict(extra="forbid")

    # --- lifecycle / TTL ---
    ttl: int = 900
    keep_warm: bool = False
    autostart: bool = True
    # --- resources ---
    group: str = "default"
    devices: list[int] = []
    cpus: float | None = None
    memory: str | None = None
    shm_size: str = "1g"
    # --- batching ---
    max_batch_size: int = 8
    max_wait_ms: int = 20
    workers: int = 1
    runtime_server: str = "bentoml"
    # --- timeouts (seconds) ---
    start_timeout: int = 120
    ready_timeout: int = 600
    queue_timeout: int = 300
    request_timeout: int = 300
    drain_timeout: int = 30
    stop_timeout: int = 30
    max_queue_depth: int = 64
    # --- health probing ---
    health_path: str = "/health"
    ready_path: str = "/ready"
    probe_interval: float = 1.0
    # --- environment and storage (free-form values, plan line 103) ---
    env: dict[str, Any] = {}
    mounts: list[str] = []
    # --- reserved/withdrawn keys (behaviour 14): accepted, never resolved ---
    soft_ttl: Any = Field(
        default=None,
        description=(
            "RESERVED and rejected (TSWAP-C400): plan/adr/0004-hard-stop-"
            "only-in-v1.md (ADR-0004 — v1 reclaims resources by stopping "
            "containers; soft unload is deferred). ttl: is the only idle "
            "timer in v1."
        ),
    )
    max_batch_bytes: Any = Field(
        default=None,
        description=(
            "RESERVED and rejected (TSWAP-C405): no such key exists; set "
            "max_batch_size low for large payloads."
        ),
    )


class GroupConfig(BaseModel):
    """One ``groups.<name>:`` entry (``plan/02`` §3).

    Deliberately has no ``ttl`` — TTL is a tool-level and ``defaults:``
    concern, so a misspelled ``ttl`` inside ``groups:`` must not be
    "corrected" to a tool field.
    """

    model_config = ConfigDict(extra="forbid")

    max_resident: int = 4
    eviction: str = "lru"
    devices: list[int] | None = None


class BuildConfig(BaseModel):
    """The ``build:`` sub-block of a tool (``plan/02`` §5.2)."""

    model_config = ConfigDict(extra="forbid")

    context: str
    dockerfile: str = "Dockerfile"


class ToolConfig(BaseModel):
    """One inline ``tools.<name>:`` entry in the top-level config.

    Every field is optional-with-``None`` so that layering (inline >
    ``tool.yaml`` > ``defaults:`` > built-ins, ``plan/02`` §4.1) and the
    semantic checks of later behaviours (e.g. ``TSWAP-C300`` for a missing
    ``description``) stay in charge of their own diagnostics.

    ``description`` is inline-layerable: a key present with a blank value
    wins over a good ``tool.yaml`` one (behaviour 10 semantics).
    """

    model_config = ConfigDict(extra="forbid")

    path: str | None = None
    handler: str | None = None
    requirements: str | None = None
    build: BuildConfig | None = None
    group: str | None = None
    ttl: int | None = None
    devices: list[int] | None = None
    keep_warm: bool | None = None
    max_batch_size: int | None = None
    max_wait_ms: int | None = None
    mounts: list[str] | None = None
    env: dict[str, Any] | None = None
    description: str | None = None
    # --- reserved/withdrawn keys (behaviour 14): accepted, never resolved ---
    soft_ttl: Any = Field(
        default=None,
        description=(
            "RESERVED and rejected (TSWAP-C400): plan/adr/0004-hard-stop-"
            "only-in-v1.md (ADR-0004 — v1 reclaims resources by stopping "
            "containers; soft unload is deferred). ttl: is the only idle "
            "timer in v1."
        ),
    )
    scalar_inputs: Any = Field(
        default=None,
        description=(
            "RESERVED and rejected (TSWAP-C403): plan/adr/0005-one-uniform-"
            "batched-calling-convention.md (ADR-0005 — One uniform calling "
            "convention: every handler takes and returns a list)."
        ),
    )
    max_batch_bytes: Any = Field(
        default=None,
        description=(
            "RESERVED and rejected (TSWAP-C405): no such key exists; set "
            "max_batch_size low for large payloads."
        ),
    )


class ToolYamlConfig(BaseModel):
    """Schema for a tool directory's own ``tool.yaml`` (``plan/02`` §4).

    Minimal on purpose: behaviour 4 only pins that the model exists and
    forbids extra keys.  The identity fields of §4/§5.1 are included, all
    optional, so required-ness and reserved-key handling belong to the
    later behaviours that own those diagnostics.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    version: str | None = None
    description: str | None = None
    handler: str | None = None
    # Authoring blocks of plan/02 §4, stored as authored (not interpreted);
    # behaviour 20 owns the inner entry shape (TSWAP-S1xx).
    inputs: list[dict[str, Any]] | None = None
    outputs: list[dict[str, Any]] | None = None
    params: list[dict[str, Any]] | None = None
    json_schema: dict[str, Any] | None = None
    # --- reserved/withdrawn keys (behaviour 14): accepted, never resolved ---
    soft_ttl: Any = Field(
        default=None,
        description=(
            "RESERVED and rejected (TSWAP-C400): plan/adr/0004-hard-stop-"
            "only-in-v1.md (ADR-0004 — v1 reclaims resources by stopping "
            "containers; soft unload is deferred). ttl: is the only idle "
            "timer in v1."
        ),
    )
    scalar_inputs: Any = Field(
        default=None,
        description=(
            "RESERVED and rejected (TSWAP-C403): plan/adr/0005-one-uniform-"
            "batched-calling-convention.md (ADR-0005 — One uniform calling "
            "convention: every handler takes and returns a list)."
        ),
    )
    max_batch_bytes: Any = Field(
        default=None,
        description=(
            "RESERVED and rejected (TSWAP-C405): no such key exists; set "
            "max_batch_size low for large payloads."
        ),
    )


class RootConfig(BaseModel):
    """The top-level config document (``tools.yaml``)."""

    model_config = ConfigDict(extra="forbid")

    version: int | None = None
    router: RouterConfig | None = None
    backend: BackendConfig | None = None
    defaults: DefaultsConfig | None = None
    groups: dict[str, GroupConfig] = {}
    tools: dict[str, ToolConfig] = {}


def validate_root(data: dict[str, Any]) -> list[Diagnostic]:
    """Validate an already-parsed YAML dict against :class:`RootConfig`.

    Args:
        data: The parsed top-level config (a mapping).

    Returns:
        One ``Diagnostic`` per problem found — all problems, not just the
        first — or an empty list when the config is valid.  An unsupported
        ``version`` short-circuits to a single ``TSWAP-C001``: the rest of
        the document would be checked against the wrong schema anyway.
        Never raises for config content.
    """
    version = data.get("version")
    if version is not None and version != _SUPPORTED_VERSION:
        return [_unsupported_version(version)]
    try:
        RootConfig.model_validate(data)
    except ValidationError as exc:
        return _translate_validation_error(exc)
    return []


def _unsupported_version(version: object) -> Diagnostic:
    """Build the ``TSWAP-C001`` diagnostic for an unsupported config major."""
    message = (
        f"config version {version} is not supported by tool-swap "
        f"{_CURRENT_VERSION}; this version understands version "
        f"{_SUPPORTED_VERSION}"
    )
    return Diagnostic(
        code=_CODE_UNSUPPORTED_VERSION,
        severity=Severity.ERROR,
        message=message,
        location=Location(file=_DEFAULT_FILE, yaml_path="version"),
        remedy="set version: 1 (or omit the key) — this build reads only "
        "config version 1",
    )


def _translate_validation_error(exc: ValidationError) -> list[Diagnostic]:
    """Convert every error of ``exc`` into a coded, actionable Diagnostic.

    Args:
        exc: The ``ValidationError`` raised while validating the document.

    Returns:
        One diagnostic per reported error, in Pydantic's order.
    """
    diagnostics: list[Diagnostic] = []
    for err in exc.errors():
        err_type: str = str(err["type"])
        loc: tuple[object, ...] = tuple(err["loc"])
        if err_type == "extra_forbidden":
            diagnostics.append(_unknown_key(loc))
        elif loc and str(loc[-1]) == "devices" and not isinstance(loc[-1], int):
            diagnostics.append(_devices_as_count(loc))
        else:
            diagnostics.append(_invalid_shape(loc))
    return diagnostics


def _model_at_path(
    root: type[BaseModel], path: tuple[object, ...]
) -> type[BaseModel] | None:
    """Resolve the model class that owns the mapping at ``path``.

    Args:
        root: The model to start from (the document root).
        path: Field names down to the *parent* of the offending key; a part
            following a ``dict[str, Model]`` field names a mapping entry,
            not a field, and is matched accordingly.

    Returns:
        The model class of the containing mapping, or ``None`` when the path
        cannot be resolved to one (e.g. it ends inside a scalar).
    """
    current: type[BaseModel] | None = root
    next_part_is_mapping_entry = False
    for part in path:
        if next_part_is_mapping_entry:
            next_part_is_mapping_entry = False
            continue
        if current is None or not isinstance(part, str):
            return None
        field = current.model_fields.get(part)
        if field is None:
            return None
        inner = _inner_model(field.annotation)
        if _is_mapping_of_models(field.annotation) and inner is not None:
            next_part_is_mapping_entry = True
        current = inner
    return current


def _inner_model(annotation: Any) -> type[BaseModel] | None:
    """Extract the ``BaseModel`` class a field annotation ultimately holds.

    Args:
        annotation: A field annotation (possibly optional, ``list[...]``,
            ``dict[...]`` or a plain class).

    Returns:
        The first ``BaseModel`` subclass found inside the annotation, or
        ``None`` for scalar/free-form annotations.
    """
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        for arg in get_args(annotation):
            if arg is type(None):
                continue
            found = _inner_model(arg)
            if found is not None:
                return found
        return None
    if origin in (dict, list, tuple):
        for arg in get_args(annotation):
            found = _inner_model(arg)
            if found is not None:
                return found
        return None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def _is_mapping_of_models(annotation: Any) -> bool:
    """True when ``annotation`` is a ``dict[str, Model]`` of model values."""
    return get_origin(annotation) is dict and _inner_model(annotation) is not None


def _unknown_key(loc: tuple[object, ...]) -> Diagnostic:
    """Build the ``TSWAP-C101`` diagnostic for an unknown key at ``loc``.

    The suggestion is computed over the field names of the model that owns
    the *containing* mapping, so the same misspelling yields the right
    answer in ``tools.<name>:`` and the right non-answer in ``groups:``.
    """
    key = str(loc[-1])
    parent = _model_at_path(RootConfig, loc[:-1])
    candidates: list[str] = list(parent.model_fields) if parent is not None else []
    parent_name = _path_name(loc[:-1])
    suggestion = nearest_alternative(key, candidates)
    if suggestion is not None:
        message = f"unknown key '{key}' in {parent_name} — did you mean '{suggestion}'?"
        remedy = f"rename '{key}' to '{suggestion}'"
    elif candidates:
        listed = ", ".join(sorted(candidates))
        message = f"unknown key '{key}' in {parent_name} — valid keys are: {listed}"
        remedy = "remove the key or rename it to one of the valid keys"
    else:
        message = f"unknown key '{key}' in {parent_name}"
        remedy = "remove the key"
    return Diagnostic(
        code=_CODE_UNKNOWN_KEY,
        severity=Severity.ERROR,
        message=message,
        location=Location(file=_DEFAULT_FILE, yaml_path=_path_name(loc)),
        remedy=remedy,
    )


def _devices_as_count(loc: tuple[object, ...]) -> Diagnostic:
    """Build the ``TSWAP-C104`` diagnostic for ``devices: <count>``.

    The bespoke message cites the R8 flaw of ``plan/02`` §5.4: a bare number
    reads like a device index but behaves like a count.
    """
    message = (
        "'devices' is a list of GPU indices, not a count — write "
        "'devices: [3]' for GPU 3, or 'devices: [0,1,2]' for three GPUs "
        "(plan/02_CONFIGURATION.md §5.4)"
    )
    return Diagnostic(
        code=_CODE_DEVICES_AS_COUNT,
        severity=Severity.ERROR,
        message=message,
        location=Location(file=_DEFAULT_FILE, yaml_path=_path_name(loc)),
        remedy="replace the number with a list of GPU indices, e.g. devices: [0,1,2]",
    )


def _invalid_shape(loc: tuple[object, ...]) -> Diagnostic:
    """Build a generic ``TSWAP-C105`` diagnostic for any other shape error."""
    leaf = _leaf_name(loc)
    parent_name = _path_name(loc[:-1])
    field = _field_at(loc)
    if field is not None:
        expected = _describe_type(field.annotation)
        message = f"invalid value for '{leaf}' in {parent_name}: expected {expected}"
    else:
        message = f"invalid value for '{leaf}' in {parent_name}"
    return Diagnostic(
        code=_CODE_INVALID_SHAPE,
        severity=Severity.ERROR,
        message=message,
        location=Location(file=_DEFAULT_FILE, yaml_path=_path_name(loc) or None),
        remedy="check the documented type in plan/02_CONFIGURATION.md §5 "
        "and fix the value",
    )


def _field_at(loc: tuple[object, ...]) -> Any:
    """The ``FieldInfo`` owning the offending key, or ``None``."""
    parent = _model_at_path(RootConfig, loc[:-1])
    if parent is None or not loc or not isinstance(loc[-1], str):
        return None
    return parent.model_fields.get(loc[-1])


def _leaf_name(loc: tuple[object, ...]) -> str:
    """Render the offending position, indexing list items as ``name[i]``."""
    if not loc:
        return "the whole document"
    if isinstance(loc[-1], int) and len(loc) >= 2:
        return f"{_leaf_name(loc[:-1])}[{loc[-1]}]"
    return str(loc[-1])


def _path_name(loc: tuple[object, ...]) -> str:
    """Dotted path for a location tuple, or ``root`` for the document top."""
    return ".".join(str(part) for part in loc) or "root"


_BASIC_TYPE_NAMES: dict[type, str] = {
    int: "an integer",
    float: "a number",
    str: "a string",
    bool: "a boolean",
    list: "a list",
    dict: "a mapping",
}


def _describe_type(annotation: Any) -> str:
    """A plain-English name for a field annotation (no Pydantic internals).

    Args:
        annotation: The annotation to describe.

    Returns:
        A short phrase such as ``"a list of integers"`` or ``"a string or
        null"``; falls back to the annotation's own name, or to a generic
        phrase when it cannot be named.
    """
    if annotation is type(None):
        return "null"
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        parts = [_describe_type(arg) for arg in get_args(annotation)]
        return " or ".join(parts)
    if origin is list:
        args = get_args(annotation)
        item = _describe_type(args[0]) if args else "values"
        return f"a list of {item}"
    if origin is dict:
        return "a mapping"
    if isinstance(annotation, type):
        if annotation in _BASIC_TYPE_NAMES:
            return _BASIC_TYPE_NAMES[annotation]
        if issubclass(annotation, BaseModel):
            return f"a {annotation.__name__} block"
        return f"a {annotation.__name__}"
    return "the documented type"

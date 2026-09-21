"""Pins build_container_spec (m2b plan \u00a73): the core assembly (behaviour 1)
and the ParsedMount \u2192 MountSpec conversion (behaviour 2): entry order,
the mode \u2192 read_only normalisation, duplicate targets, and the raise
paths. The import is deferred to call time so a missing module fails per
test, not at collection."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

from tool_swap.backend.base import ContainerSpec, MountSpec
from tool_swap.backend.labels import container_name, managed_labels
from tool_swap.config.defaults import BUILT_IN_DEFAULTS
from tool_swap.config.resolver import ResolvedTool, resolve_tool
from tool_swap.config.schema import BackendConfig

TOOL = "t1"
IMAGE = "registry.example.com/acme/model:1.0"

# The four backend-named keys are also present in ResolvedTool.values, always
# carrying the built-in value (m2b plan \u00a76.3); the fixtures rely on that.
_BACKEND_KEYS = ("network", "container_prefix", "label_namespace", "gpu_runtime")

# A fixed config directory that never exists; mount resolution is lexical
# (normpath, no disk, no CWD), so no filesystem is ever touched.
_CFG_DIR: Final[Path] = Path("/cfg")


def _build_container_spec() -> Callable[..., Any]:
    """Return build_container_spec, importing the module at call time.

    Raises:
        AssertionError: the module or function is missing; the message names
            the file to create.
    """
    try:
        module: ModuleType = importlib.import_module("tool_swap.lifecycle.spec_builder")
    except ModuleNotFoundError as exc:
        raise AssertionError(
            "tool_swap.lifecycle.spec_builder is missing \u2014 create "
            "src/tool_swap/lifecycle/spec_builder.py"
        ) from exc
    try:
        return module.build_container_spec
    except AttributeError as exc:
        raise AssertionError(
            "build_container_spec is missing from "
            "src/tool_swap/lifecycle/spec_builder.py"
        ) from exc


def _resolved_tool() -> ResolvedTool:
    """A resolved tool whose values carry the built-ins except
    container_port, resolved to 8080 inline."""
    return resolve_tool(TOOL, inline={"container_port": 8080})


def _backend_config() -> BackendConfig:
    """A backend block whose four backend-named values all diverge from the
    built-in defaults."""
    return BackendConfig(
        network="acme-net",
        container_prefix="acme-",
        label_namespace="acme.model",
        gpu_runtime="cuda",
    )


def _build_with_config_dir(resolved: ResolvedTool, config_dir: Path) -> ContainerSpec:
    """Build the spec for resolved with the config directory supplied.

    Raises:
        AssertionError: the builder's signature does not accept a
            config_dir keyword; the message names the file to change, so a
            missing parameter fails as an assertion, not a bare TypeError.
    """
    builder = _build_container_spec()
    try:
        return builder(resolved, _backend_config(), IMAGE, config_dir=config_dir)
    except TypeError as exc:
        raise AssertionError(
            "build_container_spec must accept the config directory for "
            "relative-host resolution \u2014 extend its signature in "
            "src/tool_swap/lifecycle/spec_builder.py"
        ) from exc


def _resolved_tool_mounted(*entries: str) -> ResolvedTool:
    """A resolved tool whose inline layer carries exactly the given mount
    entries; the built-in list is empty, so the resolved list is the inline
    entries, in order."""
    return resolve_tool(TOOL, inline={"container_port": 8080, "mounts": list(entries)})


def _assert_sources_diverge(resolved: ResolvedTool, cfg: BackendConfig) -> None:
    """Fail if the two sources agree, which would make the source test
    vacuous."""
    for key in _BACKEND_KEYS:
        assert resolved.values[key] == BUILT_IN_DEFAULTS[key], (
            f"fixture values carry {key!r} = {resolved.values[key]!r}, not the "
            f"built-in {BUILT_IN_DEFAULTS[key]!r}"
        )
        assert getattr(cfg, key) != BUILT_IN_DEFAULTS[key], (
            f"fixture BackendConfig {key!r} equals the built-in "
            f"{BUILT_IN_DEFAULTS[key]!r}; the fixtures must diverge"
        )


def test_backend_named_fields_come_from_backend_config_not_values() -> None:
    """name, network, gpu_runtime and labels reflect the BackendConfig's
    divergent values, not the built-ins carried in ResolvedTool.values."""
    # Arrange
    resolved = _resolved_tool()
    cfg = _backend_config()
    _assert_sources_diverge(resolved, cfg)
    builtin_prefix = str(resolved.values["container_prefix"])
    # Act
    builder = _build_container_spec()
    spec = builder(resolved, cfg, IMAGE)
    # Assert
    assert spec.name == container_name(cfg.container_prefix, TOOL)
    assert spec.name != container_name(builtin_prefix, TOOL)
    assert spec.network == cfg.network
    assert spec.gpu_runtime == cfg.gpu_runtime
    assert spec.labels == managed_labels(cfg.label_namespace, TOOL)


def test_tool_image_and_container_port_come_from_the_resolved_tool() -> None:
    """tool and image pass through as given, and container_port is read from
    ResolvedTool.values rather than a configured default."""
    # Arrange
    resolved = _resolved_tool()
    assert resolved.values["container_port"] == 8080
    assert resolved.values["container_port"] != BUILT_IN_DEFAULTS["container_port"]
    # Act
    builder = _build_container_spec()
    spec = builder(resolved, _backend_config(), IMAGE)
    # Assert
    assert isinstance(spec, ContainerSpec)
    assert spec.tool == TOOL
    assert spec.image == IMAGE
    assert spec.container_port == 8080


@pytest.mark.parametrize(
    ("prefix", "tool_name"),
    [
        ("UP-", "t1"),  # the concatenation breaks the name pattern
        ("ms-", "Bad"),  # the tool name itself breaks the name pattern
    ],
)
def test_container_name_value_error_propagates(prefix: str, tool_name: str) -> None:
    """A name container_name rejects (tool or concatenation) surfaces as the
    same ValueError, not a reworded or swallowed one."""
    # Arrange
    resolved = resolve_tool(tool_name, inline={})
    cfg = BackendConfig(container_prefix=prefix)
    with pytest.raises(ValueError) as expected:
        container_name(prefix, tool_name)
    # Act
    builder = _build_container_spec()
    with pytest.raises(ValueError) as caught:
        builder(resolved, cfg, IMAGE)
    # Assert
    assert str(caught.value) == str(expected.value)


def test_empty_image_raises_value_error_naming_the_tool() -> None:
    """An empty image is refused with a ValueError naming the tool, before it
    can reach the backend's run-kwargs construction."""
    # Arrange
    resolved = _resolved_tool()
    cfg = _backend_config()
    # Act
    builder = _build_container_spec()
    with pytest.raises(ValueError) as excinfo:
        builder(resolved, cfg, "")
    # Assert
    assert TOOL in str(excinfo.value)


def test_backend_config_is_a_required_argument() -> None:
    """Omitting the BackendConfig is a TypeError: it is a separate required
    argument, never read out of ResolvedTool.values."""
    # Arrange
    resolved = _resolved_tool()
    # Act
    builder = _build_container_spec()
    with pytest.raises(TypeError):
        builder(resolved, IMAGE)


# ---------------------------------------------------------------------------
# Behaviour 2 \u2014 ParsedMount \u2192 MountSpec (m2b plan \u00a73.2, D-D)
# ---------------------------------------------------------------------------


def test_mount_entries_appear_in_declaration_order() -> None:
    """One MountSpec per entry, in declaration order, with source, target
    and read_only per entry \u2014 a reordered or re-sorted conversion is
    invisible unless the full sequence is pinned."""
    # Arrange
    entries = ["/h/one:/mnt/one:rw", "/h/two:/mnt/two", "/h/three:/mnt/three:ro"]
    resolved = _resolved_tool_mounted(*entries)
    assert resolved.values["mounts"] == entries
    # Act
    spec = _build_with_config_dir(resolved, _CFG_DIR)
    # Assert
    assert [m.source for m in spec.mounts] == ["/h/one", "/h/two", "/h/three"]
    assert [m.target for m in spec.mounts] == ["/mnt/one", "/mnt/two", "/mnt/three"]
    assert [m.read_only for m in spec.mounts] == [False, True, True]


def test_relative_host_resolves_against_config_dir_not_the_tool_dir() -> None:
    """source is the host resolved against the config directory lexically,
    never against the tool's base_dir \u2014 a wrong resolution base or a
    skipped resolution yields a tool-relative or CWD-relative source."""
    # Arrange
    resolved = resolve_tool(
        TOOL,
        inline={"container_port": 8080, "mounts": ["data/weights:/mnt/weights"]},
        base_dir=Path("/tools/t1"),
    )
    # Act
    spec = _build_with_config_dir(resolved, _CFG_DIR)
    # Assert
    (mount,) = spec.mounts
    assert mount.source == "/cfg/data/weights"
    assert mount.source != "/tools/t1/data/weights"


@pytest.mark.parametrize(
    ("entry", "read_only"),
    [
        ("/models/a:/mnt/a", True),  # 2-part: mode defaulted to "ro"
        ("/models/a:/mnt/a:ro", True),  # explicit ro
        ("/models/a:/mnt/a:rw", False),  # explicit rw
    ],
)
def test_mount_mode_maps_to_read_only(entry: str, read_only: bool) -> None:
    """The mode \u2192 read_only normalisation: the defaulted two-part form
    and explicit ro are read-only, explicit rw is not \u2014 a flipped or
    defaulted bool violates plan/01 \u00a710's read-only-by-default."""
    # Arrange
    resolved = _resolved_tool_mounted(entry)
    # Act
    spec = _build_with_config_dir(resolved, _CFG_DIR)
    # Assert
    assert spec.mounts == (
        MountSpec(source="/models/a", target="/mnt/a", read_only=read_only),
    )


def test_defaults_mounts_come_before_tool_mounts() -> None:
    """The resolver's defaults-then-tool concatenation survives into the
    spec's order \u2014 a builder that replaces instead of concatenates, or
    reorders, loses or moves the default mounts."""
    # Arrange
    resolved = resolve_tool(
        TOOL,
        inline={"container_port": 8080, "mounts": ["/tool:/mnt/tool:rw"]},
        defaults={"mounts": ["/def:/mnt/def"]},
    )
    assert resolved.values["mounts"] == ["/def:/mnt/def", "/tool:/mnt/tool:rw"]
    # Act
    spec = _build_with_config_dir(resolved, _CFG_DIR)
    # Assert
    assert [m.source for m in spec.mounts] == ["/def", "/tool"]
    assert [m.read_only for m in spec.mounts] == [True, False]


def test_duplicate_container_targets_keep_both_entries() -> None:
    """The same container target twice keeps both entries \u2014
    de-duplication is config validation's job; a silent drop loses a mount."""
    # Arrange
    resolved = _resolved_tool_mounted("/a:/dup", "/b:/dup")
    # Act
    spec = _build_with_config_dir(resolved, _CFG_DIR)
    # Assert
    assert len(spec.mounts) == 2
    assert [m.source for m in spec.mounts] == ["/a", "/b"]
    assert [m.target for m in spec.mounts] == ["/dup", "/dup"]


def test_no_mounts_yields_empty_tuple() -> None:
    """A tool with no mounts yields the ContainerSpec default of (), not a
    missing attribute or a stray empty entry."""
    # Arrange
    resolved = _resolved_tool()
    # Act
    builder = _build_container_spec()
    spec = builder(resolved, _backend_config(), IMAGE)
    # Assert
    assert spec.mounts == ()


@pytest.mark.parametrize("mode", ["RO", "r", "rw2"])
def test_mount_mode_outside_ro_and_rw_raises_naming_tool_entry_and_mode(
    mode: str,
) -> None:
    """A mode outside {ro, rw} raises a ValueError naming the tool, the
    entry and the offending mode \u2014 a silent downgrade to read-only
    would hide a broken upstream invariant (decision D-D)."""
    # Arrange
    entry = f"/models/a:/mnt/a:{mode}"
    resolved = _resolved_tool_mounted(entry)
    # Act
    with pytest.raises(ValueError) as excinfo:
        _build_with_config_dir(resolved, _CFG_DIR)
    # Assert
    message = str(excinfo.value)
    assert TOOL in message
    assert entry in message
    assert mode in message


@pytest.mark.parametrize(
    "entry",
    [
        "host",  # 1 part: no colon
        ":/x",  # 2 parts: empty host
        "/h:/c:",  # 3 parts: empty mode
        "/h:/c:ro:extra",  # 4 parts
    ],
)
def test_unparseable_mount_entry_raises_naming_tool_and_entry(entry: str) -> None:
    """An entry parse_mount cannot parse (a C540 shape) raises a ValueError
    naming the tool and the entry \u2014 a silent drop would yield a
    container whose mounts do not match its config."""
    # Arrange
    resolved = _resolved_tool_mounted(entry)
    # Act
    with pytest.raises(ValueError) as excinfo:
        _build_with_config_dir(resolved, _CFG_DIR)
    # Assert
    message = str(excinfo.value)
    assert TOOL in message
    assert entry in message


def test_relative_mount_without_config_dir_raises() -> None:
    """A relative host with no config_dir raises a ValueError naming the
    tool, rather than silently resolving against the CWD."""
    # Arrange
    resolved = _resolved_tool_mounted("data/weights:/mnt/weights")
    # Act
    builder = _build_container_spec()
    with pytest.raises(ValueError) as excinfo:
        builder(resolved, _backend_config(), IMAGE)
    # Assert
    assert TOOL in str(excinfo.value)

"""Pins build_container_spec's core assembly (m2b plan \u00a73, behaviour 1):
each spec field's source and the ValueError paths. The import is deferred
to call time so a missing module fails per test, not at collection."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest

from tool_swap.backend.base import ContainerSpec
from tool_swap.backend.labels import container_name, managed_labels
from tool_swap.config.defaults import BUILT_IN_DEFAULTS
from tool_swap.config.resolver import ResolvedTool, resolve_tool
from tool_swap.config.schema import BackendConfig

TOOL = "t1"
IMAGE = "registry.example.com/acme/model:1.0"

# The four backend-named keys are also present in ResolvedTool.values, always
# carrying the built-in value (m2b plan \u00a76.3); the fixtures rely on that.
_BACKEND_KEYS = ("network", "container_prefix", "label_namespace", "gpu_runtime")


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

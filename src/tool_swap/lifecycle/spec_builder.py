"""The config -> ContainerSpec builder (m2b plan §3).

Core assembly (behaviour 1) plus the ParsedMount -> MountSpec conversion
(behaviour 2); the resource, environment and port fields (behaviour 3)
keep their ContainerSpec defaults here.
"""

from __future__ import annotations

from pathlib import Path

from tool_swap.backend.base import ContainerSpec, MountSpec
from tool_swap.backend.labels import container_name, managed_labels
from tool_swap.config.resolver import ResolvedTool
from tool_swap.config.schema import BackendConfig
from tool_swap.config.validate import parse_mount


def build_container_spec(
    resolved: ResolvedTool,
    cfg: BackendConfig,
    image: str,
    *,
    config_dir: Path | None = None,
) -> ContainerSpec:
    """Assemble the core ContainerSpec from both config blocks.

    Raises ValueError for an empty image, an unparseable mount entry, a
    mount mode outside ro/rw (D-D), or mounts without a config_dir; a
    name container_name rejects propagates unchanged. The backend-named
    values come from cfg, never resolved.values (plan §6.3).
    """
    tool = resolved.name
    if not image:
        raise ValueError(f"image for tool {tool!r} must not be empty")
    port = resolved.values["container_port"]
    if not isinstance(port, int):
        raise TypeError(
            f"container_port for tool {tool!r} must be an int, "
            f"got {type(port).__name__}"
        )
    # The four backend-named keys are also in resolved.values, but always
    # carrying the built-in: the backend: block is not a resolver layer.
    return ContainerSpec(
        tool=tool,
        name=container_name(cfg.container_prefix, tool),
        image=image,
        gpu_runtime=cfg.gpu_runtime,
        container_port=port,
        labels=managed_labels(cfg.label_namespace, tool),
        network=cfg.network,
        mounts=_mount_specs(resolved, config_dir),
    )


def _mount_specs(
    resolved: ResolvedTool, config_dir: Path | None
) -> tuple[MountSpec, ...]:
    """One MountSpec per authored entry, in declaration order (plan §3.2).

    Raises:
        ValueError: an unparseable entry, a mode outside ro/rw (D-D), or
            any entry while ``config_dir`` is None.
        TypeError: ``mounts`` is not a list of strings.
    """
    tool = resolved.name
    raw = resolved.values["mounts"]
    if not isinstance(raw, list):
        raise TypeError(
            f"mounts for tool {tool!r} must be a list of str, got {type(raw).__name__}"
        )
    if not raw:
        return ()
    # Without a base, a relative host would resolve against the router's
    # CWD; parse_mount has no default base, so refuse up front.
    if config_dir is None:
        raise ValueError(
            f"mounts for tool {tool!r} cannot be resolved without a "
            "config_dir; refusing to fall back to the router's CWD"
        )
    specs: list[MountSpec] = []
    for entry in raw:
        if not isinstance(entry, str):
            raise TypeError(
                f"mounts for tool {tool!r} must be a list of str, "
                f"got {type(entry).__name__} entry"
            )
        # The resolution base is the config directory, never base_dir.
        parsed = parse_mount(entry, config_dir=config_dir)
        if parsed is None:
            raise ValueError(
                f"mount entry {entry!r} for tool {tool!r} is unparseable "
                "(expected host:container or host:container:ro|rw)"
            )
        if parsed.mode not in ("ro", "rw"):
            raise ValueError(
                f"mount entry {entry!r} for tool {tool!r} has mode "
                f"{parsed.mode!r}; only 'ro' and 'rw' are legal"
            )
        specs.append(
            MountSpec(
                source=str(parsed.resolved_host),
                target=parsed.container,
                read_only=(parsed.mode == "ro"),
            )
        )
    return tuple(specs)

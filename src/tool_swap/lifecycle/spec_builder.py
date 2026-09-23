"""The config -> ContainerSpec builder.

``build_container_spec`` assembles a tool's complete start
instructions from its resolved configuration and the ``backend:``
block; the private helpers convert the mounts, environment,
resource limits and published port.
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
    mount mode outside ro/rw, mounts without a config_dir, or an
    expose_host_port of true (no allocator exists); a name container_name
    rejects propagates unchanged. The backend-named values come from cfg,
    never resolved.values: the backend: block is not a resolver layer,
    so the values dict always carries the built-in there.
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
        env=_env_map(resolved),
        devices=_devices(resolved),
        labels=managed_labels(cfg.label_namespace, tool),
        network=cfg.network,
        mounts=_mount_specs(resolved, config_dir),
        cpus=_cpus(resolved),
        memory=_memory(resolved),
        shm_size=_shm_size(resolved),
        published_port=_published_port(resolved),
    )


def _mount_specs(
    resolved: ResolvedTool, config_dir: Path | None
) -> tuple[MountSpec, ...]:
    """One MountSpec per authored entry, in declaration order.

    Raises:
        ValueError: an unparseable entry, a mode outside ro/rw, or
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


def _env_map(resolved: ResolvedTool) -> dict[str, str]:
    """The authored env as str -> str.

    Values are coerced with str(): the config types the dict as
    dict[str, Any], and a container cannot read a non-string value.

    Raises:
        TypeError: env is not a mapping.
    """
    raw = resolved.values["env"]
    if not isinstance(raw, dict):
        raise TypeError(
            f"env for tool {resolved.name!r} must be a mapping, "
            f"got {type(raw).__name__}"
        )
    return {key: str(value) for key, value in raw.items()}


def _devices(resolved: ResolvedTool) -> tuple[int, ...]:
    """The authored GPU indices as a tuple, in authored order:
    the order is not sorted away, because it is a real allocation.

    Raises:
        TypeError: devices is not a list of ints.
    """
    tool = resolved.name
    raw = resolved.values["devices"]
    if not isinstance(raw, list):
        raise TypeError(
            f"devices for tool {tool!r} must be a list of int, got {type(raw).__name__}"
        )
    for device in raw:
        if not isinstance(device, int):
            raise TypeError(
                f"devices for tool {tool!r} must be a list of int, "
                f"got {type(device).__name__} entry"
            )
    return tuple(raw)


def _cpus(resolved: ResolvedTool) -> float | None:
    """The authored CPU limit, verbatim; null leaves it unlimited.

    Raises:
        TypeError: cpus is neither a number nor null.
    """
    raw = resolved.values["cpus"]
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return raw
    raise TypeError(
        f"cpus for tool {resolved.name!r} must be a number or null, "
        f"got {type(raw).__name__}"
    )


def _memory(resolved: ResolvedTool) -> str | None:
    """The authored memory limit, verbatim: the size string
    is parsed by the backend SDK, not here; null leaves it unlimited.

    Raises:
        TypeError: memory is neither a string nor null.
    """
    raw = resolved.values["memory"]
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    raise TypeError(
        f"memory for tool {resolved.name!r} must be a string or null, "
        f"got {type(raw).__name__}"
    )


def _shm_size(resolved: ResolvedTool) -> str:
    """The shared-memory size, always set: the config field
    is non-optional with a built-in default, so a None reaching the spec
    would read as a legitimate "unset".

    Raises:
        TypeError: shm_size is not a string.
    """
    raw = resolved.values["shm_size"]
    if isinstance(raw, str):
        return raw
    raise TypeError(
        f"shm_size for tool {resolved.name!r} must be a string, "
        f"got {type(raw).__name__}"
    )


def _published_port(resolved: ResolvedTool) -> int | None:
    """The host port from expose_host_port: false and null
    publish nothing (an authored null takes the benign default), an int
    publishes exactly that port, never the container port.

    Raises:
        ValueError: the value is True — the schema promises
            auto-allocation from backend.port_range, but no such
            allocator exists.
    """
    raw = resolved.values["expose_host_port"]
    # bool before int: True == 1 and isinstance(True, int), so a naive
    # int check would publish port 1 (the C530/C531 precedent).
    if isinstance(raw, bool):
        if raw:
            raise ValueError(
                f"expose_host_port for tool {resolved.name!r} is true, "
                "which promises auto-allocation from backend.port_range; "
                "no allocator exists, so write an explicit port instead"
            )
        return None
    if isinstance(raw, int):
        return raw
    return None

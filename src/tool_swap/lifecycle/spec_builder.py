"""The config -> ContainerSpec builder (m2b plan §3, behaviour 1).

Core assembly only; mounts, env, devices, cpus, memory, shm_size and
published_port belong to behaviours 2 and 3 and keep their
ContainerSpec defaults here.
"""

from __future__ import annotations

from tool_swap.backend.base import ContainerSpec
from tool_swap.backend.labels import container_name, managed_labels
from tool_swap.config.resolver import ResolvedTool
from tool_swap.config.schema import BackendConfig


def build_container_spec(
    resolved: ResolvedTool, cfg: BackendConfig, image: str
) -> ContainerSpec:
    """Assemble the core ContainerSpec from both config blocks.

    An empty image or a non-int container_port raises here; a name
    container_name rejects propagates unchanged. The backend-named
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
    )

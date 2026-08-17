"""Built-in defaults for tool-swap configuration.

This module is the single named source of truth for every built-in default
(``BUILT_IN_DEFAULTS``); the configuration resolver may only read built-in
values from this constant.  Values are documented in
``plan/02_CONFIGURATION.md`` §3 (``router:`` / ``backend:`` / ``defaults:``
blocks) and §5 (field reference); ``log_output`` in
``plan/07_CLI_AND_OPS.md`` §2.1.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping

#: The single named source of truth for every built-in default.
#:
#: Flat keys: the 30 tool-level fields (including ``env`` and ``mounts``),
#: the 9 ``router`` fields, and the 8 ``backend`` fields — 47 keys in total.
BUILT_IN_DEFAULTS: Mapping[str, object] = {
    # --- tool-level defaults -------------------------------------------------
    # --- lifecycle / TTL ---
    "ttl": 900,
    "keep_warm": False,
    "autostart": True,
    "evict_cost": 1,
    "max_concurrent": None,
    "restart_backoff": [1, 5, 15, 60],
    "max_consecutive_failures": 3,
    # --- resources ---
    "group": "default",
    "devices": [],
    "cpus": None,
    "memory": None,
    "shm_size": "1g",
    # --- batching ---
    "max_batch_size": 8,
    "max_wait_ms": 20,
    "workers": 1,
    "runtime_server": "bentoml",
    # --- timeouts (seconds) ---
    "start_timeout": 120,
    "ready_timeout": 600,
    "queue_timeout": 300,
    "request_timeout": 300,
    "drain_timeout": 30,
    "stop_timeout": 30,
    "max_queue_depth": 64,
    # --- health probing ---
    "health_path": "/health",
    "ready_path": "/ready",
    "probe_interval": 1.0,
    # --- image ---
    "container_port": 8000,
    "expose_host_port": False,
    # --- environment / storage (the built-in layer contributes none) ---
    "env": {},
    "mounts": [],
    # --- router --------------------------------------------------------------
    "host": "0.0.0.0",
    "port": 8600,
    "log_level": "INFO",
    "log_dir": "./logs",
    "log_json": True,
    "cors_origins": ["*"],
    "auth_token": None,
    "status_page": True,
    "log_output": "router",
    # --- backend -------------------------------------------------------------
    "type": "docker",
    "network": "tool-swap-net",
    "container_prefix": "ms-",
    "label_namespace": "com.tool-swap",
    "gpu_runtime": "nvidia",
    "orphans": "stop",
    "port_range": [7000, 7999],
    "registry_prefix": "tool-swap",
}


def builtin_defaults() -> dict[str, object]:
    """Return a fresh, deep copy of the built-in defaults.

    Every call returns a new mapping with independently copied mutable
    values (``devices``, ``cors_origins``, ``restart_backoff``,
    ``port_range``, ``mounts``, ``env``), so mutating one result can never
    corrupt another result or :data:`BUILT_IN_DEFAULTS` itself.

    Returns:
        A deep copy of :data:`BUILT_IN_DEFAULTS`.
    """
    return copy.deepcopy(dict(BUILT_IN_DEFAULTS))

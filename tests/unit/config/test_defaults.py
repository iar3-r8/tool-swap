"""Tests for M1 behaviour 3 — built-in defaults are a single named source of truth.

See ``plans/m1-configuration.md`` behaviour 3 (lines 80-86).  The authoritative
values are ``plan/02_CONFIGURATION.md`` §3 (``router:`` / ``backend:`` /
``defaults:`` blocks) and §5 (field reference); ``log_output`` is documented
in ``plan/07_CLI_AND_OPS.md`` §2.1.

This file is the RED step: the module under test,
``src/tool_swap/config/defaults.py``, does not exist yet, so this file fails
collection with ``ModuleNotFoundError``.  That is the *right* red reason —
every test body below pins a concrete behaviour the GREEN step must satisfy,
so the assertions (not just the import) are the contract.

Pinned public API (the contract the GREEN step must meet verbatim):

- ``BUILT_IN_DEFAULTS`` — a module-level constant of type
  ``Mapping[str, object]`` (a plain ``dict`` qualifies): the **single named
  source of truth** for every built-in default.  Flat keys: the 28 tool-level
  fields (including ``env``/``mounts``), the 9 ``router`` fields, and the 8
  ``backend`` fields — 47 keys in total, exactly
  ``EXPECTED_RESOLVABLE_FIELDS`` below.
- ``builtin_defaults() -> dict[str, object]`` — returns a **fresh, deeply
  copied** mapping on every call: each call's result is distinct from every
  other call's and from ``BUILT_IN_DEFAULTS`` itself, and mutating any
  mutable value (the ``devices``, ``cors_origins``, ``restart_backoff``,
  ``port_range`` or ``mounts`` lists, or the ``env`` mapping) in one result
  must not affect any other result or the constant.

Two flagged judgment calls in the pinned values (see the RED report):

- ``env`` and ``mounts`` are pinned **empty** at the built-in layer.  The §3
  reference config shows non-empty values, but those are *example user
  config* containing ``${...}`` interpolation references (behaviour 5's
  domain), so they cannot be literal built-ins.
- ``auth_token=None`` follows the behaviour-3 summary (plan line 83);
  02_CONFIGURATION.md §3 shows the interpolation template
  ``${TSWAP_TOKEN:-}`` in the reference config instead.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from tool_swap.config.defaults import (  # noqa: E501
    BUILT_IN_DEFAULTS,
    builtin_defaults,
)

# ---------------------------------------------------------------------------
# Documented values — pinned from plan/02_CONFIGURATION.md (source of truth)
# ---------------------------------------------------------------------------

# §3 ``defaults:`` block (lines 75-115) + §5 field reference.  ``env`` and
# ``mounts`` are pinned empty: the built-in layer contributes nothing, and
# the §3 reference values are an example *user* config with ``${...}``
# interpolation, not a built-in.
_TOOL_DEFAULTS: dict[str, object] = {
    # --- lifecycle / TTL ---
    "ttl": 900,  # §5.3: idle seconds -> stop container
    "keep_warm": False,  # §5.3
    "autostart": True,  # §5.3
    "evict_cost": 1,  # §5.3
    "max_concurrent": None,  # §5.3: "unset" means uncapped
    "restart_backoff": [1, 5, 15, 60],  # §5.3
    "max_consecutive_failures": 3,  # §5.3
    # --- resources ---
    "group": "default",  # §5.4
    "devices": [],  # §5.4: [] = CPU only
    "cpus": None,  # §3: cpus: null
    "memory": None,  # §3: memory: null
    "shm_size": "1g",  # §3
    # --- batching ---
    "max_batch_size": 8,  # §5.5
    "max_wait_ms": 20,  # §5.5
    "workers": 1,  # §5.5
    "runtime_server": "bentoml",  # §5.5 (D14)
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
    # --- image (from §5.2; the tool-level defaults a resolver must supply) ---
    "container_port": 8000,  # §5.2
    "expose_host_port": False,  # §5.2
    # --- environment and storage (built-in layer contributes none) ---
    "env": {},
    "mounts": [],
}

# §3 ``router:`` block (lines 48-56).  ``auth_token=None`` per plan line 83
# (the §3 template ``${TSWAP_TOKEN:-}`` interpolates to unset -> None here).
_ROUTER_DEFAULTS: dict[str, object] = {
    "host": "0.0.0.0",
    "port": 8600,
    "log_level": "INFO",
    "log_dir": "./logs",
    "log_json": True,
    "cors_origins": ["*"],
    "auth_token": None,
    "status_page": True,
    # 07_CLI_AND_OPS.md §2.1: "router" (default) | tool | both | none
    "log_output": "router",
}

# §3 ``backend:`` block (lines 61-70).
_BACKEND_DEFAULTS: dict[str, object] = {
    "type": "docker",
    "network": "tool-swap-net",
    "container_prefix": "ms-",
    "label_namespace": "com.tool-swap",
    "gpu_runtime": "nvidia",
    "orphans": "stop",
    "port_range": [7000, 7999],
    "registry_prefix": "tool-swap",
}

DOCUMENTED_DEFAULTS: dict[str, object] = {
    **_TOOL_DEFAULTS,
    **_ROUTER_DEFAULTS,
    **_BACKEND_DEFAULTS,
}

# The resolvable field names, pinned explicitly (not derived from the value
# table above, to keep the two independent) so the set is a visible,
# reviewable constant in the test.
# Source: plan/02_CONFIGURATION.md §3 and §5.
EXPECTED_RESOLVABLE_FIELDS: frozenset[str] = frozenset(
    {
        # --- tool-level defaults (30, including env and mounts) ---
        "ttl",
        "keep_warm",
        "autostart",
        "evict_cost",
        "max_concurrent",
        "restart_backoff",
        "max_consecutive_failures",
        "group",
        "devices",
        "cpus",
        "memory",
        "shm_size",
        "max_batch_size",
        "max_wait_ms",
        "workers",
        "runtime_server",
        "start_timeout",
        "ready_timeout",
        "queue_timeout",
        "request_timeout",
        "drain_timeout",
        "stop_timeout",
        "max_queue_depth",
        "health_path",
        "ready_path",
        "probe_interval",
        "container_port",
        "expose_host_port",
        # --- environment / storage (2, counted in the 30 above) ---
        "env",
        "mounts",
        # --- router (9) ---
        "host",
        "port",
        "log_level",
        "log_dir",
        "log_json",
        "cors_origins",
        "auth_token",
        "status_page",
        "log_output",
        # --- backend (8) ---
        "type",
        "network",
        "container_prefix",
        "label_namespace",
        "gpu_runtime",
        "orphans",
        "port_range",
        "registry_prefix",
    }
)

# Fields whose built-in value is a list and must be per-instance (plan line 84).
_MUTABLE_LIST_FIELDS = (
    "devices",
    "cors_origins",
    "restart_backoff",
    "port_range",
    "mounts",
)


# ---------------------------------------------------------------------------
# 1. A single named source of truth
# ---------------------------------------------------------------------------


def test_module_pins_a_single_named_source_of_truth() -> None:
    """``BUILT_IN_DEFAULTS`` is the contract name for the source of truth.

    The resolver may only read built-in values from this one module-level
    constant — the name itself is pinned here (plan behaviour 3: "a single
    named source of truth"; repo layout: ``defaults.py  BUILT_IN_DEFAULTS``).
    """
    assert isinstance(BUILT_IN_DEFAULTS, Mapping)
    assert BUILT_IN_DEFAULTS, "built-in defaults must not be empty"


# ---------------------------------------------------------------------------
# 2. Every documented default is present with the documented value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("field", "expected"), sorted(DOCUMENTED_DEFAULTS.items()))
def test_built_in_default_has_documented_value(field: str, expected: object) -> None:
    """Each default documented in 02_CONFIGURATION.md §3/§5 is present.

    Arrangement: the pinned value table from the spec.
    Action: look the field up in ``BUILT_IN_DEFAULTS``.
    Assertion: the value equals the documented one exactly; ``None``
    defaults must *be* ``None`` (the "unset" sentinel), not a stand-in.
    """
    if expected is None:
        assert BUILT_IN_DEFAULTS[field] is None, (
            f"built-in default {field!r} must be the unset sentinel (None)"
        )
    else:
        assert BUILT_IN_DEFAULTS[field] == expected, (
            f"built-in default {field!r} must equal the documented value {expected!r}"
        )


def test_fresh_defaults_copy_matches_the_constant() -> None:
    """``builtin_defaults()`` hands out the same values as the constant.

    The per-call copy is a copy, not a different source: its content must
    equal ``BUILT_IN_DEFAULTS`` exactly.
    """
    assert builtin_defaults() == BUILT_IN_DEFAULTS


# ---------------------------------------------------------------------------
# 3. Mutable defaults are produced per-instance
# ---------------------------------------------------------------------------


def test_builtins_defaults_returns_a_fresh_mapping_per_call() -> None:
    """Contract pin: ``builtin_defaults()`` returns a fresh mapping each call.

    Two calls must return distinct mapping objects with distinct list
    objects — a shared list mutated by one tool's resolution corrupting
    another is the classic bug this behaviour calls out by name.
    """
    first = builtin_defaults()
    second = builtin_defaults()
    assert first is not second, "each call must return a new mapping object"
    assert first["devices"] is not second["devices"], (
        "the per-call copy must deep-copy mutable values, not share them"
    )


def test_mutating_one_tools_devices_does_not_corrupt_another() -> None:
    """Dedicated test from plan line 84: resolve two tools, mutate one's devices.

    Arrangement: two per-tool resolutions (two ``builtin_defaults()`` calls).
    Action: append GPU index 0 to the first tool's ``devices``.
    Assertion: the second tool still sees the documented default ``[]``, and
    the source-of-truth constant itself is untouched.
    """
    tool_a = builtin_defaults()
    tool_b = builtin_defaults()
    tool_a["devices"].append(0)
    assert tool_a["devices"] == [0]
    assert tool_b["devices"] == []
    assert BUILT_IN_DEFAULTS["devices"] == []


@pytest.mark.parametrize("field", _MUTABLE_LIST_FIELDS)
def test_mutating_a_mutable_list_default_is_per_instance(field: str) -> None:
    """Every documented mutable list default is isolated per instance.

    Arrangement: two fresh resolutions.
    Action: append a sentinel to the first copy's list.
    Assertion: the sentinel appears in neither the second copy nor the
    source-of-truth constant.
    """
    first = builtin_defaults()
    second = builtin_defaults()
    first[field].append("TSWAP-TEST-SENTINEL")
    assert "TSWAP-TEST-SENTINEL" not in second[field]
    assert list(second[field]) == list(DOCUMENTED_DEFAULTS[field])
    assert list(BUILT_IN_DEFAULTS[field]) == list(DOCUMENTED_DEFAULTS[field])


def test_mutating_the_env_mapping_is_per_instance() -> None:
    """The ``env`` mapping (a dict default) is isolated per instance.

    Arrangement: two fresh resolutions.
    Action: inject a key into the first copy's ``env``.
    Assertion: the injected key appears in neither the second copy nor the
    source-of-truth constant.
    """
    first = builtin_defaults()
    second = builtin_defaults()
    first["env"]["INJECTED_BY_TEST"] = "must-not-escape"
    assert "INJECTED_BY_TEST" not in second["env"]
    assert dict(second["env"]) == {}
    assert dict(BUILT_IN_DEFAULTS["env"]) == {}


# ---------------------------------------------------------------------------
# 4. The built-in set is exhaustive over the resolvable field names
# ---------------------------------------------------------------------------


def test_built_in_default_key_set_is_exhaustive_over_resolvable_fields() -> None:
    """Adding a schema field without a default must fail a test, not silently
    resolve to ``None`` (plan line 85).

    The expected set is pinned explicitly as ``EXPECTED_RESOLVABLE_FIELDS``
    above, from 02_CONFIGURATION.md §3/§5.  Set equality checks both
    directions: a missing default fails, and an undocumented extra default
    fails (keeping the constant and the schema field list in lockstep once
    behaviour 4 lands).
    """
    assert set(BUILT_IN_DEFAULTS) == set(EXPECTED_RESOLVABLE_FIELDS)

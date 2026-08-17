"""Tests for M1 behaviour 4 — the Pydantic config schema and the
``ValidationError`` → ``Diagnostic`` translation.

See ``plans/m1-configuration.md`` behaviour 4 (lines 88-105).  The
authoritative config spec is ``plan/02_CONFIGURATION.md`` §3 (the full
reference config, reproduced below as a fixture with ``${VAR}``
interpolation stripped to literal values — interpolation is behaviour 5
and must not be needed here) and §5 (field reference).

This file is the RED step: the module under test,
``src/tool_swap/config/schema.py``, does not exist yet, so this file
fails collection with ``ModuleNotFoundError``.  That is the *right* red
reason — every test body below pins a concrete behaviour the GREEN step
must satisfy, so the assertions (not just the import) are the contract.

Pinned public API (the contract the GREEN step must meet verbatim):

- Pydantic v2 models, ALL with ``model_config = ConfigDict(extra="forbid")``:
  ``RouterConfig``, ``BackendConfig``, ``DefaultsConfig``, ``GroupConfig``,
  ``ToolConfig``, ``ToolYamlConfig``, ``RootConfig`` (names pinned by plan
  line 92).
- ``validate_root(data: dict) -> list[Diagnostic]`` — takes an
  already-parsed YAML dict and returns the list of ``Diagnostic`s (empty
  for a valid config).  The schema layer raises nothing to the caller;
  ``pydantic.ValidationError`` is translated into ``Diagnostic`s here and
  Pydantic's raw error text (``"Input should be ..."``) never reaches the
  user.

Pinned diagnostic codes and message substrings:

- ``TSWAP-C001`` for ``version: 2`` — message contains
  ``"config version 2 is not supported by tool-swap 0.1.0; this version
  understands version 1"`` (plan line 94, exact wording).
- ``TSWAP-C101`` for every unknown key — message names the key and its
  containing path, e.g. ``"unknown key 'batch_size' in
  tools.cxr_to_embedding — did you mean 'max_batch_size'?"`` (plan line
  95); when no field is within the edit-distance threshold the message
  omits ``"did you mean"`` and instead lists the valid keys with
  ``"valid keys are"`` (plan line 96).  ``location.yaml_path`` includes
  the offending key, e.g. ``"tools.cxr_to_embedding.batch_size"`` (the
  diagnostic-model example at plan line 29 shows the offending field in
  the path).
- A ``TSWAP-C1xx`` type error (schema-shape block per the plan's code
  table) for ``devices: 3`` whose message cites the R8 flaw (plan line
  97): ``"is a list of GPU indices, not a count"``,
  ``"devices: [3]"`` and ``"devices: [0,1,2]"``.

Flagged judgment calls (see the RED report):

- ``version`` is optional-defaulting: the five-line minimal config
  (plan behaviour 23, lines 375-380) omits it and must validate clean,
  so the schema may not make it required.
- ``GroupConfig`` fields are pinned to the §3 groups block
  (``max_resident``, ``eviction``, ``devices``) — in particular NO
  ``ttl`` — which is what lets the "suggestion runs against the correct
  model for the location" edge case (plan line 99) be asserted by
  absence of a tool-field suggestion inside ``groups:``.
- The ``devices: 3`` code is pinned only to the ``TSWAP-C1`` prefix
  (schema-shape block); the plan does not name an exact code for it.
- ``env`` values are free-form strings in these tests; map VALUES
  themselves are not schema-checked (map-valued fields are free-form,
  plan line 103).

Conventions: pytest, AAA pattern, no ``warnings.warn`` (pyproject sets
``filterwarnings = "error"``).
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from tool_swap.config.errors import Diagnostic, Severity
from tool_swap.config.schema import (
    BackendConfig,
    DefaultsConfig,
    GroupConfig,
    RootConfig,
    RouterConfig,
    ToolConfig,
    ToolYamlConfig,
    validate_root,
)

#: The seven models pinned by plan line 92; all must forbid extra keys.
_ALL_MODELS = (
    RouterConfig,
    BackendConfig,
    DefaultsConfig,
    GroupConfig,
    ToolConfig,
    ToolYamlConfig,
    RootConfig,
)


def _diagnostics(data: dict) -> list[Diagnostic]:
    """Arrange/Act helper: run the translation and pin its return type.

    Assertion (shared): the result is a ``list`` of ``Diagnostic``s —
    the schema layer never raises and never returns anything else.
    """
    result = validate_root(data)
    assert isinstance(result, list)
    for diag in result:
        assert isinstance(diag, Diagnostic)
    return result


# ---------------------------------------------------------------------------
# Fixtures — plan/02_CONFIGURATION.md §3, reproduced faithfully
# ---------------------------------------------------------------------------

# §3 "Full global config reference" (lines 38-169) with ``${VAR}``
# interpolation stripped to literal values (behaviour 5's domain).  The
# three stripped references: ``auth_token: ${TSWAP_TOKEN:-}``,
# ``env.HF_TOKEN: ${HF_TOKEN:-}`` and
# ``mounts: [${HF_HOME:-~/.cache/huggingface}:/weights/hf:rw]``.
FULL_REFERENCE_CONFIG: dict = {
    "version": 1,  # §3 line 43: router refuses unknown majors
    "router": {
        "host": "0.0.0.0",
        "port": 8600,
        "log_level": "INFO",
        "log_dir": "./logs",
        "log_json": True,
        "cors_origins": ["*"],
        "auth_token": "sekrit-token",  # was ${TSWAP_TOKEN:-}
        "status_page": True,
    },
    "backend": {
        "type": "docker",
        "network": "tool-swap-net",
        "container_prefix": "ms-",
        "label_namespace": "com.tool-swap",
        "gpu_runtime": "nvidia",
        "orphans": "stop",
        "port_range": [7000, 7999],
        "registry_prefix": "tool-swap",
    },
    "defaults": {
        # --- lifecycle / TTL ---
        "ttl": 900,
        "keep_warm": False,
        "autostart": True,
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
        # --- environment and storage applied to every model ---
        "env": {
            "HF_HOME": "/weights/hf",
            "HF_TOKEN": "hf-secret-token",  # was ${HF_TOKEN:-}
        },
        "mounts": [
            # was ${HF_HOME:-~/.cache/huggingface}:/weights/hf:rw
            "~/.cache/huggingface:/weights/hf:rw",
        ],
    },
    "groups": {
        "default": {
            "max_resident": 4,
            "eviction": "lru",
        },
        "gpu0": {
            "max_resident": 1,
            "devices": [0],
            "eviction": "lru",
        },
        "gpu1": {
            "max_resident": 1,
            "devices": [1],
            "eviction": "lru",
        },
        "cpu": {
            "max_resident": 8,
        },
    },
    "tools": {
        # --- (a) defined in its own directory ---
        "cxr_to_embedding": {
            "path": "./tools/cxr_to_embedding",
            "group": "gpu0",
            "ttl": 600,
        },
        # --- (b) defined fully inline ---
        "text_embedding": {
            "handler": "./tools/text_embedding/handler.py:TextEmbedding",
            "requirements": "./tools/text_embedding/requirements.txt",
            "group": "gpu1",
            "max_batch_size": 32,
            "max_wait_ms": 50,
        },
        # --- (c) exotic build: author supplies the Dockerfile ---
        "totalsegmentator": {
            "build": {
                "context": "./tools/totalsegmentator",
                "dockerfile": "Dockerfile",
            },
            "group": "gpu1",
            "ttl": 300,
            "mounts": [
                "/data/ct:/data/ct:ro",
            ],
        },
        # --- (e) always-warm small CPU model ---
        "text_cleanup": {
            "path": "./tools/text_cleanup",
            "devices": [],
            "keep_warm": True,
            "group": "cpu",
        },
    },
}

# Plan behaviour 23 (lines 375-380): the five-line minimal config.
# ``version`` is deliberately omitted — it must be optional-defaulting.
MINIMAL_CONFIG: dict = {
    "tools": {
        "example_echo": {
            "path": "./tools/example_echo",
        },
    },
}


# ---------------------------------------------------------------------------
# 1. Acceptance: the documented config is accepted with zero errors
# ---------------------------------------------------------------------------


def test_full_reference_config_validates_with_zero_errors() -> None:
    """Plan line 93: the full §3 reference config validates with zero errors.

    Arrangement: the full §3 reference config as a parsed-YAML dict
    (interpolation stripped to literals).
    Action: ``validate_root``.
    Assertion: the result is empty — a list with no diagnostics at all,
    so no hidden warnings either.
    """
    assert _diagnostics(FULL_REFERENCE_CONFIG) == []


def test_minimal_five_line_config_validates_with_zero_errors() -> None:
    """Plan behaviour 23: the five-line config (no ``version``) is clean.

    Arrangement: the five-line minimal config, which omits ``version``
    entirely — pinning that ``version`` is optional-defaulting.
    Action: ``validate_root``.
    Assertion: zero diagnostics.
    """
    assert _diagnostics(MINIMAL_CONFIG) == []


def test_version_one_is_accepted() -> None:
    """Plan line 94: ``version: 1`` is accepted.

    Arrangement: the barest config carrying an explicit ``version: 1``.
    Action: ``validate_root``.
    Assertion: zero diagnostics.
    """
    assert _diagnostics({"version": 1, "tools": {}}) == []


# ---------------------------------------------------------------------------
# 2. Version rejection
# ---------------------------------------------------------------------------


def test_version_two_is_rejected_with_TSWAP_C001() -> None:
    """Plan line 94: ``version: 2`` is rejected naming the supported major.

    Arrangement: a minimal config with ``version: 2``.
    Action: ``validate_root``.
    Assertion: exactly one diagnostic, code ``TSWAP-C001``, severity
    ERROR, message containing the plan's exact wording, non-empty
    remedy, and no Pydantic raw text.
    """
    diags = _diagnostics({"version": 2, "tools": {}})

    c001 = [d for d in diags if d.code == "TSWAP-C001"]
    assert len(c001) == 1, f"expected exactly one C001, got: {diags!r}"
    diag = c001[0]
    assert diag.severity is Severity.ERROR
    assert (
        "config version 2 is not supported by tool-swap 0.1.0; "
        "this version understands version 1"
    ) in diag.message
    assert diag.remedy.strip()
    assert "Input should be" not in diag.message


# ---------------------------------------------------------------------------
# 3. Unknown keys: TSWAP-C101 with and without a suggestion
# ---------------------------------------------------------------------------


def test_unknown_key_names_key_path_and_nearest_alternative() -> None:
    """Plan line 95: unknown key → C101 with the nearest valid alternative.

    Arrangement: ``batch_size`` (a misspelling of ``max_batch_size``)
    inside ``tools.cxr_to_embedding``.
    Action: ``validate_root``.
    Assertion: exactly one C101, severity ERROR, message naming the key,
    its containing path, and the suggestion verbatim (em dash included);
    ``location.yaml_path`` carries the dotted path down to the key;
    remedy non-empty; no Pydantic raw text.
    """
    data = {
        "tools": {
            "cxr_to_embedding": {
                "path": "./tools/cxr_to_embedding",
                "batch_size": 8,
            },
        },
    }
    diags = _diagnostics(data)

    c101 = [d for d in diags if d.code == "TSWAP-C101"]
    assert len(c101) == 1, f"expected exactly one C101, got: {diags!r}"
    diag = c101[0]
    assert diag.severity is Severity.ERROR
    assert (
        "unknown key 'batch_size' in tools.cxr_to_embedding — "
        "did you mean 'max_batch_size'?"
    ) in diag.message
    assert diag.location.yaml_path == "tools.cxr_to_embedding.batch_size"
    assert diag.remedy.strip()
    assert "Input should be" not in diag.message


def test_unknown_key_without_close_match_lists_valid_keys() -> None:
    """Plan line 96: no close field → omit "did you mean", list valid keys.

    Arrangement: ``zzzz`` (unrelated to every router field) inside
    ``router:``.
    Action: ``validate_root``.
    Assertion: exactly one C101 naming ``zzzz`` and its path, with
    ``"valid keys are"`` in the message, ``"host"`` (a valid router
    field) listed, and ``"did you mean"`` ABSENT — a confidently wrong
    suggestion is worse than none.
    """
    data = {"router": {"zzzz": 1}}
    diags = _diagnostics(data)

    c101 = [d for d in diags if d.code == "TSWAP-C101"]
    assert len(c101) == 1, f"expected exactly one C101, got: {diags!r}"
    diag = c101[0]
    assert diag.severity is Severity.ERROR
    assert "'zzzz'" in diag.message
    assert "router" in diag.message
    assert "valid keys are" in diag.message
    assert "host" in diag.message
    assert "did you mean" not in diag.message
    assert diag.remedy.strip()


def test_all_unknown_keys_in_one_file_are_reported_in_a_single_run() -> None:
    """Plan line 101: ALL unknown keys are reported in one run.

    Arrangement: three distinct unknown keys in three different blocks
    (``router``, ``defaults``, ``tools.t1``), each deliberately far from
    any valid field name of its block.
    Action: ``validate_root`` (a single call).
    Assertion: exactly three C101 diagnostics — one per key — and each
    key name appears in a message.  A ``tswap validate`` that reveals
    one typo per invocation is a bad tool.
    """
    data = {
        "router": {"bogus_key": 1},
        "defaults": {"another_bad": 2},
        "tools": {
            "t1": {
                "path": "./tools/t1",
                "yet_more": 3,
            },
        },
    }
    diags = _diagnostics(data)

    c101 = [d for d in diags if d.code == "TSWAP-C101"]
    assert len(c101) == 3, f"expected three C101s, got: {diags!r}"
    messages = " | ".join(d.message for d in c101)
    assert "'bogus_key'" in messages
    assert "'another_bad'" in messages
    assert "'yet_more'" in messages


# ---------------------------------------------------------------------------
# 4. The suggestion runs against the correct model for the location
# ---------------------------------------------------------------------------


def test_suggestion_inside_a_tool_suggests_tool_fields() -> None:
    """Plan line 99 (first half): tool location → tool fields.

    Arrangement: ``titl`` (a misspelling of the tool field ``ttl``)
    inside a ``tools:`` entry.
    Action: ``validate_root``.
    Assertion: the single C101 suggests ``'ttl'`` — a tool field.
    """
    data = {
        "tools": {
            "t1": {
                "path": "./tools/t1",
                "titl": 600,
            },
        },
    }
    diags = _diagnostics(data)

    c101 = [d for d in diags if d.code == "TSWAP-C101"]
    assert len(c101) == 1, f"expected exactly one C101, got: {diags!r}"
    assert "did you mean 'ttl'" in c101[0].message


def test_suggestion_inside_groups_suggests_group_fields() -> None:
    """Plan line 99 (second half): group location → group fields.

    Arrangement: the SAME misspelling ``titl`` inside a ``groups:``
    entry.  Group fields (``max_resident``, ``eviction``, ``devices``
    per §3) do not include ``ttl``, so a tool-field-aware implementation
    would wrongly suggest ``'ttl'`` here.
    Action: ``validate_root``.
    Assertion: the single C101 lists the group's valid keys (``"valid
    keys are"`` with the group field ``max_resident`` listed) and does
    NOT suggest the tool field ``'ttl'``.
    """
    data = {"groups": {"g1": {"titl": 600}}}
    diags = _diagnostics(data)

    c101 = [d for d in diags if d.code == "TSWAP-C101"]
    assert len(c101) == 1, f"expected exactly one C101, got: {diags!r}"
    diag = c101[0]
    assert "did you mean 'ttl'" not in diag.message
    assert "valid keys are" in diag.message
    assert "max_resident" in diag.message


# ---------------------------------------------------------------------------
# 5. Bespoke type error for devices-as-count (the R8 flaw)
# ---------------------------------------------------------------------------


def test_devices_as_count_gets_bespoke_message_not_pydantic_default() -> None:
    """Plan line 97: ``devices: 3`` is a type error citing the R8 flaw.

    Arrangement: ``devices: 3`` (a count, not a list) in ``defaults:``.
    Action: ``validate_root``.
    Assertion: exactly one schema-shape error (``TSWAP-C1xx`` prefix per
    the plan's code table) whose message is the bespoke one — it cites
    the R8 flaw and shows both corrected forms — and Pydantic's raw
    error text does not reach the user.
    """
    data = {"defaults": {"devices": 3}}
    diags = _diagnostics(data)

    type_errors = [
        d for d in diags if d.code.startswith("TSWAP-C1") and d.severity is Severity.ERROR
    ]
    assert len(type_errors) == 1, f"expected exactly one C1xx error, got: {diags!r}"
    diag = type_errors[0]
    assert "is a list of GPU indices, not a count" in diag.message
    assert "devices: [3]" in diag.message
    assert "devices: [0,1,2]" in diag.message
    assert diag.remedy.strip()
    assert "Input should be" not in diag.message


# ---------------------------------------------------------------------------
# 6. Legitimate free-form and empty shapes
# ---------------------------------------------------------------------------


def test_empty_tools_block_is_valid() -> None:
    """Plan line 102: ``tools: {}`` is valid — a router with no tools is
    a legitimate boot state.

    Arrangement: a config whose only block is an empty ``tools:`` map.
    Action: ``validate_root``.
    Assertion: zero diagnostics.
    """
    assert _diagnostics({"tools": {}}) == []


def test_extra_keys_inside_env_are_legal() -> None:
    """Plan line 103: ``env`` is a free-form map; ``extra="forbid"`` must
    not apply to map-valued fields.

    Arrangement: a tool with ``env: {ANYTHING: "x"}`` — a key no schema
    could know about, which is the whole point of an environment map.
    Action: ``validate_root``.
    Assertion: zero diagnostics.
    """
    data = {
        "tools": {
            "t1": {
                "path": "./tools/t1",
                "env": {"ANYTHING": "x"},
            },
        },
    }
    assert _diagnostics(data) == []


# ---------------------------------------------------------------------------
# 7. Model-level pin: every documented model forbids extra keys
# ---------------------------------------------------------------------------


def test_all_documented_models_are_pydantic_models_forbidding_extra_keys() -> None:
    """Plan line 92: all seven models exist and forbid extra keys.

    Arrangement: the seven model classes pinned by name in the plan.
    Action: inspect each class.
    Assertion: each is a Pydantic v2 ``BaseModel`` subclass whose
    ``model_config`` sets ``extra="forbid"`` — the declarative form of
    the unknown-key behaviour pinned behaviourally above.
    """
    for model in _ALL_MODELS:
        assert issubclass(model, BaseModel), f"{model.__name__} is not a BaseModel"
        assert model.model_config.get("extra") == "forbid", (
            f"{model.__name__} must set model_config extra='forbid'"
        )

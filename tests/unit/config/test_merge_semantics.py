"""Tests for M1 behaviour 10 — merge semantics of the resolver.

See ``plans/m1-configuration.md`` §1, behaviour 10 (lines 179-196) and
``plan/02_CONFIGURATION.md`` §5.6.  This file covers the merge rules that
"which lists merge" makes unpredictable if guessed per field:

- **``env`` is merged key-by-key**, the higher layer winning per key
  (plan line 184).  Per-key origins use the dotted path convention
  ``env.<KEY>``.
- **``mounts`` is concatenated, not replaced**, in the order
  **built-in → defaults → tool.yaml → inline** (most specific last)
  (plan line 185).  Per-entry origins use the index convention
  ``mounts[i]``.  A duplicate *container* path across layers emits
  ``TSWAP-C503`` WARNING naming both host sources; the duplicate itself
  is preserved (Docker's last-wins applies at runtime).  Note the
  built-in layer contributes an empty ``mounts`` list by default, so the
  observable order is defaults → tool.yaml → inline.
- **Other lists (``devices``, ``cors_origins``, ``restart_backoff``) are
  replaced wholesale**, not concatenated (plan line 186).
- **Nested blocks in ``tool.yaml`` flatten onto the tool's fields**
  (plan line 187).  The pinned flattening table (asserted field by field,
  in both directions):

    =====================  ================
    tool.yaml nested key   flat field
    =====================  ================
    ``batching.max_batch_size``   ``max_batch_size``
    ``resources.group``           ``group``
    ``lifecycle.ttl``             ``ttl``
    ``lifecycle.ready_timeout``   ``ready_timeout``
    =====================  ================

  A nested key inside a known block that maps to no flat field is
  ``TSWAP-C106`` (schema-shape block, next free code after ``C105``),
  an ERROR naming the key — "a ``tool.yaml`` key that maps to nothing
  fails a test" (plan line 187).

This file is the RED step: the module under test,
``src/tool_swap/config/resolver.py``, does not exist yet, so the file
fails collection with ``ModuleNotFoundError``.  That is the *right* red
reason — every test body below pins a concrete behaviour the GREEN step
must satisfy.

Pinned public API (in addition to what ``test_resolver.py`` pins for
``resolve_tool`` / ``ResolvedTool``):

- ``TSWAP-C503`` — WARNING — the same container path mounted in more
  than one layer; the message contains **both** host sources (e.g.
  ``"/hostA"`` and ``"/hostB"``).  Exactly one such diagnostic is
  emitted per duplicated container path.
- ``TSWAP-C106`` — ERROR — a nested key inside a known ``tool.yaml``
  block (``batching``/``resources``/``lifecycle``) that maps to no flat
  field; the message contains the offending key name.

Conventions: pytest, AAA pattern, no ``warnings.warn`` (pyproject sets
``filterwarnings = "error"``).
"""

from __future__ import annotations

import pytest

from tool_swap.config.errors import Severity
from tool_swap.config.origin import OriginLevel
from tool_swap.config.resolver import resolve_tool

#: The pinned flattening table: tool.yaml nested key -> flat field.
#: Asserted field by field in both directions (``test_flattening_table_is
#: one_nested_key_per_flat_field``): each nested key maps to exactly one
#: flat field, and no flat field is the target of two nested keys.
FLATTENING_TABLE: dict[tuple[str, str], str] = {
    ("batching", "max_batch_size"): "max_batch_size",
    ("resources", "group"): "group",
    ("lifecycle", "ttl"): "ttl",
    ("lifecycle", "ready_timeout"): "ready_timeout",
}

# ---------------------------------------------------------------------------
# env: merged key-by-key, higher layer wins per key
# ---------------------------------------------------------------------------


def test_env_merged_key_by_key_higher_layer_wins_per_key() -> None:
    """The plan's own example: per-key winner and per-key origins."""
    # Act
    result = resolve_tool(
        "t",
        inline={"env": {"HF_HOME": "/b"}},
        defaults={"env": {"HF_HOME": "/a", "HF_TOKEN": "x"}},
    )
    # Assert
    assert result.values["env"] == {"HF_HOME": "/b", "HF_TOKEN": "x"}
    assert result.origins.winning("env.HF_HOME").level is OriginLevel.INLINE
    assert result.origins.winning("env.HF_TOKEN").level is OriginLevel.DEFAULTS
    assert result.diagnostics == []


def test_env_merge_tool_yaml_layer_wins_per_key() -> None:
    """A tool.yaml env key beats a defaults env key; inline beats both."""
    # Act
    result = resolve_tool(
        "t",
        inline={"env": {"A": "inline"}},
        tool_yaml={"env": {"A": "tool", "B": "tool"}},
        defaults={"env": {"A": "defaults", "C": "defaults"}},
    )
    # Assert
    assert result.values["env"] == {"A": "inline", "B": "tool", "C": "defaults"}
    assert result.origins.winning("env.A").level is OriginLevel.INLINE
    assert result.origins.winning("env.B").level is OriginLevel.TOOL_YAML
    assert result.origins.winning("env.C").level is OriginLevel.DEFAULTS


# ---------------------------------------------------------------------------
# mounts: concatenated built-in -> defaults -> tool.yaml -> inline
# ---------------------------------------------------------------------------


def test_mounts_concatenated_in_layer_order_most_specific_last() -> None:
    """Mounts from each layer appear in built-in -> defaults -> tool.yaml
    -> inline order, with per-entry origins at ``mounts[i]``."""
    # Act
    result = resolve_tool(
        "t",
        inline={"mounts": ["/h3:/data/c:ro"]},
        tool_yaml={"mounts": ["/h2:/data/b:rw"]},
        defaults={"mounts": ["/h1:/data/a:ro"]},
    )
    # Assert — exact list order across layers.
    assert result.values["mounts"] == [
        "/h1:/data/a:ro",
        "/h2:/data/b:rw",
        "/h3:/data/c:ro",
    ]
    # Per-entry origins of the contributing layer.
    assert result.origins.winning("mounts[0]").level is OriginLevel.DEFAULTS
    assert result.origins.winning("mounts[1]").level is OriginLevel.TOOL_YAML
    assert result.origins.winning("mounts[2]").level is OriginLevel.INLINE
    assert result.diagnostics == []


def test_mounts_empty_in_some_layers_concatenates_rest() -> None:
    """A layer with no mounts contributes nothing; the rest keep order."""
    # Act
    result = resolve_tool(
        "t",
        inline={"mounts": ["/i:/iso:ro"]},
        tool_yaml=None,
        defaults={"mounts": ["/d:/data:ro"]},
    )
    # Assert
    assert result.values["mounts"] == ["/d:/data:ro", "/i:/iso:ro"]
    assert result.origins.winning("mounts[0]").level is OriginLevel.DEFAULTS
    assert result.origins.winning("mounts[1]").level is OriginLevel.INLINE


def test_duplicate_container_path_across_layers_is_c503_warning() -> None:
    """``TSWAP-C503`` WARNING names both host sources; duplicates preserved."""
    # Act
    result = resolve_tool(
        "t",
        inline={"mounts": ["/hostB:/data:ro"]},
        defaults={"mounts": ["/hostA:/data:ro"]},
    )
    # Assert — both entries preserved (Docker last-wins applies at runtime).
    assert result.values["mounts"] == ["/hostA:/data:ro", "/hostB:/data:ro"]
    # Exactly one C503, WARNING, naming both host sources.
    c503 = [d for d in result.diagnostics if d.code == "TSWAP-C503"]
    assert len(c503) == 1
    assert c503[0].severity is Severity.WARNING
    assert "/hostA" in c503[0].message
    assert "/hostB" in c503[0].message
    # Nothing else is emitted.
    assert len(result.diagnostics) == 1


def test_distinct_container_paths_produce_no_c503() -> None:
    """Mounting different container paths across layers is clean."""
    # Act
    result = resolve_tool(
        "t",
        inline={"mounts": ["/h:/x:ro"]},
        defaults={"mounts": ["/h2:/y:ro"]},
    )
    # Assert
    assert result.values["mounts"] == ["/h2:/y:ro", "/h:/x:ro"]
    assert result.diagnostics == []


# ---------------------------------------------------------------------------
# other lists: replaced wholesale, not concatenated
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "defaults_value", "higher_value"),
    [
        pytest.param("devices", [0], [1], id="devices"),
        pytest.param(
            "cors_origins", ["https://a.example"], ["https://b.example"],
            id="cors_origins",
        ),
        pytest.param("restart_backoff", [2, 3], [1], id="restart_backoff"),
    ],
)
def test_lists_replaced_wholesale_not_concatenated(
    field: str, defaults_value: list, higher_value: list
) -> None:
    """The higher layer's list fully replaces the lower layer's list."""
    # Act
    result = resolve_tool("t", inline={field: higher_value},
                          defaults={field: defaults_value})
    # Assert — replacement, not concatenation.
    assert result.values[field] == higher_value
    assert result.values[field] != defaults_value + higher_value
    assert result.origins.winning(field).level is OriginLevel.INLINE
    assert result.diagnostics == []


def test_devices_tool_yaml_replaces_defaults_wholesale() -> None:
    """Replacement also holds between the tool.yaml and defaults layers."""
    # Act
    result = resolve_tool("t", inline={}, tool_yaml={"devices": [3]},
                          defaults={"devices": [0, 1]})
    # Assert
    assert result.values["devices"] == [3]
    assert result.origins.winning("devices").level is OriginLevel.TOOL_YAML


# ---------------------------------------------------------------------------
# tool.yaml nested blocks flatten onto flat fields
# ---------------------------------------------------------------------------


def test_flattening_table_is_one_nested_key_per_flat_field() -> None:
    """The table is a bijection in both directions (structural pin)."""
    # Assert — forward: every nested key maps to exactly one flat field.
    for _nested_key, flat_field in FLATTENING_TABLE.items():
        assert flat_field
    # Assert — reverse: no flat field is the target of two nested keys.
    targets = list(FLATTENING_TABLE.values())
    assert len(targets) == len(set(targets))


def test_flattening_maps_each_nested_key_to_its_flat_field() -> None:
    """Each pinned nested key lands on its flat field with TOOL_YAML origin."""
    # Arrange — one nested key per block, all four blocks at once.
    tool_yaml = {
        "batching": {"max_batch_size": 16},
        "resources": {"group": "gpu0"},
        "lifecycle": {"ttl": 42, "ready_timeout": 321},
    }
    # Act
    result = resolve_tool("t", inline={}, tool_yaml=tool_yaml)
    # Assert — field by field.
    for (block, key), flat_field in FLATTENING_TABLE.items():
        value = tool_yaml[block][key]
        assert result.values[flat_field] == value, flat_field
        assert result.origins.winning(flat_field).level is OriginLevel.TOOL_YAML, (
            flat_field
        )
    assert result.diagnostics == []


def test_flattened_tool_yaml_loses_to_inline() -> None:
    """A flattened tool.yaml value sits below inline in precedence."""
    # Act
    result = resolve_tool(
        "t",
        inline={"max_batch_size": 32},
        tool_yaml={"batching": {"max_batch_size": 16}},
    )
    # Assert
    assert result.values["max_batch_size"] == 32
    assert result.origins.winning("max_batch_size").level is OriginLevel.INLINE


def test_unmapped_nested_key_is_c106_error_naming_the_key() -> None:
    """A nested key that maps to no flat field is ``TSWAP-C106``."""
    # Act
    result = resolve_tool(
        "t",
        inline={},
        tool_yaml={"batching": {"max_batch_size": 16, "zz_not_a_key": 3}},
    )
    # Assert — the mapped key still resolves.
    assert result.values["max_batch_size"] == 16
    c106 = [d for d in result.diagnostics if d.code == "TSWAP-C106"]
    assert len(c106) == 1
    assert c106[0].severity is Severity.ERROR
    assert "zz_not_a_key" in c106[0].message

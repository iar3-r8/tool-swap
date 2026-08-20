"""
Behaviour 22 (RED) — the ``tswap config show`` CLI command.

Executable form of ``plans/m1-configuration.md`` behaviour 22 and its
"Confirmed contract details (2026-08-20)" block (items 1-15). The command
does not exist yet: ``src/tool_swap/cli/main.py`` registers only ``version``
and ``validate``. Every test in this file is expected to RED — typer answers
the unknown ``config`` sub-group with a usage error (exit 2) and prints
``No such command 'config'.`` on stderr, so ``config show --help`` also
exits 2 and nothing produces the pinned resolved-config output. Nothing here
should pass against the current tree.

Contract pinned by these tests (plan items in parentheses):

- the rendered line format: one value per line, a fixed origin column of 40,
  a single space before the ``#`` annotation (item 1);
- the origin annotation vocabulary, per winning level, with the honest
  line-number availability (item 1): ``<file>:<line> (inline)`` with a real
  line, ``<tool.yaml path> (tool.yaml)`` with NO line number,
  ``<file>:<line> (defaults)`` / ``<file>:<line> (group '<n>')``, and
  ``built-in default``;
- ``--verbose`` shadowed values served by ``OriginMap.shadowed`` plus the
  renderer-synthesised ``# overrides <v> from built-in default`` tail, and the
  A25 tool.yaml-layer shadow form ``# overrides the value in <path> (tool.yaml)``
  (item 2);
- the fixed field order (``BUILT_IN_DEFAULTS`` declaration order) and the
  per-tool section order: router block, backend block, then the tool header,
  description, the 30 resolved fields, and the carriers (item 3);
- the router/backend blocks shown ONCE as top-level raw blocks, never per
  tool (item 4, assumption A24);
- ``env`` per-key origins, ``mounts`` per-entry origins with the defaulted
  ``:ro`` made visible (items 5, 6);
- ``--json``: the ``{config, router, backend, tools}`` envelope, a structured
  ``origin`` of ``{level, source, line}``, an always-present ``shadowed`` key,
  byte-identity with/without ``--verbose`` (item 8);
- the secret-redaction rule (item 9, assumption A12): ``auth_token`` and any
  env key matching ``TOKEN|SECRET|KEY|PASSWORD`` case-insensitively are
  redacted to ``***`` with the origin unchanged, ``--show-secrets`` opts out
  with no banner;
- the exit-code table (item 12): warnings exit 0, errors exit 1 with the
  resolved output still on stdout, an unknown tool exits 1 via the shared
  ``_unknown_tool`` line, a missing file exits 2 with ``TSWAP-C000``;
- the golden snapshot over ``MINIMAL`` (item 14): the whole stdout,
  character for character — the format's anchor;
- determinism: NO_COLOR=1, and a second invocation byte-identical.

Shipped-code pins verified while writing this file:

- the built-in defaults and their declaration order —
  ``src/tool_swap/config/defaults.py:20`` (``BUILT_IN_DEFAULTS``): 30 tool
  fields + 9 router + 8 backend = 47; ``ttl`` = 900, ``auth_token`` = None,
  ``env`` = ``{}``, ``mounts`` = ``[]``;
- the origin level/suffix vocabulary — ``src/tool_swap/config/origin.py:16``
  (``OriginLevel``) and :32 (``_RENDER_SUFFIX``); the ``built-in default``
  source is origin.py:39;
- the resolver's totality and layering — ``src/tool_swap/config/resolver.py``:
  ``_shadowed`` (:659) excludes the built-in baseline, so the ``900`` tail is
  synthesised by the renderer; ``_resolve_env`` (:784) records per-key
  ``env.<KEY>`` origins with the most-specific layer first; ``_resolve_mounts``
  (:845) concatenates built-in first, inline last, recording ``mounts[i]``;
- the mount parser ``parse_mount`` — ``src/tool_swap/config/validate.py:2486``
  returns a ``ParsedMount`` with ``resolved_host`` / ``mode`` /
  ``mode_defaulted``; a two-part entry defaults ``mode="ro"`` with
  ``mode_defaulted=True``;
- the loader's line map — ``src/tool_swap/config/loader.py:494``
  (``line_for``) resolves dotted paths from the ROOT document only, so a
  ``tool.yaml``-sourced value has no line number;
- missing file: ``TSWAP-C000``; the unknown-tool line reuses behaviour 21's
  ``nearest_alternative`` (``'preidt'`` -> ``'predict'``).

Fixture strategy (item 14): ``tmp_path`` plus a module-level ``_write`` helper,
no committed fixture files — the ``test_validate_cli.py`` shipped pattern,
copied (not imported) because leaf test dirs have no ``__init__.py``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tool_swap.__main__ import app
from tool_swap.config.validate import (
    BUILTIN_RULES,
    RULES,
    register,
    registered_rule_ids,
    unregister_all,
)

# ---------------------------------------------------------------------------
# Pinned strings (plan items 1, 2, 6, 9, 12; copied as local constants, not
# imported from the not-yet-existent cli/config_show.py, so each test fails
# individually rather than the module erroring at collection)
# ---------------------------------------------------------------------------

_BUILTIN_ANNOTATION = "built-in default"
_REDACTED = "***"
_MODE_DEFAULTED_NOTE = "mode defaulted to ro"
# The shared ``_unknown_tool`` line, identical to behaviour 21's pin —
# ``'preidt'`` is distance 2 over length 7 from ``'predict'`` (2 <= 0.3*7).
_UNKNOWN_TOOL_LINE = "error: unknown tool 'preidt'; did you mean 'predict'?"

# The origin column the renderer aligns annotations to (plan item 1).
_ORIGIN_COLUMN = 40

# Each flag must appear on its own help line followed by a non-trivial
# description (>= 10 characters after the flag) — behaviour 21's item-12
# precedent. config show offers exactly these five flags plus the TOOL arg
# (no --all, no --strict, no --allow-missing-descriptions; plan item 13).
_FLAG_HELP_RES = {
    "--config": re.compile(r"(?m)^.*--config\b.{10,}$"),
    "--env-file": re.compile(r"(?m)^.*--env-file\b.{10,}$"),
    "--verbose": re.compile(r"(?m)^.*--verbose\b.{10,}$"),
    "--json": re.compile(r"(?m)^.*--json\b.{10,}$"),
    "--show-secrets": re.compile(r"(?m)^.*--show-secrets\b.{10,}$"),
}
_TOOL_ARG_RE = re.compile(r"(?m)^.*\bTOOL\b.{10,}$")


# ---------------------------------------------------------------------------
# Runner / env (verbatim copy of tests/unit/test_cli.py's shipped pattern —
# plan item 14; copied, not imported, because leaf test dirs have no
# __init__.py and cross-directory test imports are unavailable)
# ---------------------------------------------------------------------------


def _make_runner(**overrides) -> CliRunner:
    """Return a CliRunner with NO_COLOR enforced for clean assertions.

    *overrides* may add/replace environment variables on top of the
    defaults (``COLUMNS=80 TERM=linux NO_COLOR=1``).
    """
    env = {**os.environ, "COLUMNS": "80", "TERM": "linux", "NO_COLOR": "1"}
    env.update(overrides)
    return CliRunner(env=env)


@pytest.fixture()
def runner() -> CliRunner:
    """Return a CliRunner with NO_COLOR enforced for clean assertions."""
    return _make_runner()


# ---------------------------------------------------------------------------
# Registry isolation: snapshot/restore the shared rule registry
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_registry():
    """Keep the module-level rule registry state untouched across tests.

    Behaviour 22's command (behaviour 21b's shared ``run_pipeline``) calls
    ``register_builtin_rules()`` (idempotent, object-identity based), so
    invoking the CLI leaves the builtins registered. Snapshot the live
    registry and restore exactly that state after each test.
    """
    snapshot: list = list(RULES)

    def _restore() -> None:
        unregister_all()
        for rule in snapshot:
            register(rule)

    try:
        yield
    finally:
        _restore()


# ---------------------------------------------------------------------------
# Fixtures (plan item 14): tmp_path + a module-level _write helper,
# no committed fixture files — test_validate_cli.py's shipped pattern
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, text: str) -> Path:
    """Write ``text`` (UTF-8) to ``tmp_path/name`` and return the path.

    Parent directories are created as needed (``t/tool.yaml`` fixtures).
    """
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


#: The golden snapshot target: one tool, no tool.yaml, nothing else set.
#: Every one of the 30 resolved fields falls to the built-in layer, so the
#: output exercises the column, the field order, and the "all 30 present"
#: promise at once.
MINIMAL = (
    "tools:\n"
    "  echo:\n"
    "    image: registry.example.com/echo:1\n"
    "    description: Echoes its input back.\n"
)

#: The ledger's headline ``--verbose`` case: tool.yaml's flattened
#: ``lifecycle.ttl`` (600) beats the ``defaults:`` layer (300), which in turn
#: beats the built-in (900). The winner is a tool.yaml-sourced value (no line
#: number), so the shadow list carries the ``defaults`` loser (300) and the
#: renderer-synthesised built-in tail (900).
SHADOW_TTL = (
    "tools:\n"
    "  t:\n"
    "    image: registry.example.com/t:1\n"
    "    description: A tool whose ttl is shadowed.\n"
    "    path: ./t\n"
    "\n"
    "defaults:\n"
    "  ttl: 300\n"
)
SHADOW_TTL_TOOL_YAML = (
    "lifecycle:\n"
    "  ttl: 600\n"
)

#: The same tool with ``ttl: 600`` written INLINE in tools.yaml — the one
#: level where the ``<file>:<line> (inline)`` form is achievable (the real
#: line number comes from ``line_for("tools.t.ttl")``).
INLINE_TTL = (
    "tools:\n"
    "  t:\n"
    "    image: registry.example.com/t:1\n"
    "    description: A tool with an inline ttl.\n"
    "    ttl: 600\n"
)

#: A ttl supplied only by the ``defaults:`` layer — the ``(defaults)``
#: annotation with a real line number from ``line_for("defaults.ttl")``.
DEFAULTS_TTL = (
    "tools:\n"
    "  t:\n"
    "    image: registry.example.com/t:1\n"
    "    description: A tool with a defaults-layer ttl.\n"
    "\n"
    "defaults:\n"
    "  ttl: 300\n"
)

#: A group with ``devices`` and a tool bound to it — the ``(group 'gpu0')``
#: annotation, proving the ``{**groups[gname], "name": gname}`` injection
#: reaches the display (without it the origin would read
#: ``groups.unnamed.devices``). ``max_resident: 1`` is pinned so the C613
#: under-saturation warning stays silent and the fixture is focused.
GROUP_DEVICES = (
    "groups:\n"
    "  gpu0:\n"
    "    max_resident: 1\n"
    "    devices: [0]\n"
    "\n"
    "tools:\n"
    "  t:\n"
    "    image: registry.example.com/t:1\n"
    "    description: A tool bound to a group.\n"
    "    group: gpu0\n"
)

#: Secret env split across inline and tool.yaml, exercising per-key origins
#: and the redaction rule: ``HF_TOKEN`` and lowercase ``hf_token`` are both
#: redacted (case-insensitivity), ``api_key`` (lowercase) is redacted,
#: ``KEYSTONE_URL`` is redacted (the accepted false positive), and ``HF_HOME``
#: is left untouched.
ENV_SECRET = (
    "tools:\n"
    "  t:\n"
    "    image: registry.example.com/t:1\n"
    "    description: A tool with secret env.\n"
    "    path: ./t\n"
    "    env:\n"
    "      HF_HOME: /weights\n"
    "      HF_TOKEN: secret-token-1\n"
)
ENV_SECRET_TOOL_YAML = (
    "name: t\n"
    "env:\n"
    "  hf_token: t2\n"
    "  KEYSTONE_URL: u\n"
    "  api_key: k\n"
)

#: A router block with ``port`` (shown with its raw value and a ``(router)``
#: annotation) and ``auth_token`` (redacted to ``***``), plus the 7 other
#: router keys at their built-in defaults — and that NO tool section shows
#: ``port`` (A24: the router/backend blocks are top-level, never per tool).
ROUTER_AUTH = (
    "router:\n"
    "  port: 9000\n"
    "  auth_token: s3cr3t\n"
    "\n"
    "tools:\n"
    "  t:\n"
    "    image: registry.example.com/t:1\n"
    "    description: A tool with a router block.\n"
)

#: Mounts at two layers: a ``defaults:`` entry with no mode (defaults to
#: ``ro``, ``mode_defaulted=True``) and an inline entry with an explicit
#: ``:rw``. Exercises concatenation order (built-in/defaults first, inline
#: last), the ``host:container:mode`` form, and the ``mode defaulted to ro``
#: note. The ``/data`` host is absent, so C543 (a WARNING) fires — the config
#: still resolves and exits 0.
MOUNTS = (
    "defaults:\n"
    "  mounts:\n"
    "    - /data:/weights\n"
    "\n"
    "tools:\n"
    "  t:\n"
    "    image: registry.example.com/t:1\n"
    "    description: A tool with mounts.\n"
    "    mounts:\n"
    "      - /cache:/cache:rw\n"
)

#: A ``path:`` tool whose tool.yaml carries a description, a 3-entry
#: ``inputs:`` block and a 1-entry ``params:`` block — the carrier count form
#: (``inputs: 3 entries`` / ``params: 1 entry``) and the absent-carrier
#: (``outputs:`` / ``json_schema:``) prints-nothing rule.
CARRIERS = (
    "tools:\n"
    "  t:\n"
    "    image: registry.example.com/t:1\n"
    "    description: A tool with carriers.\n"
    "    path: ./t\n"
)
CARRIERS_TOOL_YAML = (
    "name: t\n"
    "inputs:\n"
    "  - name: a\n"
    "    type: string\n"
    "    description: First input.\n"
    "  - name: b\n"
    "    type: string\n"
    "    description: Second input.\n"
    "  - name: c\n"
    "    type: string\n"
    "    description: Third input.\n"
    "params:\n"
    "  - name: p\n"
    "    type: string\n"
    "    description: A param.\n"
)

#: Two clean tools — the per-tool view filter (``config show beta`` shows
#: only beta's section) and the unknown-tool candidates (``echo`` /
#: ``predict``) for the nearest-name test.
TWO_TOOLS = (
    "tools:\n"
    "  alpha:\n"
    "    image: registry.example.com/alpha:1\n"
    "    description: A clean tool.\n"
    "  beta:\n"
    "    image: registry.example.com/beta:1\n"
    "    description: A second tool.\n"
)

#: Two tools, one with no image source (``beta`` — TSWAP-C511): the exit-1
#: case where the resolved output is STILL on stdout (both sections) while the
#: diagnostic goes to stderr.
TWO_TOOLS_ERROR = (
    "tools:\n"
    "  alpha:\n"
    "    image: registry.example.com/alpha:1\n"
    "    description: A clean tool.\n"
    "  beta:\n"
    "    description: A tool with no image source at all.\n"
)

#: Only the C601 warning (``keep_warm: true`` + explicit ``ttl``): exit 0 with
#: the resolved config on stdout and the warning on stderr.
WARNING_ONLY = (
    "tools:\n"
    "  a:\n"
    "    image: registry.example.com/a:1\n"
    "    description: A warm tool.\n"
    "    keep_warm: true\n"
    "    ttl: 300\n"
)

#: Tools ``echo`` and ``predict``; invoked as ``config show preidt`` for the
#: shared ``_unknown_tool`` nearest-name line (suggestions ``predict``).
NEAREST_NAME = (
    "tools:\n"
    "  echo:\n"
    "    image: registry.example.com/echo:1\n"
    "    description: Echoes its input back.\n"
    "  predict:\n"
    "    image: registry.example.com/predict:1\n"
    "    description: Runs the prediction handler.\n"
)

#: The A25 gap fixture: an inline ``ttl: 600`` that SHADOWS a tool.yaml
#: ``ttl: 300``. The shadowed tool.yaml layer is rendered WITHOUT its value —
#: the pinned A25 form ``# overrides the value in <path> (tool.yaml)`` — plus
#: the synthesised built-in tail.
A25_INLINE_WINS = (
    "tools:\n"
    "  t:\n"
    "    image: registry.example.com/t:1\n"
    "    description: An inline ttl that shadows tool.yaml.\n"
    "    path: ./t\n"
    "    ttl: 600\n"
)
A25_TOOL_YAML = (
    "lifecycle:\n"
    "  ttl: 300\n"
)


def _invoke(runner: CliRunner, config_path: Path, *args: str) -> object:
    """Invoke ``config show`` with ``--config <path>`` plus *args*."""
    return runner.invoke(
        app, ["config", "show", "--config", str(config_path), *args]
    )


def _line_of(text: str, needle: str) -> int:
    """Return the 1-based line of ``needle`` (an exact line) in ``text``.

    Computed from the fixture text, never hardcoded, so the line-number
    assertions track the fixture if it is edited.
    """
    return text.splitlines().index(needle) + 1


# ---------------------------------------------------------------------------
# Help and absence
# ---------------------------------------------------------------------------


class TestHelp:
    """``tswap config show --help`` lists every flag with a description."""

    def test_config_show_help_exits_zero_and_lists_every_flag(
        self, runner: CliRunner
    ) -> None:
        """Exit 0; each of the five flags and the TOOL argument appear.

        Plan item 13: every surface name must be present with a non-trivial
        one-line description (>= 10 characters after the flag), so asserting
        presence alone cannot pass against empty help strings.
        """
        result = runner.invoke(app, ["config", "show", "--help"])

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        for flag, pattern in _FLAG_HELP_RES.items():
            assert pattern.search(result.stdout), (
                f"Expected '{flag}' with a one-line description in "
                f"'config show --help'. Got:\n{result.stdout}"
            )
        assert _TOOL_ARG_RE.search(result.stdout), (
            "Expected the TOOL positional argument with a description in "
            f"'config show --help'. Got:\n{result.stdout}"
        )

    def test_root_help_lists_config_subcommand(self, runner: CliRunner) -> None:
        """The root ``tswap --help`` names the new ``config`` sub-group.

        Plan item 13: ``main.py``'s hand-maintained command list gains a
        ``config`` line; a list that omits the new group is the rot this
        guards against.
        """
        result = runner.invoke(app, ["--help"])

        assert result.exit_code == 0
        assert re.search(r"(?m)^.*\bconfig\b.{3,}$", result.stdout), (
            "Expected 'config' with a description in the root help. "
            f"Got:\n{result.stdout}"
        )


# ---------------------------------------------------------------------------
# Golden snapshot (the format's anchor)
# ---------------------------------------------------------------------------


class TestGoldenSnapshot:
    """One whole-stdout snapshot over MINIMAL; every other test is targeted."""

    # The full MINIMAL stdout, character for character. Built from the plan's
    # pinned format (item 1: column 40, one space before ``#``; item 3: the
    # 30-field order; item 4: router/backend blocks first). ``__PATH__`` is
    # the config path as typed; ``__ECHO_LINE__`` / ``__DESC_LINE__`` are the
    # real line numbers of ``tools.echo`` / ``tools.echo.description``.
    #
    # Choices the plan did NOT pin byte-for-byte (flagged as green ambiguities):
    #   * no blank line between the router and backend blocks, nor between the
    #     backend block and the first tool section (the plan pins only the
    #     inter-TOOL blank line);
    #   * the tool-header annotation is a bare ``<file>:<line>`` (no level
    #     suffix), per the plan's item-3 template literally;
    #   * a single trailing newline after the last field line.
    _GOLDEN_TEMPLATE = (
        "router:\n"
        "  host: 0.0.0.0                         # built-in default\n"
        "  port: 8600                            # built-in default\n"
        "  log_level: INFO                       # built-in default\n"
        "  log_dir: ./logs                       # built-in default\n"
        "  log_json: true                        # built-in default\n"
        "  cors_origins: [*]                     # built-in default\n"
        "  auth_token: null                      # built-in default\n"
        "  status_page: true                     # built-in default\n"
        "  log_output: router                    # built-in default\n"
        "backend:\n"
        "  type: docker                          # built-in default\n"
        "  network: tool-swap-net                # built-in default\n"
        "  container_prefix: ms-                 # built-in default\n"
        "  label_namespace: com.tool-swap        # built-in default\n"
        "  gpu_runtime: nvidia                   # built-in default\n"
        "  orphans: stop                         # built-in default\n"
        "  port_range: [7000, 7999]              # built-in default\n"
        "  registry_prefix: tool-swap            # built-in default\n"
        "tool: echo                              # __PATH__:__ECHO_LINE__\n"
        "  description: Echoes its input back.   "
        "# __PATH__:__DESC_LINE__ (inline)\n"
        "  ttl: 900                              # built-in default\n"
        "  keep_warm: false                      # built-in default\n"
        "  autostart: true                       # built-in default\n"
        "  evict_cost: 1                         # built-in default\n"
        "  max_concurrent: null                  # built-in default\n"
        "  restart_backoff: [1, 5, 15, 60]       # built-in default\n"
        "  max_consecutive_failures: 3           # built-in default\n"
        "  group: default                        # built-in default\n"
        "  devices: []                           # built-in default\n"
        "  cpus: null                            # built-in default\n"
        "  memory: null                          # built-in default\n"
        "  shm_size: 1g                          # built-in default\n"
        "  max_batch_size: 8                     # built-in default\n"
        "  max_wait_ms: 20                       # built-in default\n"
        "  workers: 1                            # built-in default\n"
        "  runtime_server: bentoml               # built-in default\n"
        "  start_timeout: 120                    # built-in default\n"
        "  ready_timeout: 600                    # built-in default\n"
        "  queue_timeout: 300                    # built-in default\n"
        "  request_timeout: 300                  # built-in default\n"
        "  drain_timeout: 30                     # built-in default\n"
        "  stop_timeout: 30                      # built-in default\n"
        "  max_queue_depth: 64                   # built-in default\n"
        "  health_path: /health                  # built-in default\n"
        "  ready_path: /ready                    # built-in default\n"
        "  probe_interval: 1.0                   # built-in default\n"
        "  container_port: 8000                  # built-in default\n"
        "  expose_host_port: false               # built-in default\n"
        "  env: {}                               # built-in default\n"
        "  mounts: []                            # built-in default\n"
    )

    def test_minimal_stdout_equals_the_pinned_golden(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Exit 0; stdout is exactly the pinned golden string.

        The alignment column, the field order, and the "all 30 present"
        promise are exactly the properties that rot silently, so the whole
        stdout is asserted character for character. The file path and the two
        inline line numbers are substituted from the written fixture.
        """
        path = _write(tmp_path, "tools.yaml", MINIMAL)
        echo_line = _line_of(MINIMAL, "  echo:")
        desc_line = _line_of(MINIMAL, "    description: Echoes its input back.")

        result = _invoke(runner, path)

        expected = (
            self._GOLDEN_TEMPLATE.replace("__PATH__", str(path))
            .replace("__ECHO_LINE__", str(echo_line))
            .replace("__DESC_LINE__", str(desc_line))
        )
        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert result.stdout == expected, (
            "The MINIMAL golden snapshot mismatched. "
            f"--- expected ---\n{expected!r}\n--- got ---\n{result.stdout!r}"
        )
        assert result.stderr == ""


# ---------------------------------------------------------------------------
# Origin annotations (item 1)
# ---------------------------------------------------------------------------


class TestOriginAnnotations:
    """The per-level origin vocabulary, with honest line-number availability."""

    def test_inline_ttl_has_a_real_line_number(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """``(inline)`` is the one level with a real ``<file>:<line>`` number.

        The line is computed from the fixture text (the actual line of the
        ``ttl:`` entry), never hardcoded, and matches
        ``line_for("tools.t.ttl")``.
        """
        path = _write(tmp_path, "tools.yaml", INLINE_TTL)
        ttl_line = _line_of(INLINE_TTL, "    ttl: 600")

        result = _invoke(runner, path)

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stderr: {result.stderr!r}"
        )
        expected = f"  ttl: 600" + " " * (
            _ORIGIN_COLUMN - len("  ttl: 600")
        ) + f"# {path}:{ttl_line} (inline)"
        assert expected in result.stdout, (
            f"Expected the inline ttl line with the real line number. "
            f"Expected: {expected!r}\nstdout: {result.stdout!r}"
        )

    def test_tool_yaml_value_has_no_line_number(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """A tool.yaml-sourced value annotates ``<path> (tool.yaml)`` with no line.

        The loader's line map is built from the ROOT document only, so the
        tool.yaml layer has no line number — the honest availability is pinned
        here: the annotation carries the path and the ``(tool.yaml)`` suffix
        but NO ``:<digits>``.
        """
        path = _write(tmp_path, "tools.yaml", SHADOW_TTL)
        _write(tmp_path, "t/tool.yaml", SHADOW_TTL_TOOL_YAML)

        result = _invoke(runner, path)

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stderr: {result.stderr!r}"
        )
        ttl_line = next(
            (l for l in result.stdout.splitlines() if l.lstrip().startswith(
                "ttl:")),
            None,
        )
        assert ttl_line is not None, (
            f"Expected a ttl line. stdout: {result.stdout!r}"
        )
        assert "t/tool.yaml (tool.yaml)" in ttl_line, (
            f"Expected the tool.yaml path + suffix on the ttl line. "
            f"Got: {ttl_line!r}"
        )
        annotation = ttl_line.split("#", 1)[1]
        assert not re.search(r":\d+", annotation), (
            f"The tool.yaml annotation must carry NO line number. "
            f"Got: {annotation!r}"
        )

    def test_defaults_layer_value_has_file_and_line(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """A ``defaults:``-sourced value annotates ``<file>:<line> (defaults)``."""
        path = _write(tmp_path, "tools.yaml", DEFAULTS_TTL)
        ttl_line = _line_of(DEFAULTS_TTL, "  ttl: 300")

        result = _invoke(runner, path)

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stderr: {result.stderr!r}"
        )
        expected = f"  ttl: 300" + " " * (
            _ORIGIN_COLUMN - len("  ttl: 300")
        ) + f"# {path}:{ttl_line} (defaults)"
        assert expected in result.stdout, (
            f"Expected the defaults-layer ttl line. "
            f"Expected: {expected!r}\nstdout: {result.stdout!r}"
        )

    def test_group_devices_has_group_annotation(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """A group-supplied value annotates ``<file>:<line> (group 'gpu0')``.

        Proves the ``{**groups[gname], "name": gname}`` injection reaches the
        display — without it the origin would read ``groups.unnamed.devices``.
        """
        path = _write(tmp_path, "tools.yaml", GROUP_DEVICES)
        devices_line = _line_of(GROUP_DEVICES, "    devices: [0]")

        result = _invoke(runner, path)

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stderr: {result.stderr!r}"
        )
        expected = f"  devices: [0]" + " " * (
            _ORIGIN_COLUMN - len("  devices: [0]")
        ) + f"# {path}:{devices_line} (group 'gpu0')"
        assert expected in result.stdout, (
            f"Expected the group-annotated devices line. "
            f"Expected: {expected!r}\nstdout: {result.stdout!r}"
        )

    def test_builtin_value_annotates_built_in_default(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """A value at its built-in default annotates exactly ``built-in default``."""
        path = _write(tmp_path, "tools.yaml", MINIMAL)

        result = _invoke(runner, path)

        assert result.exit_code == 0
        line = next(
            (l for l in result.stdout.splitlines() if l.lstrip().startswith(
                "shm_size:")),
            None,
        )
        assert line is not None, (
            f"Expected a shm_size line. stdout: {result.stdout!r}"
        )
        assert line.rstrip().endswith(f"# {_BUILTIN_ANNOTATION}"), (
            f"Expected the built-in annotation on the shm_size line. "
            f"Got: {line!r}"
        )


# ---------------------------------------------------------------------------
# --verbose: the shadowed values (item 2)
# ---------------------------------------------------------------------------


class TestVerbose:
    """--verbose shows the full shadow history; without it, nothing."""

    def test_verbose_shadows_defaults_and_synthesised_builtin(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """SHADOW_TTL --verbose shows the defaults loser and the built-in tail.

        The winner is tool.yaml's 600; the shadow list carries the defaults
        loser (300, with its real line) and the renderer-synthesised built-in
        tail (``# overrides 900 from built-in default``) — the ledger's
        headline example.
        """
        path = _write(tmp_path, "tools.yaml", SHADOW_TTL)
        _write(tmp_path, "t/tool.yaml", SHADOW_TTL_TOOL_YAML)
        defaults_line = _line_of(SHADOW_TTL, "  ttl: 300")

        result = _invoke(runner, path, "--verbose")

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stderr: {result.stderr!r}"
        )
        expected_defaults = (
            " " * _ORIGIN_COLUMN
            + f"# overrides 300 from {path}:{defaults_line} (defaults)"
        )
        expected_builtin = (
            " " * _ORIGIN_COLUMN
            + f"# overrides 900 from {_BUILTIN_ANNOTATION}"
        )
        assert expected_defaults in result.stdout, (
            f"Expected the defaults shadow line. "
            f"Expected: {expected_defaults!r}\nstdout: {result.stdout!r}"
        )
        assert expected_builtin in result.stdout, (
            f"Expected the synthesised built-in shadow line. "
            f"Expected: {expected_builtin!r}\nstdout: {result.stdout!r}"
        )

    def test_non_verbose_has_no_overrides_text(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Without --verbose the shadowed lines are absent.

        Pins the non-verbose output: no ``overrides`` text anywhere.
        """
        path = _write(tmp_path, "tools.yaml", SHADOW_TTL)
        _write(tmp_path, "t/tool.yaml", SHADOW_TTL_TOOL_YAML)

        result = _invoke(runner, path)

        assert result.exit_code == 0
        assert "overrides" not in result.stdout, (
            f"No shadow lines may appear without --verbose. "
            f"stdout: {result.stdout!r}"
        )

    def test_tool_yaml_shadow_omits_its_value(self, tmp_path: Path, runner: CliRunner) -> None:
        """A tool.yaml-layer shadow renders without its value (A25).

        The inline ttl (600) shadows a tool.yaml ttl (300); the shadowed
        tool.yaml layer is rendered as ``# overrides the value in <path>
        (tool.yaml)`` — the value is omitted on purpose (recovering it would
        need a second flattening implementation), only the file is named.
        """
        path = _write(tmp_path, "tools.yaml", A25_INLINE_WINS)
        _write(tmp_path, "t/tool.yaml", A25_TOOL_YAML)

        result = _invoke(runner, path, "--verbose")

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stderr: {result.stderr!r}"
        )
        shadow_lines = [
            l for l in result.stdout.splitlines() if "overrides" in l
        ]
        ty_shadow = [l for l in shadow_lines if "(tool.yaml)" in l]
        assert ty_shadow, (
            f"Expected a tool.yaml shadow line under --verbose. "
            f"stdout: {result.stdout!r}"
        )
        line = ty_shadow[0]
        assert "overrides the value in " in line, (
            f"Expected the A25 'overrides the value in' form. Got: {line!r}"
        )
        assert "300" not in line, (
            f"The tool.yaml shadow must NOT show its value. Got: {line!r}"
        )


# ---------------------------------------------------------------------------
# env per-key origins + redaction (items 5, 9)
# ---------------------------------------------------------------------------


class TestEnv:
    """env renders per-key with per-key origins; secrets are redacted."""

    def test_env_keys_render_with_origins_and_redaction(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Per-key lines: HF_TOKEN redacted with origin, HF_HOME in full.

        ``HF_TOKEN`` (inline) is redacted to ``***`` and its origin is still
        shown; ``HF_HOME`` does not match the secret pattern and is shown in
        full.
        """
        path = _write(tmp_path, "tools.yaml", ENV_SECRET)
        _write(tmp_path, "t/tool.yaml", ENV_SECRET_TOOL_YAML)

        result = _invoke(runner, path)

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stderr: {result.stderr!r}"
        )
        # HF_TOKEN redacted, origin still present on the same line.
        hf_token_line = next(
            (l for l in result.stdout.splitlines()
             if l.lstrip().startswith("HF_TOKEN:")),
            None,
        )
        assert hf_token_line is not None, (
            f"Expected an HF_TOKEN env line. stdout: {result.stdout!r}"
        )
        assert f"HF_TOKEN: {_REDACTED}" in hf_token_line, (
            f"Expected HF_TOKEN redacted to ***. Got: {hf_token_line!r}"
        )
        assert "(inline)" in hf_token_line, (
            f"The redacted HF_TOKEN line must keep its origin. "
            f"Got: {hf_token_line!r}"
        )
        # HF_HOME shown in full (not redacted).
        assert "HF_HOME: /weights" in result.stdout, (
            f"Expected HF_HOME shown in full. stdout: {result.stdout!r}"
        )
        assert "HF_HOME: ***" not in result.stdout

    def test_case_insensitive_redaction_covers_lowercase_keys(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Lowercase ``hf_token`` and ``api_key`` are redacted (case-insensitive).

        The env-key match is a case-INSENSITIVE substring, so the lowercase
        spellings are the same secret as their upper-case forms.
        """
        path = _write(tmp_path, "tools.yaml", ENV_SECRET)
        _write(tmp_path, "t/tool.yaml", ENV_SECRET_TOOL_YAML)

        result = _invoke(runner, path)

        assert result.exit_code == 0
        assert f"hf_token: {_REDACTED}" in result.stdout, (
            f"Expected lowercase hf_token redacted. stdout: {result.stdout!r}"
        )
        assert f"api_key: {_REDACTED}" in result.stdout, (
            f"Expected lowercase api_key redacted. stdout: {result.stdout!r}"
        )

    def test_accepted_false_positive_keystone_is_redacted(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """KEYSTONE_URL is redacted — the accepted false positive (contains KEY)."""
        path = _write(tmp_path, "tools.yaml", ENV_SECRET)
        _write(tmp_path, "t/tool.yaml", ENV_SECRET_TOOL_YAML)

        result = _invoke(runner, path)

        assert result.exit_code == 0
        assert f"KEYSTONE_URL: {_REDACTED}" in result.stdout, (
            f"Expected KEYSTONE_URL redacted (accepted false positive). "
            f"stdout: {result.stdout!r}"
        )

    def test_show_secrets_reveals_values_with_no_banner(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """--show-secrets opts out globally: real values, no *** and no banner.

        The flag is a legitimate local action, so no warning line is printed
        into the output; the real values appear and no ``***`` remains.
        """
        path = _write(tmp_path, "tools.yaml", ENV_SECRET)
        _write(tmp_path, "t/tool.yaml", ENV_SECRET_TOOL_YAML)

        result = _invoke(runner, path, "--show-secrets")

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stderr: {result.stderr!r}"
        )
        assert "HF_TOKEN: secret-token-1" in result.stdout, (
            f"Expected the real HF_TOKEN value. stdout: {result.stdout!r}"
        )
        assert "hf_token: t2" in result.stdout
        assert "api_key: k" in result.stdout
        assert "KEYSTONE_URL: u" in result.stdout
        assert _REDACTED not in result.stdout, (
            f"No *** may remain with --show-secrets. stdout: {result.stdout!r}"
        )
        # No banner: the flag is a legitimate local action, so no warning line
        # is printed into the output (the caution lives in the flag's help
        # text). The config is clean, so stderr is empty.
        assert "WARNING" not in result.stdout
        assert result.stderr == "", (
            f"No banner or warning may be emitted for --show-secrets. "
            f"stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# The redaction rule for auth_token (item 9)
# ---------------------------------------------------------------------------


class TestRedaction:
    """auth_token (the router block's) is redacted to *** with its origin."""

    def test_auth_token_redacted_with_origin(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """ROUTER_AUTH: auth_token is ***; the origin annotation is unchanged."""
        path = _write(tmp_path, "tools.yaml", ROUTER_AUTH)

        result = _invoke(runner, path)

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stderr: {result.stderr!r}"
        )
        line = next(
            (l for l in result.stdout.splitlines()
             if l.lstrip().startswith("auth_token:")),
            None,
        )
        assert line is not None, (
            f"Expected an auth_token line. stdout: {result.stdout!r}"
        )
        assert f"auth_token: {_REDACTED}" in line, (
            f"Expected auth_token redacted. Got: {line!r}"
        )
        assert "(router)" in line, (
            f"The redacted auth_token line must keep its origin. "
            f"Got: {line!r}"
        )

    def test_show_secrets_reveals_auth_token(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """--show-secrets reveals the real auth_token value."""
        path = _write(tmp_path, "tools.yaml", ROUTER_AUTH)

        result = _invoke(runner, path, "--show-secrets")

        assert result.exit_code == 0
        assert "auth_token: s3cr3t" in result.stdout, (
            f"Expected the real auth_token value. stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# mounts per-entry rendering (items 5, 6)
# ---------------------------------------------------------------------------


class TestMounts:
    """mounts renders host:container:mode per entry, with the ro default noted."""

    def test_mount_entries_render_with_mode_and_note(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """The :ro default is made explicit and the defaulted-mode note is pinned.

        The defaults-layer entry ``/data:/weights`` has no mode, so it renders
        ``/data:/weights:ro`` with the ``mode defaulted to ro`` note; the
        inline entry ``/cache:/cache:rw`` keeps its explicit mode.
        """
        path = _write(tmp_path, "tools.yaml", MOUNTS)

        result = _invoke(runner, path)

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stderr: {result.stderr!r}"
        )
        assert "/data:/weights:ro" in result.stdout, (
            f"Expected the defaulted :ro entry. stdout: {result.stdout!r}"
        )
        assert _MODE_DEFAULTED_NOTE in result.stdout, (
            f"Expected the 'mode defaulted to ro' note. "
            f"stdout: {result.stdout!r}"
        )
        assert "/cache:/cache:rw" in result.stdout, (
            f"Expected the explicit :rw entry. stdout: {result.stdout!r}"
        )
        # The note sits on the same line as the defaulted entry.
        ro_line = next(
            (l for l in result.stdout.splitlines()
             if "/data:/weights:ro" in l),
            None,
        )
        assert ro_line is not None and _MODE_DEFAULTED_NOTE in ro_line, (
            f"The note must be on the defaulted entry's line. "
            f"stdout: {result.stdout!r}"
        )
        # The explicit entry carries no defaulted-mode note.
        rw_line = next(
            (l for l in result.stdout.splitlines()
             if "/cache:/cache:rw" in l),
            None,
        )
        assert rw_line is not None and _MODE_DEFAULTED_NOTE not in rw_line, (
            f"The explicit :rw entry must not carry the note. "
            f"stdout: {result.stdout!r}"
        )

    def test_mount_order_is_defaults_first_inline_last(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Concatenation order: the defaults entry precedes the inline entry.

        Mounts concatenate built-in first, inline last (Docker's application
        order) — the opposite of every other field's most-specific-first
        convention, pinned so nobody "fixes" the display into descending order.
        """
        path = _write(tmp_path, "tools.yaml", MOUNTS)

        result = _invoke(runner, path)

        assert result.exit_code == 0
        lines = result.stdout.splitlines()
        defaults_idx = next(
            (i for i, l in enumerate(lines) if "/data:/weights:ro" in l), None
        )
        inline_idx = next(
            (i for i, l in enumerate(lines) if "/cache:/cache:rw" in l), None
        )
        assert defaults_idx is not None and inline_idx is not None, (
            f"Expected both mount entries. stdout: {result.stdout!r}"
        )
        assert defaults_idx < inline_idx, (
            f"Expected the defaults mount before the inline mount. "
            f"stdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# Carriers: a count, not the content (item 7)
# ---------------------------------------------------------------------------


class TestCarriers:
    """inputs/outputs/params/json_schema render as a one-line count."""

    def test_input_and_param_counts_render(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """``inputs: 3 entries`` and ``params: 1 entry`` (singular at 1)."""
        path = _write(tmp_path, "tools.yaml", CARRIERS)
        _write(tmp_path, "t/tool.yaml", CARRIERS_TOOL_YAML)

        result = _invoke(runner, path)

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stderr: {result.stderr!r}"
        )
        assert "inputs: 3 entries" in result.stdout, (
            f"Expected the inputs count form. stdout: {result.stdout!r}"
        )
        assert "params: 1 entry" in result.stdout, (
            f"Expected the singular params count form. "
            f"stdout: {result.stdout!r}"
        )

    def test_absent_carriers_print_nothing(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """An absent carrier prints NOTHING — no ``outputs:`` or ``json_schema:`` line.

        ``None`` means the author wrote no such key; the resolver's
        None-vs-absent distinction is preserved rather than flattened into a
        fake ``null`` line.
        """
        path = _write(tmp_path, "tools.yaml", CARRIERS)
        _write(tmp_path, "t/tool.yaml", CARRIERS_TOOL_YAML)

        result = _invoke(runner, path)

        assert result.exit_code == 0
        assert "outputs:" not in result.stdout, (
            f"No outputs: line for an absent carrier. stdout: {result.stdout!r}"
        )
        assert "json_schema:" not in result.stdout, (
            f"No json_schema: line for an absent carrier. "
            f"stdout: {result.stdout!r}"
        )

    def test_render_value_forms_are_pinned(self, tmp_path: Path, runner: CliRunner) -> None:
        """_render_value: None->null, bools->true/false, str unquoted, list->[a, b, c].

        Each form is pinned with a fixture value from the MINIMAL golden:
        ``auth_token: null`` (None), ``log_json: true`` / ``keep_warm: false``
        (bools), ``shm_size: 1g`` (str, unquoted),
        ``restart_backoff: [1, 5, 15, 60]`` (list).
        """
        path = _write(tmp_path, "tools.yaml", MINIMAL)

        result = _invoke(runner, path)

        assert result.exit_code == 0
        for expected in (
            "auth_token: null",
            "log_json: true",
            "status_page: true",
            "keep_warm: false",
            "shm_size: 1g",
            "restart_backoff: [1, 5, 15, 60]",
            "cors_origins: [*]",
        ):
            assert expected in result.stdout, (
                f"Expected the rendered value form {expected!r}. "
                f"stdout: {result.stdout!r}"
            )


# ---------------------------------------------------------------------------
# router/backend: top-level, raw, NOT per tool (item 4, A24)
# ---------------------------------------------------------------------------


class TestRouterBackend:
    """The router/backend blocks are shown once, from the raw config."""

    def test_router_backend_shown_once_not_per_tool(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """The router block is printed once; no tool section shows ``port``.

        A per-tool rendering would print ``port: 8600 # built-in default`` next
        to a config that plainly says ``router: {port: 9000}`` — a confident
        lie. So the raw value 9000 appears exactly once (in the router block).
        """
        path = _write(tmp_path, "tools.yaml", ROUTER_AUTH)

        result = _invoke(runner, path)

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stderr: {result.stderr!r}"
        )
        assert result.stdout.count("port: 9000") == 1, (
            f"Expected the raw port value exactly once. "
            f"stdout: {result.stdout!r}"
        )
        # Both top-level blocks are present.
        assert "router:" in result.stdout
        assert "backend:" in result.stdout

    def test_raw_router_value_shows_value_and_annotation(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """A key set in the raw router block shows the raw value + ``(router)``.

        Plan item 4: present in the raw block -> ``<file>:<line> (router)`` with
        the line from ``line_for("router.port")``; the level word is the block
        name.
        """
        path = _write(tmp_path, "tools.yaml", ROUTER_AUTH)
        port_line = _line_of(ROUTER_AUTH, "  port: 9000")

        result = _invoke(runner, path)

        assert result.exit_code == 0
        expected = f"  port: 9000" + " " * (
            _ORIGIN_COLUMN - len("  port: 9000")
        ) + f"# {path}:{port_line} (router)"
        assert expected in result.stdout, (
            f"Expected the raw router port line with a (router) annotation. "
            f"Expected: {expected!r}\nstdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# --json (item 8)
# ---------------------------------------------------------------------------


class TestJson:
    """--json: the {config, router, backend, tools} envelope, nothing else."""

    def test_json_envelope_and_structured_origin(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """stdout is valid JSON with the envelope; origin is a structured object.

        ``origin`` is ``{level, source, line}`` (never the human phrase);
        ``level`` is a string, ``line`` is an int or null; a tool field entry
        carries an always-present ``shadowed`` list.
        """
        path = _write(tmp_path, "tools.yaml", MINIMAL)

        result = _invoke(runner, path, "--json")

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stderr: {result.stderr!r}"
        )
        payload = json.loads(result.stdout)  # raises if stdout is not pure JSON
        assert set(payload) == {"config", "router", "backend", "tools"}, (
            f"Expected the {{config, router, backend, tools}} envelope. "
            f"Got keys: {sorted(payload)!r}"
        )
        assert payload["config"] == str(path)
        ttl = payload["tools"]["echo"]["ttl"]
        assert set(ttl) == {"value", "origin", "shadowed"}, (
            f"Expected the {{value, origin, shadowed}} field entry. "
            f"Got keys: {sorted(ttl)!r}"
        )
        origin = ttl["origin"]
        assert set(origin) == {"level", "source", "line"}
        assert isinstance(origin["level"], str)
        assert origin["line"] is None or isinstance(origin["line"], int)
        assert isinstance(ttl["shadowed"], list)
        assert ttl["value"] == 900

    def test_json_redacts_secrets(self, tmp_path: Path, runner: CliRunner) -> None:
        """Redaction applies in --json exactly as in the text (item 9)."""
        path = _write(tmp_path, "tools.yaml", ENV_SECRET)
        _write(tmp_path, "t/tool.yaml", ENV_SECRET_TOOL_YAML)

        result = _invoke(runner, path, "--json")

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        env = payload["tools"]["t"]["env"]
        assert env["HF_TOKEN"]["value"] == _REDACTED, (
            f"Expected HF_TOKEN redacted in JSON. Got: {env['HF_TOKEN']!r}"
        )
        assert env["HF_HOME"]["value"] == "/weights"

    def test_json_verbose_is_byte_identical(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """--verbose has no effect on --json: byte-identical stdout (item 8).

        ``shadowed`` is always present, so a machine consumer never re-runs
        with a different flag; ``--verbose`` is a rendering concern only.
        """
        path = _write(tmp_path, "tools.yaml", SHADOW_TTL)
        _write(tmp_path, "t/tool.yaml", SHADOW_TTL_TOOL_YAML)

        plain = _invoke(runner, path, "--json")
        verbose = _invoke(runner, path, "--json", "--verbose")

        assert plain.exit_code == 0 and verbose.exit_code == 0
        assert verbose.stdout == plain.stdout, (
            f"--json must be byte-identical with/without --verbose.\n"
            f"plain: {plain.stdout!r}\nverbose: {verbose.stdout!r}"
        )

    def test_json_show_secrets_reveals_value(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """--show-secrets with --json carries the real secret value."""
        path = _write(tmp_path, "tools.yaml", ENV_SECRET)
        _write(tmp_path, "t/tool.yaml", ENV_SECRET_TOOL_YAML)

        result = _invoke(runner, path, "--json", "--show-secrets")

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        env = payload["tools"]["t"]["env"]
        assert env["HF_TOKEN"]["value"] == "secret-token-1", (
            f"Expected the real HF_TOKEN value in JSON. Got: {env!r}"
        )


# ---------------------------------------------------------------------------
# Per-tool view (item 11) and unknown tool (item 12)
# ---------------------------------------------------------------------------


class TestPerTool:
    """config show <tool>: only that tool's section, router/backend kept."""

    def test_single_tool_view_hides_other_tools(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """``config show beta`` shows beta's section and not alpha's.

        The tool filter applies to the tool sections only; the other tool's
        section is absent.
        """
        path = _write(tmp_path, "tools.yaml", TWO_TOOLS)

        result = _invoke(runner, path, "beta")

        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. "
            f"stderr: {result.stderr!r}"
        )
        assert "tool: beta" in result.stdout, (
            f"Expected beta's section. stdout: {result.stdout!r}"
        )
        assert "tool: alpha" not in result.stdout, (
            f"alpha's section must be absent under 'config show beta'. "
            f"stdout: {result.stdout!r}"
        )

    def test_single_tool_view_still_prints_router_backend(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Under ``config show <tool>`` the router/backend blocks are STILL printed.

        They are global state, not tool-scoped; suppressing them would make the
        per-tool view claim a smaller effective config than exists (item 4).
        """
        path = _write(tmp_path, "tools.yaml", TWO_TOOLS)

        result = _invoke(runner, path, "beta")

        assert result.exit_code == 0
        assert "router:" in result.stdout, (
            f"The router block must be shown per tool. stdout: {result.stdout!r}"
        )
        assert "backend:" in result.stdout, (
            f"The backend block must be shown per tool. stdout: {result.stdout!r}"
        )


class TestUnknownTool:
    """config show <unknown-tool>: exit 1, the shared nearest-name line."""

    def test_unknown_tool_suggests_nearest_and_exits_one(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Exit 1 with the verbatim shared ``_unknown_tool`` line.

        ``'preidt'`` is distance 2 over length 7 from ``'predict'``
        (2 <= 0.3*7), so ``nearest_alternative`` suggests it. The line carries
        NO TSWAP- code — it is a usage error, not a config finding.
        """
        path = _write(tmp_path, "tools.yaml", NEAREST_NAME)

        result = _invoke(runner, path, "preidt")

        assert result.exit_code == 1, (
            f"Expected exit 1 for an unknown tool, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert _UNKNOWN_TOOL_LINE in result.stderr, (
            f"Expected the shared unknown-tool line. stderr: {result.stderr!r}"
        )
        assert re.search(r"TSWAP-[CS]\d{3}", result.stderr) is None, (
            "The unknown-tool error must carry no TSWAP- code. "
            f"stderr: {result.stderr!r}"
        )


# ---------------------------------------------------------------------------
# Exit codes (item 12)
# ---------------------------------------------------------------------------


class TestExitCodes:
    """The exhaustive exit-code table: 0 warnings, 1 errors, 2 missing."""

    def test_warning_only_exits_zero_with_config_on_stdout(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Warnings never fail: exit 0, the resolved config on stdout.

        The warning (C601) is shown on stderr — ``config show`` is never more
        optimistic than ``validate`` — but the exit stays 0.
        """
        path = _write(tmp_path, "tools.yaml", WARNING_ONLY)

        result = _invoke(runner, path)

        assert result.exit_code == 0, (
            f"Expected exit 0 (warnings never fail), got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert "tool: a" in result.stdout, (
            f"Expected the resolved config on stdout. stdout: {result.stdout!r}"
        )
        assert "TSWAP-C601" in result.stderr, (
            f"Expected the C601 warning on stderr. stderr: {result.stderr!r}"
        )

    def test_error_exits_one_but_config_still_on_stdout(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Errors exit 1 but the resolved output is NOT suppressed.

        Both tool sections are on stdout (the partial resolution is how a user
        finds the mistake); the C511 diagnostic is on stderr.
        """
        path = _write(tmp_path, "tools.yaml", TWO_TOOLS_ERROR)

        result = _invoke(runner, path)

        assert result.exit_code == 1, (
            f"Expected exit 1 for an error, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert "tool: alpha" in result.stdout, (
            f"alpha's section must still be on stdout. stdout: {result.stdout!r}"
        )
        assert "tool: beta" in result.stdout, (
            f"beta's section must still be on stdout. stdout: {result.stdout!r}"
        )
        assert "TSWAP-C511" in result.stderr, (
            f"Expected the C511 diagnostic on stderr. stderr: {result.stderr!r}"
        )

    def test_missing_file_exits_two_with_c000(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """A nonexistent --config path is TSWAP-C000 on stderr, exit 2.

        The same C0xx diagnostic and exit as ``validate`` (plan item 12, row 4).
        """
        missing = tmp_path / "does_not_exist.yaml"

        result = runner.invoke(
            app, ["config", "show", "--config", str(missing)]
        )

        assert result.exit_code == 2, (
            f"Expected exit 2 for a missing config, got {result.exit_code}. "
            f"stdout: {result.stdout!r} stderr: {result.stderr!r}"
        )
        assert "TSWAP-C000" in result.stderr
        assert "TSWAP-C000" not in result.stdout


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """NO_COLOR: colour-free output; a second invocation byte-identical."""

    def test_output_has_no_ansi_escapes(self, tmp_path: Path, runner: CliRunner) -> None:
        """Under NO_COLOR=1 no ANSI escape sequence appears anywhere."""
        path = _write(tmp_path, "tools.yaml", MINIMAL)

        result = _invoke(runner, path)

        assert "\x1b[" not in result.stdout
        assert "\x1b[" not in result.stderr

    def test_second_invocation_is_byte_identical(
        self, tmp_path: Path, runner: CliRunner
    ) -> None:
        """Two invocations in one process produce byte-identical stdout.

        The output is a pure function of the config: no dict-insertion-order
        or clock dependence.
        """
        path = _write(tmp_path, "tools.yaml", SHADOW_TTL)
        _write(tmp_path, "t/tool.yaml", SHADOW_TTL_TOOL_YAML)

        first = _invoke(runner, path)
        second = _invoke(runner, path)

        assert first.exit_code == 0 and second.exit_code == 0
        assert second.stdout == first.stdout, (
            f"A second invocation must be byte-identical.\n"
            f"first: {first.stdout!r}\nsecond: {second.stdout!r}"
        )

"""Generate ``docs/configuration.md`` from the Pydantic config models.

Every key ``tools.yaml`` understands, with its type, default and
description, grouped by block, plus a troubleshooting table covering
every ``TSWAP-C*``/``TSWAP-S*`` diagnostic code the codebase can emit.

Design (``plans/m1-configuration.md`` behaviour 25, items 3, 5 and 6):

- The document is rendered by the pure :func:`render_reference`;
  generation is deterministic (no timestamps, no absolute paths, no
  version banner).
- Field rows are built from ``Model.model_fields`` in declaration
  order, over a fixed pipeline model order (not alphabetical), and the
  type column reuses :func:`tool_swap.config.schema._describe_type` so
  it can never drift from the prose users see in ``TSWAP-C105``
  messages.
- The troubleshooting table is an authored ``CODE_TABLE`` of 76 rows
  (assumption A28): the 41 rule rows supply the cause only and their
  fix is read from ``BUILTIN_RULES``' ``Rule.remedy`` at render time
  (so a remedy edit shows up as a docs diff); the 14 S-codes and the
  21 non-rule C-codes carry both columns as authored data, because no
  code-side source exists for them.

Usage::

    python scripts/gen_config_reference.py            # write docs/configuration.md
    python scripts/gen_config_reference.py --check    # write nothing; exit 1 on drift
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from tool_swap.config.schema import (
    BackendConfig,
    BuildConfig,
    DefaultsConfig,
    GroupConfig,
    RootConfig,
    RouterConfig,
    ToolConfig,
    ToolYamlConfig,
    _describe_type,
)
from tool_swap.config.validate import BUILTIN_RULES

#: The rendered document, relative to the repository root.
REFERENCE_PATH: Final[Path] = Path("docs/configuration.md")

#: Pinned pipeline model order (plan item 3): deterministic and
#: declaration-ordered, not alphabetical.
_MODELS: Final[tuple[type[BaseModel], ...]] = (
    RootConfig,
    RouterConfig,
    BackendConfig,
    DefaultsConfig,
    GroupConfig,
    ToolConfig,
    BuildConfig,
    ToolYamlConfig,
)

#: Pinned section heading per model (plan item 6).
_SECTION_HEADINGS: Final[dict[str, str]] = {
    "RootConfig": "## The document root",
    "RouterConfig": "## `router:`",
    "BackendConfig": "## `backend:`",
    "DefaultsConfig": "## `defaults:`",
    "GroupConfig": "## `groups.<name>:`",
    "ToolConfig": "## `tools.<name>:`",
    "BuildConfig": "## `build:` (inside a tool)",
    "ToolYamlConfig": "## `tool.yaml`",
}

#: Trailing parenthesised citation on a docstring first line, e.g. the
#: ``(plan/02 §3)`` pointer that is noise in the user-facing reference.
_CITATION: Final[re.Pattern[str]] = re.compile(r"\s*\([^()]*\)$")


@dataclass(frozen=True)
class CodeRow:
    """One authored row of the troubleshooting table.

    Attributes:
        code: The diagnostic code (``TSWAP-C*`` or ``TSWAP-S*``).
        cause: What triggers the code. For the 41 rule rows this is the
            rule class's docstring summary, normalised at render time.
        fix: The fix. For the 41 rule rows this is unused (superseded by
            ``Rule.remedy`` at render time); for the 14 S-codes and the
            21 non-rule C-codes it is authored verbatim.
    """

    code: str
    cause: str
    fix: str


#: Every code the codebase can emit: 41 rule codes (fix read from
#: ``Rule.remedy`` at render time), 14 S-codes and 21 non-rule C-codes
#: (both columns authored) = 76 rows. ``TSWAP-C001`` has ONE row whose
#: cause names both emitters (the loader's YAML-syntax error and the
#: schema's unsupported-version error).
CODE_TABLE: Final[tuple[CodeRow, ...]] = (
    CodeRow(
        "TSWAP-C000",
        "The config file named on the command line does not exist.",
        "Check the path, or run from the directory holding tools.yaml.",
    ),
    CodeRow(
        "TSWAP-C001",
        "The file is not valid YAML, or its version: is not 1.",
        "Fix the YAML syntax; set version: 1 (or omit the key), since "
        "this build reads only config version 1.",
    ),
    CodeRow(
        "TSWAP-C002",
        "The same mapping key appears twice in the YAML.",
        "Remove the duplicate key so the mapping has one of each.",
    ),
    CodeRow(
        "TSWAP-C003",
        "The config file is empty.",
        "Add at least a 'tools:' block, e.g. the minimal config.",
    ),
    CodeRow(
        "TSWAP-C004",
        "The top level of the config is a list or a scalar, not a mapping.",
        "Make the top level a YAML mapping of keys to values.",
    ),
    CodeRow(
        "TSWAP-C005",
        "A tool directory named by path: exists but has no tool.yaml.",
        "Create tool.yaml in that directory, or drop the 'path:' key and "
        "configure the tool inline.",
    ),
    CodeRow(
        "TSWAP-C006",
        "A tool's path: points at a file, not a directory.",
        "Point 'path:' at the directory that holds tool.yaml, e.g. ./tools/t.",
    ),
    CodeRow(
        "TSWAP-C007",
        "An included tool.yaml contains a 'path:' key; include recursion "
        "is not supported (one level only).",
        "Remove the 'path:' key from tool.yaml; nested includes are not allowed.",
    ),
    CodeRow(
        "TSWAP-C010",
        "An interpolated variable is unset and the reference declares no default.",
        "Set the variable, or write ${VAR:-default} to give it one.",
    ),
    CodeRow(
        "TSWAP-C011",
        "The --env-file named on the command line does not exist.",
        "Create the file, or drop --env-file to auto-discover .env next to the config.",
    ),
    CodeRow(
        "TSWAP-C012",
        "A line of the .env file is not KEY=value.",
        "Write the line as KEY=value, or prefix it with '#' to comment it out.",
    ),
    CodeRow(
        "TSWAP-C013",
        "A ${...} reference is never closed with }.",
        "Add the missing } to close the reference.",
    ),
    CodeRow(
        "TSWAP-C101",
        "A key is not valid in the block it appears in.",
        "Rename the key to the suggested alternative, or remove it.",
    ),
    CodeRow(
        "TSWAP-C104",
        "devices: is a bare number, which reads like a device index but "
        "behaves like a count.",
        "Replace the number with a list of GPU indices, e.g. devices: [0,1,2].",
    ),
    CodeRow(
        "TSWAP-C105",
        "A value has the wrong shape for its key (any other schema error).",
        "Check the documented type and fix the value.",
    ),
    CodeRow(
        "TSWAP-C106",
        "A tool.yaml block key does not map to any tool field.",
        "Remove the key, or use one of the mapped keys named in the message.",
    ),
    CodeRow(
        "TSWAP-C201",
        "tool.yaml's name: does not equal the tools: map key.",
        "Make 'name:' in tool.yaml equal the tools: map key, or remove "
        "the 'name:' key if the tool.yaml is shared.",
    ),
    CodeRow(
        "TSWAP-C202",
        "Two tools: entries point at the same path: directory.",
        "Give each tool its own directory, unless the entries "
        "deliberately differ only by params:.",
    ),
    CodeRow(
        "TSWAP-C501",
        "A resolved ttl is not -1 (inherit), 0 (never stop) or a positive "
        "number of seconds.",
        "Set ttl to -1, 0, or a positive number of seconds.",
    ),
    CodeRow(
        "TSWAP-C503",
        "Two mounts map different host paths to the same container path.",
        "Remove one of the duplicate mounts so each container path is mounted once.",
    ),
    CodeRow(
        "TSWAP-C999",
        "Internal: a rule raised an exception instead of returning diagnostics.",
        "This is a tool-swap bug; file a report with the full traceback.",
    ),
    CodeRow(
        "TSWAP-C210",
        "a tool name outside `^[a-z0-9][a-z0-9_-]*$`.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C211",
        "two or more tools resolve to the same name.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C220",
        "a tool references a group absent from `groups:`.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C221",
        "`groups.*.max_resident` below 1.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C222",
        "`groups.*.eviction` outside the valid set.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C223",
        "a group defined but referenced by no tool.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C300",
        "a tool whose own description is missing or blank.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C301",
        "an `inputs:` entry missing its description.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C302",
        "an `outputs:` entry missing its description.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C303",
        "a `params:` entry missing its description.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C400",
        "a reserved `soft_ttl` present at any level.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C401",
        "`runtime.server: native` (not implemented).",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C402",
        "`runtime.server` outside {bentoml, native}.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C403",
        "a reserved `scalar_inputs` present.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C404",
        "a per-input `batchable:` key (inputs ONLY).",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C405",
        "a reserved `max_batch_bytes` present.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C510",
        "more than one image source.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C511",
        "no image source at all.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C512",
        "a `handler` outside the `file.py:ClassName` form.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C513",
        "the handler file does not exist (or is a directory).",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C514",
        "a named `requirements` file that does not exist.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C515",
        "`build.context` or `build.dockerfile` missing.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C516",
        "a path escaping the tool directory (WARNING).",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C520",
        "a negative or non-integer device index.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C521",
        "a device index exceeding the visible GPUs.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C522",
        "a duplicate index within one tool's `devices`.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C523",
        "`workers > 1` AND a non-empty `devices` list.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C530",
        "two tools sharing an explicit host port.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C531",
        "an explicit host port outside `backend.port_range`.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C532",
        "an inverted or malformed `backend.port_range`.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C540",
        "an unparseable mount entry.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C541",
        "a mount mode outside `{ro, rw}`.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C542",
        "a non-absolute container path.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C543",
        "the host path does not exist (WARNING).",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C600",
        "`keep_warm: true` AND `autostart: false`.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C601",
        "`keep_warm: true` AND an EXPLICIT `ttl > 0`.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C602",
        "`max_concurrent` at or below zero.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C603",
        "an out-of-range batching or timeout number.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C610",
        "every member keep_warm while `max_resident` < count.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C612",
        "two or more groups sharing a device index.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-C613",
        "`max_resident` above the member count.",
        "",  # fix read from Rule.remedy at render time
    ),
    CodeRow(
        "TSWAP-S100",
        "Two entries in the same inputs:/outputs: block share a name.",
        "Rename one of the entries so each name appears once.",
    ),
    CodeRow(
        "TSWAP-S101",
        "A name appears in both inputs: and params:.",
        "Remove the name from one of the blocks so it appears in only one.",
    ),
    CodeRow(
        "TSWAP-S102",
        "An input name is not a valid Python identifier; handlers receive "
        "inputs as keyword arguments, so the input can never be passed.",
        "Rename it to a valid identifier.",
    ),
    CodeRow(
        "TSWAP-S103",
        "An entry's type (or an array entry's items type) is not one of "
        "the six supported: string, number, integer, boolean, array, "
        "object.",
        "Use one of the six types, or move the tool to a json_schema: "
        "block for enums, ranges, oneOf or nested objects.",
    ),
    CodeRow(
        "TSWAP-S104",
        "An entry's semantic: value is not a string.",
        "Write 'semantic' as a string, or remove it.",
    ),
    CodeRow(
        "TSWAP-S105",
        "The inputs:/outputs: block is not a list, or one of its entries "
        "is not a non-empty mapping.",
        "Make the block a YAML list of entries, each a mapping with at least a 'name'.",
    ),
    CodeRow(
        "TSWAP-S106",
        "An entry has no non-empty string name:.",
        "Add a non-empty string 'name' to the entry.",
    ),
    CodeRow(
        "TSWAP-S107",
        "An inputs: entry's required: value is not a boolean.",
        "Set 'required' to true or false.",
    ),
    CodeRow(
        "TSWAP-S108",
        "An entry's description: is present but is not a string.",
        "Write the entry's 'description' as a string.",
    ),
    CodeRow(
        "TSWAP-S109",
        "An entry's type is array but it declares no items:.",
        "Add 'items: <one of the six types>' to the entry.",
    ),
    CodeRow(
        "TSWAP-S110",
        "An array entry's items: is itself an array or an object with "
        "properties: (nesting beyond one level).",
        "Move the tool to a json_schema: block to describe nested items.",
    ),
    CodeRow(
        "TSWAP-S120",
        "An entry is missing its description: (ERROR on inputs:, WARNING on outputs:).",
        "Add a non-blank 'description' to the entry.",
    ),
    CodeRow(
        "TSWAP-S130",
        "A tool declares both json_schema: and inputs:; they are alternatives.",
        "Remove one of them from the tool's tool.yaml.",
    ),
    CodeRow(
        "TSWAP-S140",
        "The authored json_schema: is not valid JSON Schema 2020-12.",
        "Fix the schema so it validates against the 2020-12 meta-schema.",
    ),
)


def _blurb(model: type[BaseModel]) -> str:
    """The model docstring's first line, as the section's one-line blurb.

    Strips a trailing parenthesised citation (the ``plan/02 §3``
    pointer) and converts RST double backticks to markdown singles, so
    the reference reads as user documentation rather than plan notes.

    Args:
        model: The block model whose docstring provides the blurb.

    Returns:
        The one-line blurb, or an empty string when the model has no
        docstring.
    """
    doc = (model.__doc__ or "").strip()
    if not doc:
        return ""
    first = doc.splitlines()[0].strip()
    first = _CITATION.sub("", first).strip()
    return first.replace("``", "`")


def _render_default(field: FieldInfo) -> str:
    """Render a field's default value in YAML spelling (plan item 3).

    Args:
        field: The field whose default is rendered.

    Returns:
        ``—`` (an em dash) for the single required field (no default);
        ``null``/``true``/``false`` for None/bool; double-quoted
        strings; plain numbers; and ``[...]``/``{...}`` for containers.
    """
    if field.is_required():
        return "—"
    value = field.get_default()
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, (int, float)):
        return str(value)
    return repr(value)


def _troubleshooting_rows() -> list[tuple[str, str, str]]:
    """The 76 table rows sorted lexicographically by code.

    The 41 rule rows' fix is read from ``BUILTIN_RULES``'
    ``Rule.remedy`` at render time, so a remedy edit in ``validate.py``
    surfaces as a docs diff. The 35 authored rows keep their own fix.

    Raises:
        ValueError: if the table and the rule registry disagree (a row
            for a code no rule carries, or a rule whose code the table
            lacks).
    """
    remedies = {rule.id: rule.remedy for rule in BUILTIN_RULES}
    rule_ids = set(remedies)
    table_codes = {row.code for row in CODE_TABLE}
    missing = sorted(rule_ids - table_codes)
    if missing:
        raise ValueError(f"rules with no CODE_TABLE row: {', '.join(missing)}")
    rows: list[tuple[str, str, str]] = []
    for row in CODE_TABLE:
        if row.code in remedies:
            rows.append((row.code, row.cause, remedies[row.code]))
        else:
            rows.append((row.code, row.cause, row.fix))
    return sorted(rows, key=lambda item: item[0])


def _field_table(model: type[BaseModel]) -> str:
    """The per-block ``| Key | Type | Default | Description |`` table."""
    lines = [
        "| Key | Type | Default | Description |",
        "|---|---|---|---|",
    ]
    for name, field in model.model_fields.items():
        key = f"`{name}`"
        type_text = _describe_type(field.annotation)
        default = _render_default(field)
        description = field.description or ""
        lines.append(f"| {key} | {type_text} | {default} | {description} |")
    return "\n".join(lines)


def render_reference() -> str:
    """Render the whole of ``docs/configuration.md`` as a string.

    Pure: no I/O, no globals mutated. Deterministic — two calls in one
    process, and two calls in two processes, return equal strings.

    Raises:
        ValueError: listing every ``Model.field`` that has no non-empty
            description (the generator must fail loudly rather than
            emit a reference with blank rows).
    """
    missing = [
        f"{model.__name__}.{name}"
        for model in _MODELS
        for name, field in model.model_fields.items()
        if not (field.description or "").strip()
    ]
    if missing:
        raise ValueError(
            f"{len(missing)} model fields lack a non-empty "
            f"description; refusing to render: {', '.join(missing)}"
        )

    out: list[str] = [
        "# Configuration reference",
        "",
        "<!-- GENERATED FILE — do not edit by hand.",
        "     Regenerate with: python scripts/gen_config_reference.py -->",
        "",
        "Every key tool-swap understands, with its type, default and meaning.",
        "Generated from the Pydantic models in `src/tool_swap/config/schema.py`.",
        "",
    ]
    for model in _MODELS:
        heading = _SECTION_HEADINGS[model.__name__]
        out.append(heading)
        out.append("")
        out.append(_blurb(model))
        out.append("")
        out.append(_field_table(model))
        out.append("")

    out.append("## Troubleshooting: every diagnostic code")
    out.append("")
    out.append("| Code | Cause | Fix |")
    out.append("|---|---|---|")
    for code, cause, fix in _troubleshooting_rows():
        out.append(f"| `{code}` | {cause} | {fix} |")
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: write the file, or ``--check`` it.

    Args:
        argv: The command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        ``0`` on success (or, with ``--check``, when the committed file
        already equals the rendered text); ``1`` on drift or when a
        field lacks a description.
    """
    parser = argparse.ArgumentParser(
        description="Generate docs/configuration.md from the config schema.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 if the committed file has drifted",
    )
    args = parser.parse_args(argv)

    try:
        rendered = render_reference()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.check:
        if not REFERENCE_PATH.is_file():
            print(f"error: {REFERENCE_PATH} is missing", file=sys.stderr)
            return 1
        committed = REFERENCE_PATH.read_text(encoding="utf-8")
        if committed == rendered:
            return 0
        print(f"--- {REFERENCE_PATH}\n+++ rendered", file=sys.stderr)
        print(
            "error: docs/configuration.md has drifted from the schema; "
            "run python scripts/gen_config_reference.py",
            file=sys.stderr,
        )
        return 1

    REFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE_PATH.write_text(rendered, encoding="utf-8")
    print(f"wrote {REFERENCE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

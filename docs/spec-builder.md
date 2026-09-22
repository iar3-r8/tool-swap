# The config to ContainerSpec builder

The router runs each tool inside its own container. Starting that
container needs a precise recipe: which image, what name, which
network, which host directories get mounted and in what mode, which
environment variables, which GPUs. This page documents the function
that writes that recipe —
[`build_container_spec`](../src/tool_swap/lifecycle/spec_builder.py:19)
— which takes the tool's resolved configuration and the `backend:`
block from your config file and returns the complete start
instructions, a
[`ContainerSpec`](../src/tool_swap/backend/base.py:49).

Without it, whatever code starts the container would have to work out
for itself how the container is named, which labels mark it as
tool-swap's, how environment values are coerced, where relative mount
paths resolve from, and which host port is published — and each of
those decisions could drift. The builder is the single place where the
YAML you wrote in your config file and the container you see running
in `docker ps` meet.

**Where it sits:** you write the tool and the `backend:` block in your
config file (the [Configuration guide](configuration-guide.md)
covers that); this function turns the resolved result of that config
into a `ContainerSpec`; and [the backend seam
page](backend-seam.md) documents what consumes that spec to actually
start, stop and inspect the container. If you do not yet know what the
`backend:` block looks like, start with the Configuration guide.

One honest caveat before the detail: **nothing in the router calls
this function yet.** The component that will use it, the
`LifecycleManager`, is not built, so no container has been started
through this path. The rest of the page documents the function in
full, and says explicitly where it stops.

## The function

```python
def build_container_spec(
    resolved: ResolvedTool,
    cfg: BackendConfig,
    image: str,
    *,
    config_dir: Path | None = None,
) -> ContainerSpec: ...
```

[`resolved`](../src/tool_swap/config/resolver.py:82) is one tool's fully
resolved values, [`cfg`](../src/tool_swap/config/schema.py:95) is the
`backend:` block as its own object, `image` is the resolved image
reference, and `config_dir` — **the config file's directory** — is the
base relative mount hosts resolve against.

## The concrete through-line: authored YAML to `ContainerSpec`

This section shows the whole thing happening on one real config
before the exhaustive field table. A complete, validated config — the
same `backend:` block as the committed
[`tools.example.yaml`](../tools.example.yaml), a `defaults:` block
with `env` and both mount forms, one tool:

```yaml
# tools.yaml
version: 1

backend:
  type: docker
  network: tool-swap-net
  container_prefix: ms-
  label_namespace: com.tool-swap
  gpu_runtime: nvidia
  orphans: stop
  port_range: [7000, 7999]
  registry_prefix: tool-swap

defaults:
  env:
    HF_HOME: /weights/hf
    HF_TOKEN: ${HF_TOKEN:-}
  mounts:
    - ./models:/weights/hf       # two-part: mode defaults to ro
    - ./cache:/cache:rw          # three-part: read-write, explicit

tools:
  summarizer:
    image: tool-swap/summarizer:1.0
    description: Summarize a long text into one short paragraph.
    expose_host_port: 7001       # an int publishes exactly that port
```

`expose_host_port` is written as an int on purpose: `true` is rejected
by the builder — see [The published port](#the-published-port-four-forms-two-of-them-worth-explaining)
and [What goes wrong](#what-goes-wrong). Run the config through the
validated pipeline — `load_config`, `resolve_tool`, then
[`build_container_spec`](../src/tool_swap/lifecycle/spec_builder.py:19)
with `config_dir` set to the directory holding the config — and it
returns:

```python
ContainerSpec(
    tool='summarizer',
    name='ms-summarizer',
    image='tool-swap/summarizer:1.0',
    gpu_runtime='nvidia',
    container_port=8000,
    command=None,
    env={'HF_HOME': '/weights/hf', 'HF_TOKEN': ''},
    labels={'com.tool-swap.model': 'summarizer',
            'com.tool-swap.managed-by': 'tool-swap'},
    network='tool-swap-net',
    mounts=(
        MountSpec(source='config/models', target='/weights/hf', read_only=True),
        MountSpec(source='config/cache', target='/cache', read_only=False),
    ),
    devices=(),
    shm_size='1g',
    cpus=None,
    memory=None,
    published_port=7001,
)
```

Read it against the config, field by field:

- **`name`** is `backend.container_prefix` plus the tool name, so the
  container you will see in `docker ps` is predictable before anything
  starts: `ms-` + `summarizer`.
- **`labels`** is derived from `backend.label_namespace`: the
  `model` and `managed-by` keys are always stamped
  ([`managed_labels`](../src/tool_swap/backend/labels.py:54)), and
  reconciliation later finds the router's own containers by filtering
  on exactly these.
- **The two mounts** show the two legal forms: the two-part entry takes
  its mode from the parser's `ro` default, the three-part entry keeps
  the authored `rw`. Each `source` is the relative host resolved
  against **the config file's directory** — here `config/` — not the
  tool's directory and not the working directory.
- **`published_port`** is the authored `7001`. `false` and `null` both
  yield `None` (nothing published); `true` raises, because the schema
  promises an allocation from `backend.port_range` that nothing
  implements — write an explicit port instead.
- **`shm_size`** is `"1g"` although nothing in the config names it:
  the built-in default is a non-optional string, so a tool that
  configures nothing gets `"1g"`, never the spec's `None`.
- **`env["HF_TOKEN"]` is `''`**: the variable was unset in this run and
  the `:-` fallback is empty — interpolation substitutes the fallback,
  and the builder coerces every value with `str()`.

The `backend:` values reach the spec because the builder takes
`BackendConfig` as a separate argument — the resolver never merged
them; see [the trap](#the-trap-backendconfig-never-values) below.

## Where this page stops

The function is pure: two config objects and an image reference in,
one `ContainerSpec` out. It is the **only place a `ParsedMount`
becomes a `MountSpec`**, so the `mode → read_only` normalisation can
live in only one place. It has **no caller yet**: the
`LifecycleManager` that consumes it is not built, so nothing in the
router calls `build_container_spec` today and no container has been
started through this path. [The backend seam
page](backend-seam.md) documents what the spec is consumed *by*; this
page documents how the spec is *built*.

The design and its reasoning are in
[`plans/m2b-lifecycle-manager.md`](../plans/m2b-lifecycle-manager.md)
— [D-D](../plans/m2b-lifecycle-manager.md:1192) and
[D-E](../plans/m2b-lifecycle-manager.md:1201) for the two settled
refusals (the illegal mount mode, and `expose_host_port: true`), and
[§6.3](../plans/m2b-lifecycle-manager.md:1272) and
[§6.4](../plans/m2b-lifecycle-manager.md:1294) for the two config-layer
gaps this function works around rather than fixes.

## The field mapping

Every spec field:

| Spec field | Comes from | Note |
|---|---|---|
| `tool` | `resolved.name` | — |
| `name` | [`container_name`](../src/tool_swap/backend/labels.py:111)(`cfg.container_prefix`, `tool`) | a name the helper rejects propagates as the same `ValueError` — it already names the prefix, the tool and the rule |
| `image` | the `image` argument | an empty image raises `ValueError` naming the tool here, rather than reaching the backend's run-kwargs construction |
| `container_port` | `resolved.values["container_port"]` | read from `values` because `BackendConfig` has **no** `container_port` field — it is a tool-level default; a non-int value raises `TypeError` naming the type it got |
| `gpu_runtime` | `cfg.gpu_runtime` | |
| `network` | `cfg.network` | |
| `labels` | [`managed_labels`](../src/tool_swap/backend/labels.py:54)(`cfg.label_namespace`, `tool`) | |
| `env` | `resolved.values["env"]` | every value coerced with `str()` — the schema types the dict `dict[str, Any]`, and a container cannot read a non-string; a non-mapping raises `TypeError` |
| `devices` | `resolved.values["devices"]` | a tuple of ints in **authored order** — not sorted away, because the order is a real allocation; a non-int entry raises `TypeError` |
| `cpus` | `resolved.values["cpus"]` | verbatim; `null` → `None`, which leaves it unlimited |
| `memory` | `resolved.values["memory"]` | the size string verbatim — the SDK's `parse_bytes` parses it, not this function, so an authored `16zz` passes here and fails at the daemon call with the SDK's message (the [knowingly-brittle note on the seam page](backend-seam.md#two-things-documented-as-knowingly-brittle)) |
| `shm_size` | `resolved.values["shm_size"]` | the config field is a non-optional string with built-in `"1g"`, so a tool configuring nothing gets `"1g"`, **never** the spec's `None` default — a `None` reaching the spec would read as a legitimate "unset" |
| `mounts` | `resolved.values["mounts"]` through [`parse_mount`](../src/tool_swap/config/validate.py:2488) | see [Mounts](#mounts-one-conversion-three-refusals) |
| `published_port` | `resolved.values["expose_host_port"]` | see [The published port](#the-published-port-four-forms-two-of-them-worth-explaining) |

## What goes wrong

Two of the three builder refusals are caught earlier, by
`tswap validate`, and the messages a reader will actually see are the
validator's:

| Mistake | What you see |
|---|---|
| a mount mode that is not `ro` or `rw`, e.g. `./models:/weights/hf:RO` | `ERROR TSWAP-C541 — Mount entry './models:/weights/hf:RO' has mode 'RO'; the only legal modes are ro and rw` |
| an unparseable entry, e.g. `./models/weights/hf` | `ERROR TSWAP-C540 — Mount entry './models/weights/hf' is unparseable: expected host:container or host:container:ro\|rw` |

The third slips past the validator:

| Mistake | What you see |
|---|---|
| `expose_host_port: true` | `tswap validate --strict` reports no problem at all; the error surfaces when the spec is built: `ValueError: expose_host_port for tool 'summarizer' is true, which promises auto-allocation from backend.port_range; no allocator exists, so write an explicit port instead` |

The asymmetry is the point: the schema's own description promises the
allocation, validation lets `true` through, and the builder is the
boundary that refuses it with a message that names the fix.

## The trap: `BackendConfig`, never `values`

`BackendConfig` is a **separate required argument**, never read out of
`resolved.values`. This is the subtlest thing about the builder, and
a reader who does not know it will reach for `values` — the code would
type-check, pass a naive test, and fail much later in a different
place.

The shape of the trap:

- `values`' key set is **exactly** `set(BUILT_IN_DEFAULTS)`
  ([`resolver.py:239`](../src/tool_swap/config/resolver.py:239)), and
  eight of the
  [`BUILT_IN_DEFAULTS`](../src/tool_swap/config/defaults.py:20) keys are
  backend keys. So `values["label_namespace"]`,
  `values["container_prefix"]`, `values["network"]` and
  `values["gpu_runtime"]` are **always present** — and always carry
  the *built-in* value.
- **`resolve_tool` has no `backend:` layer.**
  [`resolver.py`](../src/tool_swap/config/resolver.py) does not contain
  the string `backend`. The `backend:` block is a root block that never
  enters tool-level resolution, so whatever an operator authored under
  `backend:` is invisible to `values`.

A builder reading `values["label_namespace"]` would therefore stamp
`com.tool-swap` on every container *whatever the operator
configured*. Nothing at build or start time complains; the failure
surfaces much later, as **reconciliation failing to adopt containers
the router itself started** — `list_managed` filters by the
configured namespace and cannot see the wrongly-labelled containers.

**This is a live gap in the config layer, not a style rule**
([§6.3](../plans/m2b-lifecycle-manager.md:1272)). The real fix belongs
there — either a `backend:` layer in the resolver, or removing the
backend keys from the tool-level key set so the wrong value is
unreachable rather than merely unused — and it is **not yet fixed in
the tree**. Until it lands, two local mitigations hold the line:
`BackendConfig` is a required argument of the builder, and the second
[guard](#the-two-guards) fails the suite if any backend-named key is
ever read out of `values` under `lifecycle/`.

## Mounts: one conversion, three refusals

The builder is the single `ParsedMount` → `MountSpec` conversion in
the tree
([`_mount_specs`](../src/tool_swap/lifecycle/spec_builder.py:63)). One
`MountSpec` per authored entry, **in declaration order**:

- `source` is the **resolved** host path — `MountSpec` performs no
  resolution of its own, so the builder must do it;
- `target` is the container path;
- `read_only` is `mode == "ro"`, so the two-part entry
  `host:container` (mode defaulted to `ro` by the parser) yields
  `read_only=True` — read-only-by-default
  ([`plan/01`](../plan/01_ARCHITECTURE.md) §10) survives the
  conversion instead of depending on `MountSpec`'s field default.

The resolution base is **the config file's directory, never the
tool's `base_dir`** — the plausible wrong answer. Resolution is
lexical (`normpath`, no disk, no CWD), inherited from
[`parse_mount`](../src/tool_swap/config/validate.py:2488). Two further
invariants: a tool's mounts concatenate defaults-then-tool rather than
replacing, and the order survives into the spec; the same container
target twice keeps **both** entries, since de-duplication is config
validation's job (`TSWAP-C503`).

Three refusals, all raising:

1. **A mode that is neither `ro` nor `rw` raises**
   ([D-D](../plans/m2b-lifecycle-manager.md:1192)). The loud default
   over the safe one: a silent downgrade to read-only would hide a
   bypassed validator and yield a container whose mounts do not match
   its config. It is unreachable unless config validation was
   bypassed — `TSWAP-C541` rejects any other mode case-sensitively,
   `"RO"` included — which is exactly why the error names the tool,
   the entry and the offending mode, so a bypass cannot go unnoticed.
2. **An unparseable entry raises**, naming the tool and the entry. A
   silent drop would yield a container missing a mount its config
   promised.
3. **Mounts with no `config_dir` raise.** `parse_mount` has no default
   base, so without one a relative host would resolve against **the
   router's working directory** — a different directory on every host
   the deployment lands on. The builder therefore refuses up front. A
   tool with **no** mounts and no `config_dir` is fine: the refusal
   only engages when there is something to resolve.

A `mounts` value that is not a list of strings raises `TypeError`, and
`mounts: []` yields the spec's empty tuple.

## The published port: four forms, two of them worth explaining

`expose_host_port` is typed `bool | int | None`
([`schema.py:447`](../src/tool_swap/config/schema.py:447)), so four
forms are reachable, and
[`_published_port`](../src/tool_swap/lifecycle/spec_builder.py:210)
pins all four ([D-E](../plans/m2b-lifecycle-manager.md:1201)):

| Authored value | `published_port` |
|---|---|
| `false` (the built-in default) | `None` — nothing published |
| `null` | `None` — nothing published |
| an `int` | exactly that host port — **never** copied from `container_port` |
| `true` | **raises** `ValueError` |

`null` behaving like `false` is not an accident: it follows the
convention of **every other nullable field in this schema** (`cpus`
and `memory` both "null leaves it unlimited", `auth_token` "null
disables authentication") — an authored null means "no opinion, take
the benign default", never "error". Raising on it would also turn
valid config into a runtime crash: `TSWAP-C530` and `TSWAP-C531` both
skip non-`int` values, so `expose_host_port: null` passes validation,
and a builder that raised on it would let the router load, resolve and
only then fail.

**`true` raises, and the error is not a bug.** The schema's own
description promises that `true` "auto-allocates from
`backend.port_range`", and **no allocator exists**: nothing outside
`schema.py`, `defaults.py` and the validation rules reads
`port_range` ([§6.4](../plans/m2b-lifecycle-manager.md:1294)). The
generated [Configuration reference](configuration.md) reproduces that
schema description, so it carries the same promise — the text is a
promise, not a working feature. The builder therefore raises a
`ValueError` that names the gap and tells the operator to write an
explicit port, rather than inventing an allocation policy inside a
spec builder. The right fix — an allocator, or a `TSWAP-C` rule
rejecting `true` — belongs to the config layer and is **not yet fixed
in the tree**.

One last asymmetry: `true` and the integer `1` are **deliberately not
interchangeable** despite being equal in Python (`True == 1`, and
`isinstance(True, int)`). The builder checks `bool` before `int`,
because a naive int check would publish port `1` for `true`.

## The two guards

Ordinary tests cannot police the two boundaries above — a regression
there compiles, type-checks and passes the builder's tests — so two
source-level guards walk the source tree, in
[`tests/unit/lifecycle/test_spec_builder_guards.py`](../tests/unit/lifecycle/test_spec_builder_guards.py),
with the AST detectors in
[`tests/unit/lifecycle/spec_builder_guards.py`](../tests/unit/lifecycle/spec_builder_guards.py).
Both walks are read-only, both name the offending file and line, and
neither writes anything under `src/`.

**Guard 1 — one mount parser.** Walks every `.py` under
`src/tool_swap/lifecycle/` (excluding `__pycache__`) and fails on a
`split` / `partition` / `rpartition` / `re.split` call whose
**first positional argument** is the literal `":"`, or on any callable
**defined** `parse_mount`. The backend's one-parser guard walks
`src/tool_swap/backend/` only; this walk covers the directory the
`ParsedMount` → `MountSpec` conversion lives in, and is what keeps it
a *call* to
[`parse_mount`](../src/tool_swap/config/validate.py:2488) rather than
a copy. A *call* to the legitimate parser is not an offender, nor is a
split on another separator, nor a separator carried by a later
argument.

**Guard 2 — no backend-named key from `values`.** Fails on any
`x.values[key]` subscript where `key` is one of `network`,
`container_prefix`, `label_namespace`, `gpu_runtime` — the four
present-but-wrong keys of [the trap](#the-trap-backendconfig-never-values).
Only the attribute form counts (a bare local named `values` is a
different AST shape), and the builder's legitimate tool-level reads —
`container_port`, `mounts`, `env`, … — are not flagged.

**The guards were not taken on trust.** A green guard and a blind
guard are indistinguishable from the test output, so non-vacuity is
carried two ways: in-memory decoys (string constants parsed with
`ast.parse`, covering both the reach side — each violation shape must
be reported — and the precision side — benign colons and the builder's
own legitimate code must not be) and **real violations injected into
the source tree**, each confirmed caught before the tree was restored.

**The key-set pin is a subset, not an exact match.** `BACKEND_KEYS` is
pinned against `BUILT_IN_DEFAULTS` by a subset check, because the four
trap keys cannot be derived from the eight backend keys without
restating them. It fails if one of the four **disappears** from
`BUILT_IN_DEFAULTS`; it does **not** fail if a fifth backend-named key
is **added** and goes unpoliced. That residual gap is stated here
rather than papered over.

## What this page does not claim

- **No daemon verification.** Every test here is a pure function over
  config objects. No container has been started, no socket opened, no
  docker fact asserted.
- **The builder has no caller yet.** The `LifecycleManager` that
  would use it is not built, so `build_container_spec` is a reviewed,
  guarded function with no production consumer.
- **`expose_host_port: true` is not supported.** The schema
  description promising an auto-allocation is currently wrong; writing
  `true` yields the `ValueError` documented above.
- **The guard's key set is a subset pin**, not an exact one — a fifth
  unpoliced backend key would not fail the suite.
- **The two config-layer gaps are not fixed** — `backend:` is not a
  resolver layer ([§6.3](../plans/m2b-lifecycle-manager.md:1272)) and
  there is no port allocator
  ([§6.4](../plans/m2b-lifecycle-manager.md:1294)). Both remain open
  in the tree; the builder works around each with a refusal or a
  required argument.

## Where to go deeper

- [`docs/backend-seam.md`](backend-seam.md) — the `ContainerSpec` this
  builder produces, the protocol that consumes it, and the one-parser
  boundary that guard 1 extends.
- [`docs/configuration-guide.md`](configuration-guide.md) — where the
  `backend:` block and the tool-level keys the builder reads are
  configured; the generated [Configuration
  reference](configuration.md) for exact types and defaults.
- [`plans/m2b-lifecycle-manager.md`](../plans/m2b-lifecycle-manager.md)
  — the settled decisions D-D and D-E
  ([§5](../plans/m2b-lifecycle-manager.md#5-settled-decisions)) and the
  open assumptions
  (§6.3, §6.4 in [§6](../plans/m2b-lifecycle-manager.md#6-open-assumptions)).
- [`plan/01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md) §10 — why
  mounts are read-only by default.

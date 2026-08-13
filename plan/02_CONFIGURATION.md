# 02 — Configuration

> Requirement **R4**: *"it should be simple to configure."*
> The test for this document: **a working single-model config must fit in five lines**, and every additional line must buy something the user actually asked for.

---

## 1. Guiding principles

1. **One file to start.** `tools.yaml` in the repo root is all you need. Splitting into per-tool files via `path:` includes is an option, not a requirement (**D24**) — and it is what makes a tool directory self-contained and portable.
2. **Defaults + overrides**, exactly as R8's `serve_config` did (a `defaults:` block, then per-model overrides). This pattern was good; keep it.
3. **Unknown keys are a fatal error.** R8's config silently ignored a `batch_size` typo where the field was `max_batch_size`, so an override did nothing and nobody noticed. Use Pydantic with `extra="forbid"` and fail at startup with the offending key and its file/line.
4. **Validate everything at startup, not at first request.** Bad image name, duplicate port, unknown group, device index that does not exist, missing handler file — all must be caught by `tswap validate` and by router boot.
5. **Env var interpolation** (`${HF_HOME}`, `${HF_TOKEN}`) with `${VAR:-default}` syntax, plus `.env` file loading. Secrets go in `.env`, never in `tools.yaml`.
6. **Macros/anchors for repetition.** llama-swap has a `macros:` feature for exactly this; YAML anchors also work. Provide `x-defaults` anchors in the examples so users copy a DRY pattern.
7. **Config is data, not code.** No Python imports, no plugin paths that the router must import (that would break the isolation invariant).

---

## 2. Minimal viable config

The whole promise, for a tool whose code the author wrote — which is **every** tool (see [`03_TOOL_AUTHORING.md`](03_TOOL_AUTHORING.md)):

```yaml
tools:
  cxr_to_embedding:
    path: ./tools/cxr_to_embedding      # dir with tool.yaml + handler.py + requirements.txt
```

Everything else has a sensible default.

> There is no second form for wrapping a third-party server image. tool-swap hosts our own algorithms; LLM serving belongs to llama-swap, in a separate deployment ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §0).

---

## 3. Full global config reference

```yaml
# ============================================================================
# tools.yaml — tool-swap configuration
# ============================================================================

version: 1                          # config schema version; router refuses unknown majors

# ---------------------------------------------------------------------------
# Router: the always-on HTTP entry point
# ---------------------------------------------------------------------------
router:
  host: 0.0.0.0
  port: 8600
  log_level: INFO                   # DEBUG | INFO | WARNING | ERROR | CRITICAL
  log_dir: ./logs                   # router log + one subdir per model
  log_json: true                    # structured .jsonl alongside human-readable console
  cors_origins: ["*"]               # for browser clients / the status page
  auth_token: ${TSWAP_TOKEN:-}      # if set, require Authorization: Bearer <token>
  status_page: true                 # serve the HTML status page at /ui

# ---------------------------------------------------------------------------
# Container backend
# ---------------------------------------------------------------------------
backend:
  type: docker                      # docker | fake (fake is for tests only)
  network: tool-swap-net           # created if absent
  container_prefix: ms-             # container name = <prefix><model_name>
  label_namespace: com.tool-swap   # labels used for reconciliation and pruning
  gpu_runtime: nvidia               # passed as --gpus / device requests
  orphans: stop                     # stop | adopt | ignore — what to do with running
                                    # containers whose model left the config
  port_range: [7000, 7999]          # for host-published debug ports
  registry_prefix: tool-swap       # image naming for built images

# ---------------------------------------------------------------------------
# Defaults inherited by every model. Any key here can be overridden per model.
# ---------------------------------------------------------------------------
defaults:
  # --- lifecycle / TTL ---
  ttl: 900                          # idle seconds -> stop container. THE ONLY IDLE TIMER (ADR-0004)
                                    # sentinels: -1 inherit defaults.ttl | 0 never stop | >0 seconds
                                    # NOTE: soft_ttl is RESERVED AND REJECTED, not supported (ADR-0004)
  keep_warm: false                  # start at boot and never TTL-stop
  autostart: true                   # start on first request; if false, must be started manually

  # --- resources ---
  group: default                    # scheduling group
  devices: []                       # GPU indices, e.g. [0] or [0,1]. [] = CPU only
  cpus: null                        # docker --cpus, e.g. 4.0
  memory: null                      # docker --memory, e.g. "16g"
  shm_size: "1g"                    # torch DataLoader workers need this raised

  # --- batching (see 05_RUNTIME_AND_BATCHING.md) ---
  max_batch_size: 8
  max_wait_ms: 20                   # -> BentoML max_latency_ms; a target, not a fixed wait
  workers: 1                        # in-container worker processes
  runtime_server: bentoml           # bentoml (v1) | native (specified, not implemented)

  # --- timeouts (seconds) ---
  start_timeout: 120
  ready_timeout: 600
  queue_timeout: 300
  request_timeout: 300
  drain_timeout: 30
  stop_timeout: 30
  max_queue_depth: 64

  # --- health probing ---
  health_path: /health
  ready_path: /ready
  probe_interval: 1.0

  # --- environment and storage applied to EVERY model ---
  env:
    HF_HOME: /weights/hf
    HF_TOKEN: ${HF_TOKEN:-}
  mounts:
    - ${HF_HOME:-~/.cache/huggingface}:/weights/hf:rw

# ---------------------------------------------------------------------------
# Scheduling groups. A group caps how many of its members may run at once.
# ---------------------------------------------------------------------------
groups:
  default:
    max_resident: 4
    eviction: lru                   # lru | lifo | none
  gpu0:
    max_resident: 1                 # only one model on this GPU at a time -> true swapping
    devices: [0]
    eviction: lru
  gpu1:
    max_resident: 1
    devices: [1]
  cpu:
    max_resident: 8                 # CPU-only tools; no device contention

# ---------------------------------------------------------------------------
# Tools — every one of them is ours, built from a handler + requirements
# ---------------------------------------------------------------------------
tools:

  # --- (a) defined in its own directory (the simple path, and the usual one) ---
  cxr_to_embedding:
    path: ./tools/cxr_to_embedding   # contains tool.yaml, handler.py, requirements.txt
    group: gpu0                      # inline overrides beat the tool.yaml
    ttl: 600

  # --- (b) defined fully inline (no separate tool.yaml) ---
  text_embedding:
    handler: ./tools/text_embedding/handler.py:TextEmbedding
    requirements: ./tools/text_embedding/requirements.txt
    group: gpu1
    max_batch_size: 32
    max_wait_ms: 50

  # --- (c) exotic build: our runtime, but the author supplies the Dockerfile ---
  totalsegmentator:
    build:
      context: ./tools/totalsegmentator
      dockerfile: Dockerfile         # must install tool_swap_runtime and run the handler
    group: gpu1
    ttl: 300
    mounts:
      - /data/ct:/data/ct:ro

  # --- (e) always-warm small CPU model ---
  text_cleanup:
    path: ./tools/text_cleanup
    devices: []
    keep_warm: true
    group: cpu
```

---

## 4. Per-model `tool.yaml` reference

Lives next to `handler.py`. Lets a model directory be **self-describing and portable** — copy the folder, add one `path:` line to `tools.yaml`, done.

```yaml
# ./tools/cxr_to_embedding/tool.yaml
name: cxr_to_embedding
version: "0.1.0"

# What the tool does. MANDATORY (D19). Surfaced in /tools so that humans and LLM
# agents can discover it. R8 raised an error when a tool docstring was missing;
# we keep that discipline.
description: >
  Convert the chest X-ray image at the provided PATH into a vector EMBEDDING
  using the RAD-DINO foundation model.

# Entry point: file:ClassName (class with load/predict/unload) or file:function
handler: handler.py:CXRToEmbedding

# Environment. Level 1 = requirements.txt. Deeper levels in 03_TOOL_AUTHORING.md
runtime:
  base_image: tool-swap/base-cuda:12.4-py312   # optional; default chosen by 'accelerator'
  accelerator: cuda                              # cuda | cpu
  requirements: requirements.txt
  system_packages: []                            # apt packages, e.g. [libgl1, ffmpeg]
  pre_install: []                                # raw shell lines before pip install
  post_install: []                               # raw shell lines after pip install
  server: bentoml                                # in-container serving backend (D14).
                                                 # 'native' is reserved and rejected in v1
                                                 # with "not implemented in this version".

# I/O schema. Optional but STRONGLY recommended: it is compiled into JSON Schema
# (D13) and projected into OpenAI-style tool definitions and OpenAPI, so declaring
# it is what makes this model callable by an LLM agent with no adapter written.
# See 04_API_CONTRACT.md §9.
inputs:
  - name: paths
    type: string         # JSON Schema type: string|number|integer|boolean|array|object
    required: true
    description: Path to a DICOM chest X-ray image to embed.   # MANDATORY: an LLM reads this
    semantic: dicom_path # free-form domain hint -> x-semantic; never interpreted by the router
outputs:
  - name: embedding
    type: array
    items: number
    description: Embedding vector of shape (768,) per input image.

# Static parameters (D15). Fixed at load time, passed to the handler's __init__,
# NOT accepted per request and NOT part of the agent-visible tool definition.
# This is where a knob like `threshold` belongs: on a batched tool it CANNOT be a
# per-request input, because requests with different values would share a batch.
# See 03_TOOL_AUTHORING.md §3.1.
params: []
#  - name: threshold
#    type: number
#    default: 0.5
#    description: Confidence threshold applied to detections.

# Escape hatch: for enums, ranges, nested objects or oneOf, supply raw JSON Schema
# instead of `inputs:`. Passed through untouched. Note it describes per-request
# INPUTS only, so the same D15 rule applies: on a batched tool, every property here
# must be batchable.
# json_schema:
#   type: object
#   properties:
#     paths: { type: array, items: { type: string }, description: DICOM paths to embed. }
#   required: [paths]
#   additionalProperties: false

# Batching hints (overridable in tools.yaml)
batching:
  enabled: true
  max_batch_size: 8
  max_wait_ms: 20

# Resource hints (overridable in tools.yaml)
resources:
  accelerator: cuda
  vram_gb: 4           # advisory in v1; the basis for VRAM-aware scheduling later
  group: gpu0

lifecycle:
  ttl: 600
  ready_timeout: 600

# Smoke test used by `tswap test <model>` AND by `tswap preflight` stage 6.
# Strongly recommended: without it a tool cannot be preflighted end to end,
# and preflight downgrades to a warning (03 §10.1).
example:
  inputs:
    paths: /weights/samples/cxr.dcm
```

**`example:` is worth more than it looks.** It is the only executable statement of what this tool does with real input, and three separate mechanisms consume it: `tswap test`, `tswap preflight` stage 6 (which additionally validates the response against the declared output schema), and a reviewer trying to understand an unfamiliar tool. Ship the sample file inside the image or on a documented mount so the example is runnable anywhere — an `example` pointing at a path that exists only on the author's laptop is worse than none, because it fails for everyone else.

### 4.1 Precedence

```
inline tools.yaml entry  >  tool.yaml  >  defaults:  >  built-in defaults
```

`tswap config show <model>` must print the fully-resolved effective config **with the origin of each value** (which file/level it came from). This one command eliminates the majority of "why is it not using my setting?" support questions.

### 4.2 Values you should measure rather than guess

Four keys are routinely guessed, and a wrong guess produces a tool stuck in `FAILED` or an OOM on a shared GPU. `tswap preflight` measures each and emits them as a paste-ready snippet (**D17**, [`03_TOOL_AUTHORING.md`](03_TOOL_AUTHORING.md) §10.1.3):

| Key | Derived from | Failure when guessed badly |
|---|---|---|
| `ready_timeout` | measured cold start × a safety margin | too low ⇒ a healthy tool is declared `FAILED` mid-load, repeatedly |
| `resources.vram_gb` | peak VRAM during the example inference (GPU hosts only) | too low ⇒ over-packed group ⇒ CUDA OOM for someone else's tool |
| `batching.max_latency_ms` | measured single-item inference time | too low ⇒ batches never fill; too high ⇒ needless latency |
| `batching.max_batch_size` | throughput at the measured VRAM headroom | too high ⇒ OOM under concurrency, only ever under load |

`group` is deliberately **not** on this list: preflight cannot know your GPU layout, so it emits a placeholder with a comment rather than a plausible-looking default. A confidently wrong default here would put a tool on a contended device silently.

---

## 5. Field reference

### 5.1 Identity

| Field | Type | Default | Notes |
|---|---|---|---|
| `name` | str | map key | `[a-z0-9_-]+`. Used in URLs, container names, log dirs. Enforce the charset. |
| `path` | path | — | Directory containing `tool.yaml`. Shorthand for everything in it. |
| `description` | str | — | **Required.** Discovery/documentation, and the text an LLM agent reads to decide whether to call this tool. |

There is no `kind` key. Every tool is built from a handler on our runtime, so there is nothing to discriminate. There is no `aliases` key either — it existed to resolve OpenAI `model` strings, and that door is gone ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §7).

### 5.2 Image and command

| Field | Type | Default | Notes |
|---|---|---|---|
| `image` | str | built | Pin a pre-built image of this tool instead of building it. |
| `build.context` / `build.dockerfile` | path | — | Build a custom image. |
| `cmd` | list[str] | image default | Full command override. |
| `args` | list[str] | `[]` | Appended to the image entrypoint. The vLLM pattern. |
| `container_port` | int | `8000` | Port the server listens on *inside* the container. |
| `expose_host_port` | bool \| int | `false` | Publish for debugging; `true` picks from `backend.port_range`. |

### 5.3 Lifecycle

| Field | Type | Default | Notes |
|---|---|---|---|
| `ttl` | int s | `900` | Idle → stop, freeing VRAM, the container, host RAM and the group slot. **The only idle timer** ([ADR-0004](adr/0004-hard-stop-only-in-v1.md)). Sentinels: **`-1` inherit**, **`0` never**, **`>0` seconds**. |
| ~~`soft_ttl`~~ | — | — | **Reserved and rejected** ([ADR-0004](adr/0004-hard-stop-only-in-v1.md)). Accepted by the schema, rejected at load with a message pointing at that ADR — so re-promotion stays additive and nobody sets a key that does nothing. |
| `evict_cost` | int | `1` | Relative cost of evicting this tool; higher means prefer to keep it resident. Breaks ties in an otherwise-LRU policy ([`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](06_LIFECYCLE_TTL_AND_SCHEDULING.md) §5.1.1). Set it above 1 for tools with long cold starts. |
| `max_concurrent` | int | unset | Optional cap on in-flight requests to a `READY` tool; **429** beyond it. Unset means uncapped, and the runtime's own back-pressure applies ([`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](06_LIFECYCLE_TTL_AND_SCHEDULING.md) §10). |
| `keep_warm` | bool | `false` | Start at boot, exempt from TTL. Still evictable unless `eviction: none` on its group. **Implemented as a synthetic request through the ordinary request path**, never a separate warm-up code path. |
| `autostart` | bool | `true` | If `false`, a request to a stopped model returns 503 instead of starting it. |
| `restart_backoff` | list[int] | `[1,5,15,60]` | Backoff after `FAILED` before an automatic retry. |
| `max_consecutive_failures` | int | `3` | After this, stop auto-retrying until manually reset. |

### 5.4 Resources and scheduling

| Field | Type | Default | Notes |
|---|---|---|---|
| `group` | str | `default` | Must exist in `groups:` — validate. |
| `devices` | list[int] | from group | GPU indices → `NVIDIA_VISIBLE_DEVICES` / device requests. `[]` = CPU. |
| `cpus`, `memory`, `shm_size` | | | Straight to Docker. Raise `shm_size` for torch DataLoaders. |
| `vram_gb` | float | — | Advisory in v1; the hook for VRAM-aware scheduling. |

**On device semantics — an explicit correction of an R8 flaw.** In R8's config, `gpu: 3` meant "three GPUs" but read like "GPU #3". Here `devices` is always **a list of GPU indices**, never a count. Inside the container the model always sees them as `cuda:0..n-1`, so handlers need no device arithmetic. Do not repeat the ambiguity.

### 5.5 Batching and the runtime backend

| Field | Type | Default | Notes |
|---|---|---|---|
| `batching.enabled` | bool | `true` | `false` means **`max_batch_size: 1`, and nothing else** ([ADR-0005](adr/0005-one-uniform-batched-calling-convention.md)). It is a performance setting, **not** a switch between calling conventions — the handler takes a list either way. |
| `max_batch_size` | int | `8` | Upper bound on a batch. **Also the mitigation for the absent `max_batch_bytes`** ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §4.2): for large payloads such as CT volumes, set this low per tool. |
| `max_wait_ms` | int | `20` | Maps to BentoML's `max_latency_ms`: a **latency target the adaptive dispatcher aims to keep**, not a fixed wait. ⚠️ **`60000` is BentoML's own default**, inherited by any tool that does not override it — not, as this document previously said, a value R8 invented. **The adapter must always pass this and `max_batch_size` explicitly.** |
| `workers` | int | `1` | In-container worker processes. `>1` needs an explicit worker→device mapping and multiplies VRAM; see [`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §5. **`tswap validate` warns when `workers > 1` with `devices:` set** — VRAM multiplies invisibly to the scheduler. |
| `runtime.server` | enum | `bentoml` | **D14.** The in-container serving backend. `native` is a reserved value: accepted by the schema, rejected at load with *"not implemented in this version"*. Reserved now so adding it later is not a config migration. |

There is no `max_batch_bytes` key. BentoML's dispatcher batches by count, and inventing a key we cannot honour would be worse than not having it ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §4.2).

**There is also no per-input `batchable:` flag** ([ADR-0005](adr/0005-one-uniform-batched-calling-convention.md)). Batching is a property of the tool, and every input is a field of the batched item.

### 5.5.1 Static parameters

| Field | Type | Default | Notes |
|---|---|---|---|
| `params` | list | `[]` | **D15**, as re-scoped by [ADR-0005](adr/0005-one-uniform-batched-calling-convention.md). Load-time values passed to the handler's `__init__`. Each needs `name`, `type`, `description`; `default` optional. Overridable per config entry — **changing one restarts the tool**, since it is part of the tool's identity. |

**`params:` is for values that change what the batched forward pass computes** — input resolution, dtype, a different model head, a weights path. They are not caller-visible and do not appear in `?format=tools`.

⚠️ **`threshold` is no longer the example here.** A confidence threshold shapes one item's own result, so it belongs in `inputs:` and travels per item ([ADR-0005](adr/0005-one-uniform-batched-calling-convention.md)). The question to ask is: *does this value change what the batched forward pass computes?* If yes → `params:`, and two values in production means two `tools:` entries over one image. If no → `inputs:`.

### 5.6 Environment and mounts

| Field | Type | Merge rule |
|---|---|---|
| `env` | map | **Merged** with `defaults.env`; model wins on conflict. |
| `mounts` | list[str] | **Concatenated** with `defaults.mounts`; `host:container[:ro|rw]`. Default to `ro` when the mode is omitted, and say so. |
| `env_file` | path | Extra `.env` loaded into the container. |

Merge semantics for maps vs lists are a classic source of confusion — state them in the docs and test them.

---

## 6. Validation rules (all enforced by `tswap validate`)

1. Unknown keys anywhere → error naming the key and the nearest valid alternative (`did you mean max_batch_size?`).
1b. **`batching.enabled: true` + any non-batchable entry in `inputs:` → hard error** (**D15**). The message must name the offending input and both remedies: move it to `params:`, or set `batching.enabled: false`. This prevents a *silent* wrong-answer bug ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §4.3), so it is an error rather than a warning, with no `--allow` flag.
1c. `runtime.server: native` → error *"not implemented in this version"*, naming the version that would support it. Any other value → unknown-value error listing the valid ones.
1d. No `name` collision between an entry in `inputs:` and one in `params:`.
2. `name` matches `^[a-z0-9][a-z0-9_-]*$`; no duplicate names.
3. Every `group` referenced exists; every `groups.*.max_resident >= 1`.
4. `soft_ttl` is **rejected** with a message pointing at [ADR-0004](adr/0004-hard-stop-only-in-v1.md) — not silently ignored.
4b. *(Removed.)* A tool declaring `devices` no longer has to define `unload()`. Nothing calls it on the reclamation path, so a handler that fails to release has no victim ([ADR-0004](adr/0004-hard-stop-only-in-v1.md) §4).
4c. **Warn when `workers > 1` and `devices:` is set** — VRAM multiplies by the worker count, invisibly to the scheduler ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §5).
5. Exactly one image source: `image` XOR `build` XOR (managed → we build it).
6. For managed: handler file exists; `requirements` file exists if named; `description` non-empty; `inputs`/`outputs` well-formed if present.
6b. **A missing `description` on the tool or on any input → hard error; a missing description on an output → warning** (**D19**). `--allow-missing-descriptions` downgrades the errors for local prototyping and is never permitted in CI.
7. Device indices are non-negative and refer to **whole GPUs** (**D7**); warn (do not fail) if they exceed the GPUs visible on this host, since the config may target another machine.
8. No two tools share an `expose_host_port`; all published ports fall inside `backend.port_range`. This applies only to the debugging opt-in — normal operation publishes nothing and allocates nothing (**D21**).
9. Mount host paths exist (warn, do not fail — they may be created later) and mount strings parse.
10. Env interpolation: a referenced variable with no value and no default → error naming the variable.
11. `keep_warm: true` together with `autostart: false` → error (contradictory).
12. Total `max_resident` across groups sharing a device is only a warning — we do not model VRAM in v1.
13. **Every member of a group is `keep_warm` while `max_resident` is smaller than the member count → warning** (**D9**). The configuration guarantees starvation: `keep_warm` exempts a tool from TTL but not from eviction, so the group can never satisfy all of its members. The message names the group and suggests either raising `max_resident` or using `eviction: none` if pinning was the intent.

---

## 7. Applying a config change

**In v1, config changes are applied by restarting the router: `tswap restart`.** This is cheap and non-disruptive because the router holds no persistent state and **reconciles on boot** — it finds its labelled containers, adopts the ready ones, and carries on serving them ([`01_ARCHITECTURE.md`](01_ARCHITECTURE.md) §13). A restart therefore costs no cold starts for tools that were already warm.

Validation runs **before** anything is touched, so a malformed config fails fast with the old router still running ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §8).

A no-downtime `tswap reload` / `POST /admin/reload` is **deferred**. It is not free: it requires classifying every key as hot-applicable or restart-requiring, tracking dirty containers, and applying the whole diff atomically so the router is never half-configured. That is a meaningful amount of machinery to replace a command that already works. Should it be built, this is the intended behaviour:

| Change | Action |
|---|---|
| New tool added | Registered. Started only if `keep_warm`. |
| Tool removed | Stopped and deregistered. |
| Lifecycle/TTL/timeouts changed | Applied live, no restart. |
| Image/args/env/mounts/devices changed | Marked **dirty**: keep serving with the old container, restart it on next idle (or immediately with `--force`). |
| Group topology changed | Re-evaluated; may trigger eviction. |
| Router host/port/log settings changed | Requires a router restart — say so explicitly in the reload output. |

Reload would have to be **atomic**: validate the whole new config first, and on any error keep the old one and return the error unchanged. Never leave the router in a half-applied state.

---

## 8. Worked example: the R8 tool set, ported

For orientation, here is roughly what the R8 model zoo looks like expressed in this config. (R8 ran all of these in one shared venv; here each is independent.)

```yaml
groups:
  gpu0: { max_resident: 1, devices: [0] }
  gpu1: { max_resident: 1, devices: [1] }
  cpu:  { max_resident: 8 }

tools:
  cxr_to_embedding:               # RAD-DINO chest X-ray encoder (torch)
    path: ./tools/cxr_to_embedding
    group: gpu0
  ct_to_embedding:                # CT foundation model (monai/torch)
    path: ./tools/ct_to_embedding
    group: gpu0
  eeg_to_embedding:               # REVE EEG foundation model (transformers)
    path: ./tools/eeg_to_embedding
    group: gpu1
  text_to_embedding:              # Mistral sentence-transformers
    path: ./tools/text_to_embedding
    group: gpu1
    max_batch_size: 32
  tb_from_cxr_embedding:          # small classifier head, CPU is plenty
    path: ./tools/tb_from_cxr_embedding
    devices: []
    group: cpu
    keep_warm: true
  organ_donor:                    # TensorFlow/Keras model — the one that could never
    path: ./tools/organ_donor     # cleanly free its GPU memory in a shared process
    group: gpu1
```

Note what this buys: the TensorFlow model and the torch models no longer share an interpreter, so `tf.keras.backend.clear_session()` stops being a process-wide hazard — stopping that one container frees exactly its own memory. That is the whole thesis of the project in one config block.

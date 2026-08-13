# llama-swap — annotated catalogue

**Root URL:** https://github.com/mostlygeek/llama-swap
**Upstream version at capture:** **v249**, published 2026-08-10. Files read from `main`, which is at or ahead of that tag.
**Captured:** 2026-08-13
**Extracted by:** Oxylabs `universal_scraper` MCP tool (`output_format: md`) against `raw.githubusercontent.com`, plus the GitHub REST API for the repository tree and the release tag.

This directory holds local copies of the llama-swap material that the plan depends on. **llama-swap is cited 56 times across 15 plan documents and had no capture until now** — the one load-bearing external reference with no evidence base behind it, despite [`00_CONTEXT_AND_MOTIVATION.md`](../../00_CONTEXT_AND_MOTIVATION.md) §4 instructing *"Read its README before designing the config."*

> **This capture differs in kind from both of its neighbours.** [`ray-serve/`](../ray-serve/INDEX.md) is evidence for a **rejection** ([ADR-0003](../../adr/0003-ray-serve-not-adopted.md)); [`bentoml/`](../bentoml/INDEX.md) is working reference material for an **adoption** (**D14**). This one is neither. llama-swap was **rejected as our router** ([ADR-0001](../../adr/0001-build-our-own-router.md), Spike A) and is simultaneously **the design we are copying** (**D1**, **D4**) and **the sibling service in the same deployment** ([`04_API_CONTRACT.md`](../../04_API_CONTRACT.md) §0). Call it an *inspiration* capture: its job is to make the borrowed semantics checkable and to keep our description of a project we do not control from drifting.

The narrative reading of this material — behaviour by behaviour, with the divergences named — is [`17_LLAMA_SWAP_PHILOSOPHY.md`](../../17_LLAMA_SWAP_PHILOSOPHY.md). **Start there if your question is "what are we copying and why".** Start here if your question is "does llama-swap really do that".

---

## 1. What was captured

| Local file | Source | Completeness | What it supplies | Bears on |
| --- | --- | --- | --- | --- |
| [`readme.md`](readme.md) | `README.md` | Verbatim (images stripped) | The full API surface across four protocol families; the feature list; the Docker install path; *"one binary, one configuration file"*; *"Almost all configuration settings are optional"*; the how-it-works paragraph; the Docker/Podman recommendation for Python servers | **D1**, **D4**, **R1**, **R4**; the document [`00 §4`](../../00_CONTEXT_AND_MOTIVATION.md) told us to read |
| [`configuration.md`](configuration.md) | `docs/configuration.md` | Verbatim | The three-line minimal config; multi-line `cmd`; **a complete worked `docker run` + `cmdStop` example with GPU pinning**; the feature summary table | **R4**, guardrail 10, [`02_CONFIGURATION.md`](../../02_CONFIGURATION.md); **finding F1** |
| [`config-schema.md`](config-schema.md) | `config-schema.json` (~40 KB) | ⚠️ **Condensed** — every key with type, default and verbatim description; JSON envelope summarised | The real semantics of `ttl`, `unloadTimeout`, `groups`, `matrix`/`evict_costs`, `routing.scheduler`, `checkEndpoint`, `concurrencyLimit`, `hooks`, `peers`, `macros`, `capabilities` | **D4**, **D7**, **D9**, **D21**, **D22**, **D25**; **gaps G1–G4** |
| [`container-security.md`](container-security.md) | `docs/container-security.md` | Verbatim, complete | Root-by-default in container images; `non-root` image variants; userns remapping; the Hugging Face pickle warning | **D20**, M5 base images; **gap G5** |
| [`router-design-notes.md`](router-design-notes.md) | `docs/newrouter-todo.md` | ⚠️ **Condensed excerpt** of an **internal working document** on a moving branch | Their own router rewrite: the mux/dispatch/cross-cutting decomposition, the `Router`/`LocalRouter`/`Peer` interface split, preload-as-synthetic-request, shutdown ordering, and **seven gaps found after all functional phases were marked complete** | [`01_ARCHITECTURE.md`](../../01_ARCHITECTURE.md), M2/M6, [`10_TESTING_STRATEGY.md`](../../10_TESTING_STRATEGY.md) |

---

## 2. What was not captured, and what is in it

Listed so a future reader can judge whether to fetch it, rather than assuming it was considered and set aside.

| Source | Contents | Why skipped |
| --- | --- | --- |
| `config.example.yaml` (~30 KB) | The exhaustive worked configuration. Upstream calls it *"the most up to date reference for all example configurations"* and admits *"It has grown quite complex"* | **The highest-value uncaptured item.** [`config-schema.md`](config-schema.md) gives the keys and their semantics, which is what the plan's claims rest on; this file gives idiom and worked combinations. **Capture it before designing `tools.example.yaml`** |
| `docs/examples/` | Worked deployment examples | Same reason, lower density. Worth a look during M8 |
| `docs/grafana/` | Grafana dashboards for their `/metrics` | Relevant to **R1** and M7 if we build dashboards — [`deploy/grafana/`](../../../deploy/grafana) exists in this repo already |
| `internal/`, `proxy/`, `cmd/` (Go source) | The actual implementation: proxy manager, process supervision, group/matrix routers, the solver | **Deliberately not read.** We are borrowing semantics, not porting code, and it is MIT-licensed Go we have no intention of translating. The `matrix` solver is the one part where reading the source would be justified, *if* **gap G2** is ever taken up |
| `ui-svelte/` | The web UI | Our `/ui` is a status page (**R1**), not a playground. Their screenshots in [`readme.md`](readme.md) are enough to see the scope difference |
| `docker/`, `.goreleaser.yaml`, `Makefile` | Build and release plumbing for a Go binary | Not applicable; we ship a Python package and images |
| `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `.coderabbit.yaml` | Their contributor and agent instructions | No decision-bearing content |
| `ai-plans/` | Their AI-assisted planning notes | Not read. Possibly interesting as process comparison; irrelevant to design |
| GitHub issues referenced in the README (#36, #41, #58, #61, #235, #236, #327, #643, #1001) | Feature-request threads behind individual endpoints | Fetch individually if a specific behaviour needs its history. **#643** (the `matrix` DSL) is the one that would matter for **gap G2** |

---

## 3. Findings — where this capture corrects or updates the plan

**These are recorded here and nowhere else.** By explicit decision, the plan documents that carry the affected statements were **not edited**; a reader who follows a citation to this directory will find the correction, and the plan text stands as written. Anyone reopening the affected decisions should read this section first.

### F1 — "It manages processes, not containers" is stale

**Where the plan says it:**

- [`00_CONTEXT_AND_MOTIVATION.md`](../../00_CONTEXT_AND_MOTIVATION.md) §4, on llama-swap: *"Differences: it manages processes not containers, and assumes LLM/OpenAI endpoints, which ours are not."*
- [`14_ALTERNATIVES_EVALUATION.md`](../../14_ALTERNATIVES_EVALUATION.md) §3.1: *"What it does not do: manage containers with per-model environments (it spawns processes/commands)… **But note carefully** — a configured llama-swap command **can** be `docker run ...`. That single observation makes the following genuinely viable."*

**What the capture shows.** Container support is a headline feature, not a latent capability:

- [`readme.md`](readme.md), feature list: *"Docker and Podman support using `cmd` and `cmdStop` together"*.
- [`configuration.md`](configuration.md) carries a **complete worked example** — `docker run` with `--gpus '"device=2,3"'`, cache and model mounts, `-p ${PORT}:8000`, and `cmdStop: docker stop vllm-coder`.
- [`config-schema.md`](config-schema.md) §3: `cmdStop` is a first-class config key, *"Command to run to stop the model gracefully"*, added for this purpose.
- [`readme.md`](readme.md), closing section: *"For Python based inference servers like vllm or tabbyAPI it is recommended to run them via podman or docker. This provides **clean environment isolation** as well as responding correctly to `SIGTERM` signals for proper shutdown."*

**Assessment.** The observation §3.1 introduces as ours is upstream's documented, recommended practice — and their stated reason for it (*clean environment isolation* for Python inference servers) is **the reason behind D2**. The plan understates the overlap and, in doing so, understates how well-founded **D2** is.

**What it does not change.** Nothing. **D2** stands; if anything it gains an independent witness. ADR-0001 stands — see F2.

### F2 — Spike A's recorded reason is broader than the evidence supports

**Where the plan says it:** [ADR-0001](../../adr/0001-build-our-own-router.md) §Spike A: *"Reported outcome: llama-swap is built for LLMs and OpenAI-compatible endpoints only; we need custom models."* Echoed in [`README.md`](../../README.md) §2, [`HANDOFF.md`](../../HANDOFF.md), [`09_IMPLEMENTATION_PLAN.md`](../../09_IMPLEMENTATION_PLAN.md) and [`14_ALTERNATIVES_EVALUATION.md`](../../14_ALTERNATIVES_EVALUATION.md) §6.

**What the capture shows.** *"OpenAI-compatible endpoints only"* is true of the **request-dispatch path** and false of the rest of the product. Protocol-agnostic surfaces include `/upstream/:model_id`, `/running`, `/health`, `/metrics`, `/ui`, `/logs/stream/{model_id}`, `checkEndpoint` (*any* path or `none`), `env`, `metadata`, `concurrencyLimit`, `groups`, `ttl` and `hooks`. Roughly a third of the schema is LLM-specific ([`config-schema.md`](config-schema.md) §8); the swap machinery is not.

**The precise reason the rejection holds.** Model dispatch is driven by extracting `model` from a chat-completion request body — [`router-design-notes.md`](router-design-notes.md) confirms the implementation: *"Model extraction from JSON body, query string, and form bodies"*. Our contract is `POST /run/{tool}` with a JSON-Schema-validated input object (**D4**, **D13**), and there is no configuration by which their router learns to route it. Two further blockers, independent of the first: no batching contract to give a tool ([`05_RUNTIME_AND_BATCHING.md`](../../05_RUNTIME_AND_BATCHING.md), **D5**), and no schema surface to project into tool definitions (**D13**) — as [`configuration.md`](configuration.md) §2 puts it, *a `cmd:` string cannot be introspected by an LLM.*

**Assessment.** **The verdict stands; the stated reason is imprecise and the imprecision is load-bearing** — it makes the rejection sound like a property of their scope rather than of their dispatch model, which invites the reasonable-sounding rebuttal *"but they support any server, and `/upstream/` proxies anything"*. The accurate one-line form: **llama-swap routes by `body.model` on generative-API paths; our tools are addressed by path with typed bodies, and their config has no way to express that.**

### F3 — Features that post-date Spike A and land on open decisions

Spike A predates this capture and the schema has moved. Recorded as **design input**, explicitly **not** as grounds to reopen ADR-0001 (F2 is why).

| Feature | What it is | Where it lands |
| --- | --- | --- |
| `matrix` + `evict_costs` | A constraint solver over legal concurrent-model combinations that *"minimizes eviction cost when swapping"*, with per-model relative eviction costs | **D25** names preemption but not victim selection; [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../../06_LIFECYCLE_TTL_AND_SCHEDULING.md) uses LRU. **Gap G2** |
| `routing.scheduler` (FIFO + `priority`) | *"Decides the order in which queued requests are serviced"*, with per-model integer priority, *"Higher values are serviced first"* | Our queue (**D22**) is implicitly FIFO with no priority. **Gap G3** |
| `unloadTimeout` | Graceful stop, default 10s, before force-kill — global and per-model | [ADR-0004](../../adr/0004-hard-stop-only-in-v1.md) makes hard stop our only path and **names no grace period**. **Gap G1** |
| `concurrencyLimit` | Per-model in-flight cap, default 10, **429** beyond it | **D22** covers cold-start queueing only, not a saturated `READY` tool. **Gap G4** |
| `peers` | Static federation to another llama-swap or any compatible server | An unpriced alternative to Kubernetes at the *"second GPU host"* trigger ([`14_ALTERNATIVES_EVALUATION.md`](../../14_ALTERNATIVES_EVALUATION.md) §8.6) |
| `groups.exclusive` / `.persistent` | Cross-group relations — one group's activity unloads others; a group protected from others' eviction | We have `max_resident` within a group and no cross-group vocabulary |
| `profiles`, `selectors` | Runtime model-ID rewriting; virtual IDs with `warm`/`pin`/`spillover` strategies | **Not applicable.** Both resolve `body.model`, which we do not have |

All five gaps are written up as questions, not proposals, in [`17_LLAMA_SWAP_PHILOSOPHY.md`](../../17_LLAMA_SWAP_PHILOSOPHY.md) §5.

### F4 — `checkEndpoint` shows readiness is delegated there and cannot be here

[`config-schema.md`](config-schema.md) §3: `checkEndpoint` defaults to `/health`, accepts any path or `none`, and is polled until it answers, bounded by `healthCheckTimeout` (default **120s**).

llama-swap's readiness model is **delegated** — the upstream decides what ready means, and for `llama-server` a 200 genuinely implies weights mapped. We cannot delegate, because we generate the server: BentoML's `/readyz` answers before `load()` runs ([`../bentoml/health-endpoints-and-lifecycle-source.md`](../bentoml/health-endpoints-and-lifecycle-source.md)), which is precisely the R8 defect [`05_RUNTIME_AND_BATCHING.md`](../../05_RUNTIME_AND_BATCHING.md) §3.2 exists to correct.

**Not a correction — a confirmation, and a capability we have that they do not.** Their check is a poll for any 200; ours returns a **reason** while not ready. Their 120s default is also a useful sanity check on our cold-start bound (**D22**).

---

## 4. Rules of use, and how to re-verify

The directory-wide rules in [`../README.md`](../README.md) apply — snapshots not truth, no editing captured prose, corrections go in the notes sections. Three additions specific to this capture:

1. **Everything here was read from `main`, not from the `v249` tag.** [`router-design-notes.md`](router-design-notes.md) is the acute case: it describes an **incomplete migration** whose cutover phase is still open, so the architecture it describes is *not* what v249 ships. Never cite it as released behaviour.
2. **They release very frequently** — 249 tagged releases, with nightly container builds. A capture six months old should be assumed stale on anything behavioural. Re-verify with:
   ```
   curl -s https://api.github.com/repos/mostlygeek/llama-swap/releases/latest | jq -r .tag_name
   curl -s https://raw.githubusercontent.com/mostlygeek/llama-swap/main/config-schema.json
   ```
   If the tag has moved, diff the schema before trusting §3 of any file here.
3. **This is a live sibling service, not only a reference.** llama-swap serves our LLMs in the same deployment ([`04_API_CONTRACT.md`](../../04_API_CONTRACT.md) §0), and the M8 integration test feeds `?format=tools` to a model served by it ([`09_IMPLEMENTATION_PLAN.md`](../../09_IMPLEMENTATION_PLAN.md)). A breaking change upstream is an operational event here, not merely a stale document.

**Licence and attribution.** llama-swap is MIT-licensed, © the llama-swap authors. The captured prose and configuration examples are reproduced for internal technical evaluation and retain their original authorship. No source code has been copied into this repository.

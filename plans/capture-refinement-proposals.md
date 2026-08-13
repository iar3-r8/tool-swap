# Plan refinement from the BentoML and llama-swap captures — numbered proposals

**Status:** ✅ **Approved and fully applied (2026-08-13).** Every item below is now in `plan/`; this file is the decision record, not a work list.

**What landed, in one table:**

| Artefact | Change |
|---|---|
| **[ADR-0005](../plan/adr/0005-one-uniform-batched-calling-convention.md)** *(new)* | One uniform calling convention. Re-scopes **D15** |
| [`01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md) | `IDLE_SOFT` purged from the state machine; §7.1 shutdown ordering; the `Router`-decomposition citation |
| [`02_CONFIGURATION.md`](../plan/02_CONFIGURATION.md) | `soft_ttl` reserved-and-rejected; TTL sentinels; `evict_cost`; `max_concurrent`; `60000` re-attributed; `batchable:` removed |
| [`03_TOOL_AUTHORING.md`](../plan/03_TOOL_AUTHORING.md) | **§6.1 non-root images** (G5); §3.1 rewritten around one convention; `unload()` back to advisory |
| [`04_API_CONTRACT.md`](../plan/04_API_CONTRACT.md) | `/unload` out of v1; one schema shape; `STOPPED` on VRAM contention |
| [`05_RUNTIME_AND_BATCHING.md`](../plan/05_RUNTIME_AND_BATCHING.md) | **The largest edit.** §3.3 `__is_ready__`, §4.3–4.5 rewritten, §6.1 the M4 trap, §9 metrics corrected, the real dependency constraints |
| [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../plan/06_LIFECYCLE_TTL_AND_SCHEDULING.md) | **A live soft-unload spec deleted** (ADR-0004 had never been propagated here); §2.1 grace period; §5.1.1 `evict_cost`; §5.1.2 policy seam; §10 back-pressure |
| [`07_CLI_AND_OPS.md`](../plan/07_CLI_AND_OPS.md) | §2.1 `log_output`; logs for a `STOPPED` tool; runbook rows corrected |
| [`08`](../plan/08_REPO_LAYOUT.md) · [`09`](../plan/09_IMPLEMENTATION_PLAN.md) · [`10`](../plan/10_TESTING_STRATEGY.md) | Pin policy; M2/M3.5/M4/M5/M6/M7/M9; ordering, log-routing and non-root tests |
| [`00`](../plan/00_CONTEXT_AND_MOTIVATION.md) · [`14`](../plan/14_ALTERNATIVES_EVALUATION.md) · [ADR-0001](../plan/adr/0001-build-our-own-router.md) | llama-swap staleness corrected; Spike A's precise reason; `peers` priced at §8.6 |
| [`13`](../plan/13_OPEN_QUESTIONS.md) · [`README`](../plan/README.md) · [`16`](../plan/16_COMPLEXITY_AUDIT.md) · [`17`](../plan/17_LLAMA_SWAP_PHILOSOPHY.md) | D14/D15 updated; audit §3.2 second round; the five gaps marked settled |
| Both capture INDEXes · [`third-party-docs/README.md`](../plan/third-party-docs/README.md) | Findings marked **applied** with destinations; rule 2 amended per **P0** |

**One thing found that was not in any capture:** [`06 §3`](../plan/06_LIFECYCLE_TTL_AND_SCHEDULING.md) still carried a **complete, live soft-unload specification** — state diagram, soft sweep, `SOFT_UNLOAD_THEN_GRANT`, `can_soft_unload` on the snapshot — contradicting its own header. [ADR-0004](../plan/adr/0004-hard-stop-only-in-v1.md) was never fully propagated. That is now fixed, and it was the single largest correctness risk in the plan.
**Inputs:** [`third-party-docs/bentoml/`](../plan/third-party-docs/bentoml/INDEX.md) (BentoML 1.4.39) and [`third-party-docs/llama-swap/`](../plan/third-party-docs/llama-swap/INDEX.md) (llama-swap v249), both captured 2026-08-13.
**Brief:** *"Bentoml will give more cues on how to simplify features that are already implemented and llama-swap will provide a philosophy to follow."*

Each proposal was **approve / reject / defer**. Tiers A and B move no decision; tiers C and D do.

## Verdicts

| Item | Verdict |
|---|---|
| **P0** — reverse the "captures do not edit the plan" convention | ✅ **Approved** — *"the goal of this exercise is to improve the plan"* |
| **A1–A10** — corrections | ✅ Approved as a block |
| **B1–B6** — simplifications | ✅ Approved |
| **C1 (G5)** non-root tool images · **C2 (G4)** saturation · **C3 (G1)** grace period · **C5 (G3)** scheduler seam | ✅ Approved |
| **C4 (G2)** eviction cost | ✅ Approved **cheap version only** — one integer weight in an LRU tie-break; the solver and its DSL are explicitly refused |
| **D-P1** — D15 | ✅ **Approved, and widened — see the revised proposal below.** *"We need to keep the most consistent and simple API; if it's simpler to have everything batched then let's make it batched. We strive for simplicity here."* |
| **D-P2** — D19 vs the three-line config | ✅ **D19 kept, unchanged and hard-failing** — *"vital for creating a tool with proper description."* `tswap new` pre-fills descriptions so the first rung never hits the error |
| **D-P3** log routing · **D-P4** `peers` · **D-P5** `Router` shape | ✅ Approved |

**The governing principle for the whole application pass, in the requester's words: *"We strive for simplicity here."*** Where a finding offers two ways to be correct, take the one with fewer concepts on the authoring surface.

---

## P0 — The convention this whole exercise reverses (approve first, or the rest is moot)

Both captures **deliberately did not edit the plan**. [`llama-swap/INDEX.md`](../plan/third-party-docs/llama-swap/INDEX.md:48) §3: *"By explicit decision, the plan documents that carry the affected statements were **not edited**"*. [`bentoml/INDEX.md`](../plan/third-party-docs/bentoml/INDEX.md:114) §4 lists 11 amendments as *"Recorded for deliberate decision… No plan document was edited."* Rule 2 of [`third-party-docs/README.md`](../plan/third-party-docs/README.md:36) sends corrections to the notes sections, not to `plan/`.

**P0 — Reverse that stance for these findings.** Apply the approved items *in* `plan/`, and change each capture's §3/§4 entry from "proposed, not applied" to "applied, see <doc>". The captures stay the evidence base; they stop being a parallel, contradicting copy of the plan.

**Why it matters:** [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md:167) §7 already names documentation drift as *"the next-biggest risk"* and records that three documents had drifted into three versions of the Ray decision. Fifteen unapplied findings sitting beside the documents they contradict is that same defect, pre-loaded.

> ⚠️ If P0 is rejected, tiers A–D collapse to "write more notes in the captures", and the plan keeps saying things the evidence base says are false.

---

## Tier A — Corrections. No decision moves; these are things the plan gets wrong.

| # | Correction | Evidence | Where |
|---|---|---|---|
| **A1** | `POST /unload` is still listed as *"**v1** — the default reclamation mechanism on the shared node"*, and the §6 sequence diagram still shows soft unload as *"the normal idle path"*. **ADR-0004 removed both.** | [ADR-0004](../plan/adr/0004-hard-stop-only-in-v1.md) | [`05 §3.1`](../plan/05_RUNTIME_AND_BATCHING.md:152), [`05 §6`](../plan/05_RUNTIME_AND_BATCHING.md:291) |
| **A2** | `defaults.soft_ttl: 300` is still shipped in the reference config, annotated *"The default reclamation path on a shared node."* **D9 says `soft_ttl` is reserved and rejected.** | [ADR-0004](../plan/adr/0004-hard-stop-only-in-v1.md), [`README §4 D9`](../plan/README.md:122) | [`02 §3`](../plan/02_CONFIGURATION.md:78) |
| **A3** | *"Locked pins (pydantic, starlette, click)"* appears in **five** documents. In 1.4.39 those are `pydantic<3` (upper bound only), `starlette>=0.24.0` and `click>=7.0` — **lower bounds cannot conflict**. The real constraints are `cattrs<23.2.0,>=22.1.0`, a seven-package OpenTelemetry family pinned to a **beta** series, and `fsspec>=2025.7.0`. M3.5 step 1 currently instructs the spike to measure the three least informative packages. | [`dependency-constraints.md`](../plan/third-party-docs/bentoml/dependency-constraints.md) | [`05 §1.1`](../plan/05_RUNTIME_AND_BATCHING.md:42), [`09 M3.5`](../plan/09_IMPLEMENTATION_PLAN.md:129), `13`, `08 §3`, `00 §4` |
| **A4** | `tswap_queue_wait_seconds` is attributed to the *"BentoML dispatcher"*. **No such metric exists.** BentoML gives `request_in_progress`, `request_total`, `request_duration_seconds`, `adaptive_batch_size`. Queue wait is the key diagnostic for tuning `max_wait_ms` — measure it above the seam or drop the promise. | [`metrics.md`](../plan/third-party-docs/bentoml/metrics.md) | [`05 §9`](../plan/05_RUNTIME_AND_BATCHING.md:357) |
| **A5** | `max_latency_ms = 60000` is called *"a nonsensical 60000"* chosen by R8. **It is BentoML's own default**, inherited by every tool that does not override it. The conclusion strengthens; the attribution is wrong. | [`sdk-reference.md`](../plan/third-party-docs/bentoml/sdk-reference.md) | [`02 §7`](../plan/02_CONFIGURATION.md) |
| **A6** | R8's `gpu_id = max(0, worker_index - 1)` is called *"fragile and off-by-one-prone"* in two documents. It is **the vendor's documented idiom with an added guard** — and the vendor documents the index as both 0-based and 1-based, three paragraphs apart. The design conclusion (pass an explicit device list) stands; the criticism should become *"do not build device identity on a framework's indexing convention"*. | [`workers-and-devices.md`](../plan/third-party-docs/bentoml/workers-and-devices.md) | [`12 §5`](../plan/12_REFERENCE_CODE.md), [`06 §7`](../plan/06_LIFECYCLE_TTL_AND_SCHEDULING.md) |
| **A7** | *"The order of the requests in a batch is not guaranteed"* is **documented vendor behaviour**. The testing strategy must assert attribution and never submission order, and say so, or the first interleaved-arrival test reads as a flake. | [`adaptive-batching.md`](../plan/third-party-docs/bentoml/adaptive-batching.md:37) | [`10_TESTING_STRATEGY.md`](../plan/10_TESTING_STRATEGY.md) |
| **A8** | *"It manages processes, not containers"* is **stale**: Docker/Podman support is a headline llama-swap feature, with a worked `docker run` + `cmdStop` + `--gpus` example, and their stated reason is *"clean environment isolation"* for Python inference servers — **which is D2's reason**. Separately, Spike A's recorded reason (*"LLM/OpenAI endpoints only"*) is broader than the evidence: about a third of their schema is LLM-specific, the swap machinery is not. **Both verdicts stand**; the reasons are wrong in a load-bearing way. Accurate form: *llama-swap routes by `body.model` on generative paths; our tools are addressed by path with typed bodies, and their config cannot express that.* | [`llama-swap/INDEX.md`](../plan/third-party-docs/llama-swap/INDEX.md:50) F1, F2 | [`00 §4`](../plan/00_CONTEXT_AND_MOTIVATION.md), [`14 §3.1`](../plan/14_ALTERNATIVES_EVALUATION.md), [ADR-0001](../plan/adr/0001-build-our-own-router.md) |
| **A9** | **The M4 trap.** BentoML's `lifespan` awaits `create_instance` — which runs `__init__` — **before the socket accepts connections**. If M4 loads the handler in `__init__` or an `on_startup` hook, a four-minute load yields *connection refused*, not `503 reason: loading`: `/health` cannot answer, `LOADING` becomes unobservable, two contract tests become untestable, and a load failure exits the process instead of exposing a traceback. **Bind-then-load is mandatory, not stylistic** — and R8's background warm-up thread was correct, not a quirk. | [`health-endpoints-and-lifecycle-source.md`](../plan/third-party-docs/bentoml/health-endpoints-and-lifecycle-source.md:310) §4 | [`05 §6`](../plan/05_RUNTIME_AND_BATCHING.md:299), [`09 M4`](../plan/09_IMPLEMENTATION_PLAN.md:152) |
| **A10** | Four smaller adapter facts, each cheap now and painful in M4: **(a)** BentoML replaces the body of **any ≥500 response** with a generic string, so `/predict` must not encode meaning in status alone; **(b)** `/metrics` is registered **only if metrics are enabled** — the adapter must enable it rather than assume; **(c)** setting `path_prefix` moves the system routes, the API routes *and our mounted contract routes* together — **the adapter must not set it**; **(d)** BentoML already serves `/schema.json`; ours is `/schema`. Five characters apart, unrelated payloads — contract tests must assert content, not shape. | [`error-handling.md`](../plan/third-party-docs/bentoml/error-handling.md), [`health-endpoints-and-lifecycle-source.md`](../plan/third-party-docs/bentoml/health-endpoints-and-lifecycle-source.md:372) | [`04 §6`](../plan/04_API_CONTRACT.md), [`09 M4`](../plan/09_IMPLEMENTATION_PLAN.md:154) |

**Recommendation: approve A1–A10 as a block.** None changes a decision; A1 and A2 are documents contradicting a settled ADR, and A3/A9 would cost real time in M3.5/M4.

---

## Tier B — Simplifications. Work the plan budgets for that BentoML or llama-swap already does.

This is the half of the brief that says *"simplify features that are already implemented."*

| # | Simplification | What it deletes | Evidence |
|---|---|---|---|
| **B1** | **`metrics={"namespace": "tswap"}`** renames BentoML's whole default metric set. Most of [`05 §9`](../plan/05_RUNTIME_AND_BATCHING.md:350)'s table arrives free; add `request_in_progress` (an in-flight gauge we were going to build). | Custom metric plumbing for 3 of 7 rows | [`metrics.md`](../plan/third-party-docs/bentoml/metrics.md) |
| **B2** | **Wire `__is_ready__` / `__is_alive__`** to the same readiness state our `/ready` reads. Three lines. Makes `/readyz` truthful for anyone bypassing our contract — a `docker run` user, a `curl`, a future k8s probe — which is guardrail 11's standalone promise. **One readiness fact with two projections instead of two facts that can disagree.** ⚠️ Undocumented hooks read from `main`: a *bonus*, never the mechanism we depend on. | Nothing, but closes a divergence class | [`health-endpoints…`](../plan/third-party-docs/bentoml/health-endpoints-and-lifecycle-source.md:292) §3 |
| **B3** | **Drop our own handler lock.** [`05 §5`](../plan/05_RUNTIME_AND_BATCHING.md:253) rule 2 says *"Serialise with a lock"*; BentoML dispatches every sync API call through a single `anyio.CapacityLimiter(threads)` with **`threads` defaulting to 1**. Our design and the framework already agree — the lock is redundant. **But the adapter must set `threads` explicitly and M3.5 must report it**, or a spike firing 32 concurrent requests measures the wrong thing and reads as a batching failure. | One lock, and a subtle deadlock surface | [`health-endpoints…`](../plan/third-party-docs/bentoml/health-endpoints-and-lifecycle-source.md:339) §5 |
| **B4** | **`keep_warm` = a synthetic request through the ordinary path.** llama-swap's `startPreload` *"fires a background `GET /` at each preload model"* — no separate warm-up code path. Slot acquisition, readiness polling, state transitions and failure accounting all come free and **cannot drift**. This is [`D24`](../plan/README.md:141)'s own argument against `tswap exec`, applied to M6. | A second warm-up path in M6 | [`router-design-notes.md`](../plan/third-party-docs/llama-swap/router-design-notes.md:110) |
| **B5** | **Specify shutdown ordering**, which no document does: drain in-flight HTTP **before** tearing down containers, *"otherwise inflight requests 502."* Ours is harder than theirs — a request may be **queued behind a cold start** (D22), so "drain" has two meanings and one of them needs a decided answer. | An unwritten paragraph that becomes flaky integration tests | [`router-design-notes.md`](../plan/third-party-docs/llama-swap/router-design-notes.md:118) §4 |
| **B6** | **Copy the sentinel discipline** for `ttl`: llama-swap uses `-1` inherit / `0` never / `>0` seconds, explicitly named in the schema. Ours has `ttl: 0 = never` and a separate `defaults.ttl`, with no stated inherit sentinel. Free consistency. | Ambiguity, not code | [`config-schema.md`](../plan/third-party-docs/llama-swap/config-schema.md:57) |

**Recommendation: approve B1–B6.** B3 and B4 are the two that actually remove code we planned to write.

---

## Tier C — The five llama-swap gaps. Each needs a verdict; G5 is due before M5.

Written as questions in [`17 §5`](../plan/17_LLAMA_SWAP_PHILOSOPHY.md:217). My recommendation is attached to each.

### **C1 (G5) — Do tool containers run as root?  ⚠️ Sharpest item in this document.**

Nothing in the plan specifies a `USER` for tool images. Meanwhile **D11** grants network access precisely so tools can call `from_pretrained()` and `torch.load()` against arbitrary Hugging Face repos, and `.bin` checkpoints are **pickles that execute on load**. A root container, mounting the shared HF cache, deserialising a pickle from the internet, **on a shared DGX where other people's work lives**, is the sharpest edge in the design.

llama-swap ships root by default *"for convenience"* with `non-root` variants and an explicit privilege-escalation warning — but their users are on personal machines. Ours are not. The plan makes the **stability** half of the blast-radius argument (D2) and omits the **security** half.

**Proposal:** a `USER` line in the generated base images, the HF cache mounted read-only where the tool does not download, and a `safetensors` recommendation in the authoring guide.
**Cost:** three small things. **Nearly free before M5, awkward after** — changing `USER` later invalidates every author's assumptions about file ownership. **Recommend approve, scheduled into M5.**

### **C2 (G4) — What does a saturated but `READY` tool do?**

`max_queue_depth` bounds the **cold-start queue**; it never engages for a `READY` tool receiving more than it can serve. Left unowned, the answer arrives as BentoML's `ServiceUnavailable("process is overloaded")` — **a 503 whose message is stripped on the way out** (A10a). The caller sees an unexplained 503 identical to *"the tool is starting"*, and **D28** is precisely about not misattributing failures.

**Proposal:** the adapter catches `ServiceUnavailable` and re-emits it in our envelope with a distinct `reason` (saturation ≠ cold start); the router adds an optional per-tool concurrency cap returning **429**, matching llama-swap's `concurrencyLimit` (default 10). **Recommend approve the adapter half unconditionally; the router cap is the part to debate.** Due before M4.

### **C3 (G1) — Grace period before force-kill.**

Already solved and **better than theirs** — in-flight requests block eviction entirely (`inflight > 0` is never evicted), then `drain_timeout` 30s → SIGTERM → `stop_timeout` 30s. Theirs is a flat 10s `unloadTimeout` that force-kills mid-inference.

**Three checks, not a decision:** (1) confirm `drain_timeout` survives ADR-0004, which rewrote the reclamation path around hard stop while [`01 §5.1`](../plan/01_ARCHITECTURE.md) predates it; (2) sanity-check 30s+30s against a tool whose *single* inference takes 90 seconds; (3) say it in the lifecycle document, where a reader looks for it. **Recommend approve — it is a cross-reference and a sentence.**

### **C4 (G2) — When several tools are evictable, which one goes?**

LRU assumes comparable cold starts. **Ours differ by orders of magnitude** — a CPU function restarts in under a second, a large segmenter takes ninety — so evicting the expensive one because it idled marginally longer is a bad trade that will happen routinely.

llama-swap's answer is a solver over declared legal combinations with `evict_costs`, *"minimizes eviction cost when swapping"* — **and it needs a DSL (`&`, `|`, `()`, `+ref`), an 8-character `vars` indirection table and a constraint solver.** That is the clearest illustration in the capture of what R4 costs when scheduling expressiveness wins.

**Proposal — the cheap version only:** one optional per-tool integer weight, breaking ties in an otherwise-LRU comparator. Captures nearly all the benefit for one config key. **Recommend approve the cheap version, explicitly refuse the solver.** Policy only, before M6.

### **C5 (G3) — Do queued requests have a priority?**

FIFO puts an interactive request behind a batch job. llama-swap has `routing.scheduler.use: fifo` with per-model integer priority.

**Proposal: adopt the seam, refuse the feature.** Priority is where schedulers acquire starvation bugs, and [`16 §5`](../plan/16_COMPLEXITY_AUDIT.md:137) names scheduler purity as never-trim. But their `scheduler.use` **enum shape** means a second policy is a new implementation rather than a rewrite — the same seam as `ContainerBackend` and `RuntimeBackend`. **Recommend approve: an interface boundary, no feature.** Cheapest before M2.

---

## Tier D — Decisions that actually move. These are the ones to argue about.

### **D-P1 — Narrow D15.  ⚠️ Changes the API surface, not just internals.**

**D15** forbids a batched tool from declaring any non-batchable input, pushing every per-request knob into **static params fixed at load time**. The constraint behind it is real and confirmed: *"A batchable API endpoint only accepts one parameter in addition to `bentoml.Context.`"*

**But BentoML documents a second remedy, and its example is literally ours — `image: Path` plus `threshold: float`.** Group the parameters into a Pydantic model and make *that* the batched element; each item then carries its own `threshold`.

| Kind of parameter | Per-request under BentoML? |
|---|---|
| Post-processing knobs — `threshold`, top-k, NMS IoU, output format | **Yes**, carried per item, applied per item after the batched forward pass |
| Parameters changing the batched computation — input resolution, dtype, a different head, window size | **No** — D15's static-param remedy is right |

**D15 is over-broad as written**: correct for row two, unnecessarily restrictive for row one, which is probably the commoner case in our zoo.

**Cost of adopting:** the documented pattern needs a **wrapper Service via `bentoml.depends`** — two Services and an extra hop. That is exactly the framework accommodation [`03`](../plan/03_TOOL_AUTHORING.md:151) insists must never reach the author, so **our adapter would generate it** and `handler.py` would still see a plain list of typed items.
**Cost of not adopting:** every post-processing knob becomes a second config entry and a second resident model.

### ✅ Verdict — **approved, and widened: one uniform batched path**

The requester rejected *both* options I offered, in favour of a third that is simpler than either: **stop having two kinds of tool.**

> *"We need to keep the most consistent and simple API, if its simpler to have everything 'batched' then lets make it batched. We strive for simplicity here."*

**The rule this becomes:** every tool's handler receives a **list of typed items** and returns a list of the same length, always. `batching.enabled: false` stops meaning *"a different calling convention"* and starts meaning only *"`max_batch_size: 1`"*. Per-request knobs are **fields of the item**, so they are per-item by construction and D15's silent-misattribution hazard cannot arise — two items with different thresholds each carry their own. `params:` survives only for values that are genuinely per-deployment (a model head, a weights path).

**What this deletes**, which is why it is the better answer:

| Before | After |
|---|---|
| Two calling conventions (`scalar_inputs: true` vs lists) | **One.** [`05 §4.4`](../plan/05_RUNTIME_AND_BATCHING.md:242) already called lists-of-1 the default; this finishes the job and drops the exception |
| Two input classes on the authoring surface (`inputs:` + `params:`) with a rule for choosing | **One**, plus a narrow, well-motivated `params:` |
| A `validate` rule rejecting non-batchable inputs on batched tools (D15's hard error) | **Unnecessary** — the state is unrepresentable, not detected |
| Two `/schema` and `?format=tools` shapes depending on batching | **One** |

**One open question, for M3.5 to measure rather than for us to assume.** I claimed above that this costs a generated two-Service topology via `bentoml.depends`. **On re-reading the capture, that is probably wrong**: the wrapper Service exists in BentoML's docs to expose a *non-list, multi-parameter* API to clients. Our `/predict` contract is ours, and the dispatcher concatenates the lists arriving from separate HTTP requests — so posting a list of one may need no wrapper at all. **M3.5 step 5 must establish this before M4 builds on it.** If a wrapper does turn out to be needed, the adapter generates it and `handler.py` never sees it.

**Consequence for D15:** it is no longer a restriction on what a batched tool may declare; it becomes a note that parameters changing the batched computation itself (input resolution, dtype, a different head) belong in `params:`. **This needs an ADR**, since D15 changes meaning rather than wording.

### **D-P2 — D19 versus the three-line config.**

[`17 §1`](../plan/17_LLAMA_SWAP_PHILOSOPHY.md:48) says the one thing to steal above all others is **the three-line config that works** — llama-swap has over a hundred keys and **exactly one required**. **D19** makes descriptions mandatory for the tool and every input, hard-failing `validate`.

These are in tension only at the first rung of the ladder: a scientist trying the smallest possible tool hits a hard error about prose. But **D19 exists because `?format=tools` is only as good as the prose inside it**, and an undescribed parameter is one an LLM fills in wrongly.

**Options:** (a) keep D19 as-is and make `tswap new` pre-fill descriptions so the first rung never hits the error; (b) demote to a warning at authoring time, hard-fail in `preflight --strict` and CI; (c) no change.

### ✅ Verdict — **(a). D19 stands, hard-failing, unchanged.**

> *"We keep D19 as this is vital for creating a tool with proper description."*

The tension is resolved on the tooling side only: `tswap new` emits description placeholders, so the three-line promise is kept by the template rather than by weakening the rule. **No decision moves.**

### **D-P3 — Adopt `logToStdout`-style log routing, and test it.**

Their router rewrite found **seven defects after all functional phases were marked complete, five of them logging** — including a config key that silently did nothing and a `/logs` endpoint that was *"always empty"*, in reviewed, tested code.

Two consequences: **(1)** *"Observability regressions are invisible to functional tests"* — nothing 500s when logs go missing, and **R1** is *"simple to launch the service and check its logs and status"*, so a silent logging failure is a **requirement failure, not a cosmetic one**. [`10_TESTING_STRATEGY.md`](../plan/10_TESTING_STRATEGY.md) should assert that `tswap logs {tool}` returns that tool's lines. **(2)** Their gap 2 — per-model streaming, lost because it needs a model ID resolved against live process state — is exactly our `tswap logs {tool} -f`, and [`07`](../plan/07_CLI_AND_OPS.md) does not say what happens for a `STOPPED` tool. Theirs returned 400.

**Proposal:** adopt their `proxy | upstream | both | none` four-way switch as the config surface (a cleaner statement of the same choice than per-tool file toggles), and add the two log-routing assertions to the testing strategy. **Recommend approve.**

### **D-P4 — Record `peers` as a third growth path, ahead of Kubernetes.**

[`14 §8.6`](../plan/14_ALTERNATIVES_EVALUATION.md) names *"a second GPU host"* as the trigger to reconsider Kubernetes. llama-swap has `peers`: **static federation** — a second host runs its own instance and the first forwards tools it does not own, over the proxy we already have. No cluster, no control plane, no scheduler rewrite — **and no cross-host scheduling either**, which is the expensive feature.

Not v1, not a recommendation. **Proposal: price it in §8.6 before the trigger fires**, so the answer to "second host" is not reflexively Kubernetes. **Recommend approve as one paragraph.**

### **D-P5 — Copy the `Router` interface shape with one implementation.**

Their rewrite exists because *"the legacy `ProxyManager` collapses three concerns into one struct"*, and their standing warning is *"preserve that abstraction rather than reintroducing the branch in every handler"* — i.e. what happens when scheduling policy leaks into request handlers, the exact failure [`16 §5`](../plan/16_COMPLEXITY_AUDIT.md:137) never-trim item 2 guards. **We have the warning before writing the code; they got it after writing it twice.** Convergent evidence for seams we already drew — recommend citing it in [`01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md) rather than changing anything. **Recommend approve as a citation.**

---

## Summary

| Tier | Items | Decisions moved | Verdict |
|---|---|---|---|
| **P0** | 1 | the capture convention | ✅ Approved |
| **A** | A1–A10 | none | ✅ Approved as a block |
| **B** | B1–B6 | none | ✅ Approved — B3, B4 delete planned work |
| **C** | C1–C5 (G1–G5) | scheduling/security policy | ✅ Approved; **C4 cheap version only** |
| **D** | D-P1…D-P5 | **D15 (widened)**, logging, `14 §8.6`, `01` | ✅ Approved; **D19 unchanged** |

**Net effect on the decision log:** **D15 changes meaning** (an authoring restriction becomes a uniform calling convention) and needs an ADR. **D19 is untouched.** No other D-number moves — everything else is a correction, a simplification, or a policy detail inside an existing decision.

**Sequencing note.** Nothing here touches M0, which is in flight on `bugfix/m0-completion` ([issue #1](https://github.com/iar3-r8/tool-swap/issues/1)). The earliest binding item is **C5 (before M2)**, then **A9/A3 (before M3.5)**, **C2 (before M4)**, **C1 (before M5)**, **C3/C4 (before M6)**.

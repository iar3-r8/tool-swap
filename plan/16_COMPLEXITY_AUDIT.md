# 16 — Complexity Audit

> **The question this document answers:** *"Are we building a complex stack for the fun of it?"*
>
> Not "is each decision defensible" — they nearly all are, individually. The question is whether the **total** is proportionate to what was actually asked for, and whether any part of it is complexity we chose rather than complexity the problem forced on us.
>
> Written after [ADR-0004](adr/0004-hard-stop-only-in-v1.md), which is itself the largest finding of this audit and is therefore already applied throughout.

---

## 1. The method, and why it is not "score every decision equally"

Every decision in [`13_OPEN_QUESTIONS.md`](13_OPEN_QUESTIONS.md) Part A has a rationale attached, and reading them one at a time produces agreement with all of them. That is exactly how a plan accumulates more than it needs: **each increment is justified against the previous state, and nobody ever sums the column.**

So each decision is scored on three axes, and only the third is new:

| Axis | Question |
|---|---|
| **Class** | Is this **forced** by a stated requirement, **chosen** as one of several valid answers, or **elective** — something we decided we wanted? |
| **Demand** | Who asked for this, in what words? A quotable requirement, an inferred one, or none? |
| **Carrying cost** | What does it cost *forever* — a config key, a state in the machine, a test suite, a dependency, an operational failure mode? |

**The rule applied throughout:** an *elective* decision answering an *inferred* demand at *high* carrying cost is the pattern to hunt. That is precisely what soft unload was.

---

## 2. Headline findings

1. **The largest single block of avoidable complexity was soft unload, and it is now removed** ([ADR-0004](adr/0004-hard-stop-only-in-v1.md)). It was elective, answered an inferred demand, and cost a state, an endpoint, a scheduler decision variant, a tool classification, a GPU-only preflight stage and four decisions (**D26**, **D27**, **D28** plus half of **D9**).
2. **The router itself is not the problem.** After the descope, the core is a config loader, a container backend, a pure scheduler of a few hundred lines, a proxy and a watchdog. That is proportionate, and the alternatives cost more (§6).
3. **Two further items are recommended for deferral** (§4): the `?format=tools` projection's *timing*, and the CLI's long tail. Neither is wrong; both are early.
4. **Three things must not be simplified**, and the audit says so explicitly (§5), because a complexity audit that only ever subtracts is as unbalanced as a plan that only ever adds.
5. **The plan's real risk is not over-engineering, it is over-documentation.** Sixteen planning documents, four ADRs and ~29 decisions for a service whose v1 is perhaps 4,000 lines. §7 addresses this directly, since it is a maintenance burden like any other.

---

## 3. The decision log, scored

**Class:** ⬛ forced · ⬜ chosen · ⚠ elective
**Verdict:** ✅ keep · ⏸ defer · ❌ cut · ↩ already changed

| # | Decision | Class | Demand | Carrying cost | Verdict |
|---|---|---|---|---|---|
| **D1** | Name `tool-swap`, CLI `tswap` | ⬜ | none needed | none | ✅ |
| **D2** | **One container image per tool** | ⬛ | *"the environment of each tool should be easy to set up"* + ~300 conflicting pins observed | Image builds, disk, cold start | ✅ **The load-bearing decision.** Everything else exists to make this usable. |
| **D3** | Graduated authoring ladder (5 rungs) | ⬜ | **R2**, *"scientists, not Docker engineers"* | Dockerfile generation per level, 4 templates | ✅ but see §4.3 — the ladder is the product; the rung *count* is negotiable |
| **D4** | Normalized API + transparent proxy, no OpenAI layer | ⬛ | **R3** | 10 endpoints | ✅ **Deleting the OpenAI layer was itself a good descope.** |
| **D4b** | Exactly one kind of tool | ⬜ | none — a simplification | *negative cost*: removes `kind:`, `mapping:`, a whole caveat class | ✅ Model example of the right instinct |
| **D5** | Micro-batching in the container | ⬛ | *explicitly requested*; the GPU-efficiency premise | Batch attribution correctness burden | ✅ |
| **D6** | User-authored tools | ⬛ | **R2** | Everything in **D17** | ✅ |
| **D7** | Pinned devices + groups | ⬜ | needed by **D2** on finite GPUs | `groups` config block | ✅ **Deliberately the simple answer.** Explicitly refuses VRAM prediction. |
| **D8** | CLI over docker compose | ⬜ | **R1** | Compose file + CLI | ✅ |
| **D9** | ~~Soft unload as default~~ **hard stop only** | ⚠→⬛ | **inferred** from *"shared DGX"*; the requester later said *"not so critical"* | Was: a state, an endpoint, a decision variant, 4 decisions | ↩ **[ADR-0004](adr/0004-hard-stop-only-in-v1.md). The headline finding.** |
| **D10** | R8 client separate and later | ⬜ | scope hygiene | none in v1 | ✅ |
| **D11** | Networked host | ⬛ | environmental fact | none | ✅ |
| **D12** | Reuse self-hostable software | ⬛ | *explicit instruction* | none — it is a *principle*, and it saves | ✅ **This audit is D12 applied to ourselves.** |
| **D13** | JSON Schema → standard tool definitions | ⬜ | **D4**'s consequence; agent-callability | Schema compiler + projections | ✅ compiler; ⏸ *second* projection (§4.2) |
| **D14** | BentoML as in-container runtime | ⬜ | **D12**; batching is subtle | Pinned dep in every image; the `RuntimeBackend` seam | ✅ **The single biggest complexity *avoided*** — we write no batcher |
| **D15** | Batched tools declare only batchable inputs | ⬛ | safety: silent misattribution | One validation rule + `params:` | ✅ Cheap, prevents the worst bug class |
| **D17** | `tswap preflight` as author gate | ⚠ | **R2**, inferred — *nobody asked for this command* | 9 stages, a check registry, fixtures per check | ✅ **but trimmed** (§4.1). High value, and the largest elective item remaining |
| **D18** | Payloads by reference, URI-ready | ⬜ | 500 MB CTs are a fact | A resolver seam (v1: identity function) | ✅ Cost is genuinely near zero |
| **D19** | Mandatory descriptions | ⬜ | agent-consumability; R8 precedent | Two validation rules | ✅ |
| **D20** | Router in a container | ⬜ | **D8** | Docker socket mount (root-equivalent) | ✅ documented honestly |
| **D21** | Address by container name, no host ports | ⬜ | avoids a whole bug class | *negative cost* | ✅ Another good simplification |
| **D22** | Cold-start requests block, bounded | ⬜ | **R3**; simplest client contract | `queue_timeout`, `max_queue_depth` | ✅ Refusing 202-and-poll avoids a result store |
| **D23** | One tool per container, versions by name | ⬜ | follows from **D2** | none — refuses features | ✅ |
| **D24** | One file or many; no `tswap exec` | ⬜ | **R4** | `path:` includes | ✅ |
| **D25** | Preempt an idle incumbent | ⬛ | ***quotable***: *"we don't want to wait for TTL"* | Eviction ranking (needed for groups anyway) | ✅ **Nearly free** — see §3.1 |
| **D26** | ~~`unload()` mandatory, stage 8 hard FAIL~~ | ⚠ | derived from **D9**'s premise | Was: GPU-only preflight stage, a tool class | ↩ advisory ([ADR-0004](adr/0004-hard-stop-only-in-v1.md) §4) |
| **D27** | Measure free VRAM, never predict | ⬜ | shared node | One optional pre-start read | ✅ retained; the boundary is what matters |
| **D28** | VRAM failure is not a tool failure | ⬛ | shared node; correctness | One state edge + one error reason | ✅ **retained in full** — moved from reload to cold start |
| **D29** | Ray Serve not adopted | ⬜ | a challenge, twice | none — it is a *refusal* | ✅ see [`15_RAY_SERVE_EVALUATION.md`](15_RAY_SERVE_EVALUATION.md) |

### 3.1 Why D25 survives an audit that killed D9's other half

Worth isolating, because they were bundled and only one was expensive.

**Preemption is not extra machinery.** The scheduler must already choose and evict a victim when a group is full and a request arrives — that is what `max_resident` *means*. **D25** only says the trigger may be a request rather than a timer. Same code path, different caller.

**Soft unload was the expensive half**, and it was justified largely by making preemption *cheap* rather than making it *possible*. With the cost tolerated, preemption stands alone at roughly zero marginal complexity.

**Score: forced, quotable, nearly free.** Keep it.

---

## 4. Recommended trims beyond ADR-0004

### 4.1 Preflight: nine stages is two too many for v1

**D17** is the largest elective decision remaining. The audit **keeps it** — an author discovering at deployment that their tool lies about readiness is exactly the R8 defect this project exists to correct — but the stage list has grown past its demand.

| Stage | Recommendation |
|---|---|
| 1 Static · 2 Build · 3 Standalone boot · 4 Truthful readiness | **Keep.** Stage 3 is guardrail 11; stage 4 is *the* R8 defect. These four are the command's reason to exist. |
| 5 Contract | **Keep.** Schema drift silently breaks every agent consumer. |
| 6 Example inference | **Keep.** Cheap; also powers `tswap test`. |
| 7 Batching and attribution | **Keep.** Guardrail 5 is safety-critical in a healthcare context. |
| **8 Resource release** | ❌ **Removed by [ADR-0004](adr/0004-hard-stop-only-in-v1.md).** With no soft unload, nothing calls `unload()` on the reclamation path. **Preflight becomes GPU-free end to end**, which is guardrail 12 satisfied by construction rather than by exception. |
| **9 Teardown** | ⏸ **Fold into the runner's `finally`, not a reported stage.** "Leave nothing behind" is an invariant of the *runner*; asserting it as a user-facing check adds a report line for something the author cannot act on. Keep the assertion, drop the stage. |

**Net: nine stages → seven, and no GPU required.** The command gets faster, more portable and easier to explain, and loses nothing an author needed.

### 4.2 Two schema projections in v1 is one more than the trigger justifies

**D13** compiles `inputs:` to JSON Schema — **keep, unconditionally**; it is the authoring surface and the validation source. But v1 ships *two* projections (our descriptor, and `?format=tools`) with `?format=openapi` already deferred.

The audit's observation: `?format=tools` is justified by an integration whose acceptance test (M9) *"needs a real LLM deployment to run against"* — and [`HANDOFF.md`](HANDOFF.md) §6 still lists the consuming agent setup as **something we have to ask about**. That is the D9 pattern again: building for a consumer we have not confirmed.

**Recommendation — softer than for D9, because the cost is much lower:** keep `?format=tools` (it is a pure function of the compiled schema, perhaps 50 lines, and **D13** is genuinely our integration thesis), but **do not let its acceptance test gate M9**. If no agent deployment exists to test against, ship the projection and mark the test pending rather than building infrastructure to satisfy it.

### 4.3 The CLI's long tail

Twenty-two commands is a lot for v1. Most are thin wrappers over the API and cost little, but three earn scrutiny:

| Command | Finding |
|---|---|
| `tswap unload` | ❌ **Removed by [ADR-0004](adr/0004-hard-stop-only-in-v1.md).** |
| `tswap dev` | ⏸ **Defer.** Bind-mount plus hot reload is a genuine second execution path — the thing **D24** rightly refused for `tswap exec`. `tswap build` + `tswap preflight` covers the inner loop, more slowly. Add it when authors say the loop is too slow. |
| `tswap shell` | ✅ Keep — it is one line over `docker exec` and it is what people reach for at 2am. |
| `tswap prune`, `warm`, `run`, `ps` | ✅ Keep. Each is thin and each answers a question an operator actually asks. |

**Net: 22 → 20 commands.** A small win, but `tswap dev` in particular is a maintenance surface (file watching, reload semantics, a divergent container config) out of proportion to its v1 value.

### 4.4 What this audit deliberately did **not** trim

- **The four base-image templates** (`cpu`, `cuda`, `tensorflow`, `function`). They look like duplication; they are **D2**'s entire value proposition made concrete. Cutting to two would immediately re-raise "why can't I add my TF model".
- **`min_residency` and thrash detection.** [ADR-0004](adr/0004-hard-stop-only-in-v1.md) makes displacement *more* expensive, so these become **more** important, not less. Anyone tempted to trim them should read [ADR-0004](adr/0004-hard-stop-only-in-v1.md) §"What this costs" first.
- **The `RuntimeBackend` seam** (**D14**). It is architecture-only with no v1 code, and it is what makes the BentoML bet reversible per tool before it is ever reversible project-wide. Near-zero cost, high option value.

---

## 5. Three things that must not be "simplified"

A complexity audit is dangerous if it only subtracts. These are the places where the apparent complexity **is** the product:

1. **Batch result attribution** (guardrail 5). The length and order checks, and `retry_singly`, look like defensive over-engineering until the day one patient receives another's result. **Never trim.**
2. **The pure scheduler** (guardrail 2). Keeping `request_slot` free of I/O is why the entire policy surface — the reason this project exists — is testable in milliseconds. It looks like purity theatre; it is the difference between a scheduler we can change confidently and one we cannot.
3. **Truthful `/ready`** ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §3.2). Reporting server-up instead of weights-loaded is the specific R8 defect that motivated this project. It costs one background task and one status code.

**Each of these is cheap in code and expensive to lose.** That is the opposite profile from soft unload, and it is why they survive an audit that removed a larger, better-argued feature.

---

## 6. Is the router itself the complexity?

The honest form of the challenge. After [ADR-0004](adr/0004-hard-stop-only-in-v1.md), v1 is:

```
config loader + validator      pydantic + yaml, one resolver
container backend              docker SDK behind a protocol
scheduler                      a few hundred lines, pure, no I/O
proxy                          httpx streaming through FastAPI
watchdog                       one periodic tick, 5 jobs (was 6)
runtime                        a BentoML adapter + a handler protocol
```

**Nothing in that list is exotic**, and only the scheduler is genuinely ours. The alternatives were measured against it three times ([ADR-0001](adr/0001-build-our-own-router.md)) and once more in depth ([`15_RAY_SERVE_EVALUATION.md`](15_RAY_SERVE_EVALUATION.md)), and every one of them requires **operating a cluster and still writing the scheduler**.

**The strongest statement available, and it is deliberately modest:** we own a few hundred lines of eviction policy above a container boundary, and reuse everything else — Docker, FastAPI, BentoML, llama-swap's semantics. That is not a complex stack built for fun. It is the smallest thing that satisfies **D2** and **D25** together.

---

## 7. The finding nobody asked for: the plan is bigger than the product

Sixteen numbered documents, four ADRs, twenty-nine decisions, and a third-party documentation mirror — for a v1 of perhaps 4,000 lines.

**This is a real maintenance cost**, and it has already produced a real defect: [`13_OPEN_QUESTIONS.md`](13_OPEN_QUESTIONS.md), [`README.md`](README.md) and [`HANDOFF.md`](HANDOFF.md) each carry their own summary of the Ray Serve decision, and after three revisions they had drifted into three slightly different stories. [ADR-0004](adr/0004-hard-stop-only-in-v1.md) has now touched a dozen more places that must agree.

**Recommendations:**

1. **One canonical location per fact.** Summaries elsewhere must *link*, never restate. The Ray Serve position lives in [`15_RAY_SERVE_EVALUATION.md`](15_RAY_SERVE_EVALUATION.md); everything else points at it.
2. **ADRs supersede prose; prose must not re-argue a settled ADR.** [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](06_LIFECYCLE_TTL_AND_SCHEDULING.md) currently re-litigates **D9** in §3.1 — that section becomes a link.
3. **When the repo is created, the plan is history.** Port the decision log and the ADRs into `docs/adr/`; do not port sixteen planning documents into a repository whose code will contradict them within a month.

**Applying D12 to ourselves one last time:** we have written more words about this system than we will write lines of it. That was worth it for the gate decisions, which genuinely turned on argument. It is not worth continuing at this rate once code exists.

---

## 8. Summary

| Question | Answer |
|---|---|
| Are we reimplementing a complex stack for the fun of it? | **No** — but we had accumulated one elective feature (soft unload) that was expensive, inferred rather than requested, and is now removed. |
| Is the router justified? | **Yes.** Four evaluated alternatives each require operating a cluster *and* writing the scheduler anyway. |
| What was the single biggest win available? | **[ADR-0004](adr/0004-hard-stop-only-in-v1.md)** — a state, an endpoint, a scheduler variant, a tool class, a GPU-only preflight stage, a CLI command, a config key, and the "is it really freed" verification burden. |
| What is the next-biggest risk? | **Not code — documentation drift.** §7. |
| What must never be trimmed? | Batch attribution, scheduler purity, truthful readiness. §5. |

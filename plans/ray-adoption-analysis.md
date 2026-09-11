# Ray Serve adoption — a decision analysis on the simplicity axis

> **What this document is.** The requester asked: *"Can you provide an analysis of the pros/cons of using ray knowing all the evidences we have now? We need a strong emphasis on simplicity and ease of maintaining the code etc."*
>
> **What it is not.** It is not the decision. [`spike-E-results.md`](spike-E-results.md) §8 records that the frozen protocol routes this choice to the requester under Rule 3 — *"Option (c) must not be chosen by default"* — and Rule 4 escalates to the same place. This document prices the three options honestly enough that the requester can choose, and says plainly where the evidence runs out. §11 recommends; §11 also states its conditions and what would change it.
>
> **Method.** Scored on [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md)'s own three axes — **class** (forced / chosen / elective), **demand** (quotable / inferred / none), **carrying cost** (what it costs *forever*). Consistency with the project's established method matters more than inventing a new one. Every third-party claim carries a file:line or a document citation. Every factual claim is labelled **measured**, **inferred** or **assumed** — that distinction is the spike's entire value, and §0 defines it.
>
> **Bias discipline.** [`bias-audit-and-decision-procedure.md`](bias-audit-and-decision-procedure.md) §2 records seven consecutive retreats in which the anti-Ray conclusion never moved while its reasons rotated. That is a documented process defect, and this document is written by the same pipeline. Two guards are applied: §7 argues Ray's case at full strength before §8 argues against it, and §10 lists everything in the existing position that the spike **falsifies** — including two items where the desk evaluation was simply wrong.
>
> ---
>
> **Revision 2 — two inputs, pulling in opposite directions.** This revision incorporates evidence that arrived after the first draft, and it is worth stating up front that they do **not** both favour the same answer.
>
> 1. **The latency attribution is settled, against Ray** (ledger **§9T, D45**). §12 of the previous revision named the plain-podman baseline as the cheapest measurement that could most change the answer. It was run. Container lifecycle costs **~5 s**; Ray's default displacement path costs **~100 s**. §5.1 is rewritten from "unattributed — could go either way" to the measured finding, with its three limits stated so it does not harden beyond its evidence.
> 2. **Multi-node GPU is now a first-class concern**, raised by the requester: *"we need to note that we want to avoid huge rewrite in the future in the case we have multi-node gpus.. Ray is a huge production tool that might remove a lot of complexity that we have no experience in."* The previous revision priced code for a *single* node and **never priced the migration**. That was a real gap, it is the strongest pro-Ray argument available, and **§5A is a new section that answers it rather than deflecting it.**
>
> **These two inputs do not cancel. §11.0 weighs them explicitly and says which dominates, rather than splitting the difference to appear balanced.**

---

## 0. Evidence classes, defined once

Used throughout as a tag on every load-bearing claim.

| Tag | Meaning |
|---|---|
| **[M]** measured | An observation from a spike run, recorded verbatim in the ledger with an exit code and raw output. Bound to the environment in [`spike-E-results.md`](spike-E-results.md) §5.3. |
| **[S]** source-read | A behaviour established by reading Ray's own code at a cited file:line during this task or the spike. Not documentation, not recollection. |
| **[I]** inferred | A conclusion drawn from **[M]** or **[S]** by an argument that is stated, so it can be checked. |
| **[A]** assumed | Not established by this spike. Includes every estimate of code we have not written. Flagged so it cannot be laundered into fact. |

**A standing caution on [A].** Both options in this analysis rest partly on **[A]**: Ray-native's replacement-code estimate and our-router's remaining-milestone estimate are both guesses about unwritten code. [`case-for-ray-native.md`](case-for-ray-native.md) §10.4 names exactly this error — *"I compared a real system's known flaw with an imagined system's intended virtue, and scored the imagined one higher"* — and it is the single most misleading move available here. Where a Ray cost is **[M]** and the corresponding tool-swap cost is **[A]**, this document says so at the point of comparison rather than in a footnote.

---

## 1. The question, restated so it can be answered

"Simplicity" and "maintainability" are not scoreable as adjectives. Per the brief, they cash out as exactly four things:

1. **Code we own** — lines we write, test, debug and carry.
2. **Dependencies we carry** — and specifically, what their *stability contract* is.
3. **Failure modes we handle** — including the ones that fail silently on an unattended system.
4. **Hours we spend** — on operations, on upgrades, on reading somebody else's internals.

Both directions cost all four. The rest of this document prices them in those units.

**The three options are the protocol's, not new ones** ([`spike-E-results.md`](spike-E-results.md) §8, Rule 3):

| | Option | One-line shape |
|---|---|---|
| **(a)** | Adopt Ray, accept manual cluster recovery | Ray Serve is the lifecycle engine; an operator owns the head-node runbook |
| **(b)** | Adopt Ray on KubeRay | Kubernetes on the shared DGX — rejected by both the requester and the engineer as too heavy, and closed on evidence in [ADR-0001](../plan/adr/0001-build-our-own-router.md) |
| **(c)** | Keep building our router | The status quo; ~a third more code than Ray-native |

**Option (b) is priced but not analysed at length**, for one reason that is not a judgement call: adopting it re-opens the M−1 gate that [ADR-0001](../plan/adr/0001-build-our-own-router.md) closed on three executed-or-answered spikes. It would answer both the mount problem and the recovery problem at once ([`ray-serve-mounts-and-deletion-scope.md`](ray-serve-mounts-and-deletion-scope.md) §1.6) — that is a real and honest point in its favour, and it is why it is on the list at all. But it converts a "should we adopt a framework" question into a "should we adopt Kubernetes" question, and that one has an ADR. **If the requester wants (b) reconsidered, it needs its own analysis, not a subsection of this one.**

---

## 2. The simplicity question, answered concretely

### 2.1 What adopting Ray deletes — the real reduction, stated at full size

From [`09_IMPLEMENTATION_PLAN.md`](../plan/09_IMPLEMENTATION_PLAN.md), via the Rule 1 deletion list ([`spike-E-results.md`](spike-E-results.md) §8) and [`ray-serve-mounts-and-deletion-scope.md`](ray-serve-mounts-and-deletion-scope.md) §2.1:

| Deleted | What that actually is |
|---|---|
| **M2** — container backend + lifecycle | `ContainerBackend` protocol, `DockerBackend`, `FakeBackend`, the state machine, coalesced `ensure_ready`, health probe, shutdown ordering, boot reconciliation. **The single biggest deletion.** |
| **M3's proxy internals** | `ANY /upstream/{tool}/{path...}`, header hygiene, bidirectional streaming passthrough |
| **M6's TTL watchdog** | The one periodic timer and its job set |
| **M7's log collector** | Container stream capture, per-tool rotating files, `log_output` switch |
| **M3.5** — the BentoML spike | Moot if batching comes from `@serve.batch` |

**This is five milestones' worth of scope, and it is a large, real reduction.** Nothing in the spike undermines it. [`15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md) §7 conceded it in the project's own words: *"Genuinely less code than we are writing."* The arithmetic recorded in [`ray-serve-mounts-and-deletion-scope.md`](ray-serve-mounts-and-deletion-scope.md) §2.5 is **~25–35% of v1's code** — **[A]**, an estimate over unwritten code, and it is the number both sides have used.

### 2.2 What adopting Ray requires us to write instead — the replacement cost

**Ray is not free simplicity. It is different code, plus a dependency whose internals we now demonstrably have to read.** Each row below is work that does not exist in the current plan and would be created by adoption.

| New code we would own | Why it is required | Evidence |
|---|---|---|
| **`tools.yaml` → Serve config generator** | Ray's application/deployment/`runtime_env`/`ray_actor_options`/autoscaling shape is not `tools.yaml`'s shape. [`case-for-ray-native.md`](case-for-ray-native.md) §7 calls this *"`tools.yaml` with different key names"* and shows a four-line example — that is the **[A]** optimistic case; §2.3 below is why it is not that simple | [`case-for-ray-native.md`](case-for-ray-native.md) §7 |
| **The legacy `container` runtime_env wiring, per GPU tool** | `image_uri` **structurally cannot** give a container a GPU: [`ImageURIPlugin.modify_context`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:174) hardcodes `run_options=[]`. The legacy key forwards run options ([`image_uri.py:222-229`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:222)) — so every GPU tool config must carry `--runtime=/usr/bin/nvidia-container-runtime`, a **host-specific absolute path** | **[S]** + **[M]** — [`spike-E-results.md`](spike-E-results.md) §2 D36, ledger §§9L/9N |
| **A config-generation guard against D32** | A YAML config setting **any** actor option silently replaces the code-declared options wholesale ([`application_state.py:1827-1833`](/usr/local/lib/python3.11/site-packages/ray/serve/_private/application_state.py:1827)), discarding `image_uri`. Our generator must always emit the image *inside* `ray_actor_options`, and a test must assert it — because Ray reports RUNNING when it is wrong | **[S]** + **[M]** — D32, ledger §9j |
| **The autoscaling / eviction policy, as a Ray application-level policy** | We write the eviction policy either way. This is the honest half of both cases: [`15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md) §7 — *"The platform does not remove the interesting work; it relocates it"* — and [`case-for-ray-native.md`](case-for-ray-native.md) §3 agrees from the other side | Both documents, agreeing |
| **The operator runbook, as supervised automation** | Step 6 phase A: `ray stop --force` → `ray start --head` **with the cluster's own flags** → **re-apply the config** → poll. Serve applications do not come back by themselves. Unattended operation means we write the supervisor that owns those steps | **[M]** — [`spike-E-results.md`](spike-E-results.md) §3.6 |
| **A container reaper** | Ray's `image_uri` launcher passes no `--rm` ([`image_uri.py:77-96`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:77)); 109 accumulated across the spike. Harmless on this host, unbounded in principle | **[M]** — §3.7 |
| **A cluster-launch wrapper that never passes an explicit `--num-gpus=0`** | In Ray 2.57 an explicit `0` is **not** autodetect: autodetection runs only when the value is `None` ([`resource_and_label_spec.py:454-471`](/usr/local/lib/python3.11/site-packages/ray/_private/resource_and_label_spec.py:454) — `if num_accelerators is None: num_accelerators = accelerator_manager.get_current_node_num_accelerators()`, i.e. a supplied `0` is respected and the branch never runs). The spike's own harness hit this and had to encode the lesson in a comment | **[S]** — verified in this task at the cited lines; the spike's fix is recorded at [`start_cluster.sh:74-78`](../spike-e-ray-native/scripts/lib/start_cluster.sh:74) |
| **A `umask 0` + world-writable-log-dirs cluster launch, or a `USER`-uid contract on every tool image** | `image_uri` runs the worker as the *image's* `USER` with no `--user` ([`image_uri.py:76-96`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:76)); against Ray's 0755 session log dirs a uid mismatch produces an **uncaught C++ abort with no message** (D22). The spike's workaround is an accepted security trade-off | **[M]** + **[S]** — §2 D22 |
| **A plain-data boundary at every tool call** | Only str/int/float/bool/list/dict/bytes may cross a deployment boundary; a framework-typed value breaks the call by requiring the *receiver* to import the sender's libraries (D27) | **[M]** — §2 D27, ledger §9g |

**Plus what it adds that is not code but is maintenance**: a Ray cluster of six process types to operate, rootless podman as a prerequisite, and Ray/Python version lockstep down to the patch — confirmed as a real coupling, not a documentation claim, because the fixtures had to be built from the exact base tag `docker.io/rayproject/ray:2.57.0-py311-gpu` **[M]** ([`spike-E-results.md`](spike-E-results.md) §3.0).

### 2.3 The honest netting

**Adopting Ray does not trade "code" for "no code". It trades a container backend, a proxy, a watchdog and a log collector — all boring, all fully testable with fakes, all ours — for a config generator, a legacy-API wiring layer, three silent-failure guards, a supervisor runbook, a reaper, and a cluster to operate.**

The deleted code has one property the replacement code does not: **it is testable without a GPU, without a cluster and without a shared host.** [`09_IMPLEMENTATION_PLAN.md`](../plan/09_IMPLEMENTATION_PLAN.md) M2's test list is entirely `FakeBackend` plus one real-container round trip. The replacement code's correctness conditions — does the image actually reach the replica, did the GPU actually arrive, did the config re-apply after a head-node restart — are **exactly the conditions the spike needed 43 defect fixes and seven host runs to observe once**. That asymmetry is the strongest simplicity argument in this document, and it is **[I]** from **[M]**: the spike is the measurement of how hard those conditions are to verify.

### 2.4 What continuing to build costs — priced with the spike's own evidence

This is the half that the previous documents got wrong by comparing Ray's measured flaws against our imagined virtues. The spike gives real evidence about what our own code must handle, **because we hit every one of these problems ourselves while building the harness**:

| Problem our router must also solve | What the spike proves about it |
|---|---|
| **GPU passthrough to a container** | Six mechanisms tested; **only** `--runtime=/usr/bin/nvidia-container-runtime` works on this host. podman 3.4.4 does not implement `--gpus`; it predates CDI so `nvidia.com/gpu=N` is treated as a path; raw device nodes lack the driver libraries **[M]** (ledger §9L table). Our `DockerBackend` uses Docker, where `--gpus all` works **[M]** (§9L: *"Docker confirms the host plumbing independently"*) — so this specific problem is **cheaper for us, not free**. |
| **Container lifecycle and litter** | We would pass `--rm` or reap deliberately. That is a decision we must remember to make; Ray's omission is evidence that it is easy to forget **[I]**. |
| **VRAM accounting under contention** | Baseline VRAM was 647 MiB and the released state was **579 MiB — *below* baseline** **[M]** (§3.3). Any "did it release?" check we write faces the same ambiguity, and D28 (a neighbour's VRAM is not our failure) is exactly this problem. |
| **Crash recovery** | Ray gives replica-level recovery free. Ours is M2's boot reconciliation — **[A]**, unwritten. §7.2 credits Ray properly for this. |
| **Timing boundaries in reclamation** | Retraction 2 (§4): our gate measured VRAM release at 65 s when the earliest possible release was ~75–80 s, and recorded a false "leak". **Our own TTL watchdog and thrash detection will have the same class of bug**, and the spike is the evidence that it is easy to write a check that "fires on the wrong side of a timing boundary" **[M]**/**[I]**. |
| **Unfalsifiable checks** | Three of our own checks *could not fail*, and all three were **passing** when found (§5.1). This is a fact about our testing discipline, not about Ray, and it prices our own path: the code we keep must be tested by someone who makes checks falsifiable. |

**The fair summary of §2.4:** the spike does not show that our own router is easy. It shows that the problems are real, that we can solve them (Docker gives us the GPU without a legacy API), and that our discipline needs the falsifiability rules the spike learned the hard way.

---

## 3. The maintenance-burden evidence — the strongest thing the spike produced

This is the section the decision should turn on, because it is the only place where the spike produced evidence that no amount of desk evaluation could have produced.

### 3.1 Four behaviours explicable only by reading Ray's private source

All four are in `ray/_private/` or `ray/serve/_private/` — **paths whose name is Ray's own statement that they are not API.**

| # | Behaviour | Private source | Class |
|---|---|---|---|
| 1 | `image_uri` cannot pass **any** podman run option — so `--runtime`, `--device`, `--gpus` are structurally unreachable | [`image_uri.py:174`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:174) — `run_options=[]` hardcoded | **[S]** |
| 2 | A YAML `ray_actor_options` **replaces** the decorator's, not merges — silently voiding a declared image | [`application_state.py:1827-1833`](/usr/local/lib/python3.11/site-packages/ray/serve/_private/application_state.py:1827) | **[S]** |
| 3 | The downscale clock starts when Ray *first wants* to scale down, not when the request ends — so earliest release is `look_back_period_s` decay **+** `downscale_to_zero_delay_s` ≈ 75–80 s | [`autoscaling_policy.py:124-130`](/usr/local/lib/python3.11/site-packages/ray/serve/autoscaling_policy.py:124), with [`:112-118`](/usr/local/lib/python3.11/site-packages/ray/serve/autoscaling_policy.py:112) showing scale-to-zero is permitted only from 1 → 0 | **[S]** |
| 4 | An explicit `--num-gpus=0` is **not** autodetect — autodetection runs only when the value is `None`, so an explicit 0 registers a raylet with zero GPUs permanently | [`resource_and_label_spec.py:454-471`](/usr/local/lib/python3.11/site-packages/ray/_private/resource_and_label_spec.py:454) | **[S]**, re-verified in this task |

**The maintainability question, asked directly.** What does it mean to depend on a framework where:

- **the documented API cannot do the job** — `image_uri` is the modern, documented path, and it allocated **zero VRAM** while Ray reported the replica HEALTHY with `GPU: 1.0` reserved **[M]** (§3.3, D36);
- **the working path is the deprecated one** — the legacy `container` key, which [`runtime_env.py:397-404`](/usr/local/lib/python3.11/site-packages/ray/runtime_env/runtime_env.py:397) permits only alongside `config` and `env_vars`, so `pip`, `working_dir` and most of `runtime_env` are unavailable to any GPU tool **[S]**;
- **and four separate behaviours were only explicable by reading private internals**?

The honest answer, and it is a judgement call rather than a measurement: **each future Ray upgrade is a re-verification of four private-source behaviours, none of which carries a compatibility promise.** That is a recurring cost with no upper bound and no way to test for it except running the spike again. Against a stated priority of *"robust and easy to maintain"*, it is the heaviest single item on Ray's side of the ledger.

**And note what it is not.** It is not *"Ray is badly built"*. Three of the four behaviours are defensible in isolation; #3 is arguably correct autoscaler design. The cost is not that Ray is wrong — it is that **our use of it lands squarely on its private surface**, which is what "unusual usage pattern" means when priced properly.

### 3.2 The legacy-API dependency, priced for portability and upgrade risk

**Measured position** **[M]**/**[S]**: GPU tools work only through `runtime_env: {container: {image: …, run_options: ["--runtime=/usr/bin/nvidia-container-runtime"]}}`.

| Consequence | Price |
|---|---|
| Mutually exclusive with `pip`, `working_dir` and most `runtime_env` fields **[S]** ([`runtime_env.py:397-404`](/usr/local/lib/python3.11/site-packages/ray/runtime_env/runtime_env.py:397)) | Any authoring feature that would use those fields is unavailable to GPU tools — i.e. to the tools that matter |
| Requires a **host-specific absolute path** in every GPU tool's config **[M]** | Tool configs are **not portable across hosts**. That is a direct hit on [ADR-0001](../plan/adr/0001-build-our-own-router.md)'s surviving hedge — *"the tools are the durable asset; the router is replaceable"* — and on the guardrail-11 invariant that a tool image runs standalone under plain `docker run`. Mitigable by generating the path from config, which is more code we own (§2.2) |
| The API is **deprecated in favour of `image_uri`** ([`ray-serve-mounts-and-deletion-scope.md`](ray-serve-mounts-and-deletion-scope.md) §1.3, read from the same file) | Upgrade risk is asymmetric: the path we depend on is the one Ray is retiring, and its replacement lost the capability we need — a **capability regression in the migration path**, established by source-read rather than asserted |
| The Docker path might not have this problem at all | **Untested and unreachable**: Ray hardcodes `container_driver = "podman"` at [`image_uri.py:76`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:76) **[S]**. Under Docker with `nvidia-container-runtime` as the default runtime, library injection can occur without an explicit flag — **[A]**, and [`spike-E-results.md`](spike-E-results.md) §5.2 names it *"the single biggest caveat on D36"*. **If this is wrong, §3.2 weakens substantially.** |

### 3.3 The ~43 defects — stated carefully, and not overclaimed

**The number** **[M]**: ~43 defects (D1–D43) were found and fixed across seven test steps to produce trustworthy output ([`spike-E-results.md`](spike-E-results.md) §6).

**The attribution, which is the part that matters**: **two were Ray's, most were ours** — and *most of ours were **harness** defects*, not evidence about Ray's difficulty. The ledger's own step-1 accounting: seven fixes stood between "the plan says this should work" and the first real result; **two** were findings about Ray (D20/D22) and **five** were ours (§9h). Four consecutive blockers (D16–D19: a shell variable collision, podman's short-name strictness, an unprivileged-user permission, a sticky-bit unlink) were **host-only friction and none is a finding about Ray** (§§9c–9d).

**What the number may legitimately be used for** — and this is narrow:

- **It prices the cost of *evaluating* this stack carefully.** Seven steps, ~43 fixes, three unfalsifiable checks, two retracted verdicts. **[I]**
- **It calibrates confidence in the four §2 findings**, because those are what survived that filter.

**What it may not be used for.** It is **not** a measure of Ray's difficulty, and any argument of the form "43 defects, therefore Ray is hard" is invalid. The results document says so itself: *"a reader weighing the §8 decision should weight Ray accordingly — the findings in §2 are what Ray actually showed; everything else was the price of getting Ray's numbers at all."* Equally, it is not evidence that our own path is easy: three of our own green checks could not fail (§5.1), which is a fact about **us**.

---

## 4. The genuine pros of Ray, at full strength

Per [`bias-audit-and-decision-procedure.md`](bias-audit-and-decision-procedure.md) §4.1, this section is written before §8 and without hedges. Each item is tagged.

**1. Step 3 passed. The core loop demonstrably works.** **[M]** Two tools with mutually incompatible dependencies (torch 2.8.0+cu129 and tensorflow 2.16.2), in separate OCI images, alternating on **one physical GPU**, on demand, with the same-GPU invariant confirming contention was genuinely tested:

| Phase | GPU 0 VRAM |
|---|---|
| baseline, both at 0 replicas | 647 MiB |
| `tool_torch` serving | **5163 MiB** (+4516, matching a 4096 MiB allocation plus CUDA context) |
| after Ray's own scale-to-zero | **579 MiB** — released *below* baseline, on Ray's own `DOWNSCALE_COMPLETED` |
| `tool_tf` serving | **38909 MiB** |
| alternate back to `tool_torch` | served |

**This is the decisive Rule 2 gate, and Ray cleared it.** It also fires the falsifier [ADR-0003](../plan/adr/0003-ray-serve-not-adopted.md) named for itself — *"a production-viable per-deployment OCI image boundary that composes with per-device GPU pinning"* — at least in part (§10.3).

**2. Replica-level crash recovery is automatic, and we would otherwise build it.** **[M]** `kill -9` on a replica: detected via `HEALTH_CHECK_FAILED`, corpse recorded in `recent_dead_replicas`, fresh replica with a **new pid** in ~15 s, unattended, in response to a verified death (§3.6 phase B). Our equivalent is M2's boot reconciliation plus M6's liveness re-checks — **[A]**, unwritten, and [`case-for-ray-native.md`](case-for-ray-native.md) §10.4 is right that comparing our unwritten ideal favourably against Ray's measured behaviour is the single most misleading move available.

**3. Reliability at cadence is excellent — 20/20, zero errors.** **[M]** Step 5 ran 20 alternations with `SPIKE_STEP5_MAX_ERRORS=2` and **never used the tolerance**. No stuck states, no controller degradation, no orphaned replicas. The PARTIAL verdict is about the *latency distribution*, not reliability, and the results document is emphatic that this must not be lost (§3.5). **An externally-driven scheduler can drive Ray to preempt at cadence** — which is precisely the architecture a Ray-native tool-swap would use.

**4. Five milestones leave scope.** §2.1 — M2, M3 (proxy internals), M3.5, M6's watchdog, M7's collector. That is a large, real reduction and it is not disputed anywhere in this repository.

**5. Things we would never write — and multi-node is the one that matters, not the dashboard.** Multi-node scaling, a dashboard, per-replica status, Prometheus metrics, an object store with a 100 KiB threshold for large tensors, and a scheduler. [`15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md) §5 concedes `serve status` and the dashboard are *"a better status surface than we will build in v1"*, in the project's own words.

> **This item was under-weighted in the previous revision, and the requester was right to press on it.** Listing *"multi-node scaling"* in a row alongside a dashboard prices it as a feature. It is not a feature — it is **the avoidance of a future migration**, which is a different and larger thing, and it is *"complexity we have no experience in"*. **[§5A](#5a-multi-node-gpu--the-migration-this-analysis-never-priced) now prices it as a first-class section**, including the argument at full strength against this document's own recommendation (§5A.6), the rewrite-or-extension answer (§5A.3), and the one bound that limits it: robust multi-node Ray is KubeRay, which is option (b) (§5A.5).

**6. Bus factor, and it is the row that never affects any conclusion.** [`case-for-ray-native.md`](case-for-ray-native.md) §5 makes this point and it survives the spike untouched: the plan's own comparison table scores its own bus factor **"Worst"**. For a small research team, the system that survives is the one that still runs after its author moves on. **Nothing in the spike bears on this at all** — which means it is exactly as strong an argument now as it was before, and it should not be quietly discounted because the spike produced other numbers.

**7. Two people, reasoning independently, recommended reuse.** The requester (*"prioritise making the tool robust and easy to maintain"*) and the engineer (*"prioritize the use of existing frameworks"*). And **D12** is the project's own principle: *prefer existing self-hostable software*. [`14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md) §1 admits the tension and it has never been resolved, only argued around.

**8. The nine-for-nine record.** [`case-for-ray-native.md`](case-for-ray-native.md) §4 lists nine objections to Ray that were each stated confidently and each fell. **The spike adds a tenth data point and it cuts the same way**: the two decisive "Ray fails the gate" verdicts were **our own measurement errors**, retracted on the record (§4 of the results doc). *Every* decisive negative this project has produced about Ray has so far been withdrawn.

---

## 5. The cons, priced with measurements

### 5.1 P90 swap latency 103 s — now attributed, and the attribution is Ray's

> **This section previously said the 103 s was "the largest *unattributed* cost in the analysis" and priced it both ways. Step 8 has been run and the attribution is settled** (ledger **§9T, D45**, commit `01d68b3`). The both-ways table is replaced by the measurement. The previous §12 named this as the cheapest decisive experiment; it was, and it moved the answer.

**Measured** **[M]** (§3.5, ledger §9Q): 20 alternations under Ray — min 5.85 s, **median 9.48 s**, **P90 103.2 s**, max 103.6 s. Bimodal with nothing in between — ~12 cycles at 6–10 s, ~8 at 99–104 s. A **12× spread**, and the slow path is **40 % of requests**. A mean (~45 s) would describe no actual request.

**The baseline that was missing now exists** **[M]** (ledger §9T): the same alternation, same fixture images, same host, **no Ray at all**.

| | step 5 (Ray) | step 8 (plain podman) |
|---|---|---|
| min | 5.85 s | **3.87 s** |
| median | 9.48 s | **6.40 s** |
| **P90** | **103.2 s** | **6.67 s** |
| max | 103.6 s | **6.91 s** |
| distribution | **bimodal** — 40 % at 99–104 s | **tight** — all 20 within 3.9–6.9 s |

**~15× on P90, and the bimodality vanishes entirely. Podman's *slowest* cycle (6.91 s) beats Ray's *median* (9.48 s).**

**It is not a no-op being timed** — the trap that made step 3's first run worthless. Every cycle was VRAM-verified: torch **+4518 MiB**, tf **+38908 MiB**, each container returning its own baked-in `image_marker` and the correct per-image `weights_sha256`, so the step-1/2 identity guarantees hold. Inside the container, `init_total_seconds` was **1.85–2.01 s** (torch) and **3.77–3.97 s** (tf) — so roughly **half of podman's 4–7 s is the tool's own initialisation**, and the rest is container start.

**So the unattributed cost is now attributed** **[M]**/**[I]**:

| Component | Cost | Who pays it |
|---|---|---|
| **Container lifecycle** at 14–19 GB, warm store | **~4–7 s** | **Both options.** Our router inherits this and nothing else |
| **Ray's default displacement path** | **~100 s** | **Ray only.** Metric decay over `look_back_period_s` then `downscale_to_zero_delay_s` ([`autoscaling_policy.py:124-130`](/usr/local/lib/python3.11/site-packages/ray/serve/autoscaling_policy.py:124)) plus replica lifecycle |

**This is the hard-con branch that §12 specified *in advance*, which is the only reason it counts as evidence rather than as a result found after the fact.** The previous §5.1 offered two outcomes and said which way each would push; the measurement landed on the one that makes this a genuine Ray-specific con. Our own router inherits **~5 s**, not ~100 s.

#### Three limits, so the number does not harden beyond its evidence

The finding is load-bearing, so its boundaries are stated here rather than left to a reader's inference. All three are the step's own, recorded in ledger §9T.

1. **Teardown was not measured.** `mode=start` measures the **run span only** — fresh container start, init, identity, exit. It **excludes** Ray's scale RPCs, replica teardown, ingress routing and the HTTP round trip, and **`mode=full` was not run**. Step 5's cycle also includes displacing a live VRAM holder, which plain podman has no equivalent of. So the comparison is **start-side like-for-like, teardown-side incomplete**. What licenses the conclusion anyway is the size of the gap, not the completeness of the accounting: **~95 s of difference against a total podman cycle under 7 s**, so no plausible teardown accounting closes it. That is the honest form of the claim — *the gap is too large for the missing half to explain*, **not** *the missing half was measured*.
2. **Ray's ~95 s is configuration-dependent, not a floor.** `downscale_to_zero_delay_s` is a tunable config value and part of the remainder is `look_back_period_s` ([`autoscaling_policy.py:124-130`](/usr/local/lib/python3.11/site-packages/ray/serve/autoscaling_policy.py:124)) **[S]**. **The defensible claim is *"Ray's default path costs ~100 s where the container costs ~5 s"*. It is not *"Ray cannot go faster"*, and this document does not say that.** Whether it tunes to ~10 s **without destabilising the autoscaler** is **untested** **[A]** — and it is now the highest-value remaining experiment if Ray stays in contention (§12).
3. **20 samples, one run, one host, warm image store.** A second run should confirm before an ADR quotes the figure as settled.

**What the number establishes regardless** **[M]**: a swap *on Ray's default configuration* sometimes takes 100 seconds, and a swap *without an orchestrator* never took more than 6.91 s. Both facts bear on `queue_timeout` (**D22**), on `min_residency` and thrash detection ([`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §4.4, never-trim), and on §7.6's wait-versus-displace question — which step 8 sharpens rather than settles, because **a 5 s displacement is a much better deal than a 100 s one**, and that strengthens **D25**'s premise for our own router while weakening it for default-configuration Ray.

### 5.2 Cluster recovery needs an operator runbook

**Measured** **[M]** (§3.6 phase A): `kill -9` on the GCS pid. Recovery is `ray stop --force` → `ray start --head` **with the cluster's own flags** → **re-apply the config** → poll. Apps back to RUNNING in ~10 s *after* the procedure. `ray start` alone is **not** enough — an earlier run proved it (*"Ray is trying to start … but is already running"*), and **Serve applications do not come back by themselves**.

Against the protocol's written criterion — *"Fail: manual intervention, leaked VRAM, or orphaned containers"* — this is **FAIL as written**, and that is the recorded verdict (ledger §9S, D44).

**Price it fairly, in both directions:**

- **Against Ray:** for an unattended deployment, a supervisor must own that runbook, and we write it (§2.2). Guardrail 8 requires that restarting be cheap and safe.
- **For Ray, and this is [`case-for-ray-native.md`](case-for-ray-native.md) §6's best point:** our own recovery story is *"restart the router; boot reconciliation adopts running containers"* — **[A]**, code in a milestone that has never recovered anything. Ray's is a **measured three-command procedure that demonstrably works**. A documented, measured limitation is not obviously worse than an untested claim.
- **Weakening the evidence, per the protocol's own Rule 0.5:** this is the step the protocol *predicted* would fail. A result matching a prediction is weak evidence by the protocol's own terms — recorded for balance. The operational facts (the runbook, the 109 containers) stand regardless.

### 5.3 Only plain data crosses a deployment boundary (D27)

**Measured** **[M]** (§2 D27, ledger §9g): `TorchProbe` served its request fine inside its container; the HTTP 500 came from the **ingress** deployment — running on the host with no torch — while *deserialising the reply*, because [`introspect.py:61`](../spike-e-ray-native/toolkit/introspect.py:61) returned `torch.__version__`, a `TorchVersion` instance rather than a `str`.

**Consequence:** a router that aggregates heterogeneous tool results across deployment boundaries would need **every tool's libraries installed in the router** — defeating the purpose of per-tool images.

**Price it honestly: this con is partly a cost we pay regardless.** It is *direct empirical support* for [`ADR-0005`](../plan/adr/0005-one-uniform-batched-calling-convention.md)'s uniform plain-data calling convention, which we have already adopted for our own reasons. A tool-swap that already mandates plain data at the boundary is largely immune. **[I]** What remains Ray-specific is that the enforcement is a runtime pickle failure attributed to the *caller* — *"technically correct and diagnostically misleading"* — rather than a schema validation at the edge.

### 5.4 Silent failure modes — weighed specifically for unattended operation

The system is meant to run unattended. That is the axis on which these three matter more than their individual severity suggests.

| Failure | What the operator sees | Evidence |
|---|---|---|
| **D32** — a config option voids a declared image | **Ray reports RUNNING.** The tool runs on the host, against whatever is there. The spike's symptom was a `FileNotFoundError` on a path that exists only inside the image — but a tool whose dependencies *happen* to be present on the host would simply produce **wrong results silently** **[I]** | **[M]** §2 D32 |
| **D36** — a reserved GPU never reaches the container | **Replica HEALTHY, `GPU: 1.0` reserved, `CUDA_VISIBLE_DEVICES` set, zero bytes allocated, tool silently on CPU.** *"A scheduler built on the modern API would hand out GPUs its tools cannot use, and never know"* | **[M]** §2 D36 |
| **D22** — uncaught C++ abort, no message | Raylet repeats *"worker … dead, probably crashed during start"* every 60 s, with **no container log and no `.err` file**, because `RayLog` has already redirected fd 2. Diagnosed by **strace** | **[M]** §2 D22 |

**The pattern, and it is the thing to weigh:** all three fail in the direction of *reporting success*. For an unattended system serving clinical algorithms, a failure that reports RUNNING is categorically worse than one that crashes — and this project's own guardrails say so (guardrail 5c; [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §5 item 1 on never trimming result attribution).

**In fairness:** D32 and D36 are both **preventable by construction** in a generated config — always emit `image_uri` inside `ray_actor_options`, always use the `container` key for GPU tools, and assert both in a test. That mitigation is real. It is also more code we own (§2.2), and it is code whose absence is invisible.

### 5.5 109 orphaned containers

**Measured** **[M]** (§3.7): the podman store held **109 stopped containers** and 120 images at the end of the spike, because Ray's `image_uri` launcher passes no `--rm` ([`image_uri.py:77-96`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:77)) — unlike its own throwaway inspection container at [`:27`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:27). *Harmless on this host, unbounded in principle.* It also independently satisfies the protocol's step-6.3 orphaned-container Fail condition.

**Price:** low severity, trivially fixable by a reaper we write, and a genuine argument that this is not a well-trodden path. On a **shared** DGX — where step 7 recorded 9 unrelated Docker containers already running **[M]** — unbounded disk growth from a neighbour's litter is precisely the class of thing that makes you unwelcome on someone else's machine.

---

## 5A. Multi-node GPU — the migration this analysis never priced

> **This section is new, and it exists because the previous revision had a real gap.** §2 priced the code for a *single* node on both sides. It never asked what happens if GPUs later span hosts. The requester raised exactly that: *"we want to avoid huge rewrite in the future in the case we have multi-node gpus.. Ray is a huge production tool that might remove a lot of complexity that we have no experience in."*
>
> **I think this is the strongest pro-Ray argument in the whole file, and it was under-weighted.** It is treated here as a first-class section rather than an addendum, it is placed deliberately *before* the scoring in §6 so that §6 can account for it, and §5A.6 states it at full force even where it tells against my recommendation.
>
> **A standing caveat that applies to every row below: nothing in steps 1–8 touched multi-node.** The spike ran on one host and never started a second. Ray's multi-node capability here is **documented, not verified by us**; our migration cost is **[A]**, an estimate over unwritten code. This section is a *structural* argument on both sides, and it is the weakest-evidenced section in the document. That does not make it wrong — it makes it the section most in need of the labels.

### 5A.1 What our design currently assumes about node count

Our documents are unusually explicit about this, which makes the question answerable rather than speculative.

| Assumption | Where it is written |
|---|---|
| **"Not multi-node. Single host, multiple GPUs. Multi-host is a documented growth path."** | [`00_CONTEXT_AND_MOTIVATION.md`](../plan/00_CONTEXT_AND_MOTIVATION.md) §5, non-goals — the clearest statement in the repository |
| **"tool-swap runs on a shared DGX node."** Every shared-resource consequence in the lifecycle design flows from *one* node with neighbours on it | [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../plan/06_LIFECYCLE_TTL_AND_SCHEDULING.md) §1 |
| **Devices are bare integers.** `groups: gpu0: { max_resident: 1, devices: [0] }` — a device is an index, with no host qualifier anywhere in the config schema | [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../plan/06_LIFECYCLE_TTL_AND_SCHEDULING.md) §4 |
| **One Docker network; tools addressed by container name**, never by published host port (**D21**) | [`01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md) §9 |
| **State is in memory only. No database.** On boot the router *reconciles* by asking the backend which labelled containers are running | [`01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md) §7; **"No database"** is itself a non-goal in [`00_CONTEXT_AND_MOTIVATION.md`](../plan/00_CONTEXT_AND_MOTIVATION.md) §5 |
| **One global `asyncio.Lock` serialises all scheduling** — *"entirely sufficient at our scale — do not get clever"* | [`01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md) §5.1 rule 2 |

**That last row is the honest centre of this section.** The design does not merely *happen* to be single-node; it contains an explicit hedge — *"sufficient at our scale"* — and **multi-node is precisely the scale at which that hedge expires.** A single in-process lock cannot serialise scheduling decisions across hosts.

### 5A.2 What a single-node router must actually grow

Concretely, and split by who provides it.

| Capability needed at multi-node | Ray provides? | What we would write |
|---|---|---|
| **Cross-host scheduling and placement** | **Yes** — the core of what Ray is | The scheduler's *decision* survives (§5A.3); what is new is that placement must choose a **host** as well as a device, and act on a remote one |
| **Remote container lifecycle** | **Yes**, but through the same deprecated `container` key — and the **host-specific absolute path** `--runtime=/usr/bin/nvidia-container-runtime` (§3.2) must now be correct on *every* host. **The portability hit multiplies with node count** **[S]**/**[M]** | A `ContainerBackend` implementation that talks to a remote daemon rather than a local one |
| **Cluster membership and health** | **Yes** — GCS plus raylets | New component. We have nothing resembling this |
| **Node-failure handling** | **Partly.** Actors are restarted on another available machine, with controller data checkpointed to the GCS **on the head node** ([`architecture.md:44`](../plan/third-party-docs/ray-serve/architecture.md)) — **but see §5A.5, the head node itself is the catch** | New. Currently a "node" failure is the whole system failing, which needs no handling |
| **Request routing to the right host** | **Yes** — one proxy per node via `proxy_location` ([`architecture.md:16`](../plan/third-party-docs/ray-serve/architecture.md)) | Substantial proxy growth: today tools are addressed **by container name on one Docker network** (**D21**), which does not resolve across hosts |
| **Distributed state — who holds which GPU** | **Yes** — GCS | **A genuinely new component**, and it collides with the **"No database"** non-goal and with in-memory reconciliation |

### 5A.3 Rewrite or extension? The answer, in the concrete terms asked for

**This is the crux of the requester's worry, so it gets a direct answer rather than a balanced one:**

> **It is not a rewrite, and it is not a free adapter either. The scheduler stays; the backend and the proxy grow substantially; and a new distributed-state component appears that has no counterpart in the current design.**

Component by component:

| Component | Verdict | Why |
|---|---|---|
| **The scheduler** (`request_slot`) | **Survives, with a widened signature** | It is a **pure function of a state snapshot** — no I/O, no clock, no `nvidia-smi` ([`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../plan/06_LIFECYCLE_TTL_AND_SCHEDULING.md) §5.1, §5.3). `Decision.GRANT(device)` becomes `GRANT(host, device)` and the snapshot gains a host dimension. **The policy itself — LRU, `evict_cost` ranking, `min_residency`, in-flight immunity, group caps — is untouched.** [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../plan/06_LIFECYCLE_TTL_AND_SCHEDULING.md) §6 already anticipates this shape for a different growth path: *"Design the scheduler interface so this is a new `Policy` implementation, not a rewrite."* **[I]** |
| **The container backend** | **Grows substantially, behind the existing seam** | `ContainerBackend` is a `Protocol` and *"the ONLY component that touches Docker"* ([`01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md) §12). A remote implementation is a new class behind an interface that already exists. **[A]** — and note this rests on an unverified assumption that the Docker SDK addresses remote daemons cleanly enough for our use. **I did not verify that in this task and it is not cited; treat it as an assumption, not a fact** |
| **The proxy** | **Grows substantially** | **D21** — addressing by container name on one Docker network — is the specific design choice that does not survive. Cross-host needs host-qualified addressing or real service discovery |
| **Distributed state** | **New component, no counterpart today** | In-memory state plus backend reconciliation works because one process sees one daemon. Across hosts, "who holds which GPU" needs a store or a single-writer election. The one global `asyncio.Lock` stops being sufficient, by the design's own words |
| **The tool contract and the zoo** | **Untouched** | See §5A.7 — and this is the most important row in the table |

**Why scheduler purity is what makes this an extension rather than a rewrite.** [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §5 item 2 lists the pure scheduler as **never-trim**, on the grounds that *"it looks like purity theatre; it is the difference between a scheduler we can change confidently and one we cannot."* **Multi-node is the concrete case that vindicates that item.** A scheduler that had acquired I/O — that read `nvidia-smi` inline, or held Docker handles — would have to be rewritten to become distributed. A pure function over a snapshot is migrated by widening its types. **The audit's never-trim item is, in effect, already paying part of the multi-node insurance premium.** **[I]**

**The honest counter to my own point:** "the scheduler survives" is the cheapest third of the work. Membership, remote lifecycle, cross-host routing and distributed state are the expensive two-thirds, and **[`14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md) §8.6 already identifies cross-host scheduling as *"precisely the expensive feature, and precisely what makes Kubernetes worth its cost when you genuinely need it."*** I am not claiming the migration is small. I am claiming it is **bounded, and bounded to the router** — which is a different and weaker claim than "easy".

### 5A.4 "Complexity we have no experience in" — engaged directly

**The requester is right, and this deserves better than a reassurance.** Writing a distributed scheduler for the first time, under deadline, is **a genuinely different risk class** from working around a documented framework quirk. The two failure modes are not comparable:

- **A framework quirk** has a fixed shape. You read the source, you find `run_options=[]`, you write the workaround, and the cost is paid once and known. The spike is the proof: four private-source reads, four workarounds, all in hand **[S]**.
- **A distributed-systems bug** has an unbounded shape. Split-brain, partial failure, stale membership and races that appear only under load are the classic ones, and they are exactly the bugs that do not reproduce on a laptop. Nobody on this project has written one before — that is the requester's point and it is accurate.

**But the spike cuts both ways here, and I will not pretend otherwise.** The four private-source reads show *both* that we **can** debug Ray's internals **and** how much each Ray surprise costs: D22 was an **uncaught C++ abort with no message, diagnosed by `strace`** **[M]**. That is not a cheap debugging session either, and there were seven host runs and ~43 fixes around it.

**The distinction that survives the two-way cut, and it is the one that matters:** Ray's surprises are **bounded and already discovered** — we have found four and worked around all four. Distributed-systems bugs we have not written yet are **undiscovered and unbounded**. Those are not the same risk even when the per-incident cost is similar. §5A.6 gives that argument its full weight.

### 5A.5 What Ray's multi-node payout actually is — with the catch stated

**The payout is real.** Multi-node scheduling, membership, health and cross-host placement are the core of what Ray is, they are mature, and we would never write them as well. §4 item 5 already listed multi-node among the things we would never write, and this section is the reason that item was under-weighted.

**The catch is documented in Ray's own architecture page, and it is specific** ([`architecture.md:42`](../plan/third-party-docs/ray-serve/architecture.md)):

> *"If you aren't using KubeRay, when the Ray cluster fails, Ray Serve cannot recover."*

Combined with the measured single-node finding (§5.2 — cluster recovery is a three-command operator runbook and Serve applications **do not come back by themselves** **[M]**), the multi-node consequence is uncomfortable:

- The GCS and the controller's checkpoint live **on the head node** ([`architecture.md:44`](../plan/third-party-docs/ray-serve/architecture.md)).
- At multi-node, that head node becomes **a single point of failure for every host in the cluster**, not just for one.
- **Our measured §5.2 runbook therefore gets worse with node count, not better** — the blast radius of the failure we already measured grows. **[I]** from **[M]** + the cited page.
- **The form of Ray that genuinely solves multi-node robustly is KubeRay** — which is **option (b)**, rejected by both the requester and the engineer as too heavy, and closed on evidence in [ADR-0001](../plan/adr/0001-build-our-own-router.md) (§1).

**So Ray's multi-node answer is partial in exactly the place the requester cares about.** It removes the scheduling complexity we have no experience in — genuinely — and in exchange, at multi-node, it hands us a cross-host single point of failure whose recovery is a manual runbook, unless we adopt the Kubernetes option we have already rejected twice. **That does not refute the requester's argument. It bounds it, and the bound is the difference between "Ray solves multi-node" and "Ray solves multi-node scheduling".**

### 5A.6 The asymmetry, stated at full force against my own recommendation

**Per the bias discipline in the header, this is the argument for Ray that my recommendation must answer rather than deflect, so it is stated without hedges:**

> Ray's costs are **known, bounded, measured and already worked around**. We have the four private-source workarounds in hand. We have the runbook. We have the reaper. We have, now, the exact latency number. **Every one of Ray's costs in this document is a number or a source line.**
>
> A from-scratch distributed scheduler is an **unknown** cost, written by people who have not written one before. **Unknown costs are the ones that break schedules** — known ones get budgeted. A team that has never built a distributed system consistently underestimates it, and this document's own §9 concedes that our ~4,000-line estimate *"is already looking optimistic"* against ~9,700 lines of `src/` for M1 alone **[I]**.
>
> On the requester's own stated priority — *"robust and easy to maintain"* — a mature production framework that has solved multi-node for thousands of users is, on its face, the more robust answer to a multi-node future than code we have not written.

**That argument is correct on its own terms, and I do not have a measurement that refutes it.** What limits its force is not a counter-argument about Ray's quality but three facts about *when* and *whether* the cost is incurred — which is §5A.8.

### 5A.7 What the spike makes easier — and it is more than it looks

The requester's fear is a *"huge rewrite"*. The single most useful thing this analysis can do is be precise about **what would have to be rewritten** — and the spike's evidence narrows it substantially.

| Asset | Survives a later migration to Ray? | Evidence |
|---|---|---|
| **`tools.yaml`** — the config the scientists write | **Yes.** Ray's shape is *"`tools.yaml` with different key names"*; adoption adds a generator, it does not change the authored file | [`case-for-ray-native.md`](case-for-ray-native.md) §7; §2.2 of this document |
| **The tool images and the `container` runtime_env path** | **Yes, and this is now measured rather than hoped.** The `container` key is **proven** to run our fixture images with a real GPU **[M]** — the spike's whole GPU path is that key | §2 D36, ledger §§9L/9N |
| **The plain-data boundary at every tool call (D27)** | **Yes — and it is *the same constraint either way*.** Ray enforces it as a runtime pickle failure; [`ADR-0005`](../plan/adr/0005-one-uniform-batched-calling-convention.md) **already mandates** the uniform plain-data calling convention for our own reasons. A zoo built to ADR-0005 is already Ray-shaped at its most expensive boundary | §5.3; **[M]** D27 |
| **`handler.py`, the authoring contract, the runtime** | **Yes.** A handler imports nothing of ours beyond a metadata decorator | [`14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md) §8.5 |
| **The router** — backend, proxy, watchdog, state | **No. This is what gets rewritten** | — |

**This is [ADR-0001](../plan/adr/0001-build-our-own-router.md)'s surviving hedge doing precisely the job it was written for:** *"the models are the durable asset; the router is replaceable"* ([`14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md) §8.6). **The thing the requester fears rewriting — the zoo of ~20 tool images and the config the scientists author — is the thing the spike shows would *not* be rewritten.** What would be rewritten is the router: the ~4,000-line component the project has always treated as replaceable, and which the deletion arithmetic already prices at ~25–35 % **[A]**.

**Stated fairly in the other direction: a later migration is not free, and two things make it harder than the table suggests.** First, whatever we build in the meantime is thrown away, so the work is paid twice — once now, once at migration. Second, the Ray we would migrate to will not be Ray 2.57: **the four private-surface behaviours would need re-verifying against whatever version exists then** **[A]**, which is the same unbounded re-verification cost §3.1 charges against adoption, simply deferred. **Deferring does not eliminate it.**

### 5A.8 How likely, and when? Scoring multi-node on the demand axis

[`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §1 asks: *"Who asked for this, in what words? A quotable requirement, an inferred one, or none?"* Applied here, the document evidence is unusually consistent.

| Source | What it says about multi-node |
|---|---|
| [`00_CONTEXT_AND_MOTIVATION.md`](../plan/00_CONTEXT_AND_MOTIVATION.md) §5 | ***"Not multi-node. Single host, multiple GPUs. Multi-host is a documented growth path."*** An **explicit non-goal**, listed among non-goals so *"scope does not creep"* |
| [`13_OPEN_QUESTIONS.md`](../plan/13_OPEN_QUESTIONS.md) | Multi-node appears **only as a conditional trigger** — *"or when a second host is added"* — for revisiting Ray. Also §on payloads: paths *"[do] not survive a second host"*, again conditional |
| [`11_R8_CLIENT_PLAN.md`](../plan/11_R8_CLIENT_PLAN.md) | **Silent on node count entirely.** The client is a single `base_url` with a per-tool routing table; the migration plan is tool-by-tool, not host-by-host. **The actual consumer of this system has expressed no multi-node requirement** |
| [`14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md) §8.6 | *"a **second GPU host** is added"* — listed as a **trigger to re-evaluate**, alongside the observation that no such host exists today |
| [ADR-0003](../plan/adr/0003-ray-serve-not-adopted.md), [`15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md) §11 | *"A second host is added. Ray is genuinely multi-node without a cluster to operate"* — **already a recorded reversal trigger, in both documents** |
| **The requester, now** | *"in the case we have **multi-node gpus**"* — itself **conditional**, and the stated concern is *"avoid huge rewrite"* rather than *"we will have multi-node"* |

**The scoring, split because the two halves score differently — and this distinction is the whole point:**

| What is being scored | Demand | Reasoning |
|---|---|---|
| **The requirement "tool-swap must run across multiple nodes"** | ⚠ **Hypothetical.** Not quotable, not even inferred | No document commits to it. One document explicitly **excludes** it as a non-goal. Five documents treat it as a **conditional trigger**, which is the vocabulary of a thing that has not happened. The R8 client plan — the actual consumer — never mentions it |
| **The requirement "do not architect ourselves into a future rewrite"** | ✅ ***Quotable***, from the requester, verbatim, now | *"we want to avoid huge rewrite in the future"*. This is a real, stated, present requirement about **optionality**, and it is satisfiable independently of whether multi-node ever arrives |

**Why the split matters, rather than being a debating trick.** The audit's rule is that demand drives weight. If multi-node were scored as a single item it would be mis-weighted either way: scoring it *quotable* would justify paying Ray's full measured cost today for an event no document commits to; scoring it *none* would dismiss a concern the requester has now explicitly raised, which is itself a demand signal and the reason this section exists.

**The honest reading is that the requester has asked for insurance, not for multi-node.** Insurance is priced by premium and payout, not by whether the event is certain — which is §5A.9. And the plain statement the requester asked for: **multi-node is currently hypothetical in every requirement document, including the one belonging to the system that will consume tool-swap.** Taking it seriously anyway is correct, because the cost of being wrong is asymmetric and because a second GPU host is a plausible purchase for a growing research group.

**One fact that materially lowers the risk, and it is worth stating plainly: multi-node arrives with notice.** A second GPU host is a **procurement event**, not a runtime surprise. There is no scenario where we wake up distributed. Whatever the migration costs, we will see it coming by weeks or months — which is precisely the condition under which deferring a decision is cheap, and it is why the project already records this as a *trigger* rather than a *risk*. **[I]**

### 5A.9 The middle paths, priced

The requester's framing implies a binary — adopt Ray now, or face a rewrite later. **There are at least three positions, and the middle one is the status quo plus an explicit commitment.**

| Path | What it costs now | What it costs at multi-node | Verdict |
|---|---|---|---|
| **(i) Build single-node now behind interfaces that do not preclude a distributed backend** | **Nothing beyond what we already do.** `ContainerBackend` is already a `Protocol`; the scheduler is already pure and is already never-trim; ADR-0005 already mandates the plain-data boundary. **The insurance is already largely bought and paid for** | The router is rewritten; the zoo, `tools.yaml` and the tool contract are not (§5A.7) | **Best value.** It answers the *quotable* demand (avoid a future rewrite of the durable assets) without paying for the *hypothetical* one |
| **(ii) Static federation when a second host appears** | Nothing now | **Much less than a cluster.** A second host runs its own tool-swap; the first forwards tools it does not own, over the proxy we already built — llama-swap's `peers` model, recorded in [`14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md) §8.6. **No control plane, no distributed state, no scheduler rewrite — and no cross-host scheduling either** | **Genuinely underrated, and it is the answer to "we have more GPUs" as opposed to "we need one scheduler across all GPUs".** Those are different requirements and only the second needs Ray. §8.6's own advice: *"price federation first"* |
| **(iii) Adopt Ray now, for a future that may not arrive** | **The full measured cost, today**: ~100 s default displacement vs ~5 s **[M]**, a deprecated API with a per-host absolute path, four private-surface behaviours re-verified every upgrade, three failure modes that report success, an operator runbook | Lower — but **not zero**, because robust multi-node Ray is KubeRay (§5A.5), which is option (b) | **Pays a known premium now for a conditional, partial payout.** The premium is the one item in this document that is fully measured |
| **(iv) Adopt Ray at the point multi-node becomes real** | Nothing now | The router migration, **plus** re-verifying the private surface against a future Ray version **[A]** | **Viable, and it is what paths (i) and (ii) preserve.** This is the option that the *trigger* language in five documents was written to keep open |

**Path (i) with (ii) held in reserve and (iv) as the trigger is the same position the repository already holds** — [ADR-0003](../plan/adr/0003-ray-serve-not-adopted.md) and [`15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md) §11 both already name *"a second host is added"* as a reversal trigger. **What was missing was not the trigger; it was the pricing of what the trigger costs when it fires.** §5A.7 is that pricing, and the answer — the router is rewritten, the zoo is not — is the answer to the requester's actual question.

Using [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §1: **class** (⬛ forced · ⬜ chosen · ⚠ elective), **demand**, **carrying cost**. The audit's hunting rule is *"an elective decision answering an inferred demand at high carrying cost"*.

### 6.1 Option (a) — adopt Ray, accept manual recovery

| Component | Class | Demand | Carrying cost |
|---|---|---|---|
| Ray cluster (6 process types) + rootless podman on a shared DGX | ⬜ chosen | ***quotable*** — *"prioritise the use of existing frameworks"* (engineer), *"robust and easy to maintain"* (requester) | **High, permanent.** Six process types to operate; a Ray/Python lockstep across every image, confirmed **[M]**; podman on a machine we do not administer |
| Dependency on the **deprecated** `container` runtime_env key for every GPU tool | ⬛ **forced** by adoption — the modern API structurally cannot **[S]** | none — it is a consequence | **High.** Mutual exclusion with most of `runtime_env`; a host-specific absolute path in every tool config; the path Ray is retiring |
| Four private-source behaviours re-verified per upgrade | ⬛ forced by adoption | none | **High and unbounded.** No compatibility promise on `_private/`; re-verification means re-running the spike |
| Config generator (`tools.yaml` → Serve) | ⬜ chosen | inferred | **Medium.** New code replacing deleted code, plus the D32 guard |
| Supervisor for the head-node runbook | ⬛ forced by unattended operation | ***quotable*** — guardrail 8 | **Medium.** Three commands plus a config re-apply, automated and tested |
| Container reaper | ⬜ chosen | inferred | **Low.** One periodic job |
| Eviction policy as a Ray application-level autoscaling policy | ⬛ forced (written either way) | ***quotable*** — **D25** | **Medium.** Same policy, but now atop an experimental API instead of a pure function |
| **~100 s default displacement where the container costs ~5 s** **[M]** | ⬛ forced by adoption *as configured*; ⬜ chosen if tuning works | none — it is a consequence | **High, and newly measured** (§5.1, ledger §9T). ~15× on P90, bimodal, 40 % of requests. **Tunable in principle, untested in practice** **[A]** — §12 |
| **Deleted:** M2, M3 proxy internals, M3.5, M6 watchdog, M7 collector | — | — | ***Negative — the real win.*** ~25–35 % of v1 **[A]** |
| **Gained free:** dashboard, per-replica status, metrics, object store, replica self-healing **[M]** | — | — | ***Negative.*** Genuine, and better than what v1 would build |
| **Gained: a multi-node path we would otherwise write** | ⬜ chosen | ⚠ **hypothetical** for multi-node itself; ***quotable*** for *"avoid huge rewrite"* (§5A.8) | ***Negative, and the largest negative item after the deletion*** — but **partial**: robust multi-node Ray is KubeRay (§5A.5), and the head node becomes a cross-host single point of failure whose recovery is the measured manual runbook |

**Audit verdict on (a):** **chosen**, answering a **quotable** demand, at **high** carrying cost — with a large negative-cost offset. It is *not* the pattern the audit hunts (that pattern is elective + inferred + high, which is what soft unload was). **The decision is legitimate on the audit's own terms**; it turns on whether the negative offset exceeds the high permanent cost. §11 is where I take a position.

**What the two new inputs did to this table, in opposite directions:** step 8 **added a high-carrying-cost row that is fully measured** (~100 s vs ~5 s), and multi-node **added a large negative-cost row whose demand is hypothetical and whose payout is partial**. The audit's own rule — demand drives weight — is what separates them: **the cost is quotable-demand-relevant and measured today; the benefit answers a demand no requirement document commits to (§5A.8).**

### 6.2 Option (c) — keep building our router

| Component | Class | Demand | Carrying cost |
|---|---|---|---|
| Container backend + lifecycle (M2) | ⬛ forced by **D2** | ***quotable*** — *"the environment of each tool should be easy to set up"* + ~300 conflicting pins observed | **Medium.** Docker SDK behind a protocol; state machine; testable entirely with `FakeBackend` **[I]** |
| Proxy (M3) | ⬛ forced by **R3**/**D4** | ***quotable*** | **Medium.** httpx streaming through FastAPI |
| TTL watchdog + eviction (M6) | ⬛ forced by **D25** | ***quotable*** — *"we don't want to wait for TTL"* | **Medium.** One timer; a pure scheduler of a few hundred lines |
| Log collector (M7) | ⬜ chosen | **R1** | **Low–medium.** Rotating files; llama-swap's `log_output` switch |
| GPU passthrough | ⬛ forced | environmental | **Lower than Ray's.** Docker `--gpus` works on this host **[M]** (ledger §9L), so no legacy API and no host-specific absolute path in tool configs |
| Crash recovery | ⬛ forced by guardrail 8 | ***quotable*** | **Medium and [A] — unwritten.** This is where option (c) is weakest and where §7.2's credit to Ray bites |
| Bus factor | — | — | **High and unpriceable.** The plan scores itself *"Worst"*, and no spike changes that |
| **Swap latency** | — | — | **Low, and newly measured.** Our router inherits the container's **~5 s**, not Ray's ~100 s **[M]** (§5.1). This row previously read as an unattributed risk; it is now a modest, known cost |
| **A future multi-node migration** | ⚠ elective *insurance* | ⚠ **hypothetical** requirement; ***quotable*** concern (§5A.8) | **Deferred, bounded to the router, and partly pre-paid.** The pure scheduler survives, the `ContainerBackend` seam already exists, ADR-0005 already mandates the plain-data boundary. **The zoo, `tools.yaml` and the tool contract are not rewritten** (§5A.7). What is thrown away is the router — the component the project already calls replaceable |
| Everything Ray would give free | — | — | **Positive cost.** We build a smaller `/status` and no dashboard, and we defer the multi-node path rather than having it |

**Audit verdict on (c):** almost every component is **forced** by a **quotable** demand at **medium** carrying cost. That is the profile [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §2 finding 2 asserted — *"that is proportionate"* — and the spike does **not** falsify it (§10.1). What the spike *does* falsify is the second half of that sentence, *"the alternatives cost more (§6)"*, which was stated on desk evaluation and is now a measured question with a genuinely mixed answer.

### 6.3 The two profiles side by side

|  | (a) Ray | (c) Our router |
|---|---|---|
| Code we own | **Less** — by ~25–35 % **[A]** | More |
| **Swap latency (measured)** | **~100 s P90 on the default path, bimodal** **[M]** | **~5 s, tight, no tail** **[M]** — the inherited container cost only |
| **Multi-node, if it ever arrives** | **Provided** — though robustly only via KubeRay, which is option (b) (§5A.5) | **A router migration** — bounded to the router; the zoo and `tools.yaml` survive (§5A.7) **[A]** |
| **Testability of the code we own** | **Worse.** Correctness depends on cluster-level conditions the spike needed 7 host runs and ~43 fixes to observe **[I]** | **Better.** M2/M3/M6 are fakes plus one real round trip; the scheduler is pure |
| Dependencies carried | Ray (private-surface + deprecated key), podman, version lockstep **[M]**/**[S]** | Docker, FastAPI, BentoML — all per-image and gradual |
| Failure modes handled | Ray's, including three that report success **[M]** | Ours, including ones we have not met yet **[A]** |
| Hours spent | Operating a cluster; re-verifying private behaviour per upgrade | Writing and maintaining ~4,000 lines **[A]** |
| Bus factor | **Much better** | *"Worst"*, by the plan's own score |
| Recovery | Replica: automatic **[M]**. Cluster: operator runbook **[M]**, whose blast radius **grows** with node count (§5A.5) | Both **[A]**, unwritten |

**This table is the analysis.** Everything else is its derivation.

**What this revision changed in it.** The previous version split 3–3 and said the two decisive rows — testability and bus factor — pointed in opposite directions. **It is no longer an even split.** Step 8 added a row that (c) wins **on measurement rather than estimate** (~5 s against ~100 s), and multi-node added a row that (a) wins **on structure rather than measurement**, with a partial payout (§5A.5) against a hypothetical demand (§5A.8). (a) now wins **bus factor, recovery-today and multi-node-if-it-arrives**; (c) wins **testability, dependencies, failure modes and latency**.

**The asymmetry that matters is not the count of rows but their evidence class: (c)'s wins are increasingly [M], and (a)'s remaining wins are [A] or conditional.** That is a real shift, and §11.0 is where it is weighed rather than merely noted.

---

## 7. Engaging the strongest pro-Ray arguments directly

Not summarising them — testing them against the spike.

### 7.1 *"Every objection against Ray has fallen — nine for nine"* ([`case-for-ray-native.md`](case-for-ray-native.md) §4)

**Strengthened, not weakened, by the spike.** Two further "Ray fails" verdicts were recorded and both retracted as our own measurement faults (§4 of the results doc). The inference [`case-for-ray-native.md`](case-for-ray-native.md) draws — *"the conclusion was fixed before the reasons were gathered"* — is a fair reading of the record.

**But the spike adds something that changes its force, and this is the honest counterweight:** the spike's findings are of a **different kind** from the nine. The nine were capability claims — *"Ray can't isolate", "Ray can't evict", "Ray has nowhere for a scheduler"* — and capability claims lose to an hour of reading, which is exactly what happened nine times. §2's four findings are **cost and failure-mode findings established by source-reading and measurement**: `run_options=[]`, the wholesale option replacement, the downscale clock, the explicit-zero autodetect. They are not the kind of claim that falls to more reading, **because reading is how they were produced**.

**So the track record is real evidence about the process and weak evidence about the current findings.** Both halves of that sentence are load-bearing.

### 7.2 *"You compared Ray's documented limits against your unwritten ideals"* ([`case-for-ray-native.md`](case-for-ray-native.md) §10.4)

**Conceded, and it applies to this document too.** Ray's replica recovery is **[M]**; our boot reconciliation is **[A]**. Ray's cluster-recovery procedure is a **[M]** three-command runbook; our *"restart the router"* has never restarted anything. §6.3 marks every **[A]** row for exactly this reason, and the honest reading is: **option (c)'s recovery story is currently the weakest-evidenced claim in the whole comparison, and it is on our side of the ledger.**

### 7.3 *"'`image_uri` is experimental' is a double standard — you accept BentoML's beta pins without this scrutiny"* ([`case-for-ray-native.md`](case-for-ray-native.md) §6, §10.2)

**Was a fair hit; the spike partly answers it.** The double standard was real: BentoML shipped a beta-pinned OpenTelemetry family and `cattrs<23.2.0` into every tool image without comparable scrutiny.

**What the spike changes** **[S]**/**[M]**: the objection is no longer *"experimental, therefore risky"* — a judgement — but *"the documented API structurally cannot host a GPU tool, and the working path is the deprecated one"*. That is a measured capability fact plus a source-read, and it is not symmetric with a beta version pin. **The distinction that matters: BentoML's risk is a version we chose and can upgrade one image at a time; Ray's is an API surface we cannot route around.**

### 7.4 *"You cited our own design choices (D21) as obstacles"* ([`case-for-ray-native.md`](case-for-ray-native.md) §10.3)

**Conceded and dropped.** `--network=host` breaking **D21** is circular, and D21 does not appear anywhere in this document's cost tables. A Ray-native design would simply not have made that choice.

### 7.5 *"The real problem is over-documentation, not over-engineering"* ([`ray-native-reconsideration.md`](ray-native-reconsideration.md) §4)

**Still correct, still orthogonal, and worth restating because it is the cheapest available win either way.** [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §2 item 5 says it outright: eighteen planning documents for a v1 of *"perhaps 4,000 lines"*. Since then this spike has added a protocol, a continuation ledger of 1,463 lines, a results document and — with this file — four more analyses.

**Adopting Ray would delete about a third of the code and none of the documents.** If "simplicity" is the priority, the corpus is a larger and cheaper target than the framework, and it is available under either option.

### 7.6 The highest-leverage question, which is still unanswered and is not about frameworks

Both [`ray-native-reconsideration.md`](ray-native-reconsideration.md) §5 and [`bias-audit-and-decision-procedure.md`](bias-audit-and-decision-procedure.md) §4 keep asking it, and both flag their own bias in asking:

> **If a request for tool B arrived while idle tool A held the GPU, and B simply waited for A's TTL — how bad is that, concretely, in seconds, for your actual traffic?**

**The spike makes this question sharper, and step 8 has changed its answer materially.** **D25** (*"we don't want to wait for TTL as it could take quite some time"*) is the gate that eliminates every off-the-shelf candidate. The previous revision argued that if displacement costs 100 s 40 % of the time, the gap between "displace" and "wait with `ttl` tuned to 60 s" is narrower than **D25** assumes — and therefore that **D25**'s premise was in doubt.

**Step 8 removes that doubt, and it removes it in D25's favour** **[M]** (ledger §9T). Displacement **without an orchestrator** costs **3.9–6.9 s, every time, with no tail**. A 5-second displacement is unambiguously better than waiting out a 60-second TTL, so:

- **For our own router, D25 is vindicated and is cheap to satisfy.** The premise *"displacement takes quite some time"* was true of Ray's default path, not of the container.
- **For default-configuration Ray, D25's gate bites hardest**, because there displacement is the 100 s path.
- **The question does not disappear**, because it is still unanswered for real traffic, and a *"waiting is tolerable"* answer would still shrink our scheduler to a TTL timer and re-admit off-the-shelf candidates ([`ray-native-reconsideration.md`](ray-native-reconsideration.md) §5). **But it is now much less likely to flip the decision**, because the thing it would trade away — displacement — turns out to cost 5 s rather than 100 s. **[I]**

**[ADR-0004](../plan/adr/0004-hard-stop-only-in-v1.md) was produced by re-asking exactly this kind of question and is the largest win in this plan's history.** It still costs one sentence from the requester, and it is still worth asking — it is simply no longer the highest-leverage open item (§12).

---

## 8. Where the pre-spike desk evaluation was wrong

This matters beyond bookkeeping: it calibrates how much weight to give the remaining **un-spiked** arguments in [`14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md) and [`15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md).

| Desk claim | What measurement showed | Verdict on the desk method |
|---|---|---|
| **`image_uri` delivers D2** — the whole basis for *"D2 is satisfiable on Ray"* ([`15`](../plan/15_RAY_SERVE_EVALUATION.md) §1 concession 1, [ADR-0003](../plan/adr/0003-ray-serve-not-adopted.md) amendment) | **True for isolation, false for GPU tools.** `image_uri` cannot pass a GPU **[S]**/**[M]**; the modern path allocated **zero VRAM** while reporting HEALTHY. The working path is the **deprecated** `container` key | **Wrong in the load-bearing half.** Both the pro-Ray and anti-Ray documents built on `image_uri`; neither noticed. The docs do not say this — only the source does |
| ***"Path 1: allocation, not preemption — a replica waits for a held GPU, exactly as a Kubernetes pod goes `Pending`"*** ([ADR-0003](../plan/adr/0003-ray-serve-not-adopted.md) fork table, **D25** row) | **Refuted as stated** for the externally-driven case: **20/20 displacements at cadence, zero errors** **[M]** | **Wrong.** This was the fork that *"is the whole argument"*. What survives is the cost (P90 103 s), not the impossibility |
| ***"No volume mounts for `image_uri`"*** — presented in [`ray-native-reconsideration.md`](ray-native-reconsideration.md) §2 as *"fatal to the current tool contract"* and *"a bigger problem than the lockstep"* | **Correct as source-read** ([`image_uri.py`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:76) mounts only Ray's tmp dir) — **but the spike never tested it**, because §10.1 baked weights and payloads into the images. And the legacy `container` key we now depend on **does** forward `run_options`, so `-v` is reachable on that path **[S]** | **Partly self-undermining.** The objection was raised as near-fatal, then rendered untested by a scope reduction, and the API we would actually use may not have the limitation at all |
| **Version lockstep** — *"the strongest single ground"* ([`15`](../plan/15_RAY_SERVE_EVALUATION.md) §4.2), later conceded as *"a cost, not a gate"* | **Confirmed as a real coupling** **[M]**: fixtures had to be built from the exact base tag `docker.io/rayproject/ray:2.57.0-py311-gpu` | **Right about the fact, wrong about the weight** — and the concession was already made before the spike |
| ***"Cannot recover without KubeRay"*** — quoted from Ray's own architecture page | **Substantially confirmed, and refined** **[M]**: cluster recovery is a three-command operator runbook plus a config re-apply; **replica** recovery is fully automatic. The doc sentence conflated two very different properties | **Right, but coarse.** Measurement made it more accurate *and* less alarming |
| ***"Three experimental-or-alpha APIs"*** as the headline risk | **Understated, and on the wrong axis.** The risk is not the "experimental" label — it is that the modern path structurally cannot do the job (D36) and the working path is deprecated and carries a silent-replacement trap (D32) | **Wrong in emphasis.** The real risk was worse than the stated one, and stated in the wrong vocabulary |

**The calibration this yields, and it cuts both ways:**

1. **Desk evaluation got the *shape* right and the *load-bearing details* wrong.** Every claim that rested on documentation ("experimental", "cannot recover", "lockstep") survived in outline and was wrong in magnitude or precision. Every claim that rested on a *capability inference from documentation* ("allocation, not preemption") was **refuted**.
2. **Only source-reading produced durable findings.** All four §2 findings came from reading `_private/`. None is in any Ray document. This vindicates the repository's own rule against documenting behaviour from memory or from docs alone — and it means **the remaining un-spiked arguments on both sides should be discounted heavily**.
3. **The specific un-spiked arguments that should now be treated as weak:** the mount objection (§8 row 3), the podman-prerequisite objection (step 7 showed rootless podman coexisting with 9 running Docker containers, no `--privileged` needed **[M]** — so this one *weakened against us*), and any claim about `@serve.batch` versus BentoML adaptivity, which no measurement here touches.

---

## 9. What the evidence cannot tell us

Untested, per [`spike-E-results.md`](spike-E-results.md) §5.2, and each with what it would change:

| Unknown | Status | What it could change |
|---|---|---|
| ~~**The latency attribution baseline**~~ | **RESOLVED** by step 8 **[M]** (ledger §9T, D45): container ~5 s, Ray's default path ~100 s | *Was* the most decision-relevant unknown. It resolved **against** Ray. §5.1 |
| **Whether Ray's displacement path tunes from ~100 s to ~10 s without destabilising the autoscaler** | **Untested** **[A]**. `downscale_to_zero_delay_s` is tunable and part of the rest is `look_back_period_s` **[S]** | **The new most decision-relevant unknown**, and the successor to the row above. It decides whether §5.1 is a hard con or a soft one. §12 |
| **Multi-node anything** | **Untested by every step 1–8.** The spike ran on one host and never started a second | §5A is a structural argument with **no measurement behind it on either side** — Ray's multi-node capability is documented, not verified here, and our migration cost is **[A]** |
| **D18 payload-by-reference** (`s3://`) | **Not tested** — scope-reduced (§10.1). No fetch cost is known; step 4's 0.097 s figures are **local disk reads inside a container** | Any thrash pricing that assumes remote payloads is unpriced. Bears on **D18** under either option |
| **Step 5 mechanism B** (declarative config re-apply) | **Not implemented** — a printed stub | Only the external-scaler path is measured. The alternative displacement mechanism is unmeasured |
| **Pre-emptibility of Ray's own autoscaler** | **Not tested.** Step 5 ran under `external_scaler_enabled`, which *forbids* Serve's own autoscaling for those apps | Ray can be **driven** to preempt; whether its own timer yields to a higher-priority request is unknown. This is the exact **D25** semantic |
| **The Docker / CDI path** | **Untested and unreachable** — Ray hardcodes `container_driver = "podman"` at [`image_uri.py:76`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:76) **[S]** | *"The single biggest caveat on D36."* If `image_uri` works under Docker, §3.2 weakens substantially and the deprecated-API dependency may disappear |
| **Newer Ray versions** | Everything is Ray 2.57.0; **none of D22/D32/D36 is version-checked** | A later release could fix any of them. Equally, a later release is where private-surface behaviour changes |
| **Multi-GPU and multi-tool scale beyond two** | Not tested. The gate ran on **one** of eight A100s, with **two** tools | Nothing is known about a full zoo (~20 images) on 8 GPUs — which is the actual deployment |
| **Where app builders execute** | **Refused as a claim**, not found — needs a negative control (§3.2) | Bears on whether a generic config generator is really generic |
| **`vfs` vs `overlay` cold start** | **Not A/B'd** (would mutate a shared host) | Every latency figure implicitly depends on `overlay`; a `vfs` host would likely be far worse **[A]** |
| **Origin of the 0755 event dirs (D22)** | **Unconfirmed** — most likely Ray's C++ side | The empirical finding stands; the mechanism does not |

**Five things this document itself cannot tell you**, stated because they are the boundaries of the analysis:

1. **Both code estimates are [A].** ~25–35 % deletion and ~4,000 lines are both guesses over unwritten code. `src/` is currently ~9,700 lines across 33 Python files — **M1 config and CLI, largely** — which is already more than double the audit's whole-v1 estimate for the router core. That is worth noticing: **the audit's ~4,000-line estimate is already looking optimistic**, and if v1 is materially larger than 4,000 lines then the absolute size of Ray's deletion grows too. **[I]**
2. **No hours were measured, on either side.** Every "maintenance burden" claim is a structural argument, not a timing.
3. **Nothing was measured about ~20 tools.** Every measurement is two tools on one GPU.
4. **Nothing was measured about multi-node — on either side.** No step 1–8 started a second host. §5A is the most consequential section in this revision and it is **entirely structural argument**: Ray's multi-node capability is taken from its documentation, and our migration cost is **[A]**. **The section most likely to be quoted is the section with the least measurement behind it**, and a reader should weight it accordingly.
5. **Nothing was measured about the bus factor**, which remains the strongest un-spiked pro-Ray argument (§4 item 6) and is exactly as strong now as before step 8.

**The step-8 figures carry three limits of their own**, restated here so they are visible outside §5.1: **Ray's teardown half was not measured** (`mode=full` was not run); **~95 s is Ray's default configuration, not a demonstrated floor** — the tuning question is untested and is now §12; and the figures are **20 samples, one run, one host, warm image store**, which ledger §9T itself says should be confirmed by a second run before an ADR quotes them as settled.

---

## 10. What the spike falsifies in the existing position

### 10.1 [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §2 finding 2

> *"The router itself is not the problem. After the descope, the core is a config loader, a container backend, a pure scheduler of a few hundred lines, a proxy and a watchdog. That is proportionate, and **the alternatives cost more (§6)**."*

**First clause: not falsified.** §6.2 scores every component as forced-by-quotable-demand at medium cost. The spike gives no reason to think the router core is disproportionate.

**Second clause — *"the alternatives cost more"* — is now a measured question with a mixed answer, and it must be downgraded.** It was asserted from desk evaluation (§6 of the audit cites [ADR-0001](../plan/adr/0001-build-our-own-router.md) and [`15`](../plan/15_RAY_SERVE_EVALUATION.md), both pre-spike). Measurement shows:

- Ray **does** delete five milestones' worth of scope **[A]**, and it **does** deliver step 3, replica self-healing and 20/20 reliability **[M]**;
- Ray **also** costs a deprecated-API dependency, four private-source behaviours, three silent failure modes and an operator runbook **[M]**/**[S]**.

**"The alternatives cost more" is not established by the evidence. It is defensible as a judgement, and it should be labelled as one.** The audit's own §6 sentence — *"every one of them requires operating a cluster and still writing the scheduler"* — survives intact and is the strongest true version of the claim.

**Revision 2 update, in both directions.** Step 8 moves this clause **toward** the audit's original assertion on one specific, measured axis: on **swap latency**, the alternative does cost more — ~100 s against ~5 s **[M]** (§5.1). That is no longer a judgement. **But §5A moves it the other way on a different axis**: on **a multi-node future**, the alternative may cost *less*, because Ray provides cross-host scheduling we would otherwise write (§5A.2). **So the clause remains a judgement overall — it is simply a better-informed one, with one axis now measured and one newly identified and unmeasured.** The downgrade stands; what has changed is that the mixed answer is now mixed for stated reasons rather than for want of evidence.

### 10.2 [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §3 row **D29** — *"Ray Serve not adopted · carrying cost: none — it is a refusal"*

**Falsified.** The refusal's carrying cost is not none. It has cost: [`14 §3.3`](../plan/14_ALTERNATIVES_EVALUATION.md), three revisions of [`15`](../plan/15_RAY_SERVE_EVALUATION.md), [ADR-0003](../plan/adr/0003-ray-serve-not-adopted.md) plus two amendments, four analysis documents in `plans/`, a spike protocol, a 1,463-line ledger, a results document, seven host runs, ~43 defect fixes — and this file. **A refusal that has to be re-defended seven times is not free**, and by the audit's own §7 finding (over-documentation is the real risk) this is the largest single instance of it in the repository.

### 10.3 [ADR-0003](../plan/adr/0003-ray-serve-not-adopted.md) — its own falsifier fired, and the ADR says what to do

The ADR names one falsifier: *"if `runtime_env` provides a production-viable **per-deployment OCI image** boundary that composes with per-device GPU pinning, then Ray Serve delivers D2 and D9 and D25 together, the fork above dissolves, and this decision is wrong."*

| Half | Result |
|---|---|
| Per-deployment OCI image boundary | **Confirmed** **[M]** — step 1, two deployments, two images, proven by a baked-in marker that cannot be set through `runtime_env` |
| Composes with per-device GPU pinning | **Yes, but only via the legacy `container` key** **[M]**/**[S]** — with mutual exclusion and a host-specific absolute path |
| *"Production-viable"* | **The genuinely open word.** Deprecated API, silent traps, operator runbook. This is where the ADR's revision has to do its work |

**By the ADR's own terms** — *"if it came back the other way, this document is wrong and should be rewritten rather than patched"* — **revision is warranted.** The results document §9 already records this and notes the revision is being done separately. (I have not touched the ADR; the constraints forbid it.)

**Two further ADR-0003 claims the spike specifically falsifies:**

1. **The fork's D25 row** — *"allocation, not preemption"* — **refuted as stated** for externally-driven displacement (§8).
2. **The experimental-API risk was *understated***, not overstated: the modern path structurally cannot host GPU tools, and the working path is deprecated (§8, last row).

**And one it strengthens, materially:** the recovery objection was a *qualification* in the ADR and is now a **recorded gate failure** — step 6 FAIL as written, with 109 orphaned containers **[M]**.

### 10.4 [ADR-0001](../plan/adr/0001-build-our-own-router.md) — untouched, and worth saying

Nothing in the spike bears on Spike A (llama-swap parses `body.model`), Spike B (Kubernetes allocates rather than preempts) or Spike C (the models do not fit). **ADR-0001 stands.** It is also the reason option (b) is not analysed here (§1).

---

## 11. Recommendation, with its conditions

**I recommend option (c) — continue building our router — with three conditions attached, one of which is a genuine commitment to reverse if it fails.** I am recommending, not deciding; the protocol makes this the requester's call, and §11.4 states plainly what would change my mind.

### 11.0 Does the recommendation change? No — and here is the weighing, not a split difference

**The recommendation stands. It did not flip, and it is stronger than it was, but not for a comfortable reason: the two new inputs are of different evidence classes, and that is what decides it rather than any tally of pros and cons.**

The two inputs genuinely pull in opposite directions and it would be dishonest to pretend otherwise:

| Input | Direction | Evidence class | Timing |
|---|---|---|---|
| **Step 8 — ~100 s default displacement vs ~5 s container** | **Against Ray**, strongly | **[M]** — measured, pre-specified, VRAM-verified, 20/20 | **Today.** A cost paid from the first week |
| **Multi-node migration risk** | **For Ray**, strongly | **[A]** + structural — no step 1–8 touched it | **Conditional**, on a procurement event no document commits to (§5A.8) |

**The single consideration that decided it: the cost is certain and present; the benefit is conditional and partial — and the conditional benefit's payout arrives with months of notice, while the certain cost is paid from day one.**

Unpacked, because that sentence is doing all the work:

1. **Ray's headline cost is now measured rather than suspected.** The previous revision could not say whether the 103 s P90 was Ray's or the container's, and honestly priced it both ways. It is Ray's: **~15× on P90, bimodal, 40 % of requests, against a plain-podman cycle that never exceeded 6.91 s** **[M]**. This is the branch §12 specified **in advance**, which is what makes it evidence rather than a rationalisation.
2. **The multi-node benefit is real but partial**, and the bound is Ray's own documentation: *"If you aren't using KubeRay, when the Ray cluster fails, Ray Serve cannot recover"* ([`architecture.md:42`](../plan/third-party-docs/ray-serve/architecture.md)). Robust multi-node Ray is **KubeRay = option (b)**, which both the requester and the engineer rejected as too heavy and which [ADR-0001](../plan/adr/0001-build-our-own-router.md) closed on evidence. **Adopting Ray now to avoid a future migration may buy a future migration to Kubernetes instead.**
3. **The multi-node demand is hypothetical in every requirement document**, including the R8 client plan belonging to the system that will actually consume tool-swap, and [`00_CONTEXT_AND_MOTIVATION.md`](../plan/00_CONTEXT_AND_MOTIVATION.md) §5 lists multi-node as an **explicit non-goal** (§5A.8). The audit's rule is that demand drives weight.
4. **The migration, when priced, is not the rewrite the requester fears.** It is bounded to the router: **the scheduler survives because it is pure, the backend seam already exists, `tools.yaml` and the ~20 tool images are untouched, and ADR-0005's plain-data boundary is the same constraint either way** (§5A.3, §5A.7). The durable assets are not at risk. **That is the direct answer to the concern, and it is why the concern does not flip the recommendation.**
5. **Multi-node arrives with notice.** A second GPU host is a procurement event, not a runtime surprise (§5A.8). Deferring a decision that will announce itself months ahead is cheap; paying a measured ~100 s latency cost and an unbounded private-surface re-verification cost today, against it, is not.

**What would have flipped it.** Had step 8 shown container startup dominating — the other branch §12 named — then Ray's largest measured con would have dissolved, our own router would have inherited a ~100 s swap, **D25**'s premise would have weakened, and the multi-node argument would have arrived with Ray's cost side already much lighter. **On that combination I would have recommended re-opening the framework question, and I said so in advance.** It did not happen.

**What this recommendation does *not* do is dismiss the requester's argument.** §5A.6 states it at full strength and I do not have a measurement that refutes it: **unknown costs break schedules, and a first distributed scheduler is an unknown cost.** My answer is not that the risk is small — it is that **the insurance against it is already bought** (pure scheduler, backend seam, ADR-0005 boundary, `tools.yaml` stability), that it is **cheaper to keep buying than to pay Ray's measured premium today**, and that federation (§5A.9 path ii) answers *"we have more GPUs"* without answering the much more expensive *"we need one scheduler across all GPUs"*. **§11.4 adds the multi-node trigger explicitly, with what it costs when it fires — which is what was actually missing before.**

### 11.1 The recommendation in one paragraph

On the axis the requester named — simplicity and long-term maintainability — the decisive consideration is **not the volume of code but the verifiability of it**. Option (c) keeps ~25–35 % more code **[A]**, and every piece of that code is a container backend, a proxy, a watchdog and a log collector that are testable with fakes and an injected clock, on a laptop, in milliseconds ([`09_IMPLEMENTATION_PLAN.md`](../plan/09_IMPLEMENTATION_PLAN.md) M2, and the audit's never-trim item 2, scheduler purity). Option (a) writes *less* code but makes its correctness depend on four private-source behaviours with no compatibility promise **[S]**, a deprecated `runtime_env` key that is mutually exclusive with most of the API and requires a host-specific absolute path in every GPU tool's config **[M]**, and three failure modes that report success **[M]** — on a system meant to run unattended. **Step 8 adds a fourth measured item to that side: Ray's default displacement path costs ~100 s where the container costs ~5 s** **[M]**. The spike is itself the measurement of how expensive those conditions are to verify: seven host runs and ~43 defect fixes to observe them **once**, on **two** tools and **one** GPU. **Against that, the strongest pro-Ray arguments are not answered by this paragraph and I will not pretend they are: the bus factor (the plan scores itself "Worst", and no spike changed that), the fact that Ray's recovery is measured while ours is unwritten, and the multi-node migration the requester has now named. The first two are unchanged; the third is answered in §5A and weighed in §11.0. They are why the conditions below are not decoration.**

### 11.2 Condition 1 — ~~resolve the latency attribution~~ **RESOLVED; the successor is the tuning question**

> **This condition has been discharged.** Step 8 ran (ledger §9T, D45). The answer was the branch that **strengthens** this recommendation: the ~100 s is Ray's orchestration, and our own router inherits ~5 s.

**The successor condition, and it is narrower:** if Ray is to stay in contention at all, someone must establish **whether its displacement path tunes from ~100 s to ~10 s without destabilising the autoscaler** (§12). That single number is what makes §5.1 a **hard** con or a **soft** one, and this document deliberately does not claim *"Ray cannot go faster"* — only that its **default** path costs ~100 s where the container costs ~5 s. **If the requester is inclined toward Ray on multi-node grounds, this is the measurement to run before deciding, not after.**

### 11.3 Condition 2 — answer the wait-versus-displace question (one sentence from the requester)

Per §7.6. If waiting is tolerable, our scheduler shrinks to a TTL timer, the gate that eliminates every off-the-shelf candidate disappears, and **the reuse argument likely wins outright**. It still costs nothing to ask.

**Step 8 has lowered this condition's leverage, and that should be said rather than left implied.** The previous revision ranked it above every measurement. But displacement **without an orchestrator costs 3.9–6.9 s** **[M]**, so the thing a *"waiting is fine"* answer would trade away is now known to be cheap. **D25** is vindicated for our own router rather than undermined. The question remains worth one sentence; it is no longer the highest-leverage open item (§12).

### 11.4 Condition 3 — the commitments that make this reversible rather than sunk

Recommending (c) is only honest if it comes with the triggers that would reverse it, per the ADR convention this project uses well:

| Trigger | Then |
|---|---|
| ~~**The latency baseline shows container startup dominates**~~ | **FIRED AND RESOLVED THE OTHER WAY** (ledger §9T). Container ~5 s, Ray ~100 s. This trigger is discharged and does not reverse the recommendation |
| **Ray's displacement path is shown to tune to ~10 s without destabilising the autoscaler** | §5.1 softens from a hard con to a configuration note, and Ray becomes materially more attractive. **Untested — this is now the experiment in §12** |
| **`image_uri` gains user-supplied `run_options`, or the Docker/CDI path works** | The deprecated-API dependency and the host-specific path both disappear. §3.2 loses most of its force, and Ray becomes materially more attractive |
| **A second GPU host is added — the multi-node trigger, now priced** | **Do not reach for a cluster reflexively.** The order is: (1) **price static federation first** — a second host runs its own tool-swap and the first forwards what it does not own, over the proxy we already built ([`14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md) §8.6); (2) adopt Ray **only** when the real requirement is *"one scheduler across all hosts"*, which is a much narrower claim than *"we have two hosts"*; (3) know what it costs when you do — **the router is rewritten; `tools.yaml`, the ~20 tool images, the tool contract and the ADR-0005 plain-data boundary are not** (§5A.7). **This trigger already existed in [ADR-0003](../plan/adr/0003-ray-serve-not-adopted.md) and [`15`](../plan/15_RAY_SERVE_EVALUATION.md) §11; what was missing was this pricing** |
| **Multi-node stops being hypothetical — i.e. a second GPU host is *budgeted*, not merely imagined** | **Re-run this analysis before the hardware lands, not after.** The demand axis flips from *hypothetical* to *quotable* (§5A.8) and that legitimately changes the weight Ray's multi-node row carries. **This is the trigger the requester's concern actually justifies**, and it is cheap because procurement gives months of notice |
| **M2 boot reconciliation proves hard, or router recovery bites in practice** | This is the **[A]** claim on our side of the ledger (§7.2). If it fails, Ray's measured replica self-healing becomes the stronger position and the comparison flips on its weakest row |
| **The zoo becomes homogeneous, or splits into image-sharing families** | **D2** stops being load-bearing and most of this repository should be deleted, per [`15`](../plan/15_RAY_SERVE_EVALUATION.md) §11 |

**And two commitments that are not triggers but disciplines.**

1. **Keep buying the multi-node insurance, deliberately.** The reason §5A.3 can answer *"extension, not rewrite"* is that three specific properties hold: **the scheduler is pure** ([`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §5 never-trim item 2), **the container backend stays behind its `Protocol`** ([`01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md) §12), and **every tool call carries plain data** ([`ADR-0005`](../plan/adr/0005-one-uniform-batched-calling-convention.md)). Those are already committed for their own reasons, they cost nothing extra, and **they are the whole of the answer to the requester's rewrite concern.** If any of them is ever traded away for short-term convenience, the multi-node migration turns from an extension into the rewrite that was feared — and **that trade should be refused with this section as the reason.**
2. **If (c) is chosen, the Ray question is closed for this v1 and the analysis stops** — because §10.2 is a finding about us rather than about Ray. Seven re-defences and now five analysis documents is itself the largest carrying cost the refusal has, and continuing to pay it is the opposite of simplicity. **The triggers above are the sanctioned way to re-open it; another unprompted re-litigation is not.**

### 11.5 What I would *not* claim

- **Not** that Ray cannot do this. It demonstrably can (§4 item 1).
- **Not** that Ray is worse software. For a homogeneous zoo it is better than what we are building, as [ADR-0003](../plan/adr/0003-ray-serve-not-adopted.md) already concedes.
- **Not** that **Ray cannot swap faster than 100 s.** Step 8 measured Ray's **default** path against a container. `downscale_to_zero_delay_s` is tunable and part of the remainder is `look_back_period_s` **[S]**. Whether it tunes to ~10 s without destabilising the autoscaler is **untested** (§5.1 limit 2, §12).
- **Not** that **Ray's teardown half was measured.** `mode=full` was not run (§5.1 limit 1). The gap is too large for any plausible teardown accounting to close, which is a different claim from having measured it.
- **Not** that the cost comparison is lopsided. It has moved — (c) now wins four rows and (a) three (§6.3) — but two of (a)'s three are about the next three years, and one of them (bus factor) has never been touched by any measurement.
- **Not** that this recommendation is well-evidenced on our own recovery story. It is **[A]**, and it is the weakest link.
- **Not** that **the multi-node risk is small.** §5A.6 states it at full strength and I have no measurement that refutes it. My claim is narrower: the insurance is already bought, the migration is bounded to the router, and the demand is currently hypothetical (§5A.7–§5A.9).
- **Not** that **anything here is evidence about multi-node.** No step 1–8 started a second host. §5A is structural argument on both sides, and it is the weakest-evidenced section in this document.

---

## 12. The cheapest experiment that would most change the answer

> **The previous winner has been run.** The plain-podman alternation baseline was named here as the single cheapest measurement that could most change the answer. It was built as step 8, run on the host, and it resolved §5.1 **against** Ray (ledger §9T, D45). **This section now names its successor.**

**The new experiment: can Ray's displacement path be tuned from ~100 s to ~10 s without destabilising the autoscaler?**

**I agree with the brief's candidate, and the reason is the one the brief gives — that single number is what makes Ray's latency con hard or soft.** The argument for it, rather than the assertion:

### 12.1 Why this one, and why it beats the alternatives

**§5.1 as it now stands is deliberately narrow.** It claims *"Ray's **default** path costs ~100 s where the container costs ~5 s"* and explicitly refuses the stronger claim *"Ray cannot go faster"*. **That refusal is load-bearing, and it leaves exactly one question open.** If Ray tunes to ~10 s, the largest measured con in this document softens from a hard blocker to a configuration note, Ray's remaining costs are the private-surface and deprecated-API ones — serious but not latency-shaped — and **the multi-node argument (§5A) would then be arriving against a much lighter cost side.** That combination is the one thing that could still flip the recommendation.

Conversely, if it **cannot** be tuned without the autoscaler misbehaving, then §5.1 hardens, §11.0's weighing is confirmed on its strongest term, and the decision is as settled as cheap evidence can make it.

**It is decisive in both directions, which is the test this section applies.**

### 12.2 What to run

Two knobs, both documented config values, against the step 5 harness that already exists:

1. Lower `downscale_to_zero_delay_s` toward its practical floor.
2. Lower `look_back_period_s`, the metric-decay window ([`autoscaling_policy.py:124-130`](/usr/local/lib/python3.11/site-packages/ray/serve/autoscaling_policy.py:124) **[S]**).

Then **re-run step 5's 20-alternation loop unchanged** and compare distributions against the recorded baseline (P90 103.2 s, bimodal).

**The acceptance criterion must be two-sided, or the experiment is worthless:**

| Must measure | Why |
|---|---|
| **The latency distribution** — P90 and whether bimodality disappears | The headline number |
| **Autoscaler stability** — flapping, replicas cycling, thrash, stuck `UPDATING`, controller errors | **A tuned-down delay that merely relocates the cost into instability is a failure, not a success.** Step 5's own pass criteria already watch for stuck states and controller degradation |
| **VRAM actually released each cycle, by `nvidia-smi`** | Non-negotiable. A faster cycle that skips the release is the no-op trap that made step 3's first run worthless |

**A pre-specified interpretation, because §5.1's credibility comes from having done exactly this before the fact:**

| Outcome | Effect on the decision |
|---|---|
| **P90 falls to ~10 s, no instability, VRAM released every cycle** | §5.1 softens to a configuration note. Ray's cost side drops materially, the §11.0 weighing must be re-run, and with the multi-node argument alongside it, **this is the outcome that could flip the recommendation** |
| **P90 falls but the autoscaler flaps, thrashes or stalls** | §5.1 **hardens**: the cost is not merely a default, it is a floor defended by stability. Combined with §3.1, this is a private-surface behaviour we would be tuning against with no compatibility promise |
| **P90 does not fall meaningfully** | §5.1 hardens into a measured Ray-specific limit. The recommendation is settled on its strongest evidence |

### 12.3 Why it is cheap

- **No new code.** The step 5 harness exists and has run 20 alternations successfully; this changes two YAML values.
- **No new dependency, no new fixture, no protocol amendment**, and no second host.
- **Same GPU, same images, same host** as every prior step, so it is directly comparable to a recorded baseline — which is what makes a small sample informative.
- **It mutates nothing on the shared host** beyond what steps 3 and 5 already did.

*(Scope note: this document does not modify `spike-e-ray-native/`. Running this would be a step-9, and it is described here as a recommendation, not performed.)*

### 12.4 Candidates I considered and rank lower, with reasons

- **A multi-node experiment — stand up a second host and test cross-host placement.** **Highest relevance to the newest input (§5A), and I still rank it below.** It is not cheap: it needs hardware we do not have, and §5A.8 finds multi-node is a **hypothetical** demand in every requirement document. **Running an expensive experiment to price a hypothetical, before the cheap experiment that prices a measured cost, is the wrong order.** If a second host is ever budgeted, this becomes the first experiment to run — and §11.4 says so as a trigger.
- **A second run of step 8** to confirm the headline figure, as ledger §9T itself advises before an ADR quotes it as settled. **Cheapest of all and it should be done** — but it is *confirmatory*, not decisive: it can strengthen §5.1, not change the answer.
- **The Docker/CDI path for `image_uri`** — high upside (it could delete the deprecated-API dependency entirely, §3.2's biggest caveat), but **not cheap and possibly impossible**: Ray hardcodes podman at [`image_uri.py:76`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:76) **[S]**, so testing it means patching Ray or waiting for upstream.
- **Multi-tool, multi-GPU scale beyond two** — the most *representative* gap (every measurement is two tools on one GPU, §9), but it is a week of work and refines rather than flips.
- **~~The plain-podman baseline~~** — **done** (ledger §9T).

**And the one thing still cheaper than any experiment:** §11.3, one sentence from the requester on whether waiting is tolerable. **Step 8 lowered its leverage** — displacement costs ~5 s, so **D25** is cheap to satisfy for our own router — but it remains free to ask.

---

## 13. Summary table

| Question | Answer |
|---|---|
| Can Ray do the job? | **Yes** **[M]** — step 3 passed, one GPU, two conflicting tools, both directions |
| Is it simpler in code volume? | **Yes** — five milestones leave scope, ~25–35 % **[A]** |
| Is it simpler in code we can *verify*? | **No** **[I]** — correctness moves to cluster-level conditions that took 7 host runs and ~43 fixes to observe once |
| Is it simpler in dependencies? | **No** **[S]** — a deprecated key, four private-source behaviours, version lockstep, rootless podman |
| Is it simpler in failure modes? | **No** for unattended operation **[M]** — three modes report success; one is an unmessaged C++ abort |
| **Is it faster to swap?** | **No — and this is now measured, not guessed** **[M]** (§5.1, ledger §9T). Ray's **default** path: **P90 103.2 s**, bimodal. Plain podman, identical VRAM-verified work: **P90 6.67 s**, tight. **~15×.** Our router inherits ~5 s |
| Is it better on bus factor? | **Yes, clearly**, and no spike touched this. The plan scores itself *"Worst"* |
| Is it better on recovery? | **Replica: yes, measured. Cluster: an operator runbook — but ours is unwritten [A]**, and the runbook's blast radius grows with node count (§5A.5) |
| **Does it avoid a future multi-node rewrite?** | **Partly, and it is the strongest pro-Ray argument (§5A).** It provides cross-host scheduling, membership and placement. But **robust multi-node Ray is KubeRay = option (b)**, closed by [ADR-0001](../plan/adr/0001-build-our-own-router.md) ([`architecture.md:42`](../plan/third-party-docs/ray-serve/architecture.md)) |
| **Is multi-node a rewrite or an extension for us?** | **An extension, and a substantial one.** The **pure scheduler survives**; the backend and proxy **grow substantially**; a **new distributed-state component appears**. **`tools.yaml`, the ~20 tool images, the tool contract and ADR-0005's plain-data boundary are untouched** (§5A.3, §5A.7) |
| **How strong is the multi-node demand?** | **⚠ Hypothetical** for multi-node itself — an **explicit non-goal** in [`00_CONTEXT_AND_MOTIVATION.md`](../plan/00_CONTEXT_AND_MOTIVATION.md) §5, a conditional trigger in five documents, unmentioned in the R8 client plan. **✅ Quotable** for the underlying concern, *"avoid huge rewrite in the future"* (§5A.8) |
| What is the biggest cost? | **The ~100 s default displacement path** **[M]** — no longer unattributed. It is Ray's, not the container's |
| What is the biggest unknown? | **Whether that ~100 s tunes to ~10 s without destabilising the autoscaler.** §12 |
| What is the biggest *unmeasured* risk? | **Multi-node, bus factor, and more than two tools on one GPU.** No step 1–8 touched any of them, on either side (§9, §5A) |
| What does the analysis recommend? | **(c) — unchanged, and strengthened.** Three conditions (one discharged) and seven reversal triggers — §11, with the weighing in §11.0 |
| Who decides? | **The requester.** Protocol Rule 3, and *"option (c) must not be chosen by default"* |

---

## 14. Provenance

**Read for this analysis:** [`spike-E-results.md`](spike-E-results.md) (all sections), [`spike-E-continuation.md`](spike-E-continuation.md) §§9j–9S, [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md), [`14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md), [`15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md), [`17_LLAMA_SWAP_PHILOSOPHY.md`](../plan/17_LLAMA_SWAP_PHILOSOPHY.md), [`09_IMPLEMENTATION_PLAN.md`](../plan/09_IMPLEMENTATION_PLAN.md), [ADR-0001](../plan/adr/0001-build-our-own-router.md), [ADR-0003](../plan/adr/0003-ray-serve-not-adopted.md), [ADR-0005](../plan/adr/0005-one-uniform-batched-calling-convention.md), [`case-for-ray-native.md`](case-for-ray-native.md), [`ray-native-reconsideration.md`](ray-native-reconsideration.md), [`ray-serve-mounts-and-deletion-scope.md`](ray-serve-mounts-and-deletion-scope.md), [`bias-audit-and-decision-procedure.md`](bias-audit-and-decision-procedure.md).

**Read for revision 2** (the step-8 result and the multi-node section): [`spike-E-continuation.md`](spike-E-continuation.md) **§9T (D45)** — the step 8 figures and, importantly, the four limits the step states about itself, all four of which are carried into §5.1 and §9 rather than dropped. For §5A: [`00_CONTEXT_AND_MOTIVATION.md`](../plan/00_CONTEXT_AND_MOTIVATION.md) §5 (the multi-node non-goal), [`01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md) §§5.1/7/9/12 (the global scheduling lock, in-memory reconciliation, **D21** container-name addressing, the `ContainerBackend` `Protocol`), [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../plan/06_LIFECYCLE_TTL_AND_SCHEDULING.md) §§1/4/5.1/5.3/6 (the shared-node premise, bare-integer devices, the pure `request_slot`, and the *"a new `Policy` implementation, not a rewrite"* sentence), [`11_R8_CLIENT_PLAN.md`](../plan/11_R8_CLIENT_PLAN.md) (searched for node-count commitments; **there are none**), [`13_OPEN_QUESTIONS.md`](../plan/13_OPEN_QUESTIONS.md) and [`14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md) §8.6 (the second-host trigger and the **static federation** option), [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §§1/5 (the demand axis and the scheduler-purity never-trim item).

**Third-party document verified during this revision:** [`plan/third-party-docs/ray-serve/architecture.md`](../plan/third-party-docs/ray-serve/architecture.md) — the process model, `proxy_location` (one proxy per node), the GCS checkpoint **on the head node**, and the sentence *"If you aren't using KubeRay, when the Ray cluster fails, Ray Serve cannot recover."* That last is the source for §5A.5's bound on Ray's multi-node payout, and it is a captured vendor page in this repository rather than a recollection.

**Ray source verified during this task** (not quoted from the ledger alone): [`resource_and_label_spec.py:454-471`](/usr/local/lib/python3.11/site-packages/ray/_private/resource_and_label_spec.py:454) — the explicit-`0`-is-not-autodetect behaviour, confirmed at `if num_accelerators is None:`. The other three private-source citations are quoted from the ledger with their file:line intact and were not independently re-opened here; a reviewer wanting to check them has the exact lines.

**Not modified**, per the constraints: the ADRs, [`spike-E-continuation.md`](spike-E-continuation.md), [`spike-E-results.md`](spike-E-results.md), [`spike-E-ray-native-protocol.md`](spike-E-ray-native-protocol.md), and anything under `spike-e-ray-native/`. Nothing committed, nothing pushed.

**Revision 2 changelog**, section by section:

| Section | Change |
|---|---|
| Header | Added the revision-2 note naming both inputs and stating that they pull in opposite directions |
| **§4 item 5** | Multi-node called out as under-weighted; forward-pointed to §5A |
| **§5.1** | **Rewritten.** "Unattributed, priced both ways" → the measured attribution, with the step-8 comparison table, VRAM verification, and **three explicit limits** so the number does not harden beyond its evidence |
| **§5A** | **New section.** The multi-node migration: node-count assumptions, what must grow, rewrite-vs-extension, *"complexity we have no experience in"*, Ray's partial payout, the asymmetry at full force, what the spike makes easier, the demand scoring, and four priced middle paths |
| **§6.1 / §6.2 / §6.3** | New rows for measured latency and for multi-node on both options; the 3–3 split re-stated as 4–3 **on evidence class rather than count** |
| **§7.6** | Wait-versus-displace: **D25** vindicated for our router at ~5 s; the question's leverage lowered |
| **§9** | Latency-attribution row marked resolved; two new unknowns (autoscaler tuning, multi-node); "three things" → **five**, adding multi-node and bus factor; step-8 limits restated outside §5.1 |
| **§11.0** | **New.** The explicit weighing of both inputs, and the single consideration that decided it |
| **§11.2 / §11.3** | Condition 1 discharged and replaced by the tuning question; condition 2's leverage lowered with the reason stated |
| **§11.4** | Two new triggers (autoscaler tuning; multi-node *budgeted*), the second-host trigger **priced** rather than merely named, and a new discipline: keep buying the multi-node insurance |
| **§11.5** | Four new refusals, including *"not that Ray cannot go faster"* and *"not that teardown was measured"* |
| **§12** | **Replaced.** The previous winner has been run; the successor is the autoscaler-tuning question, with a two-sided acceptance criterion and a pre-specified interpretation |
| **§13** | Four new rows: swap speed, multi-node payout, rewrite-or-extension, demand scoring; biggest cost and biggest unknown both updated |
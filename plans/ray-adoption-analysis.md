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
>
> ---
>
> **Revision 3 — the stall is located, and the multi-node question is answered as a counterfactual rather than scored.** Two changes, and the second is a change of *method*, not merely of content.
>
> 1. **The ~100 s is no longer "Ray's autoscaler decay". It is dead time inside Ray *before* it issues `podman run` at all** (ledger **§9Z, D54**). Step 9 under eager probing reproduced the bimodality at step 5's rate — 8 slow / 12 fast — and the container timestamp splits the span decisively: **the container is first seen at ~3.0 s on a fast cycle and ~93.6 s on a slow one**, with every phase *before* the replica exists identical to the millisecond. **A pending request is a precondition**: 50 cycles that polled to RUNNING before probing never stalled. **That is exactly the request-triggered path tool-swap is built around.** §5.1 is rewritten around this. The mechanism is deliberately unnamed — five prior attributions were wrong.
> 2. **§5A is rewritten to answer the requester's counterfactual**: *"what if scaling to multiple nodes becomes a must — what happens to the Ray vs. homemade decision?"* The previous §5A spent its strongest section **scoring the likelihood** of multi-node (§5A.8, "hypothetical in every requirement document"). **That was the wrong move and it is withdrawn as the section's centre.** The requester has raised multi-node three times; he is asking for the condition to be *assumed*, not litigated. **The new §5A assumes it and prices the three options under it** — and it admits a third option the framing had been ignoring: **KServe/Seldon on Kubernetes, which this project's own [`00_CONTEXT_AND_MOTIVATION.md:225`](../plan/00_CONTEXT_AND_MOTIVATION.md:225) already names as *"The 'right' answer at cluster scale… Keep as the documented growth path"*.** The likelihood scoring survives, demoted, in §5A.9, because *"what triggers it"* is a separate and still-useful question from *"what happens if it holds"*.
>
> **The two questions §5A now keeps apart, because conflating them is what produced the previous revision's evasion:** *does the recommendation change **today**?* and *does it change **under the assumption that multi-node is mandatory**?* **Both get a one-line answer in §5A.0, and they are different answers.**

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

> **This item was under-weighted in revision 1, and the requester was right to press on it.** Listing *"multi-node scaling"* in a row alongside a dashboard prices it as a feature. It is not a feature — it is **the avoidance of a future migration**, which is a different and larger thing, and it is *"complexity we have no experience in"*. **§5A prices it as a first-class section.**
>
> **Revision 3 qualifies this item rather than deleting it, and the qualification matters.** Ray does provide multi-node scheduling and we would not write it as well. **But the specific piece of that machinery which bears on tool-swap — replica placement against a pending request — is the piece measured stalling for ~93 s** (§5.1.1) **[M]**, and §5A.2 finds no mechanism by which more nodes relieve it **[I]**. **So the row is real but smaller than revision 2 claimed**, and under a *mandatory* multi-node premise it does not rescue Ray: §5A.7 ranks Ray third of three, behind Kubernetes-native serving and behind building our own.

**6. Bus factor, and it is the row that never affects any conclusion.** [`case-for-ray-native.md`](case-for-ray-native.md) §5 makes this point and it survives the spike untouched: the plan's own comparison table scores its own bus factor **"Worst"**. For a small research team, the system that survives is the one that still runs after its author moves on. **Nothing in the spike bears on this at all** — which means it is exactly as strong an argument now as it was before, and it should not be quietly discounted because the spike produced other numbers.

**7. Two people, reasoning independently, recommended reuse.** The requester (*"prioritise making the tool robust and easy to maintain"*) and the engineer (*"prioritize the use of existing frameworks"*). And **D12** is the project's own principle: *prefer existing self-hostable software*. [`14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md) §1 admits the tension and it has never been resolved, only argued around.

**8. The nine-for-nine record.** [`case-for-ray-native.md`](case-for-ray-native.md) §4 lists nine objections to Ray that were each stated confidently and each fell. **The spike adds a tenth data point and it cuts the same way**: the two decisive "Ray fails the gate" verdicts were **our own measurement errors**, retracted on the record (§4 of the results doc). *Every* decisive negative this project has produced about Ray has so far been withdrawn.

---

## 5. The cons, priced with measurements

### 5.1 P90 swap latency 103 s — attributed, and now *located*: it is dead time inside Ray before the container starts

> **This section has been rewritten twice.** Revision 1 called the 103 s *"the largest **unattributed** cost in the analysis"* and priced it both ways. **Revision 2** (step 8, ledger §9T, D45) attributed it: the container costs ~5 s, so the ~95 s is Ray's. **Revision 3** (step 9 eager, ledger **§9Z, D54**) **locates** it, and the location is worse than the attribution was. It is **not** autoscaler metric decay as revision 2 assumed by elimination — it is **dead time inside Ray between deciding a replica is needed and issuing `podman run`**.

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
| **Ray's displacement path** | **~100 s** | **Ray only.** Revision 2 attributed this to autoscaler decay *by elimination*. **Step 9 shows that was wrong** — see §5.1.1 |

**This is the hard-con branch that §12 specified *in advance*, which is the only reason it counts as evidence rather than as a result found after the fact.** The previous §5.1 offered two outcomes and said which way each would push; the measurement landed on the one that makes this a genuine Ray-specific con. Our own router inherits **~5 s**, not ~100 s.

#### 5.1.1 The stall is located — and it is pre-container dead time, on the request-triggered path **[M]**

> **Ledger §9Z, D54.** `SPIKE_STEP9_N=20 SPIKE_STEP9_PROBE=eager make step9` → exit 0. **8 slow / 12 fast — the bimodality reproduced under instrumentation, at step 5's ~40 % rate.** This is the single most decision-relevant measurement in the spike, and it changes what §5.1 *means* rather than what it costs.

| Phase | fast (12 cycles) | slow (8 cycles) |
|---|---|---|
| scale-down RPC / scale-up RPC | 8 ms / 5 ms | 8 ms / 4 ms |
| controller decision lag | 7 ms | 7 ms |
| replica materialize | 0.87 s | 0.87 s |
| **container first seen** | **~3.0 s** | **~93.6 s** |
| **STARTING → RUNNING** | **8.9 s** | **99.3 s** |

**Every phase before the replica exists is identical between the two groups, to the millisecond.** The whole difference sits in one span, and the container timestamp splits that span decisively:

> **Ray waits ~90 seconds before issuing `podman run` at all.**

**Verified independently, against Ray's own log rather than the harness's summary** **[M]**: cycle 2's `container_first_seen_s` = 93.578 from t0 ≈ 10:05:43.9 predicts 10:07:17.48; Ray's `runtime_env_setup` log records `10:07:17.555 Pulling image tool_tf:spike`. **Agreement within 80 ms.** The replica's own initialisation then takes 3.3 s. **The work is fast; the waiting precedes it.**

**What this rules out** **[M]**: the scale RPCs (8 ms), the controller's target update (7 ms), actor creation (0.87 s — *identical* in both groups), container startup (~1 s, per step 8 and the fast cycles), and tool initialisation (2–3.5 s, present in every cycle's replica log including the slow ones). **It is dead time inside Ray between deciding a replica is needed and launching the process.**

**A pending request is a precondition, and this is the part that bears hardest on the decision** **[M]**. `ready` polled to RUNNING *before* probing — **50 cycles, never slow**. `eager` probes immediately — **8/20 slow**. The difference is not observation overhead. **Ray takes ~90 s to place a replica *when a request is already waiting on it*.** Tool-swap is request-triggered by construction: a request arrives for a non-resident tool and the router must displace and start it. **So the stall does not hit an incidental path — it hits exactly the path the product exists to serve, and only that path.**

**Three consequences for this document:**

1. **Revision 2's attribution to autoscaler decay was wrong**, and it was wrong in the way this spike keeps being wrong: by elimination rather than by measurement. `look_back_period_s` and `downscale_to_zero_delay_s` remain real config values **[S]**, but they are **not** what the 8 slow cycles were spending ~93 s on, because the scale RPCs and the controller decision completed in **15 ms combined**. Any claim in this file resting on "it is the downscale clock" is superseded by §9Z.
2. **The tuning experiment named in §12 loses most of its force**, because it was designed to lower knobs that the measurement now shows are not on the critical path. §12 is rewritten accordingly.
3. **The mechanism is deliberately unnamed** **[A]**. Retry/backoff, a lock, a queue interaction, a health-check cycle — **unknown**. The ledger states plainly that **five prior attributions were wrong**, and refuses a sixth. What is measured: the dead time is inside Ray, it *precedes* the container launch, it is ~90–95 s with little spread, and **it requires a pending request to manifest**. The controller and proxy logs for a slow cycle are the next place to look.

**The number that should be quoted from this section** **[M]**: **~15× on the core path, ~40 % of the time**, against a plain-podman baseline of 3.9–6.9 s with no bimodality (§9T). Not "Ray's autoscaler is slow to release" — **"Ray sometimes does nothing for 90 seconds while a request waits."**

#### Three limits, so the number does not harden beyond its evidence

The finding is load-bearing, so its boundaries are stated here rather than left to a reader's inference. Limit 1 is step 8's own (ledger §9T); limits 2 and 3 are restated after step 9 (ledger §9Z).

1. **Teardown was not measured.** `mode=start` measures the **run span only** — fresh container start, init, identity, exit. It **excludes** Ray's scale RPCs, replica teardown, ingress routing and the HTTP round trip, and **`mode=full` was not run**. Step 5's cycle also includes displacing a live VRAM holder, which plain podman has no equivalent of. So the comparison is **start-side like-for-like, teardown-side incomplete**. What licenses the conclusion anyway is the size of the gap, not the completeness of the accounting: **~95 s of difference against a total podman cycle under 7 s**, so no plausible teardown accounting closes it. That is the honest form of the claim — *the gap is too large for the missing half to explain*, **not** *the missing half was measured*.
2. **~~Ray's ~95 s is configuration-dependent, not a floor.~~ — SUPERSEDED by §5.1.1, and the replacement limit is different in kind.** Revision 2 wrote that the ~95 s was `downscale_to_zero_delay_s` plus `look_back_period_s` decay, and that tuning might therefore dissolve it. **Step 9 measured those phases at 15 ms combined** **[M]**, so that limit was describing the wrong thing. **The replacement limit:** the stall's **mechanism is unknown** **[A]**, and an unknown mechanism is not a knob. It may still be configurable, it may be a defect fixed in a later Ray, or it may be structural — **we cannot say, and §9Z explicitly refuses to guess after five wrong attributions.** The defensible claim is now: ***"on Ray 2.57, on the request-triggered path, ~40 % of swaps spend ~90 s in pre-container dead time inside Ray."*** It is still **not** *"Ray cannot go faster"* — but it is no longer *"a config value explains it"* either, and **that is a worse position for Ray, not a better one**, because a measured cost with a named cause can be budgeted and one with an unknown cause cannot.
3. **20 samples in step 8, 20 more in step 9-eager, one host, warm image store.** The bimodality has now reproduced across two independently-built harnesses at the same ~40 % rate, which is stronger than revision 2's single run — but it is still one host, one GPU, two tools.

**What the number establishes regardless** **[M]**: a swap **on the request-triggered path** sometimes takes 100 seconds under Ray, and a swap *without an orchestrator* never took more than 6.91 s. Both facts bear on `queue_timeout` (**D22**), on `min_residency` and thrash detection ([`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §4.4, never-trim), and on §7.6's wait-versus-displace question — which step 8 sharpens rather than settles, because **a 5 s displacement is a much better deal than a 100 s one**, and that strengthens **D25**'s premise for our own router while weakening it for Ray.

**And one thing step 9 establishes that step 8 could not**: the penalty is **not** an artefact of how we drove the displacement. Step 9 used a different harness, a different probe pattern and a different instrumentation path, and reproduced the same bimodality at the same rate **[M]**. **Two independent measurements now agree that ~40 % of request-triggered swaps stall.**

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

## 5A. Multi-node GPU is a MUST — the counterfactual, answered

> **This section is rewritten for revision 3, and the rewrite is a correction of method.** The requester has now raised multi-node three times, and his question this time is explicit: ***"what if scaling to multiple nodes become a must.. what happens to the ray vs homemade decision"***.
>
> **The previous §5A answered a different question and it should not have.** Its strongest subsection (§5A.8) scored how *likely* multi-node was, concluded *"hypothetical in every requirement document"*, and used that to discount the argument. **That is an evasion when the requester has just told you to assume the condition holds.** "It is currently a non-goal" is a true sentence and an irrelevant one: the counterfactual asks what happens *if* the non-goal is overturned, and a non-goal being overturned is exactly the scenario worth pricing in advance.
>
> **So this section assumes multi-node is mandatory and prices the options under that assumption.** The likelihood question survives — demoted to **§5A.9**, reframed as *"what would actually trigger it"*, which is a genuinely useful question and a different one.
>
> **The framing itself was also wrong, and this is the larger correction.** "Ray vs. homemade" is a two-option frame, and the project's own documents record a **third** option that the multi-node question has been implicitly ignoring: [`00_CONTEXT_AND_MOTIVATION.md:225`](../plan/00_CONTEXT_AND_MOTIVATION.md:225) names **KServe / Seldon** as *"The 'right' answer at cluster scale… Keep as the documented growth path."* **The plan of record for multi-node was never Ray. It was Kubernetes-native serving.** §5A.5 argues it properly, for and against.
>
> **A standing caveat that applies to every row in this section: nothing in steps 1–9 touched multi-node.** The spike ran on one host and never started a second. Ray's multi-node capability here is **documented, not verified by us**; our migration cost is **[A]**. **Every multi-node claim below is tagged [I] or [A] and none is [M].** The one **[M]** fact in the section is the single-node stall (§5.1.1), which is why §5A.2 reasons *from* it rather than about it.

### 5A.0 The two answers, up front, because they are different answers

**These are separate questions and conflating them is what produced the previous revision's evasion. One line each, no hedging:**

| Question | Answer |
|---|---|
| **Does the recommendation change TODAY?** | **No.** Multi-node is not a requirement today, the ~15 × core-path penalty is measured and present, and **(c) continue building our router** stands — for the reasons in §11.0, now strengthened by §5.1.1 rather than weakened. |
| **Does the recommendation change UNDER THE ASSUMPTION that multi-node is mandatory?** | **Yes — but not to Ray.** It changes to **Kubernetes-native serving (KServe/Seldon), which is this project's own documented answer at cluster scale.** Ray is the option that *loses* most under mandatory multi-node, because robust multi-node Ray is KubeRay — Kubernetes anyway — at which point you have paid for Kubernetes *and* a measured 15 × penalty on the path the product exists to serve. |

**Stated as one sentence, since that is what was asked for:** *if multi-node becomes a must, the honest answer is Kubernetes, and the Ray-vs-homemade framing was the wrong question — because the only form of Ray that answers multi-node robustly is the one that runs on Kubernetes.*

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

### 5A.2 Does the ~93 s stall get better, worse, or stay the same at multi-node?

> **This is the first question the requester asked, and it must be answered before any option can be priced — because if the stall worsens with node count, option (a) is not merely expensive at multi-node, it is disqualified by the very condition that was supposed to justify it.**

**The measurement first, so the boundary between fact and reasoning is visible** **[M]** (§5.1.1, ledger §9Z): the stall is **pre-container dead time inside Ray**, ~90–95 s, on ~40 % of request-triggered swaps, on **one host with one GPU and two tools**. Every phase we *can* see — scale RPCs, controller decision, actor materialisation — is identical between fast and slow cycles.

**Stated plainly, and this is the limit that governs everything below: the stall is UNMEASURED at >1 node. We have one host. Nothing in steps 1–9 started a second.** **[M]** for the single-node figure; everything that follows is **[I]**, and the argument is stated so it can be checked rather than merely asserted.

#### The structural reason to expect it not to improve — and to expect it to worsen **[I]**

Two facts about where the stall sits, both from captured vendor documentation:

1. **The stall is in the replica-placement path.** It is dead time between the controller deciding a replica is needed and the process being launched **[M]**. Whatever the mechanism, it sits *after* the decision and *before* the launch.
2. **Replica creation is owned by a single global actor.** [`architecture.md:15`](../plan/third-party-docs/ray-serve/architecture.md:15): *"**Controller**: A global actor unique to each Serve instance that manages the control plane. The Controller is responsible for **creating, updating, and destroying other actors**."* Proxies can be per-node via `proxy_location` ([`:16`](../plan/third-party-docs/ray-serve/architecture.md:16)), and the autoscaler *also* runs in the controller ([`:48`](../plan/third-party-docs/ray-serve/architecture.md:48)) — **but replica creation goes through the one controller regardless of node count.**

**The inference** **[I]**: adding nodes does not add controllers. It adds **placement candidates, cross-node actor scheduling, and more metric traffic into the same serialised control plane** — every `DeploymentHandle` and every replica *"periodically pushes its metrics to the autoscaler"* in that controller ([`:49`](../plan/third-party-docs/ray-serve/architecture.md:49)). So the component that stalls is the one component that **does not scale out**, while the work flowing through it grows with node count.

| Hypothesis about the mechanism | Effect of adding nodes | Confidence |
|---|---|---|
| Contention, a lock, or a queue interaction **inside the controller** | **Worse.** More replicas, more metric pushes, more placement decisions, same single actor | **[I]** — follows from [`architecture.md:15`](../plan/third-party-docs/ray-serve/architecture.md:15) if the mechanism is contention |
| A retry/backoff cycle on a failed or deferred placement | **Plausibly worse.** Cross-node placement has more ways to defer — resource reporting lag from a remote raylet, a node not yet reporting its GPU — and each deferral is another backoff interval | **[I]** |
| A health-check or heartbeat interval that must elapse | **Roughly unchanged per event, but hit more often**, since more nodes means more heartbeat relationships | **[I]** |
| A fixed timeout that only fires when a request is already pending | **Unchanged per swap.** Still ~90 s, still ~40 % | **[I]** |

**Not one of those four hypotheses predicts improvement.** That is the finding, and it is worth stating as bluntly as the evidence allows:

> **There is no mechanism by which adding nodes relieves a stall that sits in a single global controller before the container launch. More placement options do not help, because the measurement shows Ray is not *searching* for a placement — it is doing nothing for 90 seconds.** **[I]**

#### The honest counter, stated because it is real **[I]**

**Multi-node could reduce how *often* the stall is hit**, without touching the stall itself. With GPUs on several hosts, a request for a non-resident tool is more likely to find a free device somewhere and **not need a displacement at all** — and the stall's measured precondition is a pending request waiting on a replica that must be placed **[M]**. **That is a real mitigation and it should not be waved away.** But note precisely what it is: it reduces the *rate of swaps*, not the *cost of a swap*. When the zoo is larger than the cluster — which is the premise of this entire project, ~20 tools competing for a bounded set of GPUs — swaps remain the steady state, and every swap that does occur still faces the same ~40 %/~90 s distribution. **[I]**

#### The answer

| Question | Answer | Class |
|---|---|---|
| Does the stall improve at multi-node? | **No mechanism for it to.** The stalling component is global and does not scale out | **[I]** |
| Does it worsen? | **Probably — on three of four hypotheses**, because the same single controller carries more placement and more metric traffic | **[I]** |
| Is this measured? | **No. We have one host.** The single-node figure is **[M]**; every multi-node claim here is **[I]** | **[M]**/**[I]** |
| Could we find out cheaply? | **No.** It needs a second GPU host. §12 ranks it, and under *mandatory* multi-node it becomes the **first** experiment to run, not the last | — |

**Why this matters more than it looks.** The multi-node argument for Ray is *"it removes distributed scheduling complexity we have no experience in"*. **But the one piece of Ray's distributed machinery we have actually measured — replica placement, the thing a distributed scheduler exists to do — is the piece that stalls for 90 seconds.** We would be adopting a distributed scheduler on the strength of the parts we have not measured, having measured the part that is on our critical path and found it wanting. **[I]**

### 5A.2b What a single-node router must actually grow

Concretely, and split by who provides it. **Read with §5A.2 in hand: "Ray provides" means Ray provides *something*, and for the placement row we have measured what that something costs.**

| Capability needed at multi-node | Ray provides? | What we would write |
|---|---|---|
| **Cross-host scheduling and placement** | **Yes — and this is the row §5A.2 complicates.** It is the core of what Ray is, *and* it is the path measured at ~93 s of dead time on ~40 % of request-triggered swaps **[M]** | The scheduler's *decision* survives (§5A.4); what is new is that placement must choose a **host** as well as a device, and act on a remote one |
| **Remote container lifecycle** | **Yes**, but through the same deprecated `container` key — and the **host-specific absolute path** `--runtime=/usr/bin/nvidia-container-runtime` (§3.2) must now be correct on *every* host. **The portability hit multiplies with node count** **[S]**/**[M]** | A `ContainerBackend` implementation that talks to a remote daemon rather than a local one |
| **Cluster membership and health** | **Yes** — GCS plus raylets | New component. We have nothing resembling this |
| **Node-failure handling** | **Partly.** Actors are restarted on another available machine, with controller data checkpointed to the GCS **on the head node** ([`architecture.md:44`](../plan/third-party-docs/ray-serve/architecture.md:44)) — **but see §5A.3, the head node itself is the catch** | New. Currently a "node" failure is the whole system failing, which needs no handling |
| **Request routing to the right host** | **Yes** — one proxy per node via `proxy_location` ([`architecture.md:16`](../plan/third-party-docs/ray-serve/architecture.md:16)) | Substantial proxy growth: today tools are addressed **by container name on one Docker network** (**D21**), which does not resolve across hosts |
| **Distributed state — who holds which GPU** | **Yes** — GCS | **A genuinely new component**, and it collides with the **"No database"** non-goal and with in-memory reconciliation |

### 5A.3 Option (a) — adopt Ray, priced under mandatory multi-node

**The case for it, at full strength and in one sentence:** Ray is a mature distributed framework whose core competence is exactly the thing we would otherwise have to write and have never written, and under a *mandatory* multi-node requirement that competence stops being speculative insurance and becomes a present need.

**What it actually buys, and what it actually costs, under the assumption:**

| | Detail | Class |
|---|---|---|
| **Buys** | Cross-host placement, cluster membership, health, distributed state, per-node proxies, actor restart on a surviving machine | **[A]** — documented, never verified by us |
| **Costs — measured** | ~93 s of pre-container dead time on ~40 % of request-triggered swaps, **on the single-node configuration we could measure** | **[M]** |
| **Costs — inferred** | That stall sits in a **global, non-scale-out controller** and has no mechanism to improve with node count (§5A.2) | **[I]** |
| **Costs — structural** | The deprecated `container` key on **every host**, with a host-specific absolute path per host (§3.2); four private-surface behaviours re-verified per upgrade (§3.1); three failure modes that report success (§5.4) | **[S]**/**[M]** |
| **Costs — the catch** | **Robust multi-node Ray is KubeRay** | **[S]** |

**The catch, stated as the document it comes from states it** ([`architecture.md:42`](../plan/third-party-docs/ray-serve/architecture.md:42)):

> *"If you aren't using KubeRay, when the Ray cluster fails, Ray Serve cannot recover."*

Combined with the measured single-node finding (§5.2 — cluster recovery is a three-command operator runbook and Serve applications **do not come back by themselves** **[M]**), and with [`architecture.md:44`](../plan/third-party-docs/ray-serve/architecture.md:44) placing the GCS and the controller checkpoint **on the head node**, the multi-node consequence is this **[I]**:

- At multi-node, the head node becomes **a single point of failure for every host in the cluster**, not just for one.
- **The blast radius of the failure we already measured grows with node count.** A manual runbook that costs one host's availability at n=1 costs the whole cluster's at n=8.
- **The fix Ray itself names is KubeRay** — i.e. Kubernetes.

**And that is where option (a) collapses under its own premise.** The argument for adopting Ray *because* multi-node is mandatory is an argument for adopting **KubeRay**, because a cross-cluster single point of failure with a manual recovery runbook is not a multi-node answer for a system meant to run unattended. **But KubeRay is Kubernetes.** So:

> **Under mandatory multi-node, option (a) does not avoid Kubernetes. It arrives at Kubernetes *and* carries a measured ~15 × penalty on the core path, *and* keeps the deprecated-API dependency on every host. It is strictly dominated by option (c), which arrives at Kubernetes without the other two.** **[I]**

**The strongest reply to that, and it deserves stating:** KubeRay-plus-Ray-Serve is a *more capable* platform than KServe for anything involving stateful actors, model composition across replicas, or a shared object store — and if tool-swap's future involves those, the extra cost buys something. **That reply is correct and it is also not our use case**: tool-swap is a swap/TTL/proxy/authoring layer over independent single-container tools ([`00_CONTEXT_AND_MOTIVATION.md:228`](../plan/00_CONTEXT_AND_MOTIVATION.md:228)). We would be paying for a distributed-actor runtime to run containers that never talk to each other.

### 5A.4 Option (b) — build our own now, extend to multi-node later

**What must actually be written**, taken from §5A.2b and split on the axis that matters. **"Hard" here means unbounded-failure-mode hard — the risk class §5A.6 is about. "Tedious" means a known amount of careful work.**

| Piece | Hard or tedious? | Why |
|---|---|---|
| **Cross-host placement *decision*** | **Tedious** — nearly free, in fact | The scheduler is a **pure function of a state snapshot** ([`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../plan/06_LIFECYCLE_TTL_AND_SCHEDULING.md) §5.1, §5.3). `GRANT(device)` becomes `GRANT(host, device)`; the policy — LRU, `evict_cost`, `min_residency`, in-flight immunity, group caps — is untouched. §6 of that document already anticipates *"a new `Policy` implementation, not a rewrite"* **[I]** |
| **Remote container lifecycle** | **Tedious** | `ContainerBackend` is a `Protocol` and *"the ONLY component that touches Docker"* ([`01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md) §12). A remote implementation is a new class behind an existing seam. **[A]** — rests on the unverified assumption that the Docker SDK addresses remote daemons cleanly enough; **not verified in this task, treat as assumption** |
| **Request routing to the right host** | **Tedious** | **D21** (container-name addressing on one Docker network) does not survive, and is replaced by host-qualified addressing. Annoying, well-understood, no novel failure mode |
| **Membership and health** | **Genuinely hard** | Deciding *"is that host down, or is the network slow?"* is the classic problem, it has no correct answer, and every wrong answer is a failure mode we would meet in production rather than in tests |
| **Node-failure handling** | **Genuinely hard** | Fencing a node we believe is dead but which may still be running containers holding GPUs. Get it wrong and two hosts both think they own a device — or a tool runs twice on weights it thinks it owns alone |
| **Distributed "who holds which GPU"** | **Genuinely hard — and it is the one that breaks a stated non-goal** | In-memory state plus backend reconciliation works because one process sees one daemon. Across hosts this needs a store or a single-writer election, colliding with **"No database"** ([`00_CONTEXT_AND_MOTIVATION.md`](../plan/00_CONTEXT_AND_MOTIVATION.md) §5) and with the one global `asyncio.Lock` that [`01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md) §5.1 calls *"entirely sufficient at our scale — do not get clever"*. **Multi-node is exactly the scale at which that hedge expires** |

**The split is three tedious, three hard — and the three hard ones are one problem wearing three hats.** Membership, fencing and distributed ownership are all *"who decides, and what happens when two deciders disagree"*. **That is consensus, and writing it yourself is the thing nobody on this project has done.** **[I]**

**So the honest verdict on (b) under mandatory multi-node:**

> **It is not a rewrite of the product — `tools.yaml`, the ~20 tool images, the tool contract and the ADR-0005 plain-data boundary all survive (§5A.7). But it *is* asking a team that has never built a distributed system to build the hard half of one, on the critical path of a clinical-inference service, in order to avoid adopting a platform that already solves it.** **[I]**

**That is a bad trade, and I will not dress it up.** Option (b) was the right answer when multi-node was a non-goal, because then none of the three hard pieces had to be written at all. **Under the assumption that multi-node is mandatory, (b)'s central virtue — that we only write what we need — stops applying, because what we need now includes consensus.**

### 5A.5 Option (c) — KServe / Seldon on Kubernetes, the plan's own documented answer

> **This is the option the multi-node question has been implicitly ignoring for three rounds, and it should not have been.** [`00_CONTEXT_AND_MOTIVATION.md:225`](../plan/00_CONTEXT_AND_MOTIVATION.md:225), in the project's own words: **KServe / Seldon** — *"Kubernetes-native model serving with scale-to-zero (which is hard TTL). **The 'right' answer at cluster scale.** Rejected for v1: requires Kubernetes, contradicts R1 (simple to launch) and D8 (docker compose). **Keep as the documented growth path.**"* And [`:237`](../plan/00_CONTEXT_AND_MOTIVATION.md:237) makes multi-node a non-goal **in the same document** — the two statements are a matched pair. **The plan of record has always been: single node now, Kubernetes-native serving at cluster scale. "We would adopt Ray when multi-node arrives" was never the plan.**

**The case for (c) under mandatory multi-node:**

1. **Multi-node *is* cluster scale.** The condition under which the plan itself says KServe is *"the right answer"* is precisely the condition we are assuming. Every reason (c) was rejected for v1 — *"requires Kubernetes, contradicts R1 and D8"* — is a **single-node** reason. **Mandatory multi-node dissolves all three**: you cannot have multi-node GPU scheduling and still claim `docker compose` simplicity, on any option. **The objection to (c) was never portable to the multi-node case.** **[I]**
2. **It is the only option where the Kubernetes cost buys the Kubernetes benefit.** Under (a) you end at KubeRay — Kubernetes **plus** a distributed actor runtime you do not need, **plus** the measured stall. Under (c) you get Kubernetes' scheduler, its membership, its health, its fencing, its multi-tenancy, and a serving layer built for exactly this. **If multi-node is mandatory, you are paying for Kubernetes in two of the three options; (c) is the one where you pay once.** **[I]**
3. **The migration is already worked out, in detail, in this repository.** [`14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md) §8 maps `tools.yaml` to `InferenceService` field-by-field (§8.2), lists what ports unchanged (§8.1), what is discarded (§8.3) and what must genuinely be rebuilt (§8.4). **Nothing equivalent exists for Ray** — §5A.2b is the closest, and it is a sketch by comparison.
4. **The tool images are already valid KServe predictors.** Guardrail 11 — *"a tool image runs standalone under plain `docker run`"*, proven per-tool by `tswap preflight` (**D17**) — is what makes this true, and [`14 §8.5`](../plan/14_ALTERNATIVES_EVALUATION.md) says so explicitly: *"This single property is what makes a tool image simultaneously a valid compose service, a valid llama-swap target, a valid tool-swap tool **and a valid KServe predictor**."*
5. **Bus factor, which has never been touched by any measurement (§4 item 6).** Kubernetes is the single most widely-known operational substrate in existence. A research team that loses its router author is in a far better position with `InferenceService` manifests than with either a bespoke distributed scheduler **or** a Ray cluster whose GPU path depends on four private-surface behaviours.

**The case against (c), argued properly rather than conceded:**

1. **Kubernetes does not preempt, and preemption is our whole product.** This is the real objection and it is decisive-sounding. [ADR-0001](../plan/adr/0001-build-our-own-router.md) Spike B: *"Kubernetes **allocates** devices. A second pod requesting a GPU that is held goes `Pending` and stays there until the incumbent leaves of its own accord. It does not evict an incumbent to make room."* **D25** — *"we don't want to wait for TTL"* — is the requirement that eliminates every off-the-shelf candidate, and Kubernetes fails it as shipped.
2. **But the reply is already recorded, in two places, and it is stronger than the objection.** [`14 §8.4`](../plan/14_ALTERNATIVES_EVALUATION.md): *"Reproducing 'swap' needs priority and preemption classes plus a graceful-shutdown path, or a small custom controller. **This is the hardest part of any migration, and it is the same work we would be doing here anyway** — the design effort is not wasted even if the platform changes."* And [ADR-0001](../plan/adr/0001-build-our-own-router.md) itself: *"the preemption logic we now write is **the same work** a Kubernetes migration would require."* **So under (c), what we write is the eviction policy — the pure scheduler, the interesting part, the part we were always going to own — and Kubernetes provides membership, fencing and distributed ownership, which are the three genuinely hard parts of §5A.4.** That is exactly the right division of labour. **[I]**
3. **Kubernetes is heavy, and both the requester and the engineer have said so.** True, and under a single-node premise it was decisive: a cluster to run twenty models on one box *"inverts the complexity budget"* ([`14 §8.6`](../plan/14_ALTERNATIVES_EVALUATION.md)). **Under mandatory multi-node the budget is already inverted by the requirement itself.** The comparison is no longer "Kubernetes vs. a simple thing" — it is **"Kubernetes vs. writing consensus ourselves (b), or Kubernetes-plus-Ray-plus-a-measured-15 ×-penalty (a)"**.
4. **We have not spiked KServe.** Genuine, and it must be labelled: **[A]**. Spike B was *"answered on the record, not run"* ([ADR-0001](../plan/adr/0001-build-our-own-router.md)) — answered on the preemption point, which is the point §5A.5 item 2 addresses. **KServe's multi-node behaviour is documented and unverified by us, exactly as Ray's is.** The difference is that **Ray's single-node behaviour on our core path has been measured, and it was bad** — so the two options are not symmetrically unverified. (a)'s unknowns sit on top of a measured 15 × penalty; (c)'s do not.

**The verdict on (c), stated plainly:** **under mandatory multi-node it is the strongest of the three**, and it is strongest for a reason that should be uncomfortable: **it is what our own planning documents said all along, and the last two revisions of this file did not consider it because the question was framed as "Ray vs. homemade" and nobody re-opened the frame.**

### 5A.6 The key asymmetry — a measured present cost against an unwritten distributed scheduler

**The trade, stated as sharply as it can be:** adopting Ray for multi-node means accepting a **measured, present, ~15 × penalty on the core path** in exchange for **not writing** distributed scheduling. Is that trade good?

**The strongest case that it is, stated without hedges, per the bias discipline in the header:**

> Ray's costs are **known, bounded and already worked around**. Four private-source workarounds in hand. The runbook. The reaper. And now the exact latency number, located to the phase. **Every one of Ray's costs in this document is a number or a source line.** A from-scratch distributed scheduler is an **unknown** cost, written by people who have not written one before. **Unknown costs break schedules; known ones get budgeted.** On the requester's own priority — *"robust and easy to maintain"* — a mature framework that has solved multi-node for thousands of users is, on its face, the more robust answer than code we have not written.

**That argument is correct on its own terms and I have no measurement that refutes it. What defeats it is not a counter-argument about Ray's quality — it is that the trade as stated is a false pair.** Three reasons:

1. **The exchange is not "penalty for no distributed scheduling". It is "penalty for *Ray's* distributed scheduling, whose placement path is the thing we measured stalling."** §5A.2: no mechanism relieves it at multi-node, three of four hypotheses worsen it **[I]**. **You do not escape writing a scheduler by adopting one whose scheduling is what you measured as the problem.**
2. **The trade ignores that a third party will write it either way.** The genuinely hard pieces of §5A.4 — membership, fencing, distributed ownership — are provided by **Kubernetes** under option (c), with a far larger operational track record than Ray's, and **without** the 15 × penalty and **without** the deprecated GPU path. **So "don't write distributed scheduling yourself" does not imply Ray. It implies a platform, and Ray is the more expensive of the two platforms on the table.**
3. **The penalty lands on the one path the product exists to serve, and this is the part that is now measured rather than inferred.** §5.1.1: the stall requires a pending request. **50 cycles that polled to RUNNING before probing never stalled; 8/20 that probed immediately did** **[M]**. Tool-swap *is* the request-triggered path. **A framework penalty that spared our hot path would be a tolerable trade for distributed scheduling. One that lands exclusively on it is not.**

**And here is where [`00_CONTEXT_AND_MOTIVATION.md:228`](../plan/00_CONTEXT_AND_MOTIVATION.md:228) cuts both ways, as the requester rightly flagged** — *"tool-swap is a thin, opinionated, self-hostable orchestrator whose value is in the **swap/TTL/proxy/authoring UX**, not in inventing inference technology."*

| Direction | The argument |
|---|---|
| **Against building our own** | Writing a distributed scheduler **is** inventing infrastructure technology. It is the clearest possible violation of that sentence, and **D12** (*prefer existing self-hostable software*) says so too. **Under mandatory multi-node, option (b) is on the wrong side of this project's own stated value.** |
| **Against adopting Ray** | The sentence says the value **is** the swap UX. **Swap is the hot path.** A platform that makes swaps take 100 seconds 40 % of the time has degraded precisely the thing the sentence names as our value — while the parts of Ray we would be buying (distributed actors, object store, model composition) are inference technology we were told not to invent *and do not need*. **[I]** |

**Both readings are correct, and together they point at neither (a) nor (b).** The sentence says: *don't invent infrastructure* **and** *protect the swap UX*. **Only option (c) satisfies both** — Kubernetes provides the infrastructure we would otherwise invent, and the swap path stays ours as a preemption controller, which [`14 §8.4`](../plan/14_ALTERNATIVES_EVALUATION.md) already identifies as *"the same work we would be doing here anyway"*.

### 5A.7 The ranking under mandatory multi-node, and the one testable sentence

**Ranking, with the deciding reason for each position:**

| Rank | Option | Deciding reason |
|---|---|---|
| **1** | **(c) KServe / Seldon on Kubernetes** | **If multi-node is mandatory you are paying for Kubernetes under two of the three options. (c) is the one where you pay for it once and get the three genuinely hard pieces — membership, fencing, distributed ownership — from the most operationally proven substrate available, while keeping the eviction policy, which is the part that is actually ours.** It is also this project's own recorded answer at cluster scale ([`00_CONTEXT_AND_MOTIVATION.md:225`](../plan/00_CONTEXT_AND_MOTIVATION.md:225)) |
| **2** | **(b) Build our own, extend later** | **Preserves everything and commits to nothing, which is worth a lot** — but under a *mandatory* requirement it eventually asks a team that has never written consensus to write consensus on a clinical-inference critical path. **Second because it remains the right first move even if (c) is the right destination** (§5A.8) |
| **3** | **(a) Adopt Ray** | **Last, and it is not close.** Robust multi-node Ray is KubeRay, so it does not avoid Kubernetes — it adds a measured ~15 × core-path penalty **[M]** and a deprecated per-host GPU path **on top of** Kubernetes. **Strictly dominated by (c)** on the very axis it was proposed to win: the one piece of Ray's distributed machinery we measured is its replica placement, and it stalls **[M]**/**[I]** |

**The one testable sentence, since the honest answer to "is (c) right?" is conditional:**

> **If a second GPU host is budgeted AND the requirement is one scheduler across all hosts rather than more capacity, then adopt Kubernetes-native serving (c); measured by whether a request for a tool resident on host B, arriving at host A, must be *scheduled* there rather than merely *forwarded* there.**

**That is testable with no hardware**: it is answered by asking whether tools are pinned to hosts or must float. **If tools can be statically assigned to hosts, federation answers it (§5A.10 path ii) and no cluster is needed. If tools must float across hosts under one policy, that is cross-host scheduling and it is Kubernetes.**

### 5A.8 What survives under every option — the requester's "huge rewrite" fear, answered

The fear is a *"huge rewrite"*. **The most useful thing this analysis can do is be precise about what is at risk, and the answer is the same under all three options.**

| Asset | Survives (a) Ray? | Survives (b) extend? | Survives (c) KServe? |
|---|---|---|---|
| **`tools.yaml`** — the config the scientists write | **Yes** — adoption adds a generator ([`case-for-ray-native.md`](case-for-ray-native.md) §7) | **Yes** — gains a host dimension | **Yes** — maps to `InferenceService` near field-for-field ([`14 §8.2`](../plan/14_ALTERNATIVES_EVALUATION.md)) |
| **The ~20 tool images** | **Yes** **[M]** — the `container` key is proven to run them with a real GPU | **Yes** | **Yes** — guardrail 11 makes each one a valid custom predictor ([`14 §8.5`](../plan/14_ALTERNATIVES_EVALUATION.md)) |
| **`handler.py`, the authoring contract, the runtime** | **Yes** | **Yes** | **Yes** — *"the authoring UX is the part KServe never provided, so it is exactly the part we would still want afterwards"* ([`14 §8.1`](../plan/14_ALTERNATIVES_EVALUATION.md)) |
| **ADR-0005's plain-data boundary** | **Yes — the same constraint either way** **[M]** (D27) | **Yes** | **Yes** |
| **The eviction policy / pure scheduler** | Relocated to a Ray autoscaling policy | Widened signature | **Survives as a preemption controller** — *"the same work we would be doing here anyway"* ([`14 §8.4`](../plan/14_ALTERNATIVES_EVALUATION.md)) |
| **The router** — backend, proxy, watchdog, state | **No** | Grows | **No** ([`14 §8.3`](../plan/14_ALTERNATIVES_EVALUATION.md)) |

**The answer to the fear, in one line: the durable assets survive all three options, and the thing that gets rewritten is the router — the ~4,000-line component this project has always called replaceable.** [ADR-0001](../plan/adr/0001-build-our-own-router.md)'s hedge — *"the tools are the durable asset; the router is replaceable"* — is doing exactly the job it was written for. **The rewrite the requester fears is not on the table under any option.**

**Stated fairly in the other direction:** whatever router we build in the meantime is thrown away at migration, so that work is paid twice. **That is true of every option including (a)**, since adopting Ray today still discards M2/M3/M6/M7 as planned and rebuilds them as a config generator, a supervisor and a reaper (§2.2).

### 5A.9 What would actually make multi-node a must — and does each trigger imply Kubernetes?

> **This subsection is what remains of the previous revision's §5A.8, and it is demoted deliberately.** Scoring multi-node's likelihood was the wrong centre for this section. **But "what would trigger it" is a genuinely useful question**, and it has a sharp finding: **most triggers imply Kubernetes directly, which is why the Ray-vs-homemade framing keeps producing the wrong answer.**

| Trigger | What it would take | Does it *also* imply Kubernetes? |
|---|---|---|
| **GPU count exceeds one chassis** | More GPUs than a DGX holds, or a second box bought because the first is saturated | **Not necessarily.** This is *"we have more GPUs"*, not *"we need one scheduler across them"*. **Static federation answers it** — a second host runs its own tool-swap and the first forwards what it does not own ([`14 §8.6`](../plan/14_ALTERNATIVES_EVALUATION.md), llama-swap's `peers`). **The one trigger with a cheap answer** |
| **High availability — the service must survive a host failure** | A stated uptime requirement for clinical inference | **Yes, effectively.** HA needs health, fencing and failover — the three hard pieces of §5A.4. **And it specifically excludes option (a) as configured**, since Ray's head node is a cross-cluster single point of failure whose recovery is a manual runbook ([`architecture.md:42`](../plan/third-party-docs/ray-serve/architecture.md:42), §5.2 **[M]**). **An HA requirement is the cleanest possible argument against non-KubeRay Ray** |
| **Tenancy isolation — more than ~two parties kept apart** | A second research group, or a data-governance boundary | **Yes, directly.** Namespaces, RBAC, network policy and quota are Kubernetes' native vocabulary, and [ADR-0001](../plan/adr/0001-build-our-own-router.md) already lists *"multi-tenant isolation becomes a requirement"* as a **Kubernetes** trigger — not a Ray trigger |
| **Aggregate throughput — one host cannot serve the load** | Sustained concurrent demand exceeding a chassis | **Not necessarily**, and it is worth separating from the first row. If the bottleneck is *throughput per tool*, the answer is replicas, which is a `replicas` knob ([`00_CONTEXT_AND_MOTIVATION.md`](../plan/00_CONTEXT_AND_MOTIVATION.md) §5, *"a documented future knob"*), not a cluster. **If it is throughput across a zoo larger than the hardware, that is cross-host scheduling and it is Kubernetes** |
| **An infrastructure team already operating Kubernetes takes on the deployment** | An organisational change, not a technical one | **Yes by definition — and it inverts the cost entirely.** [ADR-0001](../plan/adr/0001-build-our-own-router.md) and [`14 §8.6`](../plan/14_ALTERNATIVES_EVALUATION.md) both already list this. **If this fires, (c) wins outright and cheaply** |

**The finding, and it is the point of the subsection: four of five triggers imply Kubernetes, and none implies Ray.** The only trigger with a cheap non-Kubernetes answer is *"we have more GPUs"*, and its answer is **federation**, not Ray. **[I]**

> **So the Ray-vs-homemade framing is the wrong question whenever the trigger is real.** Ray is the answer to a trigger that does not appear on this list: *"we need a distributed actor runtime with a shared object store"*. **That is not what a second GPU host means, and it is not what this project does** ([`00_CONTEXT_AND_MOTIVATION.md:228`](../plan/00_CONTEXT_AND_MOTIVATION.md:228)).

**And the one fact that materially lowers the urgency, which survives from the previous revision because it is correct and does not depend on likelihood scoring: multi-node arrives with notice.** A second GPU host, an HA requirement and a second tenant are all **procurement or policy events**, not runtime surprises. **There is no scenario in which we wake up distributed.** **[I]** That is what makes deferring cheap — not the claim that it will never happen.

**What the requester's three askings do change, and this should be said plainly:** a concern raised three times is itself a demand signal. **It does not make multi-node a requirement, but it does make "what happens if it is" a question that deserved this section rather than a likelihood score — which is what revision 2 gave it, and why this revision rewrites it.**

### 5A.10 The paths, re-priced under the assumption

| Path | What it costs now | What it costs at mandatory multi-node | Verdict |
|---|---|---|---|
| **(i) Build single-node now behind interfaces that do not preclude a distributed backend** | **Nothing beyond what we already do.** `ContainerBackend` is a `Protocol`; the scheduler is pure and never-trim; ADR-0005 mandates the plain-data boundary; guardrail 11 keeps every image a valid KServe predictor. **The insurance is already bought** | The router is rewritten; the zoo, `tools.yaml` and the tool contract are not (§5A.8) | **Still best value, and now for a better reason.** The same properties that make a Ray migration an extension make a **KServe** migration one — [`14 §8.5`](../plan/14_ALTERNATIVES_EVALUATION.md) calls the insurance *"free, because every item is something we want for its own sake"* |
| **(ii) Static federation when a second host appears** | Nothing now | **Much less than a cluster.** No control plane, no distributed state, no scheduler rewrite — **and no cross-host scheduling either** | **The right answer to *"we have more GPUs"***, and §5A.7's testable sentence is exactly the test for whether this suffices. [`14 §8.6`](../plan/14_ALTERNATIVES_EVALUATION.md): *"price federation first"* |
| **(iii) Adopt Ray now** | **The full measured cost, today**: ~93 s of pre-container dead time on ~40 % of request-triggered swaps **[M]**, a deprecated API with a per-host absolute path, four private-surface behaviours re-verified every upgrade, three failure modes that report success, an operator runbook | **Not lower — and plausibly higher** (§5A.2), plus KubeRay for robustness, i.e. Kubernetes anyway | **Worst of the four.** Pays a measured premium now for a payout that §5A.2 gives no mechanism to deliver |
| **(iv) Adopt Kubernetes-native serving at the point a real trigger fires** | Nothing now | The router migration, against a platform whose migration is **already mapped field-by-field** in [`14 §8`](../plan/14_ALTERNATIVES_EVALUATION.md) | **The destination, and (i)+(ii) are how you keep it open.** This is what *"keep as the documented growth path"* ([`00_CONTEXT_AND_MOTIVATION.md:225`](../plan/00_CONTEXT_AND_MOTIVATION.md:225)) always meant |

**Path (i) now, (ii) when capacity is the issue, (iv) when scheduling is the issue.** **What changed in revision 3 is the destination, not the first step:** the previous revision's path (iv) was *"adopt Ray at the point multi-node becomes real"*. **§5A.2 through §5A.5 are the reasons that destination is wrong, and the repository's own documents had the right one written down before this analysis started.**

### 5A.11 "Complexity we have no experience in" — engaged directly

**The requester is right, and this deserves better than a reassurance.** Writing a distributed scheduler for the first time, under deadline, is **a genuinely different risk class** from working around a documented framework quirk. The two failure modes are not comparable:

- **A framework quirk** has a fixed shape. You read the source, you find `run_options=[]`, you write the workaround, and the cost is paid once and known. The spike is the proof: four private-source reads, four workarounds, all in hand **[S]**.
- **A distributed-systems bug** has an unbounded shape. Split-brain, partial failure, stale membership and races that appear only under load are the classic ones, and they are exactly the bugs that do not reproduce on a laptop. Nobody on this project has written one before — that is the requester's point and it is accurate.

**But the spike cuts both ways here, and I will not pretend otherwise.** The four private-source reads show *both* that we **can** debug Ray's internals **and** how much each Ray surprise costs: D22 was an **uncaught C++ abort with no message, diagnosed by `strace`** **[M]**. That is not a cheap debugging session either, and there were seven host runs and ~43 fixes around it.

**The distinction that survives the two-way cut** was the previous revision's centre: Ray's surprises are **bounded and already discovered** — four found, four worked around. Distributed-systems bugs we have not written yet are **undiscovered and unbounded**. Those are not the same risk even when the per-incident cost is similar, and §5A.6 states that argument at full force.

**What revision 3 adds, and it is what turns the argument away from Ray rather than toward it** **[I]**: the choice was never *"bounded Ray surprises vs. unbounded distributed-systems bugs"*. **Under (c), the unbounded distributed-systems bugs are Kubernetes' to have already found** — membership, fencing and distributed ownership are its core, exercised by an operational population orders of magnitude larger than Ray Serve's containerised-GPU path, which §3.1 shows we are among the few to walk. **The "bounded vs. unbounded" argument is an argument for a platform. It is not an argument for *this* platform**, and §5A.2 is why: the one part of Ray's distributed machinery we measured is the part that stalls.

---

## 5B. Superseded subsections

> **Revision 3 removed the previous §5A.5 (*"What Ray's multi-node payout actually is"*), §5A.7 (*"What the spike makes easier"*), §5A.8 (*"How likely, and when?"*) and §5A.9 (*"The middle paths, priced"*).** They are not deleted from the argument — each is **absorbed and answered** rather than dropped:
>
> | Previous subsection | Where it went |
> |---|---|
> | §5A.5 Ray's payout and the KubeRay catch | **§5A.3**, where the catch is load-bearing rather than a caveat: it is why option (a) is dominated |
> | §5A.7 What survives a migration | **§5A.8**, widened from *"survives a Ray migration"* to *"survives all three options"* — which is the more useful table and the actual answer to the rewrite fear |
> | §5A.8 Likelihood scoring on the demand axis | **§5A.9**, reframed from *"how likely is multi-node"* to *"what would trigger it, and does each trigger imply Kubernetes"*. **The demotion is deliberate and is the method correction this revision is built on** |
> | §5A.9 The middle paths | **§5A.10**, with path (iv)'s destination changed from Ray to Kubernetes-native serving |

---

## 6. Scoring both options on the complexity audit's axes

Using [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §1: **class** (⬛ forced · ⬜ chosen · ⚠ elective), **demand**, **carrying cost**. The audit's hunting rule is *"an elective decision answering an inferred demand at high carrying cost"*.

> **Scope note for revision 3.** §6 scores the **present-day** decision — the two options that are live *today*, under the protocol's Rule 3. **Option (c)-KServe is not scored here**, because today it is rejected by the same reasons [`00_CONTEXT_AND_MOTIVATION.md:225`](../plan/00_CONTEXT_AND_MOTIVATION.md:225) gives (*"requires Kubernetes, contradicts R1 and D8"*), which remain valid at one node. **§5A is where the mandatory-multi-node counterfactual is scored, and it reaches a different ranking on a different premise.** Keeping the two scorings separate is deliberate: collapsing them is what would let a hypothetical requirement drive a present-day decision.

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
| **~93 s of pre-container dead time on ~40 % of request-triggered swaps** **[M]** | ⬛ **forced by adoption.** Revision 2 wrote *"⬜ chosen if tuning works"*; §5.1.1 removes that escape — the phases tuning would target measured **15 ms combined** | none — it is a consequence | **High, measured, and now *located*** (§5.1.1, ledger §9Z). ~15× on the core path. **Mechanism unknown** **[A]**, which is worse than a known default: an unknown cost cannot be budgeted |
| **Deleted:** M2, M3 proxy internals, M3.5, M6 watchdog, M7 collector | — | — | ***Negative — the real win.*** ~25–35 % of v1 **[A]** |
| **Gained free:** dashboard, per-replica status, metrics, object store, replica self-healing **[M]** | — | — | ***Negative.*** Genuine, and better than what v1 would build |
| **Gained: a multi-node path we would otherwise write** | ⬜ chosen | ⚠ **hypothetical** for multi-node itself; ***quotable*** for *"avoid huge rewrite"* (§5A.9) | ***Negative — but revision 3 shrinks this item substantially.*** Still partial (robust multi-node Ray is KubeRay, §5A.3), and now additionally: **the placement path this row is buying is the path measured stalling**, with no mechanism to improve at multi-node (§5A.2) **[I]**. **Under a *mandatory* multi-node premise this row does not rescue (a) — it ranks third (§5A.7)** |

**Audit verdict on (a):** **chosen**, answering a **quotable** demand, at **high** carrying cost — with a large negative-cost offset. It is *not* the pattern the audit hunts (that pattern is elective + inferred + high, which is what soft unload was). **The decision is legitimate on the audit's own terms**; it turns on whether the negative offset exceeds the high permanent cost. §11 is where I take a position.

**What the two new inputs did to this table, in opposite directions:** step 8 **added a high-carrying-cost row that is fully measured** (~100 s vs ~5 s), and multi-node **added a large negative-cost row whose demand is hypothetical and whose payout is partial**. The audit's own rule — demand drives weight — is what separates them.

**Revision 3 changes the balance again, and this time both changes cut the same way** — which is unusual enough in this file to state explicitly. **(1)** The cost row loses its *"⬜ chosen if tuning works"* escape, because the phases tuning would target measured 15 ms (§5.1.1). **(2)** The benefit row shrinks, because the capability being bought — replica placement — is the measured stall, and §5A.2 finds no mechanism by which it improves at multi-node **[I]**. **The row that was (a)'s largest offset is the row most damaged by the new measurement.**

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
| **Swap latency** | — | — | **Low, and measured.** Our router inherits the container's **~5 s**, not Ray's ~100 s **[M]** (§5.1). This row previously read as an unattributed risk; it is now a modest, known cost |
| **A future multi-node migration** | ⚠ elective *insurance* | ⚠ **hypothetical** requirement; ***quotable*** concern (§5A.9) | **Deferred, bounded to the router, and largely pre-paid.** The pure scheduler survives, the `ContainerBackend` seam exists, ADR-0005 mandates the plain-data boundary, **guardrail 11 keeps every image a valid KServe predictor**. **The zoo, `tools.yaml` and the tool contract are not rewritten under any option** (§5A.8). **Revision 3 correction:** the insurance is better than revision 2 claimed, because it insures against the *right* destination — [`14 §8`](../plan/14_ALTERNATIVES_EVALUATION.md) maps the KServe migration field-by-field, and nothing equivalent exists for Ray |
| Everything Ray would give free | — | — | **Positive cost.** We build a smaller `/status` and no dashboard, and we defer the multi-node path rather than having it |

**Audit verdict on (c):** almost every component is **forced** by a **quotable** demand at **medium** carrying cost. That is the profile [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §2 finding 2 asserted — *"that is proportionate"* — and the spike does **not** falsify it (§10.1). What the spike *does* falsify is the second half of that sentence, *"the alternatives cost more (§6)"*, which was stated on desk evaluation and is now a measured question with a genuinely mixed answer.

### 6.3 The two profiles side by side

|  | (a) Ray | (c) Our router |
|---|---|---|
| Code we own | **Less** — by ~25–35 % **[A]** | More |
| **Swap latency (measured)** | **~93 s of pre-container dead time, ~40 % of request-triggered swaps** **[M]** — and the stall *requires* a pending request, so it lands only on our hot path (§5.1.1) | **~5 s, tight, no tail** **[M]** — the inherited container cost only |
| **Multi-node, if it ever arrives** | **Provided — but the placement path is the one that stalls, with no mechanism to improve at multi-node (§5A.2) [I], and robustly it means KubeRay, i.e. Kubernetes (§5A.3)** | **A router migration** — bounded to the router; the zoo and `tools.yaml` survive (§5A.8) **[A]**. **And the migration is toward KServe, which [`14 §8`](../plan/14_ALTERNATIVES_EVALUATION.md) already maps field-by-field** |
| **Testability of the code we own** | **Worse.** Correctness depends on cluster-level conditions the spike needed 7 host runs and ~43 fixes to observe **[I]** | **Better.** M2/M3/M6 are fakes plus one real round trip; the scheduler is pure |
| Dependencies carried | Ray (private-surface + deprecated key), podman, version lockstep **[M]**/**[S]** | Docker, FastAPI, BentoML — all per-image and gradual |
| Failure modes handled | Ray's, including three that report success **[M]** | Ours, including ones we have not met yet **[A]** |
| Hours spent | Operating a cluster; re-verifying private behaviour per upgrade | Writing and maintaining ~4,000 lines **[A]** |
| Bus factor | **Much better** | *"Worst"*, by the plan's own score |
| Recovery | Replica: automatic **[M]**. Cluster: operator runbook **[M]**, whose blast radius **grows** with node count (§5A.3) | Both **[A]**, unwritten |

**This table is the analysis.** Everything else is its derivation.

**What revision 2 changed in it.** The original split 3–3. Step 8 added a row (c) wins **on measurement rather than estimate**, and multi-node added a row (a) wins **on structure rather than measurement**. (a) won **bus factor, recovery-today and multi-node-if-it-arrives**; (c) won **testability, dependencies, failure modes and latency**.

**What revision 3 changes.** **The multi-node row is no longer a clean (a) win**, on two grounds stated separately because they have different evidence classes: the placement capability being bought is the measured stall **[M]**, and adding nodes gives no mechanism to relieve it **[I]** (§5A.2). **(a) is left winning bus factor and recovery-today outright** — both still real, neither touched by any measurement in the multi-node direction.

**The asymmetry that matters is not the count of rows but their evidence class: (c)'s wins are increasingly [M], and (a)'s remaining wins are [A] or conditional.** Revision 3 sharpens that: **(a)'s one structural win has had its own critical path measured, and it failed.** §11.0 is where this is weighed rather than merely noted.

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

- **For our own router, D25 is vindicated and is cheap to satisfy.** The premise *"displacement takes quite some time"* was true of Ray, not of the container.
- **For Ray, D25's gate bites hardest**, because there displacement is the ~100 s path.
- **The question does not disappear**, because it is still unanswered for real traffic, and a *"waiting is tolerable"* answer would still shrink our scheduler to a TTL timer and re-admit off-the-shelf candidates ([`ray-native-reconsideration.md`](ray-native-reconsideration.md) §5). **But it is now much less likely to flip the decision**, because the thing it would trade away — displacement — turns out to cost 5 s rather than 100 s. **[I]**

**Step 9 sharpens this further, and in the same direction** **[M]** (§5.1.1). Revision 2 could still have been read as *"Ray's autoscaler is slow to release, which a patient design might tolerate"*. **It is not a release problem. A request is already waiting, and Ray does nothing for ~90 s before starting the container** — the stall's precondition **is** the pending request. **So the wait-versus-displace question cannot be answered on Ray by choosing to wait: under Ray, waiting is what the ~93 s already is, and it is imposed rather than chosen.** **[I]**

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
| ~~**The latency attribution baseline**~~ | **RESOLVED** by step 8 **[M]** (ledger §9T, D45): container ~5 s, Ray's path ~100 s | *Was* the most decision-relevant unknown. It resolved **against** Ray. §5.1 |
| ~~**Whether Ray's displacement path tunes from ~100 s to ~10 s**~~ | **LARGELY MOOT** after step 9 **[M]** (ledger §9Z, D54). The phases the two knobs govern measured **15 ms combined**; the ~93 s is pre-container dead time the knobs do not reach | The tuning experiment would have measured the wrong thing. **§12 is rewritten around the successor question** |
| **What mechanism causes the ~93 s pre-container stall** | **Unknown, and deliberately un-guessed** **[A]**. Retry/backoff, a lock, a queue interaction, a health-check cycle — ledger §9Z refuses a sixth attribution after five wrong ones | **The new most decision-relevant unknown.** It decides whether the cost is a defect (fixable, possibly already fixed upstream), a configuration (tunable), or structural (permanent). **Controller and proxy logs for a slow cycle are the next place to look** — §12 |
| **Multi-node anything** | **Untested by every step 1–9.** The spike ran on one host and never started a second | §5A's multi-node claims are **[I]** and **[A]** throughout, on all three options. **§5A.2's "the stall does not improve at multi-node" is [I] from [M] plus a cited architecture page — it is reasoning, not measurement, and a second host would settle it** |
| **Whether the stall reproduces on a Ray version other than 2.57.0** | **Untested** **[A]** | If a later Ray does not stall, the single largest measured cost in this document disappears. **Cheap to check and nobody has** — §12 |
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
4. **Nothing was measured about multi-node — on any of the three options.** No step 1–9 started a second host. **§5A is the most consequential section in this document and it is argument, not measurement**: Ray's multi-node capability is taken from its documentation, KServe's is taken from its documentation and from [`14 §8`](../plan/14_ALTERNATIVES_EVALUATION.md), and our own migration cost is **[A]**. **The section most likely to be quoted is the section with the least measurement behind it**, and a reader should weight it accordingly. **What revision 3 adds is not measurement but a reasoned chain that can be checked**: §5A.2 reasons from a **[M]** single-node stall plus a cited statement that the controller is global, to an **[I]** conclusion about node count. **A reader who rejects the inference should say which link fails.**
5. **Nothing was measured about the bus factor**, which remains the strongest un-spiked pro-Ray argument (§4 item 6) — **though §5A.5 item 5 notes it is an even stronger argument for Kubernetes than for Ray**, which is a point revision 2 missed.
6. **Nothing was measured about KServe at all.** Spike B was *"answered on the record, not run"* ([ADR-0001](../plan/adr/0001-build-our-own-router.md)), on the preemption point only. **§5A.5 ranks (c) first under mandatory multi-node on documents and on this repository's own prior analysis — not on any measurement we have taken.** That is a real asymmetry with (a), whose costs *are* measured, and it is stated here rather than buried: **(a)'s costs are known and bad; (c)'s costs are unknown.** The ranking rests on the claim that (c)'s unknowns are ordinary-Kubernetes unknowns while (a) carries the measured penalty *on top of* arriving at Kubernetes anyway.

**The step-8/9 figures carry three limits of their own**, restated here so they are visible outside §5.1: **Ray's teardown half was not measured** (`mode=full` was not run); **the stall's mechanism is unknown**, so it cannot be called a floor *or* a default; and the figures are **two runs of 20 on one host with a warm image store** — stronger than revision 2's single run, since the bimodality reproduced across two harnesses at the same rate, but still one host, one GPU, two tools.

---

## 10. What the spike falsifies in the existing position

### 10.1 [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §2 finding 2

> *"The router itself is not the problem. After the descope, the core is a config loader, a container backend, a pure scheduler of a few hundred lines, a proxy and a watchdog. That is proportionate, and **the alternatives cost more (§6)**."*

**First clause: not falsified.** §6.2 scores every component as forced-by-quotable-demand at medium cost. The spike gives no reason to think the router core is disproportionate.

**Second clause — *"the alternatives cost more"* — is now a measured question with a mixed answer, and it must be downgraded.** It was asserted from desk evaluation (§6 of the audit cites [ADR-0001](../plan/adr/0001-build-our-own-router.md) and [`15`](../plan/15_RAY_SERVE_EVALUATION.md), both pre-spike). Measurement shows:

- Ray **does** delete five milestones' worth of scope **[A]**, and it **does** deliver step 3, replica self-healing and 20/20 reliability **[M]**;
- Ray **also** costs a deprecated-API dependency, four private-source behaviours, three silent failure modes and an operator runbook **[M]**/**[S]**.

**"The alternatives cost more" is not established by the evidence. It is defensible as a judgement, and it should be labelled as one.** The audit's own §6 sentence — *"every one of them requires operating a cluster and still writing the scheduler"* — survives intact and is the strongest true version of the claim.

**Revision 2 update, in both directions.** Step 8 moves this clause **toward** the audit's original assertion on one specific, measured axis: on **swap latency**, the alternative does cost more — ~100 s against ~5 s **[M]** (§5.1). That is no longer a judgement. **But §5A moves it the other way on a different axis**: on **a multi-node future**, the alternative may cost *less*, because Ray provides cross-host scheduling we would otherwise write. **So the clause remains a judgement overall** — better-informed, with one axis measured and one newly identified and unmeasured.

**Revision 3 update, and it is a genuine correction to the sentence's scope rather than a re-weighting.** The audit's *"the alternatives"* was always read here as *"Ray"*, and **that reading was too narrow**. On the evidence now assembled:

- **On swap latency, the alternative (Ray) costs more, measured** — and revision 3 sharpens it from *"a slow default"* to *"~93 s of dead time on the request-triggered path, mechanism unknown"* **[M]** (§5.1.1).
- **On a multi-node future, the relevant alternative is not Ray at all.** §5A.9 finds four of five triggers imply Kubernetes and none implies Ray. **Against *Kubernetes-native serving*, "the alternatives cost more" is a claim this repository has never tested** — [`14 §8`](../plan/14_ALTERNATIVES_EVALUATION.md) maps the migration in detail without pricing the operational burden, and Spike B was *"answered on the record, not run"* on the preemption point only.

**So the downgrade stands and widens: *"the alternatives cost more"* is now established against Ray on one measured axis, and remains an untested judgement against Kubernetes — which is the alternative this project's own documents name as right at cluster scale.** That is the honest state of the clause.

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

> **Revision 3 note on what "option (c)" means, because the label is now overloaded and the ambiguity would be dangerous.** In §1's protocol table, **(c) = keep building our router**, and that is what this section recommends **for today**. In §5A, the three options are the *multi-node* ones and **(c) = KServe/Seldon on Kubernetes**. **These are different (c)s.** The present-day recommendation is *build our own router*; the mandatory-multi-node recommendation is *Kubernetes-native serving*. **They are compatible — building our own router now is how you keep the Kubernetes path open, and §5A.10 path (i) is the bridge — but they are not the same answer to the same question.**

### 11.0 Does the recommendation change? Two questions, two answers

> **Revision 3 splits this section, because the requester asked two different questions and they have different answers.** §5A.0 states them in one line each; this is the weighing behind them.

#### (i) Does it change **today**? **No.**

**The recommendation stands, and revision 3 strengthens rather than weakens it** — the new measurement removed the one escape the cost row had.

| Input | Direction | Evidence class | Timing |
|---|---|---|---|
| **Steps 8 + 9 — ~93 s of pre-container dead time on ~40 % of request-triggered swaps** | **Against Ray**, strongly | **[M]** — two harnesses, two runs, VRAM-verified, log-corroborated to 80 ms | **Today.** Paid from the first week, **on the hot path only** |
| **Multi-node migration risk** | **For Ray**, and revision 3 weakens it | **[I]**/**[A]** — no step 1–9 touched multi-node | **Conditional** (§5A.9) |

**The single consideration that decided it: the cost is certain, present, and lands exclusively on the path the product exists to serve; the benefit is conditional, partial, and buys the very capability we measured failing.**

1. **Ray's headline cost is measured *and located*.** Not *"the autoscaler takes a while to release"* — **Ray does nothing for ~90 s while a request waits, ~40 % of the time** **[M]** (§5.1.1). The stall requires a pending request, which means **it is the request-triggered path or nothing**, and tool-swap is the request-triggered path.
2. **The "it is just a tunable default" escape is gone.** Revision 2 offered it in good faith; the phases those knobs govern measured **15 ms combined** **[M]**. What replaces it is worse for Ray: an **unknown mechanism** **[A]**. **A cost with a named cause can be budgeted; one without cannot.**
3. **The multi-node benefit shrank on inspection** (§5A.2). The capability being bought is replica placement, which is the measured stall, sitting in a **global controller that does not scale out** ([`architecture.md:15`](../plan/third-party-docs/ray-serve/architecture.md:15)). **[I]**
4. **The migration, when priced, is not the rewrite the requester fears** (§5A.8) — and it is not a rewrite under *any* of the three options. The durable assets survive all three.

**What would have flipped it:** had step 9 located the stall in container startup, or had the knobs explained it, Ray's largest measured con would have dissolved. **Neither happened, and step 9 was specified before it was run.**

#### (ii) Does it change **under the assumption that multi-node is mandatory**? **Yes — and not to Ray.**

**This is the requester's counterfactual and it gets an unhedged answer: under mandatory multi-node the recommendation becomes (c)-KServe — Kubernetes-native serving — which is this project's own documented answer at cluster scale** ([`00_CONTEXT_AND_MOTIVATION.md:225`](../plan/00_CONTEXT_AND_MOTIVATION.md:225)). **Ray ranks last, not first** (§5A.7).

**The deciding reason, in one sentence: under mandatory multi-node you are paying for Kubernetes under two of the three options — because robust multi-node Ray is KubeRay — and (c) is the only one where you pay for it once, without also carrying a measured 15× core-path penalty and a deprecated per-host GPU path.**

**Three things this does *not* mean, stated because the distinction matters:**

- **It does not mean adopt Kubernetes now.** The premise is counterfactual. §5A.9 lists what would make it real, and §11.4 carries the triggers.
- **It does not mean the work so far is wasted.** The opposite: guardrail 11, the pure scheduler, the `ContainerBackend` seam and ADR-0005 are exactly what make a KServe migration an extension rather than a rewrite, and [`14 §8.5`](../plan/14_ALTERNATIVES_EVALUATION.md) calls that insurance *"free, because every item is something we want for its own sake"*. **The preemption logic we write is the same work the migration needs** ([ADR-0001](../plan/adr/0001-build-our-own-router.md)).
- **It does not mean the requester's argument was wrong.** §5A.6 states it at full force and I have no measurement that refutes it: **unknown costs break schedules, and a first distributed scheduler is an unknown cost.** **I now think that argument is correct and points at Kubernetes rather than at Ray** — which is a change from revision 2, where I used it to argue for building our own. **Under mandatory multi-node, §5A.4 concedes that (b) asks a team that has never written consensus to write consensus on a clinical-inference critical path. That is a bad trade and revision 2 did not say so.**

### 11.1 The recommendation in one paragraph

On the axis the requester named — simplicity and long-term maintainability — the decisive consideration is **not the volume of code but the verifiability of it**. Option (c) keeps ~25–35 % more code **[A]**, and every piece of that code is a container backend, a proxy, a watchdog and a log collector that are testable with fakes and an injected clock, on a laptop, in milliseconds ([`09_IMPLEMENTATION_PLAN.md`](../plan/09_IMPLEMENTATION_PLAN.md) M2, and the audit's never-trim item 2, scheduler purity). Option (a) writes *less* code but makes its correctness depend on four private-source behaviours with no compatibility promise **[S]**, a deprecated `runtime_env` key that is mutually exclusive with most of the API and requires a host-specific absolute path in every GPU tool's config **[M]**, and three failure modes that report success **[M]** — on a system meant to run unattended. **Steps 8 and 9 add a fourth measured item to that side, and revision 3 sharpens it: Ray spends ~93 s doing nothing before it starts the container, on ~40 % of request-triggered swaps, and the stall requires a pending request — so it lands on our hot path and only there** **[M]** (§5.1.1). The spike is itself the measurement of how expensive those conditions are to verify: seven host runs and ~43 defect fixes to observe them **once**, on **two** tools and **one** GPU. **Against that, the strongest pro-Ray arguments are not answered by this paragraph and I will not pretend they are: the bus factor (the plan scores itself "Worst", and no spike changed that) and the fact that Ray's recovery is measured while ours is unwritten. The third — the multi-node migration — was the strongest of them in revision 2, and revision 3 finds it weaker than claimed: §5A.2 shows the capability it buys is the capability that stalls, and §5A.3 shows its robust form is Kubernetes anyway. They are why the conditions below are not decoration.**

### 11.2 Condition 1 — ~~resolve the latency attribution~~ ~~the tuning question~~ **the mechanism question**

> **Discharged twice over.** Step 8 attributed the cost to Ray (ledger §9T). **Step 9 located it** (ledger §9Z) — and in doing so **retired the successor condition revision 2 named.** The tuning experiment targeted `downscale_to_zero_delay_s` and `look_back_period_s`; step 9 measured the phases they govern at **15 ms combined** **[M]**. **That condition was well-specified and is now simply moot.**

**The successor, and it is narrower still:** if Ray is to stay in contention at all, someone must establish **what the ~93 s pre-container stall actually is** — a defect, a configuration, or a structural property. Ledger §9Z names where to look: **the controller and proxy logs for a slow cycle** (gaps G1–G2). **Until that is known, the cost cannot be budgeted, which is the strongest form the objection has yet taken.**

**And a second successor that did not exist before and is cheaper than either:** **does the stall reproduce on a Ray version other than 2.57.0?** Nothing in the spike is version-checked. **If a newer Ray does not stall, the single largest measured cost in this document disappears** — and that is worth knowing before any ADR quotes the figure as settled.

### 11.3 Condition 2 — answer the wait-versus-displace question (one sentence from the requester)

Per §7.6. If waiting is tolerable, our scheduler shrinks to a TTL timer, the gate that eliminates every off-the-shelf candidate disappears, and **the reuse argument likely wins outright**. It still costs nothing to ask.

**Step 8 has lowered this condition's leverage, and that should be said rather than left implied.** The previous revision ranked it above every measurement. But displacement **without an orchestrator costs 3.9–6.9 s** **[M]**, so the thing a *"waiting is fine"* answer would trade away is now known to be cheap. **D25** is vindicated for our own router rather than undermined. The question remains worth one sentence; it is no longer the highest-leverage open item (§12).

### 11.4 Condition 3 — the commitments that make this reversible rather than sunk

Recommending (c) is only honest if it comes with the triggers that would reverse it, per the ADR convention this project uses well:

| Trigger | Then |
|---|---|
| ~~**The latency baseline shows container startup dominates**~~ | **FIRED AND RESOLVED THE OTHER WAY** (ledger §9T). Container ~5 s, Ray ~100 s. Discharged; does not reverse the recommendation |
| ~~**Ray's displacement path tunes to ~10 s**~~ | **MOOT** (ledger §9Z). The knobs govern phases measuring 15 ms **[M]**. This trigger cannot fire as written and is withdrawn |
| **The ~93 s stall is shown to be a defect fixed in a later Ray, or is otherwise explained and eliminated** | **The successor trigger, and it is the one that would most change the picture.** §5.1 would soften from a measured core-path penalty to a version note, and Ray would become materially more attractive. **Untested — §12** |
| **`image_uri` gains user-supplied `run_options`, or the Docker/CDI path works** | The deprecated-API dependency and the host-specific path both disappear. §3.2 loses most of its force, and Ray becomes materially more attractive |
| **A second GPU host is added — the multi-node trigger, re-priced in revision 3** | **Do not reach for a cluster reflexively, and do not reach for Ray at all.** The order is: **(1) price static federation first** — a second host runs its own tool-swap and the first forwards what it does not own ([`14 §8.6`](../plan/14_ALTERNATIVES_EVALUATION.md)); **(2) apply §5A.7's test** — must a tool be *scheduled* on another host, or merely *forwarded* to one? Only the first needs a cluster; **(3) if it needs a cluster, go to Kubernetes-native serving, not to Ray** (§5A.3, §5A.5), because robust multi-node Ray is KubeRay and you would be paying for Kubernetes plus a measured core-path penalty; **(4) know what it costs — the router is rewritten; `tools.yaml`, the ~20 tool images, the tool contract and the ADR-0005 boundary are not** (§5A.8). **Revision 3 changed step (3): revision 2 said "adopt Ray when the requirement is one scheduler across all hosts". That was wrong, and [`00_CONTEXT_AND_MOTIVATION.md:225`](../plan/00_CONTEXT_AND_MOTIVATION.md:225) had the right answer written down all along** |
| **Multi-node stops being hypothetical — a second GPU host is *budgeted*, or an HA or tenancy requirement is stated** | **Re-run this analysis before the hardware lands, not after** — and re-run it **against KServe**, which has never been spiked (§9 item 6). **§5A is the counterfactual already worked through**, so the re-run is a validation rather than a fresh analysis. Cheap, because every trigger in §5A.9 gives months of notice |
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
- **Not** that **the multi-node risk is small.** §5A.6 states it at full strength and I have no measurement that refutes it. My claim is narrower: the insurance is already bought, the migration is bounded to the router, and **under a mandatory premise the answer is Kubernetes rather than either Ray or a bespoke distributed scheduler** (§5A.7).
- **Not** that **anything here is evidence about multi-node.** No step 1–9 started a second host. **§5A.2's conclusion that the stall does not improve with node count is [I] — an inference from a [M] single-node measurement plus a cited architecture page — and it is the load-bearing inference of the whole section.** If it is wrong, option (a) recovers substantially.
- **Not** that **KServe has been evaluated to the standard Ray has.** It has not been spiked at all (§9 item 6). **§5A ranks it first under mandatory multi-node on documents and prior analysis, not on measurement**, and that asymmetry is real: Ray's costs are known and bad, KServe's are unknown.
- **Not** that **the recommendation changes today.** It does not (§11.0 (i)). **The counterfactual answer in §5A is conditional on a premise that is not currently true, and it must not be quoted as a present-day recommendation to adopt Kubernetes.**

---

## 12. The cheapest experiment that would most change the answer

> **Two winners have now been run and this section is rewritten for the second time.** Revision 1 named the plain-podman baseline; it ran as step 8 and resolved §5.1 against Ray (ledger §9T). Revision 2 named the **autoscaler-tuning** experiment; **step 9 has made it moot before it was run** (ledger §9Z), because the knobs it would have turned govern phases measuring **15 ms combined** **[M]**. **That is worth recording as a small vindication of the method: a cheap locating measurement retired a more expensive tuning experiment.**

**The new experiment: read the controller and proxy logs for a slow cycle, and name the mechanism.**

### 12.1 Why this one, and why it beats the alternatives

**§5.1.1 states what is measured and refuses to name a cause, after five wrong attributions.** That refusal is correct and it leaves exactly one question open — **and the answer determines which of three very different things the ~93 s is:**

| If the mechanism turns out to be | Then |
|---|---|
| **A defect, fixed or fixable upstream** | The largest measured cost in this document becomes a version note. **Ray recovers materially**, and §11.4's successor trigger fires |
| **A configuration we have not found** | Same, conditional on tuning it without destabilising anything else |
| **Structural — inherent to how the controller places a replica against a pending request** | **§5.1 hardens into a permanent core-path property**, and §5A.2's inference about multi-node gains direct support rather than resting on the architecture page alone |

**It is decisive in all three directions, which is the test this section applies.** It is also the only remaining experiment that could still flip the present-day recommendation.

### 12.2 What to run

**No new code, no new fixture, no cluster changes, and no second host.** Ledger §9Z already names the gaps (G1–G2) and the step 9 harness already reproduces the stall on demand at ~40 %:

1. Re-run `SPIKE_STEP9_N=20 SPIKE_STEP9_PROBE=eager make step9`, which is known to produce ~8 slow cycles.
2. For a cycle whose `container_first_seen_s` exceeds ~90 s, **pull the controller log and the proxy log for the interval between the scale-up RPC and `runtime_env_setup`'s `Pulling image` line** — the ~93 s window, whose boundaries are already established to within 80 ms.
3. Report what Ray logged in that window, including *nothing at all*, which is itself a finding.

**A second, cheaper check that should be run alongside:** **does the stall reproduce on a different Ray patch version?** Nothing in the spike is version-checked (§9). This costs one fixture rebuild.

**A pre-specified interpretation, because §5.1's credibility comes from having done exactly this before the fact:**

| Outcome | Effect on the decision |
|---|---|
| **A named, fixable cause — a defect or a reachable configuration** | §5.1 softens toward a version-or-config note. Ray's cost side drops materially and **the §11.0 (i) weighing must be re-run.** This is the outcome that could still flip the present-day recommendation |
| **A named but structural cause** — inherent to placing a replica against a pending request | §5.1 **hardens into a permanent property of the core path**, and **§5A.2's multi-node inference gains direct support** rather than resting on the architecture page alone |
| **Nothing in the logs — 93 seconds of silence** | **The most damning outcome, and a real possibility.** An unattributable 90-second stall in an unattended clinical-inference path is not a cost that can be budgeted, mitigated or explained to an operator |

### 12.3 Why it is cheap

- **No new code.** The step 9 harness exists and reproduces the stall at ~40 % on demand.
- **No new dependency, no new fixture, no protocol amendment**, and no second host.
- **The window is already bounded to 80 ms**, so there is no search — just read the logs between two known timestamps.
- **It mutates nothing on the shared host** beyond what steps 3, 5 and 9 already did.

*(Scope note: this document does not modify `spike-e-ray-native/`. This is described as a recommendation, not performed. Two harness artefacts noted in ledger §9Z — a negative `serving_s` in eager mode and poll-quantised `replica_materialize_s` — should be fixed before that output is quoted elsewhere; neither entered the attribution.)*

### 12.4 Candidates I considered and rank lower, with reasons

- **A multi-node experiment — stand up a second host and test cross-host placement.** **Highest relevance to §5A, and I still rank it below — but the gap has narrowed.** It is not cheap: it needs hardware we do not have. **But §5A.2 now rests on an inference that a second host would settle directly**, and under a *mandatory* multi-node premise this becomes the **first** experiment to run rather than the last (§11.4). **What changed in revision 3: this is no longer "an expensive experiment to price a hypothetical" — it is the experiment that would test this document's most load-bearing [I] claim.**
- **Does the stall reproduce on another Ray version?** **Cheapest of all and it should be done alongside §12.2**, since a fixed-upstream defect would dissolve the largest measured cost here.
- **A second run of step 8** to confirm the headline figure. **Partly discharged**: step 9 reproduced the bimodality at the same ~40 % rate with a different harness, which is stronger than a repeat of the same one.
- **~~The autoscaler-tuning experiment~~** — **moot** (ledger §9Z). The knobs govern 15 ms of the cycle.
- **The Docker/CDI path for `image_uri`** — high upside (it could delete the deprecated-API dependency entirely, §3.2's biggest caveat), but **not cheap and possibly impossible**: Ray hardcodes podman at [`image_uri.py:76`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:76) **[S]**.
- **Multi-tool, multi-GPU scale beyond two** — the most *representative* gap (§9), but a week of work, and it refines rather than flips.
- **~~The plain-podman baseline~~** — **done** (ledger §9T).

**And the one thing still cheaper than any experiment:** §11.3, one sentence from the requester on whether waiting is tolerable. **Step 8 lowered its leverage** — displacement costs ~5 s, so **D25** is cheap to satisfy for our own router — but it remains free to ask. **A second one-sentence question now joins it, and it is §5A.7's test: must a tool be *scheduled* on another host, or merely *forwarded* to one? That single answer decides between federation and a cluster.**

---

## 13. Summary table

| Question | Answer |
|---|---|
| Can Ray do the job? | **Yes** **[M]** — step 3 passed, one GPU, two conflicting tools, both directions |
| Is it simpler in code volume? | **Yes** — five milestones leave scope, ~25–35 % **[A]** |
| Is it simpler in code we can *verify*? | **No** **[I]** — correctness moves to cluster-level conditions that took 7 host runs and ~43 fixes to observe once |
| Is it simpler in dependencies? | **No** **[S]** — a deprecated key, four private-source behaviours, version lockstep, rootless podman |
| Is it simpler in failure modes? | **No** for unattended operation **[M]** — three modes report success; one is an unmessaged C++ abort |
| **Is it faster to swap?** | **No — measured, and now *located*** **[M]** (§5.1.1, ledger §9Z). **Ray spends ~93 s doing nothing before it issues `podman run`**, on ~40 % of request-triggered swaps. Plain podman, identical VRAM-verified work: 3.9–6.9 s, no bimodality. **~15× on the core path** |
| **Where exactly does the time go?** | **Pre-container dead time inside Ray** **[M]**. Scale RPCs 8 ms, controller decision 7 ms, actor materialise 0.87 s — **all identical between fast and slow cycles**. Container first seen at ~3.0 s (fast) vs ~93.6 s (slow), corroborated against Ray's own log to **80 ms** |
| **Does the stall hit the path we care about?** | **It hits that path and only that path** **[M]**. A pending request is a **precondition**: 50 cycles that polled to RUNNING before probing never stalled; 8/20 that probed immediately did. **Tool-swap is request-triggered by construction** |
| Is it better on bus factor? | **Yes, clearly**, and no spike touched this. The plan scores itself *"Worst"* — **though §5A.5 notes Kubernetes beats both on this axis** |
| Is it better on recovery? | **Replica: yes, measured. Cluster: an operator runbook — but ours is unwritten [A]**, and the runbook's blast radius grows with node count (§5A.3) |
| **If multi-node became a MUST, what wins?** | **(c) Kubernetes-native serving — KServe/Seldon — not Ray and not a bespoke distributed scheduler** (§5A.7). **Ray ranks last:** robust multi-node Ray is KubeRay, so it does not avoid Kubernetes; it adds a measured 15× core-path penalty on top of it |
| **Does the stall improve at multi-node?** | **No mechanism for it to, and probably the reverse** **[I]** (§5A.2). It sits in a **global controller that does not scale out** ([`architecture.md:15`](../plan/third-party-docs/ray-serve/architecture.md:15)); adding nodes adds placement and metric traffic through the same actor. **Unmeasured at >1 node — we have one host** |
| **Is multi-node a rewrite or an extension for us?** | **An extension under every option.** Three pieces are tedious (placement decision, remote lifecycle, routing) and three are genuinely hard (membership, fencing, distributed ownership — i.e. consensus). **`tools.yaml`, the ~20 tool images, the tool contract and ADR-0005's boundary survive all three options** (§5A.4, §5A.8) |
| **What would make multi-node a must?** | GPU count beyond one chassis, HA, tenancy isolation, aggregate throughput, or an infra team already on Kubernetes. **Four of the five imply Kubernetes; none implies Ray** (§5A.9) |
| What is the biggest cost? | **The ~93 s pre-container stall on the request-triggered path** **[M]** |
| What is the biggest unknown? | **What the stall actually is.** Defect, configuration or structural — ledger §9Z refuses to guess after five wrong attributions. §12 |
| What is the biggest *unmeasured* risk? | **Multi-node on every option, KServe entirely, bus factor, and more than two tools on one GPU.** No step 1–9 touched any (§9, §5A) |
| **What does the analysis recommend TODAY?** | **(c)-build-our-own — unchanged, and strengthened**, because the cost row lost its tuning escape while the multi-node benefit row shrank. §11.0 (i) |
| **What does it recommend UNDER MANDATORY MULTI-NODE?** | **(c)-KServe — Kubernetes-native serving.** **The recommendation does change under that premise, and it changes away from Ray, not toward it.** §11.0 (ii), §5A.0 |
| Who decides? | **The requester.** Protocol Rule 3, and *"option (c) must not be chosen by default"* |

---

## 14. Provenance

**Read for this analysis:** [`spike-E-results.md`](spike-E-results.md) (all sections), [`spike-E-continuation.md`](spike-E-continuation.md) §§9j–9S, [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md), [`14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md), [`15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md), [`17_LLAMA_SWAP_PHILOSOPHY.md`](../plan/17_LLAMA_SWAP_PHILOSOPHY.md), [`09_IMPLEMENTATION_PLAN.md`](../plan/09_IMPLEMENTATION_PLAN.md), [ADR-0001](../plan/adr/0001-build-our-own-router.md), [ADR-0003](../plan/adr/0003-ray-serve-not-adopted.md), [ADR-0005](../plan/adr/0005-one-uniform-batched-calling-convention.md), [`case-for-ray-native.md`](case-for-ray-native.md), [`ray-native-reconsideration.md`](ray-native-reconsideration.md), [`ray-serve-mounts-and-deletion-scope.md`](ray-serve-mounts-and-deletion-scope.md), [`bias-audit-and-decision-procedure.md`](bias-audit-and-decision-procedure.md).

**Read for revision 2** (the step-8 result and the multi-node section): [`spike-E-continuation.md`](spike-E-continuation.md) **§9T (D45)** — the step 8 figures and, importantly, the four limits the step states about itself, all four of which are carried into §5.1 and §9 rather than dropped. For §5A: [`00_CONTEXT_AND_MOTIVATION.md`](../plan/00_CONTEXT_AND_MOTIVATION.md) §5 (the multi-node non-goal), [`01_ARCHITECTURE.md`](../plan/01_ARCHITECTURE.md) §§5.1/7/9/12 (the global scheduling lock, in-memory reconciliation, **D21** container-name addressing, the `ContainerBackend` `Protocol`), [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../plan/06_LIFECYCLE_TTL_AND_SCHEDULING.md) §§1/4/5.1/5.3/6 (the shared-node premise, bare-integer devices, the pure `request_slot`, and the *"a new `Policy` implementation, not a rewrite"* sentence), [`11_R8_CLIENT_PLAN.md`](../plan/11_R8_CLIENT_PLAN.md) (searched for node-count commitments; **there are none**), [`13_OPEN_QUESTIONS.md`](../plan/13_OPEN_QUESTIONS.md) and [`14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md) §8.6 (the second-host trigger and the **static federation** option), [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §§1/5 (the demand axis and the scheduler-purity never-trim item).

**Read for revision 3** (the located stall and the multi-node counterfactual): [`spike-E-continuation.md`](spike-E-continuation.md) **§9Z (D54)** — the step 9 eager run, the six-phase table, the 80 ms log corroboration, the eager/ready precondition finding, the deliberate refusal to name a mechanism after five wrong attributions, and the two harness artefacts the ledger flags as non-load-bearing. Also **§9X (D50)** and **§9Y (D52)**, which establish why the eager/ready distinction exists and why the earlier eager run never happened.

**Third-party documents verified during revisions 2 and 3:** [`plan/third-party-docs/ray-serve/architecture.md`](../plan/third-party-docs/ray-serve/architecture.md) — read again for revision 3 at four specific lines, because §5A.2's inference rests on them and an inference resting on a paraphrase is not checkable: [`:15`](../plan/third-party-docs/ray-serve/architecture.md:15) (*"A global actor unique to each Serve instance… responsible for creating, updating, and destroying other actors"* — **the controller does not scale out**), [`:16`](../plan/third-party-docs/ray-serve/architecture.md:16) (`proxy_location`, one proxy per node — **proxies do**), [`:42`](../plan/third-party-docs/ray-serve/architecture.md:42) (*"If you aren't using KubeRay, when the Ray cluster fails, Ray Serve cannot recover"*), [`:44`](../plan/third-party-docs/ray-serve/architecture.md:44) (GCS checkpoint **on the head node**), and [`:48-49`](../plan/third-party-docs/ray-serve/architecture.md:48) (the autoscaler runs **in the controller**, and every handle and replica pushes metrics to it).

**Project documents verified for revision 3's §5A:** [`00_CONTEXT_AND_MOTIVATION.md:225`](../plan/00_CONTEXT_AND_MOTIVATION.md:225) — **KServe/Seldon as *"The 'right' answer at cluster scale… Keep as the documented growth path"***, which is the finding that reframed the whole section, read alongside [`:228`](../plan/00_CONTEXT_AND_MOTIVATION.md:228) (*"value is in the swap/TTL/proxy/authoring UX, not in inventing inference technology"*) and [`:237`](../plan/00_CONTEXT_AND_MOTIVATION.md:237) (multi-node as a non-goal, **in the same document as the KServe growth path — they are a matched pair**). Also [`14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md) **§§8.1–8.6** — the KServe migration mapped field-by-field, what ports, what is discarded, the two things that must genuinely be rebuilt, the free-insurance invariants, the three triggers and the federation advice — and [ADR-0001](../plan/adr/0001-build-our-own-router.md) **Spike B** and its *"the preemption logic we now write is the same work a Kubernetes migration would require"*, which is §5A.5's strongest supporting citation and was written years before this question was asked.

**Ray source verified during this task** (not quoted from the ledger alone): [`resource_and_label_spec.py:454-471`](/usr/local/lib/python3.11/site-packages/ray/_private/resource_and_label_spec.py:454) — the explicit-`0`-is-not-autodetect behaviour, confirmed at `if num_accelerators is None:`. The other three private-source citations are quoted from the ledger with their file:line intact and were not independently re-opened here; a reviewer wanting to check them has the exact lines.

**Not modified**, per the constraints: the ADRs, [`spike-E-continuation.md`](spike-E-continuation.md), [`spike-E-results.md`](spike-E-results.md), [`spike-E-ray-native-protocol.md`](spike-E-ray-native-protocol.md), and anything under `spike-e-ray-native/`. Nothing committed, nothing pushed.

**Revision 3 changelog**, section by section:

| Section | Change |
|---|---|
| Header | Added the revision-3 note: the stall is located (§9Z), and §5A is rewritten to answer the counterfactual rather than score its likelihood |
| **§5.1** | **Retitled and extended.** Revision 2's attribution to autoscaler decay is marked **superseded** — it was reached by elimination, and step 9 measured those phases at 15 ms |
| **§5.1.1** | **New.** The located stall: the six-phase table, the ~93.6 s vs ~3.0 s container timestamp, the 80 ms log corroboration, what it rules out, **the pending-request precondition**, and the deliberate refusal to name a mechanism |
| **§5.1 limits** | Limit 2 **replaced**: *"configuration-dependent, not a floor"* → *"the mechanism is unknown, and an unknown mechanism is not a knob"*, which is **a worse position for Ray, not a better one**. Limit 3 strengthened — the bimodality reproduced across two harnesses |
| **§5A** | **Rewritten end to end, and the rewrite is a method correction.** Revision 2 scored multi-node's *likelihood*; revision 3 **assumes it and prices the options**. New: §5A.0 (the two answers up front), §5A.2 (does the stall improve or worsen at multi-node — **[I]**, with the counter stated), §5A.3/§5A.4/§5A.5 (options (a)/(b)/(c) priced individually), §5A.6 (the asymmetry, and how [`:228`](../plan/00_CONTEXT_AND_MOTIVATION.md:228) cuts both ways), §5A.7 (the ranking and the one testable sentence), §5A.8 (what survives under **all three** options), §5A.9 (the triggers, and whether each implies Kubernetes), §5A.10 (the paths, with the destination changed from Ray to Kubernetes) |
| **§5A — the third option** | **KServe/Seldon admitted to the analysis.** It was named as *"the right answer at cluster scale"* in this project's own documents and had been ignored by three rounds of Ray-vs-homemade framing |
| **§5B** | **New.** A map of which revision-2 subsections were absorbed where, so nothing looks silently dropped |
| **§6.1 / §6.2 / §6.3** | The latency row loses its *"⬜ chosen if tuning works"* escape; the multi-node row shrinks on both options; §6 gains a scope note keeping the present-day scoring separate from §5A's counterfactual |
| **§9** | Tuning row marked **moot**; two new unknowns (**the stall's mechanism**, **other Ray versions**); a sixth boundary added — **KServe has never been spiked, and the ranking rests on documents rather than measurement** |
| **§11** | Opening note disambiguating **the two different "(c)"s** — build-our-own today, KServe under the counterfactual |
| **§11.0** | **Split into (i) today and (ii) under mandatory multi-node.** Answers: **no** and **yes-but-not-to-Ray**. Includes the concession that revision 2 used the unknown-cost argument to argue for building our own, and that under a mandatory premise it points at Kubernetes instead |
| **§11.2** | Condition 1's successor **retired** — the tuning question is moot. Replaced by the **mechanism** question and a cheap version check |
| **§11.4** | Tuning trigger **withdrawn**; new trigger on the stall's mechanism; the second-host trigger re-priced with a four-step order that now ends at **Kubernetes rather than Ray**, with the revision-2 error named |
| **§11.5** | Four refusals updated or added, including **"not that KServe has been evaluated to the standard Ray has"** and **"not that the recommendation changes today"** |
| **§12** | **Replaced again.** The tuning experiment is moot before it was run; the successor is **reading the controller and proxy logs for a slow cycle**, with a three-way pre-specified interpretation. The multi-node experiment is **promoted** in the rankings, because §5A.2's inference is now load-bearing |
| **§13** | Six rows rewritten or added: where the time goes, the pending-request precondition, what wins under mandatory multi-node, whether the stall improves at multi-node, what would make multi-node a must, **and the two separate recommendation rows — today and under the counterfactual** |

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
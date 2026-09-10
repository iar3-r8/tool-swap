# Ray Serve adoption — a decision analysis on the simplicity axis

> **What this document is.** The requester asked: *"Can you provide an analysis of the pros/cons of using ray knowing all the evidences we have now? We need a strong emphasis on simplicity and ease of maintaining the code etc."*
>
> **What it is not.** It is not the decision. [`spike-E-results.md`](spike-E-results.md) §8 records that the frozen protocol routes this choice to the requester under Rule 3 — *"Option (c) must not be chosen by default"* — and Rule 4 escalates to the same place. This document prices the three options honestly enough that the requester can choose, and says plainly where the evidence runs out. §11 recommends; §11 also states its conditions and what would change it.
>
> **Method.** Scored on [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md)'s own three axes — **class** (forced / chosen / elective), **demand** (quotable / inferred / none), **carrying cost** (what it costs *forever*). Consistency with the project's established method matters more than inventing a new one. Every third-party claim carries a file:line or a document citation. Every factual claim is labelled **measured**, **inferred** or **assumed** — that distinction is the spike's entire value, and §0 defines it.
>
> **Bias discipline.** [`bias-audit-and-decision-procedure.md`](bias-audit-and-decision-procedure.md) §2 records seven consecutive retreats in which the anti-Ray conclusion never moved while its reasons rotated. That is a documented process defect, and this document is written by the same pipeline. Two guards are applied: §7 argues Ray's case at full strength before §8 argues against it, and §10 lists everything in the existing position that the spike **falsifies** — including two items where the desk evaluation was simply wrong.

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

**5. Things we would never write.** Multi-node scaling, a dashboard, per-replica status, Prometheus metrics, an object store with a 100 KiB threshold for large tensors, and a scheduler. [`15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md) §5 concedes `serve status` and the dashboard are *"a better status surface than we will build in v1"*, in the project's own words.

**6. Bus factor, and it is the row that never affects any conclusion.** [`case-for-ray-native.md`](case-for-ray-native.md) §5 makes this point and it survives the spike untouched: the plan's own comparison table scores its own bus factor **"Worst"**. For a small research team, the system that survives is the one that still runs after its author moves on. **Nothing in the spike bears on this at all** — which means it is exactly as strong an argument now as it was before, and it should not be quietly discounted because the spike produced other numbers.

**7. Two people, reasoning independently, recommended reuse.** The requester (*"prioritise making the tool robust and easy to maintain"*) and the engineer (*"prioritize the use of existing frameworks"*). And **D12** is the project's own principle: *prefer existing self-hostable software*. [`14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md) §1 admits the tension and it has never been resolved, only argued around.

**8. The nine-for-nine record.** [`case-for-ray-native.md`](case-for-ray-native.md) §4 lists nine objections to Ray that were each stated confidently and each fell. **The spike adds a tenth data point and it cuts the same way**: the two decisive "Ray fails the gate" verdicts were **our own measurement errors**, retracted on the record (§4 of the results doc). *Every* decisive negative this project has produced about Ray has so far been withdrawn.

---

## 5. The cons, priced with measurements

### 5.1 P90 swap latency 103 s — the biggest number, and the least attributable

**Measured** **[M]** (§3.5, ledger §9Q): 20 alternations, min 5.85 s, **median 9.48 s**, **P90 103.2 s**, max 103.6 s. Bimodal with nothing in between — ~12 cycles at 6–10 s, ~8 at 99–104 s. A **12× spread**, and the slow path is **40 % of requests**. A mean (~45 s) would describe no actual request.

**The hypothesis for the split** **[I]**, and the results document labels it a hypothesis: the ~100 s cluster matches step 3's measured ~80 s scale-to-zero plus a ~12 s cold start. Step 5 recorded end-to-end latency only, not replica transitions, so it is not proven.

**Critically: we cannot attribute this between Ray's orchestration and 14–19 GB container startup, because no baseline exists.** The results document corrects the manager's own framing on this point (§3.7, ledger §9R): step 7 was described as a "plain podman baseline" and **is not one** — *"no such baseline exists in this spike"*.

**So price it both ways, honestly:**

| If the 103 s is mostly… | Consequence for the decision |
|---|---|
| **Ray's autoscaler timing** (`look_back_period_s` decay + `downscale_to_zero_delay_s`, [`autoscaling_policy.py:124-130`](/usr/local/lib/python3.11/site-packages/ray/serve/autoscaling_policy.py:124)) | A genuine Ray-specific con — though partly tunable: `downscale_to_zero_delay_s` is a config value; **the metric-decay component is not** **[S]**/**[M]**. And step 5 ran under `external_scaler_enabled`, where that timer *does not exist*, so the residual is harder to blame on the timer than it first appears — which is itself a reason the attribution question is live |
| **14–19 GB container startup** | **Our own router inherits most of it too**, because we start the same images with the same weights on the same storage driver. That materially weakens this con, and it must be said plainly rather than buried |

**Therefore: the 103 s P90 is currently the largest *unattributed* cost in the analysis, not the largest Ray-specific one.** §12 makes resolving it the cheapest decisive experiment.

**One thing the number does establish either way** **[M]**: a swap on this stack, with these images, sometimes takes 100 seconds. Whoever owns the design owns that fact. It bears directly on `queue_timeout` (**D22**), on `min_residency` and thrash detection (which [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §4.4 already says must not be trimmed), and on whether "wait for TTL" was ever really worse than "displace".

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

## 6. Both options, scored on the complexity audit's own axes

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
| **Deleted:** M2, M3 proxy internals, M3.5, M6 watchdog, M7 collector | — | — | ***Negative — the real win.*** ~25–35 % of v1 **[A]** |
| **Gained free:** dashboard, per-replica status, metrics, multi-node, object store, replica self-healing **[M]** | — | — | ***Negative.*** Genuine, and better than what v1 would build |

**Audit verdict on (a):** **chosen**, answering a **quotable** demand, at **high** carrying cost — with a large negative-cost offset. It is *not* the pattern the audit hunts (that pattern is elective + inferred + high, which is what soft unload was). **The decision is legitimate on the audit's own terms**; it turns on whether the negative offset exceeds the high permanent cost. §11 is where I take a position.

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
| Everything Ray would give free | — | — | **Positive cost.** We build a smaller `/status` and no dashboard, and get no multi-node path |

**Audit verdict on (c):** almost every component is **forced** by a **quotable** demand at **medium** carrying cost. That is the profile [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §2 finding 2 asserted — *"that is proportionate"* — and the spike does **not** falsify it (§10.1). What the spike *does* falsify is the second half of that sentence, *"the alternatives cost more (§6)"*, which was stated on desk evaluation and is now a measured question with a genuinely mixed answer.

### 6.3 The two profiles side by side

|  | (a) Ray | (c) Our router |
|---|---|---|
| Code we own | **Less** — by ~25–35 % **[A]** | More |
| **Testability of the code we own** | **Worse.** Correctness depends on cluster-level conditions the spike needed 7 host runs and ~43 fixes to observe **[I]** | **Better.** M2/M3/M6 are fakes plus one real round trip; the scheduler is pure |
| Dependencies carried | Ray (private-surface + deprecated key), podman, version lockstep **[M]**/**[S]** | Docker, FastAPI, BentoML — all per-image and gradual |
| Failure modes handled | Ray's, including three that report success **[M]** | Ours, including ones we have not met yet **[A]** |
| Hours spent | Operating a cluster; re-verifying private behaviour per upgrade | Writing and maintaining ~4,000 lines **[A]** |
| Bus factor | **Much better** | *"Worst"*, by the plan's own score |
| Recovery | Replica: automatic **[M]**. Cluster: operator runbook **[M]** | Both **[A]**, unwritten |

**This table is the analysis.** Everything else is its derivation. Note that (a) wins three rows, (c) wins three rows, and the two decisive ones — testability and bus factor — point in **opposite** directions and are both about the next three years rather than the next month.

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

**The spike makes this question sharper, not moot.** **D25** (*"we don't want to wait for TTL as it could take quite some time"*) is the gate that eliminates every off-the-shelf candidate. But the spike measured what displacement actually costs on this stack: **P90 103 s** **[M]**. If displacement costs 100 seconds 40 % of the time, the practical gap between "displace" and "wait, with `ttl` tuned to 60 s" is much narrower than **D25** assumes — and `ttl` is a config value, not code.

**[I], and I flag it as inference from a measurement whose attribution is unknown.** If the answer is *"waiting is tolerable"*, then per [`ray-native-reconsideration.md`](ray-native-reconsideration.md) §5 our scheduler shrinks to a TTL timer, KServe re-enters, Ray path 1 re-enters, and the reuse argument wins outright. **[ADR-0004](../plan/adr/0004-hard-stop-only-in-v1.md) was produced by re-asking exactly this kind of question and is the largest win in this plan's history.** It costs one sentence from the requester.

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
| **The latency attribution baseline** — how much of P90 103 s is orchestration vs 14–19 GB container startup | **No baseline exists.** Step 7 was mis-described as one and is not (ledger §9R) | **The most decision-relevant unknown.** If it is container startup, our router inherits it and §5.1 largely dissolves. §12 |
| **D18 payload-by-reference** (`s3://`) | **Not tested** — scope-reduced (§10.1). No fetch cost is known; step 4's 0.097 s figures are **local disk reads inside a container** | Any thrash pricing that assumes remote payloads is unpriced. Bears on **D18** under either option |
| **Step 5 mechanism B** (declarative config re-apply) | **Not implemented** — a printed stub | Only the external-scaler path is measured. The alternative displacement mechanism is unmeasured |
| **Pre-emptibility of Ray's own autoscaler** | **Not tested.** Step 5 ran under `external_scaler_enabled`, which *forbids* Serve's own autoscaling for those apps | Ray can be **driven** to preempt; whether its own timer yields to a higher-priority request is unknown. This is the exact **D25** semantic |
| **The Docker / CDI path** | **Untested and unreachable** — Ray hardcodes `container_driver = "podman"` at [`image_uri.py:76`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:76) **[S]** | *"The single biggest caveat on D36."* If `image_uri` works under Docker, §3.2 weakens substantially and the deprecated-API dependency may disappear |
| **Newer Ray versions** | Everything is Ray 2.57.0; **none of D22/D32/D36 is version-checked** | A later release could fix any of them. Equally, a later release is where private-surface behaviour changes |
| **Multi-GPU and multi-tool scale beyond two** | Not tested. The gate ran on **one** of eight A100s, with **two** tools | Nothing is known about a full zoo (~20 images) on 8 GPUs — which is the actual deployment |
| **Where app builders execute** | **Refused as a claim**, not found — needs a negative control (§3.2) | Bears on whether a generic config generator is really generic |
| **`vfs` vs `overlay` cold start** | **Not A/B'd** (would mutate a shared host) | Every latency figure implicitly depends on `overlay`; a `vfs` host would likely be far worse **[A]** |
| **Origin of the 0755 event dirs (D22)** | **Unconfirmed** — most likely Ray's C++ side | The empirical finding stands; the mechanism does not |

**Three things this document itself cannot tell you**, stated because they are the boundaries of the analysis:

1. **Both code estimates are [A].** ~25–35 % deletion and ~4,000 lines are both guesses over unwritten code. `src/` is currently ~9,700 lines across 33 Python files — **M1 config and CLI, largely** — which is already more than double the audit's whole-v1 estimate for the router core. That is worth noticing: **the audit's ~4,000-line estimate is already looking optimistic**, and if v1 is materially larger than 4,000 lines then the absolute size of Ray's deletion grows too. **[I]**
2. **No hours were measured, on either side.** Every "maintenance burden" claim is a structural argument, not a timing.
3. **Nothing was measured about ~20 tools.** Every measurement is two tools on one GPU.

---

## 10. What the spike falsifies in the existing position

### 10.1 [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md) §2 finding 2

> *"The router itself is not the problem. After the descope, the core is a config loader, a container backend, a pure scheduler of a few hundred lines, a proxy and a watchdog. That is proportionate, and **the alternatives cost more (§6)**."*

**First clause: not falsified.** §6.2 scores every component as forced-by-quotable-demand at medium cost. The spike gives no reason to think the router core is disproportionate.

**Second clause — *"the alternatives cost more"* — is now a measured question with a mixed answer, and it must be downgraded.** It was asserted from desk evaluation (§6 of the audit cites [ADR-0001](../plan/adr/0001-build-our-own-router.md) and [`15`](../plan/15_RAY_SERVE_EVALUATION.md), both pre-spike). Measurement shows:

- Ray **does** delete five milestones' worth of scope **[A]**, and it **does** deliver step 3, replica self-healing and 20/20 reliability **[M]**;
- Ray **also** costs a deprecated-API dependency, four private-source behaviours, three silent failure modes and an operator runbook **[M]**/**[S]**.

**"The alternatives cost more" is not established by the evidence. It is defensible as a judgement, and it should be labelled as one.** The audit's own §6 sentence — *"every one of them requires operating a cluster and still writing the scheduler"* — survives intact and is the strongest true version of the claim.

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

### 11.1 The recommendation in one paragraph

On the axis the requester named — simplicity and long-term maintainability — the decisive consideration is **not the volume of code but the verifiability of it**. Option (c) keeps ~25–35 % more code **[A]**, and every piece of that code is a container backend, a proxy, a watchdog and a log collector that are testable with fakes and an injected clock, on a laptop, in milliseconds ([`09_IMPLEMENTATION_PLAN.md`](../plan/09_IMPLEMENTATION_PLAN.md) M2, and the audit's never-trim item 2, scheduler purity). Option (a) writes *less* code but makes its correctness depend on four private-source behaviours with no compatibility promise **[S]**, a deprecated `runtime_env` key that is mutually exclusive with most of the API and requires a host-specific absolute path in every GPU tool's config **[M]**, and three failure modes that report success **[M]** — on a system meant to run unattended. The spike is itself the measurement of how expensive those conditions are to verify: seven host runs and ~43 defect fixes to observe them **once**, on **two** tools and **one** GPU. **Against that, the two strongest pro-Ray arguments are not answered by this recommendation and I will not pretend they are: the bus factor (the plan scores itself "Worst", and no spike changed that) and the fact that Ray's recovery is measured while ours is unwritten. Those are real, and they are why the conditions below are not decoration.**

### 11.2 Condition 1 — resolve the latency attribution before any sizing work (blocking on nothing, but decision-relevant)

Run the baseline in §12. If **most of the 103 s P90 is Ray's orchestration**, this recommendation strengthens and the matter is closed. If **most of it is 14–19 GB container startup**, then our own router inherits the same cost, **D25**'s premise weakens (§7.6), and the whole framework question deserves re-opening on better terms — because a router that cannot swap faster than 100 seconds is not obviously better than one that waits for a TTL.

### 11.3 Condition 2 — answer the wait-versus-displace question (one sentence from the requester)

Per §7.6. If waiting is tolerable, our scheduler shrinks to a TTL timer, the gate that eliminates every off-the-shelf candidate disappears, and **the reuse argument likely wins outright**. This is higher-leverage than any framework measurement and it costs nothing. **It should be asked before condition 1 is run**, because a "waiting is fine" answer makes condition 1 much less interesting.

### 11.4 Condition 3 — the commitments that make this reversible rather than sunk

Recommending (c) is only honest if it comes with the triggers that would reverse it, per the ADR convention this project uses well:

| Trigger | Then |
|---|---|
| **The latency baseline shows container startup dominates** | Re-open the framework question, and re-ask **D25** first (§11.2) |
| **`image_uri` gains user-supplied `run_options`, or the Docker/CDI path works** | The deprecated-API dependency and the host-specific path both disappear. §3.2 loses most of its force, and Ray becomes materially more attractive |
| **A second GPU host is added** | [ADR-0001](../plan/adr/0001-build-our-own-router.md)'s trigger fires anyway, and Ray is genuinely multi-node without a cluster to adopt |
| **M2 boot reconciliation proves hard, or router recovery bites in practice** | This is the **[A]** claim on our side of the ledger (§7.2). If it fails, Ray's measured replica self-healing becomes the stronger position and the comparison flips on its weakest row |
| **The zoo becomes homogeneous, or splits into image-sharing families** | **D2** stops being load-bearing and most of this repository should be deleted, per [`15`](../plan/15_RAY_SERVE_EVALUATION.md) §11 |

**And one commitment that is not a trigger but a discipline**, because §10.2 is a finding about us rather than about Ray: **if (c) is chosen, the Ray question is closed for this v1 and the analysis stops.** Seven re-defences and four analysis documents is itself the largest carrying cost the refusal has, and continuing to pay it is the opposite of simplicity.

### 11.5 What I would *not* claim

- **Not** that Ray cannot do this. It demonstrably can (§4 item 1).
- **Not** that Ray is worse software. For a homogeneous zoo it is better than what we are building, as [ADR-0003](../plan/adr/0003-ray-serve-not-adopted.md) already concedes.
- **Not** that the cost comparison is lopsided. §6.3 splits 3–3, and the two rows that decide it point in opposite directions.
- **Not** that this recommendation is well-evidenced on our own recovery story. It is **[A]**, and it is the weakest link.

---

## 12. The cheapest experiment that would most change the answer

**The latency attribution baseline.** I agree with the brief that this is the one number that could move the answer materially, and here is the argument rather than the assertion.

### 12.1 What to run

On the same host, with the same fixture images, with the cluster **not running**:

```
time podman run --rm --runtime /usr/bin/nvidia-container-runtime \
  -e NVIDIA_VISIBLE_DEVICES=0 -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
  tool_torch:spike   # then the same for tool_tf:spike
```
— to first successful HTTP response from the tool's own server, ~10 repetitions each, alternating, with `nvidia-smi` sampled to confirm VRAM actually moved. Then the same alternation **without** Ray, driven by a five-line shell loop that stops one container and starts the other.

**That produces the missing number: what an alternation costs with no orchestrator at all.**

### 12.2 Why it is the cheapest

- **No new code.** The command is already in the ledger (§9L), on the working path, against our own fixture images.
- **No new dependency, no cluster, no protocol amendment.** It does not touch anything under `spike-e-ray-native/`.
- **It is the one measurement the spike was described as having and does not have** — the results document corrects that framing itself (§3.7).
- **It needs no GPU beyond the one already used**, and it mutates nothing on the shared host.

### 12.3 Why it has the most leverage

The 103 s P90 is the largest single cost in the analysis and it is currently **unattributed**. The two possible answers point in opposite directions:

| Outcome | Effect on the decision |
|---|---|
| Plain-podman alternation is **fast** (say < 20 s) | The ~100 s is Ray's orchestration. §5.1 becomes a hard Ray-specific con, **D25** is vindicated, and the recommendation for (c) is settled |
| Plain-podman alternation is **also ~100 s** | Container startup dominates. **Our router inherits it**, §5.1 largely dissolves as a differentiator, and the *interesting* question becomes §7.6 — whether displacement was ever worth its premise. This would be the most consequential result available from any cheap experiment |

**Two candidates I considered and rank lower, with reasons:**

- **The Docker/CDI path for `image_uri`** — arguably higher *upside* (it could delete the entire deprecated-API dependency, §3.2's biggest caveat), but it is **not cheap and may be impossible**: Ray hardcodes podman at [`image_uri.py:76`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:76) **[S]**, so testing it means patching Ray or waiting for upstream. **If it were cheap, I would rank it first.**
- **Multi-tool, multi-GPU scale** — the most *representative* gap (every measurement is two tools on one GPU, §9), but it is a week of work and it only refines a decision rather than flipping it.

**And the one thing cheaper than any experiment:** §11.3. One sentence from the requester about whether waiting is tolerable decides more than any measurement in this document.

---

## 13. Summary table

| Question | Answer |
|---|---|
| Can Ray do the job? | **Yes** **[M]** — step 3 passed, one GPU, two conflicting tools, both directions |
| Is it simpler in code volume? | **Yes** — five milestones leave scope, ~25–35 % **[A]** |
| Is it simpler in code we can *verify*? | **No** **[I]** — correctness moves to cluster-level conditions that took 7 host runs and ~43 fixes to observe once |
| Is it simpler in dependencies? | **No** **[S]** — a deprecated key, four private-source behaviours, version lockstep, rootless podman |
| Is it simpler in failure modes? | **No** for unattended operation **[M]** — three modes report success; one is an unmessaged C++ abort |
| Is it better on bus factor? | **Yes, clearly**, and no spike touched this. The plan scores itself *"Worst"* |
| Is it better on recovery? | **Replica: yes, measured. Cluster: an operator runbook — but ours is unwritten [A]** |
| What is the biggest cost? | **P90 103 s** **[M]** — and it is **unattributed** between Ray and container startup |
| What is the biggest unknown? | The same number. §12 |
| What does the analysis recommend? | **(c), with three conditions and five reversal triggers** — §11 |
| Who decides? | **The requester.** Protocol Rule 3, and *"option (c) must not be chosen by default"* |

---

## 14. Provenance

**Read for this analysis:** [`spike-E-results.md`](spike-E-results.md) (all sections), [`spike-E-continuation.md`](spike-E-continuation.md) §§9j–9S, [`16_COMPLEXITY_AUDIT.md`](../plan/16_COMPLEXITY_AUDIT.md), [`14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md), [`15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md), [`17_LLAMA_SWAP_PHILOSOPHY.md`](../plan/17_LLAMA_SWAP_PHILOSOPHY.md), [`09_IMPLEMENTATION_PLAN.md`](../plan/09_IMPLEMENTATION_PLAN.md), [ADR-0001](../plan/adr/0001-build-our-own-router.md), [ADR-0003](../plan/adr/0003-ray-serve-not-adopted.md), [ADR-0005](../plan/adr/0005-one-uniform-batched-calling-convention.md), [`case-for-ray-native.md`](case-for-ray-native.md), [`ray-native-reconsideration.md`](ray-native-reconsideration.md), [`ray-serve-mounts-and-deletion-scope.md`](ray-serve-mounts-and-deletion-scope.md), [`bias-audit-and-decision-procedure.md`](bias-audit-and-decision-procedure.md).

**Ray source verified during this task** (not quoted from the ledger alone): [`resource_and_label_spec.py:454-471`](/usr/local/lib/python3.11/site-packages/ray/_private/resource_and_label_spec.py:454) — the explicit-`0`-is-not-autodetect behaviour, confirmed at `if num_accelerators is None:`. The other three private-source citations are quoted from the ledger with their file:line intact and were not independently re-opened here; a reviewer wanting to check them has the exact lines.

**Not modified**, per the constraints: the ADRs, [`spike-E-continuation.md`](spike-E-continuation.md), [`spike-E-results.md`](spike-E-results.md), [`spike-E-ray-native-protocol.md`](spike-E-ray-native-protocol.md), and anything under `spike-e-ray-native/`. Nothing committed, nothing pushed.
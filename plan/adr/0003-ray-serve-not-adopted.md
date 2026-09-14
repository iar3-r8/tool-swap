# ADR-0003 — Ray Serve is not the router for tool-swap's v1 single-host model-switching workload

- **Status:** **Accepted — re-based a third time (2026-09-14), now on measured evidence and with a deliberately narrowed scope.** The conclusion stands; **the claim is smaller than in any previous version.** The basis has moved capability (v1) → operational cost (v2) → **one measured latency on our core path, for one workload shape (v3, current)**. **Spike D is retired** ([`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md) §8); **Spike E was specified, run on a GPU host, and is the reason this ADR is re-based** ([`spike-E-continuation.md`](../../plans/spike-E-continuation.md)).
- **Date:** 2026-08-12 (amended 2026-08-12; re-based 2026-08-13; **re-based onto measurement 2026-09-14**)
- **Scope — read this before quoting the decision:** the decision applies to **tool-swap v1: one host, ~20 mutually-exclusive tools, swapped on request arrival — model-switching, not scaling.** It is **not** a general verdict on Ray Serve, and the unqualified title this ADR carried until 2026-09-14 over-claimed. Where Ray *is* the right tool is recorded in [`ray-adoption-analysis.md`](../../plans/ray-adoption-analysis.md) §0′ and summarised below.
- **Adds:** **D29** to [`13_OPEN_QUESTIONS.md`](../13_OPEN_QUESTIONS.md) Part A
- **Evidence classes**, used on every load-bearing claim below and defined once in [`ray-adoption-analysis.md`](../../plans/ray-adoption-analysis.md) §0: **[M]** measured in Spike E, with a ledger reference · **[S]** read in Ray's source or in captured vendor documentation · **[I]** inferred from **[M]**/**[S]** by a stated argument · **[A]** assumed — not established here.
- **Full analysis:** [`ray-adoption-analysis.md`](../../plans/ray-adoption-analysis.md) **(revision 3 — the current analysis of record)**, which supersedes [`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md) v3 as the place to read the argument in full. Measurements live in [`spike-E-continuation.md`](../../plans/spike-E-continuation.md) and [`spike-E-results.md`](../../plans/spike-E-results.md).
- **Depends on:** [ADR-0004](0004-hard-stop-only-in-v1.md), which removed soft unload from v1 and thereby removed the one open question that could have reversed this decision
- **Corrects:** [`14_ALTERNATIVES_EVALUATION.md`](../14_ALTERNATIVES_EVALUATION.md) §3.3, which dismissed Ray Serve in one paragraph, and §2.2, which implied no existing tool offers bounded LRU model eviction
- **Does not reopen:** [ADR-0001](0001-build-our-own-router.md). Ray Serve was not one of the three spikes, so this is a new question rather than a re-run of a closed one.

---

## Re-basing (2026-09-14) — the spike ran, this ADR's own falsifier fired, and the decision is re-scoped

> **Read this section first. It supersedes the grounds in both sections below; those are retained because the error trail is the point** ([`README.md`](README.md): *"preserve superseded reasoning rather than deleting it"*).

### 1. The falsifier fired. Stating it plainly, as the ADR required of itself

This ADR named one falsifier and undertook to be rewritten rather than patched if it came back the other way:

> *"if `runtime_env` provides a production-viable **per-deployment OCI image** boundary that composes with per-device GPU pinning, then Ray Serve delivers **D2** *and* **D9** *and* **D25** together, the fork above dissolves, and this decision is wrong."*

**Spike E ran it, and every capability clause came back against this ADR:**

| Falsifier clause | Spike result |
|---|---|
| Per-deployment OCI image boundary | **Confirmed** **[M]** — two GPU deployments, one cluster, correct isolation, proven by a baked-in marker unreachable through `runtime_env` (§9h) |
| Per-tool container images | **Confirmed** **[M]** — per-tool images via the `container` runtime_env key (§9i) |
| Composes with per-device GPU pinning | **Confirmed** **[M]** — **real GPU displacement**, VRAM verified released and reclaimed by `nvidia-smi`, torch 4519 MiB ↔ tf 38909 MiB (§9N) |
| Delivers **D25** (preempt an idle incumbent) | **The fork's Path-1 row is refuted as stated** **[M]** — **20/20 alternations, zero errors** (§9Q). Driven externally, Ray displaces; it does not merely queue |
| Usable for real work | **Confirmed** **[M]** — payload and weights read from inside the container (§9O); automatic **unattended** replica recovery, new pid, ~15 s (§9P) |

**So the sentence this ADR was obliged to write:** ***the central structural argument of every previous version of this document is wrong.*** The fork that the Evidence section calls *"the whole argument"* — *"Path 1: allocation, not preemption — a replica waits for a held GPU, exactly as a Kubernetes pod goes `Pending`"* — **is refuted as stated for the externally-driven case** **[M]**. What survives from the falsifier is one word: ***production-viable***. That word is now the whole decision, and it is answered below by measurement rather than by argument.

**None of the above is presented as a capability gap anywhere in this ADR from here on.** A mechanism we used successfully is a working mechanism. What can still be said about it is narrower and is said in §4.

### 2. The deciding ground — one measured failure, and it is on our core path

**Under eager probing — a request arriving *during* the swap, which is tool-swap's actual trigger — 8 of 20 cycles took ~100 s** **[M]** (§9Z, **D54**). The phase table locates it:

| phase | fast (12) | slow (8) |
|---|---|---|
| scale-down RPC | 8 ms | 8 ms |
| scale-up RPC | 5 ms | 4 ms |
| decision lag | 7 ms | 7 ms |
| replica materialise | 0.87 s | 0.87 s |
| **container first seen** | **~3.0 s** | **~93.6 s** |

**Every phase before the replica exists is identical between the two groups, to the millisecond.** The difference is entirely **dead time inside Ray *before* it issues `podman run`** **[M]**, verified against Ray's own `runtime_env_setup` log to within 80 ms.

Two properties make this decisive rather than merely unwelcome:

- **A pending request is a precondition** **[M]**. 50 cycles that polled to RUNNING before probing never stalled; 8/20 that probed immediately did. **tool-swap is request-triggered by construction**, so the penalty lands on our hot path *and only there*.
- **The comparison is not against an ideal.** Plain podman does the same work in **3.9–6.9 s with no bimodality** **[M]** (§9T). That is **~15×** on the one path the product exists to serve.

**The mechanism is deliberately unnamed** — five prior attributions were wrong, and naming a sixth from plausibility would repeat exactly the error this document keeps making. What is claimed is only what was measured: the dead time is inside Ray, it precedes the container launch, it is ~90–95 s with little spread, and it requires a pending request.

> **The single deciding ground, stated once:** ***an unexplained ~93 s pre-container stall on ~40 % of request-triggered swaps is a cost that cannot be budgeted, on the only path that matters to this product.*** **[M]** Everything else in this ADR is supporting, and none of it would carry the decision alone.

**And the honest converse:** *"production-viable"* is refused on **this** ground, not on the capability grounds the previous versions used. If the mechanism is identified and proves configurable, the ground goes with it — which is why the revisit triggers below are rewritten around exactly that.

### 3. The scope correction — what this ADR does and does not claim about Ray

The requester asked: *"In what actual case would Ray be useful… why would anyone use ray, based on what you are mentioning ray should never be used."* **He was right that the framing over-claimed, and the correction belongs here and not only in the analysis.**

**Ray is the right tool for a large space of work** ([`ray-adoption-analysis.md`](../../plans/ray-adoption-analysis.md) §0′.2): distributed training and tuning; serving a model too large for one host; heterogeneous pipelines with object-store hand-off; **load-driven autoscaling of a stable model set**; batch inference over large datasets; and any team already on Ray, for whom serving on it removes a platform boundary. **We evaluated none of those and have no criticism of them.**

**Why it fits *us* badly is specific.** Our workload is ~20 tools, one replica each, mutually exclusive on the GPU, swapped on request arrival. **That is model-switching, not scaling.** The mismatch is in Ray's own words ([`architecture.md:26`](../third-party-docs/ray-serve/architecture.md:26) and the tool-swap note at [`:77`](../third-party-docs/ray-serve/architecture.md:77)) **[S]**: a request is queued until **a replica of its own deployment** becomes available — **there is no path by which a queued request for tool B causes tool A to release a GPU.**

The consequence **[I]**: we must drive scaling externally, which means **reimplementing the eviction policy on top of the framework adopted for its policy** — and the ~93 s stall is then the price of using the *replica-placement* path as a *swap* mechanism, which is not what it is for.

> **Therefore the claim of this ADR is: Ray Serve is not the router for tool-swap's v1 single-host model-switching workload.** Not *"Ray Serve is not for us"*, and certainly not *"Ray should not be used"*. Any quotation of this ADR that drops the qualifier is misquoting it.

### 4. What this re-basing supersedes in the grounds below

| Ground as previously stated | Status after the spike |
|---|---|
| **`image_uri` / `container` is *"experimental and the API is subject to change"***, and the previous `container` field is deprecated | **Demoted, and re-shaped.** **The spike used the mechanism successfully** **[M]** (§9i, §9N) — it is not a capability gap and must not be presented as one. What survives is narrower and still true: **the path that works is the deprecated `container` key, not the modern `image_uri`**, because [`ImageURIPlugin.modify_context`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:174) hardcodes `run_options=[]`, so `--runtime`, `--device` and `--gpus` are structurally unreachable through it **[S]** (**D36**). The legacy key is mutually exclusive with `pip`, `working_dir` and most of `runtime_env` **[S]**, and needs a host-specific absolute path in every GPU tool's config **[M]**. **A stability and portability cost, not an impossibility.** |
| **Version lockstep** — *"must match… down to the patch number"*, presented in v2 as *"the evidenced form of the 'Ray is heavy' claim"* | **Retagged and demoted, and this is a correction of the record.** The *coupling* is **[M]**: the fixtures had to be built from the exact base tag `docker.io/rayproject/ray:2.57.0-py311-gpu` ([`spike-E-results.md`](../../plans/spike-E-results.md) §1 item 9, §3.0). **The *maintenance cost* was never experienced: no upgrade was performed, so the "coordinated rebuild of every tool image" remains [A].** Its weight was already conceded before the spike ([`ray-native-reconsideration.md`](../../plans/ray-native-reconsideration.md) §1: *"a cost, not a gate"*). **It is a cost row. It is not a ground for refusal, and v2 was wrong to lean on it.** |
| **Recovery** — *"If you aren't using KubeRay, when the Ray cluster fails, Ray Serve cannot recover"* ([`architecture.md:42`](../third-party-docs/ray-serve/architecture.md:42)) | **Stands, refined by measurement, and now *more* relevant.** The doc sentence conflated two properties **[S]**/**[M]**: **replica** recovery is fully automatic and unattended (§9P) **[M]**, while **cluster/head-node** recovery is a three-command operator runbook plus a config re-apply, with Serve applications not returning by themselves and 109 orphaned containers left behind (§9S) **[M]**. More relevant because robust multi-node Ray means KubeRay — see §5. **Measurement made it both more accurate and less alarming.** |
| **D9 / D25 (soft unload)** — the hinge of v1 and v2 | **Unchanged: they left the scorecard**, because [ADR-0004](0004-hard-stop-only-in-v1.md) removed soft unload from v1. Worth recording alongside: **the spike measured hard displacement working** — VRAM released and reclaimed across 20/20 alternations **[M]** — so the v1 fork's **D9**/**D25** rows are now moot *and* the capability they doubted is demonstrated. |
| **Podman on a shared DGX** as an unpriced risk | **Partly discharged.** It ran: rootless podman on the shared host, alongside Docker with 9 unaffected containers **[M]** (§9T, [`spike-E-results.md`](../../plans/spike-E-results.md) §5.3). What remains is operational (a `umask 0` trade-off and world-writable session log dirs for `image_uri` workers, **D22** **[M]**), not a blocker. |

### 5. The multi-node counterfactual, briefly — and it does not end at Ray

If multi-node ever becomes mandatory, **the answer is not Ray** ([`ray-adoption-analysis.md`](../../plans/ray-adoption-analysis.md) §5A, revision 3). Robust multi-node Ray is **KubeRay** — Kubernetes anyway **[S]** — so adopting Ray does not avoid Kubernetes; it arrives there *and* carries the measured core-path penalty *and* the deprecated GPU path on every host **[I]**. The project's own recorded answer at cluster scale is **Kubernetes-native serving (KServe/Seldon)**: [`00_CONTEXT_AND_MOTIVATION.md:225`](../00_CONTEXT_AND_MOTIVATION.md:225) already names it *"The 'right' answer at cluster scale… Keep as the documented growth path."*

**Stated with its weakness on its face: KServe has never been spiked** **[A]**. That ranking rests on documents and prior analysis, whereas Ray's costs here are measured. The two are not symmetrically unverified — but they are not symmetrically evidenced either, and this ADR does not claim otherwise. **This paragraph also supersedes the old revisit trigger *"a second host is added → Ray competes on better terms"*, which was wrong.**

### 6. The pattern this re-basing is obliged to name

[`bias-audit-and-decision-procedure.md`](../../plans/bias-audit-and-decision-procedure.md) §2 records **seven consecutive retreats in which the anti-Ray conclusion never moved while its reasons rotated**, and this ADR is the main artefact of that pattern — re-based twice before today. **A third re-basing that merely swapped in fresh reasons for the same conclusion would be the eighth retreat, and a reader is entitled to suspect that is what this is.**

**Three things are different, and they are the only defence offered:**

1. **The ground is measured, not argued.** Every previous version rested on documentation or on a structural claim; each lost ground when checked. This one rests on a number from our own GPU host, with a ledger reference and raw output.
2. **The claim is smaller.** The title, the status line and §3 all narrow it to one workload shape on one host — the first version of this document that concedes where Ray wins.
3. **The trigger can actually fire, and would be cheap to fire.** §"Revisit when" below turns on identifying a mechanism, which is one log read away (§12 of the analysis). A decision defended by an unfalsifiable trigger is the failure mode this pattern produces; this one is falsifiable within a day.

**What would not be a defence, and is not claimed:** that the conclusion surviving seven challenges is evidence for it. It is not. It is evidence about the process, and it should be weighted as such.

---

## Re-basing (2026-08-13) — the decision is settled, and it rests on maintainability

> **SUPERSEDED 2026-09-14 by the re-basing above, and retained deliberately.** Two of its three named grounds have moved: **`image_uri`/`container` experimental status** is demoted (the spike used the mechanism successfully **[M]**), and **version lockstep** is retagged from an evidenced ground of refusal to a cost whose maintenance half is **[A]**. **The recovery ground survives and is strengthened.** This section's *reasoning* was sound on what was then known; **its premise — that no measurement was available — expired when Spike E ran.** Read it for the error trail, do not quote it as current grounds.

**Two things changed after the amendment below was written, and together they close the question.**

**1. The requirement was restated on a different axis.**

> *"We need to know if we are reimplementing a complex stack just for the fun of it… It is important that we prioritise making the tool robust and easy to maintain."*

Every version of this ADR argued **capability**, and lost ground each time. On **maintainability** the answer is not close, and it is the axis the requester named. Adopting Ray means depending simultaneously on:

| Dependency | Ray's own stability language |
|---|---|
| `image_uri` (delivers **D2**) | *"experimental and the API is subject to change"*, and the previous `container` field is already deprecated |
| Custom / application-level autoscaling policies (our scheduler) | *"experimental and may change in future releases"* |
| External scaling API | *"in alpha and may change before becoming stable"* |
| Config updates at request cadence | documented as a deployment-time mechanism; graph updates *"NOT recommended in production"* |
| Per-**deployment** `image_uri` | **the documentation contradicts itself** and does not resolve it |

Plus two facts that are not about features at all:

- **Version lockstep.** *"The Ray version and Python version in the container must match those of the host environment exactly… down to the patch number."* A Ray upgrade becomes a coordinated rebuild of **every** tool image, where **D14**'s BentoML pin is upgraded one image at a time. That is the evidenced form of the "Ray is heavy" claim earlier drafts asserted without support.
- **Recovery.** *"If you aren't using KubeRay, when the Ray cluster fails, Ray Serve cannot recover."* We are not on Kubernetes, and guardrail 8 requires that restarting be cheap and safe. Our router is a stateless process that re-adopts running containers on boot.

**2. [ADR-0004](0004-hard-stop-only-in-v1.md) removed soft unload from v1**, which dissolves this ADR's only remaining hinge. The single question that could have reversed the decision — *can `reconfigure()` genuinely release VRAM from a live replica?* — tests a capability **we no longer need**, because we no longer build `IDLE_SOFT`. **D9** and **D26** leave the scorecard entirely.

**Consequences for how this ADR should be read and quoted:**

- **It is a decision, not a deferral.** The previous status line said the opposite; that line was correct when written and is now withdrawn.
- **Spike D is retired rather than rescoped** ([`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md) §8). Its decisive step tested the capability ADR-0004 removed, and it could not be run without first installing Podman on the shared DGX — part of the very cost it was meant to evaluate.
- **The capability concessions below stand and are not re-argued.** Ray can containerise each tool, deploy tools independently, and host a scheduler policy. None of that is in dispute; none of it is the basis of the decision.

**Revisit triggers** are in [`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md) §11. The strongest single one: **`image_uri` leaving experimental status *and* the Ray/Python lockstep being relaxed** — both, not either.

> **That trigger is WITHDRAWN as of 2026-09-14, and it was mis-specified when written.** Half of it is now partly obsolete — we have *used* the mechanism on a GPU **[M]** — and the other half rests on a ground since demoted to a cost. It was also unfalsifiable in practice: it waited on someone else's release notes. **The replacement triggers are in "Revisit when" below, and they turn on a question we can answer ourselves.**

---

## Amendment (2026-08-12) — `runtime_env.image_uri` exists, and the first version of this ADR was wrong

> **SUPERSEDED 2026-09-14, and retained because it is the first half of the error trail.** This section conceded the falsifier *on documentation*; the 2026-09-14 re-basing above concedes it *on measurement*, which is stronger and settles several rows this section left open. Two specific corrections to it: the **D25** row's *"cost argument"* is now **priced** rather than pending (**[M]**, ~93 s on ~40 % of request-triggered swaps), and its **version-lockstep** row is demoted per §4 above.

**What happened.** This ADR named one falsifier and said that if it came back the other way *"this document is wrong and should be rewritten rather than patched"*. It was challenged immediately with [Run Multiple Applications in Different Containers](https://docs.ray.io/en/latest/serve/advanced-guides/multi-app-container.html), and **the falsifier fired**: `runtime_env.image_uri` runs each Serve *application* in its own container image, so *"all deployment replicas in the applications start and run in containers with the respective images"*.

**Therefore the central claim below is withdrawn.** Ray Serve **can** give each tool its own image, and **D2 is satisfiable on Ray**. The assertion that Ray's isolation is *"a pip layer, not a process-and-libc boundary"* was false. [`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md) has been rewritten to v2 accordingly; read that rather than the Evidence section below, which is preserved only so the error is legible.

**What the decision now rests on** — narrower, and no longer an impossibility:

| Ground | Substance |
|---|---|
| **Displacement across applications is a redeploy, not a residency change** (**D25**) | Displacement-as-residency lives *inside* a replica (`@serve.multiplexed`); isolation lives *around* it (`image_uri`). A controller *can* free a GPU by deleting or updating an application — the [multi-application guide](https://docs.ray.io/en/latest/serve/multi-app.html) confirms this *"doesn't affect other applications"* — but that pays a full container start and CUDA init (5–18 s before a weight is read, [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../06_LIFECYCLE_TTL_AND_SCHEDULING.md) §6.1) where our soft unload pays a `POST /unload`. **This is a cost argument, not a capability one**, and Spike D step 4 measures it. |
| ~~No alive-but-unloaded state~~ **(D9) — largely conceded** | [Updating Applications In-Place](https://docs.ray.io/en/latest/serve/advanced-guides/inplace-updates.html) lists `user_config` among changes that *"modify running deployment replicas **without tearing them down and restarting them**"*, delivered to a live replica's `reconfigure()`. **That is a soft-unload channel.** It is unproven for VRAM specifically ([`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md) §9 item 8) — but "Ray has no representation for this" is no longer a defensible claim. |
| **Cadence mismatch** | `reconfigure()` and `num_replicas: 0` are configuration-update mechanisms, documented at *deployment* cadence. A scheduler drives them at *request* cadence, and the same guide warns that graph updates in production are *"NOT recommended"*. Being the first to use a mechanism this way is a genuine risk — but it is a risk, not an impossibility. |
| **Version lockstep** | *"The Ray version and Python version in the container **must** match those of the host environment exactly… down to the patch number."* A tool cannot choose its interpreter, and a cluster upgrade means rebuilding every tool image at once. **This is a strictly stronger coupling than D14 accepts for BentoML**, whose version we pin per image and upgrade gradually. |
| **Experimental, and already once-deprecated** | *"This feature is experimental and the API is subject to change"*, and the previous `container` field is deprecated in favour of `image_uri`. **D2** is the most load-bearing decision in the plan; resting it here is a real risk. |
| **Podman on a shared DGX** | Required on all head and worker nodes, `--privileged` if the raylet is itself containerised, with documented `overlayfs` and slow-startup failure modes on large images. We do not administer this node. |

**What this means for confidence.** Any one of those is survivable. Together they justify *not switching today* — but they do **not** justify closing the question, and the honest position is that **Spike D is now the recommended next step rather than an optional extra**. If displacement across applications turns out to be achievable at acceptable cost, this ADR should be superseded.

**A second correction, from the [multi-application guide](https://docs.ray.io/en/latest/serve/multi-app.html).** Applications can be added, removed and updated independently, `serve status` reports per-application and per-replica health, and Ray explicitly names our use case: *"separate groups of models that may not communicate with each other, but you want to co-host them to increase hardware utilization."* **Ray's multi-application model is a better fit than this ADR's first version implied.**

**A third correction, from the [in-place updates guide](https://docs.ray.io/en/latest/serve/advanced-guides/inplace-updates.html), and it is the largest.** `user_config` reaches a *running* replica through `reconfigure()` *"without tearing them down and restarting them"*, and `num_replicas` is likewise a lightweight update. **Two of the three capabilities this ADR said Ray lacks are plausibly reachable** — soft unload via `reconfigure()`, on-demand release via scaling to zero. Neither is proven for VRAM, and both would be driven at a cadence the docs do not contemplate, but the honest position is now **"unmeasured", not "absent"**.

**Three pages, three concessions, all in the same direction.** That pattern is itself information: the grounds have moved from *structural impossibility* to *operational risk*, and a reader deciding whether to trust this ADR should weigh it accordingly. **We write a scheduler either way** — the question is only what it drives, and at what cost.

**Process lesson, recorded because it is the useful part:** the falsifier did its job. A decision published with an explicit "here is what would prove me wrong" was corrected in hours instead of becoming folklore. Keep writing them.

---

## Context

After the M−1 gate closed, a second reuse challenge arrived:

> *"I got challenged that we were reimplementing Ray Serve — why not use this framework?"*

The challenge is well aimed, for two reasons that must be conceded before anything is decided:

1. **The existing record was thin.** Ray Serve got a single paragraph ([`14_ALTERNATIVES_EVALUATION.md`](../14_ALTERNATIVES_EVALUATION.md) §3.3) and a single table row ([`05_RUNTIME_AND_BATCHING.md`](../05_RUNTIME_AND_BATCHING.md) option C). **It was never spiked.** llama-swap, KServe and do-nothing each got a designed experiment; Ray Serve got three clauses. **(Resolved 2026-09-14: Spike E gave it the designed experiment, on a GPU host. KServe remains the candidate that has not had one** **[A]**.**)**
2. **It is a closer match than KServe was.** KServe failed because Kubernetes has no preemption and Knative cannot express "keep the pod, release the weights". **Ray Serve has an analogue of both** — `@serve.multiplexed` is a bounded LRU cache of models inside a live replica, which is very nearly our `IDLE_SOFT` plus `max_resident`. The claim in §2.2 that our central primitive has no off-the-shelf equivalent was **wrong**, and this ADR withdraws it.

## Decision

**For tool-swap's v1 workload — one host, ~20 mutually-exclusive tools, swapped on request arrival — Ray Serve is not adopted as the router (Role A) and does not replace BentoML as the in-container runtime (Role B). Ray inside a tool image (Role C) remains permitted and always was.**

The three roles are separated deliberately, because conflating them is what makes this argument circular ([`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md) §3).

| Role | Outcome | On what grounds |
|---|---|---|
| **A** — replace the router | **Refused, for this workload** | **Cost, measured.** ~93 s of pre-container dead time on ~40 % of request-triggered swaps, mechanism unknown, against 3.9–6.9 s for plain podman **[M]** — on the only path this product exists to serve. **Not** the structural fork below, which the spike refuted as stated **[M]**. |
| **B** — replace BentoML inside the image (**D14** option C) | **Refused on cost, not principle** | Ray in every image is heavier than BentoML for one model per container. Reversible via the `RuntimeBackend` seam — a `ray` backend would be an addition, not a rewrite. |
| **C** — Ray *inside* one tool's image, e.g. multi-GPU sharding | **Permitted, no decision needed** | An author uses `base_image:` and imports Ray in their own container. The router neither knows nor cares. **We are not rejecting Ray; we decline to make it the boundary between tools.** |

## Evidence

> **SUPERSEDED 2026-09-14 in its load-bearing row, and retained as the error trail.** The **D25** cell in the Path-1 column below — *"allocation, not preemption — a replica waits for a held GPU"* — is **refuted as stated** for the externally-driven case: **20/20 displacements at cadence, zero errors, VRAM released and reclaimed** **[M]** (§9N, §9Q). **The fork this ADR called *"the whole argument"* is no longer the argument.** The **D9**/**D26** rows are moot for a different reason ([ADR-0004](0004-hard-stop-only-in-v1.md)). What survives intact is the **D2** column and the Path-2 critique, which no measurement has touched. Read the rest of this section as history.

### The fork — this was the whole argument, and it no longer is

Ray Serve offers two ways to host many models, and our two hardest requirements sit on opposite sides of it.

| | **Path 1** — one deployment per tool | **Path 2** — one multiplexed deployment |
|---|---|---|
| Isolation | `runtime_env`: a pip/venv layer over the worker's interpreter. Shared Python minor version, shared Ray pins, shared CUDA userspace and system libraries | **One replica process for every model.** No isolation at all |
| **D2** one image per tool | ✗ | ✗✗ this is the R8 monolith, rebuilt on purpose |
| **D25** preempt an idle incumbent | ✗ allocation, not preemption — a replica waits for a held GPU, exactly as a Kubernetes pod goes `Pending` | ✓ LRU displacement, and cheap |
| **D9** soft unload as default | ✗ a replica holds its weights or it dies — the Knative objection from [ADR-0002](0002-shared-node-soft-unload.md) repeated | ✓ this is what multiplexing *is* |
| **D26** hard stop as the backstop | ✓ process exit still reclaims | ✗ **there is no process exit to fall back on** |

> **The mechanism that satisfies D9 and D25 is the same mechanism that violates D2; the mechanism that respects D2 satisfies neither D9 nor D25.**

tool-swap has both because the isolation boundary is a **container** while the eviction table is **ours** — a few hundred lines of pure, decidable policy over a boundary the OS enforces. Ray owns the eviction and therefore needs the shared process; we own the eviction and therefore keep the process boundary.

### Why Path 1 is a closed question rather than a new one

Path 1 fails **D2**, **D9** and **D25** for the *same reasons, at the same level of primitives*, as the Kubernetes path already rejected in [ADR-0001](0001-build-our-own-router.md): devices are allocated rather than preempted, and there is no representation for "alive but holding no weights". Adopting it would reopen a closed gate to arrive at the same destination.

### Why Path 2 is the more interesting failure

Path 2 is genuinely better than our design on scheduling — and it requires every tool to share one interpreter. The evidence against that is observed, not argued: ~300 pinned packages containing **both** `torch 2.8+cu129` and `tensorflow 2.16`, plus a URL-pinned `flash_attn` wheel built for `cu12torch2.8 / cp312` ([`00_CONTEXT_AND_MOTIVATION.md`](../00_CONTEXT_AND_MOTIVATION.md) §3). **D2** exists because a dependency resolver cannot reconcile that set, and `runtime_env` is a dependency resolver.

One consequence deserves separate mention because it would bite in production rather than at install time. **D26** concedes that some handlers (TensorFlow/Keras) cannot reliably release VRAM and classifies them *hard-stop-only*, which is safe **because the OS reclaims on process exit**. In a multiplexed replica that backstop does not exist, and the failure it guards against — believing memory was freed while silently holding it on a node shared with other tenants — is guardrail 5c.

### An argument this ADR withdraws

*"R8's own Ray attempt stalled"* is cited in three places as a reason to avoid Ray. It is weak evidence and should not be relied on: [`12_REFERENCE_CODE.md`](../12_REFERENCE_CODE.md) §8 shows the actual defect was a synchronous caller force-flushing its own batch, and the same file calls the underlying batching policy *"clean and well-tested"*. That is one developer misusing a batching pattern, not a finding about Ray Serve. **Withdrawn as evidence about Ray**; it survives only as a fact about R8's history.

## Evidence class — read this before quoting the decision

**The original statement of evidence class, preserved because it is the premise that expired:**

> *"**This ADR is weaker than ADR-0001 and should not be presented as equivalent.** ADR-0001 rested on **three executed or directly-answered spikes**. This one rests on **documented behaviour plus one structural argument**. **No spike was run**, by explicit choice: a written answer was what was asked for. Every version-sensitive claim about Ray is listed as **unverified** in [`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md) §9, per the repository rule against documenting behaviour from memory. **Spike D is specified but not run** ([`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md) §10), with a decision rule that would delete most of this plan if it passed. That outcome would be welcome ([`HANDOFF.md`](../HANDOFF.md) §2)."*

> **Withdrawn 2026-09-14 as a description of this ADR's evidence: a spike *was* run.** Spike D stayed retired; **Spike E** was specified and executed instead. **The decision rule was honoured** — the spike's capability results went against this ADR, and the ADR was rewritten rather than patched.

**As of 2026-09-14 this ADR rests on measurement**, and is no longer weaker than [ADR-0001](0001-build-our-own-router.md) on evidence class — though it is narrower in claim.

- The grounds are **Spike E**: seven host runs on a shared DGX with real GPUs, ~43 defect fixes, verbatim output and metrics recorded per step ([`spike-E-continuation.md`](../../plans/spike-E-continuation.md), [`spike-E-results.md`](../../plans/spike-E-results.md)).
- **Ray passed most of the protocol** **[M]**. The decision rests on **one** measured failure (§9Z) plus a **[S]** structural mismatch between Ray's queueing rule and our workload shape.
- **Bounds that must travel with the numbers** **[M]**: Ray 2.57.0 / Python 3.11 only — **not version-checked against any other Ray** ; **two** tools, **one** GPU, **one** host; and **no multi-node was ever exercised** — every multi-node statement in this ADR is **[I]** or **[A]**.
- The mechanism of the stall is **unknown, deliberately** — see the re-basing §2. **An unexplained cost is being treated as a reason to refuse, and a reader may reasonably regard that as the weakest joint in the argument.** It is also precisely what the first revisit trigger is for.

**The original falsifier, preserved verbatim because it fired:** *if `runtime_env` provides a production-viable **per-deployment OCI image** boundary that composes with per-device GPU pinning, then Ray Serve delivers **D2** *and* **D9** *and* **D25** together, the fork above dissolves, and this decision is wrong.* **It came back against this ADR on every clause except the words *"production-viable"*** (re-basing §1). **The decision was rewritten rather than patched, as promised — three times now, and each rewrite made the claim smaller.**

**The current falsifier, and it is one experiment:** **if the ~93 s pre-container stall is named and eliminated — a defect fixed upstream, a configuration we have not found, or absent on another Ray version — then the deciding ground of this ADR disappears and the decision must be re-run.** Ledger §9Z names where to look (the controller and proxy logs for a slow cycle, gaps G1–G2).

## Consequences

### Accepted

- **Nothing changes in the implementation plan.** No milestone is added, removed or reordered. This ADR is a defence of existing scope, not a change to it.
- **We continue to own the scheduler**, bounded by the constraints in [`14_ALTERNATIVES_EVALUATION.md`](../14_ALTERNATIVES_EVALUATION.md) §7, which remain load-bearing.
- **We accept that a third of Ray Serve is reimplemented knowingly**, and say so publicly rather than claiming novelty. The parts that are genuinely ours are narrower than the challenge implies: the authoring ladder (**D3**), the schema and contract (**D13**, **D19**), preflight (**D17**), and the container-boundary scheduler.
- **We accept that the refusal now rests on an unexplained number** **[M]**. Budgeting against a cost whose mechanism nobody has named is uncomfortable, and it is the honest description of where we are. The first revisit trigger exists to discharge it.
- **We accept that Ray's recovery is measured and ours is not** **[A]**. Ray's replica self-healing is unattended and demonstrated (§9P); our boot reconciliation is unwritten. **That is the weakest row on our side of the comparison**, and it is a trigger below rather than a footnote.

### What this decision does *not* claim

Added 2026-09-14, because the previous versions' framing invited exactly the reading the requester objected to:

- **Not** that Ray cannot do this. **It demonstrably can** **[M]** — isolation, per-tool images, real GPU displacement, 20/20 alternations with zero errors, unattended replica recovery.
- **Not** that Ray should not be used. §0′.2 of the analysis lists six classes of work where it is the right tool, and we evaluated none of them.
- **Not** that the ~93 s stall is understood. **The mechanism is unknown and is deliberately not guessed at** after five wrong attributions.
- **Not** that the numbers generalise. Ray 2.57.0, two tools, one GPU, one host, no multi-node **[M]**.
- **Not** that KServe has been evaluated to this standard. **It has never been spiked** **[A]**, so §5's ranking rests on documents, not measurement.

### What this decision does *not* license

Stated because decisions drift at their edges ([`adr/README.md`](README.md)):

- **It does not ban Ray.** Role C is permitted; a tool that needs Ray for sharding uses it inside its own image.
- **It does not close Role B permanently.** A `ray` runtime backend remains addable behind the **D14** seam if `@serve.batch` ever proves superior to BentoML's dispatcher for a real tool.
- **It does not license dismissing the next reuse candidate in a paragraph.** The failure this ADR corrects was the thinness of §3.3, not the conclusion. Any future candidate gets the KServe treatment: scored against R1–R4, against the decision log, with a falsifier and a defined spike.
- **It does not claim Ray Serve is worse software.** For a homogeneous zoo of co-installable models it is better than what we are building. **Updated 2026-09-14:** the discriminator is no longer only the heterogeneity of this zoo — **it is the workload shape**. Mutually-exclusive tools swapped on request arrival is model-switching; Ray's autoscaler is built for scaling (re-basing §3). Heterogeneity is why **D2** is load-bearing; **the shape is why Ray's own path costs us ~93 s** **[M]**.

## Revisit when

> **Rewritten 2026-09-14.** The previous triggers are listed at the end of this section with their disposition, per the convention of preserving rather than deleting. **Two of the four had become unfireable or were simply wrong.**

**Ordered by how much they would change the decision.**

1. **The ~93 s pre-container stall is named, and proves configurable, defective-and-fixed, or version-specific.** **This is the strongest trigger, it is cheap, and it is ours to fire.** Concretely, any one of:
   - reading the **controller and proxy logs for a slow cycle** identifies the mechanism, and it is a setting we can change (ledger §9Z, gaps G1–G2);
   - the stall is traced to a Ray defect that is **fixed in a released version**;
   - **the step-9-eager protocol is re-run unchanged on a Ray other than 2.57.0 and the bimodality is absent** — nothing in the spike is version-checked, and this is the cheapest of the three.
   **Then the deciding ground of this ADR is gone** and Role A must be re-decided on the remaining rows, which are costs rather than refusals. **If instead the mechanism proves structural — inherent to placing a replica against a pending request — this ADR hardens and the trigger is discharged, not left open.**
2. **`image_uri` gains user-supplied `run_options`, or the Docker/CDI path works.** Then the GPU path stops depending on the deprecated `container` key **[S]**, the host-specific absolute path leaves every tool config **[M]**, and the mutual-exclusion constraint on `runtime_env` disappears. **Not decisive alone** — it does not touch the stall — but it removes the largest remaining cost row.
3. **M2 boot reconciliation proves hard, or router recovery bites in practice.** This is the **[A]** claim on *our* side. Ray's replica self-healing is measured **[M]**; ours is written down. **If ours fails in practice, the comparison flips on its weakest row** and Ray's operational story becomes the stronger one.
4. **The workload shape changes from model-switching to scaling.** If tools stop being mutually exclusive — more GPUs than tools, or replicas of one tool scaling with load — **Ray's autoscaler is aimed at exactly that** and the §3 mismatch dissolves. **This is the scope qualifier in the title doing its work: the decision is about a workload, so a change of workload reopens it.**
5. **The zoo becomes homogeneous**, i.e. every tool is co-installable in one environment. Then **D2** stops being load-bearing, Path 2 wins, and most of this repository should be deleted.
6. **A tool needs multi-GPU sharding of a single model** — Role C arrives, which needs no decision, and its arrival is a good prompt to re-read the analysis.
7. **A second GPU host is budgeted, or an HA or tenancy requirement is stated.** **Do not reach for Ray, and do not reach for a cluster reflexively.** The order is: price **static federation** first; then ask §5A.7's test — must a tool be *scheduled* on another host, or merely *forwarded* to one?; and **if it genuinely needs a cluster, go to Kubernetes-native serving, not to Ray** (re-basing §5), **re-running the comparison against KServe, which has never been spiked** **[A]**.

**Previous triggers and their disposition:**

| Previous trigger | Disposition |
|---|---|
| *"`runtime_env` gains a production per-deployment container/image boundary that composes with device pinning"* | **FIRED** **[M]**. The boundary exists and composes with GPU pinning. Only *"production-viable"* survives, and trigger 1 is what would settle it |
| *"`image_uri` leaving experimental status **and** the lockstep being relaxed"* — the 2026-08-13 *"strongest single one"* | **WITHDRAWN.** Partly obsolete (we used the mechanism **[M]**), partly resting on a ground since demoted to a cost, and unfalsifiable by us — it waited on someone else's release notes |
| *"A second host is added. Ray is genuinely multi-node… it would then compete with the Kubernetes growth path on better terms than KServe does"* | **WRONG, and replaced by trigger 7.** Robust multi-node Ray is KubeRay **[S]**, so it does not avoid Kubernetes; the project's own documented answer at cluster scale is KServe/Seldon ([`00_CONTEXT_AND_MOTIVATION.md:225`](../00_CONTEXT_AND_MOTIVATION.md:225)) |
| *"The zoo becomes homogeneous"* | **Unchanged** — trigger 5 |
| *"A tool needs multi-GPU sharding"* | **Unchanged** — trigger 6 |

**One discipline, not a trigger.** The Ray question is **closed for v1**, and the triggers above are the sanctioned way to reopen it. Seven re-defences and five analysis documents are themselves the largest carrying cost this refusal has; another unprompted re-litigation is the opposite of the simplicity being defended.

## Notes

Recorded because the previous answer to this question was not written down properly, and the challenger was right to notice. The conclusion survived; the argument for it did not exist yet.

**Postscript, 2026-09-14.** It now exists, and it is measured — but the argument that survived is **not** the argument this ADR was written to make. The structural claim of v1 was wrong, the capability claim of v2 was wrong, the *"whole argument"* fork was refuted by our own spike, and what is left is **one unexplained latency on one workload shape**. **A reader should notice that this is the third time the conclusion outlived its reasons, and weigh the conclusion accordingly** ([`bias-audit-and-decision-procedure.md`](../../plans/bias-audit-and-decision-procedure.md) §2). The defence offered is only that the current ground is a number rather than an argument, that the claim has been narrowed to match the evidence, and that trigger 1 could overturn it within a day.

Worth keeping in view: **independent convergence on bounded LRU model residency is evidence that the primitive is correct**, not that we are redundant. Ray Serve, Triton's explicit model control, llama-swap's groups and our own scheduler all describe the same idea. The disagreement is only ever about *where the isolation boundary sits*, and for this zoo that is a requirement rather than a preference.

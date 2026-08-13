# ADR-0003 — Ray Serve is not the router, and not the in-container runtime

- **Status:** **Accepted — settled on maintainability grounds, with triggers.** Superseded twice as evidence arrived; the third and current basis is operational cost, not capability. **Spike D is retired** ([`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md) §8).
- **Date:** 2026-08-12 (amended 2026-08-12; re-based 2026-08-13)
- **Adds:** **D29** to [`13_OPEN_QUESTIONS.md`](../13_OPEN_QUESTIONS.md) Part A
- **Full analysis:** [`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md) **(v3 — read that, not the Evidence section below)**
- **Depends on:** [ADR-0004](0004-hard-stop-only-in-v1.md), which removed soft unload from v1 and thereby removed the one open question that could have reversed this decision
- **Corrects:** [`14_ALTERNATIVES_EVALUATION.md`](../14_ALTERNATIVES_EVALUATION.md) §3.3, which dismissed Ray Serve in one paragraph, and §2.2, which implied no existing tool offers bounded LRU model eviction
- **Does not reopen:** [ADR-0001](0001-build-our-own-router.md). Ray Serve was not one of the three spikes, so this is a new question rather than a re-run of a closed one.

---

## Re-basing (2026-08-13) — the decision is settled, and it rests on maintainability

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

---

## Amendment (2026-08-12) — `runtime_env.image_uri` exists, and the first version of this ADR was wrong

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

1. **The existing record was thin.** Ray Serve got a single paragraph ([`14_ALTERNATIVES_EVALUATION.md`](../14_ALTERNATIVES_EVALUATION.md) §3.3) and a single table row ([`05_RUNTIME_AND_BATCHING.md`](../05_RUNTIME_AND_BATCHING.md) option C). **It was never spiked.** llama-swap, KServe and do-nothing each got a designed experiment; Ray Serve got three clauses.
2. **It is a closer match than KServe was.** KServe failed because Kubernetes has no preemption and Knative cannot express "keep the pod, release the weights". **Ray Serve has an analogue of both** — `@serve.multiplexed` is a bounded LRU cache of models inside a live replica, which is very nearly our `IDLE_SOFT` plus `max_resident`. The claim in §2.2 that our central primitive has no off-the-shelf equivalent was **wrong**, and this ADR withdraws it.

## Decision

**Ray Serve is not adopted as the router (Role A) and does not replace BentoML as the in-container runtime (Role B). Ray inside a tool image (Role C) remains permitted and always was.**

The three roles are separated deliberately, because conflating them is what makes this argument circular ([`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md) §3).

| Role | Outcome | On what grounds |
|---|---|---|
| **A** — replace the router | **Refused** | Structural: the fork below. Ray puts the eviction boundary and the isolation boundary in the same place; our zoo requires them apart. |
| **B** — replace BentoML inside the image (**D14** option C) | **Refused on cost, not principle** | Ray in every image is heavier than BentoML for one model per container. Reversible via the `RuntimeBackend` seam — a `ray` backend would be an addition, not a rewrite. |
| **C** — Ray *inside* one tool's image, e.g. multi-GPU sharding | **Permitted, no decision needed** | An author uses `base_image:` and imports Ray in their own container. The router neither knows nor cares. **We are not rejecting Ray; we decline to make it the boundary between tools.** |

## Evidence

### The fork — this is the whole argument

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

**This ADR is weaker than ADR-0001 and should not be presented as equivalent.**

- ADR-0001 rested on **three executed or directly-answered spikes**.
- This one rests on **documented behaviour plus one structural argument**. **No spike was run**, by explicit choice: a written answer was what was asked for.
- Every version-sensitive claim about Ray is listed as **unverified** in [`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md) §9, per the repository rule against documenting behaviour from memory.
- **Spike D is specified but not run** ([`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md) §10), with a decision rule that would delete most of this plan if it passed. That outcome would be welcome ([`HANDOFF.md`](../HANDOFF.md) §2).

**The single falsifier:** if `runtime_env` provides a production-viable **per-deployment OCI image** boundary that composes with per-device GPU pinning, then Ray Serve delivers **D2** *and* **D9** *and* **D25** together, the fork above dissolves, and this decision is wrong. That is §9 item 1, and it is the counterpart of Spike A's *"is the proxy protocol-agnostic?"* — the one fact the decision turns on.

## Consequences

### Accepted

- **Nothing changes in the implementation plan.** No milestone is added, removed or reordered. This ADR is a defence of existing scope, not a change to it.
- **We continue to own the scheduler**, bounded by the constraints in [`14_ALTERNATIVES_EVALUATION.md`](../14_ALTERNATIVES_EVALUATION.md) §7, which remain load-bearing.
- **We accept that a third of Ray Serve is reimplemented knowingly**, and say so publicly rather than claiming novelty. The parts that are genuinely ours are narrower than the challenge implies: the authoring ladder (**D3**), the schema and contract (**D13**, **D19**), preflight (**D17**), and the container-boundary scheduler.

### What this decision does *not* license

Stated because decisions drift at their edges ([`adr/README.md`](README.md)):

- **It does not ban Ray.** Role C is permitted; a tool that needs Ray for sharding uses it inside its own image.
- **It does not close Role B permanently.** A `ray` runtime backend remains addable behind the **D14** seam if `@serve.batch` ever proves superior to BentoML's dispatcher for a real tool.
- **It does not license dismissing the next reuse candidate in a paragraph.** The failure this ADR corrects was the thinness of §3.3, not the conclusion. Any future candidate gets the KServe treatment: scored against R1–R4, against the decision log, with a falsifier and a defined spike.
- **It does not claim Ray Serve is worse software.** For a homogeneous zoo of co-installable models it is better than what we are building. Our discriminator is the heterogeneity of *this* zoo.

## Revisit when

- **`runtime_env` gains a production per-deployment container/image boundary** that composes with device pinning — the falsifier above. This is the trigger that would make Ray Serve strictly better than what we are building.
- **The zoo becomes homogeneous**, i.e. every tool is co-installable in one environment. Then **D2** stops being load-bearing, Path 2 wins, and most of this repository should be deleted.
- **A tool needs multi-GPU sharding of a single model** — Role C arrives, and its arrival is a good prompt to re-read [`15_RAY_SERVE_EVALUATION.md`](../15_RAY_SERVE_EVALUATION.md).
- **A second host is added.** Ray is genuinely multi-node without a cluster to operate, so it would then compete with the Kubernetes growth path on better terms than KServe does.

## Notes

Recorded because the previous answer to this question was not written down properly, and the challenger was right to notice. The conclusion survived; the argument for it did not exist yet.

Worth keeping in view: **independent convergence on bounded LRU model residency is evidence that the primitive is correct**, not that we are redundant. Ray Serve, Triton's explicit model control, llama-swap's groups and our own scheduler all describe the same idea. The disagreement is only ever about *where the isolation boundary sits*, and for this zoo that is a requirement rather than a preference.

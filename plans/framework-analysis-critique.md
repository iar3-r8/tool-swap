# Critique — "Existing Model Serving Frameworks" analysis

> **Reviewing:** an engineer's objectives/requirements/framework-comparison document for R8 model serving.
> **Reviewed against:** [`plan/14_ALTERNATIVES_EVALUATION.md`](../plan/14_ALTERNATIVES_EVALUATION.md), [`plan/15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md), [ADR-0001](../plan/adr/0001-build-our-own-router.md), [ADR-0003](../plan/adr/0003-ray-serve-not-adopted.md), [ADR-0004](../plan/adr/0004-hard-stop-only-in-v1.md), and the primary-source captures in [`plan/third-party-docs/`](../plan/third-party-docs/README.md).
>
> **Verdict in one line:** the document is **directionally right and methodologically wrong**. Its conclusions mostly agree with ours, but its table cannot produce them — and four of its twenty cells repeat errors this repository has already made, published, and withdrawn.

---

## 1. Where the engineer is right, and it is most of the framing

Concede these first, because they are the strong parts and they should be kept verbatim in any merged version.

1. **The objectives section is better than ours was.** Naming the non-goals up front — no monitoring, no scaling, no version control — is exactly the discipline [`00_CONTEXT_AND_MOTIVATION.md`](../plan/00_CONTEXT_AND_MOTIVATION.md) §5 arrived at only after several drafts.
2. **"Prioritise existing frameworks"** is our **D12**, and the reason given — *"relevance and requirements will likely evolve"* — is a better justification than ours.
3. **The four strict requirements are the right four.** Single machine with GPUs, scale-to-zero on a shared box, conflicting dependencies, HTTP endpoints. Nothing to add and nothing to remove.
4. **"Run models with conflicting dependencies"** as a *strict* requirement is correct and is the load-bearing one. It is our **D2**, and the evidence behind it is not theoretical: ~300 pinned packages holding both `torch 2.8+cu129` and `tensorflow 2.16`, plus a URL-pinned `flash_attn` wheel built for `cu12torch2.8 / cp312`.
5. **KServe's verdict is right and the reason given is right.** *"Complex to setup (especially on a single machine)"* is the finding of our Spike B.
6. **MLflow's verdict is right for the right reason.** Its scale-to-zero and fractional allocation *are* delegated to an external backend, which means it is not a candidate — it is a wrapper around whichever candidate you pick.
7. **Ray Serve scoring highest is correct.** It is the closest match of any candidate. Our own §3.3 dismissed it in one paragraph and was rightly challenged for it.
8. **The "same version of Python and Ray in every container" note is the single most valuable sentence in the document.** See §4.1 — it deserves promotion, not a footnote.

---

## 2. The structural problem: every column is a capability column

All five columns ask *can it*. None asks *what would we operate and maintain for three years*.

This is the exact trap [`15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md) fell into three times. Versions 1 and 2 of that document argued capability, lost ground on each revision, and had to be re-based on maintainability in v3 — because **a sufficiently determined engineer can make almost any framework do almost anything.** Capability tables therefore converge on "everything is ⚠️" and decide nothing.

The symptom is visible in the engineer's own table: **Ray Serve scores 4.5 out of 5 and is still not the answer.** When the winner of a scorecard is not the recommendation, the scorecard is not carrying the decision — something unstated is. Worth making the unstated thing explicit rather than leaving it as taste.

### 2.1 The missing column that actually decides it: preemption

**"Scale-to-Zero" and "preempt an idle incumbent" are different requirements, and the table conflates them.**

- **Scale-to-zero** is a *timer* releasing an idle resource. Every ✅ in that column is this.
- **Preemption** is a *request* forcing release now, before the timer fires.

Our requirement is quotable and it is the second one:

> *"We don't want to wait for TTL as it could take quite some time, if another process is not being used right now we want to stop it and warm up any process that has a request."* (**D25**)

This distinction is the entire reason KServe was rejected — and KServe has ✅ in the Scale-to-Zero column. Kubernetes *allocates* devices; with one GPU and two models the second pod sits `Pending` indefinitely and nothing evicts the incumbent. Ray has the same shape of problem in a different place: `@serve.multiplexed` gives real bounded-LRU displacement, but it operates *inside* a replica, while `image_uri` isolation operates *around* it — so a **containerised** tool cannot be cheaply displaced.

**Recommendation:** add a **Preemption / displacement** column. It is the column where every framework in the table scores ❌ or ⚠️, which is precisely why it is the interesting one.

### 2.2 Three more missing columns, each of which changed our decision

| Missing column | Why it decides something |
|---|---|
| **Authoring UX** | Our **R2**: a scientist with a `requirements.txt` and a `load()`/`predict()` function. KServe's *serving runtime* path is excellent and better than anything we would build; its *custom predictor* path means a Dockerfile, a `kserve.Model` subclass, a registry push and an `InferenceService` YAML. Those two paths deserve separate rows, not one cell. **No framework in the table does the requirements.txt-to-agent-callable-tool step**, and that is the honest remainder. |
| **Truthful readiness** | BentoML's `/readyz` returns 200 when the *server* is up, not when *weights* are loaded — confirmed in source, not inferred. R8 polled it and proved nothing. Any framework's health endpoint must be checked for this, and the table does not look. |
| **Maintenance surface** | API stability labels, version coupling, and failure recovery. For Ray this is three experimental-or-alpha APIs stacked under the most load-bearing decision in the plan, plus *"if you aren't using KubeRay, when the Ray cluster fails, Ray Serve cannot recover"* — Ray's own words, on a box we do not administer. |

### 2.3 The scoring scheme invites the wrong arithmetic

✅/⚠️/❌ across equally-weighted columns invites summing checkmarks. Two of these requirements are **gates** (conflicting dependencies; preemption) — failing one eliminates a candidate regardless of the rest. The others are **costs**, which trade off. Mixing gates and costs in one grid is what lets a 4.5/5 candidate lose.

**Recommendation:** split the table in two — *gates that eliminate* above, *costs that trade* below — and attach a named **falsifier** to each rejection. The falsifier discipline is not decoration: ADR-0003 published one, it fired within hours, and the error was corrected instead of becoming folklore.

---

## 3. Cell-by-cell: four errors, three inconsistencies

### 3.1 ❌ Ray Serve, Dependency Isolation: **⚠️ is wrong, and we made this same error twice**

`runtime_env.image_uri` runs each Serve *application* in its own container image — *"all deployment replicas in the applications start and run in containers with the respective images"*. That is a real OCI image boundary, not a pip layer. **Ray satisfies the conflicting-dependencies requirement.**

This is not a nitpick. v1 of our Ray evaluation asserted *"pip layer, not a process boundary"*, was challenged with the multi-application container guide, and had to withdraw the claim. ADR-0003 carries the withdrawal in writing. **Anyone repeating "Ray only isolates at the pip layer" is repeating an error of ours** — and the engineer's ⚠️ is the same error in milder form.

The correct cell is **✅ with two asterisks**: the API is labelled *"experimental and the API is subject to change"* and the previous `container` field is already deprecated in favour of it; and see §4.1 for the lockstep.

### 3.2 ❌ Ray Serve, Fractional Resources: **✅ is true and misleading**

`ray_actor_options={"num_gpus": 0.5}` exists and does what the docs say. But it is an **accounting reservation with no VRAM enforcement** — Ray's own guidance is *"if you have two models and each doesn't fully saturate a GPU"*, i.e. the user guarantees the fit. Two half-GPU deployments that both grow will OOM each other, and on a shared DGX the victim may not even be ours.

Presented as a plain ✅ against a stated requirement, this will mislead a reader into thinking the fractional-allocation nice-to-have is *solved* by Ray. It is *expressible* in Ray. Our **D7** declines exactly this trade deliberately, in favour of whole-device pinning, and **D27**'s rule is *measure free VRAM, never predict it*.

**Recommendation:** rename the column **Fractional resources (enforced?)** and the cell becomes ⚠️ for every row, because no scheduler in the table enforces VRAM.

### 3.3 ⚠️ KServe, Fractional Resources: **❌ is inconsistent with the Ray cell**

The NVIDIA device plugin supports MIG partitioning, time-slicing and MPS, all of which Kubernetes schedules. If Ray's unenforced `num_gpus: 0.5` earns ✅, then k8s time-slicing cannot be ❌. As written, the column is scored by a different standard in each row — which is the failure mode that makes comparison tables unreliable in general.

### 3.4 ⚠️ KServe ✅ vs Ray ⚠️ on Dependency Isolation: same mechanism, different marks

Both isolate by giving each unit its own container image. Whatever the marks are, they should match, with the asterisks carrying the difference (Ray: experimental API + version lockstep; KServe: needs a registry the cluster can pull from, which is where the minikube path failed our **R2** — a `minikube image load` of a multi-gigabyte image after every build).

### 3.5 ⚠️ BentoML, Scale-to-Zero ❌ and *"requires an orchestrator like Kubernetes"*

Both statements are **true of BentoML-as-orchestrator** and they lead to the wrong conclusion, because they only score one of its two possible roles.

We adopted BentoML **as a library inside each tool's container** (**D14**) — not as the thing that manages lifecycle. In that role the scale-to-zero column does not apply, and what we get instead is the adaptive dispatcher: *"continuously adjusts batch size and window based on real-time traffic patterns"*, with `max_latency_ms` honoured by predicting batch processing time. **That is the single largest piece of complexity this plan avoids** — we write no batcher at all. Two batchers were written in R8 and neither ended up running, which is the argument for reusing a third party's.

Scoring frameworks only as orchestrators hides the best available answer for one of the requirements. Every candidate should be scored **per role**: router/orchestrator, in-container runtime, and library-inside-a-tool. Conflating the three is what makes reuse arguments circular.

### 3.6 ⚠️ *"Only supports Python models"* is doing no work

It is repeated for Ray, BentoML and MLflow, and KServe's R support is offered as its differentiator — but **non-Python models are not in the requirements list**, not even as a nice-to-have. Meanwhile any of these frameworks can shell out to or proxy a non-Python server from inside a container, so the constraint is soft even where it applies.

Either promote "non-Python models" to a stated requirement — in which case it should be argued from a real model someone needs — or drop the criterion. Right now it silently advantages KServe against a requirement nobody made.

### 3.7 ⚠️ The nice-to-have *"no required dependencies for models"* is unscored

It is stated in the requirements and appears in no column. Worth scoring, because it is where the frameworks genuinely diverge and where the *strongest* argument against Ray lives (§4.1).

---

## 4. The two strongest arguments are present but buried

### 4.1 The Ray/Python version lockstep is a maintenance argument, and it is decisive

The engineer writes it as a clause: *"each container must have the same version of Python and Ray installed."* Ray's own wording is stronger — the versions must match the host environment *"down to the patch number."*

This does **not** defeat the isolation requirement; separate images still resolve every dependency conflict in the evidence base. What it does is impose a coupling across the whole zoo:

| | BentoML inside each image (**D14**) | Ray Serve |
|---|---|---|
| Runtime version in an image | Pinned per image, chosen per tool | **Must equal the cluster's, exactly** |
| Upgrading it | One tool at a time, at leisure | **Every image, at once**, or the tool does not run |
| A tool needing an older Python | Fine — it is its own image | **Impossible** without moving the cluster |
| Blast radius of a runtime bump | One tool | ~20 heterogeneous images, several painful to rebuild |

**This is the evidenced form of "Ray is heavy"** — an objection our own drafts asserted three times without support and had to withdraw as unmeasured. It is not about RSS or process count. It is that a Ray upgrade is a coordinated migration of the entire zoo. For a small research team maintaining ~20 images, that is the difference between a maintainable system and one that quietly stops being upgraded.

And note the honesty check this survives: **D14** knowingly accepts a pinned dependency in every image too. We cannot invoke that principle for BentoML and refuse it for Ray *unless the coupling is categorically stronger* — which it is: ours is per-image and gradual, Ray's is global and simultaneous.

**This belongs in the table as a column, not in a bullet under the table.** It also maps directly onto the engineer's own unscored nice-to-have, *"no required dependencies for models"*: Ray fails it hardest, and the document never says so.

### 4.2 "Complex to set up" understates what KServe actually requires

*"Runs on top of a Kubernetes cluster, which is complex to setup"* is true but soft. Concretely, adopting KServe means adopting Kubernetes **plus Knative Serving** (scale-to-zero comes from Knative's activator, not KServe — and KServe's Raw Deployment mode avoids Knative but also gives up scale-to-zero, the one feature we came for), **plus** a mesh or Kourier, **plus** a container registry the cluster can pull from, **plus** a GPU device plugin, **plus** cluster-level observability.

On a single research box that stack is heavier than everything it serves. And the debugging surface a scientist must learn to answer *"why won't my model start?"* is pod events, init-container logs, Knative revision conditions and possibly mesh config.

---

## 5. The omission: the closest existing thing is not in the table

**llama-swap is absent, and it is the nearest match to these exact requirements.** It is a single Go binary with a YAML config that does on-demand start, TTL, groups, a `/upstream/{model}` proxy and a status UI — and **it drives containers as a headline feature**: `cmd` with `docker run --gpus '"device=2,3"'` paired with `cmdStop: docker stop ...`. Upstream *recommends* containers for Python inference servers, for *"clean environment isolation"* — which is the conflicting-dependencies requirement, in their words, as an independent witness.

Scored on the engineer's own columns it would read: single machine ✅, scale-to-zero ✅, dependency isolation ✅, HTTP endpoints ✅, fractional ❌. **That is a better row than any in the table**, and its absence is the largest gap in the analysis.

**We rejected it anyway, for one narrow reason** worth knowing because it is the kind of finding a capability table never produces: llama-swap dispatches by extracting `model` from a chat-completion request body, and our tools are addressed by URL path with JSON-Schema-validated bodies. No configuration of theirs expresses that. Two independent blockers sit behind it — no batching contract to give a tool, and no schema surface to project into agent-facing tool definitions.

Note the shape of that reason: **not "it fails a requirement", but "its request-dispatch model is the wrong shape for our contract."** Roughly a third of its schema is LLM-specific; the swap machinery is not. A survey that had listed it with a ⚠️ would have missed why it fails.

**Two more absences**, both cheaper to add than to justify omitting:

- **Triton with `--model-control-mode=explicit`** — the load/unload API *is* the TTL feature, with mature dynamic batching. It fails the isolation requirement in an interesting way: Python-backend models share the Triton process and environment, so per-model isolation needs conda-pack stub environments per model.
- **Ollama / Docker Model Runner** — LLM-only, so not candidates, but they confirm the on-demand-load-with-idle-timeout UX is the industry norm rather than our invention.

---

## 6. What the corrected table looks like

Gates first. A ❌ here eliminates, regardless of everything below.

| | Conflicting deps (image boundary) | **Preemption** (evict on request) | HTTP endpoints | Single machine, no k8s |
|---|---|---|---|---|
| **KServe** | ✅ | ❌ allocates, second pod stays `Pending` | ✅ | ❌ |
| **Ray Serve** | ✅* experimental API | ❌ displacement is inside a replica; isolation is around it | ✅ | ⚠️ needs Podman + a cluster that *"cannot recover"* without KubeRay |
| **BentoML** (as orchestrator) | ✅ | ❌ needs an external orchestrator | ✅ | ⚠️ |
| **llama-swap** | ✅ via `docker run` + `cmdStop` | ✅ groups + eviction | ⚠️ dispatch is by `body.model` | ✅ |
| **MLflow** | — delegates to a backend | — delegates | ✅ | — delegates |
| **Triton** (explicit control) | ❌ shared process for Python backends | ✅ load/unload API | ✅ | ✅ |

Then costs, which trade rather than eliminate: runtime-version coupling, authoring UX for a non-expert, truthful readiness, batching quality, operational surface, bus factor, fractional-VRAM enforcement (⚠️ everywhere).

**Read that way, the table says something the original cannot: no row passes all four gates.** So the real question was never "which framework wins" but **"which framework leaves the smallest custom remainder, and is that remainder the interesting part or the plumbing?"** For us the remainder is the authoring layer, the uniform contract, and an eviction table above the container boundary — a few hundred lines of pure, testable policy over Docker, FastAPI and BentoML, none of which we wrote.

---

## 7. Two claims worth verifying before anyone relies on this

Both are cheap, need no GPU, and neither would change the recommendation — which is worth saying in advance so results are not over-read.

1. **Per-*deployment* `image_uri`.** Ray's docs contradict themselves: the dependency guide shows per-deployment `runtime_env`, while the multi-app-container guide says `image_uri` is per-*application* and composes only with `config` and `env_vars`. `runtime_env` is also a documented `ray_actor_options` key. Test: two deployments, two images, print the image inside each replica. A yes would make a Ray-native design architecturally neat; it leaves the lockstep and the recovery story untouched.
2. **Re-confirm the lockstep wording against current Ray.** It is the strongest single ground in both documents, and it is a version fact. Our capture is Ray 2.57.0 (2026-08-13). Never restate framework behaviour from memory.

---

## 8. Summary

| | |
|---|---|
| **Are they right?** | **On the conclusions, largely yes** — KServe too heavy for one box, MLflow a delegator, Ray the closest match, existing frameworks preferred on principle. Our independent analysis reached the same rejections. |
| **Should it be challenged?** | **Yes, on method and on four cells.** The table scores capability when the requirement is maintainability; it conflates scale-to-zero with preemption, which is the requirement that actually eliminated KServe; it understates Ray's isolation (an error we published and withdrew); it overstates Ray's fractional GPUs as if VRAM were enforced; it scores the fractional column by different standards per row; it judges BentoML only as an orchestrator when its value is as an in-container library; and it omits llama-swap, the closest existing thing. |
| **What to adopt from it** | The objectives framing, the four strict requirements verbatim, and the Python/Ray version note — **promoted from a bullet to a column**, because it is the strongest argument either document contains. |
| **The correction that matters most** | Score every candidate **per role** (router, in-container runtime, library inside a tool) and **separate gates from costs**. Conflating roles is what makes reuse arguments circular; conflating gates with costs is what lets a 4.5/5 candidate lose without the table explaining why. |

**The pattern worth keeping from our side of this, earned by being wrong three times:** *reuse the engine, own the contract — check the engine's manual before saying what it cannot do, and then ask what it costs to keep running.*

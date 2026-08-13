# 15 — Ray Serve: the second "are we reinventing the wheel?" challenge

> **v3.** Raised after the M−1 gate closed: *"I got challenged that we were reimplementing Ray Serve — why not use this framework?"* Then refined: *"we need to know if we are reimplementing a complex stack just for the fun of it… prioritise making the tool robust and easy to maintain."*
>
> **Version history, because the direction of travel is itself evidence.**
> **v1** argued Ray could not isolate tools in containers. **Wrong** — `runtime_env.image_uri` does exactly that.
> **v2** conceded that and retreated to a semantic gap: Ray cannot express *alive but unloaded*. Then [`third-party-docs/ray-serve/`](third-party-docs/ray-serve/INDEX.md) was captured, and the gap narrowed again.
> **v3 stops defending a capability argument that has lost three times, and argues the axis the requirement is actually stated on: robustness and maintainability.** It also records a change that dissolves the central question — [ADR-0004](adr/0004-hard-stop-only-in-v1.md) removes soft unload from v1, so the one thing Ray was being tested for no longer needs to exist.

---

## 1. The three concessions, made once and not re-argued

Restating these each revision has made this document long and repetitive. They are conceded, permanently, and **the case below does not depend on any of them**:

1. **`runtime_env.image_uri` gives each Serve application its own container image.** **D2 is satisfiable on Ray.** v1's "pip layer, not a process boundary" claim was false.
2. **`@serve.multiplexed` is bounded LRU model residency, off the shelf.** [`14_ALTERNATIVES_EVALUATION.md`](14_ALTERNATIVES_EVALUATION.md) §2.2's implication that our central primitive had no equivalent was wrong.
3. **Ray has a designed home for a scheduler.** Application-level autoscaling policies receive every deployment's context and return targets for all of them; there is also an external scaling REST API. v2's *"we would write the scheduler either way and Ray gives us nowhere to put it"* was **too strong** — Ray gives us somewhere good to put it.

**Also withdrawn permanently:** *"R8's own Ray attempt stalled"* is not evidence about Ray ([`12_REFERENCE_CODE.md`](12_REFERENCE_CODE.md) §8 shows the defect was a caller force-flushing its own batch).

**What all three have in common: they are capability findings.** Ray *can* do these things. The question this document now asks is different, and it is the question that was actually put to us.

---

## 2. The question changed, and it is a better question

> *"Prioritise making the tool robust and easy to maintain."*

Three revisions of this document scored Ray on **can it**. None scored it on **what would we be signing up to operate and maintain for the next three years**. That is the stated priority, it is the axis on which the answer is clear, and it is the axis this version argues.

The reframing is not a retreat to softer ground. **Capability arguments are the weaker ones here**, because a sufficiently determined engineer can make almost any framework do almost anything. Maintenance burden is what actually decides whether a system is still working in eighteen months.

---

## 3. The finding that reframes everything: we are no longer building what we were testing Ray for

**[ADR-0004](adr/0004-hard-stop-only-in-v1.md) removes soft unload from v1.** The requester clarified the premise ADR-0002 had inferred:

> *"Unloading on the shared DGX is not 'so' critical… We do not have any mechanism to quickly unload a model on demand, we just don't want to block all the resources indefinitely. If soft unload is not possible let's just not use it and do hard unloads and find out if it becomes a problem later."*

**This dissolves the hinge of v2.** That version identified exactly one decisive open question — *can `reconfigure()` genuinely release VRAM from a live replica, giving Ray an equivalent of `IDLE_SOFT`?* — and called it *"the single most valuable open question in this document"*. Spike D step 7 existed to answer it.

**We are not building `IDLE_SOFT`.** A framework's ability to express a state we have removed from the design cannot be a reason to adopt that framework.

Consequences, and they are large:

- **D9 leaves the Ray scorecard entirely.** So does **D26**, and **D27**/**D28** reduce to a distinct error reason on the cold-start path, which any framework supports.
- **Spike D is retired, not rescoped** (§8). Its decisive step tests a capability we no longer need.
- **What remains is the comparison v2 kept calling "the weaker argument": operational surface.** With the semantic question gone, it is the *only* argument — and it is the one the requester asked for.

---

## 4. The maintenance surface, which is the actual case

### 4.1 What a Ray-native tool-swap would depend on

Assembled from the captured documentation. Each row is Ray's own stability language.

| Component we would need | Purpose | Ray's own words |
|---|---|---|
| `runtime_env.image_uri` | Per-tool images (**D2**) | *"This feature is experimental and the API is subject to change"* — and the previous `container` field is **already deprecated in favour of it** |
| Custom / application-level autoscaling policy | Our scheduler | *"Custom autoscaling policies are experimental and may change in future releases"* |
| External scaling API | Driving replica counts from our controller | *"This API is in alpha and may change before becoming stable"* |
| `user_config` → `reconfigure()` releasing VRAM | Soft unload, **if we wanted it** | **Undocumented.** Ray claims *"adjust model weights and versions without restarting"*; it never claims device memory returns |
| Config updates at request cadence | Every swap | Docs frame these as *deployment*-time; *"NOT recommended in production"* for graph updates |
| `image_uri` **per deployment** rather than per application | Many tools under one coordinating policy | **The documentation contradicts itself.** [`handling-dependencies.md`](third-party-docs/ray-serve/production-guide/handling-dependencies.md) shows per-deployment `runtime_env`; [`multi-app-container.md`](third-party-docs/ray-serve/advanced-guides/multi-app-container.md) says `image_uri` is per-application and composes only with `config` and `env_vars`. Unresolved |

**Three experimental-or-alpha APIs, one undocumented behaviour, one documented-against usage pattern, and one unresolved contradiction — all load-bearing simultaneously, underneath D2, the most important decision in the plan.**

That is the answer to *"are we reimplementing a complex stack for the fun of it?"* **Adopting Ray would be the complex option**, not the simple one. It only looked simple while we were counting features instead of counting the things that must not change under us.

### 4.2 The version lockstep is the maintenance argument, and it is decisive

> *"The Ray version and Python version in the container **must** match those of the host environment exactly. Note that for Python, the versions must match down to the patch number."*

This does **not** defeat **D2** — separate images still resolve every dependency conflict in our evidence base. What it does is impose a coupling across the whole zoo:

| | tool-swap (**D14**, BentoML) | Ray Serve |
|---|---|---|
| Runtime version in an image | **Pinned per image**, chosen per tool | **Must equal the cluster's**, exactly |
| Upgrading it | One tool at a time, at leisure | **Every image, at once**, or the tool does not run |
| A tool needing an older Python | Fine — it is its own image | **Impossible** without moving the cluster |
| Blast radius of a runtime bump | One tool | ~20 heterogeneous images, several painful to rebuild |

**This is the honest, evidenced form of "Ray is heavy"** — an objection asserted three times in earlier drafts and never supported. It is not about RSS or process count. It is that **a Ray upgrade is a coordinated migration of the entire zoo**, whereas a BentoML upgrade is a per-tool decision. For a small research team maintaining ~20 images, that is the difference between a maintainable system and one that quietly stops being upgraded.

**And note the asymmetry with our own accepted cost.** **D14** knowingly accepts a pinned dependency in every image. We cannot invoke that principle for BentoML and refuse it for Ray — *unless the coupling is categorically stronger*, which it is: ours is per-image and gradual, Ray's is global and simultaneous.

### 4.3 Failure recovery on a node we do not administer

From [`architecture.md`](third-party-docs/ray-serve/architecture.md), Ray's own page:

> *"If you aren't using KubeRay, when the Ray cluster fails, Ray Serve cannot recover."*

**We are not on Kubernetes** ([ADR-0001](adr/0001-build-our-own-router.md)), and adopting KubeRay to make Ray recoverable would re-open a gate closed on evidence.

| | tool-swap | Ray Serve without KubeRay |
|---|---|---|
| Processes to operate | Router (one FastAPI process) | Controller + proxy per node + one actor per replica + GCS + raylet + dashboard + **Podman** |
| Router/cluster dies | Restart it; boot reconciliation adopts running containers | **"Cannot recover"** by Ray's own statement |
| Persistent state | **None** (guardrail 8) | GCS checkpoints on the head node |
| Prerequisites on the shared DGX | Docker (already there) | **Podman on every node**, `--privileged` if the raylet is containerised, with documented `overlayfs` and slow-startup-on-large-images failure modes |

**Guardrail 8 says restarting the router must be safe and cheap.** Ray's documented answer for our topology is that it cannot recover. On a shared DGX we do not administer, installing Podman is also a request to somebody else's change process — a maintenance cost that appears in no feature comparison.

### 4.4 Ray's scheduling vocabulary stops one word short

The concession of §1 item 3 is real: application-level policies are structurally a scheduler interface, and the external scaling API is a clean integration point. But every hook's **output is a replica count**.

And [`advanced-autoscaling.md`](third-party-docs/ray-serve/advanced-guides/advanced-autoscaling.md) closes the most optimistic reading:

> *"Setting `min_replicas = 0` causes higher tail latencies; when you start sending traffic, the deployment scales up, and there will be a **cold start time**."*

So `num_replicas: 0` is Ray's **hard stop**, not a warm state — which **settles open question 9 negatively**. Under [ADR-0004](adr/0004-hard-stop-only-in-v1.md) that is no longer a defect, because hard stop is exactly what v1 does. **It simply means Ray offers us nothing our own design does not already have**, while costing everything in §4.1–4.3.

One genuine point of convergence worth recording: **`downscale_to_zero_delay_s` is our `ttl` under another name**, with the docs' example value (1800 s) in the same range as our defaults. Independent convergence on idle-timer reclamation is evidence the primitive is right.

---

## 5. Where Ray Serve is genuinely better

Unchanged from v2, and worth keeping visible:

- **`image_uri` is a real per-application container boundary**, and the plan should never again imply per-tool isolation is unique to us.
- **Multiplexing is a cleaner articulation of bounded LRU residency** than our own prose. Borrow the vocabulary.
- **No registry needed for local deployment** — precisely where the KServe/minikube path failed **R2**.
- **`serve status` and the dashboard** are a better status surface than we will build in v1.
- **The 100 KiB object-store threshold** is a genuine efficiency win over HTTP bodies for large tensors.
- **It is the right answer if the zoo becomes homogeneous**, or splits into families that can share an image, or grows to a second host.
- **Independent convergence validates our design.** Ray, Triton's explicit model control, llama-swap's groups and our scheduler all describe the same idea.

**And a caution against the reflex this document could encourage:** the correct response to a reuse challenge is the KServe treatment — score against R1–R4 and the decision log, name a falsifier, define a spike. Three revisions here were caused by *not* reading the manual before saying what a framework could not do. That lesson costs nothing to keep.

---

## 6. Scored against the requirements

| Req | Ray Serve with `image_uri` | Verdict |
|---|---|---|
| **R1** launch, logs, status | `serve status` with per-replica states, plus a dashboard — genuinely better than ours. Against it: a Podman troubleshooting surface, per-session per-worker logs, and *"cannot recover"* without KubeRay | **Partial.** Better observability, worse operability |
| **R2** add a tool | Good: a Dockerfile, no registry locally, a few lines of config. **But** every image must pin the cluster's exact Ray *and* Python patch version, and our base images would derive from Ray's | **Partial.** The ladder survives; free choice of interpreter does not |
| **R3** proxy | Native HTTP ingress, FastAPI integration | **Wins** |
| **R4** simple config | Applications, `runtime_env`, `ray_actor_options`, autoscaling blocks. Larger than our five-line minimum (guardrail 10) | **Partial** |

**Against the decisions**, post-[ADR-0004](adr/0004-hard-stop-only-in-v1.md) — note how much shorter this table is than v2's, because half the rows tested a feature we no longer build:

| Decision | Ray, path 1b (`image_uri`) |
|---|---|
| **D2** one image per tool | ✓ **satisfied**, subject to Ray/Python lockstep and an experimental API |
| **D5** micro-batching | ✓ `@serve.batch` (fixed-window, not adaptive — **closes open question 5**) |
| **D7** whole-device pinning | ~ and **re-pinning restarts replicas**: GPU assignment lives in `ray_actor_options`, a *code* update |
| **D25** preempt an idle incumbent | ~ reachable by driving replica counts, at a cadence the docs warn against |
| **D28** a neighbour's VRAM is not our failure | ~ custom handling either way |
| **Guardrail 8** restart cheap, no state | ✗ **a cluster that "cannot recover" without KubeRay** |
| ~~**D9** soft unload~~ | **removed from v1** ([ADR-0004](adr/0004-hard-stop-only-in-v1.md)) — no longer scored |
| ~~**D26** verified release~~ | **removed from v1** — no longer scored |

---

## 7. If we adopted it anyway

**Deleted:** the container backend, the TTL watchdog and much of the lifecycle manager. Genuinely less code than we are writing.

**Retained regardless:** the authoring ladder (**D3**), the schema compiler and `?format=tools` (**D13**), `tswap preflight` (**D17**), mandatory descriptions (**D19**), the reference resolver (**D18**), the **R1** status and CLI surface — and the eviction policy itself, now expressed as a Ray autoscaling policy. **The platform does not remove the interesting work**; it relocates it.

**Added:** a Ray cluster to operate, Podman on a node we do not administer, a Ray/Python lockstep across every image, three experimental-or-alpha API dependencies, and an unrecoverable-cluster failure mode.

**Net:** we would trade a few hundred lines of pure, testable policy for a distributed system with six process types and three experimental APIs — **and still write the policy.**

---

## 8. Spike D is retired

v2 specified an eight-step spike and called it *"now the recommended next step rather than an optional one"*. **It is now withdrawn**, for three reasons:

1. **Its decisive step (7) tests `reconfigure()` releasing VRAM — a capability we removed from the design** ([ADR-0004](adr/0004-hard-stop-only-in-v1.md)). A pass would change nothing.
2. **It requires Podman on the shared DGX**, which is itself one of the reasons not to adopt Ray. The spike cannot be run without first paying part of the cost it was meant to evaluate.
3. **Its decision rule was wrong.** *"If step 7 passes, Ray Serve replaces our router"* weighed one capability and ignored the operational axis entirely — the axis the requirement is stated on.

**What replaces it: nothing, deliberately.** No experiment would change the decision, because the decision no longer rests on an unknown. The version lockstep, the experimental labels, the Podman prerequisite and *"cannot recover"* are all **documented facts, quoted in §4**, not hypotheses. Running an experiment to confirm documented facts is how a plan spends a week feeling rigorous.

**If someone wants to test something anyway**, the only question left with any leverage is open question 12 — *does `ray_actor_options={"runtime_env": {"image_uri": ...}}` give a per-deployment container?* — because a yes would make a Ray-native tool-swap architecturally neat. It needs no GPU and no DGX: two deployments, two images, print the image inside each replica. **Even a yes would not flip the decision**, because §4.2 and §4.3 are untouched by it. That is worth stating in advance, so the result is not over-read.

---

## 9. Open questions, closed out

§9 of v2 listed eleven; the capture proposed four more. Most are now moot rather than answered, which is the point.

| # | Question | Status |
|---|---|---|
| 1 | Is `runtime_env` only a pip layer? | **Resolved against v1.** `image_uri` is a real image boundary |
| 2 | Does `CUDA_VISIBLE_DEVICES` reach a containerised replica? | Open, **moot** — only matters if we adopt |
| 3 | Can an application be released on demand, and at what cost? | **Answered:** yes by deleting/updating it, at full container start |
| 4 | Any representation of *alive but weights released*? | **Moot** — [ADR-0004](adr/0004-hard-stop-only-in-v1.md) removes our need for one |
| 5 | Is `@serve.batch` adaptive like BentoML's dispatcher? | **Closed: no.** Fixed-window, runtime-tunable via `reconfigure()`, with a `batch_size_fn` we lack. Mildly favours **D14** |
| 6 | Cold start for a multi-GB image under Podman | Open, **moot** |
| 7 | "Ray is heavy" — process count and RSS | **Superseded.** [`architecture.md`](third-party-docs/ray-serve/architecture.md) gives the process inventory; §4.2 replaces the RSS claim with the version-lockstep argument, which is better evidenced and matters more |
| 8 | Can `reconfigure()` genuinely release VRAM? | **Moot — this was the hinge, and [ADR-0004](adr/0004-hard-stop-only-in-v1.md) removed it** |
| 9 | Does `num_replicas: 0` keep a process alive? | **Closed: no.** *"There will be a cold start time"* |
| 10 | Is the config-update path safe at request cadence? | Open, and the docs discourage it. **Moot** unless adopting |
| 11 | Device re-pinning, given `ray_actor_options` is a code update | **Answered: it restarts replicas** (**D7**) |
| 12 | Per-deployment `image_uri`? | **Open, unresolved in the docs, and the only one with leverage** (§8) |
| 13 | Can an application-level policy see other applications? | Open. **Moot** unless 12 is yes |
| 14 | Controller health at request cadence | Open, **moot** |
| 15 | Instrument any spike with Ray's own metrics | **Moot** — no spike |

---

## 10. Recommendation

**Do not adopt Ray Serve as the router. This is now a decision, not a deferral, and the grounds have changed from capability to maintainability.**

1. **Role A (router) — refused, on the axis the requirement names.** Adopting Ray means depending on three experimental-or-alpha APIs, an undocumented behaviour and one unresolved documentation contradiction, all beneath **D2**; locking every image to the cluster's exact Ray and Python patch version; installing Podman on a shared node we do not administer; and accepting a cluster that, in Ray's own words, *"cannot recover"* without Kubernetes. **Against a stated priority of robust and easy to maintain, that is not a close call.**
2. **Role B (in-container runtime) — refused on cost, reversibly**, behind the **D14** `RuntimeBackend` seam. **Open question 5 is now closed in BentoML's favour** on adaptivity.
3. **Role C (Ray inside a tool image) — permitted, and always was.** A tool needing Ray for tensor-parallel sharding uses `base_image:` and imports it. **We are not rejecting Ray; we decline to make it the boundary between tools.**
4. **Spike D is retired** (§8), and **D29** is restated as settled-with-triggers.

---

## 11. Revisit when

Concrete triggers, each of which removes one pillar of §4:

- **`image_uri` leaves experimental status *and* the Ray/Python lockstep is relaxed.** Both, not either — the lockstep is §4.2 and it is the strongest single ground.
- **We adopt Kubernetes for other reasons.** KubeRay answers §4.3 outright, and the [ADR-0001](adr/0001-build-our-own-router.md) triggers (a second GPU host, multi-tenant isolation, an infra team already running it) would have fired anyway.
- **The zoo becomes homogeneous or splits into families** that can share an image. Then **D2** stops being load-bearing, `@serve.multiplexed` wins outright, and most of this repository should be deleted.
- **Soft unload returns and proves expensive to maintain ourselves.** [ADR-0004](adr/0004-hard-stop-only-in-v1.md) names the measurements that would re-promote it; if it comes back, `reconfigure()` becomes interesting again and open question 8 revives.
- **A second host is added.** Ray is genuinely multi-node, and would then beat the Kubernetes growth path for a research team.

---

## 12. Summary answer to the challenge

*Are we reimplementing Ray Serve?*

**In part, knowingly, and less than before.** Three capability concessions stand and are not re-argued: Ray can containerise each tool, deploy them independently, and host a scheduler policy.

**But the question we were actually asked is whether we are building a complex stack for the fun of it, and the answer is no — because adopting Ray would be the complex option.** It means operating a distributed system of six process types on a shared node we do not administer, depending on three experimental-or-alpha APIs beneath our most load-bearing decision, and coupling every tool image to the cluster's exact Ray and Python patch version, in exchange for deleting a few hundred lines of pure, fully-testable eviction policy that we would substantially have to write anyway.

**And the thing Ray was being tested for is gone.** [ADR-0004](adr/0004-hard-stop-only-in-v1.md) removed soft unload from v1, so the one question that could have flipped this decision — can `reconfigure()` release VRAM — no longer bears on anything we are building.

**The smallest true statement of our contribution:** tool-swap puts an eviction table above the container boundary, in a few hundred lines of pure policy, over Docker and FastAPI and BentoML — none of which we wrote. That is a modest claim, and it is the one to defend.

The pattern holds, with both corrections earned the hard way: **reuse the engine, own the contract** — *check the engine's manual before saying what it cannot do*, **and then ask what it costs to keep running.**

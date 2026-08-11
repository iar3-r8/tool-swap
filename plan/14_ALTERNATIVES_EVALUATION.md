# 14 — "Are we reinventing the wheel?" — an honest evaluation

> Raised by the requester: *"would it be simpler to use KServe in the end and less risky? I feel like we are reinventing the wheel."*
>
> This is the correct challenge to make before writing code, and it deserves a real answer rather than a defence of the plan.

> ## ✅ **THE GATE IS CLOSED — the answer is: build our own router**
>
> All three spikes in §6 were run or answered. **None produced a cheaper path.** Recorded in [ADR-0001](adr/0001-build-our-own-router.md).
>
> | Spike | Outcome |
> |---|---|
> | **C** — do the tools fit? | **No.** The swapping premise holds. |
> | **A** — llama-swap as router? | **No.** LLM/OpenAI-shaped; it cannot route `/predict`. |
> | **B** — KServe on k3s? | **No.** Kubernetes allocates rather than preempts, and preemption is required (**D25**). |
>
> **Read this document as the recorded reasoning, not as pending work.** It remains the place to check *why* before anyone proposes reopening the question — and §8 remains live, because it describes the growth path if a trigger in §8.6 ever fires.
>
> One thing changed since the analysis below was written: the deployment is a **shared DGX**, which makes Kubernetes fit *worse* than §2 estimated. Knative has no way to express "keep the pod, release the weights", and that is now our default reclamation mechanism ([ADR-0002](adr/0002-shared-node-soft-unload.md)).

---

## 1. Where the challenge is right

Let me concede the strong parts of the argument first, because they are strong.

1. **The core feature is not novel.** "Load a model on demand, unload it when idle" is scale-to-zero. KServe, Knative, Triton (explicit model control), Ollama, Docker Model Runner and llama-swap all implement a version of it. Nobody should be proud of inventing it again.
2. **The proxy is not novel either.** Path-based routing to a backend, with a readiness gate, is what every ingress does.
3. **A bespoke orchestrator has real ongoing costs** that are easy to under-count at planning time: the failure modes in [`01_ARCHITECTURE.md`](01_ARCHITECTURE.md) §11 are a to-do list that a mature system has already worked through, over years, against real production traffic.
4. **Bus-factor risk.** A tool maintained by one team is a liability the moment that team is busy. KServe outlives whoever set it up.
5. **My own plan says to prefer existing software (D12)** and then proceeds to build a router. That tension is fair to point at, and it needs a better answer than "but this bit is special".

So the question is not whether reuse is preferable in principle. It is: **does the reusable thing actually meet the four stated requirements, and is the total risk lower?**

---

## 2. What KServe actually requires

KServe is a Kubernetes-native model-serving stack. Concretely, adopting it means adopting:

| Layer | Why it is needed |
|---|---|
| **Kubernetes** | KServe is a set of CRDs and controllers; there is no non-Kubernetes mode. |
| **Knative Serving** (for scale-to-zero) | Scale-to-zero and request-buffering-while-cold come from Knative's activator, not KServe itself. The "Raw Deployment" mode avoids Knative but **also gives up scale-to-zero** — which is the one feature we actually came for. |
| **A service mesh or networking layer** | Istio, or Kourier for a lighter path. Another moving part with its own failure modes. |
| **`InferenceService` CRDs per model** | The model definition surface. |
| **A container registry** | Images must be pullable by the cluster. |
| **GPU device plugin + node labels/taints** | Same as any GPU Kubernetes setup. |
| **Cluster-level observability** | Prometheus/Grafana/Loki or equivalent; `kubectl logs` alone is not an ops story. |

On a **single research GPU box**, that stack is heavier than everything it is serving. And the operational surface a user must learn is `kubectl`, CRDs, Knative revisions, pod events, admission webhooks and mesh sidecars.

### 2.1 Scored against the four requirements

| Req | KServe | Verdict |
|---|---|---|
| **R1** simple to launch, check logs and status | `kubectl apply` + `kubectl get inferenceservice` + `kubectl logs <pod> -c kserve-container`. Debugging a model that will not start means reading pod events, init-container logs, Knative revision conditions, and possibly mesh config. There is no single command that says "GPU 0 is held by model X, TTL expires in 4 minutes". | **Fails as stated.** Achievable only by building a status/CLI layer on top — i.e. building part of tool-swap anyway. |
| **R2** easy to add a model; code and environment easy to set up | Two paths. (a) A **serving runtime** (sklearn/xgboost/triton/HF) — genuinely excellent *if* your model fits a supported runtime; you point at a model artefact and you are done. (b) A **custom predictor** — you write a Dockerfile, implement a `kserve.Model` class, build, push to a registry, then write an `InferenceService` YAML. Our target user is a scientist with a `requirements.txt` and a `load()`/`predict()` function. | **Partial.** Path (a) is better than anything we would build, for the models it covers. Path (b) is materially harder than three files and `tswap build`, and demands registry access and Kubernetes literacy. |
| **R3** a proxy to all services | Yes — this is a genuine strength. Ingress, routing, canary traffic splitting, an inference protocol (V2/Open Inference Protocol). | **Wins.** |
| **R4** simple to configure | `InferenceService` YAML per model plus Knative annotations for scale-to-zero and timeouts. Not a five-line file, and the knobs are spread across CRDs, annotations and cluster config. | **Fails as stated**, though it is *standard* complexity rather than *bespoke* complexity — which has real value. |

### 2.2 Two specific technical mismatches worth knowing

- **Scale-to-zero is per-pod, and cold start includes pod scheduling and image pull.** For a 20 GB image on a research box this can be far worse than starting a local container. Our cold-start mitigations (a warm local image cache, a shared weights mount, `tswap warm`) are things you would have to reproduce anyway with node-local caching and pre-pull DaemonSets.
- **Knative's concurrency-based autoscaling is not a GPU-slot scheduler.** Our central primitive — "at most N models resident in this group, evict LRU to make room" ([`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](06_LIFECYCLE_TTL_AND_SCHEDULING.md)) — has no direct KServe equivalent. Kubernetes GPU scheduling is *allocation* (a pod requests `nvidia.com/gpu: 1` and waits for a free device), not *eviction to make room for a more urgent model*. With `max_resident: 1` on a single GPU, a second model's pod simply stays `Pending` forever; nothing evicts the incumbent. You would need a custom controller or priority/preemption classes plus a graceful-shutdown path — which is, again, writing the interesting part ourselves.

**The honest counterpoint, now settled.** This section originally noted: *"if `Pending`-until-free is acceptable behaviour (requests queue rather than swap), a lot of that complexity evaporates. Whether 'swap' or 'wait' is the required semantic is worth confirming — it is the crux of whether Kubernetes fits."*

**It was confirmed, and the answer is "swap":** *"We don't want to wait for TTL as it could take quite some time, if another process is not being used right now we want to stop it and warm up any process that has a request"* (**D25**). The crux resolved against Kubernetes.

**A second mismatch appeared later and is arguably worse.** On our shared DGX the default reclamation mechanism is soft unload — keep the container, release the weights ([ADR-0002](adr/0002-shared-node-soft-unload.md)). Knative has no representation for that state: a pod is up or it is down. This is a disagreement at the level of primitives rather than configuration, and no amount of tuning reconciles it.

---

## 3. The other serious reuse candidates

KServe is not the only alternative, and two of the others score better against the actual requirements.

### 3.1 llama-swap — the closest existing thing, and already our neighbour

**First, a distinction that must not be blurred.** llama-swap has *two* possible relationships to this project:

1. **As our sibling** — it already serves our LLMs in a separate deployment. That is settled, and it is why tool-swap has no OpenAI-compatible API ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §0).
2. **As our router** — could the same software also schedule our *algorithm* containers, replacing the router we would otherwise build? That is the open question Spike A answers, and it is independent of role 1. A "no" changes nothing about its LLM duties.

It already does: YAML config, on-demand start, TTL, groups, an OpenAI front door, a `/upstream/{model}` proxy, a status UI. A single Go binary. It is the acknowledged inspiration.

**The specific risk for role 2 — and the outcome.** The risk was stated in advance as: *"its request path is shaped around OpenAI endpoints, whereas our tools speak `/predict` with an arbitrary JSON body. If its proxy is protocol-agnostic it works for us; if it parses `body.model` or assumes chat semantics, it does not. This is the single fact the decision turns on."*

> **❌ Spike A result: it is OpenAI/LLM-only.** The fact the decision turned on came back negative. llama-swap cannot be our router.

**Role 1 is untouched.** It continues to serve our LLMs in a separate deployment, exactly as [`04_API_CONTRACT.md`](04_API_CONTRACT.md) §0 assumes. The two roles were always independent; only the router role is refused.

**What it does not do:** manage *containers* with per-model environments (it spawns processes/commands), or provide a generic model-authoring story with batching. But note carefully — a configured llama-swap command can be `docker run ...`. That single observation makes the following genuinely viable:

> **Use llama-swap as the router, where each model's command is `docker run` of that model's image, and our contribution is only the authoring/build layer plus the runtime with batching.**

This deletes the scheduler, the proxy, the TTL watchdog, the state machine and the status UI from our scope — the majority of the code in [`08_REPO_LAYOUT.md`](08_REPO_LAYOUT.md). It deserves a spike (§6) because if it works it is dramatically cheaper than either alternative.

Risks to test: whether groups/TTL semantics work correctly when the managed process is `docker run` (does killing the client process reliably stop the container? use `--rm` and signal forwarding, or `docker start/stop`?); whether readiness gating is configurable per model; whether it can express "wait vs evict"; and how it reports errors from a container that fails to start.

### 3.2 Triton with explicit model control

`--model-control-mode=explicit` plus the load/unload API *is* our TTL feature, with excellent dynamic batching and a mature protocol. **Rejected as the core for one reason:** Python-backend models share the Triton process and its environment, so per-model dependency isolation (**D2** — the requirement that torch and TensorFlow models stop fighting) requires custom conda-pack stub environments per model. That is a real feature of Triton, but it is a harder authoring story than three files, and it is precisely the complexity we are trying to remove. Triton remains an excellent `external` backend for models that suit it.

### 3.3 Ray Serve

Multi-model, `@serve.batch`, per-deployment resources, model multiplexing with LRU eviction — genuinely close to our semantics. Rejected because per-deployment environment isolation via `runtime_env` is fragile for native/CUDA stacks (it is a pip/conda layer, not a container boundary), Ray is heavy, and R8's own Ray attempt stalled ([`12_REFERENCE_CODE.md`](12_REFERENCE_CODE.md) §8). Worth a second look if the container boundary is ever relaxed.

---

## 4. Side-by-side

Scored for **this** context: one or two GPU hosts, a research team, ~20 heterogeneous models with mutually incompatible dependencies, non-expert model authors.

| | **KServe** | **llama-swap + our build layer** | **tool-swap as planned** |
|---|---|---|---|
| Prerequisites on the host | Kubernetes + Knative + mesh + registry | Docker + one binary | Docker |
| Code we own | An ops/status/CLI layer, plus a controller for eviction semantics | Build layer + runtime + a thin CLI | Router + scheduler + runtime + build + CLI |
| Per-model env isolation | Yes (containers) | Yes (containers) | Yes (containers) |
| Group/eviction semantics ("swap") | Not natively; needs a controller or preemption design | Native (groups + TTL) | Native, by design |
| Scale-to-zero / TTL | Yes (via Knative) | Yes | Yes |
| Micro-batching | Yes, in supported runtimes | Ours | Ours |
| **R1** launch/logs/status | Weak without extra work | Good (`/ui`, one binary) | Best (purpose-built) |
| **R2** add a model | Great for standard runtimes; heavy for custom | Good | Best |
| **R3** proxy | Best | Good | Good |
| **R4** simple config | Weak | Good | Best |
| Bus factor / longevity | Best | Medium (single-maintainer OSS, but small and forkable) | Worst |
| Scales to multi-host | Yes, natively | No | No |
| Total risk **in this context** | **Medium-high** (adoption + operational + a custom controller anyway) | **Low-medium** | **Medium** |

---

## 5. Recommendation — *as written before the spikes, retained for the reasoning*

> **Outcome:** the recommendation below was followed. Spike C ran first, then A; both failed, and B was answered on the record. **We build our own router** ([ADR-0001](adr/0001-build-our-own-router.md)). Point 3 is the one the evidence overturned: the challenge *did* land on the router, and llama-swap turned out not to be able to take it.

**Do not adopt KServe now. Spike llama-swap-as-router before committing to building our own router.**

Reasoning:

1. **KServe solves a problem we do not yet have** (multi-tenant, multi-host, cluster-scale serving) at the cost of the problem we do have (**R1** and **R4** — simplicity of launching, configuring and diagnosing on a single box). Adopting Kubernetes to serve twenty models on one DGX inverts the complexity budget.
2. **KServe would not even remove the interesting work.** We would still write a status/CLI layer for **R1**, an authoring/build layer for **R2**, and — because Kubernetes allocates rather than evicts — something custom for the swap semantics. We would trade "code we own" for "code we own **plus** a cluster to operate".
3. **But the challenge lands on the router.** The router (scheduler + TTL + proxy + status) is the largest single chunk of our scope and the part with the closest existing substitute. If llama-swap can drive `docker run` commands with per-model TTL and groups, we should use it and keep only the parts that are genuinely ours: **the graduated-complexity build layer (R2) and the batching runtime (D5)**. Those are the pieces no existing tool provides for this use case.
4. **Revisit KServe at a real trigger**, not on principle: a second GPU host, multi-tenant isolation requirements, or an infrastructure team that already runs Kubernetes. Then it becomes the right answer, and this plan's tool directories port to it because a tool image is already a valid custom predictor. Section 8 works that migration through in detail: what ports unchanged, what is thrown away, and the two things that must genuinely be rebuilt.

The intellectually honest framing of the project: **tool-swap's value is the authoring UX and the swap semantics, not the HTTP plumbing.** Everywhere the plumbing can be borrowed, borrow it.

---

## 6. The de-risking spikes — ✅ **EXECUTED**

> **All three are resolved. Do not re-run them.** The outcomes are recorded in [ADR-0001](adr/0001-build-our-own-router.md); the procedures below are kept so that anyone reopening the question knows exactly what was asked, and so a future re-evaluation can be compared like for like.

| Spike | Result | Basis |
|---|---|---|
| **C** | ❌ Failed | The tools do not all fit on the GPUs simultaneously. |
| **A** | ❌ Failed | llama-swap is built for LLM/OpenAI-compatible endpoints; our tools are custom models speaking `/predict`. |
| **B** | ❌ Failed, answered without standing up a cluster | Preemption is required (**D25**) and Kubernetes does not provide it; soft unload (**D9**) has no Knative representation. Minikube separately unsuitable. |

### Spike A — llama-swap driving containers ❌
1. Install llama-swap. Configure two models whose commands are `docker run --rm -p ...` of two trivially different images (`example_echo` at two ports).
2. Verify: on-demand start on first request; TTL stops it; **the container actually dies** (no orphan — check `docker ps`); `groups` with one member resident forces alternation; the `/upstream/{model}/...` proxy reaches the container; the status UI reflects reality.
3. Probe the failure modes: a container that fails to start; one that never becomes ready; a request arriving mid-swap; killing llama-swap while containers run.
4. Record: which of our required semantics are expressible in its config, and which are not.

**Decision rule:** if steps 2–3 pass, adopt llama-swap as the router and cut the scheduler/proxy/watchdog/status work from the plan. Our repo becomes the build layer + runtime + a thin CLI that generates llama-swap config from `tools.yaml`. If they fail, we have concrete evidence for building, recorded in an ADR.

> **Outcome:** it did not get as far as step 2. The proxy is shaped around OpenAI endpoints and cannot forward an arbitrary `/predict` body, so the premise of the spike — that a `docker run` command could be driven behind a protocol-agnostic proxy — does not hold. Evidence recorded; we build.

### Spike B — KServe reality check ❌
1. On a single-node k3s with Knative and a GPU: deploy one **custom predictor** end-to-end, from Dockerfile to a served request, with `minReplicas: 0`.
2. Measure cold start honestly (including image pull and pod scheduling).
3. Attempt the swap semantic: two models, one GPU, `max_resident: 1`. Observe what happens to the second pod. Determine whether "wait" is acceptable or whether preemption must be built.
4. Time how long it takes a **non-Kubernetes colleague** to add a second model and to diagnose a deliberately broken one. That is the real **R1**/**R2** measurement, and it is the number that should decide.

> **Outcome:** not run, and deliberately so. Step 3 — *"attempt the swap semantic: two models, one GPU, `max_resident: 1`; observe what happens to the second pod; determine whether 'wait' is acceptable or whether preemption must be built"* — was answered directly by the requirement in **D25**: waiting is not acceptable. Kubernetes leaves the second pod `Pending`, so preemption would have to be built on top of a cluster we would also have to operate. Standing up k3s to confirm a documented behaviour would have cost days to reach a conclusion already available.
>
> **Also note:** minikube was raised as a lighter alternative and rejected on its own terms — host-built images are invisible to the cluster (a `minikube image load` of a multi-gigabyte image after every `tswap build`, straight into **R2**), and GPU support is the experimental docker-driver path, which fits badly with per-device pinning (**D7**).

### Spike C — the honest "do nothing new" baseline ❌
Before either: measure how far a plain `docker compose` file with all models running permanently gets us. If the GPUs actually fit the real working set, **the entire swapping premise is unnecessary** and the right answer is compose plus the build layer. Check this first; it is the cheapest possible outcome and it would be embarrassing to discover it in month three.

> **Outcome:** they do not fit. The cheapest possible result is unavailable, and the swapping premise — with it, the whole project — is justified. Everything downstream (groups, TTL, eviction, cold-start handling) is load-bearing rather than speculative.

---

## 7. If we build anyway — how to stay cheap and reversible

Constraints that keep the "we own too much code" risk bounded:

- **Keep the scheduler pure and small** ([`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](06_LIFECYCLE_TTL_AND_SCHEDULING.md) §9). It is a few hundred lines of decidable logic, not a distributed system.
- **Never write inference infrastructure at all.** This constraint got stronger with **D14**: the in-container runtime is BentoML, so we do not write a batcher, a dispatcher or a server loop — only the handler protocol, the schema, the lifecycle and the contract. We host no third-party *model servers* (**D4b**), but we happily reuse a *serving framework* inside our own images; those are different things, and conflating them is what produced the earlier "write our own batcher" recommendation.
- **Keep the runtime backend behind a seam** ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §2). Reusing BentoML is reversible precisely because nothing above the seam knows about it. That is the same hedge as `ContainerBackend`, applied one level down.
- **Keep the tool definition portable by design.** A tool is an OCI image with an HTTP server, which is already a valid KServe custom predictor, a valid llama-swap target and a valid compose service. **This is the key hedge: the tools are the durable asset, the router is replaceable.** Write it down as an explicit design constraint, test that an image runs standalone under plain `docker run`, and keep the wire protocol inside the runtime adapter so a second one can be added without touching a single handler. Section 8 sets out exactly what this buys and what it does not.
- **Behind an interface**: `ContainerBackend` already abstracts the runtime; a future `KubernetesBackend` is a new implementation, not a rewrite.
- **Set an exit trigger now**: a second GPU host, or more than ~two people needing isolation, means re-evaluating Kubernetes rather than extending tool-swap.

---

## 8. The growth path: how we would move to KServe later

> *"Will we be able to evolve easily to a more KServe-ish style if needed? Is it realistic to take this path?"*

**Yes, and the honest framing is that we would *replace the router*, not migrate it.** The move is realistic precisely because the split between what survives and what does not is decided in advance, and it is not an even split.

### 8.1 What ports unchanged

These are the durable assets, and they represent the majority of the effort:

| Asset | Why it survives |
|---|---|
| **The tool image** | A KServe custom predictor (bring-your-own-container) is defined as *an OCI image serving HTTP inference on a configurable port with a readiness endpoint*. That is exactly guardrail 11's definition of a tool image. Nothing to rewrite. |
| **In-container batching** | The BentoML dispatcher lives *inside* the image, so it travels with it. A design that had put batching in the platform would have to surrender it and inherit whatever the platform offers instead. |
| **The handler protocol** | `load()` / `predict()` / `unload()` imports nothing of ours, and nothing of any platform's. |
| **The compiled JSON Schema and `?format=tools`** | Agent-facing discovery is orthogonal to the orchestrator. It would be re-hosted, not redesigned. |
| **The authoring ladder and `tswap preflight`** | Both operate on a tool directory and Docker; neither knows a router exists. This matters, because **the authoring UX is the part KServe never provided**, so it is exactly the part we would still want afterwards. |

### 8.2 What is mechanically convertible

`tools.yaml` is a superset of what an `InferenceService` needs, and the mapping is close to field-for-field:

| `tools.yaml` | KServe equivalent |
|---|---|
| `image` | `predictor.containers[0].image` |
| `devices: [0]` | `resources.limits."nvidia.com/gpu": 1` plus node selection |
| `env`, `mounts` | `env`, `volumeMounts` |
| `ttl` | Knative `scale-to-zero-grace-period` |
| `keep_warm` | `minReplicas: 1` |
| `ready_timeout` | readiness probe `failureThreshold` x `periodSeconds` |
| `group` / `max_resident` | **no equivalent**, see 8.4 |

A generator emitting `InferenceService` manifests from `tools.yaml` is a small piece of work. **We are not building it now**: writing an exporter for a platform nobody has stood up is precisely the speculative work this document argues against. The point is only that the information already exists, in the right shape, whenever someone wants it.

### 8.3 What is discarded rather than migrated

The router, the scheduler, the TTL watchdog, the proxy, the status page and most of the CLI. Their responsibilities pass to Knative, the Kubernetes scheduler, the ingress, and `kubectl` plus a monitoring stack.

State this without euphemism: **a substantial part of what we build would be deleted.** That is acceptable only because it is also the part that is cheapest to rebuild elsewhere and least valuable to own, the plumbing rather than the contract. It is section 5's conclusion, seen from the other end of the project's life.

### 8.4 The two things that must genuinely be rebuilt

1. **Eviction.** Kubernetes *allocates* devices and leaves the second pod `Pending`; it does not evict an incumbent to make room (section 2.2). Reproducing "swap" needs priority and preemption classes plus a graceful-shutdown path, or a small custom controller. **This is the hardest part of any migration, and it is the same work we would be doing here anyway**, which is worth noticing: the design effort is not wasted even if the platform changes.
2. **The wire protocol.** KServe consumers expect the Open Inference Protocol (`/v2/models/{name}/infer`), whereas our tools speak `/predict`. Adding a V2-shaped route is genuinely additive **provided the protocol never leaks into handlers**, which is what the invariants below protect.

### 8.5 The invariants that keep this cheap, and what we deliberately do not build

The insurance is free, because every item is something we want for its own sake:

- **A tool image runs standalone under plain `docker run`** (guardrail 11), proven per-tool by `tswap preflight` (**D17**) rather than asserted by a test nobody runs. This single property is what makes a tool image simultaneously a valid compose service, a valid llama-swap target, a valid tool-swap tool and a valid KServe predictor.
- **The wire protocol lives in the runtime adapter, never in `handler.py`.** The author writes `predict()`; the adapter decides what HTTP looks like. A second protocol is therefore an adapter change, not a zoo-wide migration.
- **Port and readiness path are read from the environment**, never hardcoded, so a platform that dictates them can.
- **A handler imports nothing of ours beyond a metadata decorator**, so it stays portable even if the runtime does not.

**Explicitly not built in v1:** no manifest exporter, no Open Inference Protocol route, no Kubernetes backend, and no abstraction layer anticipating one. Those are written when a trigger fires, against the platform's real constraints rather than our guesses about them.

### 8.6 The trigger

Re-evaluate deliberately, rather than drifting, when one of these becomes true:

- a **second GPU host** is added, making single-box scheduling insufficient;
- **multi-tenant isolation** becomes a requirement, meaning more than about two parties who must be kept apart;
- an **infrastructure team already operating Kubernetes** takes on the deployment, which changes the operational cost calculation entirely.

Absent one of those, adopting Kubernetes to serve twenty models on one box inverts the complexity budget (section 5). **The models are the durable asset; the router is replaceable.** Protecting that property is the whole of the strategy, and today it costs nothing.

---

## 9. Summary answer to the question

*Would KServe be simpler and less risky?*

**Simpler: no**, not on a single GPU box, and not against **R1** and **R4** as stated. It replaces bespoke complexity with standard complexity — valuable, but a larger absolute amount of it, and it would not remove the authoring layer, the status layer, or the swap semantics we would still have to build.

**Less risky: partly yes** — on longevity and bus factor, KServe clearly wins, and that matters more than it feels like it does today. It is the right destination if this becomes multi-host or multi-tenant.

*Are we reinventing the wheel?* **For the router, quite possibly — and that is worth two days to find out.** For the **batching runtime, we were about to** — and **D14** stopped it: BentoML's dispatcher is the wheel, and we now turn it instead of carving one ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §1). What remains genuinely ours is the **authoring ladder** and the **uniform contract**: nothing off the shelf takes a scientist's `requirements.txt` and a heterogeneous zoo and produces an agent-callable tool. Run Spike C, then Spike A, then decide with evidence rather than with either of our instincts.

The pattern worth naming, since it now applies twice: **reuse the engine, own the contract.** BentoML serves inside the container, Docker runs the containers, llama-swap may yet route them — and in each case what we keep is the thin layer that makes the zoo uniform, discoverable and safe. Every time we caught ourselves about to write infrastructure, the better answer was a seam plus somebody else's implementation.

# ADR-0001 — Build our own router

- **Status:** Accepted
- **Date:** 2026-08-11
- **Resolves:** [`13_OPEN_QUESTIONS.md`](../13_OPEN_QUESTIONS.md) Q1 — *"Should we build a router at all, or reuse one?"*
- **Gate:** M−1 in [`09_IMPLEMENTATION_PLAN.md`](../09_IMPLEMENTATION_PLAN.md); spikes specified in [`14_ALTERNATIVES_EVALUATION.md`](../14_ALTERNATIVES_EVALUATION.md) §6
- **Supersedes:** the recommendation in [`14_ALTERNATIVES_EVALUATION.md`](../14_ALTERNATIVES_EVALUATION.md) §5 ("spike llama-swap before committing to building a router"), which is now executed rather than pending

---

## Context

The requester challenged the plan before any code was written: *"would it be simpler to use KServe in the end and less risky? I feel like we are reinventing the wheel."*

That challenge was taken seriously enough to become a gate. [`14_ALTERNATIVES_EVALUATION.md`](../14_ALTERNATIVES_EVALUATION.md) §6 defined three timeboxed spikes whose purpose was explicitly to **avoid** building a router, in descending order of how much work each would save:

| Spike | Question | Saving if it passed |
|---|---|---|
| **C** | Do all the tools simply fit on the GPUs at once? | The entire swapping premise. Ship `docker compose` plus the build layer and stop. |
| **A** | Can llama-swap be the router, each tool's command being `docker run`? | The scheduler, proxy, TTL watchdog, state machine and status UI. |
| **B** | Is KServe on single-node Kubernetes the answer? | The router, in exchange for operating a cluster. |

The instruction attached to the gate was unambiguous: *"We would rather you delete two thirds of this plan on evidence than implement it faithfully because it was written down"* ([`HANDOFF.md`](../HANDOFF.md) §2).

## Decision

**Build our own router**, as described from M0 onward in [`09_IMPLEMENTATION_PLAN.md`](../09_IMPLEMENTATION_PLAN.md).

All three spikes were run or answered. None of them produced a cheaper path.

## Evidence

### Spike C — the models do not fit

Reported outcome: **they do not all fit on the GPUs simultaneously.**

This was the cheapest possible result and it is gone. The swapping premise holds, and with it the reason the project exists. Everything downstream — groups, TTL, eviction, cold-start handling — is therefore load-bearing rather than speculative.

### Spike A — llama-swap cannot route our tools

Reported outcome: **llama-swap is built for LLMs and OpenAI-compatible endpoints only; we need custom models.**

This confirms the exact risk §3.1 identified in advance:

> *"its request path is shaped around OpenAI endpoints, whereas our tools speak `/predict` with an arbitrary JSON body. If its proxy is protocol-agnostic — routing on the model name and forwarding the body untouched — it works for us. If it parses `body.model` or assumes chat semantics, it does not. Establish this early in the spike; it is the single fact the decision turns on."*

It parses OpenAI-shaped requests. The fact the decision turned on came back negative.

**This does not affect llama-swap's other role.** It continues to serve our LLMs in a separate deployment, which is why tool-swap has no OpenAI-compatible API ([`04_API_CONTRACT.md`](../04_API_CONTRACT.md) §0). §3.1 anticipated this distinction: *"A 'no' here does not affect its LLM role."* The two roles were always independent, and only the router role is refused.

### Spike B — answered on the record, not run

Spike B became live precisely because A failed. It was answered without standing up a cluster, because a requirement stated during this session settles it more directly than a measurement would.

**The requirement, verbatim:**

> *"We don't want to wait for TTL as it could take quite some time, if another process is not being used right now we want to stop it and warm up any process that has a request."*

That is **preemption** — displacing an idle-but-not-yet-expired incumbent on demand — and it is the one semantic Kubernetes does not provide:

- Kubernetes **allocates** devices. A second pod requesting a GPU that is held goes `Pending` and stays there until the incumbent leaves of its own accord. It does not evict an incumbent to make room ([`14_ALTERNATIVES_EVALUATION.md`](../14_ALTERNATIVES_EVALUATION.md) §2.2).
- Knative's scale-to-zero *would* eventually release the GPU, but only after the idle grace period elapses — which is exactly the wait the requirement rules out. §2.2 left this open (*"if `Pending`-until-free is acceptable behaviour, a lot of that complexity evaporates"*); the requirement closes it as unacceptable.
- Reproducing preemption on Kubernetes therefore needs priority/preemption classes plus a graceful-shutdown path, or a small custom controller ([`14_ALTERNATIVES_EVALUATION.md`](../14_ALTERNATIVES_EVALUATION.md) §8.4).

So the KServe path is: stand up k3s + Knative + a networking layer + a registry, **and then still write the preemption logic**, because the single semantic we most need is the one the platform lacks. That is a cluster to operate *in addition to* the interesting code, rather than instead of it.

A second consideration reinforces it. ADR-0002 promotes **soft unload** — keep the container, release the weights — to the default reclamation mechanism. Knative has no representation for that state at all: a pod is up or it is down. The deployment target's shape and the platform's model disagree at the level of primitives, not configuration.

### Minikube — separately unsuitable

Raised during the session as a possible simplification: *"could it be simpler to use kserve on a single node and simply setup minikube to handle the containers"*. Rejected on its own merits, independent of the argument above:

- **Host-built images are invisible to the cluster.** Minikube's usual driver runs the kubelet inside a container, so every `tswap build` would need `minikube image load` of a multi-gigabyte image. That friction lands directly on **R2**, the requirement the whole authoring ladder exists to serve.
- **GPU support is the experimental path** — docker driver with `--gpus all` — which sits badly with per-device pinning under **D7**.

[`14_ALTERNATIVES_EVALUATION.md`](../14_ALTERNATIVES_EVALUATION.md) §6 already specified k3s rather than minikube for the spike, for these reasons. If Kubernetes is ever revisited, it is k3s + Knative + Kourier, single node.

## Consequences

### Accepted

- **The full router scope returns**: M2 (backend and lifecycle), M3 (proxy), M6 (TTL, groups, eviction), M7 (observability) and M8 (CLI) are all in scope. Nothing is deleted from [`09_IMPLEMENTATION_PLAN.md`](../09_IMPLEMENTATION_PLAN.md).
- **We own the failure modes** in [`01_ARCHITECTURE.md`](../01_ARCHITECTURE.md) §11, and the bus-factor risk §1 of the evaluation names honestly.

### Bounded by

The constraints in [`14_ALTERNATIVES_EVALUATION.md`](../14_ALTERNATIVES_EVALUATION.md) §7 stand and are now load-bearing rather than precautionary:

- the scheduler stays **pure and small** ([`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](../06_LIFECYCLE_TTL_AND_SCHEDULING.md) §9);
- we write **no inference infrastructure** — BentoML serves inside the container (**D14**);
- **a tool image runs standalone under plain `docker run`** (guardrail 11), proven per-tool by `tswap preflight` (**D17**);
- the wire protocol lives in the runtime adapter, never in `handler.py`.

### The hedge that survives

**The tools are the durable asset; the router is replaceable.** Every tool image remains a valid KServe custom predictor, a valid compose service and a valid llama-swap target. [`14_ALTERNATIVES_EVALUATION.md`](../14_ALTERNATIVES_EVALUATION.md) §8 works through what a later migration would keep and what it would discard.

Worth noticing: the preemption logic we now write is *the same work* a Kubernetes migration would require (§8.4). The design effort is not wasted even if the platform changes.

## Revisit when

The triggers in [`14_ALTERNATIVES_EVALUATION.md`](../14_ALTERNATIVES_EVALUATION.md) §8.6, unchanged by this decision:

- a **second GPU host** is added, making single-box scheduling insufficient;
- **multi-tenant isolation** becomes a requirement — more than about two parties who must be kept apart;
- an **infrastructure team already operating Kubernetes** takes on the deployment.

Note that the deployment target is a *shared* DGX (ADR-0002), which means other tenants already exist on the node. That is not the same as us needing to isolate tenants *within* tool-swap, and it does not fire the second trigger — but it is close enough to the boundary to be worth re-reading this ADR if our share of the node ever grows to serve more than one team.

## Notes

Recorded because the gate asked for the reasoning to be written down whichever way it went: *"Record the outcome as an ADR either way — the reasoning matters more than the choice"* ([`13_OPEN_QUESTIONS.md`](../13_OPEN_QUESTIONS.md) Q1).

The honest summary is that the challenge was correct to make and the answer survived it. Every cheaper option was tested rather than dismissed, and each failed for a specific, recorded reason. The plan asked to be talked out of building a router; it could not be.

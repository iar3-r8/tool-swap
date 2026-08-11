# HANDOFF — read this first

> **What this is:** a complete design plan for a new, standalone project called **tool-swap**, written to be built by a team that has never seen the system it was extracted from.
>
> **What it is not:** a specification handed down to be implemented literally. It is a set of decisions with the reasoning attached, so that you can tell which parts are load-bearing and which are merely our best guess.

---

## 1. What tool-swap is, in one paragraph

A small self-hosted service that **hosts a zoo of LLM-callable tools and serves them over HTTP**, starting each tool on demand and stopping it when idle, so that a handful of GPUs can serve far more tools than would fit in VRAM at once. Each tool is a container with its own Python environment, because the tools in question have mutually incompatible dependencies (one needs PyTorch, another TensorFlow, and they cannot coexist in one interpreter). ML models are one kind of tool; pure CPU functions are another.

It is directly inspired by [`llama-swap`](https://github.com/mostlygeek/llama-swap), which does the same for `llama.cpp` servers.

**It does not serve LLMs.** That is llama-swap's job, in a separate deployment. This distinction shapes the whole API surface, so it is worth absorbing before reading further.

---

## 2. The gate has been run — you may start at M0

**There was a gate, and it was not a formality.** [`14_ALTERNATIVES_EVALUATION.md`](14_ALTERNATIVES_EVALUATION.md) §6 defined three timeboxed spikes, each designed to let us *avoid* building a router. **All three failed**, so the build-our-own branch is live:

| Spike | Question | Outcome |
|---|---|---|
| **C** | Do all the tools simply fit on the GPUs at once? | **No.** Swapping is genuinely required. |
| **A** | Can **llama-swap** act as the router, with each tool's command being `docker run`? | **No.** It is LLM/OpenAI-shaped; it cannot route `/predict`. It keeps serving our LLMs separately. |
| **B** | KServe on single-node Kubernetes? | **No.** Kubernetes allocates and never preempts; we would run a cluster *and* still write the preemption logic. |

Recorded in **[ADR-0001](adr/0001-build-our-own-router.md)**. **Do not re-run them** — but do read the ADR before proposing that we should have.

**Two requirements came out of that gate and shape the design**, both in **[ADR-0002](adr/0002-shared-node-soft-unload.md)**:

1. **Preemption** — a request displaces an idle incumbent immediately rather than waiting out its TTL (**D25**).
2. **A shared DGX** — other tenants use the same GPUs. So **soft unload is the default reclamation mechanism** (**D9**, reversed from its original phase-2 position), and a reload that fails because a neighbour took the memory is **not** a tool failure (**D28**).

The sentiment behind the gate still applies to everything else here: we would rather you delete a chunk of this plan on evidence than implement it faithfully because it was written down.

---

## 3. What is decided, and what is not

**Decided:** twenty-eight decisions, D1–D28, each with its reasoning, in [`13_OPEN_QUESTIONS.md`](13_OPEN_QUESTIONS.md) Part A. The ones that shape everything else:

- **D2** — one container image per tool. This is the non-negotiable core; §21 of the reference document is the evidence for why.
- **D14** — the in-container runtime is BentoML, behind our own contract. We write no batcher.
- **D13** — schemas are JSON Schema, projected into standard tool definitions. This is the integration surface for agents.
- **D17** — `tswap preflight` is how a tool author finds out whether their tool will actually deploy.
- **D9 / D25 / D28** — the shared-node trio: soft unload by default, preemption on demand, and a neighbour's VRAM usage never marking our tool broken.

**Genuinely open:** three items, in [`13_OPEN_QUESTIONS.md`](13_OPEN_QUESTIONS.md) Part B — Q1, the gating question, is now closed. Each remaining item has a recommended default and a milestone by which it must be settled. None blocks a start.

**Deliberately parked:** Part C lists ideas that were considered and set aside, with the reason. Consult it before re-inventing one as if new.

**Guardrails:** Part D lists thirteen things that must not be "improved" without a fight. They are there because each one is a decision that looks arbitrary until the day it saves you. The most important is number 5: **batch result attribution is safety-critical** — this is a healthcare context, and a misattributed result means one patient's answer returned for another.

---

## 4. Reading order

Do not read these in file order. Read them in this order:

1. **[`README.md`](README.md)** — what we are building, the vocabulary, and the decision table. Includes a note explaining the "R8" references you will see throughout.
2. **[`00_CONTEXT_AND_MOTIVATION.md`](00_CONTEXT_AND_MOTIVATION.md)** — where this comes from and what went wrong there. This is the *why*, and skipping it makes several later decisions look arbitrary.
3. **[`14_ALTERNATIVES_EVALUATION.md`](14_ALTERNATIVES_EVALUATION.md)** — the honest "are we reinventing the wheel?" evaluation, the spikes, and the growth path to Kubernetes. **Read before committing to build.**
4. **[`01_ARCHITECTURE.md`](01_ARCHITECTURE.md)** through **[`08_REPO_LAYOUT.md`](08_REPO_LAYOUT.md)** — the design proper, each assuming the previous.
5. **[`09_IMPLEMENTATION_PLAN.md`](09_IMPLEMENTATION_PLAN.md)** and **[`10_TESTING_STRATEGY.md`](10_TESTING_STRATEGY.md)** — milestones in TDD order, and how to test each.
6. **[`12_REFERENCE_CODE.md`](12_REFERENCE_CODE.md)** — reach for this when a claim seems unsupported, or when a milestone says "port this".
7. **[`13_OPEN_QUESTIONS.md`](13_OPEN_QUESTIONS.md)** — when a detail is ambiguous, check here before guessing.

[`11_R8_CLIENT_PLAN.md`](11_R8_CLIENT_PLAN.md) is **not your scope**: it describes later work in the originating repository, by that team. It is included so the eventual integration is designed rather than improvised.

---

## 5. How to read the plan critically

Some honest guidance on where to trust this document and where to push back.

**Trust it most on:**
- **The problem statement.** Everything in [`00_CONTEXT_AND_MOTIVATION.md`](00_CONTEXT_AND_MOTIVATION.md) §3 and [`12_REFERENCE_CODE.md`](12_REFERENCE_CODE.md) §20–21 is observed fact with the code attached, not conjecture.
- **The failure modes.** The regression tests in [`10_TESTING_STRATEGY.md`](10_TESTING_STRATEGY.md) §10 each exist because something specific went wrong. They are institutional memory.

**Push back on:**
- **Anything about performance.** No numbers here were measured on the target hardware. Cold-start times, batch sizes and TTL defaults are guesses that should be replaced with measurements.
- **The CLI surface.** It is designed, not user-tested. If `tswap status` does not answer the question an operator actually asks, change it.
- **Milestone granularity.** The sequence matters (spine first, then depth); the exact boundaries do not.

**Tell us if:**
- A decision's stated rationale does not match what you find in practice. The reasoning is recorded precisely so it can be challenged on evidence.
- The five-line minimal config stops being five lines. That is guardrail 10, and it is the canary for the whole "simple to configure" requirement.

---

## 6. What to ask us about

Things this document cannot tell you, where a conversation will be faster than inference:

| Topic | Why you may need to ask |
|---|---|
| **The real workload** — how many tools, sizes, request rates, concurrency | Still needed to set `soft_ttl`/`ttl` defaults and size the groups, though Spike C has already established that the tools do not all fit. |
| **The GPU hosts** — count, VRAM, driver and CUDA versions, **and how much of the shared DGX is ours versus other tenants** | Constrains base images and determines how aggressive the soft sweep should be. The tenancy split is the new question: it decides whether releasing VRAM promptly is a courtesy or a necessity. |
| **Which tools to port first** | The plan suggests the TensorFlow/Keras one, because it is the one that was structurally broken before. Confirm it is still relevant. |
| **The consuming agent setup** | `?format=tools` is the integration surface (**D13**); its acceptance test needs a real LLM deployment to run against. |
| **Weights and data locations** | **D18** assumes shared mounts in v1 and object storage later; the actual storage arrangement determines how soon "later" is. |

---

## 7. What success looks like

From [`00_CONTEXT_AND_MOTIVATION.md`](00_CONTEXT_AND_MOTIVATION.md) §6, restated because it is the acceptance criterion for the whole project:

1. A new user, on a fresh GPU box, can clone the repo, copy the example config, run `tswap up`, and call a tool that starts on demand and stops itself later.
2. A scientist can add a tool by creating **one directory with three files** (`tool.yaml`, `handler.py`, `requirements.txt`), running `tswap build`, and having it appear in `/tools` — without touching the router's code, its environment, or any Dockerfile.

If both are true, the project has succeeded, whatever the internals look like.

---

## 8. The one-sentence summary

**The tools are the durable asset; the router is replaceable** — so keep every tool image runnable under plain `docker run`, and be willing to throw away the rest.

# 13 — Decisions, Open Questions and Alternatives

> Three parts: **decisions already made** (with the reasoning, so they can be revisited honestly rather than accidentally), the few **genuinely open questions** (each with a recommended default, so implementation is never blocked), and **ideas parked deliberately**.
>
> Nearly everything here is settled. Where a decision looks arbitrary, the rationale is recorded so that a future reader can tell the difference between a considered trade-off and an accident.

---

## Part A — Decision log

Format: an abbreviated ADR. Copy these into `docs/adr/` in the new repo.

### D1 — Name: `tool-swap`
**Chosen because** the parent organisation already has `anvil` (LLM serving for coding/agents), this project is the generic *model zoo with serving*, and `llama-swap` is the acknowledged inspiration — the name signals the behaviour (swapping models in and out) to anyone who has met it.
**Rejected:** `forge`, `crucible`, `smithy`, `bellows` (all evocative but say nothing about what it does); `runengine` (inherits confusing R8 baggage).
**Consequence:** package `tool_swap`, CLI `tswap`, labels `com.tool-swap.*`.

### D2 — Docker-first isolation, one image per model
**Chosen because** the requirement "the environment of each model should be easy to set up" plus "models live by themselves" is unachievable in a shared interpreter. The R8 requirements file — ~300 pinned packages containing **both** torch 2.8+cu129 and TensorFlow 2.16, plus a URL-pinned flash-attention wheel — is the proof ([`00_CONTEXT_AND_MOTIVATION.md`](00_CONTEXT_AND_MOTIVATION.md) §3). Their own code contains the confession: a Keras `unload()` noting that clearing the session is *"process-wide, not scoped to this model alone"*.
**Rejected:** per-model venvs (does not isolate CUDA/system libraries, and torch+TF in one process still fight over VRAM); conda envs (same, plus slow); in-process only (the status quo we are escaping).
**Costs accepted:** image build time, disk, container cold start. All are managed (cache mounts, layer ordering, TTL tuning, `tswap warm`).

### D3 — Graduated complexity for model authoring
**Chosen because** the users are scientists, not Docker engineers. The five-rung ladder (function → handler+requirements → system packages → custom base → full Dockerfile/external) means the common case needs no Docker knowledge, and each escalation is *additive*.
**Key mechanism:** the generated Dockerfile is written to `.tswap/build/<model>/` and kept, so a user can read it, learn from it, and graduate by copying it.

### D4 — A normalized API and a transparent proxy; **no OpenAI layer**
**Chosen because** `/run/{tool}` gives every tool one uniform shape, and `/upstream/{tool}/...` reaches a tool's own endpoints for debugging and for handlers that expose more than `/predict`.
**There is no OpenAI-compatible front door.** Such a layer exists to let OpenAI clients reach LLMs, and **we serve no LLMs** — that is llama-swap's job, in a separate deployment ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §0). A compatibility layer for a protocol none of our tools speak would be pure cost, so there is none, and with it no `body.model` resolution, no `aliases` and no `served_model_name`.
**Consequence:** `GET /tools?format=tools` (**D13**) is our integration surface. We are the *tool provider* to an agent whose LLM lives elsewhere, not an LLM endpoint.
**Explicitly out of scope:** consumer-specific translation logic — a layer between this project and any particular serving setup — belongs to the consumer, not here.

### D4b — There is exactly one kind of tool
**Chosen because** the only serious candidate for a "proxy someone else's server image" tool kind was vLLM, and LLM serving is out of scope. **Every tool is built by us from a handler running on our runtime.**
**What this avoids:** a `kind:` config key, a `mapping:` translation façade to give a foreign server a `/run` shape, and a permanent "does this feature degrade gracefully for external tools?" caveat on every capability in the architecture.
**What it buys:** `/run` works for every tool with no translation config; `/schema` is always live, so `?format=tools` never has holes; soft TTL (**D9**) applies to the whole zoo; and the router never has to ask what a given image exposes.
**Escape hatch:** an author who needs vendor inference code uses that vendor's image as a `base_image` and calls their library from `predict()` ([`03_TOOL_AUTHORING.md`](03_TOOL_AUTHORING.md) §7).

### D5 — Micro-batching, inside the container
**Chosen because** it is where GPU throughput comes from, and putting it inside the container keeps the router tool-agnostic.
**It is load-bearing rather than optional:** since the zoo contains no third-party servers (**D4b**), there is no vLLM or TEI to defer the hard cases to, so [`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) has to be right.
**Batching is ours in contract and BentoML's in implementation** (**D14**): the engine is BentoML's adaptive dispatcher, configured with `max_batch_size` and `max_latency_ms`. The simpler fixed policy — flush on size *or* on the oldest item's age — is the mental model operators should use when tuning those knobs, and the written specification for a future `native` backend ([`12_REFERENCE_CODE.md`](12_REFERENCE_CODE.md) §7).

### D6 — Models are user-authored and configurable
**Consequence:** the schema must be *declared as data* (`tool.yaml`) rather than *derived by importing code*, because the router cannot import a model that lives in another container with another interpreter. This is why the ~440-line `tool_builder` introspection layer is not ported.

### D7 — Scheduling: pinned devices + groups first
**Chosen because** "one model on GPU 0 at a time" is comprehensible and sufficient for the real workload, whereas VRAM prediction is unreliable (it depends on batch size, sequence length, activations and allocator behaviour) and a number in a config file would be a comforting fiction.
**Left open:** `vram_gb` is in the schema as advisory, and the scheduler is a swappable `Policy`, so VRAM-aware packing is an addition rather than a rewrite.
**Clarified by D27:** groups cap *our own* residency and are blind to other tenants on the shared node. Measuring free VRAM before a reload is permitted; predicting a model's consumption remains refused. The rejection above was always about prediction, never about measurement.
**Whole devices only.** `devices` is a list of whole GPU indices. MIG instances present themselves as devices and therefore work without special handling; MPS and fractional allocation are out of scope. Revisit only against a concrete need, since partial-GPU sharing reintroduces exactly the contention accounting **D7** avoids.

### D8 — CLI over docker compose
**Division of labour:** compose owns the **router only**; the **router** owns model containers (created via the Docker API with our labels). Model containers cannot be compose services because they come and go dynamically, which is the entire point.
**Acknowledged cost:** mounting `/var/run/docker.sock` gives the router root-equivalent access to the host. Documented plainly, with running the router on the host as the alternative.

### D9 — Both TTLs ship in v1; soft unload is the default reclamation mechanism
> **Amended by [ADR-0002](adr/0002-shared-node-soft-unload.md).** The original decision — *"hard TTL first, soft TTL later"* — is superseded. Its reasoning is preserved below, because it was correct given what was known at the time and the premise is what moved.

**The deployment is a shared DGX.** Other tenants use the same GPUs, so the genuinely contended resource is **node VRAM**, not a slot in our own table. A container that is alive but holds no weights costs a few hundred megabytes of host RAM and *zero VRAM*.

**Decision:**
- **Soft unload is the default.** A tool idle for `soft_ttl` receives `POST /unload`, releasing its weights while the container stays alive. This is how VRAM goes back to the node.
- **Hard stop is the backstop**, after a longer idle (`ttl > soft_ttl`), reclaiming the container and host RAM — and the **forced fallback** for handlers whose `unload()` cannot genuinely release.
- **Build order is unchanged:** hard TTL is implemented first in TDD order (M6), because everything depends on stop working and because it always works. Soft unload builds on it.

**Superseded reasoning, recorded so the reversal is legible:** *"hard stop frees everything including the group slot, which is the contended resource; soft unload keeps the slot and therefore does not help the case that motivates the project."* That holds when we own the whole box, where slot and VRAM are the same scarce thing. On a shared node they come apart, and releasing VRAM while holding a slot becomes exactly the trade we want. The third original objection — that the scheduler must then distinguish "resident in the group" from "resident in VRAM" — stands, and is now simply paid for ([`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](06_LIFECYCLE_TTL_AND_SCHEDULING.md) §5.1.1).

**Consequence — `unload()` is no longer optional for GPU tools.** It is required in the handler contract for any tool declaring `devices`, and preflight stage 8 verifying it becomes a hard **`FAIL`** rather than advisory (**D26**).

**`keep_warm` exempts a tool from TTL, but not from eviction.** The two are separate concerns: TTL is about idleness, eviction is about contention. Conflating them would let a badly-configured group of `keep_warm` members deadlock every other member of that group. True pinning is expressed with `eviction: none` on the group, which says what it means. `tswap validate` **warns** when every member of a group is `keep_warm` and `max_resident` is smaller than the member count, because that configuration guarantees starvation and is almost always a mistake rather than an intention.

**Verifying that VRAM was really freed.** Stopping the container makes the OS reclaim the memory, but drivers and zombie processes occasionally lie about it — and with soft unload the guarantee is weaker still, since no process exits. Preflight stage 8 is therefore a **hard `FAIL`** for GPU tools rather than advisory (**D26**), and operators still run `nvidia-smi` for ad-hoc diagnosis. A report in `tswap status` / `tswap doctor` remains a reasonable later addition. **It must never become a scheduling input** (**D7**, **D27**).

### D10 — The R8 client is separate and later
**Chosen because** v1 must not be shaped by one consumer. Its plan is written now, while context is fresh ([`11_R8_CLIENT_PLAN.md`](11_R8_CLIENT_PLAN.md)), and it lives in the **R8 repo** so tool-swap stays ignorant of R8.

### D11 — Networked host, no air-gap
Simplifies weight downloads, image builds and base images. If an air-gapped deployment is ever needed: pre-built image tarballs, an offline wheelhouse, and a pre-populated cache mount — all additive.

### D12 — Reuse self-hostable software where possible
**Applied to infrastructure**: Docker, FastAPI (the router), and the swap semantics borrowed from llama-swap. **Applied to the in-container runtime**: BentoML (**D14**). **Not applied to model serving**: we host no third-party inference *servers* (**D4b**) — LLMs live in llama-swap, and anything else is wrapped in a handler so it keeps our uniform contract.

**The distinction that matters:** reusing a serving *framework* inside an image we build is reuse; hosting someone else's *server image* is an integration burden with a black box behind it. Those are different things, and conflating them is what makes "write our own batcher" sound principled.

The principle therefore applies uniformly — at the infrastructure level, and at the in-image runtime level — and we write only what is genuinely ours: the handler protocol, the schema, and the contract.

### D13 — Schemas are JSON Schema, projected into standard tool definitions
**Chosen because** the LLM tool-calling ecosystem has already standardised on JSON Schema: OpenAI function/tool `parameters`, Anthropic `input_schema`, Google function declarations, MCP tool definitions and LangChain tool specs are all the same shape. Authoring in that format means **a tool in the zoo is automatically a callable tool**, with no translation code written by us or by any consumer.
**Promoted by D4:** with the OpenAI door removed, this is no longer one integration option among several — it is *the* way an LLM reaches our tools. The agent's model runs elsewhere, reads `?format=tools`, and calls back into `/run`. Correctness here is the difference between a zoo agents can use and one they cannot.
**Rejected:** R8's closed `ModalityType` enum (adding a modality required editing the orchestrator — the exact coupling **D2** removes); a bespoke `Port` type with a custom text renderer (R8's `to_node_text()` existed *only* because its schema was non-standard, and it forces every consumer to write a parser).
**Consequences:** three projections from one authored schema — descriptor, `?format=tools`, and OpenAPI 3.1 (chosen over 3.0 because 3.1 is JSON-Schema-2020-12 compatible, making the embed mechanical rather than lossy). Domain vocabulary survives as open `x-semantic` hints instead of a closed enum. Validation comes free from any JSON Schema validator. The simple `inputs:` list stays the authoring surface (**R4**) and is *compiled* to JSON Schema, with a raw `json_schema:` escape hatch. Full specification in [`04_API_CONTRACT.md`](04_API_CONTRACT.md) §9.
**This closes the question of what type vocabulary to invent**; the answer is to invent none.

### D14 — The in-container runtime is built on BentoML
Full analysis in [`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §1.

**Chosen because** micro-batching is the cumbersome, subtle, correctness-critical part of the runtime, and it is precisely the part with a mature answer. BentoML's adaptive dispatcher tunes its wait window from the observed arrival rate and model latency — better than a fixed size/age policy — and the originating system already ran it successfully ([`00_CONTEXT_AND_MOTIVATION.md`](00_CONTEXT_AND_MOTIVATION.md) §2.3). Everything else the runtime does (import a handler, load in the background, answer readiness truthfully, expose a schema) is straightforward code that has to be written either way. Writing our own server would therefore have bought control exactly where control is worth least.

**The counter-argument, and the stance taken:** BentoML brings locked pins (pydantic, starlette, click) into every tool image, in tension with **D2**'s per-tool dependency freedom. *A locked dependency is acceptable until a concrete tool demonstrates an unresolvable conflict.* "BentoML pins pydantic" is not a conflict; "this tool requires pydantic <2 and therefore cannot install alongside BentoML" is. We do not pay the permanent cost of owning an inference server to pre-empt a conflict nobody has hit.

**Risk controls** ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §1.2): BentoML is **pinned**, never floated; a spike (M3.5) resolves it against a torch/monai stack and a TensorFlow stack *before* the runtime is built on it; a per-template dependency-resolution gate runs in CI; and `tswap doctor` reports the resolved versions inside built images.

**What makes it reversible** ([`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §2): a `RuntimeBackend` seam, specified as **architecture only** — v1 ships one backend and **no `native` code is written**. The handler protocol, schema compiler, predict wrapper, batch-length safety check and readiness semantics all sit *above* the seam, so a future `native` backend supplies only a queue, a flush policy and a server loop. Enforced by an import-linter rule (no BentoML import outside the adapter), a ban on BentoML types in signatures above the seam, and a backend-agnostic contract test suite any future backend must pass. `runtime.server: bentoml` exists in the config schema from day one, with `native` reserved.

**Costs accepted:** batching unit tests move from L1 (`ManualClock`, milliseconds) to L2 (in-process, real time, statistical assertions), because the dispatcher owns its own adaptive timing; `max_batch_bytes` is not available; and per-request non-batchable inputs on a batched tool become illegal (**D15**).

**Gains:** adaptive rather than fixed batching; built-in Prometheus metrics **including batch-size and dispatcher metrics**, which are exactly what proves batching is working; `/livez` `/readyz` `/metrics` for free; and faster tool builds, since BentoML is pre-installed in the base images.

**Revisit if** a tool cannot install BentoML, or a BentoML release breaks the dispatcher contract. The exit is per-tool before it is ever project-wide.

### D15 — A batched tool may declare only batchable inputs; static params are the escape hatch
**Chosen because** BentoML's dispatcher cannot group a batch by non-batchable arguments — a batcher of our own could have, via compatibility keys, and this is the one real capability **D14** gives up. Left unaddressed, two requests with `threshold=0.5` and `threshold=0.9` would be batched together and one silently answered with the other's parameter: no exception, no log line, and a plausible-looking wrong number returned about a patient. **The failure is silent, so the state is made unrepresentable rather than handled at runtime.**

**Rule:** `tswap validate` **hard-errors** if a tool with `batching.enabled: true` declares any per-request non-batchable input, naming the input and the ways out.

**Escape hatch — a third input class.** `params:` in `tool.yaml` are **static, load-time** values (`threshold`, `top_k`, a model variant), passed to `load()` rather than `predict()`, overridable per config entry, and part of the tool's identity. Two thresholds become two config entries over the same image — which the scheduler, TTL and status surfaces already handle — at the cost of two resident models. Without this class, the rule would push authors to disable batching on every parameterised tool.

**If per-request non-batchable inputs are genuinely required:** either set `batching.enabled: false` (the common answer, and free for CPU tools), or use the `native` backend — **the first real use case for the D14 seam**, and the reason that seam earns its keep beyond dependency risk.

### D17 — `tswap preflight` is a first-class, author-facing deployment gate

**The gap it closes.** **D6** makes tools user-authored and **D3** promises a scientist can add one without Docker knowledge — but nothing in the plan told that scientist *whether their tool would actually deploy*. The existing commands each answer a fragment: `tswap validate` is static and never starts anything; `tswap build` proves only that an image compiles; `tswap test` runs one happy-path example; `tswap doctor` diagnoses the **host**, not a tool. An author had to run four commands, interpret four unrelated outputs, and would still not have exercised readiness, batch attribution, `unload()`, or standalone operation. Discovering those at deployment time — on a shared GPU box, in front of colleagues — is exactly the experience **R2** exists to prevent.

**Chosen shape:** one self-service command, `tswap preflight <tool>`, running the whole chain locally and printing a single go/no-go verdict with a per-check remedy. **It requires no router and no `tools.yaml` entry**, so it works on a laptop, before the tool has been registered with anyone, which is precisely when an author wants it.

**Why it is a gate and not a convenience.** Guardrail 11 (Part D) requires that a tool image run standalone under plain `docker run`; that invariant is what keeps tools portable across compose, llama-swap, tool-swap and KServe, and it is currently asserted only by an integration test the author never sees. Preflight makes the author prove it for their own tool, every time. Likewise guardrail 5 calls batch misattribution the worst possible bug class here — preflight puts that assertion in the author's hands rather than leaving it solely in our suite.

**Severity, not a binary.** `FAIL` blocks and exits non-zero; `WARN` informs and still exits zero (unpinned requirements, a missing `unload()`, a slow cold start, a nondeterministic example). A tool that is merely *unwise* must still be deployable — a gate that refuses everything imperfect gets bypassed, and a bypassed gate protects nobody.

**It ends with a config snippet, not just a verdict.** The measured cold start becomes a suggested `ready_timeout`, observed VRAM a suggested `resources.vram_gb`, the observed inference time a suggested `max_latency_ms`. The author's next action is a paste into `tools.yaml` rather than a guess — and guessed timeouts are a recurring source of `FAILED` tools ([`07_CLI_AND_OPS.md`](07_CLI_AND_OPS.md) §7).

**One check registry.** `validate` and `preflight` are the same checks with different filters — static-only versus all. Two independent implementations of "is this tool well-formed" would drift within a release, and the CI gate would then disagree with the author's command about whether their tool is acceptable. See [`08_REPO_LAYOUT.md`](08_REPO_LAYOUT.md) §1.

**Rejected alternatives:**
- *Fold everything into `tswap validate`* — it would stop being CI-runnable. Its value is that it needs no Docker and finishes in seconds on every PR; adding container starts destroys that.
- *Make it an admission gate in the router or CI only* — it would run too late, and the author would learn of the failure from someone else's pipeline. Preflight is deliberately author-first and local. Reusing the registry in CI later is additive and cheap.
- *A `POST /admin/tools/{tool}/preflight` endpoint* — requires the router and a registered tool, which is exactly the situation the author is not yet in. Deferred to phase 2, with `/ui` as the trigger.

**Scope discipline:** M5.5 ships the stages that need only Docker. VRAM-release verification requires a GPU and lands with M6; cold-start statistics enrich the report in M7.

**Revisit if** preflight's runtime grows to the point that authors skip it. The stages are independent, so `--fast` (skip the batching stage) is the pressure valve, not a redesign.

### D18 — Large payloads travel by reference, and the reference may later be a URI

**Rule for v1:** a tool that consumes a large object (a DICOM study, a CT volume, an EEG recording) declares an input that carries a **filesystem path**, and the host directory is mounted into the container. Inline base64 is not the mechanism: a 500 MB volume becomes ~670 MB of JSON, buffered end to end.

**The direction of travel is object storage.** Passing paths couples the caller and the container to the same filesystem view, which does not survive a second host and is a recurring source of confusion when a path exists for the caller but was never mounted for the container. Object-storage URIs (S3/MinIO) remove that coupling, and MinIO is already present in the wider data stack.

**What makes the evolution additive rather than a migration** — this is the substance of the decision, not the ordering:

- The input is specified as a **reference**, and its JSON Schema is `type: string` with `x-semantic` naming the content (`dicom_path`). It is **not** named or described as a filesystem path in the tool's public contract.
- **Resolution happens inside the runtime**, immediately before the handler sees the value. In v1 the resolver accepts a local path and returns it unchanged. Adding `s3://` support later means teaching that one resolver a new scheme, plus a credentials block in config.
- Consequently, **adding object storage changes no client code, no tool schema and no handler.** A caller that passes `s3://bucket/key` where it used to pass `/data/x.dcm` gets the same behaviour, and a tool that never learns the difference keeps working.

**Consequences accepted for v1:** mounts must be declared, and a path that is valid on the host but unmounted in the container is a configuration error the tool cannot diagnose. `tswap doctor` and the troubleshooting runbook must name this explicitly, because it will be the single most common "why does my tool say file not found" report.

**Deliberately not built now:** multipart upload to the router with staging to a scratch volume. It is a genuine convenience for interactive callers, but it is a *third* mechanism to maintain, and the object-storage path serves the same need without the router holding large bodies.

### D19 — Descriptions are mandatory for the tool and its inputs; advisory for outputs

**Chosen because** mandatory descriptions are the reason the zoo is agent-consumable at all: `?format=tools` (**D13**) is only as useful as the prose inside it, and an undescribed parameter is one an LLM will fill in wrongly. The originating system raised an error when a parameter description was missing, and that strictness is precisely why its registry could be fed to a model.

**Rule:** `tswap validate` **hard-errors** on a missing description for the tool itself or for any input. Missing **output** descriptions are a `WARN`, since outputs are consumed by whoever called the tool and already knew what they asked for.

**Escape hatch:** `--allow-missing-descriptions` exists for local prototyping and is **never** permitted in CI. A rule that cannot be bypassed while iterating gets bypassed permanently by deleting the rule.

### D20 — The router runs in a container; running on the host is a debugging option

**Chosen because** one supported deployment is simpler to document, to test and to reproduce in a bug report, and the container is the shape that `tswap up` and the compose file already assume.

**The cost, stated plainly:** the router mounts `/var/run/docker.sock`, which is root-equivalent access to the host. This is documented rather than hidden, and running the router on the host is the answer for anyone who cannot accept it.

**Host mode is not deleted** — the `ContainerBackend` abstraction supports it, and it is genuinely useful when debugging path or permission problems. It is documented as a debugging option and does not carry the v1 test matrix. Note the one real behavioural difference between the two: **how a tool is addressed** (container name on the shared network versus `127.0.0.1:port`), which is exactly what **D21** settles.

### D21 — Tools are addressed by container name; no host ports are published

**Chosen because** it removes the entire problem class. There is no port allocation, therefore no port collisions, no state file recording who has which port, and no repeat of the failure where ports were assigned by registry index and reordering the config silently reassigned every one of them.

Every tool container joins the shared network and the router reaches it at `http://<container-name>:<internal-port>`. The internal port is a constant, since nothing else on that network competes for it.

**`expose_host_port` exists for debugging** — attaching `curl` or a profiler from the host — and is explicitly not the normal path.

**Consequence for health checks:** a container-side health check runs in the container's own namespace and must target the *internal* port. This is an easy mistake to make once tools are addressed by name.

### D22 — A request during a cold start blocks, bounded by `queue_timeout`

**Chosen because** it is the simplest contract for a caller: one request, one response, no polling and no result store. It matches llama-swap's behaviour, and a caller that cannot wait can set a shorter timeout.

Bounded is the operative word: `queue_timeout` yields a 503 with a `Retry-After` and a reason, and `max_queue_depth` yields a 429 rather than accumulating an unbounded queue in memory.

**Asynchronous submission (`?async=true` plus a result store) is a phase-2 item, and its trigger is concrete:** a tool whose cold start plus inference genuinely exceeds a client's practical HTTP timeout. Until such a tool exists, a result store is a state-management burden for a problem nobody has.

### D23 — One tool per container, and one version per tool name

**One tool per container.** Packing several small tools into one image would reintroduce the shared environment that **D2** exists to eliminate, in exchange for a few hundred megabytes of RAM. The answer for genuinely small models is to place them on the CPU with `keep_warm: true`, which costs no GPU slot and keeps them permanently available.

**Versioning is expressed in the tool name** (`cxr_v1`, `cxr_v2`) in v1. Two entries over two images is something the scheduler, TTL, status and discovery surfaces already handle correctly with no new concepts, and running two versions side by side for comparison is a real research need that this satisfies today.

**There is no version routing and no `aliases` field.** If a stable name that points at "whichever version is current" becomes necessary — most likely when an external consumer hardcodes a tool name and cannot be redeployed in step with the zoo — that is the trigger to introduce aliasing, on its own merits and with that use case in hand.

### D24 — Config may be one file or many; there is no separate one-shot execution path

**Config layout:** a single `tools.yaml` for small setups, and `path:` includes pointing at per-tool `tool.yaml` files for anything larger. Both are supported because they serve different situations, and the include form is what makes a tool directory self-contained and therefore portable. Glob includes (`include: tools/*/tool.yaml`) are deferred until the explicit list becomes tiresome.

**One-shot execution** — start a container, run a single input, stop it — exists **only inside `tswap test` and `tswap preflight`**, never as a separate command with its own code path. A parallel implementation would drift from the real request path and would then be reassuring about behaviour it no longer shares.

Whether it deserves promotion to a user-facing command depends on evidence from the user-validation workflow that someone actually wants it. Until then, deliberately minimal: no `tswap exec`.

### D25 — A request preempts an idle incumbent; it does not wait for its TTL

**Chosen because** it was stated as a requirement: *"We don't want to wait for TTL as it could take quite some time, if another process is not being used right now we want to stop it and warm up any process that has a request."*

A request for tool B **displaces** an idle incumbent A immediately, subject only to `min_residency` and in-flight immunity. `WAIT` remains only where the config asks for it (`eviction: none`) or where nothing is evictable.

**This is the decision that ruled out Kubernetes** ([ADR-0001](adr/0001-build-our-own-router.md)). Kubernetes *allocates* devices and leaves the second pod `Pending`; it has no preemption semantic, and Knative's scale-to-zero only releases the GPU after the incumbent's own grace period — precisely the wait being rejected here.

**What makes it affordable:** soft unload (**D9**). Displacement becomes a `POST /unload` rather than a container stop, so the displaced tool keeps its process, its imports and its CUDA context. A mistaken eviction therefore costs a weight load rather than a full cold start, which also defuses much of the thrashing risk in [`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](06_LIFECYCLE_TTL_AND_SCHEDULING.md) §5.3.

### D26 — `unload()` is mandatory for GPU tools, and preflight stage 8 is a hard `FAIL`

**Chosen because** soft unload is now the primary way VRAM returns to a **shared** node (**D9**). A handler whose `unload()` silently fails to release produces the worst outcome available: we believe the memory is free, we tell the scheduler so, and we hold it anyway — degrading the whole DGX, other tenants included, with no error raised anywhere.

**Rules:**
- a tool declaring `devices` **must** define `unload()` — a hard validation error;
- preflight stage 8 measures release with `nvidia-smi` before/after and **fails** if it does not happen;
- a tool that genuinely cannot release is **not rejected**. It is classified **hard-stop-only**: never soft-unloaded, reclaimed exclusively by hard TTL and eviction.

**Why not rejection:** **D17**'s severity principle — *a gate that refuses everything imperfect gets bypassed, and a bypassed gate protects nobody*. TensorFlow/Keras tools are the expected members of this class, and they must still be deployable. They lose the fast path and their author is told exactly why.

### D27 — Free VRAM may be measured; a model's consumption is still never predicted

**Chosen because** on a shared node, *"is there memory right now"* is a fact we can read and act on, while *"will this model fit"* remains the guess **D7** rejected. The distinction is worth stating precisely, because collapsing it re-introduces exactly the fiction D7 refused.

**Permitted:** reading live free VRAM immediately before a reload, so that a load doomed to OOM fails fast with the right reason (**D28**) instead of failing slowly with the wrong one.

**Still refused:** using `vram_gb` to decide placement, packing tools by predicted size, or admitting on a predicted fit. `vram_gb` stays advisory.

**Boundary that must hold:** the measurement happens in the *caller* and enters the policy as a plain value on the snapshot. It never becomes I/O inside `request_slot`, which stays pure (guardrail 2), and it is never a scheduling input in the sense D7 forbids.

### D28 — A reload that fails for lack of VRAM is not a tool failure

**Chosen because** on a shared DGX, memory released while idle can be taken by another tenant before we reload it. Every other failure path in the design leads to `FAILED`, which means *"this tool is broken"* — and a tool marked broken because a neighbour was busy is both wrong and actively misleading during an incident.

**Rules** ([`06_LIFECYCLE_TTL_AND_SCHEDULING.md`](06_LIFECYCLE_TTL_AND_SCHEDULING.md) §3.3):
- the tool returns to **`IDLE_SOFT`**, never `FAILED`;
- the occurrence is **excluded from `max_consecutive_failures`** — a busy neighbour must never permanently disable our tool;
- the caller receives **503 `TOOL_UNAVAILABLE` with `reason: vram_unavailable`** and a `Retry-After`, phrased so that nobody starts debugging a tool that is working perfectly;
- it is **logged under its own reason**, because the rate of these describes the *node* and is the number an operator needs when negotiating for capacity.

**The regression this prevents** is a tool that quietly marks itself broken whenever the DGX is busy and stays broken until a human notices.

---

## Part B — The questions that remain open

Everything else has been decided and lives in Part A. What follows is genuinely undecided, and none of it blocks a start: each carries a recommended default and a milestone by which it must be settled.

### ~~Q1~~ — ✅ **RESOLVED at the M−1 gate: build our own router**

Was the gating question. **Closed** by [ADR-0001](adr/0001-build-our-own-router.md); the full evidence is there and in [`14_ALTERNATIVES_EVALUATION.md`](14_ALTERNATIVES_EVALUATION.md) §6.

| Spike | Outcome |
|---|---|
| **C** — do the tools fit on the GPUs at once? | **No.** The swapping premise holds; compose-with-everything-resident is not available. |
| **A** — can llama-swap be our router? | **No.** It is LLM/OpenAI-shaped and cannot route `/predict`. Its separate role serving our LLMs is unaffected. |
| **B** — KServe on single-node Kubernetes? | **No.** Kubernetes allocates rather than preempts, and preemption is a requirement (**D25**). We would operate a cluster *and still* write the preemption logic. |

**Do not re-open without new evidence**, and do not re-run the spikes. The triggers that would justify revisiting are unchanged and specific: a second GPU host, multi-tenant isolation, or an infrastructure team already operating Kubernetes ([`14_ALTERNATIVES_EVALUATION.md`](14_ALTERNATIVES_EVALUATION.md) §8.6).

**The invariant that keeps the decision reversible, and which still costs nothing:** a tool is an OCI image serving HTTP, runnable with plain `docker run` — simultaneously a valid compose service, a valid llama-swap target, a valid tool-swap tool and a valid KServe custom predictor. **The tools are the durable asset; the router is replaceable.**

### Q2 — Docker SDK, or shell out to the `docker` CLI?

| | Pros | Cons |
|---|---|---|
| `docker` Python SDK | Typed, no output parsing, streaming logs | Another dependency; occasional API-version friction |
| Shell out | Zero dependencies, and the failing command is exactly what a user would type, so errors are reproducible by hand | Output parsing, quoting |

**Recommended:** the SDK, behind our `ContainerBackend` protocol — the protocol is what makes the choice cheap to reverse.
**Resolve at:** M2.

### Q3 — Implementation details left to the milestone that meets them

None of these are architectural. They are recorded so that the choice is made deliberately, once, rather than three times in three files.

| Question | Recommended default | Resolve at |
|---|---|---|
| Which BentoML version to pin, and when to upgrade it | Pin at the M3.5 spike; upgrade only when the backend contract suite passes | M3.5 |
| Whether to expose BentoML's own `/healthz` and `/readyz` beside ours | No — one contract, and `/info` says what is underneath | M4 |
| Whether `max_batch_bytes` is worth pursuing upstream | No — a conservative per-tool `max_batch_size` covers it until a tool proves otherwise | M4 |
| Validate `/run` bodies with `jsonschema` or with pydantic models built from the schema | Pydantic: already a dependency, better error messages. Fall back to `jsonschema` only if a raw `json_schema:` block needs constructs pydantic cannot express | M9 |
| How the output schema (`returns`) is exposed, given tool definitions have no standard slot for it | Keep it in our descriptor; omit it from `?format=tools` | M9 |

### Q4 — Should the router expose an aggregated `/metrics`?

**Deferred rather than answered.** There is no Prometheus endpoint in v1: `/status` already returns counters, latencies and cold-start statistics as JSON, and building an exposition format for a monitoring stack nobody has stood up is speculative ([`04_API_CONTRACT.md`](04_API_CONTRACT.md) §8).

**If it is ever built:** the router aggregates its own metrics and *proxies* container metrics under `/metrics/{tool}`. Containers are ephemeral, so direct scrape targets keep vanishing and alerting on absence becomes noise.

**Trigger:** somebody stands up Prometheus and needs alerting.

---

## Part B-1 — Reference: where the previously-open questions were settled

For anyone returning to this document with an older copy, or wondering why a question they remember is gone:

| Was | Now |
|---|---|
| Build a router, or reuse one? (the gating question) | **[ADR-0001](adr/0001-build-our-own-router.md)** — build our own; all three spikes failed |
| Should soft TTL wait for phase 2? | **D9 as amended** — no; on a shared node it is the default reclamation mechanism |
| Does a request wait for an incumbent's TTL, or displace it? | **D25** — displace |
| What happens when a reload cannot get VRAM? | **D28** — not a tool failure; `vram_unavailable`, back to `IDLE_SOFT` |
| Build our own in-container runtime, or reuse one? | **D14** — BentoML behind our own contract |
| What type vocabulary for schemas? | **D13** — JSON Schema plus open `x-semantic` hints |
| How are large payloads passed? | **D18** — paths in v1, object-storage URIs as the designed growth path |
| Is the mandatory-description rule too strict? | **D19** — mandatory for tool and inputs, advisory for outputs |
| Router in a container or on the host? | **D20** — container supported, host is a debugging option |
| Port allocation strategy? | **D21** — container names, no published ports |
| What happens to `keep_warm` models when a group is full? | **D9** — exempt from TTL, not from eviction |
| Block or 202-and-poll during a cold start? | **D22** — block, bounded by `queue_timeout` |
| Can `tswap` run a tool without the router? | **D24** — only inside `test`/`preflight`, no separate command |
| Multi-tool-per-container? | **D23** — no |
| Config in one file or many? | **D24** — both |
| Model versioning / A-B? | **D23** — by tool name; aliases only at a real trigger |
| GPU sharing beyond whole devices? | **D7** — whole devices only |
| How do we detect that VRAM was really freed? | **D9** — manually via `nvidia-smi` in v1 |

---

## Part B-2 — Superseded question numbering

The questions above were renumbered when the resolved ones were promoted into Part A. If an external document cites "Q7" or "Q11" from an earlier revision of this plan, consult the table in Part B-1 rather than the current numbering.


---

## Part C — Ideas parked deliberately

Recorded so they are not re-invented as if new, and not built prematurely.

| Idea | Why parked |
|---|---|
| Kubernetes / KServe with scale-to-zero | **Evaluated and rejected at the M−1 gate** ([ADR-0001](adr/0001-build-our-own-router.md)), not merely parked. Provides no preemption semantic — Kubernetes allocates devices and leaves the second pod `Pending` — which **D25** requires; and Knative cannot express "keep the pod, release the weights", which **D9** now depends on. Also contradicts **R1** and **D8** for a single-box deployment. Remains the documented growth path with explicit triggers ([`14_ALTERNATIVES_EVALUATION.md`](14_ALTERNATIVES_EVALUATION.md) §8.6). Minikube specifically: host-built images are invisible to the cluster, and GPU support is the experimental path. |
| Predictive pre-warming (start a model because a workflow is about to need it) | Genuinely valuable with the R8 orchestration layer, which *knows* the graph ahead of time. But it needs a hint API (`POST /admin/hint`) and a consumer that uses it. Phase 3. |
| Cost/priority-aware scheduling (a "premium" client cannot be evicted) | Needs auth and tenancy first. |
| Automatic TTL tuning from observed traffic | Attractive, but users must be able to predict behaviour. Report the statistics; let humans decide. |
| Model warm-up on config reload | Surprising resource usage on an innocuous command. Keep `tswap warm` explicit. |
| Speculative multi-model residency using free VRAM | Requires the VRAM accounting deliberately deferred by **D7**. |
| A web UI beyond the status page | `/ui` covers the operational need; anything more is a product, not a tool. |
| Result caching (identical inputs → cached output) | Tempting for deterministic embedders, but correctness questions (input identity, model version) and a healthcare context argue for caution. If added, opt-in per model. |

---

## Part D — Things that must not be "improved" without a fight

Guardrails against well-intentioned drift during implementation.

1. **The router must never import model code.** The moment it does, environment isolation is gone. Enforced by import-linter and a runtime assertion.
2. **The scheduler must stay pure.** No I/O, no clock access, no logging side effects. It is the only reason the core logic is testable in milliseconds.
3. **The runtime's dependency budget is BentoML and its transitive set, and nothing further of our own choosing.** A new *direct* dependency added by us needs written justification (**D14**, [`05_RUNTIME_AND_BATCHING.md`](05_RUNTIME_AND_BATCHING.md) §1.1). Every package in a tool image competes with that tool's own pins.
4. **Descriptions stay mandatory.** They are what make the zoo self-documenting and agent-consumable.
5. **Batch result attribution is safety-critical.** Never relax the length/order checks; in a healthcare context a misattributed result is the worst possible bug.
5b. **A neighbour's VRAM usage must never mark our tool `FAILED`** (**D28**). We share the node; a reload that cannot get memory returns to `IDLE_SOFT` with its failure counter untouched. Collapsing this back into the ordinary failure path produces tools that disable themselves whenever the DGX is busy, and an operator who spends the outage debugging code that works.
5c. **A handler that cannot release VRAM is never soft-unloaded** (**D26**). Believing memory was freed when it was not is worse than not trying: it degrades the whole shared node silently. Hard-stop-only is a valid classification, not a defect to be worked around.
6. **Errors keep honest HTTP status codes.** Never regress to R8's blanket 500.
7. **Logs are always persisted**, never gated behind a verbosity flag, and always survive the container that produced them.
8. **No database.** State is in memory plus the container runtime. Restarting the router must stay safe and cheap.
9. **Named inputs only.** Never reintroduce positional-by-index mapping.
10. **The five-line minimal config must keep working.** Every new config key needs a sensible default. If the quickstart grows, **R4** has been lost.
11. **A tool image must run standalone under plain `docker run`.** No dependency on the router to be useful. This is what keeps a tool simultaneously portable to compose, llama-swap, tool-swap and KServe — the hedge that makes the router replaceable and answers the "reinventing the wheel" risk structurally rather than rhetorically ([`14_ALTERNATIVES_EVALUATION.md`](14_ALTERNATIVES_EVALUATION.md) §8). Assert it with an integration test — **and with `tswap preflight` (D17)**, which makes every author prove it for their own tool rather than trusting a test they never run. Its corollary: **the wire protocol lives in the runtime adapter, never in `handler.py`**, and the port and readiness path are read from the environment rather than hardcoded.
12. **`tswap preflight` must keep working with no router, no `tools.yaml` entry and no GPU.** It is the command an author runs *before* their tool exists to anyone else; the moment it requires a registered tool or a running service, it stops being reachable at the point of need and authors go back to discovering failures at deployment. GPU-only checks may be skipped with a stated reason, never made mandatory.
13. **`validate` and `preflight` share one check registry.** Never implement a rule twice. If they diverge, CI and the author will eventually disagree about whether a tool is deployable, and the author will believe the one that says yes.

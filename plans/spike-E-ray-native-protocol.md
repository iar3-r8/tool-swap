# Spike E — Ray-native tool-swap: protocol and pre-agreed decision rule

> **Status:** specified, not run.
> **Supersedes:** retired Spike D ([`plan/15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md) §8). Spike D was retired because its decisive step tested soft unload, which [ADR-0004](../plan/adr/0004-hard-stop-only-in-v1.md) removed. **This spike tests something different and still live:** whether a Ray-native architecture can replace the router, given that the mount objection has been answered by S3 payloads (**D18**) and the app builder.
> **Why it exists:** nine written objections to Ray have been raised and all nine have fallen ([`case-for-ray-native.md`](case-for-ray-native.md) §4). A tenth written argument has no better prior than the first nine. **This is the point where argument stops and measurement starts.**

---

## 0. Read this section before running anything

**Rule 0.1 — The decision rule in §5 is fixed now and must not be edited after any result is known.** If it needs changing, change it *before* step 1 runs, and record who changed it and why. This rule exists because [`bias-audit-and-decision-procedure.md`](bias-audit-and-decision-procedure.md) established a pattern of objections rotating under a fixed conclusion; a spike whose criteria move after the fact would repeat that pattern with more effort.

**Rule 0.2 — A pass is a real outcome, and the welcome one.** If Ray passes, the router leaves scope, **M2, M3.5, most of M3, M6's watchdog and M7's collector are deleted**, and this repository shrinks by roughly a third. [`plan/HANDOFF.md`](../plan/HANDOFF.md) §2 already records that such an outcome would be welcome. Nobody involved should be defending a milestone list.

**Rule 0.3 — Record raw output, not summaries.** Paste commands and their actual stdout into the results file. Every error in this plan's history came from restating behaviour rather than quoting it.

**Rule 0.4 — Stop early on a hard fail.** Steps 3 and 6 are gates. If either fails, stop and record; do not spend days on the remainder.

**Rule 0.5 — The prediction is on the record.** I expect **step 6 (recovery) to fail** and steps 1–5 to pass ([`case-for-ray-native.md`](case-for-ray-native.md) §10.6). Writing this down means a result matching my prediction is weak evidence about Ray and strong evidence about nothing, while a result *contradicting* it is informative. **If everything passes, my judgement was wrong and the plan changes.**

---

## 1. Scope and non-scope

**In scope:** can Ray Serve host two mutually-incompatible containerised tools on one GPU, swap between them on demand, feed them weights and payloads without bind mounts, and survive a restart?

**Explicitly out of scope**, because they are answered or irrelevant:

| Not tested | Why |
|---|---|
| Soft unload / `reconfigure()` releasing VRAM | Removed from v1 by [ADR-0004](../plan/adr/0004-hard-stop-only-in-v1.md) |
| Whether the authoring ladder, schema compiler, preflight or CLI survive | **They survive either way.** Not a discriminator |
| Batching quality | `@serve.batch` is fixed-window, BentoML's is adaptive — documented, no measurement needed |
| Multi-host | Not a v1 requirement |
| Fractional GPUs | **D7** declines them regardless of framework |

**Environment.** Steps 1–2 need a laptop. Steps 3–7 need one GPU and Podman. **If the DGX is unavailable, steps 3–7 may run on any single GPU box** — nothing here is DGX-specific except step 7.

---

## 2. Fixtures — build these first

Two tools chosen so the dependency conflict is real, not simulated. This mirrors the actual R8 conflict ([`plan/00_CONTEXT_AND_MOTIVATION.md`](../plan/00_CONTEXT_AND_MOTIVATION.md) §3).

| Fixture | Contents | Purpose |
|---|---|---|
| `tool_torch` | `rayproject/ray:<ver>-py<ver>-gpu` + `torch==2.8.0+cu129`; loads a ~2 GB dummy checkpoint from S3/MinIO; allocates ~4 GB VRAM; `predict` reads a file by URI and returns its size | The common case |
| `tool_tf` | Same Ray base + `tensorflow==2.16` + `tf-keras`; same shape | **The conflicting case.** Cannot share an interpreter with `tool_torch` |
| `weights` bucket | Two dummy checkpoints, ~2 GB each, in MinIO | Tests the app-builder URI path |
| `data` bucket | One ~500 MB dummy file | Tests **D18** payload-by-reference |

**Both images must derive from the Ray base image** at the cluster's exact Ray and Python patch version. That constraint is conceded as acceptable ([`ray-native-reconsideration.md`](ray-native-reconsideration.md) §1) and is not under test — but **record the actual base tag used**, since it is the coupling we accepted.

---

## 3. Steps

### Step 1 — Per-deployment `image_uri` *(laptop, no GPU)*

Ray's docs contradict themselves: `runtime_env` is a documented `ray_actor_options` key and is settable per-actor, but the Serve guide presents `image_uri` as per-*application*.

Deploy **one application with two deployments**, each with a different `image_uri`, and print `sys.version`, `torch.__version__` / `tf.__version__`, and `/etc/hostname` from inside each replica.

- **Pass:** each deployment reports its own image's contents.
- **Fail:** both report the same, or the config is rejected.
- **On fail:** the mapping is one tool = one application. **Not fatal** — record and continue, noting that a single autoscaling policy over all tools may then be impossible (which step 5 will confirm).

### Step 2 — App builder with an S3 weights URI *(laptop)*

Build one app-builder function; deploy two applications from it with different `args`, per Ray's documented pattern. Fetch weights from MinIO inside `__init__`.

- **Record:** wall-clock time from replica start to weights loaded, for a ~2 GB checkpoint over loopback. **This is the number I asserted was expensive without measuring** ([`bias-audit-and-decision-procedure.md`](bias-audit-and-decision-procedure.md) §3.2).
- **Also record:** whether the builder module must be importable *outside* the tool's image — i.e. does it execute in the controller's environment? Print `sys.executable` and the image marker from inside the builder function.
- **Pass:** both apps load their own weights; the builder does not require tool-specific imports on the host.
- **Fail:** the builder must import tool code in the controller environment. **This would be serious** — it would mean per-tool isolation does not extend to the code that constructs the tool.

### Step 3 — 🚪 **GATE**: two conflicting tools, one GPU, on-demand start

Deploy both fixtures with `min_replicas: 0`, `num_gpus: 1`, `downscale_to_zero_delay_s: 60`.

1. Send a request to `tool_torch`. Record cold-start time end to end.
2. Confirm it is serving and holding VRAM (`nvidia-smi`).
3. Wait out the delay. Confirm the replica goes to zero and **VRAM is actually released** (`nvidia-smi`, not `serve status`).
4. Send a request to `tool_tf`. Confirm it starts and serves.
5. Confirm `CUDA_VISIBLE_DEVICES` or equivalent reaches the containerised replica — **print it from inside the container.** The env-var propagation list in Ray's guide does not mention it, and **D7** depends on it.

- **Pass:** both tools serve, alternate correctly, and VRAM is released on scale-down.
- **Fail:** VRAM is not released, or GPU assignment does not reach the container.
- **This is a gate.** On fail, stop — Ray cannot manage GPU tools for us.

### Step 4 — Payload by reference (**D18**)

`POST` to `tool_torch` with an `s3://` URI for the 500 MB object. The handler resolves and reads it.

- **Pass:** the tool reads the object with no bind mount. Record transfer time.
- **Fail:** requires credentials plumbing that cannot be expressed in `env_vars`. *(Unlikely — `env_vars` is a supported `image_uri` companion.)*

### Step 5 — Preemption via replica counts (**D25**)

The requirement: a request for B displaces **idle** A rather than waiting out A's timer.

With `tool_torch` resident and idle (timer not expired), send a request for `tool_tf`, having an external controller set `tool_torch` to `num_replicas: 0` and `tool_tf` to `1`.

1. Measure end-to-end latency for that first `tool_tf` request.
2. Repeat the alternation **20 times** and record the latency distribution — this is where a cadence problem would show, since Ray's docs frame config updates as deployment-time.
3. Watch for controller errors, stuck `UPDATING` states, or orphaned replicas.
4. Confirm an application-level autoscaling policy can see **both** tools' state. If step 1 failed, confirm whether a policy can span applications at all.

- **Pass:** 20 alternations complete with no stuck states and latency ≈ cold start.
- **Partial:** works but with occasional stuck states or latency spikes. **Record honestly; do not round to pass or fail.**
- **Fail:** the controller degrades, or displacement cannot be driven at this cadence.

### Step 6 — 🚪 **GATE**: cluster restart and recovery

**The item I predict Ray fails**, from its own docs: *"If you aren't using KubeRay, when the Ray cluster fails, Ray Serve cannot recover."* Guardrail 8 requires restarting to be cheap and safe.

1. With both tools deployed and one resident, `kill -9` the head node process.
2. Restart Ray and Serve **using only documented commands**.
3. Record: does the deployment config survive? Do orphaned Podman containers remain (`podman ps -a`)? Is VRAM leaked? What manual steps were needed?
4. Repeat with `kill -9` on a **replica actor** — this should recover, and confirming it does is as informative as the head-node case.

- **Pass:** the cluster returns to serving with no manual cleanup and no leaked VRAM or orphaned containers.
- **Fail:** manual intervention, leaked VRAM, or orphaned containers.
- **This is a gate**, but of a different kind: see §5, rule 3.

### Step 7 — Shared-node fitness *(DGX only, if available)*

1. Confirm Podman installs without disrupting existing Docker workloads.
2. **Configure the `overlay` storage driver** and record cold-start time with a multi-gigabyte image, with and without it. Ray documents *"very slow or hanging container startup"* with the default `vfs` driver.
3. Confirm no `--privileged` requirement arises for our topology.
4. Confirm the `/tmp/ray` permission failure mode does not occur with our user mapping.

- **Record only.** No pass/fail; this informs deployment, not the decision.

---

## 4. What to record

One results file, `plans/spike-E-results.md`, containing:

1. Ray version, Python version, Podman version, base image tags, GPU model, driver.
2. **Verbatim** command output per step.
3. A table of measured times: cold start, weight fetch (step 2), payload transfer (step 4), preemption latency distribution over 20 alternations (step 5).
4. Pass/fail/partial per step against §3's criteria **as written**.
5. Anything surprising, especially anything that contradicts a claim in [`plan/15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md) or in my four documents.

---

## 5. 🔒 The decision rule — fixed before execution

**Rule 1 — Ray wins if steps 3, 5 and 6 all pass.**
Then: adopt Ray Serve as the lifecycle engine. **Delete from scope:** the container backend and lifecycle manager (M2), the BentoML spike (M3.5), the proxy internals (M3), the TTL watchdog (M6), the log collector (M7). **Retain:** `tools.yaml` and the schema compiler (M1), the authoring ladder (M5), preflight (M5.5), the CLI (M8), the API surface (M9) and the eviction policy — re-homed as a Ray autoscaling policy. Supersede [ADR-0001](../plan/adr/0001-build-our-own-router.md) and [ADR-0003](../plan/adr/0003-ray-serve-not-adopted.md) with a new ADR recording this spike as the basis.

**Rule 2 — Ray loses if step 3 fails.**
Ray cannot manage GPU containers for us. ADR-0003 stands, re-based on this evidence, and its grounds become measured rather than argued.

**Rule 3 — If step 6 fails but 3 and 5 pass, the decision goes to the requester with a priced choice**, and *not* to me. The options, to be presented neutrally:

| Option | Cost |
|---|---|
| **(a)** Accept manual recovery | An operational runbook step after any cluster failure; possible VRAM leak until noticed |
| **(b)** Adopt KubeRay | Kubernetes on the shared DGX — the thing both the requester and the engineer rejected as too heavy |
| **(c)** Keep our router | The status quo, with ~a third more code than Ray-native |

**I must not choose (c) by default.** That is the failure mode this whole exchange exposed. Present the measurements and let the requester decide.

**Rule 4 — If step 5 is partial**, treat it as fail for Rule 1 but record the specifics, because "occasional stuck states" may be fixable with a retry in our controller. Escalate under Rule 3 rather than deciding alone.

**Rule 5 — Steps 1, 2, 4 and 7 do not decide anything.** They are informative and would shape a Ray-native design, but a fail in any of them is not grounds to refuse Ray. **This is stated in advance so that a step-2 disappointment cannot be promoted into a headline objection after the fact** — which is exactly what happened four times in the written phase.

---

## 6. ✅ The preemption question — **ANSWERED 2026-08-14**

This section previously flagged preemption as the one unpriced assumption, and noted that I had a declared interest in the answer ([`case-for-ray-native.md`](case-for-ray-native.md) §11). It has now been answered by the requester:

> *"We should preempt if the container is idle, else we wait would be the ideal scenario for now."*

**This confirms D25 as already written**, and the match is close enough to quote:

> *"A request for tool B **displaces** an idle incumbent A immediately, subject only to `min_residency` and **in-flight immunity**. `WAIT` remains only where the config asks for it (`eviction: none`) or where nothing is evictable."*

**"Preempt if idle, else wait" is in-flight immunity plus idle eviction** — the two halves of D25's rule, in the requester's own words. No amendment is needed.

### 6.1 What this settles, and what it deliberately does not

**Settles:** step 5 stays in the spike, and preemption remains a gate. The ADR-0001 rejection of KServe stands on its stated ground — Kubernetes allocates devices and leaves the second pod `Pending`, with nothing evicting an incumbent.

**Does not settle the framework question, and this must be said clearly given my track record.** The answer confirms *the requirement*; it does not establish that Ray fails it. Ray can drive replica counts from an external controller, which is exactly *"stop the idle one, start the requested one"*. **Whether it does so reliably at request cadence is what step 5 measures.** A confirmed requirement is not a refuted alternative, and conflating the two is the move this exchange exposed four times.

**Note also that the answer is *weaker* than the strongest form of D25.** *"Else we wait"* means no queue-jumping against a busy incumbent, and *"for now"* signals a tolerance that may loosen. Both make the requirement easier for any framework to satisfy, not harder.

### 6.2 One consequence worth flagging

Under [ADR-0004](../plan/adr/0004-hard-stop-only-in-v1.md), displacement costs the victim a **full cold start** on its next request. **D25**'s own cost note is explicit that this makes `min_residency` and thrash detection *"matter more, not less"*. If weights are fetched from S3 rather than a mount — the direction [`bias-audit-and-decision-procedure.md`](bias-audit-and-decision-procedure.md) §1 establishes — that cold start now includes a multi-gigabyte download.

**So step 2's weight-fetch measurement is no longer merely informative.** Under Rule 5 it still does not decide the framework, but it directly prices the thrash risk that preemption creates, for *both* architectures. Record it carefully.

---

## 7. Effort shape

Steps 1–2 are a laptop afternoon. Steps 3–6 need a GPU box with Podman. Step 7 needs the DGX and a cooperative admin. **Steps 1–2 can run immediately and would already answer the two questions I got wrong** (per-deployment `image_uri`, and whether weight fetching is actually slow).

**Start with steps 1–2.** They are cheap, they need no GPU, and they test my two weakest claims first — which is the right order when the person specifying the spike has a documented bias.

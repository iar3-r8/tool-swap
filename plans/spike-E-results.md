# Spike E — results

> Protocol: [`spike-E-ray-native-protocol.md`](spike-E-ray-native-protocol.md) — decision rule §5 frozen (Rule 0.1), step criteria §3 as written.
> Ledger: [`spike-E-continuation.md`](spike-E-continuation.md) §§9a–9S — every verdict, measurement, finding and retraction cited below is there with its raw excerpts; §9S (D44) records the 2026-09-10 verdict corrections applied throughout this file.
> Scope documented: **the whole branch** `feature/spike-e-continuation` (HEAD `7382e8e`; ledger and this file modified, uncommitted) — all seven steps.
> Operator: Zoo (TDD pipeline) + user · Dates: 2026-08-14 (attempt, no data) → continuation runs 2026-08-25 → 2026-09 · This rewrite: 2026-09-10 (verdicts corrected per §9S/D44 the same day).
>
> This file is the single living results document the protocol designates (§4). The 2026-09-10 rewrite replaces the pre-run skeleton that previously occupied this file (every section of which read *pending host run*). The skeleton's two standing records — the scope amendment and the 2026-08-14 null result — are preserved verbatim in §10. Verbatim host logs live in gitignored `spike-e-ray-native/results/raw/`; the excerpts quoted here are as recorded in the ledger (Rule 0.3). **Frozen at steps 1–7:** the later steps 8 (plain-podman baseline, D45) and 9 (phase timing, D47/D54) are recorded only in the ledger and are not reflected in this document's verdicts or decision section.

---

## 1. Verdicts (the decision-maker's view)

**The question the spike asked:** can Ray Serve host tool-swap's core requirement — multiple tools with mutually incompatible dependencies, each in its own container image, competing for scarce GPUs, swapped on demand?

**Short answer:** Ray *can* do the loop — measured on one GPU, step 3 passed — but only through the **legacy** container API for GPU tools, at a measured **P90 swap latency of 103 s**, and carrying a set of silent-failure traps documented in §2. The corrected verdicts (ledger §9S, D44): step 5 is **PARTIAL** — the mechanism works (20/20, zero errors), the latency distribution does not — and step 6 **FAILs as written** — replica recovery is automatic, head-node recovery is an operator runbook, and 109 orphaned containers accumulated. The frozen rule makes the decision the requester's (§8); this document presents the measurements and does not decide.

| Step | Question | Verdict | Gate | Ledger |
|---|---|---|---|---|
| 1 | Per-deployment `image_uri` | **PASS** | no (Rule 5) | §9h |
| 2 | Generic app builder, per-image baked weights | **PASS** | no (Rule 5) | §9i |
| 3 | Two conflicting tools, one GPU, on demand | **PASS** | **GATE** (Rule 2) | §9N (D36) |
| 4 | Payload read (baked-in; D18 not tested) | **PASS** | no (Rule 5) | §9O |
| 5 | 20 alternations at cadence | **PARTIAL** — 20/20, 0 errors; latency not ≈ cold start (P90 103 s) | Rule 4 → Rule 3 | §9Q (D42), corrected §9S (D44) |
| 6 | Restart and recovery | **FAIL (as written)** — replica automatic; head-node operator runbook; 109 orphaned containers | **GATE** (Rule 3 kind) | §9P (D41), corrected §9S (D44) |
| 7 | Shared-node fitness | record only, no verdict | no | §9R (D43) |

Headline numbers:

- **One-GPU swap cycle (step 3):** 647 → **5163** MiB (torch) → **579** MiB (Ray's own scale-to-zero, released *below* baseline) → **38909** MiB (tf) → back to torch. Both directions. Same-GPU invariant verified.
- **Alternation (step 5):** 20/20, 0 errors; **median 9.48 s, P90 103.2 s** — bimodal, with the slow path taken by 40 % of requests. The mechanism works; the latency distribution — not reliability — is why the verdict is PARTIAL.
- **Replica death (step 6B):** auto-recovered unattended in ~15 s, with a *new* pid — genuine self-healing, and it stands.
- **Head-node death (step 6A):** operator runbook — `ray stop --force` → `ray start --head` with the cluster's own flags → re-apply the config — plus **109 orphaned containers** in the podman store. This is what makes step 6 FAIL as written.

**What a decision actually rests on** — the costs and constraints, each traced to §2/§3:

1. GPU tools require the **legacy `container` runtime_env key**, not the modern documented `image_uri` (§2, D36). The legacy key is mutually exclusive with `pip`, `working_dir` and most other runtime_env fields — [`runtime_env.py:397-404`](/usr/local/lib/python3.11/site-packages/ray/runtime_env/runtime_env.py:397) permits only `config` and `env_vars` alongside it.
2. Every GPU tool config must carry a **host-specific absolute path** (`--runtime=/usr/bin/nvidia-container-runtime`). Tool configs are not portable across hosts.
3. **P90 swap latency 103 s vs median 9.5 s** — a 12× spread; the slow path is 40 % of requests (§3.5).
4. **Only plain data** (str, int, float, bool, list, dict, bytes) may cross a deployment boundary — a framework-typed value breaks the call (D27, §2).
5. A YAML config setting **any** actor option **silently discards** the tool's declared `image_uri` (D32, §2) — Ray reports RUNNING while the tool runs on the host.
6. **Head-node recovery is not automatic** — an operator runbook: `ray stop --force` → `ray start --head` with the cluster's own flags → **re-apply the config** → poll. Serve applications do not come back by themselves (§3.6).
7. Crashed worker containers are **never removed** (the `image_uri` launcher passes no `--rm`, [`image_uri.py:77-96`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:77)): **109** accumulated across the spike (§3.7).
8. `image_uri` workers need a permission workaround (D22, §2): the cluster must run under `umask 0` (an accepted security trade-off — any local user can reach the raylet socket while it runs) and the session's `logs/` subdirectories must be world-writable, because Ray runs the worker as the image's uid against directories it created 0755 under the cluster's uid.
9. **Version lockstep** (Ray/Python must match the host exactly, down to the patch) is confirmed as a real coupling: the fixtures had to be built from the exact base tag `docker.io/rayproject/ray:2.57.0-py311-gpu` (§3.0).

**The decision under §5, after the corrections.** The frozen rule (restated unedited in §8) says **Rule 1 — Ray wins if steps 3, 5 and 6 all pass.** The recorded verdicts, after the 2026-09-10 corrections (ledger §9S, D44), are: step 3 **PASS**, step 5 **PARTIAL**, step 6 **FAIL as written**. Rule 1's literal condition — all three pass — is **not met**. Rule 2 is not triggered (step 3 passed). The two corrections:

- **Step 5: PASS → PARTIAL.** The pass criterion is "latency ≈ cold start"; cold start measured ~12 s, and 40 % of alternations took 99-104 s. That is §3's own partial case — *"works but with occasional stuck states or latency spikes"* — with the explicit instruction *"Record honestly; do not round to pass or fail."* The original PASS rounded on reliability: completion without stuck states is **necessary** for a pass, not **sufficient**. What remains true and is preserved prominently: the mechanism *does* work — 20/20 displacements, zero errors. The failure is the latency distribution, not reliability.
- **Step 6: PASS → FAIL as written.** The criterion is *"Fail: manual intervention, leaked VRAM, or orphaned containers."* Phase A's recovery was three operator commands (`ray stop --force`, `ray start --head` with the cluster's flags, re-apply the config) — manual intervention, named in the criterion — and 109 orphaned containers were recorded. The harness's "gate CLEAN" came from its own exit-code classification, whose bar is looser than the protocol's. What remains true and is preserved prominently: **replica-level recovery genuinely is automatic** (new pid, ~15 s, unattended, §3.6). The failure is at the **head-node/cluster** level, plus the container litter.

Both corrections ran toward Ray *passing*; the two retracted verdicts in §4 ran the other way. The pattern is not bias toward a conclusion but insufficient discipline in grading against a frozen criterion — recorded in §4.

**The outcome is settled, not a judgment call.** Rule 4 treats a partial step 5 as fail for Rule 1 and escalates under Rule 3; Rule 3 makes a step 6 failure the requester's choice with a price. §8 presents that choice neutrally.

One qualification stands independent of the corrections: step 3's pass is through the **legacy** `container` key only — the modern documented API allocated zero VRAM while Ray reported the replica HEALTHY with `GPU: 1.0` reserved (§3.3, D36).

---

## 2. Findings about Ray — the spike's real output

Four findings, each with mechanism, evidence and consequence. These are the spike's durable output: the step verdicts say *Ray can do it*; these say *at what cost, and where it will bite*. (The task brief labels the fourth finding "D36/D41"; the ledger numbers it D33 — the correction, §9L — and D36 — the passing run, §9N.)

### D22 — `image_uri` workers SIGABRT silently: the image's uid against Ray's 0755 session dirs

**Mechanism.** `image_uri` launches workers with `podman run … --userns=keep-id` and **no `--user`** ([`image_uri.py:76-96`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:76)), so the worker runs as the **image's** `USER` (fixtures: `ray`, uid 1000), not the host's cluster uid (1011). Ray's per-session `logs/events/` and `logs/export_events/` directories are mode **0755** owned by the cluster uid, and the C++ core worker's event writer must open files there. The uid-1000 process gets `EACCES`; `spdlog` throws an **uncaught** `spdlog_ex`; `std::terminate` fires → **SIGABRT (exit 134)** — and the abort message is invisible because Ray's `RayLog` has already redirected fd 2 into a session log file. Symptom: the raylet repeats *"worker … dead, probably crashed during start"* every 60 s, with **no container log and no `.err` file**.

**Evidence** (ledger §§9e–9f). Captured by strace, not inferred:

```
Unhandled exception: N6spdlog9spdlog_exE. what(): Failed opening file
/tmp/ray/session_*/logs/events/event_CORE_WORKER_<pid>.log
for writing: Permission denied
```

Proven by intervention, not correlation: `chmod 777 logs/events` moved the abort to `logs/export_events/` (same exception, next directory); `chmod 777` on *all* `logs/` subdirs eliminated every SIGABRT, and the deployment then failed *differently and visibly*.

**Consequence.** `image_uri` carries an **unenforced precondition** — the host cluster uid must equal the image's `USER` uid — with no check, no escape hatch, and no diagnostic when it fails. Tool images are third-party-authored, so tool-swap cannot assume a particular `USER`. Aggravating: a **log-sink failure is fatal**, and the only diagnostic is emitted after stderr redirection, so the symptom is a silent 134. The workaround taken (`umask 0` plus world-writable session log dirs) is a security trade-off accepted only because the host has trusted users.
**Unconfirmed:** the origin of the 0755 on the two event subdirectories under `umask 0` — most likely created by Ray's C++ side; the Python-side citation first suggested (`event_logger.py:114`) is a `mkdir` with no mode argument. The empirical finding stands; the mechanism of the mode does not.

### D27 — cross-deployment results are pickled: the receiver must import the sender's types

**Mechanism.** Ray Serve passes results between deployments by **pickle**. A value crossing a deployment boundary must be importable by the receiver. The isolation `image_uri` provides is process-level, **not** serialisation-contract-level.

**Evidence** (ledger §9g). `TorchProbe` served its request fine inside its container (`CALL __call__ OK 5.5ms`). The HTTP 500 came from the **ingress** deployment — which runs on the *host*, with no torch installed — while **deserialising the reply**:

```
ray.exceptions.RaySystemError: System error: No module named 'torch'
  File ".../ray/_private/serialization.py", line 361, in _deserialize_pickle5_data
    obj = pickle.loads(in_band)
ModuleNotFoundError: No module named 'torch'
```

The culprit value: [`introspect.py:61`](../spike-e-ray-native/toolkit/introspect.py:61) returns `torch.__version__`, which is **not a `str`** — it is a `torch.torch_version.TorchVersion` instance, so its pickle carries a reference to the torch module. `tensorflow.__version__` *is* a plain `str`, so the tf reply unpickles anywhere. Ray attributes the error to the caller, which is technically correct and diagnostically misleading — the cause was visible only in the *ingress* log, not the failing deployment's.

**Consequence.** A router that calls heterogeneous tools across deployment boundaries would need **every tool's libraries installed in the router** — defeating the purpose of per-tool images. Any boundary between tools must carry **plain data only** (str, int, float, bool, list, dict, bytes), never a framework object, however incidental. This is direct empirical support for [`ADR-0005`](../plan/adr/0005-one-uniform-batched-calling-convention.md): the uniform calling convention is not stylistic tidiness, it is what makes heterogeneous tools composable.
**Caveat, stated plainly:** the fixture is at fault for returning a framework-typed value, and `str(torch.__version__)` makes step 1 pass. That fix does **not** retire the finding — it confirms it. A real tool returning a tensor, a numpy dtype, or any framework object hits exactly this wall.

### D32 — YAML `ray_actor_options` replaces the decorator's wholesale, silently discarding `image_uri`

**Mechanism.** When a YAML config supplies `ray_actor_options`, Ray **replaces** the code-declared actor options — it does not merge them ([`application_state.py:1827-1833`](/usr/local/lib/python3.11/site-packages/ray/serve/_private/application_state.py:1827): `if "ray_actor_options" in options: override_actor_options = options.pop("ray_actor_options", {})`).

**Evidence** (ledger §9j). Step 3's config set `ray_actor_options: {num_gpus: 1}`; the decorator had set `{num_gpus: 1, runtime_env: {image_uri: …}}`. The deployed `runtime_env` contained only `env_vars` — **no `image_uri`**. The replica ran **on the host, in no container at all** (traceback path was the host checkout; `/opt/spike/weights/` exists only inside the fixture images):

```
FileNotFoundError: [Errno 2] No such file or directory: '/opt/spike/weights/ckpt.bin'
```

Ray accepted the deploy and reported **RUNNING** throughout.

**Consequence.** A config setting **any** actor option — a GPU count, a CPU count — silently voids the image the tool author declared, and the tool runs against whatever is on the host. Nothing warns. For tool-swap this lands on the exact axis the project exists for: *which environment a tool executes in*. Step 1 passed only because its YAML names `image_uri` inside `ray_actor_options`, so the replacement lost nothing.

### D36 — `image_uri` cannot give a container a GPU; the legacy `container` key can (correction D33)

**Mechanism.** [`ImageURIPlugin.modify_context`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:174) hardcodes `run_options=[]` ([`image_uri.py:174`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:174)), so `--runtime`, `--device` and `--gpus` are **structurally unreachable** through `image_uri`. The **legacy `container` key forwards run options** ([`image_uri.py:222-229`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:222)), so it can name `--runtime=/usr/bin/nvidia-container-runtime` — which is what injects both the GPU devices and the driver libraries on this host.

**Evidence** (ledger §§9L, 9N). Six GPU-passthrough mechanisms were tested; only the nvidia-container-runtime works (podman 3.4.4 does not implement `--gpus`, predates CDI so `nvidia.com/gpu=N` is treated as a path, raw device nodes lack the driver libraries). Measured on the gate: the `image_uri` run moved GPU 0 VRAM 647 → 579 MiB (**nothing** allocated), while the `container`-key run moved 579 → 5163 MiB (**+4516**, matching the tool's 4096 MiB allocation plus CUDA context).

**Consequence — including the silent half.** In *both* runs, Ray **reserved `GPU: 1.0`** for the replica, set `CUDA_VISIBLE_DEVICES`, and reported the replica **HEALTHY**. In the `image_uri` run, the "allocated" A100 did zero bytes of work and the tool ran on CPU. A scheduler built on the modern API would hand out GPUs its tools cannot use, and never know. Hence §1 items 1–2: adopting Ray for GPU tools means depending on the older API, mutually exclusive with most of the runtime_env, with a host-specific absolute path in every tool config.

---

## 3. Per-step detail

### 3.0 Environment and fixtures

| Item | Value |
|---|---|
| Ray | 2.57.0 — hardcodes `container_driver = "podman"` at [`image_uri.py:76`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:76) |
| Host Python | 3.11 (`/usr/local/lib/python3.11`) |
| Podman | 3.4.4, **rootless** (`runRoot: /run/user/1011`), pre-CDI |
| GPU | 8× A100-40GB; the gate ran on one |
| NVIDIA driver | 565.57.01 |
| Host uid | 1011 (user `mgaron`); fixture images' `USER` is `ray`, uid 1000 |
| Base image | `docker.io/rayproject/ray:2.57.0-py311-gpu` (D17: podman does not assume Docker Hub for short names without unqualified-search registries) |
| Also on the host | Docker 27.5.1 with 9 running containers — unaffected throughout (step 7) |
| Storage driver | `overlay`, `Native Overlay Diff: true` (step 7) |

Fixtures: two images from the Ray base — `tool_torch` (torch 2.8.0+cu129) and `tool_tf` (tensorflow 2.16.2) — each baking in 8 MiB of weights and a 64 MiB payload built with **different seeds** (D14), plus a baked-in `image_marker` (`SPIKE_IMAGE_MARKER`) that cannot be set through `runtime_env`, so it proves *which image served the request*. Per the scope amendment preserved in §10.1, weights and payloads are baked in, not fetched: no S3/MinIO, no `boto3`, no credential plumbing.

The verbatim `make env` capture lives in gitignored `spike-e-ray-native/results/raw/`; the values above are as recorded in the ledger and the env capture.

### 3.1 Step 1 — per-deployment `image_uri` — **PASS** (informative, Rule 5)

Protocol §3 step 1: one application, two deployments, each with a different `image_uri`; **pass** if each deployment reports its own image's contents.

`make step1` → exit 0. Both probes answered from their own containers:

| | TorchProbe | TfProbe |
|---|---|---|
| `image_marker` | `tool_torch` | `tool_tf` |
| framework / version | torch 2.8.0+cu129 | tensorflow 2.16.2 |
| `sys_executable` | `/home/ray/anaconda3/bin/python` | `/home/ray/anaconda3/bin/python` |
| pid | 4084930 | 4086817 |

**Verdict: CONFIRMED** (ledger §9h). `SPIKE_IMAGE_MARKER` is baked in at build time and cannot be set through `runtime_env`, so it proves *which image served the request*, not merely that configuration was accepted. `sys_executable` confirms both ran the container's interpreter, not the host's; distinct pids confirm separate processes. Both configuration forms (decorator/`ray_actor_options` and YAML) were accepted. Deployments took **12 polls (~60 s)** to reach RUNNING from a warm image cache.

**What this does NOT establish:** only that per-deployment `image_uri` is possible. The D27 constraint (plain data only across boundaries) applies to every later step. And D32 explains why step 1 passed where step 3's first run failed: step 1's YAML names `image_uri` *inside* `ray_actor_options`, so the wholesale replacement lost nothing.

### 3.2 Step 2 — app builder, baked weights — **PASS** (informative, Rule 5)

`make step2` → exit 0.

| | tool_torch | tool_tf |
|---|---|---|
| `image_marker` | `tool_torch` | `tool_tf` |
| `weights_sha256` | `43d5b7a712b5ded7…` | `83faf8738805e750…` |
| `weights_bytes` | 8388608 | 8388608 |
| `init_total_seconds` | 1.83 | 2.72 |
| `vram_allocated_mb` | 0 | 0 |

**Verdict: CONFIRMED** (ledger §9i). A **generic** builder — [`step2_builder.py`](../spike-e-ray-native/apps/step2_builder.py), which imports neither framework — built two applications from one `import_path` with different `args`, each landing in its own image with its own weights. **Same byte count, different SHA-256:** the two images genuinely hold different bytes at the same path, and each replica read its own. That is the isolation proof — and it is the check that could never have passed before D21 fixed the op being called (§5.1, item 2). (`vram_allocated_mb: 0` is correct: CPU-only replicas, honestly reported.) The weights-load times are local disk reads — per §10.1, **not** a thrash-pricing figure.

**A claim this step does NOT make.** "The strict builder may run in the tool's image" is **refused as a result**. The strict variant (imports `torch` at function scope) got `serve deploy` exit 0, but exit 0 means the request was *accepted* — not that the builder ran, nor where it ran; and the driver's host venv **has torch installed**, so a host-side import succeeds for a reason that says nothing about images. Settling where builders execute needs a negative control: a builder importing a package absent from *both* the host venv and the target image, plus confirmation the app reaches RUNNING. Recorded as an **open question**, not a finding (ledger §9i).

### 3.3 Step 3 — 🚪 GATE: two conflicting tools, one GPU — **PASS** (Rule 2), via the legacy `container` key

This gate had two failed runs before it passed, and **both failures were our own measurement errors, retracted on the record** (§4). The passing run (ledger §9N, D36): `make step3-container` → exit 0, `gate CLEAN`. The same-GPU invariant (D31) confirms contention was genuinely tested:

```
Same-GPU invariant (D31): tool_torch anchored to GPU 0,
tool_tf anchored to GPU 0 — SAME GPU, contention tested.
```

The measured cycle, GPU 0 throughout:

| Phase | GPU 0 VRAM | Evidence |
|---|---|---|
| baseline (both at 0 replicas) | 647 MiB | — |
| `tool_torch` serving | **5163 MiB** | +4516; `image_marker: tool_torch`; cold start 11.1 s |
| after Ray's own scale-to-zero | **579 MiB** | released *below* baseline; `DOWNSCALE_COMPLETED` observed at 80 s (incl. a `STOPPING` transition), `target_num_replicas: 0`, `replicas: []` |
| `tool_tf` serving | **38909 MiB** | `image_marker: tool_tf`; cold start 12.3 s |
| alternate back to `tool_torch` | served | `image_marker: tool_torch`; probe 84.2 s |

**Verdict: CONFIRMED** — every element the gate demanded:

- **GPU reached the container** — VRAM actually moved, and `cuda_visible_devices: "0"` printed from inside a container that also reported its own baked-in marker.
- **VRAM was held** — +4516 MiB on the attributed GPU, matching the 4096 MiB allocation plus CUDA context.
- **VRAM was released — because Ray decided to.** The gate polled `target_num_replicas` until `DOWNSCALE_COMPLETED` instead of sleeping a fixed period — the fix that turned §4's false negative into a real result.
- **The swap worked both ways** — tf occupied the same GPU after torch released it, then torch returned. Repeatable, not a one-shot.
- **Contention was real** — single-GPU cluster plus the anchor invariant.

**Costs observed.** Cold starts ~11–12 s per tool from a warm image cache. The alternate-back probe took **84.2 s** because it had to wait out the incumbent's scale-to-zero (~80 s: the 15 s `look_back_period_s` metric decay + 60 s `downscale_to_zero_delay_s`) before the GPU freed. **That is the swap latency Ray's autoscaler imposes by default** — the number that matters for tool-swap's TTL design, not the 11 s cold start. `downscale_to_zero_delay_s` is tunable; the metric-decay component is not.

**The caveat that must travel with this pass.** The result is reachable **only through Ray's legacy `container` runtime_env key**, because it accepts `run_options` and can pass `--runtime=/usr/bin/nvidia-container-runtime`. The modern, documented `image_uri` key **cannot** (D36, §2). Consequences in §1 items 1–2: the legacy key is mutually exclusive with `pip`, `working_dir` and most other runtime_env fields, and its run options are a host-specific absolute path.

### 3.4 Step 4 — payload read — **PASS** (informative, Rule 5; **D18 not tested**)

`make step4` → exit 0 (self-contained after D38: it deploys the container-key config itself and waits for readiness before probing).

| Read | Time | Size (bytes) | sha256 |
|---|---|---|---|
| 1 | 0.122 s | 67108864 | `363824c7a5e0bbdc…` |
| 2 | 0.097 s | 67108864 | `363824c7a5e0bbdc…` |
| 3 | 0.095 s | 67108864 | `363824c7a5e0bbdc…` |

**Verdict: CONFIRMED, narrowly** (ledger §9O). A containerised tool can read and verify a **64 MiB** baked-in payload from inside its image, fast and repeatably: identical hash across all three reads, each verified against the image's sidecar `.meta.json` (`hash_match`/`size_match`), so the tool genuinely read its own bytes rather than reporting a cached value. The first read is slower (0.122 vs 0.095) — page-cache warming.

**What this deliberately does NOT establish — the step says so itself:** D18 (payload-by-reference via `s3://` URI) was **NOT** tested. Reason: the §10.1 scope reduction — weights and payloads are baked in; the credential plumbing via `env_vars` was never exercised. **D18 remains an open assumption.** These numbers are **local disk reads inside a container**, not the cost of fetching a payload at request time. Any latency budget that cites 0.097 s must not also assume remote payloads.

### 3.5 Step 5 — preemption at cadence — **PARTIAL** (corrected from PASS per §9S; the P90 is the cost)

`SPIKE_STEP5_MAX_ERRORS=2 make step5` → exit 0. **20/20 alternations, zero failures** — the tolerance was never needed (ledger §9Q, D42).

Per-cycle end-to-end latency, verbatim from the run:

| # | target | s | # | target | s |
|---|---|---|---|---|---|
| 1 | torch | 5.853 | 11 | torch | 8.279 |
| 2 | tf | 99.470 | 12 | tf | 9.370 |
| 3 | torch | 8.557 | 13 | torch | 101.192 |
| 4 | tf | 9.481 | 14 | tf | 101.316 |
| 5 | torch | 100.507 | 15 | torch | 8.363 |
| 6 | tf | 9.385 | 16 | tf | 9.417 |
| 7 | torch | 8.513 | 17 | torch | 100.824 |
| 8 | tf | 103.245 | 18 | tf | 9.592 |
| 9 | torch | 8.570 | 19 | torch | 8.451 |
| 10 | tf | 101.570 | 20 | tf | 103.587 |

| Statistic | Value |
|---|---|
| min | 5.85 s |
| **median** | **9.48 s** |
| **P90** | **103.2 s** |
| max | 103.6 s |

**The latency distribution is the most important number the spike produced.** Two clean clusters, nothing in between: ~12 cycles at 6–10 s, ~8 at 99–104 s. A **12× spread**, and the slow path is not an outlier — it is **40 % of requests**. A mean (~45 s) would describe no actual request; the median alone would hide a 100-second tail that nearly half of all requests hit. For a router that must answer requests on demand, **P90 is the number that matters, and it is 103 seconds.**

**What causes the split — a hypothesis, not a conclusion.** The ~100 s cluster closely matches step 3's measured ~80 s scale-to-zero plus a ~12 s cold start (step 3 independently recorded an 84.2 s alternate-back for the same reason). The likely mechanism: a cycle is fast when the target's container is still warm, slow when the incumbent must be fully torn down and the target cold-started. **This is not proven here** — the step records per-cycle end-to-end latency only, not the underlying replica transitions. Attributing the split needs a run that also samples `target_num_replicas` per cycle, before any sizing work leans on it.

**What this step tests — the script says so itself, and it is right to:**

> With `external_scaler_enabled`, the `downscale_to_zero_delay_s` timer does not exist. The incumbent is displaced by explicit scale-to-zero, not by the timer expiring. This tests whether Ray can be **driven** to preempt at cadence, not whether its own timer is **pre-emptible**.

That distinction is load-bearing: an external scheduler *can* drive displacement (the architecture tool-swap would use) — but this does **not** show that Ray's own autoscaler yields to a higher-priority request. The latter remains untested. Also recorded as the protocol requires: `external_scaler_enabled` **forbids Serve's own autoscaling** for the affected apps.

**Mechanism B** (declarative config re-apply) was **not implemented** — the run says so rather than quietly skipping. Step 5 answers the external-scaler question only.

**Verdict: PARTIAL** (corrected from PASS; ledger §9S, D44). The pass criterion is *"20 alternations complete with no stuck states and latency ≈ cold start."* Cold start measured ~12 s (§3.3); 40 % of alternations took 99-104 s. That is §3 as written's partial case — *"works but with occasional stuck states or latency spikes"* — and §3 says *"Record honestly; do not round to pass or fail."* The original PASS rounded on reliability: completion without stuck states is **necessary** for a pass, not **sufficient**. What must not be lost: the mechanism *does* work — 20/20 displacements, zero errors. The failure is the latency distribution, not reliability. Rule 4 treats a partial step 5 as fail for Rule 1 and escalates under Rule 3 (§8).

### 3.6 Step 6 — 🚪 GATE: restart and recovery — **FAIL (as written)** (corrected from PASS per §9S; Rule 3 kind)

This is the step the protocol predicted would fail (Rule 0.5). It did — at the level the written criterion names — and by the protocol's own terms that failure routes the decision to the requester, not to the spike. `make step6` → exit 0, `gate CLEAN` (the harness's own classification; ledger §9P, D41); against §3 as written the verdict is **FAIL**, corrected per §9S (D44). Under Rule 0.5 a failure here is *weak evidence* by the protocol's own terms — recorded for balance: the prediction was right, which lowers the evidential weight of the failure, but not the operational facts it rests on (the runbook, the 109 containers).

**Phase A — head node (GCS server) killed; operator recovery.** `kill -9` on the GCS pid (raylet, dashboard and workers survive). The pre-kill state was genuinely live: apps RUNNING, a replica woken by a request, VRAM **913 → 5163 MiB**. Recovery is the documented operator procedure, four steps, all exit 0:

```
ray stop --force  →  ray start --head (with the cluster's own flags, e.g. --num-gpus=1)
  →  re-apply the config  →  poll
```

Apps back to RUNNING after **2 polls (~10 s)**, and VRAM **647 → 5163 MiB** again after a wake-up request. `No manual steps required` beyond the scripted procedure — **but the procedure is the finding:** `ray start` alone is *not* enough (an earlier run proved it: *"Ray is trying to start … but is already running"*, because `kill -9` on the head pid leaves GCS, raylet and dashboard alive), and **Serve applications do not come back by themselves** — the config must be re-applied. For an unattended deployment, a supervisor must own that runbook; Ray will not do it for you.

**Phase B — replica killed; unattended recovery.** The trace is the evidence:

```
kill -9 3437362: process gone 2s after the kill
  [1] HEALTHY, UPSCALE_COMPLETED, PID: 3437362, RUNNING
      (the killed PID is still reported — not a replacement)
  [2] UNHEALTHY, HEALTH_CHECK_FAILED, PID: None, STARTING
      recent_dead_replicas: [... replica_id i3klx8ni, STOPPED, pid 3437362]
  [3] HEALTHY, PID: 3439230, RUNNING
  Recovery confirmed — replacement PID 3439230 (killed PID was 3437362)
```

Ray replaced the killed replica **unattended in ~15 s**: it detected the death (`HEALTH_CHECK_FAILED`), recorded the corpse in `recent_dead_replicas`, and started a fresh replica with a **new pid**. The kill was verified to have landed (`process gone 2s after the kill`), so the recovery is a response to a real death. The D40 fix — requiring a *different* pid — is what made this check falsifiable in the first place (§5.1, item 3).

**What the run showed — two different properties, and only one is automatic:**

- **Replica death → automatic.** Ray notices and replaces it with no human involvement. Genuine self-healing.
- **Head-node/GCS death → operator-driven.** The runbook above, including the config re-apply.

**Verdict: FAIL as written** (corrected from PASS; ledger §9S, D44). §3's written criterion says *"Fail: manual intervention, leaked VRAM, or orphaned containers."* Phase A's recovery was three operator commands — `ray stop --force`, `ray start --head` with the cluster's own flags, and the config re-apply — **manual intervention, named in the criterion**. Separately, **109 orphaned containers** were recorded in the podman store; that count comes from step 7's output (§3.7), captured there incidentally, and is cited here as satisfying protocol step 6.3's orphaned-container requirement **by reference** — the record gap the ledger notes is closed by that reference. The harness's `gate CLEAN` came from its own exit-code classification, whose bar is looser than the protocol's. The tension this section once flagged is no longer open — it is the recorded verdict.

What must not be lost in the correction: **replica-level recovery genuinely is automatic** — phase B: new pid, ~15 s, unattended, in response to a verified death. The failure is specifically at the **head-node/cluster** level, plus the container litter. The honest statement is: *automatic recovery from replica death; operator-driven recovery from cluster death; containers accumulate without bound.*

### 3.7 Step 7 — shared-node fitness — record only, no verdict

`make step7` → exit 0; step 7 **produces no pass/fail by design** — it is a shared-node fitness record (ledger §9R, D43). Three facts observed:

1. **Docker and rootless podman coexist.** Docker 27.5.1 with **9 running containers** (`vllm-openai`, `llama-swap:unified-cuda`, `qdrant`, devcontainers) was unaffected by podman use — checked before and after. The host is shared; tool-swap would never be its only tenant.
2. **`--privileged` is not required** for the host-raylet topology: podman is rootless, driven by the host user. *Inferred from configuration, not from a run that tried without it.* A **devcontainer-hosted** raylet *would* need `--privileged` plus a `/var/lib/containers` mount.
3. **Storage driver is `overlay`**, `Native Overlay Diff: true`. Ray documents *"very slow or hanging container startup"* under `vfs` — so this host is on the good path, which matters because the ~12 s cold starts (and the step-5 figures built on them) implicitly depend on it.

Also in the output: the podman store now holds **109 stopped containers** and 120 images — the no-`--rm` accumulation from Ray's `image_uri` worker launches ([`image_uri.py:77-96`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:77)) compounding across the spike. Harmless on this host, unbounded in principle. **This count also serves as the `podman ps -a` orphaned-container count that protocol step 6.3 asks to be recorded for step 6** — captured here incidentally and cited from §3.6 as satisfying 6.3 by reference (ledger §9S).

Three things the step explicitly did **not** do, and says so instead of pretending: the **vfs-vs-overlay A/B** (requires temporarily switching the storage driver on a shared host — should be done on a disposable machine); the **`/tmp/ray` permission check** (described but never exercised — though D22 hit the *same class* of uid failure for real, so the concern is genuine and this version of it stays unverified); and a **real `--privileged` experiment**.

**A correction to the manager's own framing, recorded rather than dropped:** step 7 was described to the user as a "plain podman baseline" to compare against Ray's latency. It is not, and **no such baseline exists in this spike**. How much of step 5's 103 s P90 is Ray's orchestration versus the cost of starting a 14–19 GB container is **not attributed, and cannot be, from this data.**

> **Superseded 2026-09-14:** *true as of this 2026-09-10 rewrite.* **Step 8 (D45, ledger §9T) is that plain-podman baseline**, run afterwards: the ~95 s excess is attributed to Ray, not to container lifecycle (~15× on P90, with the comparison's limits stated in the ledger). The attribution lives in the ledger and the analysis, not in this document, which remains frozen at steps 1–7.

---

## 4. The two retracted verdicts

Twice on this spike I recorded "Ray fails the decisive gate" and twice withdrew it. Both were **my measurement faults, not Ray's behaviour**. They are given prominence here because they are the best evidence of how much weight a naive "the gate failed" reading of this spike would carry, and because the correction process is part of the record.

**Retraction 1 (ledger §9k → corrected in §9L, D33).** I recorded that a GPU **cannot** reach a podman container on this host, and that `image_uri` therefore fails the gate — committed as a decisive framework-killing verdict (`2bc79d6`). The user pushed back (*"podman is supposed to support GPUs"*) and was right to: I had tested five GPU-passthrough mechanisms but not the one the host actually supports. The decisive test — `podman run --rm --runtime /usr/bin/nvidia-container-runtime …` on **our own fixture image** — returned `cuda: True`, exactly **1** GPU. The container was never the obstacle; **the missing `--runtime` flag was**, and Ray's modern API structurally cannot supply it (D36). *Corrected attribution: the host can give a container a GPU; `image_uri` cannot ask for it.*

**Retraction 2 (ledger §9M, D35).** The first `container`-key run recorded *"VRAM was NOT released on GPU 0 after downscale to zero: 5163 MiB after idle vs 579 MiB baseline"* — a Rule 2 fail. It was not: the gate measured **before Ray was due to release anything**. Per [`autoscaling_policy.py:124-130`](/usr/local/lib/python3.11/site-packages/ray/serve/autoscaling_policy.py:124), the 60 s `downscale_to_zero_delay_s` clock starts only when Ray *first wants* to scale down — which requires the request-rate metric to decay over the 15 s `look_back_period_s` first. Earliest possible release: **~75–80 s**. The gate had waited **65 s**. The run's own data proved the replica had not been asked to stop: `"target_num_replicas": 1`, replica `"state": "RUNNING"`. **The VRAM was still held because the tool was still running by Ray's own intent — correct behaviour, misread as a leak.** The fix (poll `target_num_replicas` until `DOWNSCALE_COMPLETED` instead of sleeping a fixed period) is what produced the real pass in §3.3.

**The pattern, and the rule carried forward.** Both times the tell was already in the data: a VRAM delta of *minus* 68 MiB in the first run, and `target_num_replicas: 1` in the second. Before accepting a decisive negative, verify the system was actually *asked* to do the thing being measured. **A gate that fires on the wrong side of a timing boundary is a random number generator with a persuasive label.**

**The same lesson, from the other direction (ledger §9S, D44).** The two retracted verdicts above ran toward Ray *failing*; the two corrected verdicts — step 5 PASS→PARTIAL, step 6 PASS→FAIL as written — ran toward Ray *passing*. So the pattern is not bias toward a conclusion but **insufficient discipline in grading against a frozen criterion**, in both directions. Both pairs were caught only because a second mode read the protocol independently instead of trusting the summary. That argues for the Rule 5 freeze, not against it.

---

## 5. Honest limits — what this spike cannot claim

### 5.1 Three unfalsifiable checks in our own harness — all passing at the time

Three checks **could not fail**, and all three were **passing** when they were found. Each was fixed and the affected step re-run:

| # | Check (ledger) | Why it was unfalsifiable | Fix |
|---|---|---|---|
| 1 | Step 1 (D21, §9e) | `make step1` exited **0** while *both* probes timed out — every error caught, printed, recorded, **swallowed**; nothing mapped a recorded error to the exit status. A broken run was indistinguishable from a passing one | Exit codes now mean something: **2** harness failure (observation could not be made), **3** negative finding (observation made, answers the step negatively), 0 clean, 1 crash |
| 2 | Step 2 (D21, §9e) | Compared `weights_sha256` against the **`introspect`** op, which **never returns that field** — only `startup_report` does ([`deployments.py:118`](../spike-e-ray-native/toolkit/deployments.py:118), field at [`:137`](../spike-e-ray-native/toolkit/deployments.py:137)). The central isolation comparison could **never** have succeeded on any cluster — and it still exited 0 | Call the op that returns the field |
| 3 | Step 6 phase B (D40, §9P) | Confirmed "recovery" using the pid it had **just killed** — poll 1 reported the dead pid as RUNNING (stale read) and satisfied the check | Require a **different** pid |

The existence of three unfalsifiable checks, all green, is why every verdict in this document carries the exit-code and pid discipline above — and why the ratio in §6 is what it is.

### 5.2 What was never tested

| Item | Status | Why it matters |
|---|---|---|
| D18 payload-by-reference (`s3://`) | **Not tested** — scope-reduced (§10.1) | **No fetch cost is known.** Step 4's numbers are local disk reads; any thrash pricing that assumes remote payloads is unpriced |
| Step 5 mechanism B (config re-apply) | **Not implemented** (a printed stub) | Only the external-scaler path is measured; the "re-apply the whole config" alternative is unmeasured |
| Ray's *own* autoscaler timer being pre-emptible | **Not tested** | Step 5 shows Ray can be **driven** to preempt; it does not show its own timer yields to a higher-priority request |
| Strict builder (where builders execute) | **Not settled** — needs a negative control | §3.2 records the claim as *refused*, not found |
| Podman-vs-Ray latency baseline | **Does not exist** — step 7 is not one (§3.7) | The 103 s P90 is **not attributed** between orchestration and container startup |
| `vfs` vs `overlay` storage driver | **Not A/B'd** (would mutate a shared host) | The ~12 s cold starts implicitly depend on `overlay`; a `vfs` host would likely be far worse |
| The **Docker** path for `image_uri` | **Untested and unreachable** — Ray hardcodes `container_driver = "podman"` ([`image_uri.py:76`](/usr/local/lib/python3.11/site-packages/ray/_private/runtime_env/image_uri.py:76)) | The single biggest caveat on D36: under Docker with `nvidia-container-runtime` as default runtime, library injection can occur without an explicit flag |
| `/tmp/ray` permission failure mode (step 7) | Described, **not exercised** | Same failure class as D22, which did hit for real |
| Origin of the 0755 event dirs (D22) | **Unconfirmed** — most likely Ray's C++ side | The empirical finding stands; the mechanism of the mode does not |

### 5.3 Environment specificity

Every number in this document is bound to: **Ray 2.57.0, rootless podman 3.4.4 (pre-CDI: `--gpus` unimplemented, `nvidia.com/gpu=N` treated as a path), 8× A100-40GB, NVIDIA driver 565.57.01, host uid 1011 vs image uid 1000, `overlay` storage driver, warm image cache.** Specifically:

- **D36's scope:** a podman ≥4.x host *might* reach a GPU via CDI *if Ray passed the device* — but Ray passes none and `run_options` is hardcoded empty, so the Ray-side blocker stands independently of the podman version. The **Docker** path is where the verdict might not hold, and it is unreachable here.
- **D22's failure mode** presupposes a uid mismatch between host and image. A host whose cluster uid matched the image's `USER` would not hit it — which makes the unenforced-precondition problem worse, not better, for third-party-authored tool images.
- **The step-5 latency figures** depend on the `overlay` driver and a warm image cache.

### 5.4 Hypotheses, labelled as hypotheses

- The bimodal step-5 latency (warm-target vs cold-start mechanism) — **hypothesis**, §3.5.
- The 84.2 s alternate-back as "Ray's default swap latency" — measured once, as one instance; a distribution would be needed before it is budgeted.
- "`--privileged` not required" — inferred from configuration, §3.7 fact 2.

---

## 6. Cost of evaluation: the defect ratio

**~43 defects** (D1–D43 across [`spike-E-continuation.md`](spike-E-continuation.md); the ledger's D44 entry, §9S, is the 2026-09-10 verdict correction, not a harness defect) were found and fixed for seven steps to produce trustworthy output. Of them, a handful are findings **about Ray** — the four in §2 (D22, D27, D32, D36, with the D33 correction) — and **most were ours**: harness bugs, config omissions, wrong URLs, wrong ops, wrong exit codes, and host-environment friction. The ledger's own accounting at the step-1 milestone: seven fixes stood between "the plan says this should work" and the first real result — **two** were findings about Ray (D20/D22) and **five** were ours (§9h).

Four consecutive *host-only* blockers (D16–D19 — a shell variable collision, podman's short-name strictness, an unprivileged-user permission, a sticky-bit unlink) could not have been caught by local verification, and none is a finding about Ray (§§9c–9d). They are the cost of the "run it on the real host" step the protocol demands, and they are recorded so the results document does not mistake harness friction for evidence about the framework.

**The ratio is itself a result.** It speaks to the cost of evaluating this stack carefully: most of what looked like "Ray's behaviour" along the way was our scaffolding, and the two would-be decisive "Ray fails" verdicts were our own measurement faults. A reader weighing the §8 decision should weight Ray accordingly — the findings in §2 are what Ray actually showed; everything else was the price of getting Ray's numbers at all.

---

## 7. Measured times (protocol §4 item 3)

| Measurement | Step | Samples | Median | Min | Max | Notes |
|---|---|---|---|---|---|---|
| Weights load (baked, local disk) | 2 | 2 apps | — | 1.83 s | 2.72 s | local read only — **not** a thrash-pricing figure (§10.1) |
| Cold start, container (warm cache) | 3 | 2 tools | — | 11.1 s | 12.3 s | torch 11.1 / tf 12.3 |
| Alternate-back after incumbent's scale-to-zero | 3 | 1 | 84.2 s | 84.2 s | 84.2 s | ~80 s downscale + ~12 s cold start |
| VRAM-returned-to-baseline after idle | 3 | 1 | observed at 80 s | — | — | `DOWNSCALE_COMPLETED`; 579 MiB, *below* the 647 MiB baseline |
| Local payload read (64 MiB baked) | 4 | 3 | 0.097 s | 0.095 s | 0.122 s | page-cache warming on the first read |
| Preemption latency, mechanism A | 5 | 20 | 9.48 s | 5.85 s | 103.6 s | **P90 103.2 s; bimodal — slow path is 40 % of requests** → PARTIAL per §3 as written (§3.5) |
| Preemption latency, mechanism B | 5 | — | — | — | — | **not implemented** |
| Replica-actor recovery | 6B | 1 | ~15 s | — | — | unattended; new pid |
| Head-node (GCS) recovery, time to RUNNING after the 4-step procedure | 6A | 1 | ~10 s | — | — | the procedure itself is operator time — the manual intervention that FAILs step 6 as written |
| Image cold start, `vfs` vs `overlay` | 7 | — | — | — | — | **not A/B'd** (shared host) |
| ~~Weights fetch (~2 GB, MinIO)~~ | ~~2~~ | — | — | — | — | **removed by §10.1**; no remote fetch exists |

---

## 8. Decision under §5 — the frozen rule, restated unedited

The protocol's §5, frozen by Rule 0.1 (restated here, unedited):

- **Rule 1 — Ray wins if steps 3, 5 and 6 all pass.** Then: adopt Ray Serve as the lifecycle engine. **Delete from scope:** the container backend and lifecycle manager (M2), the BentoML spike (M3.5), the proxy internals (M3), the TTL watchdog (M6), the log collector (M7). **Retain:** `tools.yaml` and the schema compiler (M1), the authoring ladder (M5), preflight (M5.5), the CLI (M8), the API surface (M9) and the eviction policy — re-homed as a Ray autoscaling policy. Supersede [ADR-0001](../plan/adr/0001-build-our-own-router.md) and [ADR-0003](../plan/adr/0003-ray-serve-not-adopted.md) with a new ADR recording this spike as the basis.
- **Rule 2 — Ray loses if step 3 fails.** *(Not triggered: step 3 passed, §3.3.)*
- **Rule 3 — If step 6 fails but 3 and 5 pass, the decision goes to the requester with a priced choice**, and *not* to the spike. The options, presented neutrally:

  | Option | Cost |
  |---|---|
  | **(a)** Accept manual recovery | An operational runbook step after any cluster failure — measured: three operator commands plus config re-apply, and Serve applications do not come back by themselves; orphaned containers accumulate (109 by the end of the spike, no `--rm`); possible VRAM leak until noticed |
  | **(b)** Adopt KubeRay | Kubernetes on the shared DGX — the thing both the requester and the engineer rejected as too heavy |
  | **(c)** Keep our router | The status quo, with ~a third more code than Ray-native |

  **Option (c) must not be chosen by default.**
- **Rule 4 — If step 5 is partial**, treat it as fail for Rule 1 but record the specifics, because "occasional stuck states" may be fixable with a retry in our controller. Escalate under Rule 3 rather than deciding alone.
- **Rule 5 — Steps 1, 2, 4 and 7 do not decide anything.**

**Application to the corrected verdicts.** The recorded verdicts (ledger §9S, D44) are: step 3 **PASS**, step 5 **PARTIAL**, step 6 **FAIL as written**. Rule 1 — *Ray wins if steps 3, 5 and 6 all pass* — is **not met**: 5 does not pass, and 6 fails. Rule 2 is not triggered: step 3 passed.

The rule application is no longer a question of which side of a line the results sit on — it is settled:

- **Rule 4** applies to step 5: a partial step is treated as fail for Rule 1, the specifics are recorded (the P90 103 s bimodal distribution — Rule 4's point being that such spikes "may be fixable with a retry in our controller"), and the matter is escalated under Rule 3.
- **Rule 3** applies to step 6: the decision goes to the requester with a priced choice, not to the spike. (Rule 3's literal wording — *"if step 6 fails but 3 and 5 pass"* — is met in all but the state of step 5: step 5 is partial, and Rule 4's explicit escalation clause ("Escalate under Rule 3 rather than deciding alone") exists precisely to route that combination to the same place. Both rules point at the same outcome, so the routing does not depend on a looser reading of either.)

Both paths land in the same place. **The decision now required** is the priced choice set out under Rule 3 above: (a) accept manual recovery, (b) adopt KubeRay, (c) keep our router — with the measured costs recorded in §3.5 (the 103 s P90) and §3.6 (the runbook and the 109-container litter). **Option (c) must not be chosen by default.**

One qualification stands independent of the corrections: step 3 passed through the **legacy** API only (§3.3, D36) — the capability is real, but the modern documented path cannot host GPU tools on this host. This does not change which rule fires; it changes what "Ray wins" would mean in practice.

**This document does not choose.** It presents the measurements, the corrected verdicts and the frozen rule, and leaves the choice to the requester — as the protocol requires wherever Rule 3 or 4 is in play.

---

## 9. How the evidence bears on ADR-0003

[ADR-0003](../plan/adr/0003-ray-serve-not-adopted.md) was settled on **maintainability** grounds, with capability concessions (*"Ray can containerise each tool, deploy tools independently, and host a scheduler policy. None of that is in dispute"*) and a single stated falsifier: a production-viable per-deployment OCI image boundary that **composes with per-device GPU pinning**. The spike bears on it as follows (distilled; the full reasoning accompanies the ADR revision separately):

- **Supports — with measurements replacing doc-citations, and with the corrected verdicts.** The recovery objection is now a **recorded gate failure, not a qualification**: step 6 **FAILs as written** — head-node recovery is operator-driven (three commands plus config re-apply; Serve applications do not come back by themselves) with **109 orphaned containers** (§3.6, §9S). Step 5's **PARTIAL** prices the preemption-cost objection with a gate measurement rather than a doc-citation: P90 103 s, bimodal, slow path 40 % of requests (§3.5, §9S). Both bear directly on the ADR's operational-cost argument, and the correction strengthens this side. The version-lockstep coupling: the fixtures had to be built from the exact base tag (§3.0). The experimental-API risk: **understated in the ADR** — the modern path structurally cannot host GPU tools (D36), the working path is the deprecated legacy key, and it carries the silent-replacement trap (D32). And D27 is a cost the ADR did not have: a Ray-native router would need **every tool's libraries** to aggregate heterogeneous results — a strong independent argument for the plain-data boundary [`ADR-0005`](../plan/adr/0005-one-uniform-batched-calling-convention.md) mandates.
- **Complicates — corrects the ADR's capability table.** The fork's *"Path 1: allocation, not preemption — a replica waits for a held GPU, exactly as a Kubernetes pod goes Pending"* is **refuted as stated** for the externally-driven case: step 5 drove 20/20 displacements at cadence. What survives is the cost: P90 103 s. The ADR's supersession trigger — *"If displacement across applications turns out to be achievable at acceptable cost, this ADR should be superseded"* — is now a **priced** question, not an open one.
- **The falsifier half-fired.** The per-deployment OCI boundary: **confirmed** (step 1). It composes with GPU pinning: **only via the legacy key**, at the mutual-exclusion and portability costs in §1. By the ADR's own terms (*"if it came back the other way, this document is wrong and should be rewritten rather than patched"*), revision is warranted — and is being done separately.
- **Undermines — nothing.** No result in this spike shows Ray *cannot* do the core loop. A maintained decision rests on the measured costs (§1) and the rule application in §8 — not on capability.

---

## 10. Records preserved from the pre-run file

### 10.1 Scope amendments (2026-08-14), unchanged

Per [`spike-e-ray-native/README.md`](../spike-e-ray-native/README.md:6) §0a (2026-08-14):

- Weights and payload are **baked into the container images at build time**. There is no S3/MinIO, no `boto3`, and no credential plumbing in this spike.
- Step 2 no longer measures weight-fetch latency (a local disk read of ~8 MB replaces a ~2 GB network fetch); its timing is **not** a thrash-pricing figure.
- Step 4 no longer tests D18 payload-by-reference; it reads a baked-in local file. **D18 remains an untested assumption.**
- Steps 3 and 5 are therefore optimistic relative to production (no cold-start weight download), which is fair because the same download is absent from our own router too.
- The §5 decision rule (steps 3, 5, 6) is **unchanged** by this reduction; no gate depended on S3/MinIO.

### 10.2 Steps 1–2, 2026-08-14: harness failure, no data

**No step 1 or step 2 verdict is claimed from the 2026-08-14 attempt, pass or fail.** Both runs died inside the harness before reaching any pass/fail criterion in protocol §3. Under Rule 0.3 (raw output, not summaries) and Rule 0.5 (a result matching a prediction is weak evidence), nothing from those runs may be recorded as a step outcome. **The scoreboard at that time was explicitly blank, not implied.**

The three logged errors, verbatim (Rule 0.3). Error 1 is quoted from the surviving raw log; errors 2–3 are quoted from [`spike-E-step1-2-failure-diagnosis.md`](spike-E-step1-2-failure-diagnosis.md:15) §1, which verified each against the raw logs at the time, because the original raw logs from the 15:08 runs were later cleaned from the gitignored `results/raw/` directory:

1. `Error: Invalid application argument 'step1_app', must be of the form '<key>=<val>'.`
   — `results/raw/step1-20260814T155717Z.log` line 4 (log survives)
2. `ConnectionError: Failed to connect to Ray at address: http://localhost:8265.`
   — diagnosis §1, quoting `results/raw/step1-20260814T150813Z.log` line 108 (raw log no longer exists in the workspace)
3. `Value error, Found duplicate applications for route prefix "/".`
   — diagnosis §1, quoting `results/raw/step2-20260814T150833Z.log` line 35 (raw log no longer exists in the workspace)

What each error actually proved (diagnosis §1 table) — none of it is a fact about Ray:

| Logged error | What it was actually evidence of |
|---|---|
| `Invalid application argument 'step1_app'` | Our CLI invocation was malformed — a bare positional where the CLI expects builder `key=val` pairs / an import path plus `--name`. |
| `Failed to connect to Ray at address: http://localhost:8265` | No Ray cluster was running — the Makefile never started one; step 1 Part B tested only the absence of a cluster. |
| `Found duplicate applications for route prefix "/"` | A one-line omission in our YAML — both applications left `route_prefix` at its default. Client-side schema rejection; no cluster was even needed to fail. |

The diagnosis §2 further identifies latent defects (e.g. deployment-level `image_uri` being silently ignored by the schema) that would have produced a **false** step-1 fail on the next attempt. All are tracked and fixed in the continuation plan items 2–9a.

### 10.3 Open questions a reviewer will ask

- **Is step 5 "pass" or "partial" under §3 as written?** Resolved 2026-09-10 — **PARTIAL** (ledger §9S, D44): 40 % of alternations took 99-104 s against a ~12 s cold start; the criterion says *"do not round to pass or fail."*
- **Is step 6's head-node half a "fail" under the written criterion?** Resolved 2026-09-10 — **FAIL as written** (§9S, D44): manual intervention is named in the Fail criterion. The orphaned-container count step 6.3 asks for is the **109** from step 7's output, cited by reference (§3.6, §3.7).
- **What fraction of the 103 s P90 is orchestration vs container startup?** Unattributable from this data — no baseline exists (§5.2).
- **Does the `container`-key path work on a Docker host, or on podman ≥4 (CDI)?** Untested; the Docker path is unreachable here (Ray hardcodes podman).
- **Where do app builders execute?** Refused claim; needs a negative control (§3.2).
- **What is the cost of D18 (payload-by-reference)?** Not tested (§5.2).
- **Can Ray's own autoscaler timer be pre-empted?** Not tested; only externally-driven displacement is shown (§3.5).
- **Would a newer Ray change D22 / D32 / D36?** Everything here is Ray 2.57.0; none of the three findings is version-checked against a later release.

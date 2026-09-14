# Spike E — Ray-native tool-swap experiment

## Start here

A nine-step empirical evaluation of one question: **can Ray Serve be
tool-swap's GPU model-switching router?** It was run on a real DGX host with
GPUs and podman; this folder is the harness that produced it. This is a
**decision spike** — the deliverable is evidence and a decision, not a
feature.

**The decision**
([`plan/adr/0003-ray-serve-not-adopted.md`](../plan/adr/0003-ray-serve-not-adopted.md),
re-based a third time onto this evidence): **Ray Serve is not the router for
tool-swap's v1 single-host model-switching workload.** The scope qualifier
travels with the decision: it is *not* a verdict on Ray in general. Where Ray
*is* the right tool is stated in
[`plans/ray-adoption-analysis.md`](../plans/ray-adoption-analysis.md) §0′.

**What the evidence says, in two breaths.** Ray **passed** most of the
protocol: isolated GPU deployments, per-tool container images, **real GPU
displacement with VRAM verified released and reclaimed** (torch 4519 MiB ↔ tf
38909 MiB), payload and weights read in-container, **20/20 alternations with
zero errors**, and automatic unattended replica recovery. **The one failure is
on tool-swap's core path:** with a request arriving *during* the swap —
tool-swap's actual trigger — **8 of 20 cycles took ~100 s**. The stall is
located precisely: it is dead time inside Ray *before* it issues
`podman run` (container first seen at ~3.0 s on fast cycles, ~93.6 s on slow
ones; plain podman does the same work in 3.9–6.9 s with no bimodality).
**The mechanism is deliberately unnamed** — five prior attributions were
wrong, and the record says only what was measured.

### Which document, for what purpose

| Document | Job |
|---|---|
| [`plans/spike-E-continuation.md`](../plans/spike-E-continuation.md) | **The evidence of record.** The run ledger, entries §9a–§9Z / D1–D55: every verdict, measurement, harness fix and retraction, with verbatim output. Chronological and ~1700 lines long — read a section by reference, not top to bottom. |
| [`plans/ray-adoption-analysis.md`](../plans/ray-adoption-analysis.md) | **The analysis of record** (revision 3). Prices Ray vs. our own router on the simplicity axis with labelled evidence classes ([M]/[S]/[I]/[A]). §0′ states where Ray *is* the right tool — read it before quoting "we rejected Ray". |
| [`plan/adr/0003-ray-serve-not-adopted.md`](../plan/adr/0003-ray-serve-not-adopted.md) | **The decision.** Re-based onto this measurement; preserves its two earlier versions as the error trail; names revisit triggers (the first and cheapest: name the ~93 s stall, or re-run step 9-eager on another Ray version). |
| [`plans/spike-E-ray-native-protocol.md`](../plans/spike-E-ray-native-protocol.md) | **The frozen protocol.** The steps, the pass/fail criteria, and the §5 decision rule the steps were graded against. Frozen before the first run (Rule 0.1) and honoured when it cut both ways against the author's own summaries. |
| [`plans/spike-E-results.md`](../plans/spike-E-results.md) | The assembled results for **steps 1–7**, frozen at the 2026-09-10 rewrite (ledger through §9S). Steps 8–9 live in the ledger only. |
| this folder | **The harness**: nine step scripts, shared `scripts/lib/`, fixtures, one Makefile target per step (plus `step3-container`, `env`, `preflight`, `clean`). |

---

## §0a — Scope amendment (2026-08-14)

Weights and payload are baked into the container images at build time.
There is no S3/MinIO, no `boto3`, and no credential plumbing in this spike.

Per [plans/spike-E-implementation.md](../plans/spike-E-implementation.md:12):
- Step 2 no longer measures weight-fetch latency (a local disk read of ~8 MB replaces a ~2 GB network fetch).
- Step 4 no longer tests D18 payload-by-reference; it reads a baked-in local file. **D18 remains an untested assumption.**
- Steps 3 and 5 are therefore optimistic relative to production (no cold-start weight download), which is fair because the same download is absent from our own router too.

## Prerequisites

### For steps 1–2 (no GPU needed — runnable in this devcontainer)

- Ray installed on host (for running `serve deploy` and scripts) — already installed in this devcontainer
- Podman CLI and nvidia-ctk installed in this devcontainer for version capture only (container build/GPU operations are not available here)

### For steps 3–6 and 8–9 (require the DGX host or another GPU box)

- Ray cluster running on the host (raylet on host, not in a container — see §6.1 assumption 8 below)
- Podman (GPU-capable, rootless)
- NVIDIA container toolkit
- GPU-accessible box with `nvidia-smi`

Step 7 additionally assumes the shared DGX itself (it records its
coexistence with the other tenants; it is record-only).

> **Why steps 3–9 must run on the host.**
> Per [§6.1 assumption 8 of the implementation plan](../plans/spike-E-implementation.md:476):
> *"The raylet and all spike scripts run on the DGX host, not in a devcontainer."*
> A containerised raylet would invalidate steps 3-6 results (nesting changes cold-start and VRAM behaviour).
> The [devcontainer sandbox](../.devcontainer/devcontainer.json:8) (`--cap-drop=ALL`, `no-new-privileges:true`)
> also prevents rootless podman from creating user namespaces, so `podman build` cannot work here regardless.

## Running a step

From `spike-e-ray-native/`:

```bash
make preflight     # report which prerequisites are present (terminal only)
make env           # capture the environment -> results/raw/env-capture-*.log
make fixtures      # build the two fixture images (host only; same user that
                   # starts Ray — see fixtures/README.md, D22)

make step1         # per-deployment image_uri (no GPU — devcontainer OK)
make step2         # app builder + baked weights (no GPU — devcontainer OK)
make step3         # GATE: two conflicting tools, one GPU (host)
make step4         # local payload read (D18 NOT tested)
make step5         # preemption at cadence, 20 alternations
make step6         # GATE: restart and recovery
make step7         # shared-node fitness (DGX, record only)
make step8         # plain-podman baseline, NO Ray (D45)
make step9         # phase timing of the alternation cycle (D47)
```

`step3-container` is a variant of the step-3 gate through the legacy
`container` runtime_env key — the path that actually reaches a GPU (D36:
`image_uri` cannot). It runs exactly like `step3`; only the config and the
recorded step name differ.

| Target | Pre-conditions |
|---|---|
| step1, step2 | Ray on the machine; no GPU, no podman |
| fixtures | podman that can run containers (host) |
| step3, step4, step5, step6, step9 | host Ray + GPU + podman; fixtures built |
| step7 | the shared DGX |
| step8 | host GPU + podman + nvidia-container-runtime; fixtures built. **Deliberately not wrapped in a cluster** — see below |

**Every Ray step gets its own clean cluster.** Each Ray target runs through
[`scripts/lib/run_with_cluster_clean.sh`](scripts/lib/run_with_cluster_clean.sh):
stop any stale cluster, start a fresh head node, run the step, tear the
cluster down. Isolation between runs is what makes each step's numbers
attributable to the step, not to a previous run's state. Ray's own startup
and runtime output goes to `results/raylogs/ray-*.log`. The head node is
pinned to `SPIKE_RAY_NUM_GPUS` (default **1**) so that the step-3 contention
is *structural* — the script header explains why auto-detecting all of the
shared host's GPUs would turn the decisive gate into a false pass.

**Step 8 is the deliberate exception**: it measures plain podman with **no
Ray**, because starting a cluster would make the raylet a co-tenant on the
GPU host and pollute the baseline it exists to establish.

### Where output lands

All of it is gitignored ([`.gitignore`](.gitignore)), so the logs do not
travel in a fresh clone. Host output must be pasted back into the workspace
for verification and quoted **inline** in the plan documents —
[`plans/spike-E-results.md`](../plans/spike-E-results.md) for steps 1–7, the
ledger for steps 8–9 — because a link to `results/raw/` would rot on a fresh
clone. Protocol Rule 0.3: record raw output, not summaries.

| Path | Contents |
|---|---|
| `results/raw/<step>-<timestamp>.log` | the step's verbatim stdout/stderr |
| `results/metrics/<step>.jsonl` | one JSON line per observation (per-cycle boundaries for steps 5/8/9, VRAM series, verdict fields) |
| `results/raylogs/ray-*.log` | Ray's own output for that step's cluster |
| step-specific extras | e.g. step 3's VRAM time-series CSV, step 7's `step7_*.log` files |

### Exit codes (D29) — every step speaks the same dialect

| Code | Meaning |
|---|---|
| **0** | clean — every required observation was made, no negative findings |
| **2** | **harness failure** — an observation could *not* be made (broken environment, deploy failed, a cycle's phases never resolved). The run's attribution is incomplete. It says nothing about Ray. |
| **3** | **negative finding** — the observations *were* made and they answer the step's question negatively. **A result, not a bug**: it belongs in the record as evidence. |
| 1 | unexpected internal error (traceback printed) |

The 0/2/3 split exists because a step that "passes" while measuring nothing
was the recurring failure mode of this spike (five times — see
[Method lessons](#method-lessons-the-transferable-part)). Each step prints
its verdict with an explicit label: `STEP N RESULT: HARNESS FAILURE — exit
code 2` / `NEGATIVE FINDING(S) — exit code 3` / `… exit code 0`.

## Environment and override precedence (read before overriding any knob)

`env.sh` loads configuration in this order, highest first:

1. **variables the caller already exported** — the shell, or inline
   `SPIKE_STEP9_PROBE=eager make step9`
2. **`.env`** — gitignored, yours, per host
3. **`.env.example`** — the committed defaults (every documented `SPIKE_*`
   knob is annotated there)
4. the `: "${VAR:=default}"` lines at the bottom of `env.sh`

A gitignored `.env` still beats `.env.example`; `.env.example` still beats
the built-in defaults.

**Why the rule exists.** The old loader did `set -a; source .env; set +a`,
which assigns *unconditionally* — a value in the file overwrote whatever the
caller exported. That silently turned `SPIKE_STEP9_PROBE=eager make step9`
into a `ready`-mode run, and **a run was reported on that never happened**
(ledger §9Y, D52). The current loader copies only names the caller has not
already set.

**The discipline it earned: verify the banner.** Steps print the
configuration they actually loaded — step 9 prints `Probe pattern: EAGER` or
`READY (default)`; the cluster launcher prints the resolved GPU count. Read
the banner before trusting a run. The environment, not the script, is the
thing that lied.

## Step 9 in particular

Step 9 instruments a step-5-style alternation with per-cycle phase
boundaries (p1–p7) plus a podman container correlation, to find *where* the
~95 s slow mode goes.

**Two probe modes — the discriminating variable:**

| Mode | Behaviour | What it is for |
|---|---|---|
| `SPIKE_STEP9_PROBE=ready` (**default**) | poll until the replica reports RUNNING, *then* POST | Step 9's original pattern, kept as default so the early runs (ledger §9V/§9X) stay comparable. **Does not reproduce step 5** — the request never arrives during the swap. 50 ready-mode cycles never stalled. |
| `SPIKE_STEP9_PROBE=eager` | POST *immediately* after the scale calls, from a background thread, exactly as step 5 does | **The mode that found the stall.** A pending request is a *precondition* for the ~93 s pre-container stall; eager reproduces step 5's bimodality (8 slow / 12 fast) and the phase table located the dead time. |

```bash
SPIKE_STEP9_PROBE=eager SPIKE_STEP9_N=20 make step9
```

The remaining knobs (`SPIKE_STEP9_N`, `SPIKE_STEP9_POLL_S`,
`SPIKE_STEP9_CYCLE_BUDGET_S`, …) are annotated in [`.env.example`](.env.example).

**Reading the output — what the step cannot see.** Everything inside Ray's
own processes is invisible to the harness; the stall shows up only as a gap
between two observable boundaries: G1 (scale response → target applied), G2
(target → replica appears — split by the container first-seen timestamp into
*before the container exists* vs *after*), and G3 (STARTING → RUNNING). The
step prints this every run under "WHAT THIS STEP CANNOT SEE INTO" and
harvests the session logs that can look inside each gap (the replica log,
`runtime_env_setup-*.log`) per cycle. If STARTING lasts under one poll
interval, p5 is never observed — the state was missed, not absent.

**Two known rough edges in eager-mode output** (neither affected the finding;
ledger §9Z):

- `serving_s` can be **negative**: p7 is the probe's return, which can land
  *before* RUNNING is observed at the next poll (p6). The subtraction is
  undefined in that mode, not "fast".
- `replica_materialize_s` reads **0.000** when p3 and p4 land on the same
  poll — real, but poll-quantised at the low end.

## Method lessons (the transferable part)

Recorded at length in the ledger; stated here as the rules earned, with
pointers.

### Five silent harness defects, each producing a *plausible* wrong answer

| # | Defect | Ledger |
|---|---|---|
| 1 | Step 1 exited **0** while both probes timed out — every error caught, printed, recorded, *swallowed*; a broken run was indistinguishable from a passing one | §9e (D21) |
| 2 | Step 2 compared `weights_sha256` against an op that **never returns that field** — the central isolation comparison could never have succeeded, and it still exited 0 | §9e (D21) |
| 3 | Step 6 phase B confirmed "recovery" using the pid it had **just killed** — a stale read satisfied the check on its first poll | §9P (D40) |
| 4 | Step 9's container correlation printed nothing for **40 cycles** (podman 3.x's JSON array parsed as NDJSON and dropped line by line), and the recency rule that replaced it matched *stale* containers from days earlier — twice returning something that looked like it worked | §9V/§9X (D53) |
| 5 | `env.sh` overrode the caller's environment, so the discriminating run **never executed** — and a report was written about the run that did execute instead | §9Y (D52) |

All five were **passing** when found. The rule earned: **a check that can
only pass is not a check.**

### Five wrong attributions — every measurement held; nearly every explanation was retracted

| # | Explanation first attached | Correction | Ledger |
|---|---|---|---|
| 1 | "A GPU cannot reach a podman container on this host" (decisive gate failure) | It can — the `--runtime` flag was missing, and Ray's modern API structurally cannot supply it | §9k → §9L (D33/D36) |
| 2 | "VRAM was not released on scale-down" (second decisive gate failure) | The gate measured at 65 s, before Ray's own timer was due to expire (~75–80 s) | §9M (D35) |
| 3 | The ~95 s is "Ray's autoscaler metric decay" | The autoscaler was never in the loop — `external_scaler_enabled` disables it | §9T → §9U (D46) |
| 4 | "The mechanism is fast; the 100 s is an artefact of that run's conditions" | Step 9 had sampled luckily (0/10 slow); the bimodality reproduced | §9V → §9W (D48/D49) |
| 5 | Proxy-side handling of a request that arrives before its replica exists | Superseded by measurement: the container is not even *launched* until ~93 s in — the dead time precedes it. Mechanism left unnamed | §9X → §9Z (D54) |

The discipline: **record the measurement and the explanation separately.**
The measurements were cheap to trust because the harness recorded raw
output; the explanations were expensive because they were reached for faster
than the evidence allowed. After the fifth wrong attribution, the record
states only what was measured — and names where to look next (the controller
and proxy logs for a slow cycle, gaps G1–G2).

### Grading against a frozen criterion

The protocol §5 decision rule was frozen before the first run (Rule 0.1) and
never reinterpreted. It was honoured **in both directions against the
author's own summaries**: two recorded *failures* were retracted as the
author's measurement faults (§9L, §9M), and two recorded *passes* were
corrected to PARTIAL / FAIL against the written criteria (§9S). The
corrections were visible only because a second reader checked the verdicts
against the frozen text instead of trusting the summary. **A frozen
criterion plus an independent read is what caught the drift.**

## Decision rule

See §5 of [`spike-E-ray-native-protocol.md`](../plans/spike-E-ray-native-protocol.md),
frozen per Rule 0.1. The decision rule (steps 3, 5, 6) is **unchanged** by
the §0a scope reduction. No gate depended on S3/MinIO.

### Notes on running inside the devcontainer

- `make env` will report podman, nvidia-smi, and GPU capability as "not present" or
  "not available" — this is expected and correct. The log file is still written.
- `make step1` and `make step2` work without GPU or podman (they use the host's
  Ray installation).
- `make fixtures`, `make step3` through `make step6`, `make step8` and
  `make step9` require the host GPU. They will refuse to run with a clear error
  if `nvidia-smi` or `podman` (with working container runtime) is not available.

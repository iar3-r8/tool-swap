# Spike E — results

> Protocol: [`spike-E-ray-native-protocol.md`](spike-E-ray-native-protocol.md). Decision rule: §5 of that file, unedited.
> Operator: Zoo (TDD pipeline) + user · Dates: 2026-08-14 (attempt) / 2026-08-25 (continuation) · Spike code commit: `0a389ed52ad0888951575acae8df667471ca89ee`
>
> This file is the single living results document for the spike. The 2026-08-14 attempt
> produced no data; the continuation plan is [`spike-E-continuation.md`](spike-E-continuation.md).
> Sections below marked *pending host run* will be filled in as the host run proceeds.

## 0. Environment

*Pending host run.* The `make env` capture on the host goes here verbatim (Rule 0.3).

For the record, the 2026-08-14 attempt ran in the devcontainer: Ray **2.57.0**, Python
**3.11.16**, no GPU, no working podman (`cannot clone: Operation not permitted` under
`--cap-drop=ALL`). See [`spike-E-step1-2-failure-diagnosis.md`](spike-E-step1-2-failure-diagnosis.md:9).

## 0a. Scope amendments

Per [`spike-e-ray-native/README.md`](../spike-e-ray-native/README.md:6) §0a (2026-08-14):

- Weights and payload are **baked into the container images at build time**. There is no
  S3/MinIO, no `boto3`, and no credential plumbing in this spike.
- Step 2 no longer measures weight-fetch latency (a local disk read of ~8 MB replaces a
  ~2 GB network fetch); its timing is **not** a thrash-pricing figure.
- Step 4 no longer tests D18 payload-by-reference; it reads a baked-in local file.
  **D18 remains an untested assumption.**
- Steps 3 and 5 are therefore optimistic relative to production (no cold-start weight
  download), which is fair because the same download is absent from our own router too.
- The §5 decision rule (steps 3, 5, 6) is **unchanged** by this reduction; no gate
  depended on S3/MinIO.

## 0b. Steps 1–2, 2026-08-14: harness failure, no data

**No step 1 or step 2 verdict is claimed, pass or fail.** Both 2026-08-14 runs died inside
the harness before reaching any pass/fail criterion in protocol §3. Under Rule 0.3 (raw
output, not summaries) and Rule 0.5 (a result matching a prediction is weak evidence),
nothing from those runs may be recorded as a step outcome. **The scoreboard is explicitly
blank, not implied.**

The three logged errors, verbatim (Rule 0.3). Error 1 is quoted from the surviving raw
log; errors 2–3 are quoted from
[`spike-E-step1-2-failure-diagnosis.md`](spike-E-step1-2-failure-diagnosis.md:15) §1, which
verified each against the raw logs at the time, because the original raw logs from the
15:08 runs were later cleaned from the gitignored `results/raw/` directory:

1. `Error: Invalid application argument 'step1_app', must be of the form '<key>=<val>'.`
   — `results/raw/step1-20260814T155717Z.log` line 4 (log survives)
2. `ConnectionError: Failed to connect to Ray at address: http://localhost:8265.`
   — diagnosis §1, quoting `results/raw/step1-20260814T150813Z.log` line 108
     (raw log no longer exists in the workspace)
3. `Value error, Found duplicate applications for route prefix "/".`
   — diagnosis §1, quoting `results/raw/step2-20260814T150833Z.log` line 35
     (raw log no longer exists in the workspace)

What each error actually proved (diagnosis §1 table) — none of it is a fact about Ray:

| Logged error | What it was actually evidence of |
|---|---|
| `Invalid application argument 'step1_app'` | Our CLI invocation was malformed — a bare positional where the CLI expects builder `key=val` pairs / an import path plus `--name`. |
| `Failed to connect to Ray at address: http://localhost:8265` | No Ray cluster was running — the Makefile never started one; step 1 Part B tested only the absence of a cluster. |
| `Found duplicate applications for route prefix "/"` | A one-line omission in our YAML — both applications left `route_prefix` at its default. Client-side schema rejection; no cluster was even needed to fail. |

The diagnosis §2 further identifies latent defects (e.g. deployment-level `image_uri`
being silently ignored by the schema) that would have produced a **false** step-1 fail on
the next attempt. All are tracked and fixed in the continuation plan items 2–9; the host
run is what will produce the real verdicts.

## 1. Fixtures as built

*Pending host run.* Base tag, digests, baked asset sizes + hashes, build logs.

## 2. Step 1 — per-deployment image_uri   [pending host run]  (informative, Rule 5)

*Pending host run.* The 2026-08-14 attempt produced no data — see §0b. Verdict to be
recorded against protocol §3 step 1 **as written**, once the host run completes.

## 3. Step 2 — app builder, baked weights   [pending host run]  (informative, Rule 5)

*Pending host run.* The 2026-08-14 attempt produced no data — see §0b. Per §0a, any
weight-load timing recorded here is a local disk read, **not** a thrash-pricing figure.

## 4. Step 3 — GATE   [pending host run]

*Pending host run.* VRAM time series, cold starts, `CUDA_VISIBLE_DEVICES` from inside the
container, podman snapshots. On fail: stop (Rule 0.4); Rule 2 applies.

## 5. Step 4 — local payload read   [pending host run]  (informative, Rule 5; D18 NOT tested)

*Pending host run.* Per §0a this reads a baked-in local file. **D18 remains an untested
assumption** — state that here when recording, not before.

## 6. Step 5 — preemption at cadence   [pending host run]

*Pending host run.* 20-row table, distribution, controller-health diff. Both mechanisms
reported separately. Record as a finding: `external_scaler_enabled` forbids Serve's own
autoscaling for those apps.

## 7. Step 6 — GATE, restart and recovery   [pending host run]

*Pending host run.* Both phases verbatim, manual-step list, VRAM before/after. This is
the step predicted to fail (Rule 0.5): a fail is weak evidence, a pass is informative.
On fail with steps 3 and 5 passing: Rule 3 — the decision goes to the requester.

## 8. Step 7 — shared-node fitness   [pending host run]  (record only)

*Pending host run.* Storage driver A/B, `--privileged` check, `/tmp/ray` permissions.
No pass/fail; this informs deployment, not the decision.

## 9. Measured times

| Measurement | Step | Samples | Median | Min | Max | Notes |
|---|---|---|---|---|---|---|
| ~~Weights fetch (~2 GB, MinIO)~~ | ~~2~~ | — | — | — | — | **removed by §0a**; no remote fetch exists |
| Weights load (baked, local disk) | 2 | 2 apps | | | | local read only — **not** a thrash-pricing figure |
| Cold start, container start component | 3 | ≥2 | | | | per tool; excludes weight download (§0a) |
| Cold start, end to end | 3 | ≥2 | | | | client-observed; optimistic vs production (§0a) |
| Replica-gone after idle | 3 | 1 | | | | vs configured 60 s |
| VRAM-returned-to-baseline after idle | 3 | 1 | | | | separate from above |
| Local payload read (64 MB baked) | 4 | 3 | | | | report all 3; page-cache effect expected |
| Preemption latency, mechanism A | 5 | 20 | | | | + p90, full list |
| Preemption latency, mechanism B | 5 | 20 | | | | + p90, full list |
| Replica-actor recovery | 6B | 1 | | | | unattended? |
| Image cold start, `vfs` vs `overlay` | 7 | 2 arms | | | | timeout if hung |

## 10. Surprises and contradictions

*Pending host run for step output.* Already on the record from the 2026-08-14 diagnosis:
the step-1 config as written would have produced a **false fail** via silently dropped
YAML keys (`extra="ignore"` on `DeploymentSchema`) — the class of error
[`bias-audit-and-decision-procedure.md`](bias-audit-and-decision-procedure.md) exists to
prevent. Also: `external_scaler_enabled` forbids Serve autoscaling for the affected apps,
which is a real constraint on a Ray-native design to be recorded when step 5 runs.
Anything contradicting [`plan/15_RAY_SERVE_EVALUATION.md`](../plan/15_RAY_SERVE_EVALUATION.md)
or the four argument docs goes here.

## 11. Decision under §5

No gate has been attempted. **No rule of the frozen §5 decision rule applies yet** — the
scoreboard is blank (see §0b), and §5 is restated in
[`spike-E-ray-native-protocol.md`](spike-E-ray-native-protocol.md:149) §5, unedited.
A decision is recorded here only after a host run reaches step 3, 5 or 6; if Rule 3 or
4 applies, the matter is escalated to the requester, not decided here.

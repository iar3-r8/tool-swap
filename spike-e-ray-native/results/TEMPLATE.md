# Spike E — results

> Protocol: plans/spike-E-ray-native-protocol.md. Decision rule: §5 of that file, unedited.
> Operator: <name> · Dates: <...> · Spike code commit: <sha>

## 0. Environment            <- capture_env.py output verbatim

## 0a. Scope amendments        <- S3 removed; what that means for steps 2 and 4, and D18

## 1. Fixtures as built      <- base tag, digests, baked asset sizes + hashes, build logs

## 2. Step 1 — per-deployment image_uri     [pass|fail]  (informative, Rule 5)

<!-- Both configs, both responses, two introspect payloads -->

## 3. Step 2 — app builder, baked weights   [pass|fail]  (informative, Rule 5)

<!-- Builder banner, weights_sha256 per app (must differ), load_seconds, whether builder needed tool imports. Explicitly state that weight-fetch latency is out of scope per §0a. -->

## 4. Step 3 — GATE                         [pass|fail]

<!-- VRAM time series, cold starts, CUDA_VISIBLE_DEVICES, podman snapshots -->

## 5. Step 4 — local payload read            [pass|fail]  (informative, Rule 5; D18 NOT tested)

<!-- Timings (all 3, name page-cache effect), size+hash equality, explicit D18-not-tested statement -->

## 6. Step 5 — preemption at cadence        [pass|partial|fail]

<!-- 20-row table, distribution, controller-health diff -->

## 7. Step 6 — GATE, restart and recovery   [pass|fail]

<!-- Both phases verbatim, manual-step list, VRAM before/after -->

## 8. Step 7 — shared-node fitness          [record only]

<!-- Storage driver A/B, --privileged check, /tmp/ray permissions -->

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

<!-- Anything contradicting plan/15_RAY_SERVE_EVALUATION.md or the four argument docs -->

## 11. Decision under §5

<!-- Which rule applies; escalate if Rule 3 or 4 -->

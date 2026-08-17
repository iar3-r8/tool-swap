# Spike E — Ray-native tool-swap experiment

Temporary experiment scaffolding for [`spike-E-ray-native-protocol.md`](../plans/spike-E-ray-native-protocol.md).
This folder is disposable.

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

### For steps 3–7 (require the DGX host or another GPU box)

- Ray cluster running on the host (raylet on host, not in a container — see §6.1 assumption 8 below)
- Podman (GPU-capable, rootless)
- NVIDIA container toolkit
- GPU-accessible box with `nvidia-smi`

> **Why steps 3-7 must run on the host.**
> Per [§6.1 assumption 8 of the implementation plan](../plans/spike-E-implementation.md:476):
> *"The raylet and all spike scripts run on the DGX host, not in a devcontainer."*
> A containerised raylet would invalidate steps 3-6 results (nesting changes cold-start and VRAM behaviour).
> The [devcontainer sandbox](../.devcontainer/devcontainer.json:8) (`--cap-drop=ALL`, `no-new-privileges:true`)
> also prevents rootless podman from creating user namespaces, so `podman build` cannot work here regardless.

## Quick start

```bash
cd spike-e-ray-native

# Check which prerequisites are available
make preflight

# Capture the environment (works in devcontainer — missing tools reported as strings)
make env

# Build fixture images (requires podman that can run containers — host only)
make fixtures

# Per-deployment image_uri test (no GPU needed — runnable in devcontainer)
make step1

# App builder + baked weights (no GPU needed — runnable in devcontainer)
make step2

# Stop here to review. Steps 3+ need the GPU and must run on the host.
# make step3             # GATE: two conflicting tools, one GPU
# make step4             # local payload read (D18 NOT tested)
# make step5             # Preemption at cadence
# make step6             # GATE: restart and recovery
# make step7             # Shared-node fitness (DGX only)
```

Each step writes verbatim logs to `results/raw/` and metrics to `results/metrics/`.
Results are assembled manually into `plans/spike-E-results.md`.

### Notes on running inside the devcontainer

- `make env` will report podman, nvidia-smi, and GPU capability as "not present" or
  "not available" — this is expected and correct. The log file is still written.
- `make step1` and `make step2` work without GPU or podman (they use the host's
  Ray installation).
- `make fixtures`, `make step3`, `make step4`, `make step5`, `make step6`,
  `make step7` require the host GPU. They will refuse to run with a clear error
  if `nvidia-smi` or `podman` (with working container runtime) is not available.

## Decision rule

See §5 of [`spike-E-ray-native-protocol.md`](../plans/spike-E-ray-native-protocol.md).
The decision rule (steps 3, 5, 6) is **unchanged** by the §0a scope reduction.
No gate depended on S3/MinIO.

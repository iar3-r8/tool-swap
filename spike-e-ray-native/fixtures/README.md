# Fixtures — Spike E

Two tool images that cannot share an interpreter due to framework conflicts:
- `tool_torch`: torch==2.8.0+cu129
- `tool_tf`: tensorflow==2.16 + tf-keras

Both derive from the same Ray base image at the cluster's exact Ray and Python patch version.

## §0a — Baked assets

Weights and payload are baked into each image at build time. No S3/MinIO.
Each image carries ~8 MB checkpoint + ~64 MB payload + sidecar `.meta.json` files.

## Usage

```bash
source ../env.sh
bash build_images.sh
```

## Verification

After building, verify cross-import failure and asset integrity:

```bash
# Cross-import isolation
podman run --rm tool_tf:spike python -c "import torch"   # should fail
podman run --rm tool_torch:spike python -c "import tensorflow"  # should fail

# Asset hashes
podman run --rm tool_torch:spike cat /opt/spike/weights/ckpt.bin.meta.json
podman run --rm tool_tf:spike cat /opt/spike/weights/ckpt.bin.meta.json
```

## Cleaning up

```bash
podman rmi tool_torch:spike tool_tf:spike
```

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

## Build args

| Arg | Default | Meaning |
|---|---|---|
| `RAY_BASE_TAG` | from `env.sh` | Ray base image tag (shared by both images) |
| `WEIGHTS_MB` / `PAYLOAD_MB` | `8` / `64` | Baked asset sizes (shared by both images) |
| `ASSET_SEED` | `1001` (torch) / `1002` (tf) | Asset bytes seed — must differ per image |
| `SPIKE_UID` / `SPIKE_GID` | invoking user's `$(id -u)` / `$(id -g)` | Runtime uid/gid of the container process |

`build_images.sh` passes `SPIKE_UID`/`SPIKE_GID` to `podman build` with the
**invoking user's real uid/gid** as the default. The uid can be overridden by
exporting `SPIKE_UID`/`SPIKE_GID` before running the script.

### Host-uid coupling (D22)

The fixture images are **host-specific**: the container runtime user is pinned
to the uid of the user who built them, because Ray's `image_uri` runtime env
starts the replica container with `--userns=keep-id` and **no `--user`**
(`ray/_private/runtime_env/image_uri.py` hardcodes empty run options), while
the host cluster's `<session>/logs/events/` and `.../logs/export_events/`
dirs are mode 0755 owned by the cluster-starting uid. A mismatched uid makes
the C++ core worker's event writer abort (SIGABRT) while opening
`event_CORE_WORKER_<pid>.log`.

Consequences:

- Rebuild the images **on the host, as the same user that starts the Ray
  cluster** (`ray start`), so `id -u` matches the session owner.
- If the cluster is started by a different user than the one that built the
  images, the replica will abort again — rebuild, don't `chmod` the session
  dirs (that was the rejected workaround).

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

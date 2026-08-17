#!/usr/bin/env bash
# Build both fixture images. Same RAY_BASE_TAG, WEIGHTS_MB, PAYLOAD_MB for both.
# Prints base tag, both image digests, baked asset sizes + hashes, and podman images output.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../env.sh"

echo "============================================================"
echo "Building Spike E fixture images"
echo "  RAY_BASE_TAG = ${RAY_BASE_TAG}"
echo "  WEIGHTS_MB   = ${WEIGHTS_MB}"
echo "  PAYLOAD_MB   = ${PAYLOAD_MB}"
echo "============================================================"

# ── tool_torch ──────────────────────────────────────────────────
echo ""
echo "--- Building tool_torch ---"
podman build \
  --build-arg RAY_BASE_TAG="${RAY_BASE_TAG}" \
  --build-arg WEIGHTS_MB="${WEIGHTS_MB}" \
  --build-arg PAYLOAD_MB="${PAYLOAD_MB}" \
  -f "${SCRIPT_DIR}/tool_torch.Dockerfile" \
  -t tool_torch:spike \
  "${SCRIPT_DIR}/../"

TOUCH_ID=$(podman inspect tool_torch:spike --format '{{.Id}}')
echo "tool_torch image ID: ${TOUCH_ID}"

# ── tool_tf ─────────────────────────────────────────────────────
echo ""
echo "--- Building tool_tf ---"
podman build \
  --build-arg RAY_BASE_TAG="${RAY_BASE_TAG}" \
  --build-arg WEIGHTS_MB="${WEIGHTS_MB}" \
  --build-arg PAYLOAD_MB="${PAYLOAD_MB}" \
  -f "${SCRIPT_DIR}/tool_tf.Dockerfile" \
  -t tool_tf:spike \
  "${SCRIPT_DIR}/../"

TF_ID=$(podman inspect tool_tf:spike --format '{{.Id}}')
echo "tool_tf image ID: ${TF_ID}"

# ── Record everything to results/raw ────────────────────────────
mkdir -p "${SPIKE_RAW_DIR}"

{
  echo "RAY_BASE_TAG: ${RAY_BASE_TAG}"
  echo "WEIGHTS_MB: ${WEIGHTS_MB}"
  echo "PAYLOAD_MB: ${PAYLOAD_MB}"
  echo "tool_torch image ID: ${TOUCH_ID}"
  echo "tool_tf image ID: ${TF_ID}"
  echo ""
  echo "=== podman images --digests ==="
  podman images --digests 2>&1
} > "${SPIKE_RAW_DIR}/build-info.log"

echo ""
echo "Build info saved to: ${SPIKE_RAW_DIR}/build-info.log"

# ── Report baked asset sizes + hashes from inside each image ────
echo ""
echo "============================================================"
echo "Baked asset sizes and hashes (from inside images)"
echo "============================================================"

for img in tool_torch:spike tool_tf:spike; do
  echo ""
  echo "--- ${img} ---"
  podman run --rm "${img}" python -c "
import json, pathlib
for name in ['weights/ckpt.bin', 'data/payload.bin']:
    p = pathlib.Path('/opt/spike') / name
    meta = p.with_suffix(p.suffix + '.meta.json')
    if meta.exists():
        m = json.loads(meta.read_text())
        print(f'  {name}: {m[\"size_bytes\"]} bytes, sha256={m[\"sha256\"]}')
    else:
        print(f'  {name}: NOT FOUND (asset generation may have failed)')
"
done

# ── Cross-import isolation check ────────────────────────────────
echo ""
echo "============================================================"
echo "Cross-import isolation check"
echo "============================================================"

echo ""
echo "--- torch import in tool_tf (should FAIL) ---"
if podman run --rm tool_tf:spike python -c "import torch" 2>&1; then
  echo "ERROR: torch imported in tool_tf — fixtures are not properly isolated"
else
  echo "OK: torch import failed in tool_tf as expected"
fi

echo ""
echo "--- tensorflow import in tool_torch (should FAIL) ---"
if podman run --rm tool_torch:spike python -c "import tensorflow" 2>&1; then
  echo "ERROR: tensorflow imported in tool_torch — fixtures are not properly isolated"
else
  echo "OK: tensorflow import failed in tool_torch as expected"
fi

echo ""
echo "============================================================"
echo "Fixture images built and verified"
echo "============================================================"

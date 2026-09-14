#!/usr/bin/env bash
# Build both fixture images. Same RAY_BASE_TAG, WEIGHTS_MB, PAYLOAD_MB for both.
# Prints base tag, both image digests, baked asset sizes + hashes, and podman images output.
# ASSET_SEED must differ between images: step 2 requires distinct baked weights.

set -euo pipefail

# Private dir var (not SCRIPT_DIR): env.sh used to clobber the caller's
# SCRIPT_DIR, which broke the -f paths and the build context below.
FIXTURES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${FIXTURES_DIR}/../env.sh"

: "${ASSET_SEED_TORCH:=1001}"
: "${ASSET_SEED_TF:=1002}"

# D22: the container worker must run as the host's cluster uid, because Ray's
# image_uri launches containers with --userns=keep-id and no --user, while the
# cluster's <session>/logs/events/ dirs are 0755 owned by the cluster-starting
# uid. Pass the invoking user's real uid/gid so the image tracks whoever
# builds it. Override with SPIKE_UID/SPIKE_GID only when you deliberately want
# a different uid (e.g. building as root for a specific operator).
: "${SPIKE_UID:=$(id -u)}"
: "${SPIKE_GID:=$(id -g)}"

echo "============================================================"
echo "Building Spike E fixture images"
echo "  RAY_BASE_TAG = ${RAY_BASE_TAG}"
echo "  WEIGHTS_MB   = ${WEIGHTS_MB}"
echo "  PAYLOAD_MB   = ${PAYLOAD_MB}"
echo "  ASSET_SEED_TORCH = ${ASSET_SEED_TORCH}"
echo "  ASSET_SEED_TF    = ${ASSET_SEED_TF}"
echo "  SPIKE_UID    = ${SPIKE_UID}"
echo "  SPIKE_GID    = ${SPIKE_GID}"
echo "============================================================"

# ── tool_torch ──────────────────────────────────────────────────
echo ""
echo "--- Building tool_torch ---"
podman build \
  --build-arg RAY_BASE_TAG="${RAY_BASE_TAG}" \
  --build-arg WEIGHTS_MB="${WEIGHTS_MB}" \
  --build-arg PAYLOAD_MB="${PAYLOAD_MB}" \
  --build-arg ASSET_SEED="${ASSET_SEED_TORCH}" \
  --build-arg SPIKE_UID="${SPIKE_UID}" \
  --build-arg SPIKE_GID="${SPIKE_GID}" \
  -f "${FIXTURES_DIR}/tool_torch.Dockerfile" \
  -t tool_torch:spike \
  "${FIXTURES_DIR}/.."

TOUCH_ID=$(podman inspect tool_torch:spike --format '{{.Id}}')
echo "tool_torch image ID: ${TOUCH_ID}"

# ── tool_tf ─────────────────────────────────────────────────────
echo ""
echo "--- Building tool_tf ---"
podman build \
  --build-arg RAY_BASE_TAG="${RAY_BASE_TAG}" \
  --build-arg WEIGHTS_MB="${WEIGHTS_MB}" \
  --build-arg PAYLOAD_MB="${PAYLOAD_MB}" \
  --build-arg ASSET_SEED="${ASSET_SEED_TF}" \
  --build-arg SPIKE_UID="${SPIKE_UID}" \
  --build-arg SPIKE_GID="${SPIKE_GID}" \
  -f "${FIXTURES_DIR}/tool_tf.Dockerfile" \
  -t tool_tf:spike \
  "${FIXTURES_DIR}/.."

TF_ID=$(podman inspect tool_tf:spike --format '{{.Id}}')
echo "tool_tf image ID: ${TF_ID}"

# ── Record everything to results/raw ────────────────────────────
mkdir -p "${SPIKE_RAW_DIR}"

{
  echo "RAY_BASE_TAG: ${RAY_BASE_TAG}"
  echo "WEIGHTS_MB: ${WEIGHTS_MB}"
  echo "PAYLOAD_MB: ${PAYLOAD_MB}"
  echo "ASSET_SEED_TORCH: ${ASSET_SEED_TORCH}"
  echo "ASSET_SEED_TF: ${ASSET_SEED_TF}"
  echo "SPIKE_UID: ${SPIKE_UID}"
  echo "SPIKE_GID: ${SPIKE_GID}"
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

TORCH_WEIGHTS_SHA=""
TF_WEIGHTS_SHA=""
for img in tool_torch:spike tool_tf:spike; do
  echo ""
  echo "--- ${img} ---"
  REPORT=$(podman run --rm "${img}" python -c "
import json, pathlib
for name in ['weights/ckpt.bin', 'data/payload.bin']:
    p = pathlib.Path('/opt/spike') / name
    meta = p.with_suffix(p.suffix + '.meta.json')
    if meta.exists():
        m = json.loads(meta.read_text())
        print(f'  {name}: {m[\"size_bytes\"]} bytes, sha256={m[\"sha256\"]}')
    else:
        print(f'  {name}: NOT FOUND (asset generation may have failed)')
")
  echo "${REPORT}"
  SHA=$(echo "${REPORT}" | sed -n 's/.*weights\/ckpt\.bin:.*sha256=\([0-9a-f]*\).*/\1/p')
  if [ "${img}" = "tool_torch:spike" ]; then
    TORCH_WEIGHTS_SHA="${SHA}"
  else
    TF_WEIGHTS_SHA="${SHA}"
  fi
done

if [ -z "${TORCH_WEIGHTS_SHA}" ] || [ -z "${TF_WEIGHTS_SHA}" ]; then
  echo "ERROR: could not read baked weights sha256 from both images — asset report is incomplete"
  exit 1
elif [ "${TORCH_WEIGHTS_SHA}" = "${TF_WEIGHTS_SHA}" ]; then
  echo "ERROR: tool_torch and tool_tf baked identical weights — seed wiring is broken"
  exit 1
else
  echo "OK: weights differ between images (isolation pre-condition for step 2)"
fi

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

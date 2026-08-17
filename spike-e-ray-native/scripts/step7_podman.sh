#!/usr/bin/env bash
# Step 7 — Shared-node fitness (DGX only, record only).
#
# This script records:
#   1. Docker coexistence with Podman
#   2. Storage driver A/B (vfs vs overlay)
#   3. --privileged requirement
#   4. /tmp/ray permission failure mode
#
# No pass/fail; this informs deployment, not the decision.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../env.sh"

RESULTS_DIR="${SPIKE_RAW_DIR}"
mkdir -p "${RESULTS_DIR}"

echo "============================================================"
echo "STEP 7: Shared-node fitness (record only)"
echo "============================================================"

# ── 1. Docker coexistence ──────────────────────────────────────
echo ""
echo "=== 1. Docker coexistence ==="
echo "--- Before Podman use ---"
if command -v docker &>/dev/null; then
  docker version 2>&1 | tee "${RESULTS_DIR}/step7_docker_before.log"
  docker ps 2>&1 | tee -a "${RESULTS_DIR}/step7_docker_before.log"
else
  echo "docker not found" | tee "${RESULTS_DIR}/step7_docker_before.log"
fi

echo "--- Podman info ---"
podman info 2>&1 | tee "${RESULTS_DIR}/step7_podman_info.log"

echo "--- After Podman use ---"
if command -v docker &>/dev/null; then
  docker ps 2>&1 | tee -a "${RESULTS_DIR}/step7_docker_before.log"
  echo "Docker still running" | tee -a "${RESULTS_DIR}/step7_docker_before.log"
else
  echo "docker still not found" | tee -a "${RESULTS_DIR}/step7_docker_before.log"
fi

# ── 2. Storage driver A/B ──────────────────────────────────────
echo ""
echo "=== 2. Storage driver A/B (vfs vs overlay) ==="
CURRENT_DRIVER=$(podman info --format '{{.Store.GraphDriverName}}' 2>/dev/null || echo "unknown")
echo "Current storage driver: ${CURRENT_DRIVER}"

# Note the current storage.conf
echo "--- Current storage.conf ---"
cat /etc/containers/storage.conf 2>/dev/null \
  || cat ${HOME}/.config/containers/storage.conf 2>/dev/null \
  || echo "No storage.conf found"

echo ""
echo "NOTE: Running the A/B comparison requires temporarily switching the"
echo "storage driver and pulling a multi-GB image with each. This changes"
echo "host configuration and should be done on a disposable machine."
echo "Record the cold-start time for a multi-gigabyte image with vfs"
echo "and with overlay (plus fuse-overlayfs if needed)."
echo ""
echo "Ray docs warn of 'very slow or hanging container startup' with vfs."
echo "Set a timeout — hanging is a documented outcome."

# ── 3. --privileged requirement ────────────────────────────────
echo ""
echo "=== 3. --privileged requirement ==="
echo "Since the raylet runs on the host (not in a container),"
echo "the expectation is that --privileged is NOT needed."
echo "Record whether it was needed by checking:"
echo "  - raylet runs as the host user"
echo "  - containers are started by podman rootless"
echo ""
echo "Expected: --privileged not required for host-raylet topology."
echo "Note: a devcontainer-hosted raylet WOULD need --privileged"
echo "and -v /var/lib/containers:/var/lib/containers."

# ── 4. /tmp/ray permissions ────────────────────────────────────
echo ""
echo "=== 4. /tmp/ray permissions ==="
echo "Host UID/GID: $(id -u):$(id -g)"
echo "In-container ray user: 1000 (default)"
echo ""
echo "Check for the documented ports_by_node.json.lock permission error:"
echo "  - Create a test /tmp/ray directory"
echo "  - Run a raylet as the host user"
echo "  - Check if the lock file permission error occurs"
echo ""
echo "With --userns=keep-id and proper user mapping, this should"
echo "not occur. Record the observation."

echo ""
echo "============================================================"
echo "STEP 7 COMPLETE — record only, no verdict"
echo "============================================================"

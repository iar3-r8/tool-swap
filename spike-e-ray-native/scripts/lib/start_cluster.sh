#!/usr/bin/env bash
# start_cluster.sh — start a Ray head node and wait for the dashboard to respond.
#
# Called by the "cluster-up" Makefile target.  Uses the environment
# variables from env.sh; falls back to sensible defaults.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/../../env.sh"

# Allow operator overrides via .env or env.sh
RAY_DASHBOARD_PORT="${RAY_DASHBOARD_PORT:-8265}"
MAX_WAIT=90
POLL_INTERVAL=3

echo "============================================================"
echo "Cluster: starting Ray head node"
echo "============================================================"

# ── Ensure no stale cluster is running ──────────────────────────
echo "Checking for stale Ray processes..."
if pgrep -f "raylet" > /dev/null 2>&1 || pgrep -f "ray start" > /dev/null 2>&1; then
    echo "WARNING: Ray processes detected — stopping them before a fresh start"
    ray stop --force 2>&1 || true
    sleep 5
fi

# ── Start the head node ────────────────────────────────────────
# Do NOT set --port: that controls the GCS server port (default 6379).
# If --port and --dashboard-port are set to the same value, Ray
# rejects it with "port number is used by other components".
# We only override --dashboard-port; GCS gets a free port.
#
# IMPORTANT: do NOT use --block here.  --block makes ray start
# foreground-execute the entire cluster lifetime, which means the
# backgrounded process never exits and `wait` blocks forever.
# We want ray running in the background so step scripts can
# connect to it; the cluster-up target should only wait for
# readiness and then return.
#
# WHY umask 0 (D20):
# Ray builds the `podman run` prefix for `runtime_env: {image_uri: ...}`
# workers in image_uri.py (installed Ray 2.57.0,
# ray/_private/runtime_env/image_uri.py, lines 76-96). It passes
# `--userns=keep-id` but NO `--user` flag, and
# ImageURIPlugin.modify_context (same file, ~line 174) hardcodes
# `run_options=[]`, so `--user` cannot be injected through the
# `image_uri` key. The worker therefore runs as the image's own
# `USER ray` (uid 1000, mapped to a subuid via keep-id), NOT as the
# host uid.
#
# Ray creates its unix sockets under /tmp/ray/session_*/sockets/ with
# the default umask 0022 (permissions 0755, owned by the host uid)
# and never chmods them. Connecting to a unix socket requires WRITE
# permission, which 0755 grants only to the owner — so the container
# worker gets EACCES and dies before it registers (raylet reports
# "worker ... dead, probably crashed during start"; no per-worker
# .err file is ever produced).
#
# Fix: run `ray start` under `umask 0` so every file the session
# creates — in particular the raylet/gcs/plasma sockets — is 0777
# and a worker running under a different uid can connect().
#
# SECURITY TRADE-OFF: while the cluster runs, ANY local user on this
# host can connect to the raylet socket and submit tasks to the
# cluster. This is accepted because the host is used by trusted users
# only. Do NOT deploy this pattern on a shared or untrusted host.
#
# The umask is set in the script shell, so the backgrounded
# `ray start` (and the daemons it forks) inherit it; no later
# commands in this script create files, and other scripts do not
# source this file, so nothing unrelated inherits the permissive
# umask.
# D31: the old hard-coded --num-gpus=0 is gone. In Ray 2.57 an explicit
# 0 is NOT "auto-detect": auto-detection runs only when the value is
# None, so --num-gpus=0 registered a raylet with zero GPUs,
# permanently. Steps 3-6 deploy num_gpus: 1 actors and can never be
# scheduled on a zero-GPU raylet, so the step 3 gate would exit 2
# without ever testing GPU swap.
#
# We pin exactly 1 GPU (SPIKE_RAY_NUM_GPUS, default 1) for EVERY step
# instead of auto-detecting all of the host's: with several idle GPUs
# Ray may place tool_torch and tool_tf on DIFFERENT GPUs, and the
# per-GPU VRAM checks would then pass without ever observing
# contention — a false pass of the decisive gate. A 1-GPU cluster
# makes contention structural. Steps 1/2 are unaffected: their
# num_gpus: 0 deployments request zero GPU units and are schedulable
# on a node regardless of its registered GPU count.
#
# If the single GPU is unavailable (busy, MIG-partitioned), set
# SPIKE_RAY_NUM_GPUS=0 deliberately and re-run only the steps that do
# not need GPUs — never silently. The resolved count is printed above
# so the recorded log shows what the cluster actually had.
RAY_NUM_GPUS="${SPIKE_RAY_NUM_GPUS:-1}"
case "${RAY_NUM_GPUS}" in
    ''|*[!0-9]*)
        echo "ERROR: SPIKE_RAY_NUM_GPUS='${SPIKE_RAY_NUM_GPUS}' is not a" >&2
        echo "       non-negative integer." >&2
        exit 1
        ;;
esac
echo "Starting Ray head node (dashboard port ${RAY_DASHBOARD_PORT}, ${RAY_NUM_GPUS} GPU(s))..."
umask 0
ray start --head \
    --dashboard-port="${RAY_DASHBOARD_PORT}" \
    --num-cpus="$(nproc 2>/dev/null || echo 2)" \
    --num-gpus="${RAY_NUM_GPUS}" \
    --no-redirect-output \
    --disable-usage-stats \
    &
RAY_PID=$!

# ── Wait for readiness ─────────────────────────────────────────
echo "Waiting for Ray dashboard at http://localhost:${RAY_DASHBOARD_PORT} (timeout: ${MAX_WAIT}s)..."
ELAPSED=0
while [ "${ELAPSED}" -lt "${MAX_WAIT}" ]; do
    if curl -sf "http://localhost:${RAY_DASHBOARD_PORT}/api/ray/version" > /dev/null 2>&1; then
        echo "Ray dashboard is ready after ${ELAPSED}s"
        echo "Ray head node PID: ${RAY_PID}"
        echo "Cluster is running — step scripts can now connect."
        # Do NOT wait for RAY_PID — ray started without --block will
        # continue running as a background daemon.  Exiting here
        # returns control to the Makefile / step script.
        exit 0
    fi
    sleep "${POLL_INTERVAL}"
    ELAPSED=$((ELAPSED + POLL_INTERVAL))
done

echo "ERROR: Ray dashboard did not become ready within ${MAX_WAIT}s"
ray stop --force 2>&1 || true
exit 1

#!/usr/bin/env bash
# run_with_cluster_clean.sh — start a Ray head node, run a command, then stop the cluster.
#
# Ray's verbose startup output (autoscaler status, worker event stats, raylet
# state dumps) is redirected to a log file so the terminal stays readable.
#
# The caller (the Makefile's $(ENV) wrapper) has already sourced env.sh, so
# this script inherits PYTHONPATH and the rest of the spike environment.
# The first argument is kept for call-site compatibility and is used as a
# command prefix.
#
# Usage:
#   run_with_cluster_clean.sh <cmd-prefix> <command> [args...]
#
# Example:
#   run_with_cluster_clean.sh env python scripts/step1_verify.py
#
# Ray logs are written to: results/raylogs/ray-<timestamp>-<PID>.log
# Exit code is that of the executed command.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# scripts/lib/ -> scripts/ -> spike-e-ray-native/
SPIKE_BASE="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RESULTS_DIR="${SPIKE_BASE}/results/raylogs"
mkdir -p "${RESULTS_DIR}"

if [ $# -lt 2 ]; then
    echo "Usage: run_with_cluster_clean.sh <cmd-prefix> <command> [args...]" >&2
    exit 1
fi

CMD_PREFIX="$1"
shift

RAY_LOG="${RESULTS_DIR}/ray-$(date +%Y%m%dT%H%M%S)Z-$$.log"
RAY_DASH="${RAY_DASHBOARD_PORT:-8265}"

echo "============================================================"
echo "Cluster: starting Ray head node (logs -> ${RAY_LOG})"
echo "============================================================"

# ── Quieten Ray ────────────────────────────────────────────────
export RAY_LOG_TO_DRIVER=0
export RAY_DEDUP_LOGS=1
export RAY_SCHEDULER_EVENTS=0
export RAY_USAGE_STATS_ENABLED=0

# ── Stop any stale cluster ─────────────────────────────────────
echo "Ensuring no stale Ray processes..."
ray stop --force >> "${RAY_LOG}" 2>&1 || true
sleep 2

# ── Start head node ────────────────────────────────────────────
echo "Starting head node (dashboard port ${RAY_DASH})..."
ray start --head \
    --dashboard-port="${RAY_DASH}" \
    --num-cpus="$(nproc 2>/dev/null || echo 2)" \
    --num-gpus=0 \
    --disable-usage-stats \
    >> "${RAY_LOG}" 2>&1
START_RC=$?

if [ "${START_RC}" -ne 0 ]; then
    echo "ERROR: 'ray start --head' exited ${START_RC}. Last 30 log lines:" >&2
    tail -30 "${RAY_LOG}" >&2
    exit 1
fi

# ── Wait for dashboard readiness ───────────────────────────────
MAX_WAIT=90
POLL=3
READY=0
for i in $(seq 1 $((MAX_WAIT / POLL))); do
    if curl -sf "http://localhost:${RAY_DASH}/api/ray/version" > /dev/null 2>&1; then
        echo "Ray dashboard ready after $((i * POLL))s"
        READY=1
        break
    fi
    sleep "${POLL}"
done

if [ "${READY}" -ne 1 ]; then
    echo "ERROR: Ray dashboard not ready within ${MAX_WAIT}s. Last 30 log lines:" >&2
    tail -30 "${RAY_LOG}" >&2
    ray stop --force >> "${RAY_LOG}" 2>&1 || true
    exit 1
fi

echo "============================================================"
echo "Running: $*"
echo "============================================================"

"${CMD_PREFIX}" "$@"
CMD_EXIT=$?

# ── Stop cluster ───────────────────────────────────────────────
echo ""
echo "============================================================"
echo "Stopping Ray cluster (step exit code ${CMD_EXIT})"
echo "============================================================"
ray stop --force >> "${RAY_LOG}" 2>&1 || true

echo "Ray log: ${RAY_LOG}"

if [ "${CMD_EXIT}" -ne 0 ]; then
    echo ""
    echo "=== Ray log (last 30 lines) ==="
    tail -30 "${RAY_LOG}"
fi

exit "${CMD_EXIT}"

#!/usr/bin/env bash
# run_with_cluster.sh — start a Ray head node, run a command, then stop the cluster.
#
# Usage:
#   run_with_cluster.sh <env-target> <command> [args...]
#
# Example:
#   run_with_cluster.sh env python scripts/step1_verify.py
#
# The <env-target> is the Makefile variable ENV (which sources env.sh
# and sets up the environment).  This script:
#   1. Stops any existing Ray cluster
#   2. Starts a fresh Ray head node
#   3. Waits for the dashboard to respond
#   4. Runs the given command
#   5. Stops the Ray cluster
#
# The exit code is that of the executed command.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ $# -lt 2 ]; then
    echo "Usage: run_with_cluster.sh <env-target> <command> [args...]" >&2
    exit 1
fi

ENV_TARGET="$1"
shift

echo "============================================================"
echo "run_with_cluster.sh: starting temporary Ray cluster"
echo "============================================================"

# ── Stop any stale cluster ──────────────────────────────────────
echo "Ensuring no stale Ray processes..."
eval "${ENV_TARGET}" ray stop --force 2>&1 || true
sleep 3

# ── Start head node (same logic as start_cluster.sh) ───────────
${ENV_TARGET} bash "${SCRIPT_DIR}/start_cluster.sh"

# ── Run the command ────────────────────────────────────────────
echo "============================================================"
echo "Running: $*"
echo "============================================================"

# Create a directory for Ray's per-process log files so verbose Ray
# output (autoscaler status, worker event stats, raylet state dumps)
# doesn't flood the terminal and drown out our step output.
RAY_LOG_DIR=$(mktemp -d)
export RAY_DEDUP_LOGS=1       # deduplicate identical log lines
export RAY_LOG_TO_DRIVER=0    # don't forward logs to driver stdout
export RAY_WORKER_LOGS_DIR="${RAY_LOG_DIR}"

# Export RAY_LOG_TO_DRIVER=0 so that `serve deploy` (which uses
# ray.init() internally) also redirects Ray logs to files.
set +e
RAY_LOG_DIR="${RAY_LOG_DIR}" eval "${ENV_TARGET}" "$@" 2>&1
CMD_EXIT=$?
set -e

# Clean up Ray log directory
rm -rf "${RAY_LOG_DIR}"

# ── Stop cluster ───────────────────────────────────────────────
echo ""
echo "============================================================"
echo "Stopping Ray cluster after exit code ${CMD_EXIT}"
echo "============================================================"
eval "${ENV_TARGET}" ray stop --force 2>&1 || true

exit "${CMD_EXIT}"

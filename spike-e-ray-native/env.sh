#!/usr/bin/env bash
# env.sh — source this in your shell or execute it.
#
# IMPORTANT: this file deliberately does NOT set -e at the top level.
# When sourced into an interactive shell, `set -e` would propagate into
# the caller and any subsequent non-zero command would terminate the
# terminal. Strict mode is applied only inside scripts that source us
# and exec a command (build_images.sh, step7_podman.sh already guard
# themselves with `set -euo pipefail`).
#
# Usage:
#   source env.sh          # exports variables into the caller's shell
#   bash env.sh            # prints them (debug)
#   bash scripts/step1.sh  # scripts source us then exec their command

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Allow operator override via .env; fall back to .env.example
if [[ -f "${SCRIPT_DIR}/.env" ]]; then
  set -a; source "${SCRIPT_DIR}/.env"; set +a
else
  set -a; source "${SCRIPT_DIR}/.env.example"; set +a
fi

# Provide defaults for variables that .env.example may not set
: "${RAY_BASE_TAG:=rayproject/ray:2.57.0-py311-gpu}"
: "${WEIGHTS_MB:=8}"
: "${PAYLOAD_MB:=64}"
: "${SERVE_DEPLOY_DIR:=${SCRIPT_DIR}/apps}"

export SCRIPT_DIR RAY_BASE_TAG WEIGHTS_MB PAYLOAD_MB \
       RAY_CLUSTER_ADDRESS SERVE_DEPLOY_DIR CONTAINER_RUNTIME

export SPIKE_RESULTS_DIR="${SCRIPT_DIR}/results"
export SPIKE_RAW_DIR="${SPIKE_RESULTS_DIR}/raw"
export SPIKE_METRICS_DIR="${SPIKE_RESULTS_DIR}/metrics"

# PYTHONPATH includes the root (for toolkit/ modules) and apps/
# (for serve deploy import_path modules like step1_two_deployments).
# Ray workers inherit PYTHONPATH from the parent process, so this
# env var flows to the cluster's Python subprocesses too.
export PYTHONPATH="${SCRIPT_DIR}:${SCRIPT_DIR}/apps:${PYTHONPATH:-}"

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

# Namespaced (not the generic SCRIPT_DIR) so sourcing this file cannot
# clobber a caller's own SCRIPT_DIR local (see fixtures/build_images.sh).
SPIKE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Allow operator override via .env; fall back to .env.example
if [[ -f "${SPIKE_ROOT}/.env" ]]; then
  set -a; source "${SPIKE_ROOT}/.env"; set +a
else
  set -a; source "${SPIKE_ROOT}/.env.example"; set +a
fi

# Provide defaults for variables that .env.example may not set
: "${RAY_BASE_TAG:=docker.io/rayproject/ray:2.57.0-py311-gpu}"
: "${WEIGHTS_MB:=8}"
: "${PAYLOAD_MB:=64}"
: "${SERVE_DEPLOY_DIR:=${SPIKE_ROOT}/apps}"
# Readiness wait for the step verify scripts (D25): total budget and
# poll interval. 300s default — the fixture images are ~14-19GB and a
# first podman start is slow; 60s (the old hard-coded wait) was not
# enough. Raise on slower hosts.
: "${SPIKE_READINESS_TIMEOUT_S:=300}"
: "${SPIKE_READINESS_POLL_S:=5}"
# Step 3 gate (D31): GPUs the cluster registers. Pinned at 1 so the
# step 3 tools are forced onto the same GPU (contention is structural,
# not observed after the fact); see scripts/lib/start_cluster.sh.
: "${SPIKE_RAY_NUM_GPUS:=1}"

export SPIKE_ROOT RAY_BASE_TAG WEIGHTS_MB PAYLOAD_MB \
       RAY_CLUSTER_ADDRESS SERVE_DEPLOY_DIR CONTAINER_RUNTIME \
       SPIKE_READINESS_TIMEOUT_S SPIKE_READINESS_POLL_S \
       SPIKE_RAY_NUM_GPUS

export SPIKE_RESULTS_DIR="${SPIKE_ROOT}/results"
export SPIKE_RAW_DIR="${SPIKE_RESULTS_DIR}/raw"
export SPIKE_METRICS_DIR="${SPIKE_RESULTS_DIR}/metrics"

# PYTHONPATH includes the root (for toolkit/ modules) and apps/
# (for serve deploy import_path modules like step1_two_deployments).
# Ray workers inherit PYTHONPATH from the parent process, so this
# env var flows to the cluster's Python subprocesses too.
export PYTHONPATH="${SPIKE_ROOT}:${SPIKE_ROOT}/apps:${PYTHONPATH:-}"

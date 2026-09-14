SHELL := /bin/bash

ENV  := bash -c 'set -a; . ./env.sh; set +a; exec "$$@"' _
CAPTURE_ENV := $(ENV) python scripts/capture_env.py

.PHONY: all env cluster-up fixtures step1 step2 step3 step3-container step4 step5 step6 step7 step8 step9 clean preflight

all: env fixtures step1 step2 step3 step4 step5 step6 step7

env:
	@$(CAPTURE_ENV)

# ── Fixtures (podman) ─────────────────────────────────────────────

fixtures: env
	@$(ENV) bash fixtures/build_images.sh

# ── Spikes (per-step cluster lifecycle) ───────────────────────────
# Each step starts its own cluster, runs the step, then tears it down.
# This gives clean isolation between runs.

step1: env
	@$(ENV) bash scripts/lib/run_with_cluster_clean.sh env python scripts/step1_verify.py

step2: env
	@$(ENV) bash scripts/lib/run_with_cluster_clean.sh env python scripts/step2_verify.py

step3: env
	@$(ENV) bash scripts/lib/run_with_cluster_clean.sh env python scripts/step3_gate.py

# Step 3 variant — the same gate through the legacy `container`
# runtime_env key (D34: its run_options can pass
# --runtime nvidia-container-runtime, which image_uri cannot). The
# gate script is identical; only the config and the recording step
# name differ (SPIKE_STEP3_CONFIG / SPIKE_STEP). Runs exactly like
# step3: own cluster, same recorder conventions, same exit codes.
step3-container: env
	@$(ENV) bash scripts/lib/run_with_cluster_clean.sh env \
		SPIKE_STEP3_CONFIG=apps/step3_config_container.yaml \
		SPIKE_STEP=step3-container \
		python scripts/step3_gate.py

step4: env
	@$(ENV) bash scripts/lib/run_with_cluster_clean.sh env python scripts/step4_payload.py

step5: env
	@$(ENV) bash scripts/lib/run_with_cluster_clean.sh env python scripts/step5_alternate.py

step6: env
	@$(ENV) bash scripts/lib/run_with_cluster_clean.sh env python scripts/step6_restart.py

step7: env
	@$(ENV) bash scripts/lib/run_with_cluster_clean.sh env bash scripts/step7_podman.sh

# Step 8 — plain-podman alternation baseline (D45). Deliberately NOT
# wrapped in run_with_cluster_clean.sh: the step's whole point is to
# measure plain podman with NO Ray — starting a cluster would pollute
# the baseline (a running raylet is a co-tenant on the GPU host) and
# contradict the measurement. It runs directly against the podman
# store and the GPU, like a fixtures/ script.
step8: env
	@$(ENV) python scripts/step8_podman_baseline.py

# Step 9 — phase timing of the alternation cycle (D47). The same
# step-5 setup (external scaler, container-key runtime_env)
# instrumented with per-cycle phase boundaries and podman container
# correlation: it finds WHERE Ray's ~95s slow mode goes. Own clean
# cluster, like every other Ray step.
step9: env
	@$(ENV) bash scripts/lib/run_with_cluster_clean.sh env python scripts/step9_phase_timing.py

preflight:
	@bash scripts/lib/preflight.sh

clean:
	rm -rf results/raw/* results/metrics/*

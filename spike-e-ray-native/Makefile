SHELL := /bin/bash

ENV  := bash -c 'set -a; . ./env.sh; set +a; exec "$$@"' _
CAPTURE_ENV := $(ENV) python scripts/capture_env.py

.PHONY: all env cluster-up fixtures step1 step2 step3 step4 step5 step6 step7 clean preflight

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

step4: env
	@$(ENV) bash scripts/lib/run_with_cluster_clean.sh env python scripts/step4_payload.py

step5: env
	@$(ENV) bash scripts/lib/run_with_cluster_clean.sh env python scripts/step5_alternate.py

step6: env
	@$(ENV) bash scripts/lib/run_with_cluster_clean.sh env python scripts/step6_restart.py

step7: env
	@$(ENV) bash scripts/lib/run_with_cluster_clean.sh env bash scripts/step7_podman.sh

preflight:
	@bash scripts/lib/preflight.sh

clean:
	rm -rf results/raw/* results/metrics/*

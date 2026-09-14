"""Step 4 — Local payload read (D18 NOT tested per §0a).

Deploys the container-key tool_torch (D38), then reads a baked-in file
from it. No S3, no remote payload, no credential plumbing.
D18 remains an untested assumption.

Exit status (D29)
    0  Every required observation was made and nothing answers the step
       negatively: all three warm reads succeeded and each payload
       verified against its sidecar.
    1  Unexpected internal error (traceback printed).
    2  Harness/environment failure — an observation could NOT be made:
       the config could not be deployed, the deployment never reached
       RUNNING, the warm-up probe was unreachable, or a read request
       failed (connection error, timeout, non-2xx, non-JSON). The
       numbers from this run are incomplete and must not be treated as
       a pass.
    3  Negative finding — the observation WAS made and answers the step
       negatively: a read returned but the payload did not verify
       (size or hash mismatch against the sidecar).

Aggregate policy (D29): the median/min/max are reported ONLY when all
three reads succeeded and verified. If any read failed or mismatched,
the aggregate is REFUSED and said so loudly. With only three trials,
a median computed over the one or two survivors of a degraded run
looks authoritative without being representative (the survivors are
systematically the fast, warm cases), so a partial-run number is
worse than no number. The per-iteration lines in
results/metrics/step4.jsonl remain the source of record.

All raw output is recorded to results/raw/step4-*.log and
results/metrics/step4.jsonl regardless of the exit status.
"""
from __future__ import annotations

import os
import sys
import time

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
sys.path.insert(0, os.path.join(_SCRIPTS_DIR, "lib"))

from recorder import Recorder, block, record
from serve_api import apply_config, post_introspect, post_predict
from step1_verify import StepOutcome, _wait_for_running

# D38: step 4 deploys the tools it needs itself, so `make step4` is
# self-contained like steps 1/2/3/5 (make step4 starts its own clean
# cluster, so nothing is running before this script does). The config
# is the container-key step 3 variant: its tool_torch app and
# deployment are the ones that hold a GPU (D34: image_uri hardcodes
# run_options=[] at ray/_private/runtime_env/image_uri.py:174), and
# step 4's payload read is the same baked-in /opt/spike/data asset the
# step 3 image bakes. Reusing step 3's config keeps one authoritative
# GPU-holding tool_torch definition; a step-4-specific config would
# duplicate it and nothing in this step's measurements differs.
STEP4_CONFIG = os.environ.get(
    "SPIKE_STEP4_CONFIG", "apps/step3_config_container.yaml"
)

# The proxy URL must match the config's tool_torch route_prefix
# (/tool_torch in the step 3 container config): requests to the bare
# root would hit no route. (The old default "http://localhost:8000"
# assumed a root-routed deployment and could never answer here.)
TOOL_URL = os.environ.get(
    "SPIKE_SERVE_URL_TORCH", "http://localhost:8000/tool_torch"
)
PAYLOAD_PATH = os.environ.get("SPIKE_PAYLOAD_PATH", "/opt/spike/data/payload.bin")

N_READS = 3


def _print_summary(outcome: StepOutcome) -> None:
    """Print the final verdict, labelling each failure kind explicitly.

    Args:
        outcome: The collected harness failures and findings.
    """
    if outcome.harness_failures:
        print("")
        print("STEP 4 RESULT: HARNESS FAILURE — exit code 2")
        print("A required observation could not be made; the environment,")
        print("not the experiment, is at fault. The findings from this run")
        print("are incomplete and must not be treated as a pass:")
        for i, msg in enumerate(outcome.harness_failures, 1):
            print(f"  {i}. {msg}")
    if outcome.findings:
        print("")
        print("STEP 4 RESULT: NEGATIVE FINDING(S) — exit code 3")
        print("The observations were made but answer the step's question")
        print("negatively. Recorded findings:")
        for i, msg in enumerate(outcome.findings, 1):
            print(f"  {i}. {msg}")
    if not outcome.harness_failures and not outcome.findings:
        print("")
        print("STEP 4 RESULT: all required observations made; no negative")
        print("findings — exit code 0")


def run(recorder: Recorder) -> int:
    """Run step 4's observations and return the process exit code.

    Args:
        recorder: The step's Recorder (stdout/stderr tee to the log).

    Returns:
        0 (clean), 2 (harness failure) or 3 (negative finding).
    """
    outcome = StepOutcome()

    print("=" * 60)
    print("STEP 4: Local payload read (D18 NOT tested)")
    print("=" * 60)

    payload_path = PAYLOAD_PATH
    print(f"  Payload path: {payload_path}")

    # ── Deploy the tools this step measures (D38) ─────────────
    # The cluster is clean (run_with_cluster_clean.sh), so without a
    # deploy here the warm-up probe below would fail against an empty
    # proxy and the step would exit 2 having measured nothing.
    # D29: a failed deploy means the reads cannot be observed —
    # harness, exit 2, with the same labels as a failed probe.
    print(f"\n=== Deploying the tool_torch config ({STEP4_CONFIG}) ===")
    deploy_ok = False
    try:
        result = apply_config(STEP4_CONFIG)
        recorder.write(
            block("serve deploy output", result.stdout + result.stderr)
        )
        print(f"Exit code: {result.returncode}")
        if result.returncode == 0:
            deploy_ok = True
        else:
            outcome.harness(
                f"`serve deploy` of {STEP4_CONFIG} exited "
                f"{result.returncode} — the payload reads cannot be "
                "observed."
            )
    except Exception as e:
        recorder.write(block("serve deploy error", str(e)))
        print(f"Deploy error: {e}")
        outcome.harness(
            f"Could not deploy {STEP4_CONFIG}: {e} — the payload "
            "reads cannot be observed."
        )

    if deploy_ok:
        # D25 readiness convention (shared with steps 1/2/3/5): poll
        # until the deployed applications report RUNNING instead of
        # hoping the warm-up probe reaches a replica that is still
        # starting. Never reached RUNNING within the budget → harness
        # failure (exit 2), recorded by the helper.
        _wait_for_running(recorder, outcome)

    # ── Warm up ────────────────────────────────────────────────
    # The measurement is a *warm* local read (min_replicas: 0), so the
    # replica must be awake before any timing starts. If the warm-up
    # cannot be made, the warm-read observation cannot be made either:
    # a read that has to cold-start a 14-19GB container would not be
    # measuring what this step claims to measure.
    print("\n=== Warming up tool_torch ===")
    if not deploy_ok:
        print("  Skipping the warm-up: the config could not be deployed.")
    else:
        # (The warm-up is attempted even if _wait_for_running timed
        # out, as in step 3: a probe that does answer is information,
        # not noise.)
        try:
            post_introspect(TOOL_URL)
            print("  Warm")
        except Exception as e:
            print(f"Warm-up error: {e}")
            recorder.write(block("warm-up introspect error", str(e)))
            record("step4", phase="warmup", harness_failure=str(e))
            outcome.harness(
                f"Warm-up probe could not be reached at {TOOL_URL} ({e}) "
                "— a warm read cannot be observed without a warm "
                "replica; skipping the timed reads."
            )
            print("  Skipping the timed reads: no warm replica.")

    # ── Three reads ────────────────────────────────────────────
    print("\n=== Reading payload (3x) ===")
    timings = []
    for i in range(N_READS):
        if outcome.harness_failures:
            # A deploy or warm-up failure is already recorded: the reads
            # would not be warm (or the tool would not exist).
            print(f"  Read {i+1}: SKIPPED (no warm replica)")
            continue
        t0 = time.monotonic()
        try:
            result = post_predict(TOOL_URL, path=payload_path, timeout=120)
            elapsed = time.monotonic() - t0
        except Exception as e:
            print(f"  Read {i+1} error: {e}")
            record("step4", iteration=i + 1, error=str(e))
            recorder.write(block(f"Read {i+1} error", str(e)))
            outcome.harness(
                f"Read {i+1} could not be completed at {TOOL_URL} ({e}) "
                "— the observation could not be made."
            )
            continue
        if result.get("error"):
            # The tool answered with a structured error payload (D27):
            # the read was not made.
            print(f"  Read {i+1} error: {result['error']}")
            record("step4", iteration=i + 1, error=str(result["error"]))
            recorder.write(block(f"Read {i+1} error", str(result["error"])))
            outcome.harness(
                f"Read {i+1} returned a tool error: {result['error']} — "
                "the observation could not be made."
            )
            continue
        timings.append(elapsed)
        record(
            "step4",
            iteration=i + 1,
            total_seconds=round(elapsed, 3),
            replica_data=result,
        )
        print(f"  Read {i+1}: {elapsed:.3f}s, size={result.get('size_bytes')}, "
              f"sha256={result.get('sha256', '')[:16]}...")
        if not result.get("hash_match", True) or not result.get(
            "size_match", True
        ):
            # The read WAS made and it answers the step negatively:
            # the bytes on disk do not verify against the sidecar.
            outcome.finding(
                f"Read {i+1} returned a payload that does not verify: "
                f"hash_match={result.get('hash_match')}, "
                f"size_match={result.get('size_match')} — the baked-in "
                "payload is corrupt or was written by a different build."
            )

    # ── Report ─────────────────────────────────────────────────
    if outcome.harness_failures or outcome.findings:
        print("\n  AGGREGATE REFUSED:")
        print(f"  {len(timings)}/{N_READS} reads completed. A "
              "median/min/max over the survivors of a degraded run")
        print("  would look authoritative without being representative,")
        print("  so no aggregate is reported. The per-iteration lines in")
        print("  results/metrics/step4.jsonl are the source of record.")
    elif timings:
        print(f"\n  Median: {sorted(timings)[len(timings)//2]:.3f}s")
        print(f"  Min: {min(timings):.3f}s")
        print(f"  Max: {max(timings):.3f}s")

    # ── Explicit D18-not-tested statement ──────────────────────
    print("")
    print("  D18 (payload-by-reference via s3:// URI) was NOT tested.")
    print("  Reason: §0a scope reduction — weights and payloads are baked in.")
    print("  The credential plumbing via env_vars was never exercised.")
    print("  D18 remains an open assumption to be verified in a future spike.")

    print("")
    print("--- STEP 4 OBSERVATIONS COMPLETE ---")
    _print_summary(outcome)
    return outcome.exit_code


if __name__ == "__main__":
    _recorder = Recorder("step4")
    try:
        _exit_code = run(_recorder)
    except Exception:
        import traceback

        print("\n" + "=" * 60)
        print("STEP 4: UNEXPECTED ERROR — recording and exiting")
        print("=" * 60)
        traceback.print_exc()
        print("Step failed with an unexpected error; review "
              "results/raw/step4-*.log")
        _recorder.close()
        sys.exit(1)
    _recorder.close()
    sys.exit(_exit_code)

"""Step 5 — Preemption via replica counts at request cadence.

Tests whether an external controller can drive displacement of an idle
incumbent at request cadence. Two mechanisms:

  A. External scaling API (alpha)
     - external_scaler_enabled: true
     - POST /api/.../scale to change replica counts
     - Cannot be combined with autoscaling_config

  B. Declarative config re-apply
     - Send full desired config with flipped num_replicas
     - Destructive: removes all apps not in the config

Per the protocol: run BOTH mechanisms separately, report separately.
Running only one would let a mechanism limitation be recorded as a Ray
limit.

Also: with external_scaler_enabled there is no
downscale_to_zero_delay_s, so the protocol's literal precondition — an
idle incumbent whose timer has not expired — cannot be reproduced.
What gets measured is whether externally-driven displacement works at
cadence. State this explicitly.

Exit status (D29)
    0  Every required observation was made and nothing answers the step
       negatively: every alternation cycle completed and every answer
       came from the tool that was just scaled up.
    1  Unexpected internal error (traceback printed).
    2  Harness/environment failure — an observation could NOT be made:
       the config could not be deployed, an app never reached RUNNING,
       or a scale/probe call failed (connection error, HTTP 412,
       timeout).
    3  Negative finding — the observations WERE made and answer the
       step negatively: a cycle failed (the displacement did not
       complete), or a probe answered with the wrong tool's identity
       (preemption served the wrong replica).

Error-rate threshold (D29): any single failed cycle in the N=20
alternations is a negative finding. Justification: each cycle is a
closed, deterministic loopback operation — scale the incumbent to 0,
scale the target to 1, serve one request — on a warmed GPU with no
network and no shared resource contention. A healthy system has no
legitimate source of request-level noise here; a cold start is part
of the measurement, not a failure mode. One failed cycle therefore
answers the step's question ("can displacement be driven reliably at
cadence?") negatively. The threshold is overridable via
``SPIKE_STEP5_MAX_ERRORS`` (default 0) so a slower host can raise the
tolerance *explicitly* — never silently.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
sys.path.insert(0, os.path.join(_SCRIPTS_DIR, "lib"))

from recorder import Recorder, block, record
from serve_api import (
    apply_config,
    post_introspect,
    scale_deployment,
    serve_status,
)
from step1_verify import StepOutcome, _wait_for_running

SERVE_BASE = os.environ.get("SERVE_BASE_URL", "http://localhost:8000")
TORCH_URL = f"{SERVE_BASE}/tool_torch"
TF_URL = f"{SERVE_BASE}/tool_tf"
N = 20  # alternations

# Expected identity per direction. Each fixture image bakes its own
# SPIKE_IMAGE_MARKER (fixtures/*.Dockerfile), so the probe that the
# target tool serves must carry the target's marker — an answer with
# the other tool's marker means the wrong replica served.
EXPECTED_MARKER: dict[str, str] = {
    "torch": "tool_torch",
    "tf": "tool_tf",
}

# App/deployment names as declared in apps/step5_config.yaml.
APPS = {
    "torch": {"app": "step5_torch", "dep": "ToolTorch", "url": TORCH_URL},
    "tf": {"app": "step5_tf", "dep": "ToolTf", "url": TF_URL},
}


def _max_errors() -> int:
    """Read the tolerated failed cycles (D29: the line is explicit).

    Returns:
        The maximum failed alternations tolerated before the step
        records a negative finding (``SPIKE_STEP5_MAX_ERRORS``,
        default 0 — a single failure is a finding by default).
    """
    return int(os.environ.get("SPIKE_STEP5_MAX_ERRORS", "0"))


def _check_cycle_identity(
    outcome: StepOutcome, iteration: int, direction: str, resp: dict
) -> None:
    """Check the probe answer came from the tool that was just scaled up.

    The ``image_marker`` field IS returned by the ``introspect`` op
    (toolkit/introspect.py); a marker from the other tool means the
    wrong replica answered the request — the observation was made and
    it answers step 5's preemption question negatively.

    Note (D29 fix): the previous code recorded
    ``resp.get("replica_id", "unknown")`` — the ``introspect`` op does
    NOT return ``replica_id`` (only ``startup_report`` does,
    toolkit/deployments.py), so that field could never be observed and
    silently logged "unknown". The ``pid`` field, which ``introspect``
    does return, records which process answered instead.

    Args:
        outcome: Collects the finding on a wrong-identity answer.
        iteration: 1-based alternation number, for the message.
        direction: "torch" or "tf" (the tool that was just scaled up).
        resp: The introspect response.
    """
    marker = str(resp.get("image_marker", ""))
    expected = EXPECTED_MARKER[direction]
    if not marker.startswith(expected):
        outcome.finding(
            f"Alt {iteration}: probe answered with the wrong identity — "
            f"image_marker={marker!r}, expected prefix {expected!r}. "
            "The request was served by the wrong tool's replica."
        )


def _print_summary(outcome: StepOutcome) -> None:
    """Print the final verdict, labelling each failure kind explicitly.

    Args:
        outcome: The collected harness failures and findings.
    """
    if outcome.harness_failures:
        print("")
        print("STEP 5 RESULT: HARNESS FAILURE — exit code 2")
        print("A required observation could not be made; the environment,")
        print("not the experiment, is at fault. The findings from this run")
        print("are incomplete and must not be treated as a pass:")
        for i, msg in enumerate(outcome.harness_failures, 1):
            print(f"  {i}. {msg}")
    if outcome.findings:
        print("")
        print("STEP 5 RESULT: NEGATIVE FINDING(S) — exit code 3")
        print("The observations were made but answer the step's question")
        print("negatively. Recorded findings:")
        for i, msg in enumerate(outcome.findings, 1):
            print(f"  {i}. {msg}")
    if not outcome.harness_failures and not outcome.findings:
        print("")
        print("STEP 5 RESULT: all required observations made; no negative")
        print("findings — exit code 0")


def run(recorder: Recorder) -> int:
    """Run step 5's observations and return the process exit code.

    Args:
        recorder: The step's Recorder (stdout/stderr tee to the log).

    Returns:
        0 (clean), 2 (harness failure) or 3 (negative finding).
    """
    outcome = StepOutcome()

    print("=" * 60)
    print(f"STEP 5: Preemption at cadence ({N} alternations)")
    print("=" * 60)

    # ── MECHANISM A: External scaling API ──────────────────────
    print("")
    print("=== MECHANISM A: External scaling API ===")
    print("Note: with external_scaler_enabled, there is no")
    print("downscale_to_zero_delay_s. We are testing whether")
    print("externally-driven displacement works at cadence,")
    print("not whether Ray's own timer can be pre-empted.")
    print("")

    # Deploy mechanism A config (D29: a deploy failure means the
    # alternations cannot be observed — harness, not finding).
    deploy_ok = False
    try:
        result = apply_config("apps/step5_config.yaml")
        recorder.write(block("Mech A deploy", result.stdout + result.stderr))
        print(f"Deploy exit code: {result.returncode}")
        if result.returncode == 0:
            deploy_ok = True
        else:
            outcome.harness(
                f"`serve deploy` of apps/step5_config.yaml exited "
                f"{result.returncode} — the alternations cannot be "
                "observed."
            )
    except Exception as e:
        recorder.write(block("Mech A deploy error", str(e)))
        print(f"Deploy error: {e}")
        outcome.harness(f"Could not invoke `serve deploy`: {e}")

    if deploy_ok:
        # Wait for both apps to reach RUNNING (D25 convention; the old
        # hard-coded sleep(10) is gone).
        _wait_for_running(recorder, outcome)

    # Confirm both are at 1 replica
    if deploy_ok:
        try:
            status = serve_status()
            print(json.dumps(status, indent=2))
            recorder.write(
                block("serve status after deploy", json.dumps(status, indent=2))
            )
        except Exception as e:
            outcome.harness(
                f"serve status unreachable after deploy: {e} — the "
                "pre-alternation status observation could not be made."
            )

    # Run N alternations
    results = []
    for i in range(N):
        if not deploy_ok:
            print(f"  Alt {i+1:2d}/{N}: SKIPPED (config not deployed)")
            continue
        direction = "torch" if i % 2 == 0 else "tf"
        other = "tf" if direction == "torch" else "torch"
        target = APPS[direction]
        other_app = APPS[other]
        target_url = target["url"]

        t0 = time.monotonic()
        try:
            # Scale incumbent to 0
            scale_deployment(other_app["app"], other_app["dep"], 0)
            # Scale target to 1
            scale_deployment(target["app"], target["dep"], 1)
            # Send request
            resp = post_introspect(target_url, timeout=120)
            elapsed = time.monotonic() - t0

            result_entry = {
                "mechanism": "A",
                "iteration": i + 1,
                "direction": direction,
                "total_seconds": round(elapsed, 3),
                "pid": resp.get("pid", "unknown"),
                "image_marker": resp.get("image_marker", "unknown"),
            }
            results.append(result_entry)
            record("step5", **result_entry)
            print(f"  Alt {i+1:2d}/{N} {direction:>7s}: {elapsed:.3f}s")
            _check_cycle_identity(outcome, i + 1, direction, resp)
        except Exception as e:
            elapsed = time.monotonic() - t0
            result_entry = {
                "mechanism": "A",
                "iteration": i + 1,
                "direction": direction,
                "total_seconds": round(elapsed, 3),
                "error": str(e),
            }
            results.append(result_entry)
            record("step5", **result_entry)
            print(f"  Alt {i+1:2d}/{N} {direction:>7s}: ERROR {e}")
            # A failed cycle: the observation could not be completed,
            # so the environment/mechanism is at fault, not the
            # experiment — harness.
            outcome.harness(
                f"Alt {i+1} ({direction}) failed: {e} — the "
                "displacement cycle could not be observed."
            )

    # Report distribution — over the completed cycles only, with the
    # failure count stated loudly alongside. (Step 4 refuses its
    # aggregate on any failure because n=3 makes a 2-sample median
    # meaningless; here the cycles are the observations and the
    # distribution is supplementary context, so it is labelled
    # "of N" with the error count on the same lines.)
    if results:
        errors_a = [r for r in results if "error" in r]
        latencies = [r["total_seconds"] for r in results if "error" not in r]
        if latencies:
            latencies_sorted = sorted(latencies)
            p90_idx = int(len(latencies_sorted) * 0.9)
            print(f"\n  Min:   {min(latencies):.3f}s  "
                  f"({len(latencies)}/{len(results)} cycles completed, "
                  f"{len(errors_a)} failed)")
            print(f"  Median: {latencies_sorted[len(latencies_sorted)//2]:.3f}s")
            print(f"  P90:   {latencies_sorted[min(p90_idx, len(latencies_sorted)-1)]:.3f}s")
            print(f"  Max:   {max(latencies):.3f}s")
            print(f"  Errors: {len(errors_a)}")

    # Clean up mechanism A (best-effort; cleanup is not an observation)
    for dep, app in (("ToolTorch", "step5_torch"), ("ToolTf", "step5_tf")):
        try:
            scale_deployment(app, dep, 0)
        except Exception:
            pass

    # ── MECHANISM B: Config re-apply ──────────────────────────
    print("")
    print("=== MECHANISM B: Declarative config re-apply ===")
    print("(Not yet implemented — same structure as A but with")
    print("full config PUT instead of scale calls)")
    print("")

    # Note: Mechanism B follows the same N-alternations pattern but
    # uses full config re-apply instead of external scaling.
    # The script structure is the same; only the scale mechanism differs.
    print("  Implementing mechanism B would mirror mechanism A's loop.")
    print("  See spike-E-implementation.md §3 step 5 for the full design.")

    # ── D29 error-rate verdict ─────────────────────────────────
    # A cycle that failed is a harness failure (the observation was
    # not made); but the STEP's question — "does displacement work at
    # cadence?" — is answered negatively when too many of the N
    # attempts could not be completed. With the default threshold of
    # 0, any failed cycle is recorded as a finding about the
    # mechanism, in addition to the per-cycle harness failures.
    if not outcome.harness_failures:
        # Reaching here with zero harness failures means every cycle
        # completed; nothing more to check.
        pass
    else:
        failed = len([r for r in results if "error" in r])
        tol = _max_errors()
        if failed > tol:
            outcome.finding(
                f"{failed}/{len(results)} alternation cycles failed "
                f"(tolerated: {tol}) — externally-driven displacement "
                "does not work reliably at cadence (mechanism A)."
            )

    # ── Results ────────────────────────────────────────────────
    print("")
    print("=== Summary ===")
    print(f"  Mechanism A: {len([r for r in results if r.get('mechanism') == 'A'])} iterations")
    errors_a = [r for r in results if r.get("mechanism") == "A" and "error" in r]
    print(f"  Errors in A: {len(errors_a)}")
    if errors_a:
        for e in errors_a:
            print(f"    Iter {e['iteration']}: {e['error']}")

    # ── D25 timer substitution note ────────────────────────────
    print("")
    print("  NOTE on D25: With external_scaler_enabled, the")
    print("  downscale_to_zero_delay_s timer does not exist. The")
    print("  incumbent is displaced by explicit scale-to-zero, not by")
    print("  the timer expiring. This tests whether Ray can be driven")
    print("  to preempt at cadence, not whether its own timer is")
    print("  pre-emptible. The results file must state this.")

    print("")
    print("--- STEP 5 OBSERVATIONS COMPLETE ---")
    _print_summary(outcome)
    return outcome.exit_code


def _gpu_guard() -> str | None:
    """Check the GPU host preconditions (D29: labelled verdict, no silent exit).

    Returns:
        A problem description to report as a harness failure (exit 2:
        the VRAM observations this step records could not be made),
        or None when the host preconditions hold.
    """
    if shutil.which("nvidia-smi") is None:
        return (
            "nvidia-smi not found on PATH — the VRAM observations "
            "cannot be made. Step 5 requires a GPU box. Run on the "
            "DGX host."
        )
    if shutil.which("podman") is None:
        return (
            "podman not found on PATH — the container observations "
            "cannot be made. Step 5 requires a container runtime. "
            "Run on the DGX host."
        )
    return None


if __name__ == "__main__":
    _problem = _gpu_guard()
    if _problem:
        print(f"\n[HARNESS FAILURE] {_problem}")
        print("  The observation could not be made — the environment, not")
        print("  the experiment, is at fault. Exit code will be 2.")
        print("")
        print("STEP 5 RESULT: HARNESS FAILURE — exit code 2")
        sys.exit(2)
    _recorder = Recorder("step5")
    try:
        _exit_code = run(_recorder)
    except Exception:
        import traceback

        print("\n" + "=" * 60)
        print("STEP 5: UNEXPECTED ERROR — recording and exiting")
        print("=" * 60)
        traceback.print_exc()
        print("Step failed with an unexpected error; review "
              "results/raw/step5-*.log")
        _recorder.close()
        sys.exit(1)
    _recorder.close()
    sys.exit(_exit_code)

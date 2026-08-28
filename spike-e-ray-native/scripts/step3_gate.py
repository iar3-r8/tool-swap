"""Step 3 GATE: two conflicting tools, one GPU, on-demand start.

This is the first hard gate. If it fails, stop and record — do not
continue to step 4. Under the spike protocol's Rule 2, a negative
verdict here is decisive: it answers the framework question.

Tests:
  1. tool_torch starts on demand, holds VRAM
  2. VRAM is released when the replica scales to zero
  3. tool_tf starts on demand, holds VRAM
  4. CUDA_VISIBLE_DEVICES reaches the container
  5. The swap is repeatable

Exit status (D29)
    0  Every required observation was made and nothing answers the gate
       negatively: both tools cold-started, VRAM was held and released,
       the GPU assignment reached the containers, and the swap repeated.
    1  Unexpected internal error (traceback printed).
    2  Harness/environment failure — a required observation could NOT be
       made: nvidia-smi or podman is absent, the config could not be
       deployed, a deployment never reached RUNNING, a probe was
       unreachable, or a VRAM snapshot could not be taken. The gate
       proves nothing and must be re-run on a healthy environment.
    3  Negative finding — the observations WERE made and answer the gate
       negatively: VRAM was not held after a request, VRAM was not
       released after the replica downscaled, the GPU assignment did not
       reach the container, or a tool answered with the wrong identity.
       This is the decisive "Ray loses" result: record it and stop.

The 2-vs-3 boundary is deliberate and load-bearing: a probe that could
not be reached, or an nvidia-smi that cannot run, means nothing was
learned (exit 2); a VRAM figure that *was measured* and shows the GPU
still occupied means something decisive was learned (exit 3). Getting
this wrong in either direction corrupts the spike's central result.

Once a negative finding is recorded, the remaining swap probes are
skipped: they would fail as *consequences* of the decisive finding (a
busy GPU cannot serve the second tool) and a consequence that looks
like an unreachable probe would flip the exit code from 3 to 2.

Both failure kinds are printed with an explicit label and a final
"STEP 3 RESULT:" summary line, and all raw output is recorded to
results/raw/step3-*.log and results/metrics/step3.jsonl regardless of
the exit status.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
sys.path.insert(0, os.path.join(_SCRIPTS_DIR, "lib"))

from nvidia import snapshot_vram, vram_sampler
from podman import podman_ps_all, podman_ps_count
from recorder import Recorder, block, record
from serve_api import apply_config, post_introspect, serve_status
from step1_verify import StepOutcome, _wait_for_running

# ── Configurable endpoints (per deployment route_prefix) ────────
# Step 3 uses two SEPARATE applications, so routes depend on app name.
SERVE_BASE = os.environ.get("SERVE_BASE_URL", "http://localhost:8000")
TOOL_TORCH_URL = f"{SERVE_BASE}/tool_torch"
TOOL_TF_URL = f"{SERVE_BASE}/tool_tf"

# Expected per-tool identity. Each fixture image bakes its own marker
# (fixtures/*.Dockerfile: SPIKE_IMAGE_MARKER) and its own framework, so
# a healthy replica's introspect response identifies exactly one.
EXPECTED: dict[str, dict[str, str]] = {
    "tool_torch": {"marker_prefix": "tool_torch", "framework": "torch"},
    "tool_tf": {"marker_prefix": "tool_tf", "framework": "tensorflow"},
}


def _downscale_settings() -> tuple[float, float]:
    """Read the idle-wait knobs from the environment (D29).

    The step must idle past the deployment's
    ``downscale_to_zero_delay_s`` (60s in apps/step3_config.yaml) plus
    a buffer, so the wait is configurable rather than the old
    hard-coded ``delay = 60`` — the same convention as the D25
    readiness knobs. Read at call time so a test can override it.

    Returns:
        ``(delay_s, buffer_s)`` from ``SPIKE_DOWNSCALE_DELAY_S``
        (default 60) and ``SPIKE_DOWNSCASE_BUFFER_S`` (default 5).
    """
    delay_s = float(os.environ.get("SPIKE_DOWNSCALE_DELAY_S", "60"))
    buffer_s = float(os.environ.get("SPIKE_DOWNSCASE_BUFFER_S", "5"))
    return delay_s, buffer_s


def _release_tolerance_mb() -> int:
    """VRAM still occupied after idle that is tolerated as driver noise.

    ``nvidia-smi`` reports small per-driver allocations that never go
    to zero; a tolerance far below the fixture's 4096 MiB allocation
    keeps a genuine leak negative while ignoring that noise.

    Returns:
        The tolerance in MiB (``SPIKE_VRAM_RELEASE_TOLERANCE_MB``,
        default 256).
    """
    return int(os.environ.get("SPIKE_VRAM_RELEASE_TOLERANCE_MB", "256"))


def _total_vram_mb(gpus: list[dict]) -> int | None:
    """Sum ``memory.used [MiB]`` over all GPUs in a snapshot.

    Args:
        gpus: The parsed ``nvidia-smi --format=json`` rows.

    Returns:
        The total used MiB, or None when the snapshot is empty (no GPU
        visible — the comparison cannot be made).
    """
    if not gpus:
        return None
    return sum(int(row.get("memory.used [MiB]", 0)) for row in gpus)


def _gpu_guard() -> str | None:
    """Check the GPU host preconditions (D29: labelled verdict, no silent exit).

    Returns:
        A problem description to report as a harness failure (exit 2:
        the VRAM/container observations could not be made), or None
        when the host preconditions hold.
    """
    if shutil.which("nvidia-smi") is None:
        return (
            "nvidia-smi not found on PATH — the VRAM observations "
            "cannot be made. Step 3 requires a GPU box. Run on the "
            "DGX host."
        )
    if shutil.which("podman") is None:
        return (
            "podman not found on PATH — the container observations "
            "cannot be made. Step 3 requires a container runtime. "
            "Run on the DGX host."
        )
    return None


def _snapshot_vram_block(
    label: str, recorder: Recorder, outcome: StepOutcome
) -> list[dict] | None:
    """Take one nvidia-smi snapshot, print and record it, classify it.

    Args:
        label: The block title, e.g. "Baseline nvidia-smi".
        recorder: Records the raw snapshot (or the error text).
        outcome: Collects a harness failure when nvidia-smi cannot run.

    Returns:
        The parsed snapshot, or None when it could not be made.
    """
    try:
        data = snapshot_vram()
    except Exception as e:
        recorder.write(block(label, f"<nvidia-smi unavailable: {e}>"))
        outcome.harness(
            f"nvidia-smi snapshot ({label}) could not be taken: {e} — "
            "the VRAM observation could not be made."
        )
        return None
    print(f"{label}: {json.dumps(data, indent=2)}")
    recorder.write(block(label, json.dumps(data, indent=2)))
    return data


def _check_identity(outcome: StepOutcome, tool: str, data: dict) -> None:
    """Compare a tool's introspect response against the fixture identity.

    A mismatch is a negative *finding*: the replica answered (the
    observation was made) but with the wrong image or framework.

    Args:
        outcome: Collects the finding on mismatch.
        tool: The probed tool ("tool_torch" or "tool_tf").
        data: The introspect response.
    """
    expected = EXPECTED[tool]
    marker = str(data.get("image_marker", ""))
    framework = str(data.get("framework", ""))
    problems = []
    if not marker.startswith(expected["marker_prefix"]):
        problems.append(
            f"image_marker={marker!r} (expected prefix "
            f"{expected['marker_prefix']!r})"
        )
    if framework != expected["framework"]:
        problems.append(
            f"framework={framework!r} (expected {expected['framework']!r})"
        )
    if problems:
        outcome.finding(
            f"{tool} answered with unexpected identity: " + "; ".join(problems)
        )


def _check_cuda_visible(
    outcome: StepOutcome, tool: str, data: dict, recorder: Recorder
) -> None:
    """Check CUDA_VISIBLE_DEVICES reached the container (gate test 4).

    The field is always present in the introspect response
    (toolkit/introspect.py); an empty value means the GPU assignment
    did not reach the container — a negative finding, because the
    observation was made and it answers test 4 negatively.

    Args:
        outcome: Collects the finding when the assignment is absent.
        tool: The probed tool.
        data: The introspect response.
        recorder: Records the observed value.
    """
    cuda_val = data.get("cuda_visible_devices", "<not set>")
    print(f"  CUDA_VISIBLE_DEVICES: {cuda_val}")
    recorder.write(block(f"CUDA_VISIBLE_DEVICES ({tool})", str(cuda_val)))
    if not isinstance(cuda_val, str) or not cuda_val:
        outcome.finding(
            f"{tool}: CUDA_VISIBLE_DEVICES is empty inside the "
            "container — the GPU assignment did not reach it."
        )


def _check_vram_held(
    outcome: StepOutcome,
    baseline: list[dict] | None,
    current: list[dict] | None,
    tool: str,
) -> None:
    """VRAM must grow while a tool replica is resident (gate tests 2/3).

    The fixture allocates ~4096 MiB in __init__ (apps/step3_gpu_swap.py);
    no growth means the replica never touched a GPU.

    Args:
        outcome: Collects the finding when VRAM did not grow.
        baseline: The pre-request snapshot (None = already a harness failure).
        current: The post-request snapshot (same).
        tool: The tool whose replica should be resident.
    """
    if baseline is None or current is None:
        return  # the snapshots failed; a harness failure was recorded
    before = _total_vram_mb(baseline)
    after = _total_vram_mb(current)
    if before is None or after is None:
        outcome.harness(
            f"nvidia-smi reported no GPU in the {tool} VRAM "
            "snapshots — the comparison could not be made."
        )
        return
    if after <= before:
        outcome.finding(
            f"VRAM was NOT held after the {tool} request: "
            f"{before} MiB before vs {after} MiB after — the replica "
            "started but holds no resident GPU memory, so the "
            "single-GPU swap cannot work."
        )


def _check_vram_released(
    outcome: StepOutcome,
    baseline: list[dict] | None,
    after_idle: list[dict] | None,
) -> None:
    """VRAM must return to baseline after the replica downscales (test 2).

    This is the decisive observation: the incumbent must free the GPU
    for the other tool. Anything beyond the driver-noise tolerance
    still occupied after idle is a negative finding.

    Args:
        outcome: Collects the finding when VRAM was not released.
        baseline: The pre-request snapshot (None = already a harness failure).
        after_idle: The post-idle snapshot (same).
    """
    if baseline is None or after_idle is None:
        return
    base = _total_vram_mb(baseline)
    idle = _total_vram_mb(after_idle)
    if base is None or idle is None:
        outcome.harness(
            "nvidia-smi reported no GPU in the release snapshots — "
            "the comparison could not be made."
        )
        return
    tol = _release_tolerance_mb()
    if idle > base + tol:
        outcome.finding(
            f"VRAM was NOT released after downscale to zero: "
            f"{idle} MiB after idle vs {base} MiB baseline "
            f"(tolerance {tol} MiB) — the incumbent still occupies "
            "the GPU, so the second tool cannot start on it. Decisive "
            "negative result (Rule 2)."
        )


def _probe(
    recorder: Recorder,
    outcome: StepOutcome,
    tool: str,
    url: str,
    phase: str = "probe",
) -> dict | None:
    """POST introspect to a tool, record it, and classify the outcome.

    An unreachable endpoint is a harness failure (the observation
    could not be made); an answered endpoint is checked for the correct
    identity (a mismatch is a finding).

    Args:
        recorder: Records the raw response or error.
        outcome: Collects the harness failure / finding.
        tool: "tool_torch" or "tool_tf".
        url: The tool's proxy URL.
        phase: The metrics phase label ("cold_start" or "probe").

    Returns:
        The introspect response, or None when unreachable.
    """
    t0 = time.monotonic()
    try:
        result = post_introspect(url, timeout=120)
    except Exception as e:
        print(f"Error: {e}")
        record("step3", tool=tool, phase=phase, error=str(e))
        recorder.write(block(f"{tool} introspect error", str(e)))
        # Unreachable probe = harness/environment failure, not a
        # finding: the observation could not be made at all.
        outcome.harness(
            f"{tool} probe could not be reached at {url} ({e}) — the "
            "observation could not be made."
        )
        return None
    elapsed = time.monotonic() - t0
    record(
        "step3",
        tool=tool,
        phase=phase,
        end_to_end_seconds=round(elapsed, 3),
    )
    label = "Cold start" if phase == "cold_start" else "Probe"
    print(f"{label} end-to-end: {elapsed:.3f}s")
    print(f"Tool introspect: {json.dumps(result, indent=2)}")
    record("step3", tool=tool, phase="introspect", result=result)
    recorder.write(block(f"{tool} introspect", json.dumps(result, indent=2)))
    _check_identity(outcome, tool, result)
    return result


def _print_summary(outcome: StepOutcome) -> None:
    """Print the final gate verdict, labelling each failure kind explicitly.

    Args:
        outcome: The collected harness failures and findings.
    """
    if outcome.harness_failures:
        print("")
        print("STEP 3 RESULT: HARNESS FAILURE — exit code 2")
        print("A required observation could not be made; the environment,")
        print("not the experiment, is at fault. The gate proves nothing")
        print("and must be re-run; the incomplete findings are:")
        for i, msg in enumerate(outcome.harness_failures, 1):
            print(f"  {i}. {msg}")
    if outcome.findings:
        print("")
        print("STEP 3 RESULT: NEGATIVE FINDING(S) — exit code 3")
        print("The observations were made but answer the gate negatively.")
        print("This is the decisive Rule 2 result: record it and STOP.")
        for i, msg in enumerate(outcome.findings, 1):
            print(f"  {i}. {msg}")
    if not outcome.harness_failures and not outcome.findings:
        print("")
        print("STEP 3 RESULT: gate CLEAN — exit code 0")
        print("Both tools swapped on one GPU; VRAM was held and released;")
        print("the GPU assignment reached the containers; the swap repeated.")


def run(recorder: Recorder) -> int:
    """Run step 3's gate observations and return the process exit code.

    Args:
        recorder: The step's Recorder (stdout/stderr tee to the log).

    Returns:
        0 (gate clean), 2 (harness failure) or 3 (negative finding).
    """
    outcome = StepOutcome()

    print("=" * 60)
    print("STEP 3 GATE: Two conflicting tools, one GPU, on-demand start")
    print("=" * 60)

    # ── 1. Start VRAM sampler ──────────────────────────────────
    print("\n=== Starting VRAM sampler ===")
    vram_csv = os.path.join(
        os.environ["SPIKE_METRICS_DIR"], "step3_vram.csv"
    )
    stop_event = threading.Event()
    sampler = threading.Thread(
        target=vram_sampler,
        args=(vram_csv, 1.0, None, stop_event),
        daemon=True,
    )
    sampler.start()
    print(f"VRAM CSV: {vram_csv}")

    try:
        # ── 2. Snapshot baseline (both at zero replicas) ────────
        print("\n=== Baseline snapshot (both apps should be at 0 replicas) ===")
        try:
            baseline_podman = podman_ps_all()
            print(f"Podman containers: {podman_ps_count()}")
            recorder.write(block("Baseline podman ps -a", baseline_podman))
        except Exception as e:
            recorder.write(
                block("Baseline podman ps -a", f"<podman unavailable: {e}>")
            )
            outcome.harness(
                f"podman ps could not be run: {e} — the container "
                "observation could not be made."
            )
        baseline_vram = _snapshot_vram_block(
            "Baseline nvidia-smi", recorder, outcome
        )

        # ── 3. Deploy step 3 config ─────────────────────────────
        print("\n=== Deploying step 3 config ===")
        deploy_ok = False
        try:
            result = apply_config("apps/step3_config.yaml")
            recorder.write(
                block("serve deploy output", result.stdout + result.stderr)
            )
            print(f"Exit code: {result.returncode}")
            if result.returncode == 0:
                deploy_ok = True
            else:
                outcome.harness(
                    f"`serve deploy` of apps/step3_config.yaml exited "
                    f"{result.returncode} — the step 3 config could not "
                    "be deployed, so the gate observations cannot be "
                    "made."
                )
        except Exception as e:
            recorder.write(block("serve deploy error", str(e)))
            print(f"Deploy error: {e}")
            outcome.harness(f"Could not invoke `serve deploy`: {e}")

        if not deploy_ok:
            print("\nSkipping the gate probes: the config could not be "
                  "deployed.")
        else:
            # ── 4. Wait for the applications to reach RUNNING ───
            # (D25 readiness convention, shared with steps 1/2; the
            # old hard-coded sleep(10) is gone.)
            _wait_for_running(recorder, outcome)

            # ── 5. Request tool_torch (cold start) ──────────────
            print("\n=== Requesting tool_torch (cold start) ===")
            torch_result = _probe(
                recorder, outcome, "tool_torch", TOOL_TORCH_URL,
                phase="cold_start",
            )

            # ── 6. Verify VRAM is held + CUDA reached the container ──
            print("\n=== Checking VRAM is held ===")
            vram_after_request = _snapshot_vram_block(
                "VRAM after request", recorder, outcome
            )
            if torch_result is not None:
                _check_vram_held(
                    outcome, baseline_vram, vram_after_request, "tool_torch"
                )
                print("\n=== CUDA_VISIBLE_DEVICES inside container ===")
                _check_cuda_visible(
                    outcome, "tool_torch", torch_result, recorder
                )

            # ── 7. Idle past downscale_to_zero_delay_s ──────────
            delay_s, buffer_s = _downscale_settings()
            print(f"\n=== Waiting {delay_s + buffer_s:.0f}s for the replica "
                  f"to scale to zero (delay {delay_s:.0f}s + "
                  f"buffer {buffer_s:.0f}s) ===")
            time.sleep(delay_s + buffer_s)

            try:
                final_podman = podman_ps_all()
                print(f"Podman after idle: {podman_ps_count()}")
                recorder.write(block("Podman after idle", final_podman))
            except Exception as e:
                recorder.write(
                    block("Podman after idle", f"<podman unavailable: {e}>")
                )
                outcome.harness(
                    f"podman ps could not be run after idle: {e} — the "
                    "container observation could not be made."
                )
            final_vram = _snapshot_vram_block(
                "VRAM after idle", recorder, outcome
            )
            try:
                final_status = serve_status()
                recorder.write(block(
                    "serve status after idle",
                    json.dumps(final_status, indent=2),
                ))
            except Exception as e:
                outcome.harness(
                    f"serve status unreachable after idle: {e} — the "
                    "post-idle status observation could not be made."
                )
                recorder.write(block(
                    "serve status after idle", f"<unreachable: {e}>"
                ))
            if torch_result is not None:
                _check_vram_released(outcome, baseline_vram, final_vram)

            # ── 8/9. Swap to tool_tf, then alternate back ───────
            # Only when the gate has not already failed: once a
            # finding is recorded (e.g. VRAM not released), the
            # remaining probes would fail as consequences of that
            # finding, and a consequence that looks like an
            # unreachable probe must not flip the exit code from 3
            # to 2.
            if outcome.findings:
                print("\n=== Remaining swap probes SKIPPED: a negative "
                      "finding is already recorded ===")
                print("  The gate has failed; further probes would only")
                print("  add consequences of the decisive finding.")
            else:
                print("\n=== Requesting tool_tf (cold start) ===")
                tf_result = _probe(
                    recorder, outcome, "tool_tf", TOOL_TF_URL,
                    phase="cold_start",
                )
                if tf_result is not None:
                    vram_after_tf = _snapshot_vram_block(
                        "VRAM after tool_tf request", recorder, outcome
                    )
                    _check_vram_held(
                        outcome, baseline_vram, vram_after_tf, "tool_tf"
                    )
                    _check_cuda_visible(
                        outcome, "tool_tf", tf_result, recorder
                    )

                # ── 9. Alternate once more (repeatability) ──────
                if not outcome.findings and tf_result is not None:
                    print("\n=== Alternate back to tool_torch ===")
                    if _probe(recorder, outcome, "tool_torch",
                              TOOL_TORCH_URL) is not None:
                        print("  tool_torch served successfully")
    finally:
        stop_event.set()
        sampler.join(timeout=2)

    print("")
    print("--- STEP 3 OBSERVATIONS COMPLETE ---")
    if outcome.findings:
        print("The gate FAILED: see the [NEGATIVE FINDING] labels above.")
        print("STOP here and record the failure. Do not continue to step 4.")
    _print_summary(outcome)
    return outcome.exit_code


if __name__ == "__main__":
    _problem = _gpu_guard()
    if _problem:
        print(f"\n[HARNESS FAILURE] {_problem}")
        print("  The observation could not be made — the environment, not")
        print("  the experiment, is at fault. Exit code will be 2.")
        print("")
        print("STEP 3 RESULT: HARNESS FAILURE — exit code 2")
        sys.exit(2)
    _recorder = Recorder("step3")
    try:
        _exit_code = run(_recorder)
    except Exception:
        import traceback

        print("\n" + "=" * 60)
        print("STEP 3: UNEXPECTED ERROR — recording and exiting")
        print("=" * 60)
        traceback.print_exc()
        print("Step failed with an unexpected error; review "
              "results/raw/step3-*.log")
        _recorder.close()
        sys.exit(1)
    _recorder.close()
    sys.exit(_exit_code)

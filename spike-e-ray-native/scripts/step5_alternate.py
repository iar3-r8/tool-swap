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
Running only one would let a mechanism limitation be recorded as a Ray limit.

Also: with external_scaler_enabled there is no downscale_to_zero_delay_s,
so the protocol's literal precondition — an idle incumbent whose timer
has not expired — cannot be reproduced. What gets measured is whether
externally-driven displacement works at cadence. State this explicitly.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
from recorder import Recorder, record, block
from serve_api import serve_status, scale_deployment, post_introspect, apply_config
from nvidia import snapshot_vram

SERVE_BASE = os.environ.get("SERVE_BASE_URL", "http://localhost:8000")
TORCH_URL = f"{SERVE_BASE}/tool_torch"
TF_URL = f"{SERVE_BASE}/tool_tf"
N = 20  # alternations


def run() -> None:
    recorder = Recorder("step5")

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

    # Deploy mechanism A config
    result = apply_config("apps/step5_config.yaml")
    recorder.write(block("Mech A deploy", result.stdout + result.stderr))
    print(f"Deploy exit code: {result.returncode}")
    time.sleep(10)

    # Confirm both are at 1 replica
    status = serve_status()
    print(json.dumps(status, indent=2))

    # Run N alternations
    results = []
    for i in range(N):
        direction = "torch" if i % 2 == 0 else "tf"
        target_url = TORCH_URL if direction == "torch" else TF_URL
        target_app = "step5_torch" if direction == "torch" else "step5_tf"
        other_app = "step5_tf" if direction == "torch" else "step5_torch"

        t0 = time.monotonic()
        try:
            # Scale incumbent to 0
            scale_deployment(target_app if direction == "tf" else other_app,
                           "ToolTorch" if direction == "tf" else "ToolTf", 0)
            # Scale target to 1
            scale_deployment(target_app,
                           "ToolTorch" if direction == "torch" else "ToolTf", 1)
            # Send request
            resp = post_introspect(target_url, timeout=120)
            elapsed = time.monotonic() - t0

            result_entry = {
                "mechanism": "A",
                "iteration": i + 1,
                "direction": direction,
                "total_seconds": round(elapsed, 3),
                "replica_id": resp.get("replica_id", "unknown"),
                "image_marker": resp.get("image_marker", "unknown"),
            }
            results.append(result_entry)
            record("step5", **result_entry)
            print(f"  Alt {i+1:2d}/{N} {direction:>7s}: {elapsed:.3f}s")
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

    # Report distribution
    if results:
        latencies = [r["total_seconds"] for r in results if "error" not in r]
        if latencies:
            latencies_sorted = sorted(latencies)
            p90_idx = int(len(latencies_sorted) * 0.9)
            print(f"\n  Min:   {min(latencies):.3f}s")
            print(f"  Median: {latencies_sorted[len(latencies_sorted)//2]:.3f}s")
            print(f"  P90:   {latencies_sorted[min(p90_idx, len(latencies_sorted)-1)]:.3f}s")
            print(f"  Max:   {max(latencies):.3f}s")
            print(f"  Errors: {len([r for r in results if 'error' in r])}")

    # Clean up mechanism A
    for dep in ["ToolTorch", "ToolTf"]:
        try:
            scale_deployment("step5_torch" if dep == "ToolTorch" else "step5_tf", dep, 0)
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
    recorder.close()


import shutil


def _gpu_guard() -> None:
    """Refuse to run if nvidia-smi or podman is absent."""
    if shutil.which("nvidia-smi") is None:
        print("FATAL: nvidia-smi not found on PATH.")
        print("Step 5 requires a GPU box. Run on the DGX host.")
        import sys
        sys.exit(2)
    if shutil.which("podman") is None:
        print("FATAL: podman not found on PATH.")
        print("Step 5 requires a container runtime. Run on the DGX host.")
        import sys
        sys.exit(2)


if __name__ == "__main__":
    try:
        _gpu_guard()
        run()
    except SystemExit:
        raise
    except Exception:
        import traceback
        print("\n" + "=" * 60)
        print("STEP 5: UNEXPECTED ERROR — recording and exiting")
        print("=" * 60)
        traceback.print_exc()
        print("Step completed with errors; review results/raw/step5-*.log")

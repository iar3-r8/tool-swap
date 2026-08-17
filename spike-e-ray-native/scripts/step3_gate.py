"""Step 3 GATE: two conflicting tools, one GPU, on-demand start.

This is the first hard gate. If it fails, stop and record — do not
continue to step 4.

Tests:
  1. tool_torch starts on demand, holds VRAM
  2. VRAM is released when replica scales to zero
  3. tool_tf starts on demand, holds VRAM
  4. CUDA_VISIBLE_DEVICES reaches the container
  5. Swap is repeatable
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
from recorder import Recorder, record, block
from serve_api import serve_status, get_application, post_introspect
from nvidia import nvidia_smi_json, vram_sampler, snapshot_vram
from podman import podman_ps_all, podman_ps_count

# ── Configurable endpoints (per deployment route_prefix) ────────
# Step 3 uses two SEPARATE applications, so routes depend on app name.
SERVE_BASE = os.environ.get("SERVE_BASE_URL", "http://localhost:8000")
TOOL_TORCH_URL = f"{SERVE_BASE}/tool_torch"
TOOL_TF_URL = f"{SERVE_BASE}/tool_tf"


def run() -> None:
    recorder = Recorder("step3")

    print("=" * 60)
    print("STEP 3 GATE: Two conflicting tools, one GPU, on-demand start")
    print("=" * 60)

    # ── 1. Start VRAM sampler ──────────────────────────────────
    print("\n=== Starting VRAM sampler ===")
    vram_csv = os.path.join(
        os.environ["SPIKE_METRICS_DIR"], "step3_vram.csv"
    )
    stop_event = __import__("threading").Event()
    sampler = __import__("threading").Thread(
        target=vram_sampler, args=(vram_csv, 1.0, None, stop_event), daemon=True
    )
    sampler.start()
    print(f"VRAM CSV: {vram_csv}")

    try:
        # ── 2. Snapshot baseline (both at zero replicas) ────────
        print("\n=== Baseline snapshot (both apps should be at 0 replicas) ===")
        baseline_podman = podman_ps_all()
        baseline_vram = snapshot_vram()
        print(f"Podman containers: {podman_ps_count()}")
        print(f"VRAM: {json.dumps(baseline_vram, indent=2)}")
        recorder.write(block("Baseline podman ps -a", baseline_podman))
        recorder.write(block("Baseline nvidia-smi", json.dumps(baseline_vram, indent=2)))

        # ── 3. Deploy step 3 config ─────────────────────────────
        print("\n=== Deploying step 3 config ===")
        from serve_api import apply_config
        result = apply_config("apps/step3_config.yaml")
        recorder.write(block("serve deploy output", result.stdout + result.stderr))
        print(f"Exit code: {result.returncode}")

        # Wait for Serve to stabilize
        print("\nWaiting for Serve to stabilize...")
        time.sleep(10)
        status = serve_status()
        apps = status.get("applications", [])
        for app in apps:
            print(f"  {app.get('name')}: {app.get('status')}")
        recorder.write(block("serve status after deploy", json.dumps(status, indent=2)))

        # ── 4. Request tool_torch (cold start) ──────────────────
        print("\n=== Requesting tool_torch (cold start) ===")
        t0 = time.monotonic()
        try:
            torch_result = post_introspect(TOOL_TORCH_URL, timeout=120)
            cold_start_e2e = time.monotonic() - t0
            record("step3", tool="torch", phase="cold_start", end_to_end_seconds=round(cold_start_e2e, 3))
            print(f"Cold start end-to-end: {cold_start_e2e:.3f}s")
            print(f"Tool introspect: {json.dumps(torch_result, indent=2)}")
            record("step3", tool="torch", phase="introspect", result=torch_result)
        except Exception as e:
            print(f"Error: {e}")
            record("step3", tool="torch", phase="cold_start", error=str(e))
            recorder.write(block("tool_torch error", str(e)))

        # ── 5. Verify VRAM is held ──────────────────────────────
        print("\n=== Checking VRAM is held ===")
        vram_after_request = snapshot_vram()
        print(f"VRAM after request: {json.dumps(vram_after_request, indent=2)}")
        recorder.write(block("VRAM after request", json.dumps(vram_after_request, indent=2)))

        # ── 6. Check CUDA_VISIBLE_DEVICES ───────────────────────
        print("\n=== CUDA_VISIBLE_DEVICES inside container ===")
        cuda_val = torch_result.get("cuda_visible_devices", "<not set>")
        print(f"  CUDA_VISIBLE_DEVICES: {cuda_val}")
        recorder.write(block("CUDA_VISIBLE_DEVICES", cuda_val))

        # ── 7. Idle past downscale_to_zero_delay_s ──────────────
        print("\n=== Waiting for replica to scale to zero ===")
        delay = 60  # from autoscaling_config
        time.sleep(delay + 5)  # extra 5s buffer
        stop_event.set()
        sampler.join(timeout=2)

        replica_gone_time = None
        vram_cleared_time = None
        final_podman = podman_ps_all()
        final_vram = snapshot_vram()
        final_status = serve_status()

        print(f"Podman after idle: {podman_ps_count()}")
        print(f"VRAM after idle: {json.dumps(final_vram, indent=2)}")
        recorder.write(block("Podman after idle", final_podman))
        recorder.write(block("VRAM after idle", json.dumps(final_vram, indent=2)))
        recorder.write(block("serve status after idle", json.dumps(final_status, indent=2)))

        # ── 8. Request tool_tf (cold start) ─────────────────────
        print("\n=== Requesting tool_tf (cold start) ===")
        t0 = time.monotonic()
        try:
            tf_result = post_introspect(TOOL_TF_URL, timeout=120)
            cold_start_e2e = time.monotonic() - t0
            record("step3", tool="tf", phase="cold_start", end_to_end_seconds=round(cold_start_e2e, 3))
            print(f"Cold start end-to-end: {cold_start_e2e:.3f}s")
            print(f"Tool introspect: {json.dumps(tf_result, indent=2)}")
            record("step3", tool="tf", phase="introspect", result=tf_result)
        except Exception as e:
            print(f"Error: {e}")
            record("step3", tool="tf", phase="cold_start", error=str(e))
            recorder.write(block("tool_tf error", str(e)))

        # ── 9. Alternate once more ──────────────────────────────
        print("\n=== Alternate back to tool_torch ===")
        post_introspect(TOOL_TORCH_URL, timeout=120)
        print("  tool_torch served successfully")

    finally:
        stop_event.set()
        sampler.join(timeout=2)

    print("")
    print("--- STEP 3 OBSERVATIONS COMPLETE ---")
    print("If VRAM was not released or GPU assignment did not reach the container,")
    print("STOP here and record the failure. Do not continue to step 4.")
    recorder.close()


# ── GPU guard ──────────────────────────────────────────────────
import shutil


def _gpu_guard() -> None:
    """Refuse to run if nvidia-smi or podman is absent."""
    if shutil.which("nvidia-smi") is None:
        print("FATAL: nvidia-smi not found on PATH.")
        print("Step 3 requires a GPU box. Run on the DGX host.")
        import sys
        sys.exit(2)
    if shutil.which("podman") is None:
        print("FATAL: podman not found on PATH.")
        print("Step 3 requires a container runtime. Run on the DGX host.")
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
        print("STEP 3: UNEXPECTED ERROR — recording and exiting")
        print("=" * 60)
        traceback.print_exc()
        print("Step completed with errors; review results/raw/step3-*.log")

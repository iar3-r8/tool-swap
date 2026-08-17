"""Step 6 GATE: cluster restart and recovery.

Two phases:
  A. Kill the head node (kill -9), restart Ray and Serve, observe recovery.
  B. Kill a replica actor, observe unattended recovery.

Per rule 0.5: if Ray's own docs say "Serve cannot recover without KubeRay",
expect manual intervention. Record every command and its output verbatim.
If an undocumented step is needed, record it as a required manual step —
do not quietly do it.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
from recorder import Recorder, record, block
from serve_api import serve_status, get_application
from nvidia import snapshot_vram
from podman import podman_ps_all, podman_ps_all_json

# ── Identifying the head node process ────────────────────────────
def find_ray_head() -> int:
    """Find the Ray head node GCS process PID."""
    result = subprocess.run(
        ["pgrep", "-f", "gcs_server"],
        capture_output=True, text=True,
    )
    if result.stdout.strip():
        return int(result.stdout.strip().split("\n")[0])
    # Fallback: find raylet
    result = subprocess.run(
        ["pgrep", "-f", "raylet"],
        capture_output=True, text=True,
    )
    if result.stdout.strip():
        return int(result.stdout.strip().split("\n")[0])
    raise RuntimeError("Could not find Ray head node process")


# ── Phase A: Head node kill ──────────────────────────────────────
def phase_a(recorder: Recorder) -> None:
    """Kill head node, attempt documented recovery."""
    print("")
    print("=" * 60)
    print("STEP 6, PHASE A: Head node kill and recovery")
    print("=" * 60)

    # 1. Snapshot before
    print("\n=== Before kill ===")
    pre_status = serve_status()
    pre_vram = snapshot_vram()
    pre_podman = podman_ps_all()
    print(f"Serve apps: {json.dumps(pre_status, indent=2)}")
    print(f"VRAM: {json.dumps(pre_vram, indent=2)}")
    print(f"Containers: {podman_ps_count()}")
    recorder.write(block("Before kill — serve status", json.dumps(pre_status, indent=2)))
    recorder.write(block("Before kill — podman ps -a", pre_podman))

    # 2. Kill head node
    print("\n=== Killing head node ===")
    try:
        pid = find_ray_head()
        print(f"Head node PID: {pid}")
        recorder.write(block("Head node PID", str(pid)))
        subprocess.run(["kill", "-9", str(pid)], check=True)
        print(f"kill -9 {pid} sent")
    except Exception as e:
        print(f"Error finding/killing head: {e}")
        recorder.write(block("Kill head error", str(e)))
        return

    # 3. Immediate snapshot
    print("\n=== Immediate snapshot after kill ===")
    post_vram = snapshot_vram()
    post_podman = podman_ps_all()
    print(f"VRAM after kill: {json.dumps(post_vram, indent=2)}")
    print(f"Containers after kill: {podman_ps_count()}")
    recorder.write(block("After kill — VRAM", json.dumps(post_vram, indent=2)))
    recorder.write(block("After kill — podman ps -a", post_podman))

    # 4. Attempt recovery with documented commands
    print("\n=== Recovery: restarting Ray ===")
    manual_steps = []

    result = subprocess.run(
        ["ray", "start", "--head"],
        capture_output=True, text=True, timeout=30,
    )
    recorder.write(block("ray start --head", result.stdout + result.stderr))
    print(f"ray start exit: {result.returncode}")
    if result.returncode != 0:
        manual_steps.append("ray start --head failed — may need manual cleanup")

    time.sleep(5)

    result = subprocess.run(
        ["serve", "deploy", "apps/step3_config.yaml"],
        capture_output=True, text=True, timeout=120,
    )
    recorder.write(block("serve deploy (recovery)", result.stdout + result.stderr))
    print(f"serve deploy exit: {result.returncode}")
    if result.returncode != 0:
        manual_steps.append("serve deploy failed — manual re-apply needed")

    time.sleep(10)

    # 5. Observe recovery
    print("\n=== Post-recovery state ===")
    post_status = serve_status()
    post_vram2 = snapshot_vram()
    post_podman2 = podman_ps_all()

    recorder.write(block("Post recovery — serve status", json.dumps(post_status, indent=2)))
    recorder.write(block("Post recovery — VRAM", json.dumps(post_vram2, indent=2)))
    recorder.write(block("Post recovery — podman ps -a", post_podman2))

    print(f"Serve apps: {json.dumps(post_status, indent=2)}")
    print(f"VRAM: {json.dumps(post_vram2, indent=2)}")
    print(f"Containers: {podman_ps_count()}")

    if manual_steps:
        print(f"\n  Required manual steps: {manual_steps}")
    else:
        print("\n  No manual steps required")

    # Record verdict
    apps_healthy = all(a.get("status") == "HEALTHY" for a in post_status.get("applications", []))
    record("step6", phase="A", apps_healthy=apps_healthy, manual_steps=manual_steps)


# ── Phase B: Replica actor kill ──────────────────────────────────
def phase_b(recorder: Recorder) -> None:
    """Kill a replica actor, observe unattended recovery."""
    print("")
    print("=" * 60)
    print("STEP 6, PHASE B: Replica actor kill")
    print("=" * 60)

    # Find the serving application and its replica PID
    print("\n=== Finding replica ===")
    try:
        apps = get_application("tool_torch")
        print(f"tool_torch app: {json.dumps(apps, indent=2)}")
        recorder.write(block("tool_torch app state", json.dumps(apps, indent=2)))

        # Look for replicas
        for replica in apps.get("replicas", []):
            pid = replica.get("pid")
            if pid:
                print(f"Found replica PID: {pid}")
                recorder.write(block("Replica PID", str(pid)))

                # Kill the replica
                print(f"\n=== Killing replica PID {pid} ===")
                subprocess.run(["kill", "-9", str(pid)], check=True)
                print(f"kill -9 {pid} sent")

                # Wait for recovery
                print("\n=== Watching for unattended recovery ===")
                for _ in range(30):
                    time.sleep(2)
                    apps_after = get_application("tool_torch")
                    status = apps_after.get("status", "unknown")
                    replicas = apps_after.get("replicas", [])
                    print(f"  Status: {status}, Replicas: {len(replicas)}")
                    for r in replicas:
                        print(f"    PID: {r.get('pid')}, state: {r.get('state')}")

                    if status == "HEALTHY" and len(replicas) >= 1:
                        print("  Recovery confirmed")
                        record("step6", phase="B", recovered=True, wait_seconds=_ * 2)
                        break
                else:
                    print("  Did not recover in 60s")
                    record("step6", phase="B", recovered=False)

                break
        else:
            print("No replica found")
            recorder.write(block("Phase B", "No replica found"))

    except Exception as e:
        print(f"Error: {e}")
        recorder.write(block("Phase B error", str(e)))


# ── Main ─────────────────────────────────────────────────────────
def run() -> None:
    recorder = Recorder("step6")

    try:
        phase_a(recorder)
        phase_b(recorder)
    finally:
        print("")
        print("--- STEP 6 OBSERVATIONS COMPLETE ---")
        recorder.close()


import shutil


def _gpu_guard() -> None:
    """Refuse to run if nvidia-smi or podman is absent."""
    if shutil.which("nvidia-smi") is None:
        print("FATAL: nvidia-smi not found on PATH.")
        print("Step 6 requires a GPU box. Run on the DGX host.")
        import sys
        sys.exit(2)
    if shutil.which("podman") is None:
        print("FATAL: podman not found on PATH.")
        print("Step 6 requires a container runtime. Run on the DGX host.")
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
        print("STEP 6: UNEXPECTED ERROR — recording and exiting")
        print("=" * 60)
        traceback.print_exc()
        print("Step completed with errors; review results/raw/step6-*.log")

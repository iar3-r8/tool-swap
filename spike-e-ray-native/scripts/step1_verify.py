"""Step 1 verification: per-deployment image_uri.

Tests whether image_uri can be set per-deployment or only per-application.
Runs the decorator form (step1_two_deployments.py) AND the YAML config form.

Per the protocol: neither config form being rejected is the pass condition.
If only one form works, that means one-tool-per-application mapping.
A fail in step 1 does NOT decide the framework (Rule 5).
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
from recorder import Recorder, record, block
from serve_api import serve_status, post_introspect

TOOL_URL_TORCH = os.environ.get(
    "SPIKE_SERVE_URL_TORCH", "http://localhost:8000/torch"
)
TOOL_URL_TF = os.environ.get(
    "SPIKE_SERVE_URL_TF", "http://localhost:8000/tf"
)


def run() -> None:
    recorder = Recorder("step1")

    print("=" * 60)
    print("STEP 1: Per-deployment image_uri")
    print("=" * 60)

    # ── Part A: Decorator form (step1_two_deployments.py) ──────
    print("")
    print("=== Part A: Decorator/ray_actor_options form ===")

    try:
        import subprocess
        result = subprocess.run(
            ["serve", "deploy", "apps/step1_two_deployments.py", "step1_app"],
            capture_output=True, text=True, timeout=120,
        )
        recorder.write(block("serve deploy output", result.stdout + result.stderr))
        print(f"Deploy exit code: {result.returncode}")
        if result.returncode != 0:
            print("Decorator form REJECTED — continuing to YAML form")
            deploy_ok = False
        else:
            deploy_ok = True
    except Exception as e:
        recorder.write(block("serve deploy error", str(e)))
        print(f"Deploy error: {e}")
        deploy_ok = False

    if deploy_ok:
        # Wait for Serve to stabilize
        print("\nWaiting for Serve to stabilize...")
        for _ in range(30):
            status = serve_status()
            apps = status.get("applications", {})
            # In Ray 2.57+, applications is a dict {name: details} or {name: status_str}.
            if not apps:
                time.sleep(2)
                continue
            all_healthy = True
            for a in apps.values():
                if isinstance(a, dict):
                    if a.get("status") != "HEALTHY":
                        all_healthy = False
                else:
                    if str(a) != "HEALTHY":
                        all_healthy = False
            if all_healthy:
                print(f"Serve is HEALTHY ({len(apps)} apps: {', '.join(apps.keys())})")
                break
            time.sleep(2)
        else:
            print("Serve did not stabilize in 60s — status:")
            recorder.write(block("serve status", json.dumps(serve_status(), indent=2)))

        # Call introspect on each probe
        print("\n--- TorchProbe introspect ---")
        try:
            torch_result = post_introspect(TOOL_URL_TORCH)
            recorder.write(block("TorchProbe introspect", json.dumps(torch_result, indent=2)))
            print(json.dumps(torch_result, indent=2))
            record("step1", deployment="TorchProbe", result=torch_result)
        except Exception as e:
            print(f"Error calling TorchProbe: {e}")
            recorder.write(block("TorchProbe introspect error", str(e)))

        print("\n--- TfProbe introspect ---")
        try:
            tf_result = post_introspect(TOOL_URL_TF)
            recorder.write(block("TfProbe introspect", json.dumps(tf_result, indent=2)))
            print(json.dumps(tf_result, indent=2))
            record("step1", deployment="TfProbe", result=tf_result)
        except Exception as e:
            print(f"Error calling TfProbe: {e}")
            recorder.write(block("TfProbe introspect error", str(e)))

    # ── Part B: YAML config form ───────────────────────────────
    print("")
    print("=== Part B: YAML config form ===")
    try:
        result = subprocess.run(
            ["serve", "deploy", "apps/step1_config.yaml"],
            capture_output=True, text=True, timeout=120,
        )
        recorder.write(block("serve deploy (YAML) output", result.stdout + result.stderr))
        print(f"YAML deploy exit code: {result.returncode}")
        if result.returncode == 0:
            print("YAML form ACCEPTED")
        else:
            print("YAML form REJECTED")
    except Exception as e:
        recorder.write(block("serve deploy (YAML) error", str(e)))
        print(f"YAML deploy error: {e}")

    print("")
    print("--- STEP 1 OBSERVATIONS COMPLETE ---")
    recorder.close()


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback
        print("\n" + "=" * 60)
        print("STEP 1: UNEXPECTED ERROR — recording and continuing")
        print("=" * 60)
        traceback.print_exc()
        print("Step completed with errors; review results/raw/step1-*.log")

"""Step 2 verification: app builder with baked-in weights.

Tests:
  1. Does the builder execute in the controller's environment?
     (Check builder-environment banner in controller logs)
  2. Do the two apps load their OWN image's checkpoint?
     (Assert weights_sha256 differs between apps)
  3. What is the local disk read time for the baked weights?

Per §0a: the weight-fetch-measurement half of this step is removed.
The load_seconds reported here is a local disk read, not a thrash-pricing
figure. State this explicitly.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
from recorder import Recorder, record, block
from serve_api import serve_status, get_application, post_introspect, apply_config

TORCH_URL = os.environ.get("SPIKE_SERVE_URL_TORCH", "http://localhost:8000")
TF_URL = os.environ.get("SPIKE_SERVE_URL_TF", "http://localhost:8001")


def run() -> None:
    recorder = Recorder("step2")

    print("=" * 60)
    print("STEP 2: App builder, baked-in weights")
    print("=" * 60)

    # ── Deploy generic builder config ──────────────────────────
    print("")
    print("=== Deploying generic builder config ===")
    result = apply_config("apps/step2_config.yaml")
    recorder.write(block("serve deploy (generic) output", result.stdout + result.stderr))
    print(f"Exit code: {result.returncode}")

    # Wait for Serve to stabilize
    print("\nWaiting for Serve to stabilize...")
    for i in range(30):
        status = serve_status()
        apps = status.get("applications", {})
        if not apps:
            print("  ... waiting for apps to appear ...")
            time.sleep(2)
            continue
        # In Ray 2.57+, applications is a dict {name: details} or {name: status_str}.
        healthy = True
        for name, a in apps.items():
            if isinstance(a, dict):
                st = a.get("status", "UNKNOWN")
                if st != "HEALTHY":
                    healthy = False
            else:
                st = str(a)
                if st != "HEALTHY":
                    healthy = False
        if healthy and len(apps) >= 2:
            print(f"Serve is HEALTHY ({len(apps)} apps: {', '.join(apps.keys())})")
            break
        status_str = ", ".join(f"{k}={v.get('status',v) if isinstance(v,dict) else v}" for k,v in apps.items())
        print(f"  [{i+1}/30] Statuses: {status_str} ... waiting")
        time.sleep(2)
    else:
        print("Serve did not stabilize — status:")
        recorder.write(block("serve status", json.dumps(serve_status(), indent=2)))

    # ── Check builder banner ───────────────────────────────────
    # The builder banner is printed at module import time inside
    # the controller process. We check it by calling startup_report
    # and looking for the builder's sys.executable vs the image's.
    print("\n=== Checking builder environment ===")

    torch_startup = None
    tf_startup = None

    try:
        torch_startup = post_introspect(TORCH_URL)
        record("step2", app="torch", type="startup", data=torch_startup)
        print(f"tool_torch startup_report: {json.dumps(torch_startup, indent=2)}")
    except Exception as e:
        print(f"Error calling tool_torch: {e}")
        recorder.write(block("tool_torch startup error", str(e)))

    try:
        tf_startup = post_introspect(TF_URL)
        record("step2", app="tf", type="startup", data=tf_startup)
        print(f"tool_tf startup_report: {json.dumps(tf_startup, indent=2)}")
    except Exception as e:
        print(f"Error calling tool_tf: {e}")
        recorder.write(block("tool_tf startup error", str(e)))

    # ── Check weights_sha256 differs between apps ──────────────
    print("\n=== Verifying per-app checkpoint isolation ===")
    if torch_startup and tf_startup:
        torch_hash = torch_startup.get("weights_sha256", "")
        tf_hash = tf_startup.get("weights_sha256", "")
        torch_marker = torch_startup.get("image_marker", "")
        tf_marker = tf_startup.get("image_marker", "")

        print(f"  tool_torch marker: {torch_marker}")
        print(f"  tool_torch weights_sha256: {torch_hash[:16]}...")
        print(f"  tool_tf marker: {tf_marker}")
        print(f"  tool_tf weights_sha256: {tf_hash[:16]}...")

        if torch_hash and tf_hash and torch_hash != tf_hash:
            print("  OK: weights_sha256 differs between images — per-app isolation confirmed")
            record("step2", check="weights_sha256_differs", pass_=True)
        elif torch_hash and tf_hash:
            print("  WARNING: weights_sha256 is the same for both images — assets may not differ")
            record("step2", check="weights_sha256_differs", pass_=False)
        else:
            print("  WARNING: Could not compare sha256 values")

    # ── Deploy strict variant ──────────────────────────────────
    print("\n=== Deploying strict builder (imports torch) ===")
    result = apply_config("apps/step2_config_strict.yaml")
    recorder.write(block("serve deploy (strict) output", result.stdout + result.stderr))
    print(f"Exit code: {result.returncode}")
    if result.returncode == 0:
        print("Strict builder ACCEPTED — builder may run in tool_torch image")
    else:
        print("Strict builder REJECTED — builder likely runs in controller env")

    # ── Explicit §0a note ──────────────────────────────────────
    print("")
    print("=== §0a note ===")
    print("  Weight-fetch latency measurement was removed per scope amendment.")
    print("  The load_seconds values above are local disk reads, NOT thrash-pricing figures.")
    print("  This does NOT bias the framework decision (the fetch cost applies to both)")
    print("  architectures equally, but it is an open input to sizing work.")

    print("")
    print("--- STEP 2 OBSERVATIONS COMPLETE ---")
    recorder.close()


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback
        print("\n" + "=" * 60)
        print("STEP 2: UNEXPECTED ERROR — recording and continuing")
        print("=" * 60)
        traceback.print_exc()
        print("Step completed with errors; review results/raw/step2-*.log")

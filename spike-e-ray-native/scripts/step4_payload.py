"""Step 4 — Local payload read (D18 NOT tested per §0a).

Reads a baked-in file from the running tool_torch.
No S3, no remote payload, no credential plumbing.
D18 remains an untested assumption.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
from recorder import Recorder, record, block
from serve_api import post_predict, post_introspect

TOOL_URL = os.environ.get("SPIKE_SERVE_URL_TORCH", "http://localhost:8000")
PAYLOAD_PATH = os.environ.get("SPIKE_PAYLOAD_PATH", "/opt/spike/data/payload.bin")


def run() -> None:
    recorder = Recorder("step4")

    print("=" * 60)
    print("STEP 4: Local payload read (D18 NOT tested)")
    print("=" * 60)

    payload_path = PAYLOAD_PATH
    print(f"  Payload path: {payload_path}")

    # ── Warm up ────────────────────────────────────────────────
    print("\n=== Warming up tool_torch ===")
    post_introspect(TOOL_URL)
    print("  Warm")

    # ── Three reads ────────────────────────────────────────────
    print("\n=== Reading payload (3x) ===")
    timings = []
    for i in range(3):
        t0 = time.monotonic()
        try:
            result = post_predict(TOOL_URL, path=payload_path, timeout=120)
            elapsed = time.monotonic() - t0
            timings.append(elapsed)
            record("step4", iteration=i + 1, total_seconds=round(elapsed, 3), replica_data=result)
            print(f"  Read {i+1}: {elapsed:.3f}s, size={result.get('size_bytes')}, "
                  f"sha256={result.get('sha256', '')[:16]}...")
        except Exception as e:
            print(f"  Read {i+1} error: {e}")
            record("step4", iteration=i + 1, error=str(e))

    # ── Report ─────────────────────────────────────────────────
    if timings:
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
    recorder.close()


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import traceback
        print("\n" + "=" * 60)
        print("STEP 4: UNEXPECTED ERROR — recording and continuing")
        print("=" * 60)
        traceback.print_exc()
        print("Step completed with errors; review results/raw/step4-*.log")

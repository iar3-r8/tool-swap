"""nvidia-smi parsing and VRAM sampling."""

from __future__ import annotations

import csv
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Optional


def nvidia_smi(query: str = "memory.used", fmt: str = "csv") -> str:
    """Run nvidia-smi with the given query and return output."""
    result = subprocess.run(
        ["nvidia-smi", f"--query-gpu={query}", f"--format={fmt}"],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout


def nvidia_smi_json() -> list[dict]:
    """Run nvidia-smi --query-gpu=... --format=json and parse."""
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=index,memory.used,memory.total,name,driver_version",
            "--format=json",
        ],
        capture_output=True, text=True, timeout=10,
    )
    import json
    return json.loads(result.stdout)["gpu"]


def vram_sampler(
    output_path: str,
    interval: float = 1.0,
    duration: Optional[float] = None,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """Background VRAM sampler. Writes timestamped CSV.

    Parameters
    ----------
    output_path:
        Path to the CSV file to write.
    interval:
        Seconds between samples.
    duration:
        If set, stop after *duration* seconds.
    stop_event:
        If set, stop when the event is set.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["timestamp", "memory_used_mb"])
        start = time.monotonic()
        while True:
            if duration and (time.monotonic() - start) >= duration:
                break
            if stop_event and stop_event.is_set():
                break
            try:
                rows = nvidia_smi_json()
                for row in rows:
                    writer.writerow([
                        datetime.now(timezone.utc).isoformat(),
                        row["memory.used [MiB]"],
                    ])
                fh.flush()
            except Exception:
                pass
            time.sleep(interval)


def snapshot_vram() -> list[dict]:
    """One-shot VRAM snapshot, returns parsed list of dicts."""
    return nvidia_smi_json()

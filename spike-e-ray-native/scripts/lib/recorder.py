"""Recording utilities for spike experiments.

Rule 0.3 (protocol): record raw output, not summaries.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone


class Recorder:
    """Tee stdout/stderr to a log file while echoing to the terminal."""

    def __init__(self, step: str) -> None:
        self.step = step
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.log_path = os.path.join(
            os.environ["SPIKE_RAW_DIR"], f"{step}-{ts}.log"
        )
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self.log_fh = open(self.log_path, "w", encoding="utf-8")

    def write(self, msg: str) -> int:
        sys.stdout.write(msg)
        sys.stdout.flush()
        self.log_fh.write(msg)
        self.log_fh.flush()
        return len(msg)

    def close(self) -> None:
        self.log_fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def flush(self):
        sys.stdout.flush()


def record(step: str, **fields) -> None:
    """Append a JSON line to results/metrics/<step>.jsonl."""
    metrics_dir = os.environ["SPIKE_METRICS_DIR"]
    os.makedirs(metrics_dir, exist_ok=True)
    path = os.path.join(metrics_dir, f"{step}.jsonl")
    entry = {**fields, "_step": step, "_ts": datetime.now(timezone.utc).isoformat()}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def block(title: str, text: str) -> str:
    """Return a fenced markdown block, ready to paste into results."""
    return f"## {title}\n\n```\n{text}\n```\n"

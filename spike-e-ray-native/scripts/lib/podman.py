"""Podman snapshot helpers."""
from __future__ import annotations

import subprocess
from typing import Optional


def podman_ps_all() -> str:
    """Run 'podman ps -a' and return full output."""
    result = subprocess.run(
        ["podman", "ps", "-a"], capture_output=True, text=True, timeout=10,
    )
    return result.stdout


def podman_ps_all_json() -> list[dict]:
    """Run 'podman ps -a --format json' and return parsed list."""
    result = subprocess.run(
        ["podman", "ps", "-a", "--format", "json"],
        capture_output=True, text=True, timeout=10,
    )
    import json
    # Each line is a JSON object
    lines = result.stdout.strip().split("\n")
    return [json.loads(line) for line in lines if line]


def podman_images() -> str:
    """Run 'podman images --digests' and return full output."""
    result = subprocess.run(
        ["podman", "images", "--digests"],
        capture_output=True, text=True, timeout=10,
    )
    return result.stdout


def podman_ps_count(state: Optional[str] = None) -> int:
    """Count containers, optionally filtering by state (running, exited, etc.)."""
    cmd = ["podman", "ps", "-a"]
    if state:
        cmd.extend(["--filter", f"status={state}"])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    lines = result.stdout.strip().split("\n")
    return max(0, len(lines) - 1)  # subtract header

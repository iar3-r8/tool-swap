"""Capture environment information for spike results.

Fills the §4.1 environment table and runs the version-match assertion.

Every external command is executed through ``lib/safe_command.safe_run``,
so a missing binary is recorded as a string (e.g. "not present") rather
than a traceback that aborts the run.  The only non-zero exit is the
version-match assertion against ``RAY_BASE_TAG``.

Writes the assembled report to ``results/raw/env-capture-<ts>.log``,
satisfying protocol rule 0.3 (verbatim raw capture).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Optional

# Ensure the lib path
SCRIPT_DIR = os.path.join(os.path.dirname(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPT_DIR, "lib"))

from safe_command import safe_run, which as safe_which

from lib.recorder import block


def _safe_read_text(path: str) -> str:
    """Return file contents or 'N/A' if the file is missing."""
    try:
        return open(path, "r", encoding="utf-8").read()
    except (OSError, IOError):
        return "N/A"


def _safe_git_info() -> str:
    """Return git commit SHA and dirty-flag status."""
    sha = "(not a git repo)"
    dirty = ""
    # Check if we are inside a git tree
    rev = safe_run(["git", "rev-parse", "HEAD"], desc="git rev-parse HEAD", timeout=5)
    if "not present" not in rev:
        lines = rev.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line and "[" not in line and line.startswith("0x") is False and len(line) >= 4:
                sha = line
                break

    # Dirty check
    status = safe_run(["git", "status", "--porcelain"], desc="git status --porcelain", timeout=5)
    if "not present" not in status and status.strip():
        dirty = " (dirty)"
    else:
        dirty = " (clean)"

    return f"Commit: {sha}{dirty}"


def _safe_ray_version() -> str:
    """Return ray.__version__ or 'not installed'."""
    try:
        import ray  # noqa: F401
        return ray.__version__  # noqa: B009
    except ImportError:
        return "not installed"


def _safe_python_version() -> str:
    """Return Python version string."""
    return platform.python_version()


def _version_match_assertion(ray_base_tag: str) -> Optional[str]:
    """Assert that the host Ray + Python match RAY_BASE_TAG.

    Returns an error string on mismatch, or ``None`` on success.
    Only this function should cause a non-zero exit.
    """
    host_ray = _safe_ray_version()
    if host_ray == "not installed":
        print("WARNING: ray not installed on host; skipping version-match assertion")
        return None

    host_py = _python_minor_tag()  # e.g. 311 for py311

    # Extract from tag: rayproject/ray:2.57.0-py311-gpu
    tag_parts = ray_base_tag.split(":")[-1]  # e.g. 2.57.0-py311-gpu
    tag_ray = tag_parts.split("-")[0]  # e.g. 2.57.0
    tag_py_suffix = "py" + host_py  # e.g. py311

    if tag_ray != host_ray:
        msg = (
            f"VERSION MISMATCH:\n"
            f"  host Ray   {host_ray}\n"
            f"  tag Ray    {tag_ray}\n"
            f"  Fix: set RAY_BASE_TAG=rayproject/ray:{tag_ray}-py{host_py}-gpu"
        )
        print(msg)
        return msg

    if tag_py_suffix not in tag_parts:
        msg = (
            f"VERSION MISMATCH:\n"
            f"  host Python   {_safe_python_version()}\n"
            f"  tag             {ray_base_tag}\n"
            f"  Fix: set RAY_BASE_TAG to a tag containing py{host_py}"
        )
        print(msg)
        return msg

    return None


def _source_env() -> None:
    """Source env.sh so RAY_BASE_TAG and other vars are set.

    This ensures capture_env.py works when run directly (e.g.
    ``python scripts/capture_env.py``) and not only via the Makefile.
    """
    script_dir = os.path.join(os.path.dirname(__file__))
    env_sh = os.path.join(script_dir, "env.sh")
    if os.path.isfile(env_sh):
        # Use bash to source: set -a exports, env.sh sets vars, set +a stops export
        subprocess.run(
            ["bash", "-c", f"set -a; source {env_sh}; set +a"],
            check=False,
        )


def _python_minor_tag() -> str:
    """Return the pyNN suffix for a tag like py311.

    Platform.python_version() may be '3.11.16'; we need '311'.
    """
    parts = platform.python_version().split(".")
    # parts[0] = major, parts[1] = minor, parts[2] = patch (optional)
    return parts[0] + parts[1]  # e.g. '311'


def main() -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    raw_dir = os.environ.get("SPIKE_RAW_DIR", "results/raw")
    os.makedirs(raw_dir, exist_ok=True)
    log_path = os.path.join(raw_dir, f"env-capture-{ts}.log")

    # Source env.sh so RAY_BASE_TAG is available even when run directly
    _source_env()
    ray_base_tag = os.environ.get("RAY_BASE_TAG", "rayproject/ray:2.57.0-py311-gpu")

    sections: list[str] = []

    # ── 0. Timestamp ──────────────────────────────────────────────
    sections.append(f"## Timestamp\n\n{ts}\n")

    # ── 1. Ray version (host) ────────────────────────────────────
    sections.append(block("Ray version (ray.__version__)",
        safe_run(["python", "-c", "import ray; print(ray.__version__)"],
                 desc="ray.__version__")))
    sections.append(block("Ray CLI version",
        safe_run(["ray", "--version"], desc="ray --version")))

    # ── 2. Python version (host) ─────────────────────────────────
    sections.append(block("Python version",
        f"Version: {platform.python_version()}\nExecutable: {sys.executable}"))

    # ── 3. Base image tag ────────────────────────────────────────
    sections.append(f"## Base image tag\n\n`{ray_base_tag}`")

    # ── 4. Version-match assertion (MUST come before podman/GPU) ─
    vm_error = _version_match_assertion(ray_base_tag)
    if vm_error:
        sections.append(block("Version-match assertion", f"FAIL\n{vm_error}"))
        print("\n" + "=" * 60)
        print("VERSION MATCH FAILED — aborting environment capture.")
        print("Fix RAY_BASE_TAG before building images.")
        print("=" * 60)
        # Write whatever we have so far, then exit 1
        full_output = "\n".join(sections)
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write(full_output + "\n")
        print(f"Partial log saved to: {log_path}")
        sys.exit(1)
    else:
        host_ray = _safe_ray_version()
        host_py = platform.python_version()
        sections.append(block("Version-match assertion",
            f"OK: Ray {host_ray}, Python {host_py}, tag {ray_base_tag}"))

    # ── 5. Podman ────────────────────────────────────────────────
    sections.append(block("Podman version",
        safe_run(["podman", "version"], desc="podman version")))
    sections.append(block("Podman info",
        safe_run(["podman", "info"], desc="podman info", timeout=30)))

    # ── 6. GPU ───────────────────────────────────────────────────
    sections.append(block("nvidia-smi",
        safe_run(["nvidia-smi"], desc="nvidia-smi")))
    sections.append(block("nvidia-smi (detailed)",
        safe_run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                  "--format=csv"], desc="nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv")))

    # ── 6b. nvidia-ctk (if present) ─────────────────────────────
    if safe_which("nvidia-ctk"):
        sections.append(block("nvidia-ctk version",
            safe_run(["nvidia-ctk", "--version"], desc="nvidia-ctk --version")))

    # ── 7. Host OS / kernel ──────────────────────────────────────
    sections.append(block("OS / kernel",
        f"{platform.system()} {platform.release()}\n{platform.machine()}\n"
        + _safe_read_text("/etc/os-release")))
    sections.append(block("uname -a",
        safe_run(["uname", "-a"], desc="uname -a")))

    # ── 8. Docker presence (coexistence check) ───────────────────
    sections.append(block("Docker version (coexistence check)",
        safe_run(["docker", "version"], desc="docker version")))

    # ── 9. Git info ──────────────────────────────────────────────
    sections.append(block("Git commit", _safe_git_info()))

    # ── 10. Baked asset hashes (from each image, if podman works) ─
    sections.append("## Baked asset hashes (per image)\n")
    if safe_which("podman"):
        for img in ["tool_torch:spike", "tool_tf:spike"]:
            sections.append(f"### {img}\n")
            sections.append(block(f"{img} — asset meta",
                safe_run(
                    ["podman", "run", "--rm", img,
                     "python", "-c",
                     "import json, pathlib\n"
                     "for name in ['weights/ckpt.bin', 'data/payload.bin']:\n"
                     "    p = pathlib.Path('/opt/spike') / name\n"
                     "    meta = p.with_suffix(p.suffix + '.meta.json')\n"
                     "    if meta.exists():\n"
                     "        m = json.loads(meta.read_text())\n"
                     "        print(f'  {name}: {m[\\\"size_bytes\\\"]} bytes, sha256={m[\\\"sha256\\\"]}')\n"
                     "    else:\n"
                     "        print(f'  {name}: NOT FOUND')"],
                    desc=f"podman run --rm {img} cat asset meta",
                    timeout=30,
                )))
    else:
        sections.append("```\nSkipped: podman not present — images not available.\n```\n")

    # ── Write the log file (protocol rule 0.3) ───────────────────
    full_output = "\n".join(sections)
    with open(log_path, "w", encoding="utf-8") as fh:
        fh.write(full_output + "\n")

    print("\n" + "=" * 60)
    print("ENVIRONMENT CAPTURE COMPLETE")
    print(f"Log saved to: {log_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()

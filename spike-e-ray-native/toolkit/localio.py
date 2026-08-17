"""Read baked-in files from disk, timed.

Replaces ``s3io.py`` — there is no object storage in this spike (§0a).
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Optional


def read_file(path: str) -> bytes:
    """Read entire file, return bytes."""
    return Path(path).read_bytes()


def read_and_report(path: str) -> dict[str, Any]:
    """Read file, compute SHA-256, return metadata dict.

    Returns:
        dict with keys:
            - size_bytes (int)
            - sha256 (str) — full hash
            - read_seconds (float)
    """
    p = Path(path)
    data = p.read_bytes()

    t0 = time.monotonic()
    h = hashlib.sha256(data).hexdigest()
    elapsed = time.monotonic() - t0

    return {
        "size_bytes": len(data),
        "sha256": h,
        "read_seconds": round(elapsed, 6),
    }


def read_and_verify(path: str, expected_sha256: Optional[str] = None) -> dict[str, Any]:
    """Read file and verify against sidecar .meta.json if present.

    Returns dict with:
        - size_bytes, sha256, read_seconds
        - size_match (bool) — whether size_bytes matches the sidecar
        - hash_match (bool) — whether sha256 matches the sidecar
    """
    meta = read_and_report(path)
    meta_path = Path(f"{path}.meta.json")

    if not meta_path.exists():
        meta["size_match"] = True
        meta["hash_match"] = True
        return meta

    sidecar = meta_path.read_text()
    from json import loads as json_loads
    expected = json_loads(sidecar)

    meta["size_match"] = meta["size_bytes"] == expected.get("size_bytes")
    meta["hash_match"] = meta["sha256"] == expected.get("sha256")

    return meta

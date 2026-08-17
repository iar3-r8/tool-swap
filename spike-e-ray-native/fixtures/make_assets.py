#!/usr/bin/env python3
"""Generate fixture assets and bake them into the image at build time.

Produces:
  - a weights checkpoint  (WEIGHTS_MB megabytes)
  - a data payload        (PAYLOAD_MB megabytes)
  - sidecar .meta.json for each with exact size_bytes + sha256

Uses a deterministic SHA-256 counter mode PRNG, streamed in chunks.
Never assembles the full file in memory. Never uses zeros — compressible
content would make any future read measurement optimistic.

Usage (normally invoked via RUN inside the Dockerfile):
    python make_assets.py \
        --weights /opt/spike/weights/ckpt.bin --weights-mb 8 \
        --payload /opt/spike/data/payload.bin --payload-mb 64
"""
from __future__ import annotations

import hashlib
import json
import argparse
import os
import struct
import sys
from pathlib import Path


def _counter_stream(seed_base: int, offset: int, chunk_size: int) -> bytes:
    """Yield chunk_size deterministic bytes from SHA-256 counter mode."""
    out = bytearray()
    counter = offset
    while len(out) < chunk_size:
        h = hashlib.sha256(struct.pack(">Q", seed_base + counter)).digest()
        out.extend(h)
        counter += 1
    return bytes(out[:chunk_size])


def _generate_file(
    path: str,
    size_bytes: int,
    seed: int,
    chunk_mb: int = 10,
) -> dict:
    """Generate a file of *size_bytes* and return its metadata dict."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    chunk_size = chunk_mb * 1024 * 1024
    sha = hashlib.sha256()
    written = 0
    part = 0

    with open(p, "wb") as fh:
        while written < size_bytes:
            remaining = size_bytes - written
            this_chunk = min(chunk_size, remaining)
            data = _counter_stream(seed, part, this_chunk)
            fh.write(data)
            sha.update(data)
            written += len(data)
            part += 1

    return {
        "size_bytes": written,
        "sha256": sha.hexdigest(),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Bake fixture assets into an image.")
    ap.add_argument("--weights", required=True, help="Path to checkpoint file")
    ap.add_argument("--weights-mb", type=int, default=8, help="Checkpoint size in MB")
    ap.add_argument("--payload", required=True, help="Path to payload file")
    ap.add_argument("--payload-mb", type=int, default=64, help="Payload size in MB")
    args = ap.parse_args()

    weights_bytes = args.weights_mb * 1024 * 1024
    payload_bytes = args.payload_mb * 1024 * 1024

    print(f"Baking assets: weights={args.weights} ({args.weights_mb} MB), "
          f"payload={args.payload} ({args.payload_mb} MB)")

    w_meta = _generate_file(args.weights, weights_bytes, seed=42)
    print(f"  weights: {w_meta['size_bytes']} bytes, sha256={w_meta['sha256']}")

    p_meta = _generate_file(args.payload, payload_bytes, seed=137)
    print(f"  payload: {p_meta['size_bytes']} bytes, sha256={p_meta['sha256']}")

    # Write sidecar .meta.json alongside each asset
    for meta_path, meta in [(args.weights, w_meta), (args.payload, p_meta)]:
        meta_json_path = f"{meta_path}.meta.json"
        with open(meta_json_path, "w") as f:
            json.dump(meta, f, indent=2)
        print(f"  wrote {meta_json_path}")

    # Print everything to stdout for build-image.sh to capture
    print(json.dumps({"weights": w_meta, "payload": p_meta}))


if __name__ == "__main__":
    main()

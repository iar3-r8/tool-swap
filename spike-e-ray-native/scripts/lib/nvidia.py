"""nvidia-smi parsing and VRAM sampling.

The host driver (565.57.01 / CUDA 12.7) rejects ``--format=json``
("Format modifier is not recognized"), so all queries use
``--format=csv,noheader,nounits``: no header row to skip and no unit
suffixes to strip on the happy path. The parser additionally tolerates
the plain ``csv`` form (a header row plus " MiB" unit suffixes), so a
driver that ignores the modifiers cannot break the gate. Memory fields
come back as ints in MiB so the gate's arithmetic is unambiguous.
"""

from __future__ import annotations

import csv
import io
import os
import subprocess
import threading
import time
from datetime import datetime, timezone

_QUERY = "index,memory.used,memory.total,name,driver_version"

# Canonical dict keys — identical to the old --format=json output, so
# existing consumers (vram_sampler, the step 3 gate) work unchanged.
_KEYS = (
    "index",
    "memory.used [MiB]",
    "memory.total [MiB]",
    "name",
    "driver_version",
)


class NvidiaSmiError(RuntimeError):
    """nvidia-smi could not be run or its output could not be parsed.

    The message always names the command and shows the start of the
    output, so a broken snapshot is diagnosable from the log. Callers
    (the step 3 gate) turn this into an honest harness failure
    (exit 2) — never a silent empty result.
    """


def nvidia_smi(query: str = "memory.used", fmt: str = "csv") -> str:
    """Run nvidia-smi with the given query and return its stdout.

    Args:
        query: Comma-separated ``--query-gpu`` fields.
        fmt: The ``--format`` value (e.g. ``csv,noheader,nounits``).

    Raises:
        NvidiaSmiError: the binary is missing, timed out, or exited
            non-zero (the message includes the command and output).
    """
    cmd = ["nvidia-smi", f"--query-gpu={query}", f"--format={fmt}"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10
        )
    except FileNotFoundError:
        raise NvidiaSmiError(
            f"nvidia-smi not found on PATH (command: {' '.join(cmd)})"
        ) from None
    except subprocess.TimeoutExpired:
        raise NvidiaSmiError(
            f"nvidia-smi timed out after 10s (command: {' '.join(cmd)})"
        ) from None
    if result.returncode != 0:
        head = (result.stdout or result.stderr).strip()[:400]
        raise NvidiaSmiError(
            f"nvidia-smi exited {result.returncode} "
            f"(command: {' '.join(cmd)}, output: {head!r})"
        )
    return result.stdout


def _to_mib(raw: str, field: str) -> int:
    """Coerce one CSV memory cell to an int in MiB.

    Tolerates a trailing unit suffix ("38379 MiB") so the plain
    ``csv`` output parses as well as ``csv,noheader,nounits``.

    Args:
        raw: The raw cell text.
        field: The field name, for the error message.

    Raises:
        NvidiaSmiError: the cell is not an integer after unit stripping.
    """
    text = raw.strip()
    if text.lower().endswith("mib"):
        text = text[: -len("mib")].strip()
    try:
        return int(text)
    except ValueError:
        raise NvidiaSmiError(
            f"unparseable {field} value in nvidia-smi output: {raw!r}"
        ) from None


def _parse_csv_row(row: list[str]) -> dict:
    """Convert one CSV row into the canonical per-GPU dict.

    Args:
        row: One parsed CSV row (5 cells, in ``_QUERY`` order).

    Raises:
        NvidiaSmiError: wrong number of cells, or a cell that does not
            coerce (non-integer index/memory, header-like row).
    """
    if len(row) != len(_KEYS):
        raise NvidiaSmiError(
            f"unexpected nvidia-smi CSV row (expected {len(_KEYS)} "
            f"fields, got {len(row)}): {row!r}"
        )
    try:
        index = int(row[0].strip())
    except ValueError:
        raise NvidiaSmiError(
            f"unparseable nvidia-smi CSV row (bad index cell): {row!r}"
        ) from None
    return {
        "index": index,
        "memory.used [MiB]": _to_mib(row[1], "memory.used"),
        "memory.total [MiB]": _to_mib(row[2], "memory.total"),
        "name": row[3].strip(),
        "driver_version": row[4].strip(),
    }


def parse_nvidia_csv(stdout: str) -> list[dict]:
    """Parse nvidia-smi CSV output into one dict per GPU.

    Handles both ``csv,noheader,nounits`` (the issued form) and plain
    ``csv`` (a header row plus " MiB" suffixes).

    Args:
        stdout: The raw nvidia-smi output.

    Returns:
        One dict per GPU: ``{"index": int, "memory.used [MiB]": int,
        "memory.total [MiB]": int, "name": str,
        "driver_version": str}``.

    Raises:
        NvidiaSmiError: no rows (including empty output), or a row
            that does not parse.
    """
    rows = [r for r in csv.reader(io.StringIO(stdout)) if r]
    if rows and rows[0][0].strip().lower() == "index":
        rows = rows[1:]  # tolerate a header row
    if not rows:
        raise NvidiaSmiError(_no_rows_message(stdout))
    try:
        return [_parse_csv_row(r) for r in rows]
    except NvidiaSmiError as e:
        # Preserve the specific row complaint, but add the command and
        # the raw output so a driver error line ("Format modifier is
        # not recognized.") survives into the log.
        raise NvidiaSmiError(
            f"{e} — command: {_command()}, output: {stdout.strip()[:400]!r}"
        ) from e


def _command() -> str:
    """The exact nvidia-smi command this module issues (for errors)."""
    return (
        f"nvidia-smi --query-gpu={_QUERY} --format=csv,noheader,nounits"
    )


def _no_rows_message(stdout: str) -> str:
    """Error text for output that contains no parseable GPU rows."""
    return (
        "nvidia-smi produced no GPU rows "
        f"(command: {_command()}, output: {stdout.strip()[:400]!r})"
    )


def nvidia_smi_csv() -> list[dict]:
    """Run nvidia-smi (csv,noheader,nounits) and parse per-GPU rows.

    Raises:
        NvidiaSmiError: the command is missing/fails, or the output
            cannot be parsed (see ``parse_nvidia_csv``).
    """
    return parse_nvidia_csv(nvidia_smi(_QUERY, fmt="csv,noheader,nounits"))


def snapshot_vram() -> list[dict]:
    """One-shot VRAM snapshot, returns one dict per GPU.

    Keys: ``index`` (int), ``memory.used [MiB]`` (int),
    ``memory.total [MiB]`` (int), ``name`` (str),
    ``driver_version`` (str).

    Raises:
        NvidiaSmiError: nvidia-smi could not be run or parsed.
    """
    return nvidia_smi_csv()


def parse_cuda_visible_devices(value: str | None) -> int | None:
    """Parse a CUDA_VISIBLE_DEVICES value into a single host GPU index.

    Args:
        value: The value reported by the toolkit's introspect op
            (toolkit/introspect.py).

    Returns:
        The device index when the value names exactly one device
        (e.g. "2"), else None — empty/"<not set>", several devices
        ("0,1"), or a non-integer value cannot be attributed to one
        GPU.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if len(parts) != 1:
        return None
    try:
        index = int(parts[0])
    except ValueError:
        return None
    return index if index >= 0 else None


def gpu_used_mb(snapshot: list[dict], index: int) -> int | None:
    """Used MiB of one GPU in a snapshot.

    Args:
        snapshot: Parsed nvidia-smi rows (``snapshot_vram`` output).
        index: The host GPU index to read.

    Returns:
        That GPU's ``memory.used [MiB]``, or None when the index is
        not present in the snapshot.
    """
    for row in snapshot:
        if row.get("index") == index:
            return row["memory.used [MiB]"]
    return None


def vram_sampler(
    output_path: str,
    interval: float = 1.0,
    duration: float | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    """Background VRAM sampler. Writes timestamped CSV.

    A failed sample is printed (with the reason) and sampling
    continues: a sampler that dies mid-run would lose the trace, but a
    silent skip would hide a broken nvidia-smi.

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
        # The index column labels each sample: on a shared host an
        # unlabeled per-GPU series would not say whose VRAM it is.
        writer.writerow(["timestamp", "index", "memory_used_mb"])
        start = time.monotonic()
        while True:
            if duration and (time.monotonic() - start) >= duration:
                break
            if stop_event and stop_event.is_set():
                break
            try:
                rows = nvidia_smi_csv()
            except Exception as e:
                print(f"[vram-sampler] sample failed: {e}", flush=True)
            else:
                ts = datetime.now(timezone.utc).isoformat()
                for row in rows:
                    writer.writerow(
                        [ts, row["index"], row["memory.used [MiB]"]]
                    )
                fh.flush()
            time.sleep(interval)

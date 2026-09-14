"""Step 8 — Plain-podman alternation baseline (D45).

The one cheap measurement that resolves the step-5 P90 attribution
(ledger §9Q: bimodal, median 9.5s, P90 103s, 40% of 20 cycles at
99-104s; §9R: no such baseline exists yet). Plain podman alternates the
two fixture images on one GPU with NO Ray: no cluster, no autoscaler,
no health checks, no control plane.

FAIR-COMPARISON DECISION (stated here and in the output; re-decide
before changing it)
----------------------------------------------------------------------
Question: how much of step 5's ~100s slow path is Ray's orchestration
versus starting/stopping a 14-19 GB container?

What step 5's per-cycle latency INCLUDES (scripts/step5_alternate.py):
    * scale_deployment(incumbent, 0)  — control-plane RPC + Ray's
      replica teardown of a live, VRAM-holding container
    * scale_deployment(target, 1)     — control-plane RPC + Ray starting
      a FRESH container (image_uri launches one per replica start; the
      109 orphans, §9R, prove they are not reused)
    * the replica's Tool.__init__     — weights read + sha256
      (toolkit/deployments.py), 4096 MiB VRAM allocation + CUDA
      context (toolkit/vram.py)
    * one HTTP introspect round trip  — ingress routing + the
      deliberately GPU-free introspect op
What step 5's per-cycle latency EXCLUDES: nothing of the above is split
out; it is one wall-clock span per cycle.

Plain podman has no incumbent-to-displace machinery and no control
plane, so one single "equivalent" number is impossible. This step
therefore reports TWO labelled modes; the per-side inclusions are
printed verbatim in the output (an unfair comparison is worse than no
comparison — it would look authoritative):

    SPIKE_STEP8_MODE=start (default)
        Times exactly:  podman run (FRESH container start) +
        Tool.__init__ equivalent (weights read + verify, 4096 MiB
        VRAM, CUDA context) + identity print + exit.
        INCLUDES: the data-path container side of a step-5 cycle —
        fresh container start, init, allocation.
        EXCLUDES: Ray's scale RPCs, replica teardown, ingress routing,
        the HTTP round trip (a `podman run` is not an HTTP server; the
        identity print over captured stdout is the introspect-
        equivalent).
        INTERPRETATION: the container-start component of the slow
        path. If this is ~10s and step 5's slow cycle is ~100s, the
        difference is Ray-side.

    SPIKE_STEP8_MODE=full
        Per cycle:  podman stop of the OTHER tool's live container
        (a holder that genuinely allocated 4096 MiB) + the start-mode
        span. The sequence is: tear down the holder, start the
        challenger, allocate, respond (identity), exit — matching the
        step-5 cycle, whose slow path is hypothesised to be
        "incumbent fully torn down + target cold-started" (§9Q).
        After each cycle the just-run tool is re-launched as the live
        holder for the NEXT cycle (unmeasured setup, so no cycle pays
        for the holder that the previous cycle's teardown removed).
        LIMITS (printed in the output):
          * the stop and the start are SERIAL — Ray's actor teardown
            and new-replica start can overlap;
          * `podman stop` sends SIGTERM with a 10s grace (the holder's
            python process exits on SIGTERM immediately, so the stop
            is fast and clean — closer to Ray's replica shutdown than
            a SIGKILL, but Ray also runs the replica's own shutdown
            hooks, which we do not);
          * the holder is re-created fresh each cycle, while Ray may
            keep a stopped container's state between scale-down and
            scale-up; the challenger side (the measured cold start) is
            the same fresh-container launch in both.
        full mode is a BRACKET, not a like-for-like.

VRAM GATE (the step-3 trap)
---------------------------
Timing a no-op is worthless (step 3's first run). Each cycle runs the
CSV-based per-GPU sampler from scripts/lib/nvidia.py in a background
thread while the container runs, and requires the peak on the target
GPU to rise by at least SPIKE_STEP8_VRAM_RISE_MB (default 1024 MiB;
the fixture allocates 4096 MiB plus CUDA context — step 3 measured
+4516 MiB on this host). A cycle that ran but did not allocate is a
NEGATIVE FINDING (exit 3): the observation was made and it says the
number is of a no-op. Before/after snapshots alone cannot gate this:
`--rm` removes the container on exit and the driver returns the VRAM
before the post-run snapshot.

Exit status (D29)
-----------------
    0  All N cycles completed, every answer identified the right tool,
       every cycle allocated VRAM.
    1  Unexpected internal error (traceback printed).
    2  Harness/environment failure — an observation could NOT be made:
       podman or nvidia-smi missing, the nvidia runtime missing, a
       fixture image absent, the GPU unavailable, or a container that
       failed to start (podman exited non-zero / timed out).
    3  Negative finding — the observations WERE made: a cycle
       allocated no VRAM (the no-op trap), an answer carried the
       wrong tool's identity, or more than SPIKE_STEP8_MAX_ERRORS
       cycles failed.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import threading
import time

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
sys.path.insert(0, os.path.join(_SCRIPTS_DIR, "lib"))

from nvidia import (
    NvidiaSmiError,
    gpu_used_mb,
    snapshot_vram,
    vram_sampler,
)
from recorder import Recorder, block, record
from step1_verify import StepOutcome

# ── Knobs (env-overridable, read at import like step 5's N) ─────

N = int(os.environ.get("SPIKE_STEP8_N", "20"))
MODE = os.environ.get("SPIKE_STEP8_MODE", "start")  # "start" | "full"
GPU_INDEX = int(os.environ.get("SPIKE_STEP8_GPU_INDEX", "0"))
VRAM_RISE_MB = int(os.environ.get("SPIKE_STEP8_VRAM_RISE_MB", "1024"))
RUN_TIMEOUT_S = float(os.environ.get("SPIKE_STEP8_RUN_TIMEOUT_S", "300"))
STOP_TIMEOUT_S = float(os.environ.get("SPIKE_STEP8_STOP_TIMEOUT_S", "60"))
PREWARM = os.environ.get("SPIKE_STEP8_PREWARM", "1") == "1"
MAX_ERRORS = int(os.environ.get("SPIKE_STEP8_MAX_ERRORS", "0"))
# How long to wait (unmeasured) for a re-launched holder to allocate,
# so the next cycle's stop is not a no-op.
HOLDER_WAIT_S = float(os.environ.get("SPIKE_STEP8_HOLDER_WAIT_S", "180"))
SAMPLE_INTERVAL_S = float(os.environ.get("SPIKE_STEP8_SAMPLE_S", "0.5"))

NVIDIA_RUNTIME = "/usr/bin/nvidia-container-runtime"
# Fixture images, built by fixtures/build_images.sh (names fixed there;
# what is run must be readable — D26 style).
IMAGES = {"torch": "tool_torch:spike", "tf": "tool_tf:spike"}
# Each image bakes SPIKE_IMAGE_MARKER (fixtures/*.Dockerfile), so the
# printed marker IS the introspect-equivalent of step 5's image_marker.
EXPECTED_MARKER = {"torch": "tool_torch", "tf": "tool_tf"}
VRAM_MB = 4096  # Tool.__init__ default (toolkit/deployments.py)

# In-container program: replicates Tool.__init__ (toolkit/deployments.py)
# WITHOUT Ray — read + verify the baked weights, allocate 4096 MiB
# (toolkit/vram.py), print the identity (the introspect-equivalent).
# Exactly one JSON line; the harness greps the prefix, not the last
# line (podman may emit warnings).
CHALLENGER_PROG = r"""
import json, os, time
from toolkit.localio import read_and_verify
from toolkit.vram import VRAMAllocator
t0 = time.monotonic()
meta = read_and_verify(os.environ.get(
    "SPIKE_WEIGHTS_PATH", "/opt/spike/weights/ckpt.bin"))
vram = VRAMAllocator(int(os.environ.get("SPIKE_VRAM_MB", "4096"))).allocate()
print("SPIKE_STEP8_JSON " + json.dumps({
    "image_marker": os.environ.get("SPIKE_IMAGE_MARKER", "<absent>"),
    "pid": os.getpid(),
    "framework": vram.get("framework", "none"),
    "vram_allocated_mb": vram.get("allocated_mb", 0),
    "vram_gpu_available": bool(vram.get("gpu_available", False)),
    "weights_bytes": meta["size_bytes"],
    "weights_sha256": meta["sha256"],
    "weights_hash_match": bool(meta["hash_match"]),
    "weights_load_seconds": round(meta["read_seconds"], 6),
    "init_total_seconds": round(time.monotonic() - t0, 6),
}))
"""

# Full-mode holder: allocates the same 4096 MiB and then sleeps, so the
# container is a LIVE, VRAM-holding "incumbent" that the next cycle's
# stop must genuinely tear down. Without the sleep the process would
# exit and the stop would be a no-op — the step-3 trap, wearing a
# different hat.
HOLDER_PROG = CHALLENGER_PROG + "\ntime.sleep(3600)\n"

# Holder containers are named so a cycle can stop the exact one.
HOLDER_NAMES = {"torch": "step8_holder_torch", "tf": "step8_holder_tf"}


def _podman_run_cmd(direction: str, prog: str) -> list[str]:
    """The exact podman argv for one run (ledger §9L command shape).

    ``--rm`` is deliberate: unlike Ray's image_uri launches (109
    orphans, §9R), this step must not add to the container
    accumulation. ``-e PYTHONPATH`` is redundant with the image's ENV
    and cwd but keeps the toolkit import explicit.

    Args:
        direction: "torch" or "tf" — selects the fixture image.
        prog: The python -c program (challenger or holder).

    Returns:
        The argv list, printable verbatim.
    """
    return [
        "podman", "run", "--rm",
        "--runtime", NVIDIA_RUNTIME,
        "-e", "NVIDIA_VISIBLE_DEVICES=0",
        "-e", "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
        "-e", f"SPIKE_VRAM_MB={VRAM_MB}",
        "-e", "PYTHONPATH=/home/ray",
        "--entrypoint", "python",
        IMAGES[direction],
        "-c", prog,
    ]


def _stats(values: list[float]) -> dict[str, float]:
    """min/median/P90/max/count with step 5's exact P90 convention.

    Step 5 uses ``sorted[int(len*0.9)]`` (index 18 of 20 — nearest-rank
    upper, NOT linear-interpolated percentile 90) and the upper
    median ``sorted[len//2]``. Reusing the convention makes the two
    distributions directly comparable.

    Args:
        values: Per-cycle seconds (completed cycles only).

    Returns:
        ``{"min", "median", "p90", "max", "count"}``.

    Raises:
        ValueError: on empty input — a 0-sample distribution is
            meaningless and must not print as zeros.
    """
    if not values:
        raise ValueError("no completed cycles — no distribution to report")
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "median": ordered[len(ordered) // 2],
        "p90": ordered[min(int(len(ordered) * 0.9), len(ordered) - 1)],
        "max": ordered[-1],
        "count": len(ordered),
    }


def _print_stats(label: str, values: list[float]) -> dict[str, float] | None:
    """Print the step-5-style distribution block for *values*.

    Args:
        label: Header line for this distribution.
        values: Completed per-cycle seconds.

    Returns:
        The stats dict, or None when *values* is empty.
    """
    if not values:
        print(f"\n{label}: no completed cycles — no distribution.")
        return None
    st = _stats(values)
    print(f"\n{label} — distribution of {st['count']} completed cycle(s):")
    print(f"  Min:    {st['min']:.3f}s")
    print(f"  Median: {st['median']:.3f}s")
    print(f"  P90:    {st['p90']:.3f}s")
    print(f"  Max:    {st['max']:.3f}s")
    print(f"  Count:  {st['count']}")
    return st


def _gpu_used_or_harness(
    outcome: StepOutcome, what: str
) -> int | None:
    """Snapshot the target GPU's used MiB; harness failure on error.

    A snapshot we cannot take blinds the step's anti-no-op gate — the
    allocation observations would not be made.

    Args:
        outcome: Collects the harness failure.
        what: What this snapshot is for (message context).

    Returns:
        Used MiB on GPU *GPU_INDEX*, or None (harness recorded).
    """
    try:
        used = gpu_used_mb(snapshot_vram(), GPU_INDEX)
    except NvidiaSmiError as e:
        outcome.harness(
            f"VRAM snapshot failed ({what}): {e} — the allocation "
            "observations cannot be made."
        )
        return None
    if used is None:
        outcome.harness(
            f"GPU {GPU_INDEX} not present in the nvidia-smi snapshot "
            f"({what}) — the allocation observations cannot be made."
        )
    return used


def _peak_from_sampler(path: str) -> int | None:
    """Peak used MiB on the target GPU across one sampler CSV.

    Args:
        path: A vram_sampler CSV (timestamp, index, memory_used_mb).

    Returns:
        The peak for GPU *GPU_INDEX*, or None when the sampler never
        produced a sample for it.
    """
    peak: int | None = None
    try:
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                if int(row["index"]) == GPU_INDEX:
                    mb = int(row["memory_used_mb"])
                    peak = mb if peak is None else max(peak, mb)
    except (OSError, ValueError, KeyError) as e:
        # An unreadable/short sampler file blinds the gate — the caller
        # treats None as "the observation could not be made".
        print(f"  [warn] sampler CSV unreadable for {path!r}: {e}")
        return None
    return peak


def _wait_idle_baseline(outcome: StepOutcome, what: str) -> int | None:
    """Wait for the GPU's VRAM to plateau, then take the baseline.

    The driver releases a just-exited container's VRAM with a lag.
    Snapshotting the baseline immediately after a run can read the
    still-held ~5 GiB instead of the idle level; against that inflated
    baseline the next container's allocation looks like zero rise — a
    FALSE no-op finding. So we poll until the reading stops falling
    (a plateau within 256 MiB of the minimum, held for 4s — the same
    driver-noise tolerance step 3 uses) and use the LOWEST reading as
    the baseline. Plateau detection needs no prior reference to the
    idle level, which we do not know on a shared host.

    Args:
        outcome: Collects a harness failure when the reading does not
            plateau within HOLDER_WAIT_S (the baseline is then
            unreliable, and the min reading is returned with the
            failure recorded so the caller can proceed cautiously).
        what: What the baseline is for (message context).

    Returns:
        The minimum used MiB seen (the baseline estimate), or None
        when no reading was taken at all.
    """
    deadline = time.monotonic() + HOLDER_WAIT_S
    min_used: int | None = None
    stable_since: float | None = None
    while time.monotonic() < deadline:
        used = _gpu_used_or_harness(outcome, what)
        if used is not None:
            if min_used is None or used < min_used:
                min_used = used
                stable_since = time.monotonic()
            elif used - min_used <= 256:  # driver-noise tolerance
                if stable_since is None:
                    stable_since = time.monotonic()
            else:  # jumped above the minimum+tolerance: not plateaued
                stable_since = None
            if stable_since is not None \
                    and time.monotonic() - stable_since >= 4:
                return min_used
        time.sleep(2)
    outcome.harness(
        f"GPU {GPU_INDEX} VRAM did not plateau within "
        f"{HOLDER_WAIT_S:.0f}s ({what}) — using the lowest reading "
        f"({min_used}) as the baseline, which may be unreliable."
    )
    return min_used


def _image_present(image: str) -> bool:
    """True when the local podman store has *image*.

    Uses `podman image inspect` per image (two calls): a missing image
    is a non-zero exit with a message on stderr, which is exactly the
    signal needed and needs no output-shape assumptions (podman 3.4.4
    and 4.x differ on `--format json` for images).

    Args:
        image: The image name:tag to check.
    """
    try:
        result = subprocess.run(
            ["podman", "image", "inspect", image],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return False
    return result.returncode == 0


def _preflight(outcome: StepOutcome, recorder: Recorder) -> bool:
    """Check host preconditions; return True when the step can run.

    Each missing capability is a harness failure (exit 2): proceeding
    would only produce noise that looks like data.

    Args:
        outcome: Collects the harness failures.
        recorder: Records the preflight evidence.

    Returns:
        True when podman, nvidia-smi, the runtime, both images and the
        target GPU are all present.
    """
    ok = True
    for binary in ("podman", "nvidia-smi"):
        if shutil.which(binary) is None:
            ok = False
            outcome.harness(
                f"{binary} not found on PATH — the step-8 baseline "
                "cannot be observed. Run on the GPU host."
            )
    if shutil.which(NVIDIA_RUNTIME) is None:
        ok = False
        outcome.harness(
            f"{NVIDIA_RUNTIME} not found — ledger §9L established it is "
            "the only GPU-passthrough mechanism that works on this "
            "host; without it a run would time a no-op."
        )
    if ok:
        missing = [
            IMAGES[d] for d in ("torch", "tf") if not _image_present(IMAGES[d])
        ]
        if missing:
            ok = False
            outcome.harness(
                f"fixture image(s) absent from the local podman store: "
                f"{', '.join(missing)} — build them with `make fixtures`."
            )
    if ok:
        used = _gpu_used_or_harness(outcome, "preflight")
        if used is None:
            ok = False
        else:
            print(f"  GPU {GPU_INDEX}: {used} MiB used at preflight")
    recorder.write(block("Step 8 preflight", json.dumps({
        "mode": MODE,
        "gpu_index": GPU_INDEX,
        "n_cycles": N,
        "vram_rise_mb": VRAM_RISE_MB,
        "nvidia_runtime": NVIDIA_RUNTIME,
        "images": IMAGES,
    }, indent=2)))
    return ok


def _stop_container(
    name: str, outcome: StepOutcome, recorder: Recorder
) -> float:
    """Stop a live container. Returns wall-clock seconds.

    Default `podman stop` semantics: SIGTERM, 10s grace. The holder's
    python exits on SIGTERM immediately, so this is a clean, fast
    teardown — the closest plain-podman analogue to Ray stopping a
    replica (see the full-mode LIMITS in the module docstring).

    Args:
        name: The container name.
        outcome: Collects a harness failure when the stop itself
            could not be made (the teardown phase then was not
            observed). A "no such container" answer is NOT a failure:
            the previous cycle's --rm already removed it — the honest
            common case, recorded with 0.0s.
        recorder: Records the stop command and outcome.

    Returns:
        Wall-clock seconds for the stop.
    """
    cmd = ["podman", "stop", name]
    t0 = time.monotonic()
    detail = "not run"
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=STOP_TIMEOUT_S
        )
        detail = f"exit {result.returncode}"
        stderr = (result.stderr or "").lower()
        if result.returncode != 0 and "no container with name" not in stderr:
            outcome.harness(
                f"`podman stop` of {name} exited {result.returncode}: "
                f"{(result.stderr or result.stdout)[:300]} — the "
                "teardown phase was not observed."
            )
    except subprocess.TimeoutExpired:
        detail = f"timed out after {STOP_TIMEOUT_S:.0f}s"
        outcome.harness(
            f"`podman stop` of {name} timed out after {STOP_TIMEOUT_S:.0f}s "
            "— the teardown phase was not observed."
        )
    except Exception as e:
        detail = str(e)
        outcome.harness(f"`podman stop` of {name} could not run: {e}")
    elapsed = time.monotonic() - t0
    recorder.write(block(f"stop {name}", f"{detail} in {elapsed:.3f}s"))
    return elapsed


def _run_cycle(
    direction: str,
    iteration: int,
    outcome: StepOutcome,
    recorder: Recorder,
) -> dict:
    """Run one alternation cycle and return its metric record.

    The timed span starts where step 5's does in spirit: at the moment
    the displacement of the incumbent begins (full mode) or the
    challenger is asked to come up (start mode).

    Args:
        direction: "torch" or "tf" — the tool to start.
        iteration: 1-based cycle number.
        outcome: Collects failures and findings.
        recorder: Records the command and raw output.

    Returns:
        The metric record (the shape written to step8.jsonl).
    """
    other = "tf" if direction == "torch" else "torch"
    cmd = _podman_run_cmd(direction, CHALLENGER_PROG)
    entry = {
        "mode": MODE,
        "iteration": iteration,
        "direction": direction,
        "image": IMAGES[direction],
    }

    # Teardown phase (full mode): stop the live holder. Timed: it is
    # part of the cycle, matching step 5's scale-to-zero.
    stop_seconds = 0.0
    vram_pre_stop = None
    if MODE == "full":
        vram_pre_stop = _gpu_used_or_harness(
            outcome, f"alt {iteration} pre-stop"
        )
        stop_seconds = _stop_container(
            HOLDER_NAMES[other], outcome, recorder
        )

    # Baseline for the VRAM gate: the GPU's idle level just before the
    # challenger starts. _wait_idle_baseline guards against the driver's
    # slow release of the previous container's VRAM (see its docstring).
    vram_baseline = _wait_idle_baseline(outcome, f"alt {iteration} pre-run")

    # The challenger run, with VRAM sampled during it. Before/after
    # snapshots cannot gate allocation: --rm removes the container on
    # exit and the driver returns the VRAM before a post-run snapshot.
    # The sampler captures the peak.
    raw_dir = os.environ.get("SPIKE_RAW_DIR", "results/raw")
    sampler_path = os.path.join(
        raw_dir, f"step8-vram-gpu{GPU_INDEX}-alt{iteration}.csv"
    )
    stop_event = threading.Event()
    sampler_thread = threading.Thread(
        target=vram_sampler,
        args=(sampler_path, SAMPLE_INTERVAL_S),
        kwargs={"stop_event": stop_event},
        daemon=True,
    )
    t0 = time.monotonic()
    try:
        sampler_thread.start()
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=RUN_TIMEOUT_S,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        result = None
    except Exception as e:
        result = e
    finally:
        stop_event.set()
        sampler_thread.join(timeout=10)
    elapsed = time.monotonic() - t0

    if isinstance(result, Exception):
        entry["total_seconds"] = round(elapsed, 3)
        entry["stop_seconds"] = round(stop_seconds, 3)
        entry["error"] = f"podman run could not be invoked: {result}"
        record("step8", **entry)
        print(f"  Alt {iteration:2d}/{N} {direction:>7s}: ERROR {result}")
        outcome.harness(
            f"Alt {iteration} ({direction}): podman run could not be "
            f"invoked: {result} — the cycle was not observed."
        )
        return entry
    if result is None:  # timeout
        entry["total_seconds"] = round(elapsed, 3)
        entry["stop_seconds"] = round(stop_seconds, 3)
        entry["error"] = f"timed out after {RUN_TIMEOUT_S:.0f}s"
        record("step8", **entry)
        print(f"  Alt {iteration:2d}/{N} {direction:>7s}: TIMEOUT")
        outcome.harness(
            f"Alt {iteration} ({direction}) timed out after "
            f"{RUN_TIMEOUT_S:.0f}s — the cycle was not observed."
        )
        recorder.write(block(f"alt {iteration} command", " ".join(cmd)))
        return entry
    if result.returncode != 0:
        entry["total_seconds"] = round(elapsed, 3)
        entry["stop_seconds"] = round(stop_seconds, 3)
        entry["error"] = (result.stderr or result.stdout)[:400]
        record("step8", **entry)
        print(f"  Alt {iteration:2d}/{N} {direction:>7s}: "
              f"podman exit {result.returncode}")
        outcome.harness(
            f"Alt {iteration} ({direction}): a container that failed "
            f"to start/run (podman exit {result.returncode}) — an "
            "environment fault, not a finding."
        )
        recorder.write(block(
            f"alt {iteration} (podman exit {result.returncode})",
            " ".join(cmd) + "\n--- stderr ---\n" + (result.stderr or ""),
        ))
        return entry

    # Identity: the introspect-equivalent.
    report = None
    for line in (result.stdout or "").splitlines():
        if line.startswith("SPIKE_STEP8_JSON "):
            try:
                report = json.loads(line[len("SPIKE_STEP8_JSON "):])
            except json.JSONDecodeError:
                report = None
    marker = report.get("image_marker", "") if report else "<unparseable>"

    vram_peak = _peak_from_sampler(sampler_path)
    vram_rise = (
        vram_peak - vram_baseline
        if (vram_peak is not None and vram_baseline is not None)
        else None
    )

    entry.update({
        "total_seconds": round(elapsed, 3),
        "stop_seconds": round(stop_seconds, 3),
        "cycle_seconds": round(elapsed + stop_seconds, 3),
        "image_marker": marker,
        "pid": (report or {}).get("pid", "unknown"),
        "framework": (report or {}).get("framework", "unknown"),
        "vram_allocated_mb": (report or {}).get("vram_allocated_mb", 0),
        "weights_sha256": (report or {}).get("weights_sha256", ""),
        "weights_hash_match": (report or {}).get("weights_hash_match", True),
        "init_total_seconds": (report or {}).get("init_total_seconds", 0),
        "vram_pre_stop_mb": vram_pre_stop,
        "vram_baseline_mb": vram_baseline,
        "vram_peak_mb": vram_peak,
        "vram_rise_mb": vram_rise,
    })
    record("step8", **entry)

    if not marker.startswith(EXPECTED_MARKER[direction]):
        outcome.finding(
            f"Alt {iteration}: container answered with the wrong "
            f"identity — image_marker={marker!r}, expected prefix "
            f"{EXPECTED_MARKER[direction]!r}. The request was served "
            "by the wrong tool."
        )
    # ── VRAM gate: did it actually allocate? (the step-3 trap) ───
    if vram_rise is None:
        outcome.harness(
            f"Alt {iteration} ({direction}): the VRAM peak could not "
            "be measured (sampler or baseline missing) — the "
            "allocation was not observed for this cycle."
        )
    elif vram_rise < VRAM_RISE_MB:
        outcome.finding(
            f"Alt {iteration} ({direction}): VRAM rose only "
            f"{vram_rise} MiB (baseline {vram_baseline} -> peak "
            f"{vram_peak}); below the {VRAM_RISE_MB} MiB gate — the "
            "cycle is a no-op timing and must not be cited as "
            "container-start cost."
        )
    print(
        f"  Alt {iteration:2d}/{N} {direction:>7s}: "
        f"{entry['cycle_seconds']:.3f}s "
        f"(stop {stop_seconds:.3f}s + run {elapsed:.3f}s), "
        f"VRAM baseline {vram_baseline} -> peak {vram_peak} MiB "
        f"(rise {vram_rise}), marker={marker}"
    )
    recorder.write(block(
        f"alt {iteration} {direction} ({elapsed:.3f}s)",
        " ".join(cmd) + "\n--- stdout ---\n"
        + (result.stdout or "(none)")
        + "\n--- stderr ---\n"
        + (result.stderr or "(none)"),
    ))
    return entry


def _relaunch_holder(
    direction: str, outcome: StepOutcome, recorder: Recorder
) -> None:
    """Full mode: re-create *direction*'s holder (unmeasured).

    Runs after a completed cycle so the NEXT cycle has a live,
    VRAM-holding incumbent to tear down. Untimed by construction —
    no cycle may pay for the teardown of the holder the previous
    cycle's run itself removed.

    Args:
        direction: The tool that just ran (becomes the new holder).
        outcome: Collects a harness failure when the holder does not
            allocate (the next stop would then be a no-op).
        recorder: Records the holder launch and wait.
    """
    name = HOLDER_NAMES[direction]
    subprocess.run(
        ["podman", "rm", "-f", name], capture_output=True, timeout=60
    )
    # Idle baseline BEFORE the launch: the holder allocates on start,
    # so a post-launch "idle" reading would already include it and the
    # allocation check below would compare the holder against itself.
    baseline = _wait_idle_baseline(outcome, f"holder {name} pre-launch")
    cmd = ["podman", "run", "-d", "--name", name] + _podman_run_cmd(
        direction, HOLDER_PROG
    )[2:]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=RUN_TIMEOUT_S
        )
    except Exception as e:
        outcome.harness(
            f"holder {name} could not be launched after alt "
            f"(unmeasured): {e} — the next cycle's teardown "
            "observation would be blind."
        )
        return
    if result.returncode != 0:
        outcome.harness(
            f"holder {name} launch after alt exited {result.returncode} "
            f"(unmeasured): {(result.stderr or '')[:300]} — the next "
            "cycle's teardown observation would be blind."
        )
        return
    # Wait for the allocation so the next stop is not a no-op: a rise
    # of the gate amount above the pre-launch baseline means the
    # holder allocated.
    deadline = time.monotonic() + HOLDER_WAIT_S
    allocated = False
    while time.monotonic() < deadline:
        used = _gpu_used_or_harness(outcome, f"holder {name} wait")
        if used is not None and baseline is not None \
                and used - baseline >= VRAM_RISE_MB:
            allocated = True
            break
        time.sleep(2)
    if not allocated:
        outcome.harness(
            f"holder {name} had not allocated >= {VRAM_RISE_MB} MiB "
            f"within {HOLDER_WAIT_S:.0f}s (baseline {baseline}) — the "
            "next cycle's stop would be a no-op."
        )
    recorder.write(block(f"holder {name} (unmeasured)", "ok" if allocated
                         else "NOT ALLOCATED"))


def _print_fairness_block() -> None:
    """Print what each side of the comparison does and does not include."""
    print("")
    print("=== FAIR-COMPARISON SCOPE (read before citing these numbers) ===")
    print("STEP 5 (Ray) per-cycle latency INCLUDES: scale-to-zero RPC +")
    print("teardown of a live, VRAM-holding replica; scale-to-one RPC +")
    print("FRESH container start (image_uri: one container per replica")
    print("start); Tool.__init__ (weights read+sha256, 4096 MiB VRAM,")
    print("CUDA context); one HTTP introspect round trip through the")
    print("ingress. Nothing is split out; one wall-clock span per cycle.")
    print("STEP 8 mode=start INCLUDES: fresh podman run (container")
    print("start), Tool.__init__ equivalent (weights read+sha256, 4096")
    print("MiB VRAM, CUDA context), identity print (introspect-")
    print("equivalent), exit. EXCLUDES: Ray's scale RPCs, replica")
    print("teardown, ingress routing, the HTTP round trip.")
    print("STEP 8 mode=full ADDS, timed: `podman stop` of the other")
    print("tool's live VRAM-holding holder (SIGTERM, 10s grace). Its")
    print("limits: stop and start are serial (Ray's may overlap); the")
    print("holder is re-created fresh each cycle (Ray may keep stopped")
    print("state). full mode is a bracket, not a like-for-like.")
    print("INTERPRETATION: if step 8's P90 is ~10s where step 5's is")
    print("~100s, the slow path is Ray orchestration (a hard con). If")
    print("step 8's P90 is also ~100s — or also bimodal — the cost is")
    print("container lifecycle at this image size and our own router")
    print("would inherit nearly all of it; the Ray con dissolves.")
    print("")


def _cleanup_holders(recorder: Recorder) -> None:
    """Best-effort removal of holder containers (cleanup is not an
    observation). Records the step8_* container count afterwards so
    the run can prove it added nothing to the store's accumulation.

    Args:
        recorder: Records the cleanup and the count.
    """
    for name in HOLDER_NAMES.values():
        subprocess.run(
            ["podman", "rm", "-f", name], capture_output=True, timeout=60
        )
    try:
        result = subprocess.run(
            ["podman", "ps", "-a", "--filter", "name=step8_holder"],
            capture_output=True, text=True, timeout=30,
        )
        leftover = max(0, len(result.stdout.strip().splitlines()) - 1)
    except Exception:
        leftover = -1
    recorder.write(block("cleanup", f"step8_holder containers left: "
                                    f"{leftover}"))
    print(f"  Cleanup: step8_holder containers left: {leftover}")


def run(recorder: Recorder) -> int:
    """Run step 8's observations and return the process exit code.

    Args:
        recorder: The step's Recorder (stdout/stderr tee to the log).

    Returns:
        0 (clean), 2 (harness failure) or 3 (negative finding).
    """
    outcome = StepOutcome()

    print("=" * 60)
    print(f"STEP 8: Plain-podman alternation baseline ({N} cycles, "
          f"mode={MODE})")
    print("=" * 60)
    _print_fairness_block()

    if MODE not in ("start", "full"):
        outcome.harness(
            f"SPIKE_STEP8_MODE={MODE!r} is not 'start' or 'full' — "
            "the step cannot run."
        )
        _print_summary(outcome)
        return outcome.exit_code

    # The exact command the harness will run — printed so an operator
    # can eyeball it before a real run (verification requirement).
    print(f"  Per-cycle podman command ({IMAGES['torch']}; tf is the")
    print("  same image slot swapped):")
    printable = " ".join(_podman_run_cmd("torch", CHALLENGER_PROG))
    # The program is long; show it collapsed with its length.
    short = printable.split(' -c "', 1)
    print(f"    {short[0]} -c \"<{len(CHALLENGER_PROG.splitlines())}-line"
          " program>\"")
    recorder.write(block("podman command (full argv)", printable))

    if not _preflight(outcome, recorder):
        _print_summary(outcome)
        return outcome.exit_code

    # Pre-warm (unmeasured).
    # Step 5's alternation began with both images pulled and their
    # layers mapped (the cluster started both replicas during the
    # readiness wait). Skipping the pre-warm would charge this step's
    # first cycle with a one-off layer mapping step 5 never paid —
    # a silent unfairness against the baseline.
    if PREWARM:
        print("")
        print("Pre-warm (unmeasured): starting each image once so the")
        print("first measured cycle matches step 5's warm-store start.")
        for direction in ("torch", "tf"):
            t0 = time.monotonic()
            output = "(not run)"
            try:
                result = subprocess.run(
                    _podman_run_cmd(direction, CHALLENGER_PROG),
                    capture_output=True, text=True, timeout=RUN_TIMEOUT_S,
                    stdin=subprocess.DEVNULL,
                )
                output = (result.stdout or "") + (result.stderr or "")
                if result.returncode != 0:
                    outcome.harness(
                        f"Pre-warm {direction} exited "
                        f"{result.returncode}: "
                        f"{(result.stderr or '')[:300]} — the measured "
                        "cycles would run on a broken store."
                    )
            except Exception as e:
                outcome.harness(f"Pre-warm {direction} failed: {e}")
            print(f"  Pre-warm {direction}: {time.monotonic() - t0:.1f}s")
            recorder.write(block(f"pre-warm {direction}", output))
        if outcome.harness_failures:
            _print_summary(outcome)
            return outcome.exit_code
    else:
        print("")
        print("Pre-warm SKIPPED (SPIKE_STEP8_PREWARM=0): the first")
        print("measured cycle includes one-off layer mapping that step")
        print("5 never paid. Do not compare its min against step 5.")

    # Full mode: first holder (unmeasured setup).
    if MODE == "full":
        print("")
        print("Full mode: launching the first holder (unmeasured) so")
        print("cycle 1 has a live incumbent to tear down.")
        _relaunch_holder("tf", outcome, recorder)
        if outcome.harness_failures:
            _print_summary(outcome)
            return outcome.exit_code

    # The N alternations.
    print("")
    entries: list[dict] = []
    for i in range(N):
        direction = "torch" if i % 2 == 0 else "tf"
        entry = _run_cycle(direction, i + 1, outcome, recorder)
        entries.append(entry)
        if "error" not in entry and MODE == "full" and i + 1 < N:
            # The next cycle's incumbent is the tool that just ran.
            # Untimed setup (see _relaunch_holder's docstring).
            _relaunch_holder(direction, outcome, recorder)

    failed = [e for e in entries if "error" in e]
    completed = [e for e in entries if "error" not in e]

    # D29 error-rate line, mirroring step 5: with the default
    # tolerance of 0, failed cycles are also a finding about the
    # mechanism under test, on top of the per-cycle harness failures.
    if failed and len(failed) > MAX_ERRORS:
        outcome.finding(
            f"{len(failed)}/{N} alternation cycles failed "
            f"(tolerated: {MAX_ERRORS}) — plain-podman alternation "
            "does not complete reliably at cadence."
        )

    # Distributions (completed cycles only).
    if completed:
        st_run = _print_stats(
            f"Mode {MODE} — RUN span (fresh container start + init + "
            "identity + exit)",
            [e["total_seconds"] for e in completed],
        )
        st = st_run
        if MODE == "full":
            st = _print_stats(
                "Mode full — CYCLE span (teardown of live holder + run"
                " span)",
                [e["cycle_seconds"] for e in completed],
            ) or st_run
        print(f"\n  Failed cycles: {len(failed)} (of {N} attempted)")
        if st_run:
            record("step8", kind="stats", mode=MODE,
                   span="run", **{
                       k: (round(v, 3) if isinstance(v, float) else v)
                       for k, v in st_run.items()
                   })
        if MODE == "full" and st and st is not st_run:
            record("step8", kind="stats", mode=MODE,
                   span="cycle", **{
                       k: (round(v, 3) if isinstance(v, float) else v)
                       for k, v in st.items()
                   })
        # Per-cycle VRAM gate summary — the anti-no-op evidence.
        no_vram = [
            e for e in completed
            if e.get("vram_rise_mb") is not None
            and e["vram_rise_mb"] < VRAM_RISE_MB
        ]
        print(f"  Cycles without a >= {VRAM_RISE_MB} MiB VRAM rise: "
              f"{len(no_vram)} "
              f"(gate: {VRAM_RISE_MB} MiB; fixture allocates {VRAM_MB})")
    else:
        print("\nNo completed cycles — no distribution to report.")

    record("step8", kind="run-summary", mode=MODE, n=N,
           completed=len(completed), failed=len(failed),
           harness_failures=len(outcome.harness_failures),
           findings=len(outcome.findings))

    if MODE == "full":
        _cleanup_holders(recorder)

    # Comparison with step 5 (ledger §9Q).
    print("")
    print("=== Comparison with step 5 (ledger §9Q) ===")
    print("  Step 5: median 9.48s, P90 103.2s, max 103.6s, 20 cycles;")
    print("  40% of cycles at 99-104s (the unattributed slow path).")
    st_for_compare = None
    if completed:
        values = (
            [e["cycle_seconds"] for e in completed]
            if MODE == "full"
            else [e["total_seconds"] for e in completed]
        )
        st_for_compare = _stats(values)
    if st_for_compare and not outcome.harness_failures \
            and not outcome.findings:
        span = "cycle" if MODE == "full" else "run"
        print(f"  Step 8 (mode {MODE}, {span} span, this run): median "
              f"{st_for_compare['median']:.1f}s, P90 "
              f"{st_for_compare['p90']:.1f}s, max "
              f"{st_for_compare['max']:.1f}s.")
        if st_for_compare["p90"] < 30:
            print("  -> The slow path is NOT container lifecycle at this")
            print("     image size; it is Ray's orchestration (or its")
            print("     interaction with the runtime). A hard con.")
        else:
            print("  -> The slow path is (mostly) container lifecycle;")
            print("     our own router would inherit nearly all of it.")
        print("  NOTE: mode=start measures only the run span, so a fast")
        print("        step 8 in start mode does NOT by itself exonerate")
        print("        Ray's teardown — read mode=full for that.")
    else:
        print("  -> No valid comparison: the run is incomplete or had")
        print("     harness failures / findings; do not cite these")
        print("     numbers as an attribution.")
    print("")
    print("--- STEP 8 OBSERVATIONS COMPLETE ---")
    _print_summary(outcome)
    return outcome.exit_code


def _print_summary(outcome: StepOutcome) -> None:
    """Print the final verdict, labelling each failure kind explicitly.

    Args:
        outcome: The collected harness failures and findings.
    """
    if outcome.harness_failures:
        print("")
        print("STEP 8 RESULT: HARNESS FAILURE — exit code 2")
        print("A required observation could not be made; the environment,")
        print("not the experiment, is at fault. The findings from this run")
        print("are incomplete and must not be treated as a pass:")
        for i, msg in enumerate(outcome.harness_failures, 1):
            print(f"  {i}. {msg}")
    if outcome.findings:
        print("")
        print("STEP 8 RESULT: NEGATIVE FINDING(S) — exit code 3")
        print("The observations were made but answer the step's question")
        print("negatively. Recorded findings:")
        for i, msg in enumerate(outcome.findings, 1):
            print(f"  {i}. {msg}")
    if not outcome.harness_failures and not outcome.findings:
        print("")
        print("STEP 8 RESULT: all required observations made; no negative")
        print("findings — exit code 0")


def _gpu_guard() -> str | None:
    """Check host preconditions up front (labelled verdict, no silent exit).

    Returns:
        A problem description to report as a harness failure (exit 2),
        or None when the host looks like a GPU box.
    """
    if shutil.which("podman") is None:
        return (
            "podman not found on PATH — the step-8 baseline cannot be "
            "observed. Run on the GPU host."
        )
    if shutil.which("nvidia-smi") is None:
        return (
            "nvidia-smi not found on PATH — the VRAM observations "
            "cannot be made. Run on the GPU host."
        )
    return None


if __name__ == "__main__":
    _problem = _gpu_guard()
    if _problem:
        print(f"\n[HARNESS FAILURE] {_problem}")
        print("  The observation could not be made — the environment, not")
        print("  the experiment, is at fault. Exit code will be 2.")
        print("")
        print("STEP 8 RESULT: HARNESS FAILURE — exit code 2")
        sys.exit(2)
    _recorder = Recorder("step8")
    try:
        _exit_code = run(_recorder)
    except Exception:
        import traceback

        print("\n" + "=" * 60)
        print("STEP 8: UNEXPECTED ERROR — recording and exiting")
        print("=" * 60)
        traceback.print_exc()
        print("Step failed with an unexpected error; review "
              "results/raw/step8-*.log")
        _recorder.close()
        sys.exit(1)
    _recorder.close()
    sys.exit(_exit_code)

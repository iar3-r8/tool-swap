"""Step 9 — Phase timing of the alternation cycle (D47).

Step 5 (ledger §9Q) measured the alternation cycle as ONE wall-clock
span: bimodal, median 9.5s, P90 103.2s, ~12 cycles at 6-10s and ~8 at
99-104s. Step 8 (§9T) proved the ~95s excess is Ray's, not container
lifecycle. But the MECHANISM is unexplained: the step-5 config sets
``external_scaler_enabled: true`` with NO ``autoscaling_config``, so
Ray's autoscaler — the step 3 mechanism — was never in the loop (D46).
This step is the experiment that finds WHERE the ~95s goes.

Method
------
A step-5-style alternation (same config shape, same two apps, same
explicit ``scale_deployment`` calls) that timestamps the phases WITHIN
each cycle, each as an offset from cycle start, by polling
``GET /api/serve/applications/`` at a fixed interval (default 0.5s):

    t0  cycle start (before the scale-to-zero)
    p1  scale-to-zero (incumbent) sent -> response received
    p2  scale-to-one (challenger) sent -> response received
    p3  challenger's target_num_replicas first observed as 1
    p4  challenger's replica first appears in replicas[] (state noted)
    p5  replica first observed STARTING (state observed)
    p6  replica first observed RUNNING (state observed)
    p7  first successful introspect from the challenger

Phase durations (each the span between two adjacent boundaries, so
they sum to the total):
    scale_down_rpc        = p1
    scale_up_rpc          = p2 - p1
    decision_lag          = p3 - p2   (scale accepted -> target applied)
    replica_materialize   = p4 - p3   (target applied -> replica exists)
    starting_to_running   = p6 - p5
    serving               = p7 - p6

Container correlation (scripts/lib/podman.py shape)
----------------------------------------------------
For each cycle the poller also records when the newest container
matching the challenger's image APPEARS in ``podman ps -a`` (with its
CREATED field and observed status). That answers the question that is
the point of the whole experiment: "Ray took ~95s to *start* the
container" (container appears LATE, shortly before p4) versus "the
container started promptly and Ray took ~95s to *notice*" (container
appears early, but p4/p6 land ~95s later). Ray's image_uri plugin
starts containers without --name, so per-cycle identity is by
recency: the newest matching container is this cycle's (the
incumbent's teardown removes its container, keeping the match set
small).

Gaps this CANNOT see into (stated prominently in the report)
------------------------------------------------------------
Everything inside Ray's own processes is invisible here — GCS
registration internals, controller decisions, runtime_env plugin work
inside the raylet. It is only visible as the GAP between two
observable boundaries we do not straddle:

  * G1: p2 -> p3 (scale response -> target observed): a controller
    loop tick / GCS write. Looking inside: the serve controller logs
    (results/raylogs/ and the session logs' serve/ directory,
    dashboard_ServeHead.log).
  * G2: p3 -> p4 (target -> replica appears): actor creation,
    scheduling, and the runtime_env container launch (the ``podman
    run`` the image_uri plugin issues). The container-appearance
    timestamp splits G2 into "before the container even exists"
    (scheduling/actor creation) and "after the container exists"
    (worker start, Ray noticing it). Looking inside further: the
    session log dir's ``runtime_env_setup-*.log`` and the replica log
    ``serve/replica_step9_*_*.log`` (both harvested per cycle below).
  * G3: p5 -> p6 (STARTING -> RUNNING): the replica's Tool.__init__
    (weights read, VRAM allocation) and Ray's readiness probe. The
    replica log shows what the process itself is doing in this span.

If the ~95s lands in a gap rather than a phase we can name, the
report says exactly which gap and where to look. Note also: if
STARTING lasts under one poll interval, p5 is never observed and
starting_to_running_s is unresolvable for that cycle — the state was
missed, not absent (recorded as <none> in the table).

Log harvesting (best effort)
----------------------------
Ray writes per-replica and per-runtime-env-setup logs under its
session dir (``/tmp/ray/session_latest/logs/``; confirmed present
from earlier spike runs: ``serve/replica_<app>_<dep>_*.log`` and
``runtime_env_setup-*.log``). After each cycle this step copies the
tail of the replica log(s) for this cycle and the lines of the
runtime_env setup logs that changed since the previous cycle into the
recorder. A long runtime_env setup that correlates with a slow cycle
shows there directly. The harvest is best effort: if the session dir
is absent (different host layout) the step continues and records so.

Cycle count and resolution
--------------------------
Default N=10 (5 alternations each way) keeps a run near 10 minutes
(10 x ~100s slow + deploy/readiness ~2-4 min): we need the phase
ATTRIBUTION — the bimodality is the signal — not a tight
distribution. 0.5s polling against a ~100s window is ~200 polls; a
boundary is located to within half a poll interval (~0.25s), ~2% of
a 10s phase and ~0.25% of a 100s gap — sufficient for attribution.
The per-poll ``podman ps -a --format json`` is the costliest poll
operation (tens of ms over ~110+ orphaned containers); it does not
perturb the cycle measurably.

Exit status (D29)
-----------------
    0  Every required observation was made: all N cycles completed
       with all their phases resolved. Finding the ~95s is a SUCCESS
       for this diagnostic step — its question is "where does it
       go", not "is it fast".
    1  Unexpected internal error (traceback printed).
    2  Harness/environment failure — an observation could NOT be
       made: the config could not be deployed, a scale call failed,
       the dashboard was unreachable, or a cycle's phases could not
       be resolved (e.g. the replica never appeared). Such a cycle
       is a harness failure FOR THAT CYCLE, not a finding.
    3  Negative finding — the observations were made and answer the
       step's question negatively: no bimodality exists this run
       (no slow cycles to attribute) — the step 5 slow mode did not
       reproduce, so no attribution is possible.

The step's verdicts are printed explicitly, as in steps 5/6/8.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
sys.path.insert(0, os.path.join(_SCRIPTS_DIR, "lib"))

from recorder import Recorder, block, record
from serve_api import (
    apply_config,
    post_introspect,
    scale_deployment,
    serve_status,
)
from step1_verify import StepOutcome, _wait_for_running

SERVE_BASE = os.environ.get("SERVE_BASE_URL", "http://localhost:8000")

# A copy of step 5's setup with renamed applications (see
# apps/step9_config.yaml's header for why the names differ).
STEP9_CONFIG = os.environ.get(
    "SPIKE_STEP9_CONFIG", "apps/step9_config.yaml"
)
APPS = {
    "torch": {
        "app": "step9_torch", "dep": "ToolTorch",
        "url": f"{SERVE_BASE}/tool_torch",
    },
    "tf": {
        "app": "step9_tf", "dep": "ToolTf", "url": f"{SERVE_BASE}/tool_tf",
    },
}
EXPECTED_MARKER: dict[str, str] = {"torch": "tool_torch", "tf": "tool_tf"}
IMAGE_BY_TOOL: dict[str, str] = {
    "torch": "tool_torch:spike", "tf": "tool_tf:spike",
}

# ── Knobs (env-overridable) ───────────────────────────────────────
N = int(os.environ.get("SPIKE_STEP9_N", "10"))
POLL_S = float(os.environ.get("SPIKE_STEP9_POLL_S", "0.5"))
# Per-cycle budget for the state boundaries p3..p6 (after the scale
# RPCs). 180s is well above step 5's observed max (~104s) and keeps
# a pathological run finite.
CYCLE_BUDGET_S = float(os.environ.get("SPIKE_STEP9_CYCLE_BUDGET_S", "180"))
# Fast/slow split for the grouped report (between step 5's fast mode
# ~6-10s and its slow mode ~99-104s).
FAST_SLOW_SPLIT_S = float(os.environ.get("SPIKE_STEP9_FAST_SLOW_SPLIT_S", "30"))
# Introspect timeout per cycle (a slow cycle must still be able to
# answer; step 5 used 120).
PROBE_TIMEOUT_S = float(os.environ.get("SPIKE_STEP9_PROBE_TIMEOUT_S", "120"))
# A slow group is only a slow group when at least this many cycles
# fall above the split (fewer is noise, not a mode).
MIN_SLOW_CYCLES = int(os.environ.get("SPIKE_STEP9_MIN_SLOW_CYCLES", "2"))

# The serve_status / scale / probe / podman entry points. Module-level
# names so a test can stub exactly these (the throwaway verification
# stubs serve_status, the scale calls and podman ps).
_status_fn: Callable[[], dict] = serve_status
scale_fn: Callable[[str, str, int], dict] = scale_deployment
probe_fn: Callable[..., dict] = post_introspect


def _podman_ps_all_json() -> list[dict]:
    """`podman ps -a --format json` as a list of container dicts.

    One line per container (podman 4.x) — the same shape the toolkit
    parses in scripts/lib/podman.py, which is not used directly so a
    test can stub the call site.
    """
    result = subprocess.run(
        ["podman", "ps", "-a", "--format", "json"],
        capture_output=True, text=True, timeout=10,
    )
    containers: list[dict] = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            containers.append(json.loads(line))
        except json.JSONDecodeError:
            # A non-JSON line (a warning) must not break the poller;
            # the container snapshot is correlation evidence, and a
            # partial snapshot is still evidence.
            continue
    return containers


podman_fn: Callable[[], list[dict]] = _podman_ps_all_json

# The six phase durations, in boundary order (see module docstring).
PHASES = (
    "scale_down_rpc_s",
    "scale_up_rpc_s",
    "decision_lag_s",
    "replica_materialize_s",
    "starting_to_running_s",
    "serving_s",
)


class Cycle:
    """One alternation cycle's observable boundaries and its verdict."""

    def __init__(self, iteration: int, direction: str) -> None:
        self.iteration = iteration
        self.direction = direction
        self.other = "tf" if direction == "torch" else "torch"
        # Wall-clock (time.time()) at t0 — used only to filter the
        # log harvest by mtime, which is wall-clock, not monotonic.
        self.t0_wall: float | None = None
        # Boundaries, seconds offset from cycle start; None = not yet
        # observed (a boundary still None at report time means the
        # cycle's phases could not be resolved — a harness failure
        # for that cycle, not a finding).
        self.t0 = 0.0
        self.p1: float | None = None  # scale-down RPC returned
        self.p2: float | None = None  # scale-up RPC returned
        self.p3: float | None = None  # target_num_replicas == 1 observed
        self.p4: float | None = None  # replica appears in replicas[]
        self.p4_state: str | None = None
        self.p5: float | None = None  # replica observed STARTING
        self.p6: float | None = None  # replica observed RUNNING
        self.p7: float | None = None  # first successful introspect
        self.total: float | None = None
        self.error: str | None = None
        # Container correlation (challenger's image).
        self.container_first_seen: float | None = None
        self.container_created: str | None = None
        self.container_status: str | None = None
        # Replica log / runtime_env setup harvest (filled post-cycle).
        self.replica_log_tail: str | None = None
        self.runtime_env_lines: str | None = None

    def phases(self) -> dict[str, float | None]:
        """The six phase durations (each None until resolvable)."""
        def span(a: float | None, b: float | None) -> float | None:
            return round(b - a, 3) if a is not None and b is not None \
                else None

        return {
            "scale_down_rpc_s": span(self.t0, self.p1),
            "scale_up_rpc_s": span(self.p1, self.p2),
            "decision_lag_s": span(self.p2, self.p3),
            "replica_materialize_s": span(self.p3, self.p4),
            "starting_to_running_s": span(self.p5, self.p6),
            "serving_s": span(self.p6, self.p7),
        }

    def missing(self) -> list[str]:
        """Boundaries still None — the phases that cannot be resolved."""
        names = {
            "p1 (scale-down RPC)": self.p1,
            "p2 (scale-up RPC)": self.p2,
            "p3 (target==1)": self.p3,
            "p4 (replica appears)": self.p4,
            "p5 (STARTING)": self.p5,
            "p6 (RUNNING)": self.p6,
            "p7 (first response)": self.p7,
        }
        return [n for n, v in names.items() if v is None]

    def entry(self) -> dict:
        """The metric record written to results/metrics/step9.jsonl."""
        out: dict[str, Any] = {
            "iteration": self.iteration,
            "direction": self.direction,
            "poll_s": POLL_S,
            "replica_state_at_p4": self.p4_state,
        }
        for name in ("p1", "p2", "p3", "p4", "p5", "p6", "p7", "total"):
            value = getattr(self, name)
            if value is not None:
                out[name + "_s"] = round(value, 3)
        if self.container_first_seen is not None:
            out["container_first_seen_s"] = \
                round(self.container_first_seen, 3)
            out["container_created"] = self.container_created
            out["container_status"] = self.container_status
        out.update(self.phases())
        if self.error:
            out["error"] = self.error
        return out


def _newest_matching_container(
    containers: list[dict], image: str
) -> dict | None:
    """The newest container of *image* (by CreatedAt, then StartedAt).

    Ray's image_uri plugin starts containers WITHOUT a --name, so the
    only per-cycle identity is recency (see the module docstring).
    """
    matches = [c for c in containers if image in str(c.get("Image", ""))]
    if not matches:
        return None
    return max(
        matches,
        key=lambda c: (str(c.get("CreatedAt", "")),
                       str(c.get("StartedAt", ""))),
    )


def _dep_of(status: dict, app: str, dep: str) -> dict:
    """One deployment's details from a serve_status() payload (or {})."""
    apps = status.get("applications") or {}
    app_obj = apps.get(app) or {}
    if not isinstance(app_obj, dict):
        return {}
    dep_obj = (app_obj.get("deployments") or {}).get(dep) or {}
    return dep_obj if isinstance(dep_obj, dict) else {}


def run_cycle(
    cycle: Cycle,
    outcome: StepOutcome,
    recorder: Recorder,
    t_cycle_start: float,
) -> None:
    """Drive one alternation cycle and fill *cycle*'s boundaries.

    Args:
        cycle: The cycle to fill (boundaries stay None until observed).
        outcome: Collects a harness failure when a phase cannot be
            resolved (D29: a cycle whose phases cannot be resolved is
            a harness failure FOR THAT CYCLE, not a finding).
        recorder: Records the raw per-cycle evidence.
        t_cycle_start: time.monotonic() at t0, so the caller keeps the
            clock (and a test can drive it).
    """
    cycle.t0_wall = time.time()
    target = APPS[cycle.direction]
    other = APPS[cycle.other]
    image = IMAGE_BY_TOOL[cycle.direction]
    label = f"Cycle {cycle.iteration} ({cycle.direction})"

    # p1: scale the incumbent to zero (timed request -> response).
    try:
        scale_fn(other["app"], other["dep"], 0)
        cycle.p1 = time.monotonic() - t_cycle_start
    except Exception as e:
        cycle.error = f"scale-to-zero failed: {e}"
        outcome.harness(f"{label}: {cycle.error}")
        return

    # p2: scale the challenger to one (timed request -> response).
    try:
        scale_fn(target["app"], target["dep"], 1)
        cycle.p2 = time.monotonic() - t_cycle_start
    except Exception as e:
        cycle.error = f"scale-to-one failed: {e}"
        outcome.harness(f"{label}: {cycle.error}")
        return

    # Poll for p3..p7 within the per-cycle budget. Each boundary is
    # taken at the first poll at which its condition holds, so a
    # boundary is located to within POLL_S/2 (stated in the report).
    deadline = t_cycle_start + CYCLE_BUDGET_S
    while time.monotonic() < deadline:
        try:
            status = _status_fn()
        except Exception:
            time.sleep(POLL_S)
            continue
        # One status call per poll serves p3 (target) and p4/p5/p6
        # (replica list) together: two calls per poll would double
        # the dashboard load for no resolution gain.
        if cycle.p3 is None and _dep_target_one(status, target):
            cycle.p3 = time.monotonic() - t_cycle_start
        dep = _dep_of(status, target["app"], target["dep"])
        state = None
        for replica in dep.get("replicas") or []:
            if isinstance(replica, dict):
                state = str(replica.get("state"))
                break
        if state is not None:
            if cycle.p4 is None:
                cycle.p4 = time.monotonic() - t_cycle_start
                cycle.p4_state = state
            if cycle.p5 is None and state == "STARTING":
                cycle.p5 = time.monotonic() - t_cycle_start
            if cycle.p6 is None and state == "RUNNING":
                cycle.p6 = time.monotonic() - t_cycle_start
        # Container correlation: the newest matching container and,
        # on its first appearance, its CREATED and status at that
        # moment (the status is then tracked to its latest reading).
        try:
            newest = _newest_matching_container(podman_fn(), image)
            if newest is not None:
                if cycle.container_first_seen is None:
                    cycle.container_first_seen = \
                        time.monotonic() - t_cycle_start
                    cycle.container_created = \
                        str(newest.get("CreatedAt", ""))
                cycle.container_status = str(newest.get("Status", ""))
        except Exception:
            # A failed podman snapshot must not break the cycle: it
            # only loses the container correlation for this poll.
            pass
        if cycle.p6 is not None:
            # p6 (RUNNING) is the last state boundary; only the probe
            # (p7) remains — send it now (it also validates the
            # answer's identity, as step 5 did).
            try:
                resp = probe_fn(target["url"], timeout=PROBE_TIMEOUT_S)
                cycle.p7 = time.monotonic() - t_cycle_start
                marker = str(resp.get("image_marker", ""))
                if not marker.startswith(EXPECTED_MARKER[cycle.direction]):
                    outcome.finding(
                        f"Cycle {cycle.iteration}: probe answered with "
                        f"the wrong identity — image_marker={marker!r}, "
                        f"expected prefix "
                        f"{EXPECTED_MARKER[cycle.direction]!r}."
                    )
            except Exception as e:
                cycle.error = f"first introspect failed: {e}"
                outcome.harness(f"{label}: {cycle.error}")
            break
        time.sleep(POLL_S)
    else:
        # Budget exhausted without RUNNING: the phases cannot be
        # resolved — harness failure for this cycle (D29).
        cycle.error = (
            f"replica never reached RUNNING within "
            f"{CYCLE_BUDGET_S:.0f}s (unresolved: "
            f"{', '.join(cycle.missing())})"
        )
        outcome.harness(f"{label}: {cycle.error}")

    if cycle.p7 is not None:
        cycle.total = cycle.p7
    recorder.write(block(
        f"{label} boundaries", json.dumps(cycle.entry(), indent=2),
    ))
    _harvest_ray_logs(cycle, label, recorder)


def _dep_target_one(status: dict, target: dict) -> bool:
    """Whether *target*'s deployment reports target_num_replicas == 1."""
    dep = _dep_of(status, target["app"], target["dep"])
    value = dep.get("target_num_replicas")
    return isinstance(value, int) and value == 1


# ── Ray log harvesting (best effort) ───────────────────────────────

def _session_log_dir() -> str | None:
    """The current Ray session's logs dir, if resolvable."""
    for base in ("/tmp/ray", os.path.join(os.path.expanduser("~"), ".ray")):
        latest = os.path.join(base, "session_latest")
        if os.path.isdir(latest):
            return os.path.join(latest, "logs")
    return None


def _tail(text: str, limit: int = 40) -> str:
    """The last *limit* lines of *text* (keep the evidence small)."""
    lines = text.strip().splitlines()
    return "\n".join(lines[-limit:]) if lines else "(empty)"


def _harvest_ray_logs(cycle: Cycle, label: str, recorder: Recorder) -> None:
    """Copy this cycle's replica log and new runtime_env setup lines.

    The replica log is the replica's own stdout/stderr (what it did
    during STARTING->RUNNING); the runtime_env setup log is where the
    container launch (and its duration) is logged by Ray. Both live
    under the session's logs dir (confirmed present from earlier
    spike runs). Best effort: any absence is recorded and the step
    continues — the harvest is corroborating evidence, not a required
    observation.
    """
    log_dir = _session_log_dir()
    if log_dir is None:
        recorder.write(block(
            f"{label} log harvest",
            "session log dir not found (/tmp/ray/session_latest or "
            "~/.ray/session_latest) — log harvest skipped.",
        ))
        return
    t0_wall = cycle.t0_wall or time.time()
    target = APPS[cycle.direction]
    serve_dir = os.path.join(log_dir, "serve")
    cycle_logs: list[str] = []
    prefix = f"replica_{target['app']}_{target['dep']}_"
    if os.path.isdir(serve_dir):
        for name in sorted(os.listdir(serve_dir)):
            if name.lower().startswith(prefix.lower()) \
                    and name.endswith(".log"):
                path = os.path.join(serve_dir, name)
                # The per-replica file is per replica lifetime, so
                # mtime >= cycle start filters to this cycle's.
                try:
                    if os.path.getmtime(path) < t0_wall:
                        continue
                    with open(path, encoding="utf-8",
                              errors="replace") as fh:
                        cycle_logs.append(
                            f"--- {name} ---\n{_tail(fh.read())}"
                        )
                except OSError as e:
                    cycle_logs.append(f"--- {name} ---\n<unreadable: {e}>")
    setup_lines: list[str] = []
    for name in sorted(os.listdir(log_dir)):
        if name.startswith("runtime_env_setup-") and name.endswith(".log"):
            path = os.path.join(log_dir, name)
            try:
                # -5s slack: the setup write lands just before t0.
                if os.path.getmtime(path) < t0_wall - 5:
                    continue
                with open(path, encoding="utf-8", errors="replace") as fh:
                    setup_lines.append(
                        f"--- {name} ---\n{_tail(fh.read())}"
                    )
            except OSError:
                continue
    cycle.replica_log_tail = "\n".join(cycle_logs) or None
    cycle.runtime_env_lines = "\n".join(setup_lines) or None
    recorder.write(block(
        f"{label} log harvest",
        (cycle.replica_log_tail or "<no replica log for this cycle>")
        + "\n\n"
        + (cycle.runtime_env_lines
           or "<no runtime_env setup lines since cycle start>"),
    ))


# ── Reporting ─────────────────────────────────────────────────────

def _stats(values: list[float]) -> dict[str, float]:
    """min/median/P90/max/count with step 5's exact P90 convention."""
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "median": ordered[len(ordered) // 2],
        "p90": ordered[min(int(len(ordered) * 0.9), len(ordered) - 1)],
        "max": ordered[-1],
        "count": len(ordered),
    }


def _fmt(v: float | None) -> str:
    """Format a boundary offset for the per-cycle table."""
    return f"{v:8.3f}" if v is not None else "   <none>"


def _print_cycle_table(cycles: list[Cycle]) -> None:
    """The per-cycle table: every boundary as an offset from t0."""
    print("")
    print("=== Per-cycle boundaries (s offset from cycle start) ===")
    print(
        f"{'cyc':>3} {'dir':>5} | {'p1 rpc':>8} {'p2 rpc':>8} "
        f"{'p3 tgt=1':>9} {'p4 appear':>10} {'p5 START':>9} "
        f"{'p6 RUN':>7} {'p7 http':>8} {'total':>8} | container first seen"
    )
    for c in cycles:
        print(
            f"{c.iteration:>3} {c.direction:>5} | {_fmt(c.p1)} {_fmt(c.p2)} "
            f"{_fmt(c.p3)} {_fmt(c.p4)} {_fmt(c.p5)} {_fmt(c.p6)} "
            f"{_fmt(c.p7)} {_fmt(c.total)} | "
            f"{_fmt(c.container_first_seen)}"
            + (f" (created {c.container_created})"
               if c.container_created else "")
        )
        if c.p4_state:
            print(f"      replica state at first appearance: {c.p4_state}")
        if c.error:
            print(f"      ! {c.error}")


def _print_grouped_summary(cycles: list[Cycle]) -> None:
    """Per-phase statistics split into fast (< split) and slow (>=).

    The bimodality is the signal: if one phase is ~5s in fast cycles
    and ~95s in slow ones, that phase is the answer.
    """
    completed = [c for c in cycles if c.total is not None]
    fast = [c for c in completed if c.total < FAST_SLOW_SPLIT_S]
    slow = [c for c in completed if c.total >= FAST_SLOW_SPLIT_S]
    print("")
    print(f"=== Per-phase statistics (split at {FAST_SLOW_SPLIT_S:.0f}s "
          f"total: {len(fast)} fast, {len(slow)} slow) ===")
    for group_name, group in (("FAST", fast), ("SLOW", slow)):
        if not group:
            print(f"\n{group_name} group: no cycles.")
            continue
        print(f"\n{group_name} group ({len(group)} cycles):")
        medians: dict[str, float | None] = {}
        for phase in PHASES:
            values = [
                g.phases()[phase] for g in group
                if g.phases()[phase] is not None
            ]
            if not values:
                print(f"  {phase:>26s}: no completed observations")
                medians[phase] = None
                continue
            st = _stats(values)
            medians[phase] = round(st["median"], 3)
            print(
                f"  {phase:>26s}: min {st['min']:8.3f}  "
                f"median {st['median']:8.3f}  P90 {st['p90']:8.3f}  "
                f"max {st['max']:8.3f}"
            )
        record("step9", kind="group-stats", group=group_name,
               n=len(group), **medians)


def _attribute(cycles: list[Cycle]) -> str | None:
    """Name the phase that carries the slow group's excess, if any.

    The slow group's total is ~the sum of its phases; the answer is
    the phase whose SLOW median is much larger than its FAST median
    (>= 3x and >= 20s above — the ~95s excess has to be found in ONE
    phase; a diffuse 10s-per-phase is named as such instead).
    """
    completed = [c for c in cycles if c.total is not None]
    fast = [c for c in completed if c.total < FAST_SLOW_SPLIT_S]
    slow_c = [c for c in completed if c.total >= FAST_SLOW_SPLIT_S]
    if not slow_c or not fast:
        return None
    candidates: list[tuple[str, float, float]] = []
    for phase in PHASES:
        f_vals = [g.phases()[phase] for g in fast
                  if g.phases()[phase] is not None]
        s_vals = [g.phases()[phase] for g in slow_c
                  if g.phases()[phase] is not None]
        if f_vals and s_vals:
            candidates.append(
                (phase, _stats(f_vals)["median"], _stats(s_vals)["median"])
            )
    big = [
        (p, f, s) for p, f, s in candidates if s >= max(3.0 * f, f + 20.0)
    ]
    if not big:
        return (
            "no single phase carries the slow mode — the excess is "
            "diffuse across phases (or sits in a gap between our "
            "boundaries); read the per-cycle table and the gap notes"
        )
    big.sort(key=lambda t: t[2] - t[1], reverse=True)
    phase, f_med, s_med = big[0]
    return (
        f"{phase}: median {f_med:.1f}s in fast cycles vs "
        f"{s_med:.1f}s in slow cycles"
    )


def _print_gaps_and_blind_spots() -> None:
    """State prominently what this step cannot see into."""
    print("")
    print("=== WHAT THIS STEP CANNOT SEE INTO (read before interpreting) ===")
    print("Everything inside Ray's own processes is invisible here. It is")
    print("visible only as the gap between two boundaries we do not")
    print("straddle, plus the container-appearance timestamp:")
    print("  G1 (p2 -> p3, scale response -> target_num_replicas==1):")
    print("     the controller loop / GCS write. Inside: the serve")
    print("     controller logs (results/raylogs/ray-*.log, session")
    print("     logs/serve/controller_*.log, dashboard_ServeHead.log).")
    print("  G2 (p3 -> p4, target -> replica appears in any state):")
    print("     actor creation + scheduling + the runtime_env container")
    print("     launch. The container's first-seen timestamp splits G2:")
    print("     before the container exists = scheduling/actor creation;")
    print("     after = worker start and Ray noticing it. Inside further:")
    print("     logs/runtime_env_setup-*.log (container launch + pull)")
    print("     and logs/serve/replica_step9_*_*.log (replica stdout).")
    print("  G3 (p5 -> p6, STARTING -> RUNNING): Tool.__init__ (weights")
    print("     read, 4 GiB VRAM) + Ray's readiness probe. Inside: the")
    print("     replica log (harvested per cycle).")
    print("If the ~95s lands in a gap, the per-cycle table names the")
    print("gap (the two boundary offsets around it) and these are the")
    print("files to read. If STARTING lasts under one poll interval,")
    print("p5 is never observed — the state was missed, not absent.")
    print("")
    print("Resolution: a boundary is located to within POLL_S/2 (half")
    print(f"the {POLL_S}s poll interval). Against a ~100s window that is")
    print("~200 polls; ~0.25s is ~2% of a 10s phase and ~0.25% of a")
    print("100s gap — sufficient for phase attribution, not for")
    print("sub-second phase engineering.")


# ── Step entry ────────────────────────────────────────────────────

def run(recorder: Recorder) -> int:
    """Run step 9's observations and return the process exit code.

    Args:
        recorder: The step's Recorder (stdout/stderr tee to the log).

    Returns:
        0 (clean — the phases were resolved and the slow phase, if
        any, is named), 2 (harness failure) or 3 (negative finding —
        e.g. no bimodality to attribute).
    """
    outcome = StepOutcome()

    print("=" * 60)
    print(f"STEP 9: Phase timing of the alternation cycle ({N} cycles)")
    print("=" * 60)
    print("Same setup as step 5 (external_scaler_enabled, no")
    print("autoscaling_config, container-key runtime_env, the same two")
    print("apps), instrumented with per-cycle phase boundaries at")
    print(f"{POLL_S}s polling. The autoscaler is NOT in the loop (D46) —")
    print("this step finds where the ~95s goes; it does not assume.")

    # Deploy the step 9 config (a deploy failure = harness, D29).
    deploy_ok = False
    try:
        result = apply_config(STEP9_CONFIG)
        recorder.write(block("Step 9 deploy",
                             result.stdout + result.stderr))
        print(f"Deploy exit code: {result.returncode}")
        if result.returncode == 0:
            deploy_ok = True
        else:
            outcome.harness(
                f"`serve deploy` of {STEP9_CONFIG} exited "
                f"{result.returncode} — the cycles cannot be observed."
            )
    except Exception as e:
        recorder.write(block("Step 9 deploy error", str(e)))
        outcome.harness(f"Could not invoke `serve deploy`: {e}")

    if deploy_ok:
        _wait_for_running(recorder, outcome)
        try:
            status = serve_status()
            recorder.write(block(
                "serve status after deploy", json.dumps(status, indent=2),
            ))
        except Exception as e:
            outcome.harness(
                f"serve status unreachable after deploy: {e} — the "
                "pre-alternation status observation could not be made."
            )

    cycles: list[Cycle] = []
    for i in range(N):
        if not deploy_ok:
            print(f"  Cycle {i+1:2d}/{N}: SKIPPED (config not deployed)")
            continue
        direction = "torch" if i % 2 == 0 else "tf"
        cycle = Cycle(i + 1, direction)
        run_cycle(cycle, outcome, recorder, time.monotonic())
        cycles.append(cycle)
        record("step9", **cycle.entry())
        phases = cycle.phases()
        total = f"{cycle.total:.3f}" if cycle.total is not None \
            else "UNRESOLVED"
        print(f"  Cycle {cycle.iteration:2d}/{N} {direction:>5}: "
              f"{total}s  (down {phases['scale_down_rpc_s']}, "
              f"up {phases['scale_up_rpc_s']}, "
              f"decision {phases['decision_lag_s']}, "
              f"materialize {phases['replica_materialize_s']}, "
              f"S->R {phases['starting_to_running_s']}, "
              f"http {phases['serving_s']})")

    # Best-effort cleanup (not an observation): both deployments to 0.
    for name in ("torch", "tf"):
        try:
            scale_deployment(APPS[name]["app"], APPS[name]["dep"], 0)
        except Exception:
            pass

    # ── Report ──────────────────────────────────────────────────
    _print_gaps_and_blind_spots()
    _print_cycle_table(cycles)
    _print_grouped_summary(cycles)
    completed = [c for c in cycles if c.total is not None]

    # ── Verdict (D29) ──────────────────────────────────────────
    # A diagnostic step's success is a RESOLVED attribution. The
    # negative finding (exit 3) is "no bimodality to attribute": the
    # step 5 slow mode did not reproduce, so no phase can be named.
    if not completed:
        outcome.harness(
            f"{len(cycles)}/{N} cycles could not be resolved — "
            "the phase attribution cannot be made at all."
        )
    else:
        slow = [c for c in completed if c.total >= FAST_SLOW_SPLIT_S]
        fast = [c for c in completed if c.total < FAST_SLOW_SPLIT_S]
        attribution = _attribute(cycles)
        print("")
        print("=== ATTRIBUTION ===")
        if slow and len(slow) >= MIN_SLOW_CYCLES and fast:
            print(f"  {len(slow)} slow (>= {FAST_SLOW_SPLIT_S:.0f}s) and "
                  f"{len(fast)} fast (< {FAST_SLOW_SPLIT_S:.0f}s) "
                  "cycles — the step 5 bimodality reproduced.")
            print(f"  The slow group's excess is carried by: {attribution}")
        elif slow:
            print(f"  Only {len(slow)} slow cycle(s) — below "
                  f"MIN_SLOW_CYCLES={MIN_SLOW_CYCLES}; the slow mode is "
                  "not established this run. Attribution: "
                  f"{attribution or 'n/a (no fast/slow contrast)'}")
        else:
            outcome.finding(
                f"No cycle reached {FAST_SLOW_SPLIT_S:.0f}s this run "
                f"(max total {max(c.total for c in completed):.1f}s) — "
                "the step 5 slow mode did not reproduce, so no phase "
                "carries an attribution; re-run before concluding the "
                "~95s is gone."
            )
    _print_summary(outcome)
    return outcome.exit_code


def _print_summary(outcome: StepOutcome) -> None:
    """Print the final verdict, labelling each failure kind explicitly.

    Args:
        outcome: The collected harness failures and findings.
    """
    if outcome.harness_failures:
        print("")
        print("STEP 9 RESULT: HARNESS FAILURE — exit code 2")
        print("A required observation could not be made (a cycle's")
        print("phases could not be resolved, a scale call failed, or")
        print("the dashboard was unreachable); the environment, not")
        print("the experiment, is at fault. The attribution from this")
        print("run is incomplete and must not be treated as a pass:")
        for i, msg in enumerate(outcome.harness_failures, 1):
            print(f"  {i}. {msg}")
    if outcome.findings:
        print("")
        print("STEP 9 RESULT: NEGATIVE FINDING(S) — exit code 3")
        print("The observations were made but answer the step's")
        print("question negatively (no bimodality to attribute).")
        print("Recorded findings:")
        for i, msg in enumerate(outcome.findings, 1):
            print(f"  {i}. {msg}")
    if not outcome.harness_failures and not outcome.findings:
        print("")
        print("STEP 9 RESULT: all phases resolved — exit code 0")
        print("The per-cycle table and the grouped summary above are")
        print("the step's answer: the named phase (or gap) is where")
        print("the ~95s goes.")


def _gpu_guard() -> str | None:
    """Check the host preconditions (D29: labelled verdict, no silent exit).

    Returns:
        A problem description to report as a harness failure (exit 2:
        the container correlation this step records could not be
        made), or None when the host preconditions hold.
    """
    if shutil.which("podman") is None:
        return (
            "podman not found on PATH — the container correlation "
            "cannot be made. Step 9 requires the container runtime. "
            "Run on the DGX host."
        )
    return None


if __name__ == "__main__":
    _problem = _gpu_guard()
    if _problem:
        print(f"\n[HARNESS FAILURE] {_problem}")
        print("  The observation could not be made — the environment, not")
        print("  the experiment, is at fault. Exit code will be 2.")
        print("")
        print("STEP 9 RESULT: HARNESS FAILURE — exit code 2")
        sys.exit(2)
    _recorder = Recorder("step9")
    try:
        _exit_code = run(_recorder)
    except Exception:
        import traceback

        print("\n" + "=" * 60)
        print("STEP 9: UNEXPECTED ERROR — recording and exiting")
        print("=" * 60)
        traceback.print_exc()
        print("Step failed with an unexpected error; review "
              "results/raw/step9-*.log")
        _recorder.close()
        sys.exit(1)
    _recorder.close()
    sys.exit(_exit_code)

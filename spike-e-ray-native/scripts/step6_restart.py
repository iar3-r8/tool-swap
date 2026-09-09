"""Step 6 GATE: cluster restart and recovery.

Two phases:
  A. With the step 6 apps deployed and a GPU-holding torch replica live,
     kill the GCS server process (kill -9) — a realistic *partial*
     crash of the head node, leaving the raylet and the other head
     processes behind — then run the documented recovery procedure
     (ray stop --force, ray start --head with the cluster's own flags,
     re-apply the config) and observe recovery.
  B. Kill a replica actor, observe unattended recovery. Skipped when
     phase A did not fully recover (its observations would only measure
     consequences).

Per rule 0.5: if Ray's own docs say "Serve cannot recover without
KubeRay", expect manual intervention. Record every command and its
output verbatim. If an undocumented step is needed, record it as a
required manual step — do not quietly do it.

Exit status (D29)
    0  Every required observation was made and nothing answers the gate
       negatively: the pre-kill baseline showed the apps RUNNING with
       VRAM held, after the GCS kill the documented recovery brought
       the apps back to RUNNING with VRAM held, and after the replica
       kill the replica was replaced unattended.
    1  Unexpected internal error (traceback printed).
    2  Harness/environment failure — an observation could NOT be made:
       the step 6 config could not be deployed or made live before the
       kill, the head/replica process could not be found or killed,
       the recovery commands themselves could not be run, or the
       status polls after the kill could not be answered. The gate
       proves nothing and must be re-run.
    3  Negative finding — the observation WAS made and answers the gate
       negatively: after the recovery commands the apps were NOT back
       to RUNNING (manual intervention was required), the VRAM the
       torch replica held pre-kill is no longer held post-recovery, or
       the killed replica was NOT replaced within the recovery window
       (recovered=False).

Both failure kinds are printed with an explicit label and a final
"STEP 6 RESULT:" summary line, and all raw output is recorded to
results/raw/step6-*.log and results/metrics/step6.jsonl regardless of
the exit status.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPTS_DIR)
sys.path.insert(0, os.path.join(_SCRIPTS_DIR, "lib"))

from nvidia import gpu_used_mb, snapshot_vram
from podman import podman_ps_all, podman_ps_count
from recorder import Recorder, block, record
from serve_api import (
    apply_config,
    cluster_ready,
    post_introspect,
    serve_status,
)
from step1_verify import (
    StepOutcome,
    _readiness_settings,
    _wait_for_running,
)

# Application-level healthy statuses (D29 fix): Ray 2.57's
# ApplicationStatus (ray/serve/schema.py) reports RUNNING when healthy —
# HEALTHY is a *deployment*-level status. The old code compared the
# app-level status against "HEALTHY", which serve_status() never
# returns, so apps_healthy could be True only when no apps were
# reported at all. Both shapes are accepted, as in steps 1/2.
_APP_HEALTHY = ("RUNNING", "HEALTHY")

# Deployment-level healthy status (schema.py DeploymentStatus).
_DEP_HEALTHY = "HEALTHY"

# The config re-deployed on the recovery path (D38, mirroring D34's
# SPIKE_STEP3_CONFIG for step 3): the legacy ``container``-key config,
# which is what the phase A/B observations assume (D34: only the
# container key's run_options can pass the nvidia-container-runtime;
# image_uri hardcodes run_options=[] at
# ray/_private/runtime_env/image_uri.py:174, so an image_uri replica
# holds no GPU and step 6's VRAM observations would measure nothing).
# D37 repointed the step 6 config at the container-key module; the
# recovery deploy must use the same config, so the restarted replicas
# are what the gate is actually observing. Read at import time like
# the step 3 knob, so the path is visible and overridable rather than
# buried in a list literal.
STEP6_CONFIG = os.environ.get("SPIKE_STEP6_CONFIG", "apps/step6_config.yaml")

# The torch tool's proxy URL (the same route step 3's gate uses): a
# request to it starts the tool_torch replica, which
# apps/step6_config.yaml keeps at min_replicas: 0. Without this
# wake-up the cluster would report both apps RUNNING while holding no
# GPU, and the kill would have nothing GPU-related to lose.
TOOL_TORCH_URL = os.environ.get(
    "SPIKE_SERVE_URL_TORCH", "http://localhost:8000/tool_torch"
)


def _app_status(app) -> str:
    """Normalize one applications-dict entry to a status string.

    Args:
        app: One value from the applications dict (dict or str).

    Returns:
        The status as a string, or "UNKNOWN" if absent.
    """
    if isinstance(app, dict):
        return str(app.get("status", "UNKNOWN"))
    return str(app)


def _apps_healthy(apps: dict) -> bool:
    """True if every reported application is in a healthy status.

    Args:
        apps: The applications dict from serve_status().

    Returns:
        True when at least one app is reported and all are healthy.
        An empty dict means the observation could not be made and is
        NOT healthy (the caller must also record a harness failure).
    """
    if not apps:
        return False
    return all(_app_status(a) in _APP_HEALTHY for a in apps.values())


def _recovery_settings() -> tuple[float, float]:
    """Read the post-kill recovery-wait knobs (D25 convention, D29).

    The old phase A single status check came 10s after the recovery
    commands (too early: the apps are still starting), and the old
    phase B loop hard-coded 30 x 2s. Both waits now share one
    configurable budget and poll interval, read at call time so a
    test can override them.

    Returns:
        ``(timeout_s, interval_s)`` from ``SPIKE_RECOVERY_TIMEOUT_S``
        (default 120) and ``SPIKE_READINESS_POLL_S`` (default 5).
    """
    timeout_s = float(os.environ.get("SPIKE_RECOVERY_TIMEOUT_S", "120"))
    _, interval_s = _readiness_settings()
    return timeout_s, interval_s


def _wait_for_recovery(
    recorder: Recorder,
    outcome: StepOutcome,
    label: str,
) -> dict | None:
    """Poll serve_status() until every app is RUNNING, within a budget.

    Deliberately a local loop rather than step1_verify's
    ``_wait_for_running``: the classification of "apps never reached
    RUNNING within the budget" is the OPPOSITE of the steps 1/2
    semantics. There, a deployment that will not start means the
    environment is broken (harness, exit 2). Here, the kill and the
    documented recovery commands have already been executed, so "not
    RUNNING within the budget" is the gate's own observation — the
    answer to "does the cluster recover?" is *no* (finding, exit 3).
    Only a dashboard that cannot be polled at all is a harness
    failure.

    Args:
        recorder: Records the final status (or the last error).
        outcome: Collects the harness failure / finding.
        label: Which phase's wait this is, for the messages.

    Returns:
        The final status dict when the apps reached RUNNING (or when
        the verdict has been recorded), None when the dashboard was
        never reachable (harness failure already recorded).
    """
    timeout_s, interval_s = _recovery_settings()
    deadline = time.monotonic() + timeout_s
    print(f"\nWaiting for recovery ({label}): budget {timeout_s:.1f}s, "
          f"polling every {interval_s:.1f}s ...")
    last_status: dict | None = None
    last_error: Exception | None = None
    poll = 0
    while time.monotonic() < deadline:
        poll += 1
        try:
            status = serve_status()
        except Exception as e:
            last_error = e
            last_status = None
            print(f"  [{poll}] serve status unreachable: {e} — retrying")
            time.sleep(interval_s)
            continue
        last_status = status
        last_error = None
        apps = status.get("applications", {})
        # DEPLOY_FAILED is terminal: no recovery will happen on its
        # own — record the verdict now instead of waiting out the
        # budget. (The observation was made; it answers the gate
        # negatively.)
        for name, app in apps.items():
            if isinstance(app, dict) and str(app.get("status", "")) \
                    == "DEPLOY_FAILED":
                recorder.write(block(
                    f"Post recovery — serve status ({label})",
                    json.dumps(status, indent=2),
                ))
                outcome.finding(
                    f"Phase A: app {name} is DEPLOY_FAILED after the "
                    "recovery commands — recovery requires manual "
                    "intervention."
                )
                return status
        if _apps_healthy(apps):
            print(f"  [{poll}] all apps RUNNING")
            return status
        summary = ", ".join(
            f"{n}={_app_status(a)}" for n, a in apps.items()
        ) or "<none>"
        print(f"  [{poll}] not all RUNNING yet ({summary})")
        time.sleep(interval_s)

    if last_error is not None and last_status is None:
        # The dashboard never answered: the recovery could not be
        # observed at all.
        recorder.write(block(
            f"Post recovery — serve status ({label})",
            f"<unreachable: {last_error}>",
        ))
        outcome.harness(
            f"serve status was unreachable for the full "
            f"{timeout_s:.0f}s after the recovery commands: "
            f"{last_error} — recovery could not be observed."
        )
        return None
    # The dashboard answered, but the apps were not all RUNNING within
    # the budget: the observation was made and it is negative.
    recorder.write(block(
        f"Post recovery — serve status ({label})",
        json.dumps(last_status, indent=2),
    ))
    apps = (last_status or {}).get("applications", {})
    outcome.finding(
        f"Phase A: the apps were NOT all RUNNING within "
        f"{timeout_s:.0f}s of the recovery commands (final statuses: "
        f"{', '.join(f'{n}={_app_status(a)}' for n, a in apps.items()) or '<none>'})"
        " — recovery requires manual intervention."
    )
    return last_status


def _cluster_start_flags() -> list[str]:
    """The ``ray start`` flags a recovered cluster must be started with.

    They must match the flags the harness used to start the cluster
    (``run_with_cluster_clean.sh``), most importantly ``--num-gpus``
    (D31): the D39 run restarted with a bare ``ray start --head``,
    which registered the raylet with the host's default GPU count
    instead of the cluster's pinned one. A recovery that brings the
    cluster back with the wrong GPU count would leave the ``num_gpus:
    1`` tools unschedulable (or spread across GPUs) and produce a
    spurious negative. The dashboard port, CPU count and
    usage-stats flag mirror the launcher so the recovered cluster is
    indistinguishable from the one it replaces.

    Returns:
        The flag list for ``ray start`` (without the binary name).
    """
    num_gpus = os.environ.get("SPIKE_RAY_NUM_GPUS", "1")
    if not num_gpus.isdigit():
        num_gpus = "1"
    return [
        "--head",
        f"--dashboard-port={os.environ.get('RAY_DASHBOARD_PORT', '8265')}",
        f"--num-cpus={os.cpu_count() or 2}",
        f"--num-gpus={num_gpus}",
        "--disable-usage-stats",
    ]


def _vram_held(vram: list[dict], baseline: list[dict]) -> bool:
    """Whether any GPU holds a real allocation relative to a baseline.

    Args:
        vram: The snapshot to test.
        baseline: The host VRAM snapshot taken before anything was
            deployed.

    Returns:
        True when at least one GPU's used memory rose more than
        ``SPIKE_VRAM_RELEASE_TOLERANCE_MB`` (default 256 MiB — driver
        noise vs the fixture's 4096 MiB allocation) above the
        baseline.
    """
    tol = int(os.environ.get("SPIKE_VRAM_RELEASE_TOLERANCE_MB", "256"))
    for gpu in baseline:
        index = gpu["index"]
        if (gpu_used_mb(vram, index) or 0) - (
            gpu_used_mb(baseline, index) or 0
        ) > tol:
            return True
    return False


def _wake_torch_replica(
    recorder: Recorder,
    outcome: StepOutcome,
    baseline_vram: list[dict],
) -> bool:
    """Start the torch replica with a request and confirm it holds VRAM.

    apps/step6_config.yaml autoscales both tools down to zero
    (min_replicas: 0): a freshly deployed cluster reports both apps
    RUNNING while holding no GPU. A kill of such a cluster would have
    nothing GPU-related to lose, so the step sends the same
    introspect request step 3's gate uses to cold-start the replica,
    and then requires a GPU's used memory to have moved past driver
    noise relative to the host baseline.

    Args:
        recorder: Records the introspect response and the VRAM
            snapshot.
        outcome: Collects the harness failure when the replica
            could not be started or holds no VRAM.
        baseline_vram: The host VRAM snapshot taken before anything
            was deployed; the allocation is measured against it.

    Returns:
        True when the torch replica answered and a GPU shows the
        allocation.
    """
    print(f"\n=== Waking the torch replica: "
          f"POST introspect {TOOL_TORCH_URL} ===")
    try:
        response = post_introspect(TOOL_TORCH_URL, timeout=120)
    except Exception as e:
        recorder.write(block("torch introspect (pre-kill)", str(e)))
        outcome.harness(
            f"the tool_torch replica could not be started at "
            f"{TOOL_TORCH_URL}: {e} — a cluster with no GPU-holding "
            "tool would have nothing to lose in the kill, so the "
            "observation could not be made."
        )
        return False
    recorder.write(
        block("torch introspect (pre-kill)", json.dumps(response, indent=2))
    )
    print(json.dumps(response, indent=2))
    if isinstance(response.get("error"), str):
        recorder.write(block(
            "torch introspect (pre-kill) error payload",
            json.dumps(response, indent=2),
        ))
        outcome.harness(
            "the tool_torch replica answered with an error "
            f"({response['error']!r}) — the replica is not live, so "
            "the observation could not be made."
        )
        return False
    after = snapshot_vram()
    recorder.write(block(
        "VRAM after waking the torch replica", json.dumps(after, indent=2),
    ))
    if not _vram_held(after, baseline_vram):
        outcome.harness(
            "no GPU's used memory rose past the driver-noise "
            "tolerance after the torch replica started — the replica "
            "holds no VRAM (wrong image or runtime?), so the kill "
            "would destroy nothing GPU-related and the observation "
            "could not be made."
        )
        return False
    print("VRAM rose past the driver-noise tolerance — the torch "
          "replica holds the GPU.")
    return True


def _redeploy(
    recorder: Recorder,
    outcome: StepOutcome,
    label: str,
    wait_kind: str = "harness",
) -> tuple[str, dict | None]:
    """Re-apply STEP6_CONFIG and wait until every app is RUNNING.

    Used before the pre-kill baseline (the harness starts a CLEAN
    cluster — ``run_with_cluster_clean.sh`` — so nothing is live
    unless this step deploys it; D39: the old step killed an empty
    cluster) and on the recovery path (a restarted cluster serves no
    applications until the config is applied again).

    Args:
        recorder: Records the deploy output (and, via the wait, the
            final status).
        outcome: Collects the failure; see ``wait_kind``.
        label: Where this deploy happens, for the messages
            ("pre-kill" / "recovery").
        wait_kind: "harness" (pre-kill) classifies apps that never
            reach RUNNING as a harness failure — the environment
            cannot even start the step's own config; "finding"
            (recovery) classifies it as a negative finding — the
            recovery commands ran and the apps still did not come
            back, which is the gate's own observation.

    Returns:
        ``(state, status)`` where state is "ok" (every app RUNNING),
        "harness" (the config could not be applied or the dashboard
        never answered — a harness failure is already recorded), or
        "finding" (the recovery wait ran out and the apps never came
        back — a finding is already recorded). The matching failure
        is recorded here and the caller must NOT record another one
        for the same observation; it decides what to do with the
        state (skip phase B, label the run, ...).
    """
    try:
        result = apply_config(STEP6_CONFIG)
    except Exception as e:
        recorder.write(block(f"serve deploy ({label}) error", str(e)))
        outcome.harness(
            f"Could not invoke `serve deploy` for {STEP6_CONFIG} "
            f"({label}): {e} — the observation could not be made."
        )
        return "harness", None
    recorder.write(
        block(f"serve deploy ({label})", result.stdout + result.stderr)
    )
    print(f"serve deploy ({label}) exit: {result.returncode}")
    if result.returncode != 0:
        outcome.harness(
            f"`serve deploy` of {STEP6_CONFIG} exited "
            f"{result.returncode} ({label}) — the config is not live, "
            "so the observation could not be made."
        )
        return "harness", None
    if wait_kind == "finding":
        status = _wait_for_recovery(recorder, outcome, f"re-deploy {label}")
        if status is None:
            # The dashboard never answered: harness failure recorded
            # by the wait.
            return "harness", None
        if _apps_healthy(status.get("applications", {})):
            return "ok", status
        # The wait recorded the finding (not RUNNING within the
        # budget, or DEPLOY_FAILED).
        return "finding", status
    # The readiness wait consumed the status polls; the caller reads
    # its own baseline/status afterwards, so no extra call here.
    if _wait_for_running(recorder, outcome):
        return "ok", None
    return "harness", None


def find_ray_head() -> int:
    """Find the GCS server PID — the process the phase A kill targets.

    The head node is a *process tree* (gcs_server, raylet, dashboard,
    workers); killing only the GCS server deliberately simulates a
    realistic *partial* crash (the D39 option b): the documented
    recovery procedure must work from exactly the state such a crash
    leaves — a half-dead head node with surviving processes. The
    raylet fallback keeps the step runnable on hosts where the
    gcs_server name is not visible to pgrep.

    Raises:
        RuntimeError: No gcs_server or raylet process is found.
    """
    result = subprocess.run(
        ["pgrep", "-f", "gcs_server"],
        capture_output=True, text=True,
    )
    if result.stdout.strip():
        return int(result.stdout.strip().split("\n")[0])
    # Fallback: find raylet
    result = subprocess.run(
        ["pgrep", "-f", "raylet"],
        capture_output=True, text=True,
    )
    if result.stdout.strip():
        return int(result.stdout.strip().split("\n")[0])
    raise RuntimeError("Could not find Ray head node process")


# ── Phase A: GCS kill and documented recovery ────────────────────
def phase_a(recorder: Recorder, outcome: StepOutcome) -> bool:
    """Deploy the tools, kill the GCS server, run the documented recovery.

    Crash scenario (D39, option b): only the GCS server process is
    killed (``kill -9``) — a realistic *partial* head-node crash that
    leaves the raylet, dashboard and workers behind. The gate asks
    whether the *documented recovery procedure* works from whatever
    state such a crash leaves, so the recovery is the full operator
    procedure: ``ray stop --force`` (the cleanup an operator must
    perform — the D39 run showed a bare ``ray start --head`` collides
    with the survivors: "already running at <head>:6379"), then
    ``ray start --head`` with the cluster's own flags, then a
    re-apply of the step 6 config.

    Order: deploy → wait for RUNNING → wake the torch replica →
    pre-kill baseline (apps RUNNING + VRAM held) → kill → recover →
    poll. Every earlier stage that cannot be made into an observation
    is a harness failure (exit 2) *before* any kill is attempted, so
    the gate never measures an empty or replica-less cluster.

    Classification (D29):
      * the config cannot be deployed/made live, or the torch replica
        cannot be started to hold a GPU, or the kill itself fails, or
        the recovery commands cannot be run → HARNESS: recovery could
        not be observed;
      * the recovery commands ran but the apps (or the VRAM) are not
        back → NEGATIVE FINDING: the observation was made and it
        answers the gate negatively (manual intervention was
        required).

    Args:
        recorder: Records the raw command outputs and statuses.
        outcome: Collects the harness failures and findings.

    Returns:
        True only when every observation was made and recovery was
        confirmed (apps RUNNING and VRAM held again) — the condition
        under which phase B may run. False when a harness failure or
        a finding was recorded, so phase B is skipped (item 3:
        consequences of a failed recovery must not be reported as
        independent failures).
    """
    print("")
    print("=" * 60)
    print("STEP 6, PHASE A: GCS kill and recovery")
    print("=" * 60)
    print("Crash scenario: kill -9 on the GCS server PID only — a")
    print("partial head-node crash (raylet/dashboard/workers survive).")
    print("Recovery: ray stop --force, ray start --head "
          "(cluster flags), re-apply config.")

    # 1. Host baseline BEFORE anything is deployed (VRAM reference
    # point for "the torch replica holds the GPU").
    print("\n=== Host VRAM baseline ===")
    host_vram = snapshot_vram()
    recorder.write(block("Host VRAM baseline", json.dumps(host_vram, indent=2)))
    print(f"VRAM baseline: {json.dumps(host_vram, indent=2)}")

    # 2. Deploy the step 6 config. The harness starts a CLEAN cluster
    # (run_with_cluster_clean.sh), so nothing is live unless this
    # step deploys it — D39: the old step killed an empty cluster and
    # then "recovered" apps that were never deployed.
    print(f"\n=== Deploying {STEP6_CONFIG} (pre-kill) ===")
    pre_state, _ = _redeploy(
        recorder, outcome, "pre-kill", wait_kind="harness",
    )
    if pre_state != "ok":
        record("step6", phase="A", deployed=False)
        return False
    record("step6", phase="A", deployed=True)

    # 3. min_replicas: 0 — the apps are RUNNING at zero replicas; a
    # request must start the torch replica and it must hold VRAM.
    if not _wake_torch_replica(recorder, outcome, host_vram):
        record("step6", phase="A", replica_woken=False)
        return False
    record("step6", phase="A", replica_woken=True)

    # 4. Pre-kill baseline: apps RUNNING (step 2 waited for it) and
    # VRAM held (step 3 verified it).
    print("\n=== Before kill ===")
    try:
        pre_status = serve_status()
    except Exception as e:
        outcome.harness(
            f"serve status unreachable before the kill: {e} — the "
            "pre-kill baseline could not be observed."
        )
        record("step6", phase="A", baseline_observed=False)
        return False
    pre_vram = snapshot_vram()
    pre_podman = podman_ps_all()
    print(f"Serve apps: {json.dumps(pre_status, indent=2)}")
    print(f"VRAM: {json.dumps(pre_vram, indent=2)}")
    print(f"Containers: {podman_ps_count()}")
    recorder.write(block("Before kill — serve status", json.dumps(pre_status, indent=2)))
    recorder.write(block("Before kill — VRAM", json.dumps(pre_vram, indent=2)))
    recorder.write(block("Before kill — podman ps -a", pre_podman))
    pre_apps = pre_status.get("applications", {})
    if not _apps_healthy(pre_apps):
        outcome.harness(
            f"the pre-kill baseline does not show the apps RUNNING "
            f"(final statuses: "
            f"{', '.join(f'{n}={_app_status(a)}' for n, a in pre_apps.items())}),"
            " — nothing is live to lose, so the observation could "
            "not be made."
        )
        record("step6", phase="A", baseline_observed=False)
        return False
    if not _vram_held(pre_vram, host_vram):
        outcome.harness(
            "the pre-kill baseline shows no VRAM held past the "
            "driver-noise tolerance — the kill would destroy nothing "
            "GPU-related, so the observation could not be made."
        )
        record("step6", phase="A", baseline_observed=False)
        return False
    record("step6", phase="A", baseline_observed=True)

    # 5. Kill the GCS server PID (the partial crash; see the docstring).
    print("\n=== Killing the GCS server (partial crash) ===")
    try:
        pid = find_ray_head()
        print(f"GCS server PID: {pid}")
        recorder.write(block("GCS server PID", str(pid)))
        subprocess.run(["kill", "-9", str(pid)], check=True)
        print(f"kill -9 {pid} sent")
    except Exception as e:
        print(f"Error finding/killing GCS server: {e}")
        recorder.write(block("Kill GCS error", str(e)))
        record("step6", phase="A", kill_ok=False, error=str(e))
        # The kill did not happen: recovery cannot be observed.
        outcome.harness(
            f"Could not find or kill the GCS server: {e} — the "
            "recovery procedure was not executed, so recovery could "
            "not be observed."
        )
        return False
    record("step6", phase="A", kill_ok=True, gcs_pid=pid)

    # 6. Immediate snapshot (evidence the survivors were there).
    print("\n=== Immediate snapshot after kill ===")
    post_vram = snapshot_vram()
    post_podman = podman_ps_all()
    print(f"VRAM after kill: {json.dumps(post_vram, indent=2)}")
    print(f"Containers after kill: {podman_ps_count()}")
    recorder.write(block("After kill — VRAM", json.dumps(post_vram, indent=2)))
    recorder.write(block("After kill — podman ps -a", post_podman))

    # 7. The documented recovery procedure (option b). Step 1 is the
    # cleanup an operator must perform after a partial crash — the
    # D39 run proved a bare `ray start --head` cannot recover from
    # this state (it collides with the surviving processes), and that
    # collision is recorded as a required manual step below.
    print("\n=== Recovery: the documented procedure ===")
    manual_steps = []
    recovery_commands_ok = True

    start_flags = _cluster_start_flags()
    print(f"Restart command: ray start {' '.join(start_flags)}")

    try:
        result = subprocess.run(
            ["ray", "stop", "--force"],
            capture_output=True, text=True, timeout=120,
        )
        recorder.write(block("ray stop --force", result.stdout + result.stderr))
        print(f"ray stop --force exit: {result.returncode}")
        if result.returncode != 0:
            manual_steps.append(
                "ray stop --force failed — manual cleanup needed"
            )
    except Exception as e:
        recorder.write(block("ray stop --force error", str(e)))
        manual_steps.append(f"ray stop --force could not run: {e}")

    time.sleep(5)

    start_cmd = ["ray", "start"] + start_flags
    start_desc = "ray start " + " ".join(start_flags)
    try:
        result = subprocess.run(
            start_cmd,
            capture_output=True, text=True, timeout=120,
        )
        recorder.write(block(start_desc, result.stdout + result.stderr))
        print(f"{start_desc} exit: {result.returncode}")
        if result.returncode != 0:
            manual_steps.append(
                f"{start_desc} failed — may need manual cleanup"
            )
            recovery_commands_ok = False
    except Exception as e:
        recorder.write(block(f"{start_desc} error", str(e)))
        manual_steps.append(f"{start_desc} could not run: {e}")
        recovery_commands_ok = False

    # Wait for the dashboard to answer again before re-deploying:
    # `serve deploy` against a half-dead dashboard fails with
    # RemoteDisconnected (the D39 run).
    if recovery_commands_ok:
        print("Waiting for the dashboard to answer after the restart ...")
        if not cluster_ready(timeout_s=90, interval_s=3):
            manual_steps.append(
                "the dashboard never answered after the restart — "
                "manual inspection needed"
            )
            recovery_commands_ok = False

    redeploy_state, post_status = _redeploy(
        recorder, outcome, "recovery", wait_kind="finding",
    )
    if not recovery_commands_ok:
        # The recovery procedure could not be executed, so whether the
        # cluster recovers on its own cannot be observed. (No
        # double-recording: the failed command itself is described in
        # manual_steps; the re-deploy state, if any, is a consequence.)
        record("step6", phase="A", apps_healthy=False,
               manual_steps=manual_steps)
        outcome.harness(
            "The recovery commands could not be run or failed "
            f"({manual_steps}) — the recovery observation could not "
            "be made."
        )
        return False
    if redeploy_state == "harness":
        # The re-apply could not be run, or the dashboard never
        # answered: a harness failure is already recorded by
        # _redeploy — do not mask it with a second one.
        record("step6", phase="A", apps_healthy=False,
               manual_steps=manual_steps)
        return False
    if redeploy_state == "finding":
        # The re-apply ran and the recovery wait answered, but the
        # apps never came back: a FINDING is already recorded by the
        # wait — it is the gate's own observation, not a harness
        # failure, and it must not be masked by one (D29).
        record("step6", phase="A", apps_healthy=False,
               vram_held=False, manual_steps=manual_steps)
        return False

    # 8. Post-recovery state (the recovery wait inside _redeploy
    # already polled within a configurable budget — D29 — so the
    # final status is the one it returned).
    print("\n=== Post-recovery state ===")
    post_vram2 = snapshot_vram()
    post_podman2 = podman_ps_all()

    recorder.write(block("Post recovery — VRAM", json.dumps(post_vram2, indent=2)))
    recorder.write(block("Post recovery — podman ps -a", post_podman2))

    print(f"Serve apps: {json.dumps(post_status, indent=2)}")
    print(f"VRAM: {json.dumps(post_vram2, indent=2)}")
    print(f"Containers: {podman_ps_count()}")

    if manual_steps:
        print(f"\n  Required manual steps: {manual_steps}")
    else:
        print("\n  No manual steps required")

    # Record verdict
    # In Ray 2.57+, applications is a dict {name: details} or {name: status_str}
    # (ServeInstanceDetails.applications, schema.py:1764), not a list.
    apps = post_status.get("applications", {})
    for name, a in apps.items():
        st = _app_status(a)
        print(f"  {name}: {st}")
    apps_healthy = _apps_healthy(apps)
    vram_held = _vram_held(post_vram2, host_vram)
    # The torch replica started again after the re-apply only on the
    # next request; with min_replicas: 0 the apps can report RUNNING
    # while the VRAM is not (yet) held. The baseline promised VRAM
    # held pre-kill, so the post-recovery comparison is against the
    # same host baseline. When the replica has not re-allocated yet
    # the step sends it the same wake-up request and re-checks.
    if apps_healthy and not vram_held:
        print("Apps RUNNING but VRAM not held yet (min_replicas: 0 — "
              "the replica re-allocates on the first request).")
        if _wake_torch_replica(recorder, outcome, host_vram):
            post_vram2 = snapshot_vram()
            recorder.write(block(
                "Post recovery — VRAM after wake-up",
                json.dumps(post_vram2, indent=2),
            ))
            vram_held = _vram_held(post_vram2, host_vram)
    if apps_healthy and not vram_held:
        rises = [
            max(0, (gpu_used_mb(post_vram2, g["index"]) or 0)
                   - (gpu_used_mb(host_vram, g["index"]) or 0))
            for g in host_vram
        ]
        peak = max(rises) if rises else 0
        outcome.finding(
            "the apps were RUNNING after the recovery commands but no "
            "GPU held the allocation the torch replica held pre-kill "
            f"(used memory rose at most {peak} MiB over the host "
            "baseline) — the GPU-holding tool did not come back; "
            "recovery requires manual intervention."
        )
    record("step6", phase="A", apps_healthy=apps_healthy,
           vram_held=vram_held, manual_steps=manual_steps)
    # The finding for "not all RUNNING" (if any) was already recorded
    # by _wait_for_recovery, which owns the 2-vs-3 classification for
    # that observation; the VRAM finding above is this function's.
    return not outcome.findings and not outcome.harness_failures


# ── Phase B: Replica actor kill ──────────────────────────────────
# Data source: GET /api/serve/applications/ (serve_head.py:81) — the
# only application route; there is no per-application GET, so
# get_application() would 404. Payload shape per ServeInstanceDetails
# (schema.py:1723): applications[name].deployments[dep].replicas, and
# each replica exposes `pid` (ReplicaDetails, schema.py:1285, populated
# from the actor's PID in deployment_state.py:1792).
def _tool_torch_dep(status: dict) -> dict:
    """Return the ToolTorch deployment details from a serve status dict.

    Args:
        status: The serve_status() response.

    Returns:
        The ToolTorch deployment dict, or {} when absent.
    """
    app = status.get("applications", {}).get("tool_torch", {})
    # Deployment name as declared in apps/step6_config.yaml.
    return app.get("deployments", {}).get("ToolTorch", {})


def phase_b(recorder: Recorder, outcome: StepOutcome) -> None:
    """Kill a replica actor, observe unattended recovery.

    Classification (D29): the replica/app cannot be found or killed,
    or the status polls fail → HARNESS (the recovery could not be
    observed); the polls were answered but the deployment did not
    return to HEALTHY within the window → NEGATIVE FINDING
    (recovered=False is a result about Ray, not a harness error).

    Args:
        recorder: Records the raw states.
        outcome: Collects the harness failures and findings.
    """
    print("")
    print("=" * 60)
    print("STEP 6, PHASE B: Replica actor kill")
    print("=" * 60)

    # Find the serving application and its replica PID
    print("\n=== Finding replica ===")
    try:
        apps = serve_status()
        app = apps.get("applications", {}).get("tool_torch")
        print(f"tool_torch app: {json.dumps(app, indent=2)}")
        recorder.write(block("tool_torch app state", json.dumps(app, indent=2)))

        if app is None:
            print("tool_torch application not found in serve status")
            recorder.write(block("Phase B", "tool_torch application not found"))
            record("step6", phase="B", harness_failure="app not found")
            outcome.harness(
                "tool_torch application not found in serve status — the "
                "replica observation could not be made."
            )
            return

        dep = _tool_torch_dep(apps)

        # Look for replicas
        replica_killed = False
        for replica in dep.get("replicas", []):
            pid = replica.get("pid")
            if pid:
                print(f"Found replica PID: {pid}")
                recorder.write(block("Replica PID", str(pid)))

                # Kill the replica
                print(f"\n=== Killing replica PID {pid} ===")
                try:
                    subprocess.run(["kill", "-9", str(pid)], check=True)
                except Exception as e:
                    recorder.write(block(f"Kill replica {pid} error", str(e)))
                    record("step6", phase="B", kill_ok=False, error=str(e))
                    outcome.harness(
                        f"Could not kill replica PID {pid}: {e} — the "
                        "recovery could not be observed."
                    )
                    return
                print(f"kill -9 {pid} sent")
                replica_killed = True

                # Wait for recovery (D29: the old hard-coded 30 x 2s
                # is now SPIKE_RECOVERY_TIMEOUT_S / SPIKE_READINESS_POLL_S).
                timeout_s, interval_s = _recovery_settings()
                print(f"\n=== Watching for unattended recovery "
                      f"(budget {timeout_s:.1f}s, "
                      f"polling every {interval_s:.1f}s) ===")
                deadline = time.monotonic() + timeout_s
                recovered = False
                dep_after: dict = {}
                while time.monotonic() < deadline:
                    time.sleep(interval_s)
                    apps_after = serve_status()
                    dep_after = _tool_torch_dep(apps_after)
                    # Deployment-level status; the app-level enum is
                    # ApplicationStatus (RUNNING when healthy, never
                    # "HEALTHY" — schema.py:1171), so the healthy
                    # check applies to DeploymentStatus (schema.py).
                    status = dep_after.get("status", "unknown")
                    replicas = dep_after.get("replicas", [])
                    print(f"  Status: {status}, Replicas: {len(replicas)}")
                    for r in replicas:
                        print(f"    PID: {r.get('pid')}, state: {r.get('state')}")

                    if status == _DEP_HEALTHY and len(replicas) >= 1:
                        print("  Recovery confirmed")
                        wait_seconds = round(
                            timeout_s - (deadline - time.monotonic()), 1
                        )
                        record("step6", phase="B", recovered=True,
                               wait_seconds=wait_seconds)
                        recovered = True
                        break
                if not recovered:
                    # The polls WERE answered and the deployment did
                    # not come back: a real result about Ray.
                    print(f"  Did not recover in {timeout_s:.0f}s")
                    record("step6", phase="B", recovered=False)
                    outcome.finding(
                        f"Phase B: the killed replica was NOT replaced "
                        f"within {timeout_s:.0f}s (final deployment "
                        f"status: {dep_after.get('status', 'unknown')}) "
                        "— unattended recovery did not happen."
                    )
                break
        if not replica_killed:
            print("No replica found")
            recorder.write(block("Phase B", "No replica found"))
            record("step6", phase="B", harness_failure="no replica found")
            outcome.harness(
                "No live ToolTorch replica with a PID was found — the "
                "replica-kill observation could not be made (the "
                "deployment may still be at 0 replicas; re-apply the "
                "config and send a request first)."
            )

    except Exception as e:
        print(f"Error: {e}")
        recorder.write(block("Phase B error", str(e)))
        record("step6", phase="B", harness_failure=str(e))
        # The observation could not be made (status unreachable, kill
        # tool broken, ...) — harness, not a finding.
        outcome.harness(
            f"Phase B could not be observed: {e} — the environment, "
            "not the experiment, is at fault."
        )


def _print_summary(outcome: StepOutcome) -> None:
    """Print the final gate verdict, labelling each failure kind explicitly.

    Args:
        outcome: The collected harness failures and findings.
    """
    if outcome.harness_failures:
        print("")
        print("STEP 6 RESULT: HARNESS FAILURE — exit code 2")
        print("A required observation could not be made; the environment,")
        print("not the experiment, is at fault. The gate proves nothing")
        print("and must be re-run; the incomplete findings are:")
        for i, msg in enumerate(outcome.harness_failures, 1):
            print(f"  {i}. {msg}")
    if outcome.findings:
        print("")
        print("STEP 6 RESULT: NEGATIVE FINDING(S) — exit code 3")
        print("The observations were made but answer the gate negatively")
        print("(recovery did not happen). Recorded findings:")
        for i, msg in enumerate(outcome.findings, 1):
            print(f"  {i}. {msg}")
    if not outcome.harness_failures and not outcome.findings:
        print("")
        print("STEP 6 RESULT: gate CLEAN — exit code 0")
        print("The cluster recovered after the GCS kill (partial")
        print("head-node crash) and the killed replica was replaced")
        print("unattended.")


def run(recorder: Recorder) -> int:
    """Run step 6's gate observations and return the process exit code.

    Phase B is skipped when phase A did not fully recover (item 3): a
    broken or half-recovered cluster makes the replica-kill
    observations impossible or meaningless, and a consequence of phase
    A's failure must not be reported as an independent failure —
    exactly as step 3's gate skips its remaining probes once a
    finding is recorded.

    Args:
        recorder: The step's Recorder (stdout/stderr tee to the log).

    Returns:
        0 (gate clean), 2 (harness failure) or 3 (negative finding).
    """
    outcome = StepOutcome()

    print("=" * 60)
    print("STEP 6 GATE: Cluster restart and recovery")
    print("=" * 60)

    try:
        phase_a_recovered = phase_a(recorder, outcome)
        if phase_a_recovered:
            phase_b(recorder, outcome)
        else:
            print("")
            print("=" * 60)
            print("STEP 6, PHASE B: SKIPPED — phase A did not recover")
            print("=" * 60)
            print("The replica-kill observations require the cluster to")
            print("be back to RUNNING with the tools live; phase A's")
            print("recovery did not succeed, so phase B would only")
            print("measure consequences of that failure.")
            record("step6", phase="B", skipped=True,
                   reason="phase A did not recover")
    finally:
        print("")
        print("--- STEP 6 OBSERVATIONS COMPLETE ---")
        _print_summary(outcome)
        recorder.close()
    return outcome.exit_code


def _gpu_guard() -> str | None:
    """Check the GPU host preconditions (D29: labelled verdict, no silent exit).

    Returns:
        A problem description to report as a harness failure (exit 2:
        the VRAM/container observations this step records could not be
        made), or None when the host preconditions hold.
    """
    if shutil.which("nvidia-smi") is None:
        return (
            "nvidia-smi not found on PATH — the VRAM observations "
            "cannot be made. Step 6 requires a GPU box. Run on the "
            "DGX host."
        )
    if shutil.which("podman") is None:
        return (
            "podman not found on PATH — the container observations "
            "cannot be made. Step 6 requires a container runtime. "
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
        print("STEP 6 RESULT: HARNESS FAILURE — exit code 2")
        sys.exit(2)
    _recorder = Recorder("step6")
    try:
        _exit_code = run(_recorder)
    except Exception:
        import traceback

        print("\n" + "=" * 60)
        print("STEP 6: UNEXPECTED ERROR — recording and exiting")
        print("=" * 60)
        traceback.print_exc()
        print("Step failed with an unexpected error; review "
              "results/raw/step6-*.log")
        _recorder.close()
        sys.exit(1)
    _recorder.close()
    sys.exit(_exit_code)

"""Step 6 GATE: cluster restart and recovery.

Two phases:
  A. Kill the head node (kill -9), restart Ray and Serve, observe recovery.
  B. Kill a replica actor, observe unattended recovery.

Per rule 0.5: if Ray's own docs say "Serve cannot recover without KubeRay",
expect manual intervention. Record every command and its output verbatim.
If an undocumented step is needed, record it as a required manual step —
do not quietly do it.

Exit status (D29)
    0  Every required observation was made and nothing answers the gate
       negatively: after the head-node kill the documented recovery
       brought the apps back to RUNNING, and after the replica kill the
       replica was replaced unattended.
    1  Unexpected internal error (traceback printed).
    2  Harness/environment failure — an observation could NOT be made:
       the head/replica process could not be found or killed, the
       recovery commands themselves could not be run, or the status
       polls after the kill could not be answered. The gate proves
       nothing and must be re-run.
    3  Negative finding — the observation WAS made and answers the gate
       negatively: after the recovery commands the apps were NOT back
       to RUNNING (manual intervention was required), or the killed
       replica was NOT replaced within the recovery window
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

from nvidia import snapshot_vram
from podman import podman_ps_all, podman_ps_count
from recorder import Recorder, block, record
from serve_api import serve_status
from step1_verify import StepOutcome, _readiness_settings

# Application-level healthy statuses (D29 fix): Ray 2.57's
# ApplicationStatus (ray/serve/schema.py) reports RUNNING when healthy —
# HEALTHY is a *deployment*-level status. The old code compared the
# app-level status against "HEALTHY", which serve_status() never
# returns, so apps_healthy could be True only when no apps were
# reported at all. Both shapes are accepted, as in steps 1/2.
_APP_HEALTHY = ("RUNNING", "HEALTHY")

# Deployment-level healthy status (schema.py DeploymentStatus).
_DEP_HEALTHY = "HEALTHY"


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


def find_ray_head() -> int:
    """Find the Ray head node GCS process PID.

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


# ── Phase A: Head node kill ──────────────────────────────────────
def phase_a(recorder: Recorder, outcome: StepOutcome) -> None:
    """Kill head node, attempt documented recovery.

    Classification (D29):
      * the kill itself fails, or the recovery commands cannot be run
        (non-zero exit / exception) → HARNESS: the recovery procedure
        was not executed, so recovery could not be observed;
      * the recovery commands ran but the apps are not back RUNNING
        → NEGATIVE FINDING: the observation was made and it answers
        the gate negatively (manual intervention was required).

    Args:
        recorder: Records the raw command outputs and statuses.
        outcome: Collects the harness failures and findings.
    """
    print("")
    print("=" * 60)
    print("STEP 6, PHASE A: Head node kill and recovery")
    print("=" * 60)

    # 1. Snapshot before
    print("\n=== Before kill ===")
    try:
        pre_status = serve_status()
    except Exception as e:
        outcome.harness(
            f"serve status unreachable before the kill: {e} — the "
            "pre-kill baseline could not be observed."
        )
        return
    pre_vram = snapshot_vram()
    pre_podman = podman_ps_all()
    print(f"Serve apps: {json.dumps(pre_status, indent=2)}")
    print(f"VRAM: {json.dumps(pre_vram, indent=2)}")
    print(f"Containers: {podman_ps_count()}")
    recorder.write(block("Before kill — serve status", json.dumps(pre_status, indent=2)))
    recorder.write(block("Before kill — podman ps -a", pre_podman))

    # 2. Kill head node
    print("\n=== Killing head node ===")
    try:
        pid = find_ray_head()
        print(f"Head node PID: {pid}")
        recorder.write(block("Head node PID", str(pid)))
        subprocess.run(["kill", "-9", str(pid)], check=True)
        print(f"kill -9 {pid} sent")
    except Exception as e:
        print(f"Error finding/killing head: {e}")
        recorder.write(block("Kill head error", str(e)))
        record("step6", phase="A", kill_ok=False, error=str(e))
        # The kill did not happen: recovery cannot be observed.
        outcome.harness(
            f"Could not find or kill the head node: {e} — the "
            "recovery procedure was not executed, so recovery could "
            "not be observed."
        )
        return

    # 3. Immediate snapshot
    print("\n=== Immediate snapshot after kill ===")
    post_vram = snapshot_vram()
    post_podman = podman_ps_all()
    print(f"VRAM after kill: {json.dumps(post_vram, indent=2)}")
    print(f"Containers after kill: {podman_ps_count()}")
    recorder.write(block("After kill — VRAM", json.dumps(post_vram, indent=2)))
    recorder.write(block("After kill — podman ps -a", post_podman))

    # 4. Attempt recovery with documented commands
    print("\n=== Recovery: restarting Ray ===")
    manual_steps = []
    recovery_commands_ok = True

    try:
        result = subprocess.run(
            ["ray", "start", "--head"],
            capture_output=True, text=True, timeout=30,
        )
        recorder.write(block("ray start --head", result.stdout + result.stderr))
        print(f"ray start exit: {result.returncode}")
        if result.returncode != 0:
            manual_steps.append("ray start --head failed — may need manual cleanup")
            recovery_commands_ok = False
    except Exception as e:
        recorder.write(block("ray start --head error", str(e)))
        manual_steps.append(f"ray start --head could not run: {e}")
        recovery_commands_ok = False

    time.sleep(5)

    try:
        result = subprocess.run(
            ["serve", "deploy", "apps/step3_config.yaml"],
            capture_output=True, text=True, timeout=120,
        )
        recorder.write(block("serve deploy (recovery)", result.stdout + result.stderr))
        print(f"serve deploy exit: {result.returncode}")
        if result.returncode != 0:
            manual_steps.append("serve deploy failed — manual re-apply needed")
            recovery_commands_ok = False
    except Exception as e:
        recorder.write(block("serve deploy (recovery) error", str(e)))
        manual_steps.append(f"serve deploy could not run: {e}")
        recovery_commands_ok = False

    if not recovery_commands_ok:
        # The recovery procedure could not be executed, so whether the
        # cluster recovers on its own cannot be observed.
        record("step6", phase="A", apps_healthy=False,
               manual_steps=manual_steps)
        outcome.harness(
            "The recovery commands could not be run or failed "
            f"({manual_steps}) — the recovery observation could not "
            "be made."
        )
        return

    # 5. Observe recovery (D29: the old single check 10s after the
    # recovery commands is too early — the apps are still starting —
    # so poll within a configurable budget, like the D25 waits).
    print("\n=== Post-recovery state ===")
    post_status = _wait_for_recovery(recorder, outcome, "phase A")
    if post_status is None:
        # The dashboard was never reachable: a harness failure was
        # already recorded; the verdict below cannot be made.
        record("step6", phase="A", apps_healthy=False,
               manual_steps=manual_steps, status_unreachable=True)
        return
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
    record("step6", phase="A", apps_healthy=apps_healthy,
           manual_steps=manual_steps)
    # The finding for "not all RUNNING" (if any) was already recorded
    # by _wait_for_recovery, which owns the 2-vs-3 classification for
    # this observation.


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
        print("The cluster recovered after the head-node kill and the")
        print("killed replica was replaced unattended.")


def run(recorder: Recorder) -> int:
    """Run step 6's gate observations and return the process exit code.

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
        phase_a(recorder, outcome)
        phase_b(recorder, outcome)
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

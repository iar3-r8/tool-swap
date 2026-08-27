"""Step 1 verification: per-deployment image_uri.

Tests whether image_uri can be set per-deployment or only per-application.
Runs the decorator form (step1_two_deployments.py) AND the YAML config form.

Per the protocol: neither config form being rejected is the pass condition.
If only one form works, that means one-tool-per-application mapping.
A fail in step 1 does NOT decide the framework (Rule 5).

Exit status (D21)
    0  All required observations were made and no negative finding was
       observed.
    1  Unexpected internal error (traceback printed).
    2  Harness/environment failure — a required observation could NOT be
       made: the deployment never reached RUNNING, a probe request failed
       or timed out, or the CLI itself could not be invoked. The findings
       from this run are incomplete and must not be treated as a pass.
    3  Negative finding — the harness worked and the observation was made,
       but it answers the step's question negatively: a config form was
       rejected, or a probe answered with unexpected content (wrong image
       or framework).

A probe answering with unexpected content is a *finding* (exit 3); a probe
that could not be reached at all is a *harness failure* (exit 2). Both are
printed with an explicit label and both prevent a false "success". All raw
output is recorded to results/raw/step1-*.log and results/metrics/step1.jsonl
regardless of the exit status.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
from recorder import Recorder, block, record
from serve_api import apply_config, post_introspect, serve_status

TOOL_URL_TORCH = os.environ.get(
    "SPIKE_SERVE_URL_TORCH", "http://localhost:8000/torch"
)
TOOL_URL_TF = os.environ.get(
    "SPIKE_SERVE_URL_TF", "http://localhost:8000/tf"
)

# Expected per-probe identity. Each fixture image bakes in a marker
# (fixtures/build_images.sh) and its own framework; toolkit/deployments.py
# asserts the conflicting framework is absent, so a healthy image's
# introspect response identifies exactly one framework.
EXPECTED: dict[str, dict[str, str]] = {
    "TorchProbe": {"marker_prefix": "tool_torch", "framework": "torch"},
    "TfProbe": {"marker_prefix": "tool_tf", "framework": "tensorflow"},
}


class StepOutcome:
    """Collects harness failures and negative findings for the exit code."""

    def __init__(self) -> None:
        self.harness_failures: list[str] = []
        self.findings: list[str] = []

    def harness(self, msg: str) -> None:
        """Record a harness/environment failure (an observation not made).

        Args:
            msg: Human-readable description of what could not be observed.
        """
        self.harness_failures.append(msg)
        print(f"\n[HARNESS FAILURE] {msg}")
        print("  The observation could not be made — the environment, not")
        print("  the experiment, is at fault. Exit code will be 2.")

    def finding(self, msg: str) -> None:
        """Record a legitimate negative finding (observation made, negative).

        Args:
            msg: Human-readable description of the negative result.
        """
        self.findings.append(msg)
        print(f"\n[NEGATIVE FINDING] {msg}")
        print("  The probe answered but with unexpected content (or a config")
        print("  form was rejected) — recorded as a finding, not a harness")
        print("  failure. Exit code will be 3 (absent any harness failure).")

    @property
    def exit_code(self) -> int:
        """Exit code: 2 (harness failure) outranks 3 (finding); clean is 0."""
        if self.harness_failures:
            return 2
        if self.findings:
            return 3
        return 0


def _app_status(app: Any) -> str:
    """Normalize one applications-dict entry to a status string.

    In Ray 2.57, applications is a dict {name: details} where
    details["status"] is an ApplicationStatus (RUNNING when healthy —
    schema.py:1171); other releases may return a bare status string.
    Both shapes are accepted.

    Args:
        app: One value from the applications dict (dict or str).

    Returns:
        The status as a string, or "UNKNOWN" if absent.
    """
    if isinstance(app, dict):
        return str(app.get("status", "UNKNOWN"))
    return str(app)


def _status_summary(apps: dict[str, Any]) -> str:
    """Compact 'name=STATUS, ...' summary for failure messages.

    Args:
        apps: The applications dict from serve_status().

    Returns:
        A comma-separated summary, or "" if the dict is empty.
    """
    return ", ".join(f"{n}={_app_status(a)}" for n, a in apps.items())


def _deployment_detail(apps: dict[str, Any]) -> str:
    """Per-deployment statuses for progress lines (Ray 2.57 v2 API).

    The v2 ``/api/serve/applications/`` payload nests a ``deployments``
    dict under each application, whose values carry the
    ``DeploymentStatus`` (``UPDATING``/``HEALTHY``/...) of each
    deployment.  Surfacing these per-poll shows *which* deployment is
    still starting — e.g. TorchProbe HEALTHY while TfProbe is still
    UPDATING — instead of one coarse application status.

    Args:
        apps: The applications dict from serve_status().

    Returns:
        'Dep=STATUS, ...' for all deployments, or "" when the payload
        carries no deployment detail (e.g. a bare-status shape).
    """
    parts: list[str] = []
    for app in apps.values():
        if not isinstance(app, dict):
            continue
        deps = app.get("deployments")
        if not isinstance(deps, dict):
            continue
        for dep_name, dep in deps.items():
            if isinstance(dep, dict):
                parts.append(f"{dep_name}={dep.get('status', 'UNKNOWN')}")
    return ", ".join(parts)


def _readiness_settings() -> tuple[float, float]:
    """Read the readiness-wait knobs from the environment (D25).

    Read at call time (not import time) so a test can override them.

    Returns:
        ``(timeout_s, interval_s)``: total wait budget and poll interval,
        from ``SPIKE_READINESS_TIMEOUT_S`` (default 300s — the fixture
        images are ~14-19GB and first podman start is slow) and
        ``SPIKE_READINESS_POLL_S`` (default 5s).
    """
    timeout_s = float(os.environ.get("SPIKE_READINESS_TIMEOUT_S", "300"))
    interval_s = float(os.environ.get("SPIKE_READINESS_POLL_S", "5"))
    return timeout_s, interval_s


def _permanent_failure(apps: dict[str, Any]) -> str | None:
    """Describe a permanent failure, if the statuses indicate one.

    In Ray 2.57 the terminal failure states are ``DEPLOY_FAILED`` on
    ``ApplicationStatus`` (``ray/serve/schema.py:1176``) and
    ``DeploymentStatus`` (``ray/serve/_private/common.py:199``); the
    deployment's ``message`` field carries the details (``DeploymentDetails``,
    ``schema.py:1363``). ``UNHEALTHY`` is NOT treated as permanent: Ray
    can recover it (e.g. after a replica restart), so it keeps waiting.

    Args:
        apps: The applications dict from serve_status().

    Returns:
        A human-readable description of the failure, or None if the
        statuses still look like normal progress.
    """
    for name, app in apps.items():
        if not isinstance(app, dict):
            continue
        if str(app.get("status", "")) == "DEPLOY_FAILED":
            return (
                f"app {name} is DEPLOY_FAILED: "
                f"{app.get('message', '<no message>')}"
            )
        for dep_name, dep in (app.get("deployments") or {}).items():
            if not isinstance(dep, dict):
                continue
            if str(dep.get("status", "")) == "DEPLOY_FAILED":
                detail = dep.get("message", "<no message>")
                dead = dep.get("recent_dead_replicas") or []
                if dead:
                    detail = (
                        f"{detail} ({len(dead)} recently-stopped replica(s))"
                    )
                return (
                    f"deployment {name}/{dep_name} is DEPLOY_FAILED: {detail}"
                )
    return None


def _wait_for_running(
    recorder: Recorder,
    outcome: StepOutcome,
    status_fn: Any = serve_status,
) -> bool:
    """Poll serve_status() until every application reports RUNNING.

    D25: the wait budget is now configurable —
    ``SPIKE_READINESS_TIMEOUT_S`` (default 300s, was a hard-coded
    30 polls x 2s = 60s, too short for 14-19GB images) and
    ``SPIKE_READINESS_POLL_S`` (default 5s). Progress is printed on
    every status change plus a heartbeat every 6 polls, so a stalled
    wait is distinguishable from a hung one. A permanent failure
    (``DEPLOY_FAILED``) fails fast instead of waiting out the budget.

    On timeout the final status is recorded and a harness failure is
    reported (D21: exit 2): a deployment that never reaches RUNNING
    cannot answer the introspect probes, so the required observation
    cannot be made.

    Args:
        recorder: The step's Recorder, used to log the final status.
        outcome: Collects the harness failure on timeout or failure.
        status_fn: Status source (defaults to ``serve_status``);
            inject a stub for testing.

    Returns:
        True if all applications reached RUNNING within the window.
    """
    timeout_s, interval_s = _readiness_settings()
    deadline = time.monotonic() + timeout_s
    print(
        f"\nWaiting for Serve to stabilize "
        f"(budget {timeout_s:.0f}s, polling every {interval_s:.0f}s)..."
    )
    apps: dict[str, Any] = {}
    last_content: str | None = None
    poll = 0
    while True:
        poll += 1
        try:
            status = status_fn()
        except Exception as e:
            print(f"  [{poll}] serve status unreachable: {e} — retrying")
            if time.monotonic() >= deadline:
                break
            time.sleep(interval_s)
            continue
        apps = status.get("applications", {})
        if apps:
            failed = _permanent_failure(apps)
            if failed:
                recorder.write(
                    block("serve status", json.dumps(status, indent=2))
                )
                outcome.harness(
                    f"Deployment failed permanently: {failed} — further "
                    "polling is useless, the introspect probes cannot be "
                    "answered."
                )
                return False
            all_healthy = all(
                _app_status(a) in ("RUNNING", "HEALTHY")
                for a in apps.values()
            )
            if all_healthy:
                print(
                    f"Serve is RUNNING ({len(apps)} apps: "
                    f"{', '.join(apps.keys())}) after {poll} poll(s)"
                )
                return True
            content = _status_summary(apps)
            detail = _deployment_detail(apps)
            if detail:
                content += f"  ({detail})"
        else:
            content = "no applications reported yet"
        line = f"  [{poll}] {content}"
        if content != last_content or poll % 6 == 0:
            print(line)
        last_content = content
        if time.monotonic() >= deadline:
            break
        time.sleep(interval_s)
    print(f"Serve did not stabilize within {timeout_s:.0f}s — status:")
    try:
        status = status_fn()
        apps = status.get("applications", {})
        recorder.write(block("serve status", json.dumps(status, indent=2)))
    except Exception as e:
        apps = {}
        recorder.write(block("serve status", f"<unreachable: {e}>"))
    outcome.harness(
        f"Deployment never reached RUNNING within {timeout_s:.0f}s "
        f"(final statuses: {_status_summary(apps) or '<none>'}) — the "
        "introspect probes cannot be answered (worker failed to start? "
        "see the 'serve status' block above)."
    )
    return False


def _check_probe_content(outcome: StepOutcome, probe: str, data: dict) -> None:
    """Compare a probe response against the fixture expectations.

    A mismatch is a negative *finding*, not a harness failure: the
    deployment is running and answering (the observation was made) but it
    indicates the wrong image or framework.

    Args:
        outcome: Collects the finding on mismatch.
        probe: Probe name ("TorchProbe" or "TfProbe").
        data: The introspect response from the probe.
    """
    expected = EXPECTED[probe]
    marker = str(data.get("image_marker", ""))
    framework = str(data.get("framework", ""))
    problems = []
    if not marker.startswith(expected["marker_prefix"]):
        problems.append(
            f"image_marker={marker!r} (expected prefix "
            f"{expected['marker_prefix']!r})"
        )
    if framework != expected["framework"]:
        problems.append(
            f"framework={framework!r} (expected {expected['framework']!r})"
        )
    if problems:
        outcome.finding(
            f"{probe} answered with unexpected content: " + "; ".join(problems)
        )


def _print_summary(outcome: StepOutcome) -> None:
    """Print the final verdict, labelling each failure kind explicitly.

    Args:
        outcome: The collected harness failures and findings.
    """
    if outcome.harness_failures:
        print("")
        print("STEP 1 RESULT: HARNESS FAILURE — exit code 2")
        print("A required observation could not be made; the environment,")
        print("not the experiment, is at fault. The findings from this run")
        print("are incomplete and must not be treated as a pass:")
        for i, msg in enumerate(outcome.harness_failures, 1):
            print(f"  {i}. {msg}")
    if outcome.findings:
        print("")
        print("STEP 1 RESULT: NEGATIVE FINDING(S) — exit code 3")
        print("The observations were made but answer the step's question")
        print("negatively. Recorded findings:")
        for i, msg in enumerate(outcome.findings, 1):
            print(f"  {i}. {msg}")
    if not outcome.harness_failures and not outcome.findings:
        print("")
        print("STEP 1 RESULT: all required observations made; no negative")
        print("findings — exit code 0")


def run(recorder: Recorder) -> int:
    """Run step 1's observations and return the process exit code.

    Args:
        recorder: The step's Recorder (stdout/stderr tee to the log).

    Returns:
        0 (clean), 2 (harness failure) or 3 (negative finding).
    """
    outcome = StepOutcome()

    print("=" * 60)
    print("STEP 1: Per-deployment image_uri")
    print("=" * 60)

    # ── Part A: Decorator form (step1_two_deployments.py) ──────
    print("")
    print("=== Part A: Decorator/ray_actor_options form ===")

    try:
        result = subprocess.run(
            [
                "serve",
                "deploy",
                "step1_two_deployments:application",
                "--name",
                "step1_app",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        recorder.write(block("serve deploy output", result.stdout + result.stderr))
        print(f"Deploy exit code: {result.returncode}")
        if result.returncode != 0:
            print("Decorator form REJECTED — continuing to YAML form")
            record(
                "step1", form="decorator", accepted=False,
                exit_code=result.returncode,
            )
            # The step's question was answered (negatively): this is a
            # finding, not a harness failure.
            outcome.finding(
                f"Decorator form REJECTED by `serve deploy` "
                f"(exit {result.returncode})."
            )
            deploy_ok = False
        else:
            print("Decorator form ACCEPTED")
            record("step1", form="decorator", accepted=True)
            deploy_ok = True
    except Exception as e:
        recorder.write(block("serve deploy error", str(e)))
        print(f"Deploy error: {e}")
        record("step1", form="decorator", harness_failure=str(e))
        outcome.harness(
            f"Could not invoke `serve deploy` (decorator form): {e}"
        )
        deploy_ok = False

    if deploy_ok:
        # Wait for the deployment(s) to reach RUNNING.
        _wait_for_running(recorder, outcome)

        # The probes are attempted even if stabilization timed out: they
        # produce the same recorded evidence as before (the
        # "<Probe> introspect error" blocks), and a probe that does
        # answer is information, not noise.
        for probe, url in (
            ("TorchProbe", TOOL_URL_TORCH),
            ("TfProbe", TOOL_URL_TF),
        ):
            print(f"\n--- {probe} introspect ---")
            try:
                result_data = post_introspect(url)
                recorder.write(
                    block(f"{probe} introspect", json.dumps(result_data, indent=2))
                )
                print(json.dumps(result_data, indent=2))
                record("step1", deployment=probe, result=result_data)
                _check_probe_content(outcome, probe, result_data)
            except Exception as e:
                print(f"Error calling {probe}: {e}")
                recorder.write(block(f"{probe} introspect error", str(e)))
                record("step1", deployment=probe, harness_failure=str(e))
                # Unreachable probe = harness/environment failure, not a
                # finding: the observation could not be made at all.
                outcome.harness(
                    f"{probe} probe could not be reached at {url} ({e}) — "
                    "the observation could not be made."
                )

    # ── Part B: YAML config form ───────────────────────────────
    print("")
    print("=== Part B: YAML config form ===")
    try:
        # Render ${VAR:default} placeholders before deploy — Ray does
        # yaml.safe_load with no substitution (diagnosis §2.2).
        result = apply_config("apps/step1_config.yaml")
        recorder.write(
            block("serve deploy (YAML) output", result.stdout + result.stderr)
        )
        print(f"YAML deploy exit code: {result.returncode}")
        if result.returncode == 0:
            print("YAML form ACCEPTED")
            record("step1", form="yaml", accepted=True)
        else:
            print("YAML form REJECTED")
            record(
                "step1", form="yaml", accepted=False,
                exit_code=result.returncode,
            )
            outcome.finding(
                f"YAML form REJECTED by `serve deploy` "
                f"(exit {result.returncode})."
            )
    except Exception as e:
        recorder.write(block("serve deploy (YAML) error", str(e)))
        print(f"YAML deploy error: {e}")
        record("step1", form="yaml", harness_failure=str(e))
        outcome.harness(f"Could not invoke `serve deploy` (YAML form): {e}")

    print("")
    print("--- STEP 1 OBSERVATIONS COMPLETE ---")
    _print_summary(outcome)
    return outcome.exit_code


if __name__ == "__main__":
    _recorder = Recorder("step1")
    try:
        _exit_code = run(_recorder)
    except Exception:
        import traceback

        print("\n" + "=" * 60)
        print("STEP 1: UNEXPECTED ERROR — recording and exiting")
        print("=" * 60)
        traceback.print_exc()
        print("Step failed with an unexpected error; review "
              "results/raw/step1-*.log")
        _recorder.close()
        sys.exit(1)
    _recorder.close()
    sys.exit(_exit_code)

"""Step 2 verification: app builder with baked-in weights.

Tests:
  1. Does the builder execute in the controller's environment?
     (Check builder-environment banner in controller logs)
  2. Do the two apps load their OWN image's checkpoint?
     (Assert weights_sha256 differs between apps)
  3. What is the local disk read time for the baked weights?

Per §0a: the weight-fetch-measurement half of this step is removed.
The load_seconds reported here is a local disk read, not a thrash-pricing
figure. State this explicitly.

Exit status (D21)
    0  All required observations were made and no negative finding was
       observed.
    1  Unexpected internal error (traceback printed).
    2  Harness/environment failure — a required observation could NOT be
       made: an app never reached RUNNING, a startup probe failed or timed
       out, or the weight hash comparison could not be made.
    3  Negative finding — the harness worked and the observation was made,
       but it answers the step's question negatively: weights_sha256 is
       identical between images, or the strict builder was rejected.

A probe answering with unexpected content is a *finding* (exit 3); a probe
that could not be reached at all is a *harness failure* (exit 2). Both are
printed with an explicit label and both prevent a false "success". All raw
output is recorded to results/raw/step2-*.log and
results/metrics/step2.jsonl regardless of the exit status.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
from recorder import Recorder, block, record
from serve_api import ServeAPIError, json_response, apply_config, serve_status

# One HTTP proxy serves the whole cluster on :8000; the two apps are
# separated by route_prefix (see apps/step2_config.yaml), not by port.
TORCH_URL = os.environ.get("SPIKE_SERVE_URL_TORCH", "http://localhost:8000/torch")
TF_URL = os.environ.get("SPIKE_SERVE_URL_TF", "http://localhost:8000/tf")

STARTUP_TIMEOUT = 60


def _startup_report(url: str) -> dict:
    """Request the tool's ``startup_report`` op (builder env + weights).

    Step 2's observations — ``sys_executable`` (builder environment),
    ``weights_sha256`` and ``weights_load_seconds`` — are produced by the
    ``startup_report`` op (toolkit/deployments.py). ``post_introspect``
    (op ``introspect``) does not return them, which is why the old
    script never had a hash to compare.

    Args:
        url: Tool endpoint (proxy port).

    Returns:
        The parsed JSON startup report.

    Raises:
        requests.exceptions.Timeout: The replica never answered in
            STARTUP_TIMEOUT seconds (worker stuck / not started).
        requests.exceptions.ConnectionError: Nothing is listening (proxy
            or app down).
        ServeAPIError: The proxy answered with a non-2xx status or a
            non-JSON body (D25: the status code and a body excerpt are
            carried in the error message instead of an opaque JSON
            decode failure).
    """
    resp = requests.post(
        url, json={"op": "startup_report"}, timeout=STARTUP_TIMEOUT,
    )
    return json_response(resp)


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
    still starting instead of one coarse application status.

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


def _wait_for_stable(
    recorder: Recorder,
    outcome: StepOutcome,
    status_fn: Any = serve_status,
) -> bool:
    """Poll serve_status() until at least two apps report RUNNING.

    D25: the wait budget is now configurable —
    ``SPIKE_READINESS_TIMEOUT_S`` (default 300s, was a hard-coded
    30 polls x 2s = 60s, too short for 14-19GB images) and
    ``SPIKE_READINESS_POLL_S`` (default 5s). Progress is printed on
    every status change plus a heartbeat every 6 polls, so a stalled
    wait is distinguishable from a hung one. A permanent failure
    (``DEPLOY_FAILED``) fails fast instead of waiting out the budget.

    On timeout the final status is recorded and a harness failure is
    reported (D21: exit 2): apps that never reach RUNNING cannot
    answer the startup probes, so the required observation cannot be
    made.

    Args:
        recorder: The step's Recorder, used to log the final status.
        outcome: Collects the harness failure on timeout or failure.
        status_fn: Status source (defaults to ``serve_status``);
            inject a stub for testing.

    Returns:
        True if at least two applications reached RUNNING in the window.
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
                    "polling is useless, the startup probes cannot be "
                    "answered."
                )
                return False
            healthy = all(
                _app_status(a) in ("RUNNING", "HEALTHY")
                for a in apps.values()
            )
            if healthy and len(apps) >= 2:
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
        f"Apps never reached RUNNING within {timeout_s:.0f}s "
        f"(final statuses: {_status_summary(apps) or '<none>'}) — the "
        "startup probes cannot be answered (worker failed to start? "
        "see the 'serve status' block above)."
    )
    return False


def _print_summary(outcome: StepOutcome) -> None:
    """Print the final verdict, labelling each failure kind explicitly.

    Args:
        outcome: The collected harness failures and findings.
    """
    if outcome.harness_failures:
        print("")
        print("STEP 2 RESULT: HARNESS FAILURE — exit code 2")
        print("A required observation could not be made; the environment,")
        print("not the experiment, is at fault. The findings from this run")
        print("are incomplete and must not be treated as a pass:")
        for i, msg in enumerate(outcome.harness_failures, 1):
            print(f"  {i}. {msg}")
    if outcome.findings:
        print("")
        print("STEP 2 RESULT: NEGATIVE FINDING(S) — exit code 3")
        print("The observations were made but answer the step's question")
        print("negatively. Recorded findings:")
        for i, msg in enumerate(outcome.findings, 1):
            print(f"  {i}. {msg}")
    if not outcome.harness_failures and not outcome.findings:
        print("")
        print("STEP 2 RESULT: all required observations made; no negative")
        print("findings — exit code 0")


def run(recorder: Recorder) -> int:
    """Run step 2's observations and return the process exit code.

    Args:
        recorder: The step's Recorder (stdout/stderr tee to the log).

    Returns:
        0 (clean), 2 (harness failure) or 3 (negative finding).
    """
    outcome = StepOutcome()

    print("=" * 60)
    print("STEP 2: App builder, baked-in weights")
    print("=" * 60)

    # ── Deploy generic builder config ──────────────────────────
    print("")
    print("=== Deploying generic builder config ===")
    try:
        result = apply_config("apps/step2_config.yaml")
        recorder.write(
            block("serve deploy (generic) output", result.stdout + result.stderr)
        )
        print(f"Exit code: {result.returncode}")
    except Exception as e:
        recorder.write(block("serve deploy (generic) error", str(e)))
        print(f"Deploy error: {e}")
        record("step2", phase="deploy_generic", harness_failure=str(e))
        outcome.harness(f"Could not invoke `serve deploy` (generic): {e}")
        result = None

    # Wait for Serve to stabilize
    if result is not None:
        _wait_for_stable(recorder, outcome)

    # ── Check builder banner ───────────────────────────────────
    # The builder banner is printed at module import time inside
    # the controller process. We check it by calling startup_report
    # and looking for the builder's sys.executable vs the image's.
    print("\n=== Checking builder environment ===")

    torch_startup = None
    tf_startup = None

    try:
        # D21: the old code called the `introspect` op here, whose
        # response never contains weights_sha256 — the comparison below
        # could therefore never succeed even on a healthy cluster.
        torch_startup = _startup_report(TORCH_URL)
        record("step2", app="torch", type="startup", data=torch_startup)
        print(f"tool_torch startup_report: {json.dumps(torch_startup, indent=2)}")
    except Exception as e:
        print(f"Error calling tool_torch: {e}")
        recorder.write(block("tool_torch startup error", str(e)))
        record("step2", app="torch", type="startup", harness_failure=str(e))
        # Unreachable probe = harness/environment failure, not a finding.
        outcome.harness(
            f"tool_torch probe could not be reached at {TORCH_URL} ({e}) "
            "— the observation could not be made."
        )

    try:
        tf_startup = _startup_report(TF_URL)
        record("step2", app="tf", type="startup", data=tf_startup)
        print(f"tool_tf startup_report: {json.dumps(tf_startup, indent=2)}")
    except Exception as e:
        print(f"Error calling tool_tf: {e}")
        recorder.write(block("tool_tf startup error", str(e)))
        record("step2", app="tf", type="startup", harness_failure=str(e))
        outcome.harness(
            f"tool_tf probe could not be reached at {TF_URL} ({e}) "
            "— the observation could not be made."
        )

    # ── Check weights_sha256 differs between apps ──────────────
    print("\n=== Verifying per-app checkpoint isolation ===")
    if torch_startup and tf_startup:
        torch_hash = torch_startup.get("weights_sha256", "")
        tf_hash = tf_startup.get("weights_sha256", "")
        torch_marker = torch_startup.get("image_marker", "")
        tf_marker = tf_startup.get("image_marker", "")

        print(f"  tool_torch marker: {torch_marker}")
        print(f"  tool_torch weights_sha256: {torch_hash[:16]}...")
        print(f"  tool_tf marker: {tf_marker}")
        print(f"  tool_tf weights_sha256: {tf_hash[:16]}...")

        if torch_hash and tf_hash and torch_hash != tf_hash:
            print("  OK: weights_sha256 differs between images — per-app "
                  "isolation confirmed")
            record("step2", check="weights_sha256_differs", pass_=True)
        elif torch_hash and tf_hash:
            print("  WARNING: weights_sha256 is the same for both images "
                  "— assets may not differ")
            record("step2", check="weights_sha256_differs", pass_=False)
            # Both hashes were read (the observation was made) but the
            # result answers step 2's question negatively: a finding.
            outcome.finding(
                "weights_sha256 is the same for both images — the baked "
                "assets may not differ (per-app isolation not confirmed)."
            )
        else:
            print("  WARNING: Could not compare sha256 values")
            record(
                "step2", check="weights_sha256_differs",
                harness_failure="missing weights_sha256 field(s)",
            )
            # Neither hash could be read from the responses — the
            # comparison observation could not be made.
            outcome.harness(
                "Could not compare weights_sha256: one or both startup "
                "responses lack the field."
            )

    # ── Deploy strict variant ──────────────────────────────────
    print("\n=== Deploying strict builder (imports torch) ===")
    try:
        result = apply_config("apps/step2_config_strict.yaml")
        recorder.write(
            block("serve deploy (strict) output", result.stdout + result.stderr)
        )
        print(f"Exit code: {result.returncode}")
        if result.returncode == 0:
            print("Strict builder ACCEPTED — builder may run in tool_torch image")
            record("step2", check="strict_builder", accepted=True)
        else:
            print("Strict builder REJECTED — builder likely runs in controller env")
            record(
                "step2", check="strict_builder", accepted=False,
                exit_code=result.returncode,
            )
            # The step's question was answered (negatively): a finding.
            outcome.finding(
                "Strict builder REJECTED — the builder likely runs in the "
                "controller environment, not the tool_torch image."
            )
    except Exception as e:
        recorder.write(block("serve deploy (strict) error", str(e)))
        print(f"Deploy error: {e}")
        record("step2", check="strict_builder", harness_failure=str(e))
        outcome.harness(f"Could not invoke `serve deploy` (strict): {e}")

    # ── Explicit §0a note ──────────────────────────────────────
    print("")
    print("=== §0a note ===")
    print("  Weight-fetch latency measurement was removed per scope amendment.")
    print("  The load_seconds values above are local disk reads, NOT "
          "thrash-pricing figures.")
    print("  This does NOT bias the framework decision (the fetch cost "
          "applies to both)")
    print("  architectures equally, but it is an open input to sizing work.")

    print("")
    print("--- STEP 2 OBSERVATIONS COMPLETE ---")
    _print_summary(outcome)
    return outcome.exit_code


if __name__ == "__main__":
    _recorder = Recorder("step2")
    try:
        _exit_code = run(_recorder)
    except Exception:
        import traceback

        print("\n" + "=" * 60)
        print("STEP 2: UNEXPECTED ERROR — recording and exiting")
        print("=" * 60)
        traceback.print_exc()
        print("Step failed with an unexpected error; review "
              "results/raw/step2-*.log")
        _recorder.close()
        sys.exit(1)
    _recorder.close()
    sys.exit(_exit_code)

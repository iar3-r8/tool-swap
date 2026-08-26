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
from serve_api import apply_config, serve_status

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
    """
    resp = requests.post(
        url, json={"op": "startup_report"}, timeout=STARTUP_TIMEOUT,
    )
    return resp.json()


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


def _wait_for_stable(recorder: Recorder, outcome: StepOutcome) -> bool:
    """Poll serve_status() until at least two apps report RUNNING.

    Same loop as before (30 polls x 2s, progress lines included). On
    timeout the final status is recorded and a harness failure is
    reported: apps that never reach RUNNING cannot answer the startup
    probes, so the required observation cannot be made.

    Args:
        recorder: The step's Recorder, used to log the final status.
        outcome: Collects the harness failure on timeout.

    Returns:
        True if at least two applications reached RUNNING in the window.
    """
    print("\nWaiting for Serve to stabilize...")
    for i in range(30):
        try:
            status = serve_status()
        except Exception as e:
            print(f"  ... serve status unreachable: {e} ...")
            time.sleep(2)
            continue
        apps = status.get("applications", {})
        if not apps:
            print("  ... waiting for apps to appear ...")
            time.sleep(2)
            continue
        # In Ray 2.57+, applications is a dict {name: details} or
        # {name: status_str}.
        healthy = True
        for a in apps.values():
            if _app_status(a) not in ("RUNNING", "HEALTHY"):
                healthy = False
        if healthy and len(apps) >= 2:
            print(f"Serve is RUNNING ({len(apps)} apps: {', '.join(apps.keys())})")
            return True
        status_str = ", ".join(
            f"{k}={_app_status(v)}" for k, v in apps.items()
        )
        print(f"  [{i + 1}/30] Statuses: {status_str} ... waiting")
        time.sleep(2)
    print("Serve did not stabilize — status:")
    try:
        status = serve_status()
        apps = status.get("applications", {})
        recorder.write(block("serve status", json.dumps(status, indent=2)))
    except Exception as e:
        apps = {}
        recorder.write(block("serve status", f"<unreachable: {e}>"))
    outcome.harness(
        "Apps never reached RUNNING within 60s "
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

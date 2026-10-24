"""The five harness-correctness properties, proven against a fake runner
before any real Mei inference is wired in:

1. Completion/crash/hang each produce the correct execution_status.
2. A timeout kills the runner and its children without killing a
   separately-launched target app.
3. A fake self-reported success cannot override an independently failed
   check.
4. Ambiguous app ownership blocks destructive cleanup.
5. Evidence survives a failed cleanup, and the failure is recorded, not
   swallowed.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from harness.app_manager import close_owned_app, is_alive, launch_target_app
from harness.supervisor import FakeTaskSpec, run_task

FAKE_RUNNER = [sys.executable, "-m", "harness.fake_runner"]


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    d = tmp_path / "run"
    d.mkdir()
    return d


def _spec(run_dir, mode, timeout_s=5.0, marker_path=None, spawn_child=False,
          verifier=None, teardown=None):
    events_path = run_dir / "events.jsonl"
    self_report_path = run_dir / "self_report.json"
    cmd = FAKE_RUNNER + [
        "--mode", mode,
        "--events-out", str(events_path),
        "--self-report-out", str(self_report_path),
    ]
    if marker_path:
        cmd += ["--marker-path", str(marker_path)]
    if spawn_child:
        cmd += ["--spawn-child"]
    return FakeTaskSpec(
        name=f"test-{mode}",
        run_dir=run_dir,
        runner_cmd=cmd,
        timeout_s=timeout_s,
        events_path=events_path,
        self_report_path=self_report_path,
        verifier=verifier or (lambda spec: True),
        teardown=teardown,
    )


# --- Property 1: completion / crash / hang statuses -------------------------

def test_status_completed(run_dir):
    marker = run_dir / "marker.txt"
    spec = _spec(run_dir, "success", marker_path=marker, verifier=lambda s: marker.exists())
    result = run_task(spec)
    assert result.execution_status == "completed"
    assert result.task_verdict == "pass"
    assert result.self_report == "success"
    assert result.classification == "correct"


def test_status_crashed(run_dir):
    spec = _spec(run_dir, "crash", verifier=lambda s: False)
    result = run_task(spec)
    assert result.execution_status == "crashed"
    assert result.self_report == "none"


def test_status_timeout(run_dir):
    spec = _spec(run_dir, "hang", timeout_s=1.0, verifier=lambda s: False)
    start = time.time()
    result = run_task(spec)
    elapsed = time.time() - start
    assert result.execution_status == "timeout"
    assert result.self_report == "none"
    # Proves the hard kill actually fired rather than the test just waiting
    # out a long default.
    assert elapsed < 10


# --- Property 2: timeout kills the tree, not an unrelated target app --------

def test_timeout_kills_tree_not_target_app(run_dir):
    target = launch_target_app([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        spec = _spec(run_dir, "hang", timeout_s=1.0, spawn_child=True, verifier=lambda s: True)
        result = run_task(spec)
        assert result.execution_status == "timeout"
        time.sleep(0.3)  # let the OS reflect the kill
        assert is_alive(target), "target app must survive the runner's timeout kill"
    finally:
        target.proc.kill()
        target.proc.wait(timeout=5)


def test_timeout_kill_reaches_grandchild(run_dir):
    # The property above only proves the target app survives; this proves the
    # runner's own descendants actually die (the Job Object / killpg point).
    psutil = pytest.importorskip("psutil")
    spec = _spec(run_dir, "hang", timeout_s=1.5, spawn_child=True, verifier=lambda s: False)
    result = run_task(spec)
    assert result.execution_status == "timeout"
    events = [json.loads(l) for l in spec.events_path.read_text().splitlines()]
    child_pid = next(e["child_pid"] for e in events if e["type"] == "child_spawned")
    time.sleep(0.3)
    alive = psutil.pid_exists(child_pid) and \
        psutil.Process(child_pid).status() != psutil.STATUS_ZOMBIE
    assert not alive, "runner's grandchild survived the timeout kill"


# --- Property 3: self-reported success cannot override the verifier --------

def test_false_success_cannot_override_verifier(run_dir):
    marker = run_dir / "marker.txt"  # "lie" mode never creates this
    spec = _spec(run_dir, "lie", marker_path=marker, verifier=lambda s: marker.exists())
    result = run_task(spec)
    assert result.self_report == "success"
    assert result.task_verdict == "fail"
    assert result.classification == "false_success"


# --- Property 4: ambiguous ownership blocks destructive cleanup ------------

def test_ambiguous_ownership_blocks_cleanup(run_dir):
    target = launch_target_app([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        outcome = close_owned_app(target, ownership_confirmed=False)
        assert outcome == {"closed": False, "reason": "ownership_ambiguous"}
        assert is_alive(target), "ambiguous ownership must not result in a kill"
    finally:
        target.proc.kill()
        target.proc.wait(timeout=5)


# --- Property 5: evidence survives a failed cleanup -------------------------

def test_evidence_survives_failed_cleanup(run_dir):
    marker = run_dir / "marker.txt"

    def failing_teardown(spec):
        raise RuntimeError("simulated teardown failure")

    spec = _spec(run_dir, "success", marker_path=marker,
                 verifier=lambda s: marker.exists(), teardown=failing_teardown)
    result = run_task(spec)
    assert result.cleanup["ok"] is False
    assert any("cleanup_error" in e for e in result.errors)
    for path in result.evidence:
        assert Path(path).exists()

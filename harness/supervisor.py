"""Minimal supervisor state machine.

PREPARE -> LAUNCH -> RUNNING -> {COMPLETED, CRASHED, TIMEOUT} -> SETTLE
-> VERIFY -> CAPTURE_ARTIFACTS -> CLEANUP -> RECORD

Originally scoped to proving five harness-correctness properties against a
fake runner (see harness/tests/test_supervisor_properties.py); the same
state machine now also drives the real Mei runner (harness/mei_runner.py).

Key invariants enforced here:
  - The supervisor is the sole source of the final verdict; a self-reported
    success is recorded but never substitutes for the independent verifier.
  - VERIFY always runs, even after a timeout/crash -- the task may have
    genuinely finished before being killed.
  - Evidence (events log, self-report file, runner log) is captured before
    CLEANUP runs, and a cleanup failure is recorded rather than swallowed or
    allowed to delete already-captured evidence.
  - Anything the runner spawned is owned by the run: the runner's whole
    process tree is killed at CLEANUP even after a normal exit, so leftovers
    can't leak into the next task.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .process_group import ContainedProcess


@dataclass
class TaskSpec:
    name: str
    run_dir: Path
    runner_cmd: List[str]
    timeout_s: float
    events_path: Path
    self_report_path: Path
    verifier: Callable[["TaskSpec"], bool] = lambda spec: True
    setup: Optional[Callable[["TaskSpec"], None]] = None
    teardown: Optional[Callable[["TaskSpec"], None]] = None
    # Real-runner extras; the fake runner leaves these unset.
    log_path: Optional[Path] = None
    cwd: Optional[Path] = None
    env: Optional[Dict[str, str]] = None


# Kept so the original property tests read unchanged.
FakeTaskSpec = TaskSpec


@dataclass
class TaskResult:
    name: str
    execution_status: str  # completed | timeout | crashed | setup_failed
    task_verdict: str      # pass | fail | inconclusive | verifier_error
    self_report: str       # success | failure | none
    classification: str
    errors: List[str] = field(default_factory=list)
    evidence: List[str] = field(default_factory=list)
    cleanup: dict = field(default_factory=dict)
    exit_code: Optional[int] = None
    duration_s: float = 0.0


def _read_self_report(path: Path) -> str:
    if not path.exists():
        return "none"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("self_report", "none")
    except (json.JSONDecodeError, OSError):
        return "none"


def _classify(task_verdict: str, self_report: str) -> str:
    if task_verdict == "inconclusive" or task_verdict == "verifier_error":
        return "inconclusive"
    if task_verdict == "pass":
        return "correct" if self_report in ("success", "none") else "false_failure"
    if task_verdict == "fail":
        return "false_success" if self_report == "success" else "correctly_failed"
    return "inconclusive"


def _record(spec: TaskSpec, result: TaskResult) -> TaskResult:
    try:
        (spec.run_dir / "result.json").write_text(
            json.dumps(asdict(result), indent=2), encoding="utf-8")
    except OSError:
        pass
    return result


def run_task(spec: TaskSpec) -> TaskResult:
    spec.run_dir.mkdir(parents=True, exist_ok=True)
    errors: List[str] = []

    # --- PREPARE ---
    if spec.setup is not None:
        try:
            spec.setup(spec)
        except Exception as exc:
            return _record(spec, TaskResult(
                name=spec.name,
                execution_status="setup_failed",
                task_verdict="inconclusive",
                self_report="none",
                classification="inconclusive",
                errors=[f"setup_failed: {exc}"],
            ))

    # --- LAUNCH ---
    popen_kwargs: dict = {}
    if spec.cwd is not None:
        popen_kwargs["cwd"] = str(spec.cwd)
    if spec.env is not None:
        popen_kwargs["env"] = spec.env
    log_file = open(spec.log_path, "w", encoding="utf-8") if spec.log_path else None
    if log_file is not None:
        popen_kwargs["stdout"] = log_file
        popen_kwargs["stderr"] = log_file

    proc = ContainedProcess(spec.runner_cmd, **popen_kwargs)
    started = time.time()
    try:
        proc.start()
    except Exception as exc:
        if log_file is not None:
            log_file.close()
        return _record(spec, TaskResult(
            name=spec.name,
            execution_status="setup_failed",
            task_verdict="inconclusive",
            self_report="none",
            classification="inconclusive",
            errors=[f"launch_failed: {exc}"],
        ))

    # --- RUNNING -> terminal execution_status ---
    exit_code = proc.wait(timeout=spec.timeout_s)
    duration_s = time.time() - started
    if exit_code is None:
        proc.kill_tree()
        execution_status = "timeout"
    elif exit_code == 0:
        execution_status = "completed"
    else:
        execution_status = "crashed"
    if log_file is not None:
        log_file.close()

    # --- SETTLE ---
    # Real harness: bounded, condition-based polling (file stability, dialog
    # closed, etc). A fixed short pause is sufficient for file-system tasks.
    time.sleep(0.05)

    # --- VERIFY ---
    # Always runs, regardless of execution_status: a killed/crashed run may
    # still have produced a verifiable effect before it died.
    self_report = _read_self_report(spec.self_report_path)
    try:
        verified = spec.verifier(spec)
        task_verdict = "pass" if verified else "fail"
    except Exception as exc:
        task_verdict = "verifier_error"
        errors.append(f"verifier_error: {exc}")

    # --- CAPTURE_ARTIFACTS ---
    # Snapshot evidence paths now, before CLEANUP runs, so a teardown failure
    # (or a teardown that deletes working files) can never erase evidence
    # that was already captured.
    candidates = [spec.events_path, spec.self_report_path, spec.log_path]
    evidence = [str(p) for p in candidates if p is not None and p.exists()]

    # --- CLEANUP ---
    proc.kill_tree()  # idempotent; reaps anything the runner left behind
    cleanup_result: dict = {"ok": True}
    if spec.teardown is not None:
        try:
            spec.teardown(spec)
        except Exception as exc:
            cleanup_result = {"ok": False, "error": str(exc)}
            errors.append(f"cleanup_error: {exc}")

    # --- RECORD ---
    return _record(spec, TaskResult(
        name=spec.name,
        execution_status=execution_status,
        task_verdict=task_verdict,
        self_report=self_report,
        classification=_classify(task_verdict, self_report),
        errors=errors,
        evidence=evidence,
        cleanup=cleanup_result,
        exit_code=exit_code,
        duration_s=round(duration_s, 2),
    ))

"""Tests for per-attempt tool-call scoring (harness/scoring.py)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from harness.scoring import load_attempts, path_matches, score_attempts, summarize
from harness.supervisor import TaskSpec, run_task

TARGET = r"C:\Users\Asus\Desktop\mei_harness_abc123"
FOLDER = {"action": "create_file_or_folder",
          "args": {"path": {"kind": "path", "expected": TARGET},
                   "is_dir": {"kind": "bool", "expected": True, "default": False}}}
FILE = {"action": "create_file_or_folder",
        "args": {"path": {"kind": "path", "expected": TARGET},
                 "is_dir": {"kind": "bool", "expected": False, "default": False}}}


def attempt(outcome, params=None, action="create_file_or_folder", **extra):
    return {"outcome": outcome, "action": action, "parameters": params or {},
            "grammar_mode": "per_tool", **extra}


def write_events(path: Path, attempts):
    lines = [json.dumps({"type": "runner_started"})]
    lines += [json.dumps({"type": "mei_event", "event": "TOOL_CALL_PROPOSED", "data": a}) for a in attempts]
    lines.append(json.dumps({"type": "mei_event", "event": "PLAN_COMPLETED", "data": {}}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_attempts_reads_only_attempt_events(tmp_path):
    ev = tmp_path / "events.jsonl"
    write_events(ev, [attempt("executed", {"path": TARGET, "is_dir": True})])
    assert len(load_attempts(ev)) == 1
    assert load_attempts(tmp_path / "missing.jsonl") == []


def test_folder_correct_first_try():
    s = score_attempts([attempt("executed", {"path": "C:/Users/Asus/Desktop/mei_harness_abc123",
                                             "is_dir": True}, result_success=True)], FOLDER)
    assert s["first_attempt"]["call_correct"] is True
    assert s["wrong_but_valid"] == 0


def test_folder_missing_is_dir_is_wrong_but_valid():
    s = score_attempts([attempt("executed", {"path": TARGET}, result_success=True)], FOLDER)
    is_dir = s["first_attempt"]["args"]["is_dir"]
    assert is_dir == {"present": False, "correct": False}
    assert s["first_attempt"]["call_correct"] is False
    assert s["wrong_but_valid"] == 1, "the original is_dir bug must show up as wrong-but-valid"


def test_file_task_absent_is_dir_is_correct_but_not_present():
    s = score_attempts([attempt("executed", {"path": TARGET}, result_success=True)], FILE)
    assert s["first_attempt"]["args"]["is_dir"] == {"present": False, "correct": True}
    assert s["first_attempt"]["call_correct"] is True


def test_overcorrected_file_task_is_caught():
    s = score_attempts([attempt("executed", {"path": TARGET, "is_dir": True}, result_success=True)], FILE)
    assert s["first_attempt"]["call_correct"] is False
    assert s["wrong_but_valid"] == 1


def test_outcomes_counted_and_abstention_tracked():
    s = score_attempts([
        attempt("no_tool", {"reason": "unsure"}, action="no_tool"),
        attempt("blocked_off_menu", {"path": TARGET}, action="delete_path"),
        attempt("executed", {"path": TARGET, "is_dir": True}, result_success=True),
    ], FOLDER)
    assert s["outcomes"] == {"no_tool": 1, "blocked_off_menu": 1, "executed": 1}
    assert s["no_tool"] == 1
    assert s["first_attempt"]["tool_name_correct"] is False
    assert s["any_call_correct"] is True


def test_relative_desktop_path_matches():
    assert path_matches("Desktop/mei_harness_abc123", TARGET)
    assert not path_matches("Documents/mei_harness_abc123", TARGET)
    assert not path_matches(None, TARGET)


def test_summarize_rates():
    runs = [score_attempts([attempt("executed", {"path": TARGET, "is_dir": True}, result_success=True)], FOLDER),
            score_attempts([attempt("executed", {"path": TARGET}, result_success=True)], FOLDER)]
    m = summarize(runs)
    assert m["first_call_correct_rate"] == 0.5
    assert m["first_arg_accuracy"]["is_dir"] == 0.5
    assert m["first_arg_present_rate"]["is_dir"] == 0.5
    assert m["wrong_but_valid_total"] == 1
    assert summarize([{}, {}]) == {}


def test_scorer_failure_is_recorded_and_never_changes_verdict(tmp_path):
    def broken_scorer(spec):
        raise RuntimeError("boom")
    spec = TaskSpec(
        name="scorer-test", run_dir=tmp_path / "run",
        runner_cmd=[sys.executable, "-m", "harness.fake_runner", "--mode", "success",
                    "--events-out", str(tmp_path / "e.jsonl"),
                    "--self-report-out", str(tmp_path / "s.json")],
        timeout_s=10, events_path=tmp_path / "e.jsonl", self_report_path=tmp_path / "s.json",
        verifier=lambda s: True, scorer=broken_scorer,
    )
    result = run_task(spec)
    assert result.task_verdict == "pass"
    assert any("scorer_error" in e for e in result.errors)
    assert result.call_scores == {}


def test_relative_path_rejects_parent_segments():
    assert not path_matches("../Desktop/mei_harness_abc123", TARGET)
    assert not path_matches("Desktop/../mei_harness_abc123", TARGET)
    assert path_matches("./Desktop/mei_harness_abc123", TARGET)


def test_path_case_follows_platform_rule():
    wrong_case = r"C:\Users\Asus\desktop\MEI_HARNESS_ABC123"
    assert path_matches(wrong_case, TARGET, case_insensitive=True)
    assert not path_matches(wrong_case, TARGET, case_insensitive=False)


def test_null_is_dir_counts_as_missing():
    s = score_attempts([attempt("executed", {"path": TARGET, "is_dir": None}, result_success=True)], FILE)
    assert s["first_attempt"]["args"]["is_dir"] == {"present": False, "correct": True}


def test_scoring_is_scoped_to_the_target_step():
    s = score_attempts([
        attempt("executed", {"path": "Desktop"}, action="cd", step_id="s1", result_success=True),
        attempt("executed", {"path": TARGET, "is_dir": True}, step_id="s2", result_success=True),
    ], FOLDER)
    assert s["target_step_found"] is True
    assert s["attempts"] == 1 and s["attempts_all_steps"] == 2 and s["steps_seen"] == 2
    assert s["first_attempt"]["call_correct"] is True
    assert s["wrong_but_valid"] == 0, "the cd step must not count as a wrong-but-valid create call"


def test_missing_target_step_is_flagged():
    s = score_attempts([attempt("executed", {"path": "Desktop"}, action="cd", step_id="s1")], FOLDER)
    assert s["target_step_found"] is False
    assert s["any_call_correct"] is False


def test_zero_attempt_runs_are_counted_separately():
    ok = score_attempts([attempt("executed", {"path": TARGET, "is_dir": True}, result_success=True)], FOLDER)
    empty = score_attempts([], FOLDER)
    m = summarize([ok, empty])
    assert m["runs_scored"] == 1 and m["runs_without_attempts"] == 1
    assert m["any_call_correct_rate"] == 1.0 and m["mean_attempts"] == 1.0

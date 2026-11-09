"""Score every planner tool-call attempt against the call a task expects.

Reads Mei's TOOL_CALL_PROPOSED events from events.jsonl. The task verdict
says whether the world ended up right; these scores say *why* — tool name vs
each argument, valid-but-wrong calls, abstentions — so a grammar change can be
judged on correctness, not just on whether output parsed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

ATTEMPT_EVENT = "TOOL_CALL_PROPOSED"


def load_attempts(events_path: Path) -> List[Dict[str, Any]]:
    attempts: List[Dict[str, Any]] = []
    if not events_path.exists():
        return attempts
    for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("type") == "mei_event" and rec.get("event") == ATTEMPT_EVENT:
            attempts.append(rec.get("data") or {})
    return attempts


def _norm_path(value: Any, case_insensitive: bool) -> str:
    s = str(value).replace("\\", "/").rstrip("/")
    return s.lower() if case_insensitive else s


def path_matches(value: Any, target: str, case_insensitive: Optional[bool] = None) -> bool:
    """Case is ignored only where the filesystem ignores it (Windows by
    default), so a wrong-case directory isn't scored correct elsewhere."""
    if value is None:
        return False
    if case_insensitive is None:
        case_insensitive = os.name == "nt"
    v, t = _norm_path(value, case_insensitive), _norm_path(target, case_insensitive)
    if v == t:
        return True
    # A relative "Desktop/<name>" is resolved against the home folder by the
    # executor, so it lands on the same target. Only that exact shape counts:
    # ".." segments could point anywhere.
    rel = v[2:] if v.startswith("./") else v
    parts = rel.split("/")
    if ".." in parts or len(parts) < 2 or parts[0].lower() != "desktop":
        return False
    return t.endswith("/" + rel)


def _arg_result(params: Dict[str, Any], name: str, rule: Dict[str, Any]) -> Dict[str, Any]:
    # An explicit null behaves like a missing key: the handler falls back to
    # the default (e.g. is_dir: null still creates a file).
    present = params.get(name) is not None
    value = params[name] if present else rule.get("default")
    if rule["kind"] == "path":
        correct = path_matches(value, rule["expected"])
    elif rule["kind"] == "bool":
        correct = value is not None and bool(value) == rule["expected"]
    else:
        correct = value == rule["expected"]
    return {"present": present, "correct": correct}


def score_call(call: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, Any]:
    params = call.get("parameters") if isinstance(call.get("parameters"), dict) else {}
    args = {name: _arg_result(params, name, rule) for name, rule in expected["args"].items()}
    tool_ok = call.get("action") == expected["action"]
    return {
        "action": call.get("action"),
        "outcome": call.get("outcome"),
        "tool_name_correct": tool_ok,
        "args": args,
        "call_correct": tool_ok and all(a["correct"] for a in args.values()),
    }


def target_step_attempts(attempts: List[Dict[str, Any]], expected: Dict[str, Any]):
    """Attempts belonging to the step meant to make the expected call.

    A multi-step plan (e.g. "go to Desktop", then "create the folder") would
    otherwise score the first step's attempts as first attempts at the
    expected call. The target step is the first step in which any attempt
    names the expected tool. If no step does, every attempt is returned and
    the second value is False, so the run still counts as a miss.
    """
    for a in attempts:
        if a.get("action") == expected["action"]:
            sid = a.get("step_id")
            return [x for x in attempts if x.get("step_id") == sid], True
    return list(attempts), False


def score_attempts(attempts: List[Dict[str, Any]], expected: Dict[str, Any]) -> Dict[str, Any]:
    """expected = {"action": str, "args": {name: {"kind": "path"|"bool"|"eq", "expected": ..., "default": ...}}}"""
    all_attempts = attempts
    attempts, target_found = target_step_attempts(all_attempts, expected)
    outcomes: Dict[str, int] = {}
    for a in attempts:
        outcomes[a.get("outcome", "unknown")] = outcomes.get(a.get("outcome", "unknown"), 0) + 1

    scored = [score_call(a, expected) for a in attempts]
    executed = [(a, s) for a, s in zip(attempts, scored) if a.get("outcome") == "executed"]
    first: Optional[Dict[str, Any]] = scored[0] if scored else None
    return {
        "attempts": len(attempts),
        "attempts_all_steps": len(all_attempts),
        "steps_seen": len({a.get("step_id") for a in all_attempts}),
        "target_step_found": target_found,
        "grammar_modes": sorted({str(a.get("grammar_mode")) for a in all_attempts}),
        "outcomes": outcomes,
        "first_attempt": first,
        "any_call_correct": any(s["call_correct"] for s in scored),
        # Ran without error, yet not the call the task needed: the shape of a
        # false success (e.g. create_file_or_folder without is_dir).
        "wrong_but_valid": sum(1 for a, s in executed if a.get("result_success") and not s["call_correct"]),
        "no_tool": outcomes.get("no_tool", 0),
    }


def summarize(call_scores: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate per-run call_scores into batch rates for the summary file."""
    scored = [c for c in call_scores if c]
    if not scored:
        return {}
    # A run with zero attempts (crash or timeout before the planner) says
    # nothing about tool calling. Count it separately instead of letting it
    # drag down rates whose other denominators exclude it.
    runs = [c for c in scored if c.get("attempts")]
    firsts = [c["first_attempt"] for c in runs if c.get("first_attempt")]

    def rate(n: int, d: int) -> Optional[float]:
        return round(n / d, 3) if d else None

    arg_names = sorted({name for f in firsts for name in f["args"]})
    return {
        "runs_scored": len(runs),
        "runs_without_attempts": len(scored) - len(runs),
        "target_step_missing": sum(1 for c in runs if c.get("target_step_found") is False),
        "first_call_correct_rate": rate(sum(f["call_correct"] for f in firsts), len(firsts)),
        "first_tool_name_accuracy": rate(sum(f["tool_name_correct"] for f in firsts), len(firsts)),
        "first_arg_accuracy": {n: rate(sum(f["args"][n]["correct"] for f in firsts if n in f["args"]), len(firsts))
                               for n in arg_names},
        "first_arg_present_rate": {n: rate(sum(f["args"][n]["present"] for f in firsts if n in f["args"]), len(firsts))
                                   for n in arg_names},
        "any_call_correct_rate": rate(sum(c["any_call_correct"] for c in runs), len(runs)),
        "wrong_but_valid_total": sum(c["wrong_but_valid"] for c in runs),
        "no_tool_total": sum(c["no_tool"] for c in runs),
        "mean_attempts": round(sum(c["attempts"] for c in runs) / len(runs), 2) if runs else None,
        "grammar_modes_seen": sorted({m for c in runs for m in c["grammar_modes"]}),
    }

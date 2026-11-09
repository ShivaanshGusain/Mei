"""Run real Mei tasks under the supervisor.

    python -m harness.run --task create_desktop_folder [--repeat N] [--timeout S]
                          [--grammar per_tool|name_only|off]

Each attempt gets its own folder under harness_runs/ holding runner.log,
events.jsonl, self_report.json and result.json.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from .scoring import summarize
from .supervisor import run_task
from .tasks import REPO_ROOT, TASKS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True, choices=sorted(TASKS))
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=600.0,
                        help="per-attempt wall clock, seconds (cold model loads are slow)")
    parser.add_argument("--memory", choices=["fresh", "real"], default="fresh")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "harness_runs")
    parser.add_argument("--grammar", choices=["per_tool", "name_only", "off"], default=None,
                        help="tool-call grammar for Mei (MEI_TOOL_GRAMMAR); default: Mei's own default")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results = []
    for i in range(1, args.repeat + 1):
        run_dir = args.out / f"{stamp}_{args.task}_{i:02d}"
        spec = TASKS[args.task](run_dir, timeout_s=args.timeout, memory=args.memory,
                                grammar=args.grammar)
        print(f"[harness] {args.task} #{i}/{args.repeat} -> {run_dir}")
        result = run_task(spec)
        results.append(result)
        print(f"[harness]   status={result.execution_status} verdict={result.task_verdict} "
              f"self_report={result.self_report} -> {result.classification} "
              f"({result.duration_s}s)")
        for err in result.errors:
            print(f"[harness]   error: {err}")

    passed = sum(r.task_verdict == "pass" for r in results)
    summary = {
        "task": args.task,
        "attempts": len(results),
        "passed": passed,
        "pass_rate": passed / len(results) if results else 0.0,
        "by_classification": {c: sum(r.classification == c for r in results)
                              for c in sorted({r.classification for r in results})},
        "timeouts": sum(r.execution_status == "timeout" for r in results),
        # Without --grammar the runner inherits this shell's MEI_TOOL_GRAMMAR,
        # so record that rather than claiming Mei's default.
        "grammar_requested": args.grammar or (f"inherited:{os.environ['MEI_TOOL_GRAMMAR']}"
                                              if os.environ.get("MEI_TOOL_GRAMMAR") else "default"),
        "call_metrics": summarize([r.call_scores for r in results]),
    }
    (args.out / f"{stamp}_{args.task}_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[harness] {passed}/{len(results)} passed")
    cm = summary["call_metrics"]
    if cm:
        print(f"[harness] first call correct: {cm['first_call_correct_rate']} | "
              f"arg accuracy: {cm['first_arg_accuracy']} | arg present: {cm['first_arg_present_rate']} | "
              f"wrong-but-valid: {cm['wrong_but_valid_total']} | no_tool: {cm['no_tool_total']} | "
              f"grammar seen: {cm['grammar_modes_seen']}")


if __name__ == "__main__":
    main()

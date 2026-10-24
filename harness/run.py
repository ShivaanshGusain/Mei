"""Run real Mei tasks under the supervisor.

    python -m harness.run --task create_desktop_folder [--repeat N] [--timeout S]

Each attempt gets its own folder under harness_runs/ holding runner.log,
events.jsonl, self_report.json and result.json.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

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
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results = []
    for i in range(1, args.repeat + 1):
        run_dir = args.out / f"{stamp}_{args.task}_{i:02d}"
        spec = TASKS[args.task](run_dir, timeout_s=args.timeout, memory=args.memory)
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
    }
    (args.out / f"{stamp}_{args.task}_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[harness] {passed}/{len(results)} passed")


if __name__ == "__main__":
    main()

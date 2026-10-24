"""Real Mei-runner subprocess: boots Mei like the TUI does, runs ONE command
through core.pipeline.process_user_command, and writes a self-report.

Invoked as: python -m harness.mei_runner --command <text> --events-out <path>
            --self-report-out <path> [--memory fresh|real] [--kuzu-dir <path>]
            [--dump-stacks-after <seconds>]

The self-report is only Mei's own claim (process_user_command's return
value). The supervisor never trusts it on its own -- the task's verifier
decides the verdict.

--memory fresh (default) points Kùzu at an empty per-run database, so every
run takes the full Tier-3 path and runs are comparable; it also keeps test
goals out of data/kuzu_memory and avoids the file lock if the TUI is open.

--dump-stacks-after arms faulthandler to dump every thread's stack to the
runner log shortly before the supervisor's hard kill, so a timeout records
where Mei was stuck instead of just that it was.
"""
from __future__ import annotations

import argparse
import faulthandler
import json
import os
import sys
import threading
import time
import traceback


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", required=True)
    parser.add_argument("--events-out", required=True)
    parser.add_argument("--self-report-out", required=True)
    parser.add_argument("--memory", choices=["fresh", "real"], default="fresh")
    parser.add_argument("--kuzu-dir", default=None)
    parser.add_argument("--dump-stacks-after", type=float, default=None)
    args = parser.parse_args()

    if args.dump_stacks_after:
        faulthandler.dump_traceback_later(args.dump_stacks_after, exit=False)

    events_lock = threading.Lock()

    def record(event_type: str, **payload) -> None:
        line = {"type": event_type, "t": time.time(), **payload}
        with events_lock, open(args.events_out, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, default=str) + "\n")

    def write_self_report(data: dict) -> None:
        with open(args.self_report_out, "w", encoding="utf-8") as f:
            json.dump(data, f, default=str)

    record("runner_started", command=args.command, memory=args.memory)
    started = time.time()

    try:
        # Same bootstrap order as MeiTUI._bootstrap_agent.
        from Mei.core.config import init_config
        from Mei.core.events import EventType, emit, get_event_bus

        config = init_config()
        if args.memory == "fresh":
            if not args.kuzu_dir:
                raise SystemExit("--memory fresh requires --kuzu-dir")
            config.kuzu.database_path = args.kuzu_dir

        get_event_bus().subscribe_all(
            lambda e: record("mei_event", event=e.type.name, source=e.source, data=e.data))

        from Mei.action.executor import get_executor
        from Mei.core.pipeline import process_user_command, start_pipeline
        from Mei.memory.graph import init_graph
        from Mei.memory.working import get_working_memory

        init_graph()
        working_memory = get_working_memory()
        get_executor()
        emit(EventType.AGENT_STARTED, source="harness")
        start_pipeline()
        record("bootstrap_done", seconds=round(time.time() - started, 2))

        from Mei.action.context import ExecutionContext
        ctx = ExecutionContext.empty()
        sid = getattr(working_memory, "_session_id", None)
        if sid:
            ctx.set_variable("session_id", sid)

        command_started = time.time()
        ok = process_user_command(args.command, ctx)
        write_self_report({
            "self_report": "success" if ok else "failure",
            "returned": ok,
            "command_seconds": round(time.time() - command_started, 2),
            "total_seconds": round(time.time() - started, 2),
        })
        record("runner_finished", returned=ok)
        exit_code = 0
    except BaseException as exc:
        write_self_report({"self_report": "failure", "returned": None,
                           "error": f"{type(exc).__name__}: {exc}"})
        record("runner_crashed", error=traceback.format_exc())
        traceback.print_exc()
        exit_code = 1

    faulthandler.cancel_dump_traceback_later()
    sys.stdout.flush()
    sys.stderr.flush()
    # Hard exit: Mei leaves non-daemon threads behind (browser session, model
    # loaders) that would otherwise keep a finished run alive until timeout.
    os._exit(exit_code)


if __name__ == "__main__":
    main()

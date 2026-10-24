"""Controllable stand-in for the real Mei-runner subprocess.

Exercises the supervisor's state machine -- timeouts, crashes, tree-kill
containment, and self-report-vs-independent-verification -- without paying
for real model inference, which is slow and (per the architecture audit)
genuinely cannot be cancelled once it's inside a blocking native call.

Invoked as: python -m harness.fake_runner --mode <mode> --events-out <path>
            --self-report-out <path> [--marker-path <path>] [--spawn-child]

Modes:
  success  -- completes normally, optionally writes a marker file (simulating
              a real, independently-checkable effect), reports success.
  crash    -- exits non-zero before writing anything.
  hang     -- ignores SIGTERM and sleeps forever, forcing the supervisor to
              hard-kill it (mirrors a blocked llama.cpp call).
  lie      -- completes normally and reports success WITHOUT producing the
              marker file -- a false success the verifier must catch.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time


def _write_json(path: str, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["success", "crash", "hang", "lie"])
    parser.add_argument("--events-out", required=True)
    parser.add_argument("--self-report-out", required=True)
    parser.add_argument("--marker-path", default=None)
    parser.add_argument("--spawn-child", action="store_true")
    args = parser.parse_args()

    def emit(event_type: str, **payload) -> None:
        line = {"type": event_type, "t": time.time(), "pid": os.getpid(), **payload}
        with open(args.events_out, "a") as f:
            f.write(json.dumps(line) + "\n")

    emit("started")

    if args.spawn_child:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3600)"])
        emit("child_spawned", child_pid=child.pid)

    if args.mode == "crash":
        emit("crashing")
        sys.exit(1)

    if args.mode == "hang":
        # A real stuck inference call never checks for cancellation either --
        # this models that rather than letting a polite SIGTERM short-circuit
        # the test.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        emit("hanging")
        while True:
            time.sleep(1)

    if args.mode == "success":
        time.sleep(0.2)
        if args.marker_path:
            with open(args.marker_path, "w") as f:
                f.write("done")
        _write_json(args.self_report_out, {"self_report": "success"})
        emit("finished", self_report="success")
        return

    if args.mode == "lie":
        time.sleep(0.2)
        _write_json(args.self_report_out, {"self_report": "success"})
        emit("finished", self_report="success (unearned)")
        return


if __name__ == "__main__":
    main()

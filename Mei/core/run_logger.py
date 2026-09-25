"""
Central run logger.

Captures EVERYTHING — stdout, stderr, and uncaught exceptions in the main
thread AND background threads (the TUI/headless worker thread) — into one
timestamped file per run, regardless of whether Mei is running in the TUI or
headless. The TUI already redirects sys.stdout/stderr into the trace pane
(TUIPrintCapture), which means a plain `> file.txt` shell redirect on the
process doesn't capture what the trace pane shows — Python's print() no
longer touches the real OS-level stdout once that reassignment happens. This
module solves that by wrapping whatever sys.stdout/stderr already are with a
"tee" that also appends to a file, so the existing behavior (trace pane
rendering, or plain console output in headless) is unchanged and everything
also lands in logs/run_<timestamp>.log.

Usage: call install_run_logging() once at startup, AFTER any other
sys.stdout/sys.stderr reassignment (e.g. after TUIPrintCapture is installed
in tui.py's on_mount) so this wraps the final stream, not one that then gets
overwritten.
"""
from __future__ import annotations

import faulthandler
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO

_log_file: Optional[TextIO] = None
_log_path: Optional[Path] = None
_stacks_file: Optional[TextIO] = None
_stacks_path: Optional[Path] = None


def _open_log_file() -> TextIO:
    global _log_file, _log_path
    if _log_file is not None:
        return _log_file
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_path = log_dir / f"run_{timestamp}.log"
    _log_file = open(_log_path, "a", encoding="utf-8", buffering=1)  # line-buffered
    return _log_file


class _TeeWriter:
    """Writes to an underlying stream AND appends to the run log file."""

    def __init__(self, underlying, log_file: TextIO):
        self._underlying = underlying
        self._log_file = log_file

    def write(self, text: str) -> int:
        try:
            self._log_file.write(text)
        except Exception:
            pass
        return self._underlying.write(text)

    def flush(self) -> None:
        try:
            self._log_file.flush()
        except Exception:
            pass
        try:
            self._underlying.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        # Delegate anything else (fileno, isatty, encoding, ...) to the
        # underlying stream, so code that pokes at sys.stdout beyond
        # write/flush (fairly common) keeps working.
        return getattr(self._underlying, name)


def _log_exception(exc_type, exc_value, exc_tb, thread_name: str = "MainThread") -> None:
    log_file = _open_log_file()
    try:
        log_file.write(f"\n--- UNCAUGHT EXCEPTION in {thread_name} ---\n")
        traceback.print_exception(exc_type, exc_value, exc_tb, file=log_file)
        log_file.flush()
    except Exception:
        pass


def install_run_logging(stack_dump_interval: float = 20.0) -> Path:
    """
    Wraps sys.stdout/sys.stderr so everything printed also lands in
    logs/run_<timestamp>.log, and installs exception hooks so uncaught errors
    in the main thread AND background threads are captured there too — even
    if the process or the TUI itself dies before you can read the console.

    Also starts a periodic `faulthandler.dump_traceback_later()`: every
    `stack_dump_interval` seconds, the exact stack of EVERY thread is written
    to logs/run_<timestamp>_stacks.log. This runs inside the process itself —
    no external tool, no attach/admin-rights concerns the way py-spy can hit
    on Windows — so if the process hangs, the last dump before it went quiet
    shows exactly which line every thread was on, automatically, with zero
    extra steps at debug time. A periodic snapshot isn't proof of a hang by
    itself (a long model load will legitimately show up in a few dumps in a
    row) — it's evidence to read alongside the regular log, not a verdict.

    Returns the log file path. Safe to call more than once (reuses the same
    files for the process's lifetime).
    """
    global _stacks_file, _stacks_path
    log_file = _open_log_file()

    if not isinstance(sys.stdout, _TeeWriter):
        sys.stdout = _TeeWriter(sys.stdout, log_file)
    if not isinstance(sys.stderr, _TeeWriter):
        sys.stderr = _TeeWriter(sys.stderr, log_file)

    def _excepthook(exc_type, exc_value, exc_tb):
        _log_exception(exc_type, exc_value, exc_tb, "MainThread")
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    sys.excepthook = _excepthook

    def _thread_excepthook(args) -> None:
        name = args.thread.name if args.thread else "UnknownThread"
        _log_exception(args.exc_type, args.exc_value, args.exc_traceback, name)
        threading.__excepthook__(args)
    threading.excepthook = _thread_excepthook

    if _stacks_file is None and _log_path is not None:
        _stacks_path = _log_path.with_name(_log_path.stem + "_stacks.log")
        _stacks_file = open(_stacks_path, "a", encoding="utf-8", buffering=1)
        faulthandler.dump_traceback_later(
            stack_dump_interval, repeat=True, file=_stacks_file, exit=False
        )

    print(f"[RunLogger] Logging this run to {_log_path}")
    print(f"[RunLogger] Periodic thread stacks (every {stack_dump_interval:.0f}s) -> {_stacks_path}")
    return _log_path


def get_log_path() -> Optional[Path]:
    return _log_path


def get_stacks_path() -> Optional[Path]:
    return _stacks_path

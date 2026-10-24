"""Target-application launch and ownership tracking.

The supervisor launches target apps directly -- never as children of the
contained Mei-runner process -- so they survive a timeout kill of that tree
and stay inspectable by the verifier afterward.

Ownership confirmation exists because launching a process doesn't always
establish exclusive ownership of "the app": a launcher can hand off to an
already-running instance and exit, and PIDs get reused. When ownership can't
be confirmed, cleanup must refuse rather than guess -- closing the wrong
window is worse than leaving a stray process for a human to clean up.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import List


@dataclass
class TargetApp:
    pid: int
    cmd: List[str]
    launched_at: float
    proc: subprocess.Popen


def launch_target_app(cmd: List[str]) -> TargetApp:
    proc = subprocess.Popen(cmd)
    return TargetApp(pid=proc.pid, cmd=list(cmd), launched_at=time.time(), proc=proc)


def is_alive(app: TargetApp) -> bool:
    return app.proc.poll() is None


def confirm_ownership(app: TargetApp, expected_pid: int) -> bool:
    """Minimal placeholder check: exact PID match.

    Production version should additionally compare OS process creation-time
    (not wall-clock-since-we-called-launch) plus associated window handles,
    per the architecture discussion -- PID alone is not proof of exclusive
    ownership once an app can hand off to a pre-existing instance.
    """
    return app.pid == expected_pid


def close_owned_app(app: TargetApp, ownership_confirmed: bool) -> dict:
    """Refuses destructive cleanup when ownership is ambiguous."""
    if not ownership_confirmed:
        return {"closed": False, "reason": "ownership_ambiguous"}
    app.proc.terminate()
    try:
        app.proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        app.proc.kill()
        app.proc.wait(timeout=5)
    return {"closed": True, "reason": None}

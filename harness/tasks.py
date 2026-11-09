"""Real Mei task definitions.

Each builder returns a TaskSpec whose verifier checks the world directly
(here: the file system), never Mei's self-report. Teardown follows the
ownership rule from app_manager: only remove what this run provably created.
"""
from __future__ import annotations

import os
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .scoring import load_attempts, score_attempts
from .supervisor import TaskSpec

REPO_ROOT = Path(__file__).resolve().parent.parent
DESKTOP = Path(os.path.expanduser("~")) / "Desktop"
NAME_PREFIX = "mei_harness_"


def _create_call_scorer(target: Path, is_dir: bool) -> Callable[[TaskSpec], Dict[str, Any]]:
    expected = {
        "action": "create_file_or_folder",
        "args": {
            "path": {"kind": "path", "expected": str(target)},
            # Absent is_dir falls back to the tool default (False): scored on the
            # effective value, with "present" reported separately.
            "is_dir": {"kind": "bool", "expected": is_dir, "default": False},
        },
    }
    return lambda spec: score_attempts(load_attempts(spec.events_path), expected)


def _mei_spec(name: str, run_dir: Path, command: str, timeout_s: float,
              memory: str, grammar: Optional[str] = None, **hooks) -> TaskSpec:
    events_path = run_dir / "events.jsonl"
    self_report_path = run_dir / "self_report.json"
    cmd = [
        sys.executable, "-m", "harness.mei_runner",
        "--command", command,
        "--events-out", str(events_path),
        "--self-report-out", str(self_report_path),
        "--memory", memory,
        "--kuzu-dir", str(run_dir / "kuzu_memory"),
        # Leave a few seconds for the dump to land before the hard kill.
        "--dump-stacks-after", str(max(timeout_s - 10, 1)),
    ]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"  # Mei prints non-ASCII; cp1252 would crash on redirect
    env["PYTHONUNBUFFERED"] = "1"      # keep the log current if the run is killed
    if grammar:
        env["MEI_TOOL_GRAMMAR"] = grammar  # per_tool | name_only | off (see Mei/cognition/llm/tool_schema.py)
    return TaskSpec(
        name=name,
        run_dir=run_dir,
        runner_cmd=cmd,
        timeout_s=timeout_s,
        events_path=events_path,
        self_report_path=self_report_path,
        log_path=run_dir / "runner.log",
        cwd=REPO_ROOT,  # config.yaml and model paths resolve from here
        env=env,
        **hooks,
    )


def create_desktop_folder(run_dir: Path, timeout_s: float, memory: str = "fresh",
                          desktop: Path = DESKTOP, grammar: Optional[str] = None) -> TaskSpec:
    """'Create a folder named mei_harness_<id> on the Desktop' -> is it a directory?"""
    folder_name = f"{NAME_PREFIX}{uuid.uuid4().hex[:8]}"
    target = desktop / folder_name
    state = {"existed_before": None}

    def setup(spec: TaskSpec) -> None:
        if not desktop.is_dir():
            raise RuntimeError(f"Desktop not found at {desktop}")
        state["existed_before"] = target.exists()
        if state["existed_before"]:
            raise RuntimeError(f"{target} already exists; refusing to run")

    def verifier(spec: TaskSpec) -> bool:
        return target.is_dir()

    def teardown(spec: TaskSpec) -> None:
        # Only delete what this run created: it must not have existed at
        # setup, and must be the exact uniquely-named path we asked for.
        if state["existed_before"] is not False:
            return
        if target.parent != desktop or not target.name.startswith(NAME_PREFIX):
            raise RuntimeError(f"refusing to delete unexpected path {target}")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "task.txt").write_text(f"target={target}\n", encoding="utf-8")
    return _mei_spec(
        name="create_desktop_folder",
        run_dir=run_dir,
        command=f"Create a folder named {folder_name} on the Desktop",
        timeout_s=timeout_s,
        memory=memory,
        setup=setup,
        verifier=verifier,
        teardown=teardown,
        grammar=grammar,
        scorer=_create_call_scorer(target, is_dir=True),
    )


def create_desktop_file(run_dir: Path, timeout_s: float, memory: str = "fresh",
                        desktop: Path = DESKTOP, grammar: Optional[str] = None) -> TaskSpec:
    """'Create a file named mei_harness_<id>.txt on the Desktop' -> is it a file, not a directory?

    Companion to create_desktop_folder: regresses the is_dir fix in the other
    direction. A fix that makes the model always pass is_dir=true (or a tool
    change that flips the default) would pass the folder task and silently
    fail this one — run both, never just one.
    """
    file_name = f"{NAME_PREFIX}{uuid.uuid4().hex[:8]}.txt"
    target = desktop / file_name
    state = {"existed_before": None}

    def setup(spec: TaskSpec) -> None:
        if not desktop.is_dir():
            raise RuntimeError(f"Desktop not found at {desktop}")
        state["existed_before"] = target.exists()
        if state["existed_before"]:
            raise RuntimeError(f"{target} already exists; refusing to run")

    def verifier(spec: TaskSpec) -> bool:
        return target.is_file()

    def teardown(spec: TaskSpec) -> None:
        # Only delete what this run created: it must not have existed at
        # setup, and must be the exact uniquely-named path we asked for.
        if state["existed_before"] is not False:
            return
        if target.parent != desktop or not target.name.startswith(NAME_PREFIX):
            raise RuntimeError(f"refusing to delete unexpected path {target}")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "task.txt").write_text(f"target={target}\n", encoding="utf-8")
    return _mei_spec(
        name="create_desktop_file",
        run_dir=run_dir,
        command=f"Create a file named {file_name} on the Desktop",
        timeout_s=timeout_s,
        memory=memory,
        setup=setup,
        verifier=verifier,
        teardown=teardown,
        grammar=grammar,
        scorer=_create_call_scorer(target, is_dir=False),
    )


TASKS: Dict[str, Callable[..., TaskSpec]] = {
    "create_desktop_folder": create_desktop_folder,
    "create_desktop_file": create_desktop_file,
}

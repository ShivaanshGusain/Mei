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
from typing import Callable, Dict

from .supervisor import TaskSpec

REPO_ROOT = Path(__file__).resolve().parent.parent
DESKTOP = Path(os.path.expanduser("~")) / "Desktop"
NAME_PREFIX = "mei_harness_"


def _mei_spec(name: str, run_dir: Path, command: str, timeout_s: float,
              memory: str, **hooks) -> TaskSpec:
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
                          desktop: Path = DESKTOP) -> TaskSpec:
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
    )


TASKS: Dict[str, Callable[..., TaskSpec]] = {
    "create_desktop_folder": create_desktop_folder,
}

"""Real Mei task definitions.

Each builder returns a TaskSpec whose verifier checks the world directly
(here: the file system), never Mei's self-report. Teardown follows the
ownership rule from app_manager: only remove what this run provably created.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from .scoring import load_attempts, score_attempts
from .supervisor import TaskSpec

REPO_ROOT = Path(__file__).resolve().parent.parent
DESKTOP = Path(os.path.expanduser("~")) / "Desktop"
NAME_PREFIX = "mei_harness_"
GUARDRAILS_PATH = REPO_ROOT / "Mei" / "config" / "guardrails.yaml"
# Folders the executor expands relative to the home folder (Mei/action/executor.py).
_HOME_RELATIVE = {"desktop", "documents", "downloads", "pictures", "music", "videos"}


def _write_roots() -> List[Path]:
    """allowed_write_roots from Mei's guardrails.yaml: where Mei *can* write."""
    try:
        import yaml
        cfg = yaml.safe_load(GUARDRAILS_PATH.read_text(encoding="utf-8")) or {}
        return [Path(r) for r in cfg.get("allowed_write_roots") or []]
    except Exception:
        return []


def _resolve_like_mei(raw: str) -> List[Path]:
    """Places Mei's executor could have put a path argument. Relative paths
    resolve against the process cwd (the repo, under the harness) unless they
    start with a home folder name; a change_directory cwd isn't logged, so the
    shallow scan in find_strays covers that case."""
    p = Path(raw).expanduser()
    if p.is_absolute():
        return [p]
    out = [REPO_ROOT / p]
    if p.parts and p.parts[0].lower() in _HOME_RELATIVE:
        out.append(Path.home() / p)
    return out


def find_strays(run_id: str, target: Path, events_path: Path, since: float,
                scan_dirs: Optional[Iterable[Path]] = None) -> List[Dict[str, Any]]:
    """Paths named with this run's unique id that aren't the target.

    The id is random, so anything carrying it was produced by this run (the
    2026-11-09 smoke test left C:\\Users\\Asus\\Projects\\mei_harness_ab6a6de0
    while the target on the Desktop was never created). Looks wherever an
    executed call's parameters mention the id, and directly (not recursively)
    inside each write root, the repo, its parent and the home folder.
    """
    places = set()
    for a in load_attempts(events_path):
        if a.get("outcome") != "executed":
            continue
        for v in (a.get("parameters") or {}).values():
            if isinstance(v, str) and run_id in v:
                places.update(_resolve_like_mei(v))
    if scan_dirs is None:
        scan_dirs = {*_write_roots(), REPO_ROOT, REPO_ROOT.parent, Path.home(), DESKTOP}
    for d in scan_dirs:
        try:
            places.update(d.glob(f"*{run_id}*"))
        except OSError:
            continue

    target_key = os.path.normcase(str(target.resolve()))
    strays, seen = [], set()
    for p in places:
        # Report the outermost folder named with the id, so a nested
        # <id>\<id> mistake is one stray, not two.
        owned = [q for q in (p, *p.parents) if run_id in q.name]
        if not owned:
            continue
        root = owned[-1]
        try:
            if not root.exists():
                continue
            key = os.path.normcase(str(root.resolve()))
            if key in seen or key == target_key or key.startswith(target_key + os.sep):
                continue
            seen.add(key)
            st = root.stat()
            is_dir = root.is_dir()
            empty = not any(root.iterdir()) if is_dir else st.st_size == 0
        except OSError:
            continue
        strays.append({
            "path": str(root),
            "type": "directory" if is_dir else "file",
            "empty": empty,
            # st_ctime is the creation time on Windows, where the harness runs.
            "created_during_run": st.st_ctime >= since - 1,
        })
    return sorted(strays, key=lambda s: s["path"])


def remove_strays(strays: List[Dict[str, Any]], run_id: str) -> Dict[str, Any]:
    """Delete only strays this run provably made: named with the run id,
    created during the run, and still empty. Anything else is kept and
    reported (ambiguous ownership means refuse cleanup)."""
    removed, kept = [], []
    for s in strays:
        p = Path(s["path"])
        if run_id in p.name and s["created_during_run"] and s["empty"]:
            try:
                p.rmdir() if s["type"] == "directory" else p.unlink()
                removed.append(s["path"])
                continue
            except OSError:
                pass
        kept.append(s["path"])
    return {"strays_removed": removed, "strays_kept": kept}


def _create_call_scorer(target: Path, is_dir: bool) -> Callable[[TaskSpec], Dict[str, Any]]:
    expected = {
        "action": "create_file_or_folder",
        # The unique name picks out the create step in a multi-step plan.
        "step_hint": target.stem,
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
    state = {"existed_before": None, "started": None, "strays": []}

    def setup(spec: TaskSpec) -> None:
        if not desktop.is_dir():
            raise RuntimeError(f"Desktop not found at {desktop}")
        state["existed_before"] = target.exists()
        if state["existed_before"]:
            raise RuntimeError(f"{target} already exists; refusing to run")
        state["started"] = time.time()

    def verifier(spec: TaskSpec) -> bool:
        return target.is_dir()

    def side_effects(spec: TaskSpec) -> Dict[str, Any]:
        state["strays"] = find_strays(folder_name, target, spec.events_path, state["started"])
        return {"strays": state["strays"]}

    def teardown(spec: TaskSpec) -> Dict[str, Any]:
        # Only delete what this run created: it must not have existed at
        # setup, and must be the exact uniquely-named path we asked for.
        if state["existed_before"] is not False:
            return {}
        if target.parent != desktop or not target.name.startswith(NAME_PREFIX):
            raise RuntimeError(f"refusing to delete unexpected path {target}")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        return remove_strays(state["strays"], folder_name)

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
        side_effects=side_effects,
    )


def create_desktop_file(run_dir: Path, timeout_s: float, memory: str = "fresh",
                        desktop: Path = DESKTOP, grammar: Optional[str] = None) -> TaskSpec:
    """'Create a file named mei_harness_<id>.txt on the Desktop' -> is it a file, not a directory?

    Companion to create_desktop_folder: regresses the is_dir fix in the other
    direction. A fix that makes the model always pass is_dir=true (or a tool
    change that flips the default) would pass the folder task and silently
    fail this one — run both, never just one.
    """
    run_id = f"{NAME_PREFIX}{uuid.uuid4().hex[:8]}"
    file_name = f"{run_id}.txt"
    target = desktop / file_name
    state = {"existed_before": None, "started": None, "strays": []}

    def setup(spec: TaskSpec) -> None:
        if not desktop.is_dir():
            raise RuntimeError(f"Desktop not found at {desktop}")
        state["existed_before"] = target.exists()
        if state["existed_before"]:
            raise RuntimeError(f"{target} already exists; refusing to run")
        state["started"] = time.time()

    def verifier(spec: TaskSpec) -> bool:
        return target.is_file()

    def side_effects(spec: TaskSpec) -> Dict[str, Any]:
        state["strays"] = find_strays(run_id, target, spec.events_path, state["started"])
        return {"strays": state["strays"]}

    def teardown(spec: TaskSpec) -> Dict[str, Any]:
        # Only delete what this run created: it must not have existed at
        # setup, and must be the exact uniquely-named path we asked for.
        if state["existed_before"] is not False:
            return {}
        if target.parent != desktop or not target.name.startswith(NAME_PREFIX):
            raise RuntimeError(f"refusing to delete unexpected path {target}")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        return remove_strays(state["strays"], run_id)

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
        side_effects=side_effects,
    )


TASKS: Dict[str, Callable[..., TaskSpec]] = {
    "create_desktop_folder": create_desktop_folder,
    "create_desktop_file": create_desktop_file,
}

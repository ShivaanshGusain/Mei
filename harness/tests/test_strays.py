"""Tests for the off-target side-effect check (harness/tasks.py find_strays)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from harness.tasks import find_strays, remove_strays

RUN_ID = "mei_harness_abc123"


def write_events(path: Path, params_list):
    lines = [json.dumps({"type": "mei_event", "event": "TOOL_CALL_PROPOSED",
                         "data": {"outcome": "executed", "action": "create_file_or_folder",
                                  "parameters": p}}) for p in params_list]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_wrong_directory_folder_is_found_and_removed(tmp_path):
    # 2026-11-09 per_tool smoke run: the folder landed in Projects, not on the Desktop.
    desktop, projects = tmp_path / "Desktop", tmp_path / "Projects"
    desktop.mkdir(); projects.mkdir()
    since = time.time()
    stray = projects / RUN_ID
    stray.mkdir()
    events = tmp_path / "events.jsonl"
    write_events(events, [{"path": str(stray), "is_dir": True}])

    strays = find_strays(RUN_ID, desktop / RUN_ID, events, since, scan_dirs=[desktop, projects])
    assert [s["path"] for s in strays] == [str(stray)]
    assert strays[0]["type"] == "directory" and strays[0]["empty"] and strays[0]["created_during_run"]

    out = remove_strays(strays, RUN_ID)
    assert out == {"strays_removed": [str(stray)], "strays_kept": []}
    assert not stray.exists()


def test_target_itself_is_not_a_stray(tmp_path):
    desktop = tmp_path / "Desktop"
    (desktop / RUN_ID).mkdir(parents=True)
    events = tmp_path / "events.jsonl"
    write_events(events, [{"path": str(desktop / RUN_ID), "is_dir": True}])
    assert find_strays(RUN_ID, desktop / RUN_ID, events, time.time() - 5, scan_dirs=[desktop]) == []


def test_existing_unrelated_path_is_never_a_stray(tmp_path):
    # Run 1 of the smoke test: mkdir on the repo folder itself. It carries no
    # run id, so it must never be reported (or deleted).
    repo = tmp_path / "Mei"
    repo.mkdir()
    events = tmp_path / "events.jsonl"
    write_events(events, [{"path": str(repo), "is_dir": True}])
    assert find_strays(RUN_ID, tmp_path / "Desktop" / RUN_ID, events, time.time() - 5,
                       scan_dirs=[tmp_path]) == []


def test_nonempty_or_old_strays_are_kept(tmp_path):
    full = tmp_path / RUN_ID
    full.mkdir()
    (full / "something.txt").write_text("keep me", encoding="utf-8")
    strays = find_strays(RUN_ID, tmp_path / "Desktop" / RUN_ID, tmp_path / "none.jsonl",
                         time.time() - 5, scan_dirs=[tmp_path])
    assert strays and strays[0]["empty"] is False
    assert remove_strays(strays, RUN_ID) == {"strays_removed": [], "strays_kept": [str(full)]}
    assert full.exists()

    # Created before the run started: never deleted, even if empty.
    old_file = tmp_path / f"{RUN_ID}.txt"
    old_file.write_text("", encoding="utf-8")
    old = [{"path": str(old_file), "type": "file", "empty": True, "created_during_run": False}]
    assert remove_strays(old, RUN_ID) == {"strays_removed": [], "strays_kept": [str(old_file)]}
    assert old_file.exists()


def test_nested_strays_report_outermost(tmp_path):
    outer = tmp_path / RUN_ID
    (outer / RUN_ID).mkdir(parents=True)
    events = tmp_path / "events.jsonl"
    write_events(events, [{"path": str(outer / RUN_ID), "is_dir": True}])
    strays = find_strays(RUN_ID, tmp_path / "Desktop" / RUN_ID, events, time.time() - 5,
                         scan_dirs=[tmp_path])
    assert [s["path"] for s in strays] == [str(outer)]

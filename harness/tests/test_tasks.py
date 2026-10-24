"""Task-definition safety: verifiers check the world, and teardown only ever
removes what the run itself created. Uses a temp dir as the "Desktop" and
never launches Mei."""
from __future__ import annotations

from pathlib import Path

import pytest

from harness.tasks import NAME_PREFIX, create_desktop_folder


@pytest.fixture
def desktop(tmp_path: Path) -> Path:
    d = tmp_path / "Desktop"
    d.mkdir()
    return d


def _target(desktop: Path) -> Path:
    return next(p for p in desktop.iterdir() if p.name.startswith(NAME_PREFIX))


def test_command_names_the_verified_folder(tmp_path, desktop):
    spec = create_desktop_folder(tmp_path / "run", timeout_s=60, desktop=desktop)
    command = spec.runner_cmd[spec.runner_cmd.index("--command") + 1]
    folder = command.split("named ", 1)[1].split(" ", 1)[0]
    assert folder.startswith(NAME_PREFIX)
    spec.setup(spec)
    assert not spec.verifier(spec)
    (desktop / folder).mkdir()
    assert spec.verifier(spec)


def test_teardown_removes_only_what_the_run_created(tmp_path, desktop):
    spec = create_desktop_folder(tmp_path / "run", timeout_s=60, desktop=desktop)
    spec.setup(spec)
    unrelated = desktop / "keep_me"
    unrelated.mkdir()
    command = spec.runner_cmd[spec.runner_cmd.index("--command") + 1]
    created = desktop / command.split("named ", 1)[1].split(" ", 1)[0]
    created.mkdir()
    (created / "inner.txt").write_text("x")
    spec.teardown(spec)
    assert not created.exists()
    assert unrelated.exists()


def test_setup_refuses_preexisting_target_and_teardown_spares_it(tmp_path, desktop):
    spec = create_desktop_folder(tmp_path / "run", timeout_s=60, desktop=desktop)
    command = spec.runner_cmd[spec.runner_cmd.index("--command") + 1]
    preexisting = desktop / command.split("named ", 1)[1].split(" ", 1)[0]
    preexisting.mkdir()
    with pytest.raises(RuntimeError):
        spec.setup(spec)
    spec.teardown(spec)
    assert preexisting.exists(), "teardown must not delete a folder the run didn't create"


def test_runner_uses_isolated_memory_by_default(tmp_path, desktop):
    spec = create_desktop_folder(tmp_path / "run", timeout_s=60, desktop=desktop)
    cmd = spec.runner_cmd
    assert cmd[cmd.index("--memory") + 1] == "fresh"
    assert Path(cmd[cmd.index("--kuzu-dir") + 1]).parent == tmp_path / "run"

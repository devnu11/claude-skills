"""s41 end to end: the runner signals only groups it created; role Bash cannot kill the runner."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from agile_team import process_groups as pg
from agile_team import sandbox
from agile_team.commands import CommandShell
from agile_team.guard import Scope, check_bash


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_a_non_leader_child_is_never_signalled_in_the_callers_group() -> None:
    # Shares our group: killing "its group" would kill the test runner.
    child = subprocess.Popen(["sleep", "30"])
    try:
        assert not pg.may_signal_child_group(child.pid)
        pg.signal_child_group(child.pid, 9)
        time.sleep(0.2)
        assert child.poll() is None
    finally:
        child.kill()


def test_runner_pid_and_stale_pid_are_refused() -> None:
    assert not pg.may_signal_child_group(os.getpid())
    pg.signal_child_group(os.getpid(), 0)
    gone = subprocess.Popen(["true"])
    gone.wait()
    assert not pg.Recorded(gone.pid, time.time()).is_ours()


def test_own_session_leader_is_signalled() -> None:
    child = subprocess.Popen(["sleep", "30"], start_new_session=True)
    pg.signal_child_group(child.pid, 15)
    assert child.wait(timeout=5) != 0


def test_stop_stale_ignores_reused_pid_but_stops_a_real_old_group(tmp_path: Path) -> None:
    other = subprocess.Popen(["sleep", "30"])  # in our group, not a leader
    pid_file = tmp_path / "d.pid"
    pid_file.write_text(str(other.pid))
    try:
        sandbox.stop_stale(tmp_path / "d")
        assert other.poll() is None
        old = subprocess.Popen(["sleep", "30"], start_new_session=True)
        time.sleep(1.1)
        pid_file.write_text(str(old.pid))
        sandbox.stop_stale(tmp_path / "d")
        assert old.wait(timeout=5) != 0
    finally:
        other.kill()


def test_command_timeout_does_not_touch_our_group(tmp_path: Path) -> None:
    code, _ = CommandShell(tmp_path, 0.3).run("sleep 30")
    assert code != 0 and alive(os.getpid())


def test_role_bash_cannot_kill_the_runner_group_or_by_name(tmp_path: Path) -> None:
    scope = Scope(role="developer-cli", repo=tmp_path, write=["**"])
    me = os.getpid()
    assert check_bash(scope, f"kill -9 {me}")
    assert check_bash(scope, "pkill -f pytest")
    assert check_bash(scope, "kill $(pgrep pytest)")
    assert check_bash(scope, "pgrep x | xargs kill")
    assert check_bash(scope, "kill 0")
    assert check_bash(scope, "sleep 5 & PID=$!; kill $PID") is None

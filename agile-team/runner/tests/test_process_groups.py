"""s41: the runner signals only process groups it created (G1-G6)."""

import contextlib
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest
from agile_team import commands, process_groups, sandbox
from agile_team.process_groups import Recorded


@pytest.fixture
def sent(monkeypatch) -> list[tuple[int, int]]:
    """Record every killpg instead of sending it."""
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: calls.append((pgid, sig)))
    return calls


def _spawn(new_session: bool) -> subprocess.Popen:
    return subprocess.Popen(["sleep", "30"], start_new_session=new_session)


@pytest.fixture
def same_group():
    proc = _spawn(False)
    yield proc
    proc.kill()
    proc.wait()


@pytest.fixture
def own_group():
    proc = _spawn(True)
    yield proc
    proc.kill()
    proc.wait()


@pytest.fixture
def reaped_pid() -> int:
    proc = _spawn(True)
    proc.kill()
    proc.wait()
    return proc.pid


def _kills(sent) -> list[tuple[int, int]]:
    return [c for c in sent if c[1] != 0]


# 1
def test_same_group_child_is_never_signalled(sent, same_group) -> None:
    process_groups.signal_child_group(same_group.pid, signal.SIGTERM)
    sandbox._signal_group(same_group, signal.SIGTERM)
    assert sent == []


def test_runner_and_bad_pids_are_never_signalled(sent) -> None:
    class Me:
        pid = os.getpid()

    sandbox._signal_group(Me(), signal.SIGTERM)  # type: ignore[arg-type]
    for pid in (os.getpid(), os.getpgrp(), 0, 1, -5):
        process_groups.signal_child_group(pid, signal.SIGKILL)
    assert sent == []


# 2
def test_new_session_child_is_signalled(sent, own_group) -> None:
    process_groups.signal_child_group(own_group.pid, signal.SIGTERM)
    assert sent == [(own_group.pid, signal.SIGTERM)]


def test_vanished_leader_is_signalled(sent, monkeypatch) -> None:
    def gone(pid):
        raise ProcessLookupError

    monkeypatch.setattr(os, "getpgid", gone)
    process_groups.signal_child_group(4242, signal.SIGKILL)
    assert sent == [(4242, signal.SIGKILL)]


@pytest.mark.parametrize("error", [ProcessLookupError, PermissionError])
def test_killpg_errors_are_suppressed(monkeypatch, own_group, error) -> None:
    def boom(pgid, sig):
        raise error

    monkeypatch.setattr(os, "killpg", boom)
    process_groups.signal_child_group(own_group.pid, signal.SIGTERM)


# 3
def test_leads_own_group(own_group, same_group, reaped_pid) -> None:
    assert process_groups.leads_own_group(own_group.pid)
    assert not process_groups.leads_own_group(same_group.pid)
    assert not process_groups.leads_own_group(os.getpid())
    assert not process_groups.leads_own_group(reaped_pid)


# 4
def test_in_runner_group(own_group, same_group, reaped_pid) -> None:
    assert process_groups.in_runner_group(os.getpid())
    assert process_groups.in_runner_group(same_group.pid)
    assert not process_groups.in_runner_group(own_group.pid)
    assert not process_groups.in_runner_group(reaped_pid)
    assert not process_groups.in_runner_group(10**30)


# 5
@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("07", None),
        ("05:07", 307),
        ("1:02:03", 3723),
        ("2-01:00:00", 176400),
        ("  00:05\n", 5),
        ("", None),
        ("abc", None),
        ("1:2:3:4", None),
        ("x-01:00", None),
    ],
)
def test_parse_etime(text: str, seconds) -> None:
    assert process_groups.parse_etime(text) == seconds


# 6
def test_started_at_of_a_fresh_child(own_group) -> None:
    started = process_groups.started_at(own_group.pid)
    assert started is not None and abs(started - time.time()) < 3


def test_started_at_of_a_reaped_pid(reaped_pid) -> None:
    assert process_groups.started_at(reaped_pid) is None


@pytest.mark.parametrize(
    "outcome",
    [
        subprocess.TimeoutExpired("ps", 1),
        OSError("no ps"),
        subprocess.CompletedProcess([], 1, "00:05\n", ""),
    ],
)
def test_started_at_without_a_usable_ps(monkeypatch, outcome) -> None:
    def run(*args, **kwargs):
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(subprocess, "run", run)
    assert process_groups.started_at(os.getpid()) is None


# 7
def test_recorded_is_ours(own_group, same_group, monkeypatch) -> None:
    assert Recorded(own_group.pid, time.time()).is_ours()
    assert not Recorded(own_group.pid, time.time() - 3600).is_ours()
    assert not Recorded(same_group.pid, time.time()).is_ours()
    assert not Recorded(os.getpid(), time.time()).is_ours()
    monkeypatch.setattr(process_groups, "started_at", lambda pid: None)
    assert not Recorded(own_group.pid, time.time()).is_ours()


# 8
def test_stale_pid_reused_after_the_file_was_written_is_left_alone(
    tmp_path: Path, own_group
) -> None:
    root = tmp_path / "web"
    pid_file = tmp_path / f"web{sandbox.PID_SUFFIX}"
    pid_file.write_text(str(own_group.pid))
    old = time.time() - 3600
    os.utime(pid_file, (old, old))
    sandbox.stop_stale(root)
    assert own_group.poll() is None
    assert not pid_file.exists()


# 9
@pytest.mark.parametrize("pid", [os.getpid(), os.getpgrp()])
def test_stop_stale_never_signals_the_runner(tmp_path: Path, sent, pid) -> None:
    pid_file = tmp_path / f"web{sandbox.PID_SUFFIX}"
    pid_file.write_text(str(pid))
    sandbox.stop_stale(tmp_path / "web")
    assert sent == []
    assert not pid_file.exists()


def test_stop_stale_ends_a_group_it_recorded(tmp_path: Path, own_group) -> None:
    pid_file = tmp_path / f"web{sandbox.PID_SUFFIX}"
    pid_file.write_text(str(own_group.pid))
    sandbox.stop_stale(tmp_path / "web")
    assert own_group.wait(timeout=5) == -signal.SIGTERM
    assert not pid_file.exists()


def test_stop_stale_ignores_unreadable_pid_files(tmp_path: Path) -> None:
    pid_file = tmp_path / f"web{sandbox.PID_SUFFIX}"
    pid_file.write_text("not a pid")
    sandbox.stop_stale(tmp_path / "web")
    assert not pid_file.exists()


# 11
def test_no_sigkill_when_the_group_stopped_being_ours(
    tmp_path: Path, sent, own_group, monkeypatch
) -> None:
    pid_file = tmp_path / f"web{sandbox.PID_SUFFIX}"
    pid_file.write_text(str(own_group.pid))
    monkeypatch.setattr(sandbox, "STOP_WAIT_S", 0.1)
    answers = iter([True, False])
    monkeypatch.setattr(Recorded, "is_ours", lambda self: next(answers))
    sandbox.stop_stale(tmp_path / "web")
    assert _kills(sent) == [(own_group.pid, signal.SIGTERM)]


def test_sigkill_when_the_group_is_still_ours(tmp_path: Path, sent, own_group, monkeypatch) -> None:
    pid_file = tmp_path / f"web{sandbox.PID_SUFFIX}"
    pid_file.write_text(str(own_group.pid))
    monkeypatch.setattr(sandbox, "STOP_WAIT_S", 0.1)
    monkeypatch.setattr(Recorded, "is_ours", lambda self: True)
    sandbox.stop_stale(tmp_path / "web")
    assert _kills(sent) == [
        (own_group.pid, signal.SIGTERM),
        (own_group.pid, signal.SIGKILL),
    ]


# 12
def test_kill_group_spares_the_runners_group(sent, same_group) -> None:
    commands.kill_group(same_group)
    assert sent == []


def test_kill_group_kills_a_new_session(own_group) -> None:
    commands.kill_group(own_group)
    assert own_group.wait(timeout=5) == -signal.SIGKILL


def test_no_other_module_calls_killpg() -> None:
    pkg = Path(process_groups.__file__).parent
    users = {
        p.name
        for p in pkg.glob("*.py")
        if "os.killpg(" in p.read_text() and p.name != "process_groups.py"
    }
    assert users <= {"sandbox.py"}  # _ends_within polls with signal 0 only
    with contextlib.suppress(OSError):
        assert "killpg(pgid, 0)" in (pkg / "sandbox.py").read_text()

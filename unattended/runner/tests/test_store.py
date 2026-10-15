from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from unattended import store
from unattended.auth import Auth
from unattended.awake import SleepPolicy
from unattended.limits import Bounds, Progress, WakeOn
from unattended.store import Job, JobError, JobHome, JobKind, JobState, JobStatus, Spec


def state(name: str = "nightly") -> JobState:
    return JobState(name, Spec(JobKind.PROMPT, "/work", prompt="hi"))


def test_state_round_trips() -> None:
    original = state()
    original.spec.auth = Auth.API_KEY
    original.spec.stop_command = "agile-team stop"
    original.bounds = Bounds(deadline=5.0, max_resumes=3, max_cost=1.5, hardstop=60.0)
    original.mark(JobStatus.WAITING, "session limit")
    loaded = JobState.from_json(original.to_json())
    assert loaded == original
    assert isinstance(loaded.status, JobStatus)
    assert isinstance(loaded.spec.kind, JobKind)


def test_state_without_sleep_keeps_the_machine_awake() -> None:
    data = json.loads(state().to_json())
    del data["spec"]["sleep"]
    assert JobState.from_json(json.dumps(data)).spec.sleep is SleepPolicy.PREVENT


def test_state_from_before_hard_stops_loads() -> None:
    data = json.loads(state().to_json())
    for key in ("stop_command", "idle", "progress"):
        del data["spec"][key]
    del data["bounds"]["hardstop"], data["bounds"]["idle_stop"]
    loaded = JobState.from_json(json.dumps(data))
    assert (loaded.spec.stop_command, loaded.bounds.hardstop) == ("", None)
    assert (loaded.spec.idle, loaded.spec.progress, loaded.bounds.idle_stop) == (1200.0, [], None)


def test_mark_clears_reason() -> None:
    st = state()
    st.mark(JobStatus.FAILED, "boom")
    st.mark(JobStatus.RUNNING)
    assert (st.status, st.reason) == (JobStatus.RUNNING, "")


def test_mark_clears_the_wake() -> None:
    st = state()
    st.next_wake, st.wake_on = 99.0, WakeOn.RESET
    st.mark(JobStatus.RUNNING)
    assert (st.next_wake, st.wake_on) == (None, None)


def test_wake_on_round_trips() -> None:
    st = state()
    st.wake_on = WakeOn.FALLBACK
    loaded = JobState.from_json(st.to_json())
    assert loaded.wake_on is WakeOn.FALLBACK


def test_legacy_state_has_no_wake_on() -> None:
    data = json.loads(state().to_json())
    del data["wake_on"]
    assert JobState.from_json(json.dumps(data)).wake_on is None


def test_progress() -> None:
    st = state()
    st.resumes, st.cost = 2, 0.25
    assert st.progress(9.0) == Progress(2, 0.25, 9.0)


def test_repo_jobs_dir_wins(tmp_path: Path) -> None:
    repo, home = tmp_path / "repo", tmp_path / "home"
    (repo / ".git").mkdir(parents=True)
    (repo / store.JOBS).mkdir(parents=True)
    (repo / "sub").mkdir()
    assert JobHome.find(repo / "sub", home).root == repo / store.JOBS


def test_home_jobs_dir_without_repo_jobs(tmp_path: Path) -> None:
    repo, home = tmp_path / "repo", tmp_path / "home"
    (repo / ".git").mkdir(parents=True)
    assert JobHome.find(repo, home).root == home / store.JOBS


def test_home_jobs_dir_outside_a_repo(tmp_path: Path) -> None:
    assert store.git_root(tmp_path) is None
    assert JobHome.find(tmp_path, tmp_path / "home").root == tmp_path / "home" / store.JOBS


def test_git_root_finds_a_worktree_file(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: elsewhere")
    assert store.git_root(tmp_path) == tmp_path.resolve()


def test_create_load_and_list(tmp_path: Path) -> None:
    home = JobHome(tmp_path / "jobs")
    assert home.jobs() == []
    created = state("b")
    job = home.create(created)
    home.create(state("a"))
    assert job.load() == created
    assert [j.name for j in home.jobs()] == ["a", "b"]
    assert home.job("b") == job


def test_create_refuses_a_duplicate(tmp_path: Path) -> None:
    home = JobHome(tmp_path)
    home.create(state())
    with pytest.raises(JobError, match="already exists"):
        home.create(state())


def test_unknown_job(tmp_path: Path) -> None:
    with pytest.raises(JobError, match="no job named 'ghost'"):
        JobHome(tmp_path).job("ghost")


@pytest.mark.parametrize("name", ["", "../x", ".hidden", "a/b", "x" * 65])
def test_bad_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(JobError, match="bad job name"):
        JobHome(tmp_path).job(name)


def test_update_saves_atomically(tmp_path: Path) -> None:
    job = JobHome(tmp_path).create(state())
    job.update(lambda st: st.mark(JobStatus.DONE, "ok"))
    assert job.load().status is JobStatus.DONE
    assert sorted(p.name for p in job.dir.iterdir()) == [store.STATE_FILE]


def test_events_append(tmp_path: Path) -> None:
    job = JobHome(tmp_path).create(state())
    job.event("start")
    job.event("run", {"cost": 0.1})
    lines = [json.loads(line) for line in job.path(store.EVENTS_FILE).read_text().splitlines()]
    assert [line["event"] for line in lines] == ["start", "run"]
    assert lines[1]["cost"] == 0.1 and "at" in lines[0]


def test_stop_file(tmp_path: Path) -> None:
    job = JobHome(tmp_path).create(state())
    assert not job.stop_requested()
    job.request_stop()
    assert job.stop_requested()
    job.clear_stop()
    assert not job.stop_requested()


def test_pid_file(tmp_path: Path) -> None:
    job = JobHome(tmp_path).create(state())
    assert job.pid() is None
    with job.pid_file():
        assert job.pid() == os.getpid()
    assert job.pid() is None


def test_stale_pid_is_not_running(tmp_path: Path) -> None:
    job = Job(tmp_path)
    job.path(store.PID_FILE).write_text("999999999")
    assert job.pid() is None


def test_alive_on_a_process_we_cannot_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(pid: int, sig: int) -> None:
        raise PermissionError

    monkeypatch.setattr(os, "kill", deny)
    assert store.alive(1)


@dataclass
class FakeWin32:
    """kernel32 stand-in: ``handle`` 0 means OpenProcess failed with ``error``."""

    handle: int = 7
    code: int = store.STILL_ACTIVE
    error: int = 0
    closed: list[int] = field(default_factory=list)

    def open(self, pid: int) -> int:
        return self.handle

    def last_error(self) -> int:
        return self.error

    def exit_code(self, handle: int) -> int:
        return self.code

    def close(self, handle: int) -> None:
        self.closed.append(handle)


@pytest.mark.parametrize(
    ("win32", "expected"),
    [
        (FakeWin32(), True),
        (FakeWin32(code=0), False),
        (FakeWin32(handle=0, error=store.ERROR_ACCESS_DENIED), True),
        (FakeWin32(handle=0, error=87), False),
    ],
    ids=["running", "exited", "access-denied", "no-such-process"],
)
def test_alive_on_windows_asks_the_kernel(win32: FakeWin32, expected: bool) -> None:
    assert store._alive_on_windows(1234, win32) is expected
    assert win32.closed == ([win32.handle] if win32.handle else [])


def test_alive_on_windows_never_signals(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(pid: int, sig: int) -> None:
        raise AssertionError("os.kill terminates the process on Windows")

    monkeypatch.setattr(os, "kill", refuse)
    monkeypatch.setattr(store.sys, "platform", "win32")
    monkeypatch.setattr(store, "kernel32", FakeWin32)
    assert store.alive(1234)


@pytest.mark.skipif(sys.platform != "win32", reason="the real kernel32 exists only on Windows")
def test_alive_on_windows_with_the_real_kernel() -> None:  # pragma: no cover -- Windows only
    assert store.alive(os.getpid())
    assert not store.alive(999999999)

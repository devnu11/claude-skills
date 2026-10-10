from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from unattended import store
from unattended.auth import Auth
from unattended.awake import SleepPolicy
from unattended.limits import Bounds, Progress
from unattended.store import Job, JobError, JobHome, JobKind, JobState, JobStatus, Spec


def state(name: str = "nightly") -> JobState:
    return JobState(name, Spec(JobKind.PROMPT, "/work", prompt="hi"))


def test_state_round_trips() -> None:
    original = state()
    original.spec.auth = Auth.API_KEY
    original.bounds = Bounds(deadline=5.0, max_resumes=3, max_cost=1.5)
    original.mark(JobStatus.WAITING, "session limit")
    loaded = JobState.from_json(original.to_json())
    assert loaded == original
    assert isinstance(loaded.status, JobStatus)
    assert isinstance(loaded.spec.kind, JobKind)


def test_state_without_sleep_keeps_the_machine_awake() -> None:
    data = json.loads(state().to_json())
    del data["spec"]["sleep"]
    assert JobState.from_json(json.dumps(data)).spec.sleep is SleepPolicy.PREVENT


def test_mark_clears_reason() -> None:
    st = state()
    st.mark(JobStatus.FAILED, "boom")
    st.mark(JobStatus.RUNNING)
    assert (st.status, st.reason) == (JobStatus.RUNNING, "")


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

from __future__ import annotations

import json
import os
import signal
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ResultMessage, SystemMessage
from unattended import awake, cli
from unattended.auth import ENV_VAR
from unattended.awake import SleepPolicy
from unattended.prompt_job import PromptJob
from unattended.store import (
    EVENTS_FILE,
    OUTPUT_FILE,
    PID_FILE,
    Job,
    JobHome,
    JobKind,
    JobState,
    JobStatus,
    Spec,
)

from .test_prompt_job import FakeQuery


@pytest.fixture(autouse=True)
def place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Run each test from a scratch cwd, keep SIGTERM's handler, and drop any inherited key."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_VAR, raising=False)
    previous = signal.getsignal(signal.SIGTERM)
    yield tmp_path
    signal.signal(signal.SIGTERM, previous)


def run(tmp_path: Path, *argv: str) -> int:
    return cli.main(["--home", str(tmp_path / "home"), *argv])


def home_job(tmp_path: Path, name: str = "j") -> Job:
    return JobHome(tmp_path / "home" / ".claude/jobs").job(name)


def printed(capsys: pytest.CaptureFixture[str]) -> Any:
    return json.loads(capsys.readouterr().out)


def make(tmp_path: Path, status: JobStatus = JobStatus.STOPPED) -> Job:
    state = JobState("j", Spec(JobKind.COMMAND, str(tmp_path), command="echo again"))
    state.mark(status)
    return JobHome(tmp_path / "home" / ".claude/jobs").create(state)


# ----- start -------------------------------------------------------------------------


def test_start_command_in_the_foreground(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmp_path, "start", "j", "--command", "echo hi", "--foreground") == 0
    report = printed(capsys)
    assert (report["status"], report["kind"], report["runs"]) == ("done", "command", 1)
    assert report["supervisor_pid"] is None
    assert "warning" not in report


def test_start_command_limit_then_resume(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = tmp_path / "once.sh"
    script.write_text("[ -e done ] && exit 0\ntouch done\necho 'hit your limit'\nexit 75\n")
    code = run(tmp_path, "start", "j", "--command", f"sh {script}", "--fallback-wait", "1s",
               "--foreground")  # fmt: skip
    assert code == 0
    assert printed(capsys)["resumes"] == 1
    events = [json.loads(line)["event"] for line in home_job(tmp_path).path(EVENTS_FILE).open()]
    assert events == ["start", "keep-awake", "run", "wait", "resume", "run", "end"]


def events_named(tmp_path: Path, name: str) -> list[dict[str, object]]:
    lines = home_job(tmp_path).path(EVENTS_FILE).open()
    return [event for event in map(json.loads, lines) if event["event"] == name]


def test_start_keeps_the_machine_awake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spawned: list[list[str]]
) -> None:
    monkeypatch.setattr(awake, "inhibitor", lambda pid: ["caffeinate", "-w", str(pid)])
    assert run(tmp_path, "start", "j", "--command", "true", "--foreground") == 0
    assert spawned == [["caffeinate", "-w", str(os.getpid())]]
    assert events_named(tmp_path, "keep-awake")[0]["by"] == "caffeinate"


def test_start_allow_sleep(tmp_path: Path, spawned: list[list[str]]) -> None:
    argv = ["--command", "true", "--allow-sleep", "--foreground"]
    assert run(tmp_path, "start", "j", *argv) == 0
    assert spawned == []
    assert events_named(tmp_path, "keep-awake") == []
    assert home_job(tmp_path).load().spec.sleep is SleepPolicy.ALLOW


def test_start_prompt_in_the_foreground(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    done = ResultMessage("success", 1, 1, False, 2, "s9", total_cost_usd=0.1, result="pong")
    fake = FakeQuery([SystemMessage("init", {"session_id": "s9"}), done])
    monkeypatch.setitem(cli.RUNNERS, JobKind.PROMPT, lambda job, env: PromptJob(job, env, fake))
    assert run(tmp_path, "start", "j", "--prompt", "Reply pong", "--foreground") == 0
    report = printed(capsys)
    assert (report["status"], report["session_id"], report["cost"]) == ("done", "s9", 0.1)
    assert home_job(tmp_path).path(OUTPUT_FILE).read_text() == "pong\n"
    assert fake.calls[0]["options"].setting_sources == ["user", "project", "local"]


def test_start_prompt_file_and_limits(tmp_path: Path) -> None:
    (tmp_path / "p.md").write_text("from a file")
    args = cli.build_parser().parse_args(
        ["start", "j", "--prompt-file", "p.md", "--for", "2h", "--max-cost", "3", "--model", "m"]
    )
    spec = cli.spec_from(args)
    assert (spec.kind, spec.prompt, spec.model) == (JobKind.PROMPT, "from a file", "m")
    deadline = cli.deadline_from(args, 1000.0)
    assert deadline == 1000.0 + 7200


def test_start_detaches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    launched: list[list[str]] = []

    class FakePopen:
        def __init__(self, command: list[str], **options: Any) -> None:
            launched.append(command)
            assert options["start_new_session"] is True
            self.pid = os.getpid()

    monkeypatch.setattr(cli.subprocess, "Popen", FakePopen)
    assert run(tmp_path, "start", "j", "--command", "true") == 0
    job = home_job(tmp_path)
    assert launched == [[sys.executable, "-m", "unattended", "--home", str(tmp_path / "home"),
                         "supervise", str(job.dir)]]  # fmt: skip
    assert printed(capsys)["supervisor_pid"] == os.getpid()
    assert job.path(PID_FILE).read_text() == str(os.getpid())


def test_start_detached_for_real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "POLL", 0.1)
    assert run(tmp_path, "start", "j", "--command", "echo detached") == 0
    assert run(tmp_path, "wait", "j") == 0
    assert "detached" in (home_job(tmp_path).path("output.log")).read_text()


def test_start_uses_the_repo_jobs_dir(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".claude/jobs").mkdir(parents=True)
    assert run(tmp_path, "start", "j", "--command", "true", "--foreground") == 0
    assert (tmp_path / ".claude/jobs/j/state.json").is_file()


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--prompt", "p", "--resume-command", "c"], "--resume-command only apply to command"),
        (["--command", "c", "--model", "m"], "--model only apply to prompt jobs"),
        (["--command", "c", "--cwd", "nowhere"], "--cwd nowhere is not a directory"),
        (["--prompt-file", "missing.md"], "cannot read --prompt-file"),
        (["--command", "c", "--until", "2001-01-01T00:00"], "has already passed"),
        (["--command", "c", "--for", "soon"], "cannot read duration"),
        (["--command", "c", "--until", "noon"], "cannot read time"),
        (["--command", "c", "--fallback-wait", "x"], "cannot read duration"),
        (["--command", "c", "--auth", "api-key", "--key-file", "k"], "no API key file"),
    ],
)
def test_start_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str], message: str
) -> None:
    assert run(tmp_path, "start", "j", *argv, "--foreground") == 1
    assert message in capsys.readouterr().err


def test_start_login_refuses_an_inherited_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(ENV_VAR, "sk-x")
    assert run(tmp_path, "start", "j", "--command", "true") == 1
    assert "auth is login" in capsys.readouterr().err
    assert not (tmp_path / "home").exists()


def test_start_api_key_passes_the_key(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    key = tmp_path / "key"
    key.write_text("sk-file")
    key.chmod(0o600)
    command = f'echo "${ENV_VAR}"'
    argv = ["--command", command, "--auth", "api-key", "--key-file", str(key), "--foreground"]
    assert run(tmp_path, "start", "j", *argv) == 0
    assert "sk-file" in home_job(tmp_path).path("output.log").read_text()
    assert "sk-file" not in home_job(tmp_path).path("state.json").read_text()


def test_start_needs_a_source() -> None:
    with pytest.raises(SystemExit):
        cli.main(["start", "j"])
    with pytest.raises(SystemExit):
        cli.main(["start", "j", "--prompt", "p", "--command", "c"])


def test_start_refuses_a_duplicate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make(tmp_path)
    assert run(tmp_path, "start", "j", "--command", "true") == 1
    assert "already exists" in capsys.readouterr().err


def test_supervisor_crash_marks_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(job: Job, env: dict[str, str]) -> Any:
        raise RuntimeError("bug")

    monkeypatch.setitem(cli.RUNNERS, JobKind.COMMAND, broken)
    assert run(tmp_path, "start", "j", "--command", "true", "--foreground") == 1
    assert printed(capsys)["reason"] == "supervisor crashed: RuntimeError: bug"


# ----- status / list / wait / log ------------------------------------------------------


def test_status_and_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make(tmp_path)
    assert run(tmp_path, "status", "j") == 0
    assert printed(capsys)["status"] == "stopped"
    assert run(tmp_path, "status") == 0
    assert [r["name"] for r in printed(capsys)] == ["j"]
    assert run(tmp_path, "list") == 0
    assert len(printed(capsys)) == 1


def test_status_warns_about_an_orphan(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make(tmp_path, JobStatus.WAITING)
    run(tmp_path, "status", "j")
    assert "no supervisor is running" in printed(capsys)["warning"]


def test_status_of_an_unknown_job(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run(tmp_path, "status", "ghost") == 1
    assert "no job named 'ghost'" in capsys.readouterr().err


def test_wait_until_the_job_ends(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    job = make(tmp_path, JobStatus.RUNNING)
    job.path(PID_FILE).write_text(str(os.getpid()))

    def finish(seconds: float) -> None:
        job.update(lambda st: st.mark(JobStatus.LIMIT_REACHED, "used all 10 resumes"))

    args = cli.build_parser().parse_args(["--home", str(tmp_path / "home"), "wait", "j"])
    assert cli.cmd_wait(args, finish) == 75
    assert printed(capsys)["reason"] == "used all 10 resumes"


def test_wait_on_an_orphan_returns(tmp_path: Path) -> None:
    make(tmp_path, JobStatus.WAITING)
    assert run(tmp_path, "wait", "j") == 1


def test_log_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run(tmp_path, "start", "j", "--command", "echo logged", "--foreground")
    capsys.readouterr()
    assert run(tmp_path, "log", "j") == 0
    out = capsys.readouterr().out
    assert '"event": "end"' in out
    assert out.count("\nlogged\n") == 1


def test_log_follow(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    job = make(tmp_path, JobStatus.RUNNING)
    job.path(PID_FILE).write_text(str(os.getpid()))
    job.event("start")

    def progress(seconds: float) -> None:
        job.event("run")
        job.update(lambda st: st.mark(JobStatus.DONE))

    argv = ["--home", str(tmp_path / "home"), "log", "j", "-f"]
    assert cli.cmd_log(cli.build_parser().parse_args(argv), progress) == 0
    out = capsys.readouterr().out
    assert out.index('"start"') < out.index('"run"')


# ----- stop / resume ---------------------------------------------------------------------


def test_stop_signals_the_supervisor(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    job = make(tmp_path, JobStatus.WAITING)
    job.path(PID_FILE).write_text(str(os.getpid()))
    sent: list[tuple[int, int]] = []
    args = cli.build_parser().parse_args(["--home", str(tmp_path / "home"), "stop", "j"])
    assert cli.cmd_stop(args, lambda pid, sig: sent.append((pid, sig))) == 0
    assert sent == [(os.getpid(), signal.SIGTERM)]
    assert job.stop_requested()


def test_stop_without_a_supervisor(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    job = make(tmp_path, JobStatus.WAITING)
    assert run(tmp_path, "stop", "j") == 0
    assert job.load().status is JobStatus.STOPPED
    assert "no supervisor was running" in capsys.readouterr().out


def test_stop_an_ended_job(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make(tmp_path, JobStatus.DONE)
    assert run(tmp_path, "stop", "j") == 0
    assert "already ended: done" in capsys.readouterr().out


def test_resume_with_new_limits(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    job = make(tmp_path)
    job.update(lambda st: setattr(st, "runs", 1))
    job.request_stop()
    argv = ["resume", "j", "--max-resumes", "3", "--max-cost", "2", "--for", "1h", "--foreground"]
    assert run(tmp_path, *argv) == 0
    report = printed(capsys)
    assert (report["status"], report["max_resumes"], report["max_cost"]) == ("done", 3, 2.0)
    assert report["deadline"] is not None
    assert "again" in job.path("output.log").read_text()


def test_resume_keeps_limits_not_given(tmp_path: Path) -> None:
    job = make(tmp_path)
    job.update(lambda st: setattr(st.bounds, "max_cost", 4.0))
    assert run(tmp_path, "resume", "j", "--foreground") == 0
    assert job.load().bounds.max_cost == 4.0


def test_resume_an_orphan(tmp_path: Path) -> None:
    make(tmp_path, JobStatus.WAITING)
    assert run(tmp_path, "resume", "j", "--foreground") == 0


@pytest.mark.parametrize("status", [JobStatus.DONE, JobStatus.FAILED])
def test_resume_reruns_an_ended_job(tmp_path: Path, status: JobStatus) -> None:
    job = make(tmp_path, status)
    job.update(lambda st: setattr(st, "retries", 4))
    assert run(tmp_path, "resume", "j", "--foreground") == 0
    assert (job.load().status, job.load().retries) == (JobStatus.DONE, 0)


def test_resume_refuses_a_running_job(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make(tmp_path, JobStatus.WAITING).path(PID_FILE).write_text(str(os.getpid()))
    assert run(tmp_path, "resume", "j") == 1


def test_resume_refuses_a_passed_deadline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = make(tmp_path)
    job.update(lambda st: setattr(st.bounds, "deadline", time.time() - 60))
    assert run(tmp_path, "resume", "j") == 1
    assert "has already passed" in capsys.readouterr().err


def test_supervise_a_job_directory(tmp_path: Path) -> None:
    job = make(tmp_path, JobStatus.RUNNING)
    assert run(tmp_path, "supervise", str(job.dir)) == 0
    assert job.load().status is JobStatus.DONE


def test_keyboard_interrupt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupt(args: Any) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "job_home", interrupt)
    assert run(tmp_path, "list") == 130


def test_resume_refuses_a_used_up_cost_cap(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = make(tmp_path, JobStatus.LIMIT_REACHED)
    job.update(lambda st: (setattr(st.bounds, "max_cost", 2.0), setattr(st, "cost", 2.1)))
    assert run(tmp_path, "resume", "j") == 1
    assert "$2.10 spent reaches the cost cap" in capsys.readouterr().err
    assert run(tmp_path, "resume", "j", "--max-cost", "5", "--foreground") == 0
    assert job.load().status is JobStatus.DONE


def test_resume_now_wakes_a_waiting_supervisor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    job = make(tmp_path, JobStatus.WAITING)
    job.path(PID_FILE).write_text(str(os.getpid()))
    assert run(tmp_path, "resume", "j", "--now", "--max-resumes", "5") == 0
    assert job.wake_requested()
    assert job.load().bounds.max_resumes == 5
    assert "resuming now" in capsys.readouterr().out


def test_resume_without_now_points_at_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make(tmp_path, JobStatus.WAITING).path(PID_FILE).write_text(str(os.getpid()))
    assert run(tmp_path, "resume", "j") == 1
    assert "use --now" in capsys.readouterr().err


def test_resume_now_on_a_stopped_job_restarts_it(tmp_path: Path) -> None:
    job = make(tmp_path)
    assert run(tmp_path, "resume", "j", "--now", "--foreground") == 0
    assert job.load().status is JobStatus.DONE

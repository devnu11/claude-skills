from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest
from unattended import command_job
from unattended.command_job import CommandJob
from unattended.limits import Outcome, OutcomeKind
from unattended.store import LOG_FILE

from .conftest import MakeJob, command_spec

# Exits 75 with a reset note the first time, then 0.
LIMIT_ONCE = """
if [ -e once ]; then echo finished; exit 0; fi
touch once
echo "working"
echo "You've hit your session limit · resets 7pm"
exit 75
"""


def script(workdir: Path, body: str) -> str:
    path = workdir / "job.sh"
    path.write_text(body)
    return f"sh {path}"


def test_done(make_job: MakeJob, workdir: Path) -> None:
    job = make_job(command_spec(workdir, "echo hello"))
    assert CommandJob(job, os.environ).run_once() == Outcome(OutcomeKind.DONE)
    assert job.path(LOG_FILE).read_text() == "--- run 1: echo hello\nhello\n"


def test_limit_then_done(make_job: MakeJob, workdir: Path) -> None:
    job = make_job(command_spec(workdir, script(workdir, LIMIT_ONCE)))
    runner = CommandJob(job, os.environ)
    assert runner.run_once() == Outcome(OutcomeKind.LIMIT, "session limit, resets 7pm")
    job.update(lambda st: setattr(st, "runs", 1))
    assert runner.run_once().kind is OutcomeKind.DONE
    assert "finished" in job.path(LOG_FILE).read_text()


def test_resume_command_after_the_first_run(make_job: MakeJob, workdir: Path) -> None:
    job = make_job(command_spec(workdir, "echo first", "echo again"))
    job.update(lambda st: setattr(st, "runs", 1))
    CommandJob(job, os.environ).run_once()
    assert job.path(LOG_FILE).read_text().splitlines() == ["--- run 2: echo again", "again"]


def test_runs_in_cwd_with_env(make_job: MakeJob, workdir: Path) -> None:
    job = make_job(command_spec(workdir, 'pwd; echo "$UNATTENDED_TEST"'))
    CommandJob(job, {**os.environ, "UNATTENDED_TEST": "yes"}).run_once()
    lines = job.path(LOG_FILE).read_text().splitlines()
    assert Path(lines[1]).resolve() == workdir.resolve()
    assert lines[2] == "yes"


def test_failure(make_job: MakeJob, workdir: Path) -> None:
    job = make_job(command_spec(workdir, "exit 3"))
    assert CommandJob(job, os.environ).run_once() == Outcome(OutcomeKind.FAILED, "exit code 3")


def test_network_failure_is_offline() -> None:
    text = "agile-team start: crashed: API Error: Can't reach the API server (ENOTFOUND)"
    expected = Outcome(OutcomeKind.OFFLINE, "API server unreachable, exit code 70")
    assert command_job.outcome_for(70, text) == expected


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("resets 7pm", "usage limit, resets 7pm"),
        ("You've hit your session limit\nresets 2am (America/Edmonton)",
         "session limit, resets 2am (America/Edmonton)"),
        ("agile-team start: session limit, resets 7:20pm (UTC); run `agile-team start --resume`",
         "usage limit, resets 7:20pm (UTC)"),
        ("You've hit your weekly limit", "weekly limit"),
        ("nothing useful", command_job.DEFAULT_LIMIT_REASON),
    ],
)  # fmt: skip
def test_limit_reasons(text: str, reason: str) -> None:
    assert command_job.outcome_for(75, text) == Outcome(OutcomeKind.LIMIT, reason)


def test_tail_keeps_the_last_lines(tmp_path: Path) -> None:
    log = tmp_path / "log"
    log.write_text("".join(f"line {n}\n" for n in range(200)))
    lines = command_job.tail(log).splitlines()
    assert len(lines) == command_job.TAIL_LINES
    assert lines[-1] == "line 199"


def test_end_stops_the_process_group() -> None:
    proc = subprocess.Popen(["sh", "-c", "sleep 30 & wait"], start_new_session=True)
    command_job.end(proc)
    assert proc.returncode is not None


def test_end_kills_after_the_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(command_job, "TERM_GRACE", 0.2)
    proc = subprocess.Popen(
        ["sh", "-c", "trap '' TERM; echo ready; sleep 30"],
        start_new_session=True,
        stdout=subprocess.PIPE,
    )
    assert proc.stdout is not None and proc.stdout.readline() == b"ready\n"
    started = time.monotonic()
    command_job.end(proc)
    assert proc.returncode is not None
    assert time.monotonic() - started < 10


def test_end_ignores_a_finished_process() -> None:
    proc = subprocess.Popen(["true"])
    proc.wait()
    command_job.end(proc)

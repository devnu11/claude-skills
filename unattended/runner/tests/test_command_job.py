from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from unattended import command_job
from unattended.command_job import CommandJob, RunOutput
from unattended.limits import Bounds, Outcome, OutcomeKind
from unattended.store import LOG_FILE, Job
from unattended.watch import RunWatch, StopRequested

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
    assert CommandJob(job, os.environ).run_once(RunWatch(job)) == Outcome(OutcomeKind.DONE)
    assert job.path(LOG_FILE).read_text() == "--- run 1: echo hello\nhello\n"


def test_limit_then_done(make_job: MakeJob, workdir: Path) -> None:
    job = make_job(command_spec(workdir, script(workdir, LIMIT_ONCE)))
    runner = CommandJob(job, os.environ)
    assert runner.run_once(RunWatch(job)) == Outcome(OutcomeKind.LIMIT, "session limit, resets 7pm")
    job.update(lambda st: setattr(st, "runs", 1))
    assert runner.run_once(RunWatch(job)).kind is OutcomeKind.DONE
    assert "finished" in job.path(LOG_FILE).read_text()


def test_resume_command_after_the_first_run(make_job: MakeJob, workdir: Path) -> None:
    job = make_job(command_spec(workdir, "echo first", "echo again"))
    job.update(lambda st: setattr(st, "runs", 1))
    CommandJob(job, os.environ).run_once(RunWatch(job))
    assert job.path(LOG_FILE).read_text().splitlines() == ["--- run 2: echo again", "again"]


def test_runs_in_cwd_with_env(make_job: MakeJob, workdir: Path) -> None:
    job = make_job(command_spec(workdir, 'pwd; echo "$UNATTENDED_TEST"'))
    CommandJob(job, {**os.environ, "UNATTENDED_TEST": "yes"}).run_once(RunWatch(job))
    lines = job.path(LOG_FILE).read_text().splitlines()
    assert Path(lines[1]).resolve() == workdir.resolve()
    assert lines[2] == "yes"


def test_failure(make_job: MakeJob, workdir: Path) -> None:
    job = make_job(command_spec(workdir, "exit 3"))
    outcome = CommandJob(job, os.environ).run_once(RunWatch(job))
    assert outcome == Outcome(OutcomeKind.FAILED, "exit code 3")


def test_network_failure_is_offline() -> None:
    text = "agile-team start: crashed: API Error: Can't reach the API server (ENOTFOUND)"
    expected = Outcome(OutcomeKind.OFFLINE, "API server unreachable, exit code 70")
    assert command_job.outcome_for(70, out(text)) == expected


def out(text: str, cwd: Path = Path("/nonexistent-s37")) -> RunOutput:
    return RunOutput(text, cwd)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("resets 7pm", "usage limit, resets 7pm"),
        ("You've hit your session limit\nresets 2am (America/Edmonton)",
         "session limit, resets 2am (America/Edmonton)"),
        ("agile-team start: session limit, resets 7:20pm (UTC); run `agile-team start --resume`",
         "session limit, resets 7:20pm (UTC)"),
        ("You've hit your weekly limit", "weekly limit"),
        ("nothing useful", command_job.DEFAULT_LIMIT_REASON),
        ("the count resets the count", command_job.DEFAULT_LIMIT_REASON),
        ("resets the count", command_job.DEFAULT_LIMIT_REASON),
    ],
)  # fmt: skip
def test_limit_reasons(text: str, reason: str) -> None:
    assert command_job.outcome_for(75, out(text)) == Outcome(OutcomeKind.LIMIT, reason)


LIVE = (
    "agile-team start: session limit, resets 9pm (America/Chicago); "
    "run `agile-team start --resume` after the reset\n"
    "PO: AC4 resets the count) and add AC4b for the fallback wait\n"
)
HALTED = "agile-team start: session limit, resets 9pm (UTC); run `agile-team start --resume`\n"


def write_status(cwd: Path, content: str) -> None:
    path = cwd / command_job.STATUS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def blocked(reason: str) -> str:
    return json.dumps({"status": "blocked", "status_reason": reason})


def test_live_case_reads_the_halt_line_not_the_po_text(tmp_path: Path) -> None:
    expected = Outcome(OutcomeKind.LIMIT, "session limit, resets 9pm (America/Chicago)")
    assert command_job.outcome_for(75, out(LIVE, tmp_path)) == expected


def test_the_last_halt_line_wins(tmp_path: Path) -> None:
    text = HALTED + "agile-team start: weekly limit; run `agile-team start --resume`\n"
    assert command_job.halt_reason(out(text, tmp_path)) == "weekly limit"


def test_no_halt_line(tmp_path: Path) -> None:
    assert command_job.halt_reason(out("PO: hello", tmp_path)) is None


def test_halt_line_beats_the_status_file(tmp_path: Path) -> None:
    write_status(tmp_path, blocked("from the file"))
    outcome = command_job.outcome_for(75, out(HALTED, tmp_path))
    assert outcome.reason == "session limit, resets 9pm (UTC)"


def test_blocked_status_file_gives_its_reason(tmp_path: Path) -> None:
    write_status(tmp_path, blocked("session limit, resets 4am (UTC)"))
    outcome = command_job.outcome_for(75, out("PO: resets 7pm", tmp_path))
    assert outcome == Outcome(OutcomeKind.LIMIT, "session limit, resets 4am (UTC)")


@pytest.mark.parametrize(
    "content",
    [
        json.dumps({"status": "running", "status_reason": "x"}),
        json.dumps({"status": "blocked"}),
        json.dumps({"status": "blocked", "status_reason": ""}),
        json.dumps({"status": "blocked", "status_reason": 5}),
        "{not json",
        "[1, 2]",
        None,
    ],
)
def test_unusable_status_file_falls_through_to_free_text(
    tmp_path: Path, content: str | None
) -> None:
    if content is not None:
        write_status(tmp_path, content)
    outcome = command_job.outcome_for(75, out("limit hit, resets 7pm", tmp_path))
    assert outcome.reason == "usage limit, resets 7pm"
    assert command_job.status_reason(out("", tmp_path)) is None


def test_unreadable_status_file_is_no_reason(tmp_path: Path) -> None:
    (tmp_path / command_job.STATUS_FILE).mkdir(parents=True)
    assert command_job.status_reason(out("", tmp_path)) is None


def test_run_once_passes_cwd_to_the_status_file(make_job: MakeJob, workdir: Path) -> None:
    write_status(workdir, blocked("session limit, resets 4am (UTC)"))
    job = make_job(command_spec(workdir, "echo PO says resets the count; exit 75"))
    outcome = CommandJob(job, os.environ).run_once(RunWatch(job))
    assert outcome == Outcome(OutcomeKind.LIMIT, "session limit, resets 4am (UTC)")


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


# ----- watched runs ----------------------------------------------------------------------

PAST = 1_000.0


def watched(job: Job, *, hardstop: float | None = None) -> RunWatch:
    """A watch whose deadline has long passed, checking every 50 ms."""
    job.update(lambda st: setattr(st, "bounds", Bounds(deadline=PAST, hardstop=hardstop)))
    return RunWatch(job, time.time, 0.05)


def test_the_hard_stop_terms_a_sleeping_command(make_job: MakeJob, workdir: Path) -> None:
    job = make_job(command_spec(workdir, "sleep 30"))
    watch = watched(job, hardstop=0.0)
    started = time.monotonic()
    outcome = watch.settle(CommandJob(job, os.environ).run_once(watch))
    assert time.monotonic() - started < 10
    assert outcome == Outcome(OutcomeKind.HALTED, "deadline (hard stop after 0s)")


def test_the_graceful_stop_runs_the_stop_command(make_job: MakeJob, workdir: Path) -> None:
    spec = command_spec(workdir, "while [ ! -e stopped ]; do sleep 0.05; done; echo clean exit")
    spec.stop_command = "touch stopped"
    job = make_job(spec)
    watch = watched(job)
    outcome = CommandJob(job, os.environ).run_once(watch)
    assert outcome == Outcome(OutcomeKind.DONE)
    assert watch.settle(outcome).reason == "deadline (graceful)"
    lines = job.path(LOG_FILE).read_text().splitlines()
    assert lines[1:] == ["--- stop command: touch stopped", "clean exit"]


def test_a_slow_stop_command_times_out(
    make_job: MakeJob, workdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(command_job, "STOP_TIMEOUT", 0.1)
    spec = command_spec(workdir, "true")
    spec.stop_command = "sleep 5"
    job = make_job(spec)
    with job.path(LOG_FILE).open("a") as out:
        command_job.CommandRun(job.load(), out.fileno(), dict(os.environ)).stop_gracefully()
    assert "stop command timed out after 0.1 s" in job.path(LOG_FILE).read_text()


def test_exit_code_within_the_timeout() -> None:
    proc = subprocess.Popen(["sleep", "5"])
    assert command_job.exit_code(proc, 0.01) is None
    proc.kill()
    assert command_job.exit_code(proc, 5) is not None


def test_the_command_finds_its_heartbeat_path(make_job: MakeJob, workdir: Path) -> None:
    job = make_job(command_spec(workdir, 'echo "$UNATTENDED_HEARTBEAT"'))
    CommandJob(job, os.environ).run_once(RunWatch(job))
    assert job.path(LOG_FILE).read_text().splitlines()[1] == str(job.path("heartbeat.json"))


def test_a_stop_file_ends_the_run(make_job: MakeJob, workdir: Path) -> None:
    job = make_job(command_spec(workdir, "sleep 30"))
    job.request_stop()
    started = time.monotonic()
    with pytest.raises(StopRequested):
        CommandJob(job, os.environ).run_once(RunWatch(job, time.time, 0.05))
    assert time.monotonic() - started < 10

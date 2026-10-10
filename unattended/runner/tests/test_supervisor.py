from __future__ import annotations

import json
import os
import signal
from collections.abc import Callable
from datetime import timedelta
from itertools import pairwise
from pathlib import Path

import pytest
from unattended import supervisor
from unattended.limits import GRACE, Bounds, Metrics, Outcome, OutcomeKind, local
from unattended.store import EVENTS_FILE, Job, JobKind, JobStatus, Spec
from unattended.supervisor import StopRequested, Supervisor

from .conftest import MakeJob

START = 1_800_000_000.0
DONE = Outcome(OutcomeKind.DONE, metrics=Metrics(cost=0.5))
LIMIT = Outcome(OutcomeKind.LIMIT, "session limit, resets 7pm", Metrics(cost=1.0))
UNREADABLE = Outcome(OutcomeKind.LIMIT, "session limit")
RATE = Outcome(OutcomeKind.RATE_LIMITED, "rate limited")


class FakeClock:
    """A clock that only moves when slept on; records each sleep."""

    def __init__(self) -> None:
        self.now = START
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class Script:
    """A runner returning ``outcomes`` in order; ``before`` runs ahead of each."""

    def __init__(self, *outcomes: Outcome) -> None:
        self.outcomes = list(outcomes)
        self.before: Callable[[], None] = lambda: None

    def run_once(self) -> Outcome:
        self.before()
        return self.outcomes.pop(0)


@pytest.fixture
def job(make_job: MakeJob, workdir: Path) -> Job:
    return make_job(Spec(JobKind.PROMPT, str(workdir), prompt="p", fallback_wait=3600.0))


def supervise(job: Job, script: Script) -> tuple[JobStatus, FakeClock]:
    clock = FakeClock()
    return Supervisor(job, script, clock, clock.sleep).run(), clock


def events(job: Job) -> list[str]:
    lines = job.path(EVENTS_FILE).read_text().splitlines()
    return [json.loads(line)["event"] for line in lines]


def test_done(job: Job) -> None:
    status, clock = supervise(job, Script(DONE))
    state = job.load()
    assert status is JobStatus.DONE
    assert (state.status, state.runs, state.resumes, state.cost) == (JobStatus.DONE, 1, 0, 0.5)
    assert clock.sleeps == []
    assert events(job) == ["run", "end"]


def test_failed(job: Job) -> None:
    status, _ = supervise(job, Script(Outcome(OutcomeKind.FAILED, "exit code 2")))
    assert status is JobStatus.FAILED
    assert job.load().reason == "exit code 2"


def test_limit_then_resume_then_done(job: Job) -> None:
    status, clock = supervise(job, Script(LIMIT, DONE))
    state = job.load()
    assert status is JobStatus.DONE
    assert (state.runs, state.resumes, state.cost) == (2, 1, 1.5)
    assert state.next_wake is None
    assert events(job) == ["run", "wait", "resume", "run", "end"]
    reset = local(START).replace(hour=19, minute=0, second=0, microsecond=0)
    reset = reset if reset.timestamp() > START else reset + timedelta(days=1)
    assert clock.now == (reset + GRACE).timestamp()
    assert max(clock.sleeps) <= supervisor.SLICE


def test_unreadable_reset_uses_the_fallback(job: Job) -> None:
    _, clock = supervise(job, Script(UNREADABLE, DONE))
    assert clock.now == START + 3600.0


def test_waiting_state_while_asleep(job: Job) -> None:
    script = Script(UNREADABLE, DONE)
    seen: list[tuple[JobStatus, float | None]] = []
    clock = FakeClock()

    def sleep(seconds: float) -> None:
        state = job.load()
        seen.append((state.status, state.next_wake))
        clock.sleep(seconds)

    Supervisor(job, script, clock, sleep).run()
    assert seen[0] == (JobStatus.WAITING, START + 3600.0)


def test_rate_limit_backoff_doubles_then_resets(job: Job) -> None:
    clock = FakeClock()
    script = Script(RATE, RATE, RATE, UNREADABLE, RATE, DONE)
    starts: list[float] = []
    script.before = lambda: starts.append(clock.now)
    Supervisor(job, script, clock, clock.sleep).run()
    gaps = [later - earlier for earlier, later in pairwise(starts)]
    assert gaps == [60.0, 120.0, 240.0, 3600.0, 60.0]
    assert (job.load().resumes, job.load().retries) == (5, 0)


def test_stop_file_while_waiting(job: Job) -> None:
    clock = FakeClock()
    script = Script(UNREADABLE, DONE)

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.now >= START + 90:
            job.request_stop()

    status = Supervisor(job, script, clock, sleep).run()
    assert status is JobStatus.STOPPED
    assert job.load().reason == supervisor.STOP_REASON
    assert job.load().resumes == 0
    assert clock.now == START + 90


def test_stop_file_before_the_first_run(job: Job) -> None:
    job.request_stop()
    status, _ = supervise(job, Script(DONE))
    assert status is JobStatus.STOPPED
    assert job.load().runs == 0


def test_stop_during_a_run(job: Job) -> None:
    script = Script(DONE)

    def interrupted() -> None:
        raise StopRequested

    script.before = interrupted
    status, _ = supervise(job, script)
    assert status is JobStatus.STOPPED


def test_resumes_used_up(job: Job) -> None:
    job.update(lambda st: setattr(st, "bounds", Bounds(max_resumes=1)))
    status, _ = supervise(job, Script(UNREADABLE, UNREADABLE, DONE))
    state = job.load()
    assert status is JobStatus.LIMIT_REACHED
    assert state.reason == "session limit; used all 1 resumes"
    assert (state.runs, state.resumes) == (2, 1)


def test_deadline_before_the_next_wake(job: Job) -> None:
    job.update(lambda st: setattr(st, "bounds", Bounds(deadline=START + 600)))
    status, clock = supervise(job, Script(UNREADABLE, DONE))
    assert status is JobStatus.LIMIT_REACHED
    assert "comes before the next wake" in job.load().reason
    assert clock.sleeps == []


def test_cost_reached(job: Job) -> None:
    job.update(lambda st: setattr(st, "bounds", Bounds(max_cost=1.0)))
    status, _ = supervise(job, Script(LIMIT, DONE))
    assert status is JobStatus.LIMIT_REACHED
    assert job.load().reason.endswith("cost $1.00 reached the $1.00 cap")


def test_sigterm_raises_stop_requested() -> None:
    previous = signal.getsignal(signal.SIGTERM)
    try:
        supervisor.install_sigterm()
        with pytest.raises(StopRequested):
            os.kill(os.getpid(), signal.SIGTERM)
    finally:
        signal.signal(signal.SIGTERM, previous)


def test_budget_stop_ends_without_waiting(job: Job) -> None:
    budget = Outcome(OutcomeKind.BUDGET, "cost cap reached mid-run", Metrics(cost=2.0))
    status, clock = supervise(job, Script(budget))
    assert status is JobStatus.LIMIT_REACHED
    assert (job.load().reason, job.load().cost) == ("cost cap reached mid-run", 2.0)
    assert clock.sleeps == []


def test_wake_file_cuts_the_wait_short(job: Job) -> None:
    clock = FakeClock()
    script = Script(UNREADABLE, DONE)

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        if clock.now >= START + 60:
            job.request_wake()

    assert Supervisor(job, script, clock, sleep).run() is JobStatus.DONE
    state = job.load()
    assert (state.resumes, state.runs) == (1, 2)
    assert clock.now == START + 60
    assert not job.wake_requested()
    events = [json.loads(line)["event"] for line in job.path(EVENTS_FILE).read_text().splitlines()]
    assert events.count("wake") == 1


# ----- offline -----------------------------------------------------------------------

OFFLINE = Outcome(OutcomeKind.OFFLINE, "API server unreachable")


class Network:
    """A probe that is down for ``down`` checks, then up; counts the checks."""

    def __init__(self, down: int) -> None:
        self.down, self.checks = down, 0

    def __call__(self) -> bool:
        self.checks += 1
        return self.checks > self.down


def offline_run(job: Job, script: Script, net: Network) -> tuple[JobStatus, FakeClock]:
    clock = FakeClock()
    return Supervisor(job, script, clock, clock.sleep, net).run(), clock


def test_offline_waits_for_the_network_without_a_resume(job: Job) -> None:
    status, clock = offline_run(job, Script(OFFLINE, DONE), Network(down=2))
    state = job.load()
    assert status is JobStatus.DONE
    assert (state.runs, state.resumes, state.retries) == (2, 0, 0)
    assert clock.sleeps == [supervisor.SLICE] * 3
    assert events(job) == ["run", "offline", "online", "run", "end"]


def test_offline_marks_the_job_waiting(job: Job) -> None:
    seen: list[JobStatus] = []
    clock = FakeClock()

    def sleep(seconds: float) -> None:
        seen.append(job.load().status)
        clock.sleep(seconds)

    Supervisor(job, Script(OFFLINE, DONE), clock, sleep, Network(down=0)).run()
    assert seen == [JobStatus.WAITING]


def test_offline_past_the_deadline_is_limit_reached(job: Job) -> None:
    job.update(lambda st: setattr(st.bounds, "deadline", START + 90))
    status, clock = offline_run(job, Script(OFFLINE), Network(down=99))
    assert status is JobStatus.LIMIT_REACHED
    assert job.load().reason == "API server unreachable; deadline passed offline"
    assert clock.now == START + 90


def test_offline_too_many_times_in_a_row_fails(job: Job) -> None:
    script = Script(*[OFFLINE] * (supervisor.MAX_RECONNECTS + 1))
    status, _ = offline_run(job, script, Network(down=0))
    assert status is JobStatus.FAILED
    assert job.load().reason.endswith(f"{supervisor.MAX_RECONNECTS} reconnects in a row")


def test_stop_while_offline(job: Job) -> None:
    clock = FakeClock()

    def sleep(seconds: float) -> None:
        clock.sleep(seconds)
        job.request_stop()

    status = Supervisor(job, Script(OFFLINE), clock, sleep, Network(down=99)).run()
    assert status is JobStatus.STOPPED

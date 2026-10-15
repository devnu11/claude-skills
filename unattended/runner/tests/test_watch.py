"""RunWatch: the per-slice checks of a run, with a fake clock."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from unattended.limits import Bounds, Metrics, Outcome, OutcomeKind
from unattended.store import EVENTS_FILE, Job
from unattended.watch import RunWatch, Verdict

from .conftest import MakeJob, command_spec

DEADLINE = 1_800_000_000.0
DONE = Outcome(OutcomeKind.DONE, metrics=Metrics(cost=0.5))


class Clock:
    """A clock set by hand."""

    def __init__(self, now: float = DEADLINE - 1) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def with_bounds(job: Job, bounds: Bounds) -> Job:
    job.update(lambda st: setattr(st, "bounds", bounds))
    return job


@pytest.fixture
def job(make_job: MakeJob, workdir: Path) -> Job:
    return make_job(command_spec(workdir, "true"))


@pytest.fixture
def stoppable(make_job: MakeJob, workdir: Path) -> Job:
    spec = command_spec(workdir, "true")
    spec.stop_command = "agile-team stop"
    return make_job(spec)


def events(job: Job) -> list[dict[str, object]]:
    path = job.path(EVENTS_FILE)
    return [json.loads(line) for line in path.open()] if path.exists() else []


def test_no_deadline_never_stops(job: Job) -> None:
    watch = RunWatch(job, Clock(1e12))
    assert watch.check() == ()
    assert watch.settle(DONE) == DONE


def test_a_soft_deadline_does_nothing_mid_run(job: Job) -> None:
    watch = RunWatch(with_bounds(job, Bounds(deadline=DEADLINE)), Clock(DEADLINE + 1e6))
    assert watch.check() == ()
    assert events(job) == []
    assert watch.settle(DONE) == DONE


def test_the_stop_command_is_asked_for_once_at_the_deadline(stoppable: Job) -> None:
    clock = Clock()
    watch = RunWatch(with_bounds(stoppable, Bounds(deadline=DEADLINE)), clock)
    assert watch.check() == ()
    clock.now = DEADLINE
    assert watch.check() == (Verdict.GRACEFUL,)
    assert watch.check() == ()
    assert [e["event"] for e in events(stoppable)] == ["deadline"]
    assert events(stoppable)[0]["phase"] == "graceful"


def test_a_sent_stop_settles_any_outcome_as_halted(stoppable: Job) -> None:
    watch = RunWatch(with_bounds(stoppable, Bounds(deadline=DEADLINE)), Clock(DEADLINE))
    watch.check()
    expected = Outcome(OutcomeKind.HALTED, "deadline (graceful)", DONE.metrics)
    assert watch.settle(DONE) == expected


def test_the_hard_stop_ends_the_run_after_the_grace(job: Job) -> None:
    clock = Clock(DEADLINE)
    watch = RunWatch(with_bounds(job, Bounds(deadline=DEADLINE, hardstop=60.0)), clock)
    assert watch.check() == ()
    assert watch.halt is None
    clock.now = DEADLINE + 60
    assert watch.check() == (Verdict.END,)
    assert watch.settle(DONE).reason == "deadline (hard stop after 1m)"
    assert [(e["event"], e["phase"]) for e in events(job)] == [
        ("deadline", "graceful"), ("deadline", "hard"),
    ]  # fmt: skip


def test_a_late_check_sends_the_stop_command_before_the_hard_stop(stoppable: Job) -> None:
    bounds = Bounds(deadline=DEADLINE, hardstop=60.0)
    watch = RunWatch(with_bounds(stoppable, bounds), Clock(DEADLINE + 3600))
    assert watch.check() == (Verdict.GRACEFUL, Verdict.END)


def test_each_check_rereads_the_deadline(job: Job) -> None:
    clock = Clock(DEADLINE - 1)
    watch = RunWatch(with_bounds(job, Bounds(deadline=DEADLINE, hardstop=0.0)), clock)
    job.update(lambda st: setattr(st.bounds, "deadline", DEADLINE + 3600))
    clock.now = DEADLINE + 1
    assert watch.check() == ()

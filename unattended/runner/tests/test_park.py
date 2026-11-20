from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from unattended import park
from unattended.limits import Metrics, Outcome, OutcomeKind
from unattended.park import PARK_FILE, Park, ParkError
from unattended.steps import Advice
from unattended.store import EVENTS_FILE, Job

from .conftest import MakeJob
from .test_prompt_job import prompt_spec


@pytest.fixture
def job(make_job: MakeJob, workdir: Path) -> Job:
    return make_job(prompt_spec(workdir))


def request(job: Job, data: Any) -> None:
    job.path(PARK_FILE).write_text(json.dumps(data))


def logged(job: Job) -> list[dict[str, Any]]:
    return [json.loads(line) for line in job.path(EVENTS_FILE).read_text().splitlines()]


def test_no_file_is_no_park(job: Job) -> None:
    assert park.read_park(job) is None


def test_a_full_request(job: Job) -> None:
    request(job, {"check": "test -f done", "every": "2m", "reason": "export"})
    assert park.read_park(job) == Park("test -f done", 120.0, "export")


def test_defaults_every_five_minutes_and_the_check_as_reason(job: Job) -> None:
    request(job, {"check": "true"})
    assert park.read_park(job) == Park("true", 300.0, "true")


@pytest.mark.parametrize(
    ("data", "problem"),
    [
        ([], "expected a JSON object"),
        ({}, "check: a command is required"),
        ({"check": " "}, "check: a command is required"),
        ({"check": "true", "when": "later"}, "when: not a park field"),
        ({"check": "true", "every": 5}, "every: expected text"),
        ({"check": "true", "every": "soon"}, "cannot read duration"),
    ],
)
def test_unusable_requests(job: Job, data: Any, problem: str) -> None:
    request(job, data)
    with pytest.raises(ParkError, match=problem):
        park.read_park(job)


def test_text_that_is_not_json_is_unusable(job: Job) -> None:
    job.path(PARK_FILE).write_text("{")
    with pytest.raises(ParkError):
        park.read_park(job)


def test_find_refuses_and_removes_an_unusable_request(job: Job) -> None:
    request(job, {})
    assert park.find_park(job) is None
    assert not job.path(PARK_FILE).exists()
    assert logged(job)[-1]["event"] == "park-invalid"


def test_the_step_check_ends_a_parked_run(job: Job) -> None:
    assert park.stop_when_parked(job) == Advice()
    request(job, {"check": "true", "reason": "CI"})
    assert park.stop_when_parked(job) == Advice(stop="parked: CI")


def test_the_step_check_tells_the_agent_why_a_request_was_refused(job: Job) -> None:
    request(job, {"check": ""})
    advice = park.stop_when_parked(job)
    assert "check: a command is required" in advice.context
    assert advice.stop == ""
    assert not job.path(PARK_FILE).exists()


def test_settle_turns_a_finished_run_with_a_request_into_parked(job: Job) -> None:
    done = Outcome(OutcomeKind.DONE, metrics=Metrics(cost=0.5))
    assert park.settle_park(job, done) is done
    request(job, {"check": "true", "reason": "CI"})
    assert park.settle_park(job, done) == Outcome(OutcomeKind.PARKED, "parked: CI", done.metrics)


def test_settle_leaves_other_outcomes(job: Job) -> None:
    request(job, {"check": "true"})
    failed = Outcome(OutcomeKind.FAILED, "exit code 1")
    assert park.settle_park(job, failed) is failed
    assert job.path(PARK_FILE).exists()


def test_run_check_is_the_exit_code(tmp_path: Path) -> None:
    (tmp_path / "done").touch()
    assert park.run_check("test -f done", str(tmp_path))
    assert not park.run_check("test -f missing", str(tmp_path))


def test_a_check_that_times_out_is_not_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def slow(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(sys.executable, 1)

    monkeypatch.setattr(subprocess, "run", slow)
    assert not park.run_check("sleep 999", str(tmp_path))

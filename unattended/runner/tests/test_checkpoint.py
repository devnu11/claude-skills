from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from unattended import checkpoint
from unattended.checkpoint import (
    CHECKPOINT_FILE,
    Reply,
    build_resume_prompt,
    check_checkpoint,
    load_checkpoint,
    save_checkpoint,
)
from unattended.store import EVENTS_FILE, Job

from .conftest import MakeJob
from .fakes import GOOD
from .test_prompt_job import prompt_spec


@pytest.fixture
def job(make_job: MakeJob, workdir: Path) -> Job:
    return make_job(prompt_spec(workdir))


def last_event(job: Job) -> dict[str, Any]:
    return json.loads(job.path(EVENTS_FILE).read_text().splitlines()[-1])


def test_a_good_checkpoint_has_no_problems() -> None:
    assert check_checkpoint(GOOD) == []


def test_problems_name_their_path() -> None:
    bad = {**GOOD, "findings": [{"claim": 3, "evidence": "x"}], "extra": 1}
    del bad["goal"]
    assert check_checkpoint(bad) == [
        "$.goal: missing",
        "$.extra: not in the schema",
        "$.findings[0].claim: expected string",
        "$.findings[0].evidence: expected array",
    ]
    assert check_checkpoint([]) == ["$: expected object"]


def test_a_checkpoint_over_the_size_limit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checkpoint, "SIZE_LIMIT", 100)
    assert check_checkpoint(GOOD)[-1].endswith("over the 100-byte limit")


def test_save_stamps_and_load_returns_it(job: Job) -> None:
    assert load_checkpoint(job) is None
    save_checkpoint(job, Reply(3, GOOD))
    found = load_checkpoint(job)
    assert found is not None
    assert (found["schema_version"], found["run"], found["goal"]) == (1, 3, GOOD["goal"])
    assert last_event(job)["event"] == "checkpoint"


def test_an_invalid_checkpoint_keeps_the_old_one(job: Job) -> None:
    save_checkpoint(job, Reply(1, GOOD))
    save_checkpoint(job, Reply(2, {"goal": 1}))
    assert load_checkpoint(job)["run"] == 1
    event = last_event(job)
    assert event["event"] == "checkpoint-invalid"
    assert "$.goal: expected string" in event["problems"]
    assert not job.path(f".{CHECKPOINT_FILE}.tmp").exists()


def test_the_resume_prompt_carries_the_checkpoint() -> None:
    prompt = build_resume_prompt("Continue.", GOOD)
    assert prompt.startswith("Continue.\n\nCheckpoint from the previous run (JSON):\n")
    assert json.loads(prompt.split("(JSON):\n", 1)[1]) == GOOD

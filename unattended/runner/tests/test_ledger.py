from __future__ import annotations

from pathlib import Path

import pytest
from unattended.ledger import Ledger, read_calls
from unattended.pricing import RATES, Usage
from unattended.store import Job

from .conftest import MakeJob
from .test_prompt_job import prompt_spec


@pytest.fixture
def job(make_job: MakeJob, workdir: Path) -> Job:
    return make_job(prompt_spec(workdir))


def test_a_response_is_written_once_at_its_last_reading(job: Job) -> None:
    ledger = Ledger(job, 2, RATES)
    ledger.note(("m1", "claude-opus-5-5", Usage(input=10, output=1)))
    ledger.note(("m1", "claude-opus-5-5", Usage(input=10, output=9)))
    assert read_calls(job) == []
    ledger.note(("m2", "claude-opus-5-5", Usage(output=1)))
    calls = read_calls(job)
    assert len(calls) == 1
    assert calls[0]["run"] == 2
    assert calls[0]["message_id"] == "m1"
    assert calls[0]["tokens"]["output"] == 9
    assert calls[0]["usd"] == pytest.approx((10 * 4 + 9 * 20) / 1_000_000)


def test_close_writes_the_last_response_once(job: Job) -> None:
    ledger = Ledger(job, 1, RATES)
    ledger.close()
    ledger.note(("m1", "claude-haiku-5-5", Usage(cache_read=1_000_000)))
    ledger.close()
    ledger.close()
    calls = read_calls(job)
    assert [call["message_id"] for call in calls] == ["m1"]
    assert calls[0]["usd"] == pytest.approx(0.01)


def test_an_unpriced_model_has_no_dollars(job: Job) -> None:
    ledger = Ledger(job, 1, RATES)
    ledger.note(("m1", "mystery", Usage(output=5)))
    ledger.close()
    assert read_calls(job)[0]["usd"] is None

from __future__ import annotations

from pathlib import Path

import pytest
from unattended import inbox
from unattended.store import EVENTS_FILE, Job

from .conftest import MakeJob
from .test_prompt_job import prompt_spec


@pytest.fixture
def job(make_job: MakeJob, workdir: Path) -> Job:
    return make_job(prompt_spec(workdir))


def events(job: Job) -> list[str]:
    return [line for line in job.path(EVENTS_FILE).read_text().splitlines() if line]


def test_messages_wait_in_order_and_leave_when_taken(job: Job) -> None:
    inbox.queue_message(job, "first")
    inbox.queue_message(job, "second\n")
    assert inbox.count_messages(job) == 2
    taken = inbox.take_messages(job)
    assert [text.splitlines()[-1] for text in taken] == ["first", "second"]
    assert taken[0].startswith("Message from the operator (unattended tell), sent ")
    assert inbox.count_messages(job) == 0
    assert inbox.take_messages(job) == []


def test_an_empty_inbox_counts_nothing(job: Job) -> None:
    assert inbox.count_messages(job) == 0


def test_a_post_is_logged_and_never_half_written(job: Job) -> None:
    inbox.queue_message(job, "hello")
    assert '"event": "tell"' in events(job)[-1]
    assert not list(job.path(inbox.INBOX).glob(".*.tmp"))


def test_delivery_at_a_step_gives_the_model_the_messages(job: Job) -> None:
    assert inbox.deliver_at_step(job).context == ""
    inbox.queue_message(job, "look at the logs")
    advice = inbox.deliver_at_step(job)
    assert advice.context.endswith("look at the logs")
    assert advice.stop == ""
    assert '"at": "step"' in events(job)[-1]


def test_delivery_at_a_start_appends_to_the_prompt(job: Job) -> None:
    assert inbox.deliver_at_start(job, "Continue.") == "Continue."
    inbox.queue_message(job, "skip the tests")
    prompt = inbox.deliver_at_start(job, "Continue.")
    assert prompt.startswith("Continue.\n\nMessage from the operator")
    assert prompt.endswith("skip the tests")
    assert '"at": "start"' in events(job)[-1]

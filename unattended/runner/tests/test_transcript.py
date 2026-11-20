from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from unattended.store import Job
from unattended.transcript import Transcript, describe_message

from .conftest import MakeJob
from .test_prompt_job import prompt_spec, said


@pytest.fixture
def job(make_job: MakeJob, workdir: Path) -> Job:
    return make_job(prompt_spec(workdir))


def read_lines(transcript: Transcript) -> list[dict[str, Any]]:
    return [json.loads(line) for line in transcript.path.read_text().splitlines()]


@dataclass
class Odd:
    path: Path


def test_a_message_is_its_class_name_then_its_fields() -> None:
    line = describe_message(said("hi"))
    assert line["type"] == "AssistantMessage"
    assert line["content"] == [{"text": "hi"}]


def test_a_non_dataclass_message_is_kept_as_text() -> None:
    assert describe_message("raw") == {"type": "str", "value": "raw"}


def test_prompts_and_messages_go_in_order_to_one_file_per_run(job: Job) -> None:
    transcript = Transcript(job, 3)
    transcript.record_prompt("go")
    transcript.record_message(said("ok"))
    assert transcript.path == job.path("transcripts") / "run-3.jsonl"
    assert [line["type"] for line in read_lines(transcript)] == ["prompt", "AssistantMessage"]


def test_values_json_cannot_hold_are_written_as_text(job: Job) -> None:
    transcript = Transcript(job, 1)
    transcript.record_message(Odd(Path("/x")))
    assert read_lines(transcript) == [{"type": "Odd", "path": "/x"}]

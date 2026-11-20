from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import SystemMessage
from unattended import prefix
from unattended.store import EVENTS_FILE, Job

from .conftest import MakeJob
from .test_prompt_job import prompt_spec

INIT = {"model": "m", "tools": ["Read", "Bash"], "cwd": "/w", "session_id": "s1"}


@pytest.fixture
def job(make_job: MakeJob, workdir: Path) -> Job:
    return make_job(prompt_spec(workdir))


def prefix_events(job: Job) -> list[dict[str, Any]]:
    lines = map(json.loads, job.path(EVENTS_FILE).read_text().splitlines())
    return [event for event in lines if event["event"] == "prefix"]


def test_claude_codes_prompt_without_dynamic_sections_and_kept_fixed(workdir: Path) -> None:
    system = prefix.build_system_prompt(prompt_spec(workdir))
    assert system["preset"] == "claude_code"
    assert system["exclude_dynamic_sections"] is True
    assert system["snapshot"] is True


def test_the_jobs_own_prompt_is_kept_fixed(workdir: Path) -> None:
    spec = replace(prompt_spec(workdir), system_prompt="You triage.")
    assert prefix.build_system_prompt(spec) == {
        "type": "custom",
        "prompt": "You triage.",
        "snapshot": True,
    }


def test_only_prefix_parts_are_hashed_and_order_does_not_matter() -> None:
    parts = prefix.compute_part_hashes(INIT)
    assert set(parts) == {"model", "tools"}
    assert prefix.compute_hash({"a": 1, "b": 2}) == prefix.compute_hash({"b": 2, "a": 1})
    assert len(parts["tools"]) == prefix.HASH_CHARS


def test_each_init_logs_the_prefix_and_what_changed(job: Job) -> None:
    prefix.note_prefix(job, SystemMessage("init", INIT))
    prefix.note_prefix(job, SystemMessage("init", INIT | {"tools": ["Read"], "cwd": "/x"}))
    first, second = prefix_events(job)
    assert first["changed"] == []
    assert second["changed"] == ["tools"]
    assert job.load().prefix == second["parts"]


def test_other_messages_are_not_the_prefix(job: Job) -> None:
    prefix.note_prefix(job, SystemMessage("status", INIT))
    prefix.note_prefix(job, "text")
    assert job.load().prefix == {}

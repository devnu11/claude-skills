"""The snapshot's ``roles[].used`` flag (s104, FL7)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agile_team import config as cfg
from agile_team import state as state_mod
from agile_team.state import RunState, StoryState

from .test_snapshot import FIXTURE_TEXT, build, make_config, write_jsonl


@pytest.fixture
def config(scratch: Path) -> cfg.Config:
    return make_config(scratch / "repo")


def used(config: cfg.Config, scratch: Path) -> dict[str, bool]:
    return {r["name"]: r["used"] for r in build(config, scratch)["roles"]}


def step_start(role: str) -> dict[str, Any]:
    return {"id": "e1", "at": 1.0, "kind": "step-start", "role": role, "story": "s1", "data": {}}


def test_an_unrouted_unstepped_role_is_unused_until_its_first_step(
    config: cfg.Config, scratch: Path
) -> None:
    assert used(config, scratch)["developer-db"] is False
    write_jsonl(config.run_dir / "events.jsonl", [step_start("developer-db")])
    assert used(config, scratch)["developer-db"] is True


def test_the_pipeline_steps_route_to_their_roles(config: cfg.Config, scratch: Path) -> None:
    flags = used(config, scratch)
    assert flags["architect"] and flags["unit-tester"]


def test_a_step_left_out_of_the_pipeline_leaves_its_role_unused(
    config: cfg.Config, scratch: Path
) -> None:
    assert used(config, scratch)["integration-tester"] is False
    write_jsonl(config.run_dir / "events.jsonl", [step_start("integration-tester")])
    assert used(config, scratch)["integration-tester"] is True


def test_the_generic_developer_is_used_when_no_story_names_one(
    config: cfg.Config, scratch: Path
) -> None:
    assert used(config, scratch)["developer"] is True


@pytest.mark.parametrize("field", ["developer", "po_developer"])
def test_an_assigned_developer_replaces_the_generic_one(
    config: cfg.Config, scratch: Path, field: str
) -> None:
    story = StoryState("s1", "t", "implement")
    setattr(story, field, "developer-cli")
    state_mod.save(config.run_dir, RunState(stories={"s1": story}))
    flags = used(config, scratch)
    assert flags["developer-cli"] is True and flags["developer"] is False


def test_every_role_carries_used(config: cfg.Config, scratch: Path) -> None:
    assert all(isinstance(r["used"], bool) for r in build(config, scratch)["roles"])
    assert all("used" in r for r in json.loads(FIXTURE_TEXT)["roles"])


def test_a_pipeline_step_with_no_role_routes_nowhere(scratch: Path) -> None:
    config = make_config(scratch / "repo2", steps=["design", "mystery", "implement"])
    flags = used(config, scratch)
    assert flags["architect"] is True and flags["developer"] is True


def test_a_pipeline_without_implement_adds_no_developer(scratch: Path) -> None:
    config = make_config(scratch / "repo3", steps=["design", "tests"])
    flags = used(config, scratch)
    assert flags["developer"] is False and flags["architect"] is True

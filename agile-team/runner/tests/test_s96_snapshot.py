"""The snapshot's ``steps`` section (s96, ST7 and the fixture contract)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agile_team import config as cfg

from .clock import about
from .test_snapshot import FIXTURE_TEXT, build, make_config, write_jsonl, write_run


@pytest.fixture
def config(scratch: Path) -> cfg.Config:
    return make_config(scratch / "repo")


def row(kind: str, at: float, role: str, **data: Any) -> dict[str, Any]:
    return {"id": f"e{at}", "at": at, "kind": kind, "role": role, "story": "s1", "data": data}


def steps_for(config: cfg.Config, scratch: Path, events: list[dict]) -> list[dict]:
    write_jsonl(config.run_dir / "events.jsonl", events)
    return build(config, scratch)["steps"]


def test_the_end_model_wins(config: cfg.Config, scratch: Path) -> None:
    [step] = steps_for(
        config,
        scratch,
        [
            row("step-start", 1.0, "architect"),
            row("step-end", 3.0, "architect", status="done", model="haiku-x"),
        ],
    )
    assert step["model"] == "haiku-x" and step["seconds"] == about(2.0)


def test_a_missing_end_model_falls_back_to_the_configured_one(
    config: cfg.Config, scratch: Path
) -> None:
    events = [row("step-start", 1.0, "architect"), row("step-end", 3.0, "architect", status="done")]
    snap_steps = steps_for(config, scratch, events)
    roles = {r["name"]: r["model"] for r in build(config, scratch)["roles"]}
    assert snap_steps[0]["model"] == roles["architect"]


def test_a_running_step_uses_the_configured_model(config: cfg.Config, scratch: Path) -> None:
    [step] = steps_for(config, scratch, [row("step-start", 1.0, "architect")])
    roles = {r["name"]: r["model"] for r in build(config, scratch)["roles"]}
    assert step["model"] == roles["architect"]
    assert step["ended_at"] is None and step["seconds"] is None and step["status"] is None


def test_an_unknown_role_is_unknown_model(config: cfg.Config, scratch: Path) -> None:
    [step] = steps_for(config, scratch, [row("step-start", 1.0, "ghost-role")])
    assert step["model"] == "unknown"


def test_no_events_no_steps(config: cfg.Config, scratch: Path) -> None:
    assert steps_for(config, scratch, []) == []


def test_the_fixture_steps_are_what_the_builder_gives(scratch: Path) -> None:
    fixture = json.loads(FIXTURE_TEXT)
    config = write_run(scratch / "repo", fixture)
    assert build(config, scratch)["steps"] == fixture["steps"]


def test_the_fixture_has_exactly_one_running_step(scratch: Path) -> None:
    steps = json.loads(FIXTURE_TEXT)["steps"]
    running = [s for s in steps if s["ended_at"] is None]
    assert len(running) == 1
    assert steps[-1] is not None and all(s["model"] for s in steps)

"""The snapshot's step clocks, per platform (s97, AW4, AW9, fixture contract)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agile_team import config as cfg
from agile_team import live, system

from .fake_system import FakeSystem
from .test_snapshot import FIXTURE_TEXT, build, make_config, write_jsonl


@pytest.fixture
def config(scratch: Path) -> cfg.Config:
    return make_config(scratch / "repo")


def row(kind: str, at: float, **data: Any) -> dict[str, Any]:
    return {
        "id": f"e{at}",
        "at": at,
        "kind": kind,
        "role": "architect",
        "story": "s1",
        "data": data,
    }


def finished_with_a_sleep() -> list[dict]:
    """Wall 300 s, 120 s of it asleep: monotonic 180, counter 0 → 120."""
    return [
        row("step-start", 100.0, mono=1000.0, slept=0.0),
        row("step-end", 400.0, status="done", mono=1180.0, slept=120.0),
    ]


@pytest.mark.parametrize("name", ["darwin", "linux", "win32"])
def test_a_slept_step_counts_wall_minus_sleep_on_every_platform(
    config: cfg.Config, scratch: Path, fake: FakeSystem, name: str
) -> None:
    fake.platform_name = name
    write_jsonl(config.run_dir / "events.jsonl", finished_with_a_sleep())
    [step] = build(config, scratch)["steps"]
    assert (step["seconds"], step["clock"], step["slept"]) == (180.0, "awake", 120.0)


def test_a_running_step_on_windows_uses_the_heartbeat_sleep(
    config: cfg.Config, scratch: Path, fake: FakeSystem
) -> None:
    fake.platform_name = "win32"
    fake.clock = 700.0
    write_jsonl(config.run_dir / "events.jsonl", [row("step-start", 100.0, slept=50.0)])
    system.make_dirs(config.run_dir)
    system.write_text(config.run_dir / live.HEARTBEAT, json.dumps({"version": 2, "slept": 250.0}))
    [step] = build(config, scratch)["steps"]
    assert (step["seconds"], step["clock"], step["slept"]) == (None, "awake", 200.0)


def test_a_running_step_without_a_heartbeat_is_wall(
    config: cfg.Config, scratch: Path, fake: FakeSystem
) -> None:
    fake.platform_name = "win32"
    write_jsonl(config.run_dir / "events.jsonl", [row("step-start", 100.0, slept=50.0)])
    [step] = build(config, scratch)["steps"]
    assert (step["clock"], step["slept"]) == ("wall", 0.0)


def test_the_heartbeat_section_has_slept() -> None:
    assert "slept" in json.loads(FIXTURE_TEXT)["heartbeat"]


def test_the_fixture_has_awake_slept_wall_and_running_steps() -> None:
    steps = json.loads(FIXTURE_TEXT)["steps"]
    assert any(s["clock"] == "awake" and s["slept"] > 0 for s in steps)
    assert any(s["clock"] == "wall" and s["ended_at"] is not None for s in steps)
    assert any(s["ended_at"] is None for s in steps)

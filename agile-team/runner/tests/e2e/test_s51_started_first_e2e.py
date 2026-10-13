"""s51 end to end: started stories run before new ones; a pull-ahead needs a reason."""

from __future__ import annotations

import asyncio
import json

from agile_team import state
from agile_team.dashboard import snapshot
from agile_team.gates import StoryStatus
from agile_team.po_tools import Tools

from ..pipeline_helpers import Script, add_story, build, drive
from .test_priority_e2e import first_steps


def seed(rt) -> None:
    """The origin case: s45 and s50 not started; s38 and s21 have commits."""
    add_story(rt, "s45")
    add_story(rt, "s38", "design", commit="a")
    add_story(rt, "s21", "design", commit="b")
    add_story(rt, "s50")
    rt.state.order = ["s45", "s38", "s21", "s50"]


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


def test_started_stories_run_before_not_started_ones(make_runtime) -> None:
    rt = build(make_runtime, Script(), steps=["design", "review"])
    seed(rt)
    drive(rt)
    assert first_steps(rt)[:2] == ["s38", "s21"]
    assert all(s.status is StoryStatus.DONE for s in rt.state.stories.values())


def test_a_held_started_story_does_not_stop_a_new_one(make_runtime) -> None:
    rt = build(make_runtime, Script(), steps=["design", "review"])
    seed(rt)
    for sid in ("s38", "s21"):
        rt.state.stories[sid].hold = "quarantine"
    drive(rt)
    assert first_steps(rt)[0] == "s45"


def test_pull_ahead_is_refused_without_a_reason_and_recorded_with_one(make_runtime) -> None:
    rt = build(make_runtime, Script(), steps=["design", "review"])
    seed(rt)
    tools = Tools(rt)
    refused = call(tools.move_story({"story": "s45", "position": 1}))
    assert refused["status"] == "refused" and rt.state.pulled == []
    ok = call(tools.move_story({"story": "s45", "position": 1, "reason": "hotfix"}))
    assert ok["status"] == "ordered" and rt.state.pulled == ["s45"]
    kinds = [e for e in rt.events.events() if e.kind == "priority"]
    assert len(kinds) == 1 and kinds[0].data["reason"] == "hotfix"
    drive(rt)
    assert first_steps(rt)[0] == "s45"


def test_snapshot_positions_follow_the_new_ranking(make_runtime) -> None:
    rt = build(make_runtime, Script(), steps=["design", "review"])
    seed(rt)
    state.save(rt.config.run_dir, rt.state)
    snap = json.loads(json.dumps(snapshot.build(rt.config, rt.book)))
    positions = {s["id"]: s["position"] for s in snap["stories"]}
    assert positions["s38"] < positions["s21"] < positions["s45"] < positions["s50"]

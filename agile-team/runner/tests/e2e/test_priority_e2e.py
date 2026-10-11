"""s40 end to end: the PO sets the order, the router runs it, the snapshot shows it."""

from __future__ import annotations

import asyncio
import json

from agile_team.dashboard import snapshot
from agile_team.gates import StoryStatus
from agile_team.po_tools import Tools

from ..pipeline_helpers import Script, add_story, build, drive


def first_steps(rt) -> list[str]:
    """Story ids in the order their first step started."""
    seen: list[str] = []
    for e in rt.events.events():
        if e.kind == "step-start" and e.story not in seen:
            seen.append(e.story)
    return seen


async def set_order(rt) -> None:
    out = await Tools(rt).prioritise({"stories": ["s3", "s1"], "reason": "gate fixes"})
    assert "ordered" in out["content"][0]["text"]


def test_pipeline_runs_stories_in_the_order_the_po_set(make_runtime) -> None:
    script = Script(po=[set_order])
    rt = build(make_runtime, script, steps=["design", "review"])
    for sid in ("s1", "s2", "s3"):
        add_story(rt, sid)
    drive(rt)
    assert first_steps(rt) == ["s3", "s1", "s2"]
    assert all(s.status is StoryStatus.DONE for s in rt.state.stories.values())
    kinds = [e.kind for e in rt.events.events()]
    assert kinds.count("priority") == 1


def test_a_held_story_is_skipped_but_keeps_its_place_on_the_board(make_runtime) -> None:
    script = Script(po=[set_order])
    rt = build(make_runtime, script, steps=["design", "review"])
    for sid in ("s1", "s2", "s3"):
        add_story(rt, sid)
    rt.state.stories["s3"].hold = "questions"
    drive(rt)
    assert first_steps(rt)[0] == "s1"
    assert rt.state.order[:2] == ["s3", "s1"]
    assert rt.state.stories["s3"].status is not StoryStatus.DONE


def test_snapshot_carries_the_order_and_positions(make_runtime) -> None:
    rt = build(make_runtime, Script(), steps=["design", "review"])
    for sid in ("s1", "s2", "s3"):
        add_story(rt, sid)
    asyncio.run(set_order(rt))
    snap = json.loads(json.dumps(snapshot.build(rt.config, rt.book)))
    assert snap["run"]["order"] == ["s3", "s1", "s2"]
    positions = {s["id"]: s["position"] for s in snap["stories"]}
    assert positions == {"s3": 1, "s1": 2, "s2": 3}
    assert [s["id"] for s in snap["stories"]] == ["s3", "s1", "s2"]
    assert any(e["kind"] == "priority" for e in snap["events"])

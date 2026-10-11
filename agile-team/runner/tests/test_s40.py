"""s40: PO tools prioritise / move_story / start_sprint order, and routing by the order."""

from __future__ import annotations

import asyncio
import json

import pytest
from agile_team import po_tools
from agile_team.gates import StoryStatus
from agile_team.po_tools import Tools
from agile_team.relay import Note
from agile_team.router import Router

from .pipeline_helpers import add_story


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


def opened(make_runtime, *ids: str) -> Tools:
    t = Tools(make_runtime())
    for sid in ids:
        call(t.open_story({"id": sid, "title": sid}))
    return t


def priority_events(t: Tools) -> list:
    return [e for e in t.runtime.events.events() if e.kind == "priority"]


def test_prioritise_sets_full_queue_and_emits_one_event(make_runtime) -> None:
    t = opened(make_runtime, "s1", "s2", "s3")
    out = call(t.prioritise({"stories": ["s3", "s3", "s2"], "reason": "gate fixes"}))
    assert out == {"status": "ordered", "order": ["s3", "s2", "s1"]}
    assert t.runtime.state.order == ["s3", "s2", "s1"]
    saved = json.loads((t.runtime.config.run_dir / "state.json").read_text())
    assert saved["order"] == ["s3", "s2", "s1"]
    [ev] = priority_events(t)
    assert (ev.role, ev.story) == ("product-owner", None)
    assert ev.data["change"] == "set" and ev.data["reason"] == "gate fixes"
    assert ev.data["order"] == ["s3", "s2", "s1"]
    assert ev.data["moves"] == [
        {"story": "s3", "from": 3, "to": 1},
        {"story": "s1", "from": 1, "to": 3},
    ]


@pytest.mark.parametrize("stories", [[], ["nope"], ["s1", "nope"], ["s9"]])
def test_prioritise_refusals_change_nothing(make_runtime, stories) -> None:
    t = opened(make_runtime, "s1")
    t.runtime.state.stories["s9"] = type(t.runtime.state.stories["s1"])(
        "s9", "x", "design", status=StoryStatus.DONE
    )
    before = len(t.runtime.events.events())
    out = call(t.prioritise({"stories": stories}))
    assert out["status"] == "refused"
    assert t.runtime.state.order == [] and len(t.runtime.events.events()) == before


def test_move_story_moves_and_reports(make_runtime) -> None:
    t = opened(make_runtime, "s1", "s2", "s3")
    call(t.prioritise({"stories": ["s1", "s2", "s3"]}))
    out = call(t.move_story({"story": "s3", "position": 1, "reason": "urgent"}))
    assert out["order"] == ["s3", "s1", "s2"] == t.runtime.state.order
    ev = priority_events(t)[-1]
    assert ev.story == "s3" and ev.data["change"] == "move" and ev.data["reason"] == "urgent"
    assert {"story": "s3", "from": 3, "to": 1} in ev.data["moves"]


@pytest.mark.parametrize("args", [
    {"story": "zz", "position": 1},
    {"story": "s1", "position": 0},
    {"story": "s1", "position": 3},
    {"story": "s1", "position": "1"},
    {"story": "s1"},
])  # fmt: skip
def test_move_story_refusals_change_nothing(make_runtime, args) -> None:
    t = opened(make_runtime, "s1", "s2")
    before = len(t.runtime.events.events())
    assert call(t.move_story(args))["status"] == "refused"
    assert t.runtime.state.order == [] and len(t.runtime.events.events()) == before


def test_start_sprint_list_order_is_priority(make_runtime) -> None:
    t = opened(make_runtime, "s1", "s2", "s3")
    out = call(t.start_sprint({"goal": "G", "stories": ["s3", "s1"]}))
    assert out["order"] == ["s3", "s1", "s2"]
    kinds = [e.kind for e in t.runtime.events.events()]
    assert kinds[-2:] == ["sprint-start", "priority"]
    assert priority_events(t)[0].data["change"] == "sprint"


def test_story_status_in_ranking_order_with_order(make_runtime) -> None:
    t = opened(make_runtime, "s1", "s2", "s10")
    call(t.prioritise({"stories": ["s10"]}))
    status = call(t.story_status({}))
    assert list(status["stories"]) == ["s10", "s1", "s2"]
    assert status["order"] == ["s10", "s1", "s2"]


def test_schemas_and_tool_names() -> None:
    assert {"prioritise", "move_story"} <= set(po_tools.SCHEMAS)
    names = po_tools.tool_names()
    assert any(n.endswith("__prioritise") for n in names)
    assert any(n.endswith("__move_story") for n in names)
    assert "priority" in po_tools.SCHEMAS["start_sprint"][0]


# ----- routing ----------------------------------------------------------------


def test_router_follows_the_order_not_creation(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1")
    add_story(rt, "s2")
    add_story(rt, "s3")
    rt.state.order = ["s3", "s2"]
    assert Router(rt).next_work().story.id == "s3"


def test_router_prefers_in_progress_when_unlisted(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s9")
    add_story(rt, "s29", "tests")
    assert Router(rt).next_work().story.id == "s29"


def test_explicit_order_beats_in_progress(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s9")
    add_story(rt, "s29", "tests")
    rt.state.order = ["s9"]
    assert Router(rt).next_work().story.id == "s9"


def test_held_story_is_skipped_and_keeps_its_place(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1")
    add_story(rt, "s2")
    rt.state.order = ["s1", "s2"]
    rt.state.stories["s1"].hold = "questions"
    assert Router(rt).next_work().story.id == "s2"
    rt.state.stories["s1"].hold = None
    assert Router(rt).next_work().story.id == "s1"
    assert rt.state.order == ["s1", "s2"]


def test_question_blocked_and_needs_manager_are_skipped(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1")
    add_story(rt, "s2", status=StoryStatus.NEEDS_MANAGER)
    add_story(rt, "s3")
    add_story(rt, "s4")
    rt.state.order = ["s1", "s2", "s3", "s4"]
    rt.relay.post(Note("question", "?", ["s1"]))
    assert Router(rt).next_work().story.id == "s3"


def test_repeat_work_picks_by_ranking(make_runtime) -> None:
    rt = make_runtime()
    for sid in ("s1", "s2"):
        add_story(rt, sid, status=StoryStatus.NEEDS_MANAGER, repeated="same")
    rt.state.order = ["s2"]
    work = Router(rt).next_work()
    assert (work.role, work.story.id) == ("manager", "s2")


def test_page_source_shows_position_waits_and_priority_events() -> None:
    from agile_team.dashboard import snapshot

    html = (snapshot.Path(snapshot.__file__).parent / "index.html").read_text()
    for needle in ("WAIT_TONE", "priority:", "#${s.position}", "waits on:"):
        assert needle in html
    assert "view.stories.sort(" not in html and "view.stories.slice().sort(" not in html

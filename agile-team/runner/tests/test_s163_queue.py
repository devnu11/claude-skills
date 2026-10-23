"""s163 AC1 (Q1 to Q8): the landing queue, the order_landings tool and a revert's turn."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from agile_team.events import EventKind
from agile_team.gates import StoryState
from agile_team.landing_queue import LandingQueue, Placement
from agile_team.po_tools import Tools
from agile_team.story_branches import Landed

from .fake_system import Done

SHORT = " 1 file changed, {a} insertions(+), {d} deletions(-)\n"


def story(sid: str, step: str = "land", **kw) -> StoryState:
    return StoryState(sid, "T", step, sprint=1, branch=f"team/story-{sid}", base_sha="b" * 40, **kw)


def queue(make_runtime, *stories: StoryState) -> tuple[LandingQueue, object]:
    rt = make_runtime()
    rt.state.sprint = 1
    rt.state.stories = {s.id: s for s in stories}
    rt.landings = LandingQueue(rt)
    return rt.landings, rt


def size(fake, branch: str, lines: int) -> None:
    fake.reply(
        ("diff", "--shortstat", f"{'b' * 40}..{branch}"), Done(0, SHORT.format(a=lines, d=0))
    )


def sized(fake, **lines: int) -> None:
    for sid, n in lines.items():
        size(fake, f"team/story-{sid}", n)


def queue_revert(rt, sid: str) -> None:
    rt.state.stories[sid].landed = Landed("m" * 40, "m" * 40)
    rt.revert_queue.append(SimpleNamespace(story_id=sid, reason="r"))


# ---------- order ----------


def test_stories_at_land_wait_smallest_first_q2(make_runtime, fake) -> None:
    q, _ = queue(make_runtime, story("s1"), story("s2"), story("s3"))
    sized(fake, s1=30, s2=5, s3=5)
    assert q.order == ["s2", "s3", "s1"]


def test_a_story_not_at_land_or_with_a_hold_does_not_wait_q1(make_runtime, fake) -> None:
    q, _ = queue(make_runtime, story("s1", "implement"), story("s2", hold="x"), story("s3"))
    assert q.order == ["s3"]


def test_a_story_with_a_rebase_pending_does_not_wait_q1(make_runtime, fake) -> None:
    held = story("s1")
    held.rebase = object()
    q, _ = queue(make_runtime, held, story("s2"))
    assert q.order == ["s2"]


def test_the_pos_order_goes_first_q2(make_runtime, fake) -> None:
    q, rt = queue(make_runtime, story("s1"), story("s2"))
    sized(fake, s1=30, s2=5)
    rt.state.landing_order = ["s1"]
    assert q.order == ["s1", "s2"]


def test_the_story_landing_now_is_not_waiting_q1(make_runtime, fake) -> None:
    q, _ = queue(make_runtime, story("s1"), story("s2"))
    q.begin("s1")
    assert [c.story for c in q.candidates] == ["s2"]


# ---------- pick_next ----------


def test_next_up_is_the_first_waiting_q1(make_runtime, fake) -> None:
    q, _ = queue(make_runtime, story("s1"), story("s2"))
    sized(fake, s1=9, s2=1)
    assert q.pick_next() == "s2"


def test_next_up_of_an_empty_queue_is_none_q1(make_runtime, fake) -> None:
    q, _ = queue(make_runtime)
    assert q.pick_next() is None


def test_next_up_is_the_story_landing_while_it_is_live_q5(make_runtime, fake) -> None:
    q, _ = queue(make_runtime, story("s1"), story("s2"))
    q.begin("s1")
    assert q.pick_next() == "s1"


def test_next_up_clears_a_landing_that_left_land_q5(make_runtime, fake) -> None:
    q, rt = queue(make_runtime, story("s1", "implement"), story("s2"))
    q.begin("s1")
    assert q.pick_next() == "s2" and rt.state.landing == ""


def test_next_up_clears_a_landing_of_an_unknown_story_q5(make_runtime, fake) -> None:
    q, rt = queue(make_runtime)
    rt.state.landing = "s9"
    assert q.pick_next() is None and rt.state.landing == ""


def test_a_story_with_a_queued_revert_is_live_q5(make_runtime, fake) -> None:
    q, rt = queue(make_runtime, story("s1", "done"))
    queue_revert(rt, "s1")
    rt.state.landing = "s1"
    assert q.pick_next() == "s1"


def test_a_running_revert_holds_the_slot_d1(make_runtime, fake) -> None:
    q, rt = queue(make_runtime, story("s1", "done"), story("s2"))
    q.begin_revert("s1")
    assert q.pick_next() == "s1" and q.reverting == "s1" and rt.state.landing == "s1"


# ---------- finish ----------


def test_finish_frees_the_slot_and_forgets_the_place_and_size_q4(make_runtime, fake) -> None:
    q, rt = queue(make_runtime, story("s1"), story("s2"))
    sized(fake, s1=3, s2=4)
    q.measure("s1")
    q.measure("s2")
    q.begin_revert("s1")
    rt.state.landing_order = ["s1", "s2"]
    q.finish("s1")
    assert q.reverting == "" and rt.state.landing == ""
    assert rt.state.landing_order == ["s2"]
    assert list(q.sizes) == [("s2", "team/story-s2", "b" * 40)]


def test_finish_of_another_story_keeps_the_slot_q4(make_runtime, fake) -> None:
    q, rt = queue(make_runtime, story("s1"))
    q.begin("s1")
    q.finish("s2")
    assert rt.state.landing == "s1"


# ---------- reverts take their turn ----------


def test_a_landing_revert_waits_in_the_same_queue_ac1(make_runtime, fake) -> None:
    q, rt = queue(make_runtime, story("s1"), story("s2", "done"))
    queue_revert(rt, "s2")
    fake.reply(("diff", "--shortstat", f"{'m' * 40}^1"), Done(0, SHORT.format(a=1, d=1)))
    sized(fake, s1=50)
    assert q.order == ["s2", "s1"]


def test_a_revert_is_sized_by_its_merge_ac1(make_runtime, fake) -> None:
    q, rt = queue(make_runtime, story("s2", "done"))
    queue_revert(rt, "s2")
    fake.reply(("diff", "--shortstat", f"{'m' * 40}^1"), Done(0, SHORT.format(a=7, d=3)))
    assert q.measure("s2") == 10


def test_a_failed_diff_sizes_a_story_zero_q7(make_runtime, fake) -> None:
    q, _ = queue(make_runtime, story("s1"))
    fake.reply(("diff", "--shortstat"), Done(1, "fatal"))
    assert q.measure("s1") == 0


def test_an_unknown_story_is_size_zero_q7(make_runtime, fake) -> None:
    q, _ = queue(make_runtime)
    assert q.measure("s9") == 0


def test_a_size_is_cached_per_branch_and_base_q7(make_runtime, fake) -> None:
    q, _ = queue(make_runtime, story("s1"))
    sized(fake, s1=4)
    q.measure("s1")
    q.measure("s1")
    diffs = [c for c in fake.commands if "--shortstat" in c.argv]
    assert len(diffs) == 1


# ---------- place ----------


def test_place_refuses_an_empty_list_q3(make_runtime, fake) -> None:
    q, _ = queue(make_runtime, story("s1"))
    assert q.place(Placement([], "r"))["status"] == "refused"


def test_place_refuses_the_story_landing_now_q3(make_runtime, fake) -> None:
    q, _ = queue(make_runtime, story("s1"), story("s2"))
    q.begin("s1")
    out = q.place(Placement(["s1"], "r"))
    assert out["status"] == "refused" and "landing now" in out["reason"]


def test_place_refuses_a_story_not_at_land_q3(make_runtime, fake) -> None:
    q, _ = queue(make_runtime, story("s1", "implement"), story("s2"))
    out = q.place(Placement(["s1"], "r"))
    assert out["status"] == "refused" and "s1 is not waiting" in out["reason"]
    assert "s2" in out["reason"]


def test_place_refuses_a_departure_from_smallest_first_without_a_reason_q3(
    make_runtime, fake
) -> None:
    q, rt = queue(make_runtime, story("s1"), story("s2"))
    sized(fake, s1=30, s2=5)
    out = q.place(Placement(["s1"], "  "))
    assert out["status"] == "refused" and "s2, s1" in out["reason"]
    assert rt.state.landing_order == []


def test_place_accepts_smallest_first_without_a_reason_q3(make_runtime, fake) -> None:
    q, rt = queue(make_runtime, story("s1"), story("s2"))
    sized(fake, s1=30, s2=5)
    out = q.place(Placement(["s2"], ""))
    assert out["status"] == "ordered" and out["order"] == ["s2", "s1"]
    assert rt.state.landing_order == ["s2"]


def test_place_accepts_a_departure_with_a_reason_and_logs_it_q6(make_runtime, fake) -> None:
    q, rt = queue(make_runtime, story("s1"), story("s2"))
    sized(fake, s1=30, s2=5)
    out = q.place(Placement(["s1", "s1"], "s1 first: s2 builds on it"))
    assert out["order"] == ["s1", "s2"] and out["sizes"] == {"s1": 30, "s2": 5}
    [event] = [e for e in rt.events.events() if e.kind == EventKind.LANDING_ORDER]
    assert event.data["reason"] == "s1 first: s2 builds on it"
    assert event.data["placed"] == ["s1"] and event.data["smallest"] == ["s2", "s1"]
    assert event.data["order"] == ["s1", "s2"]


# ---------- the PO tool ----------


def test_the_tool_places_the_order_q3(make_runtime, fake) -> None:
    _, rt = queue(make_runtime, story("s1"), story("s2"))
    sized(fake, s1=30, s2=5)
    out = asyncio.run(Tools(rt).set_landing_order({"stories": ["s1"], "reason": "why"}))
    assert '"ordered"' in out["content"][0]["text"]


def test_the_tool_builds_a_queue_when_the_runtime_has_none_q3(make_runtime, fake) -> None:
    rt = make_runtime()
    out = asyncio.run(Tools(rt).set_landing_order({"stories": "s1"}))
    assert '"refused"' in out["content"][0]["text"]

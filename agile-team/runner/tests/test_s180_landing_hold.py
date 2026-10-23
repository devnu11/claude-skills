"""s180 C6 (round 2), C2.4: a kept landing merge holds new forks; the hold is saved."""

from __future__ import annotations

import json

from agile_team import landing, router
from agile_team.boundary import StackEntry
from agile_team.dispatch import RunFlags
from agile_team.gates import StoryState
from agile_team.router import Router
from agile_team.state import RunState
from agile_team.story_branches import Landed, StoryRebase

from .fake_system import Done
from .test_s159_landing import HEAD, MERGE, OLD, SPRINT, LandPrs, checks, land, setup
from .test_s159_scheduler import setup as sched_setup
from .test_s163_landing_moves import dropped
from .test_s180_landing_carry import BASE, carryable

MOVED = "m" * 40


def ids(rt) -> list[str]:
    """The ids of the stories the router offers work for."""
    return [w.story.id for w in Router(rt).list_works(frozenset()) if w.story]


def kept(sid: str, base: str, pushed: str = MERGE, **kw) -> StoryState:
    """A story at land with a kept, pushed merge whose first parent is ``base``."""
    landed = Landed(MERGE, pushed=pushed, base=base)
    return StoryState(sid, "T", "land", sprint=1, branch=f"b-{sid}", landed=landed, **kw)


def fresh(sid: str = "s2", **kw) -> StoryState:
    """A story at implement with no branch yet: it would fork on the sprint head."""
    return StoryState(sid, "T", "implement", sprint=1, **kw)


def runtime(make_runtime, head: str, *stories: StoryState):
    rt = sched_setup(make_runtime, *stories)
    rt.state.upstream.stack = [StackEntry(1, SPRINT, OLD, OLD, head=head, pushed=head)]
    return rt


# ---------- C6.1: the base is saved with the pushed merge ----------


def hold_on_ci(make_runtime, fake, monkeypatch):
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake, prs=LandPrs(sha_list=[]))
    rt.config.gates.ci_timeout_s = 0
    return rt, story, entry


def test_push_landing_saves_the_merges_first_parent_c6(make_runtime, fake, monkeypatch) -> None:
    rt, story, _ = hold_on_ci(make_runtime, fake, monkeypatch)
    land(rt, story)
    assert story.landed == Landed(MERGE, pushed=MERGE, base=HEAD)


def test_a_resume_fills_an_empty_base_and_saves_c6(make_runtime, fake, monkeypatch) -> None:
    rt, story, _ = hold_on_ci(make_runtime, fake, monkeypatch)
    story.landed = Landed(MERGE, pushed=MERGE)
    carryable(fake, rt)
    land(rt, story)
    assert story.landed is not None and story.landed.base == BASE
    saved = RunState.from_json(rt.state.to_json())
    assert saved.stories["s1"].landed.base == BASE


def test_a_resume_keeps_a_base_that_is_set_c6(make_runtime, fake, monkeypatch) -> None:
    rt, story, _ = hold_on_ci(make_runtime, fake, monkeypatch)
    story.landed = Landed(MERGE, pushed=MERGE, base=HEAD)
    land(rt, story)
    assert story.landed.base == HEAD


def test_a_saved_base_round_trips_and_an_old_record_loads_empty_c6() -> None:
    state = RunState(stories={"s1": kept("s1", BASE)})
    assert RunState.from_json(state.to_json()).stories["s1"].landed.base == BASE
    loaded = RunState.from_json(_without_base(state)).stories["s1"].landed
    assert loaded.base == "" and loaded.pushed == MERGE


def _without_base(state: RunState) -> str:
    data = json.loads(state.to_json())
    del data["stories"]["s1"]["landed"]["base"]
    return json.dumps(data)


# ---------- C6: the hold window (F1) ----------


def test_a_ci_hold_keeps_the_pushed_merge_and_its_base_c6(make_runtime, fake, monkeypatch) -> None:
    rt, story, _ = hold_on_ci(make_runtime, fake, monkeypatch)
    land(rt, story)
    assert story.landed.pushed == MERGE and story.landed.base == HEAD
    assert rt.flags.landing_base == ""


def test_a_story_with_no_branch_waits_while_a_ci_held_landing_sits_below_the_head_c6(
    make_runtime, fake, monkeypatch
) -> None:
    rt, story, entry = hold_on_ci(make_runtime, fake, monkeypatch)
    land(rt, story)
    entry.head = MOVED
    rt.state.stories["s2"] = fresh()
    assert rt.flags.landing_base == "" and "s2" not in ids(rt)


def test_the_hold_holds_after_a_restart_c6(make_runtime) -> None:
    rt = runtime(make_runtime, MOVED, kept("s1", BASE), fresh())
    assert rt.flags == RunFlags() and "s2" not in ids(rt)


def test_the_hold_ends_when_the_head_comes_back_to_the_base_c6(make_runtime) -> None:
    rt = runtime(make_runtime, BASE, kept("s1", BASE), fresh())
    assert "s2" in ids(rt)


def test_the_hold_ends_when_the_landing_leaves_land_c6(make_runtime) -> None:
    gone = kept("s1", BASE)
    gone.step = "review"
    rt = runtime(make_runtime, MOVED, gone, fresh())
    assert "s2" in ids(rt)


def test_the_hold_ends_when_the_landing_is_given_up_c6(make_runtime) -> None:
    given_up = kept("s1", BASE)
    given_up.landed = None
    rt = runtime(make_runtime, MOVED, given_up, fresh())
    assert "s2" in ids(rt)


def test_a_story_with_a_branch_is_offered_under_the_hold_c6(make_runtime) -> None:
    rt = runtime(make_runtime, MOVED, kept("s1", BASE), fresh(branch="b-s2"))
    assert "s2" in ids(rt)


def test_a_story_with_a_branch_and_a_worktree_is_offered_c6(make_runtime) -> None:
    other = fresh(branch="b-s2", worktree_head="w" * 40)
    assert "s2" in ids(runtime(make_runtime, MOVED, kept("s1", BASE), other))


def test_a_story_at_land_is_offered_under_the_hold_c6(make_runtime) -> None:
    rt = runtime(make_runtime, MOVED, kept("s1", BASE), kept("s2", BASE))
    assert {"s1", "s2"} <= set(ids(rt))


def test_a_record_with_no_base_holds_nothing_c6(make_runtime) -> None:
    rt = runtime(make_runtime, MOVED, kept("s1", ""), fresh())
    assert "s2" in ids(rt)


def test_an_unpushed_record_holds_nothing_c6(make_runtime) -> None:
    rt = runtime(make_runtime, MOVED, kept("s1", BASE, pushed=""), fresh())
    assert "s2" in ids(rt)


def test_a_landed_story_past_land_holds_nothing_c6(make_runtime) -> None:
    done = kept("s1", BASE)
    done.step = "review"
    rt = runtime(make_runtime, MOVED, done, fresh())
    assert Router(rt)._held_landings == []


def test_the_in_flight_landing_holds_through_its_flag_c6(make_runtime) -> None:
    rt = runtime(make_runtime, MOVED, fresh())
    rt.state.landing = "s9"
    rt.flags.landing_base = BASE
    assert Router(rt)._held_landings == ["s9"] and "s2" not in ids(rt)


def test_only_the_landing_below_the_head_is_named_c6(make_runtime) -> None:
    below, level = kept("s1", BASE), kept("s3", MOVED)
    rt = runtime(make_runtime, MOVED, below, level, fresh())
    assert Router(rt)._held_landings == ["s1"] and "s2" not in ids(rt)


# ---------- C6: the hand-over names the hold ----------


def test_a_held_story_reads_the_landing_hold_in_the_stall_lines_c6(make_runtime) -> None:
    held, free = fresh(), kept("s1", MOVED)
    rt = runtime(make_runtime, MOVED, kept("s3", BASE), held, free)
    lines = Router(rt)._list_stall_lines([held, free])
    assert lines[0] == f"s2 at implement: {router.LANDING_HOLD.format(ids='s3')}"
    assert router.LANDING_HOLD not in lines[1]


def test_an_unheld_story_keeps_its_own_why_c6(make_runtime) -> None:
    rt = runtime(make_runtime, MOVED, fresh())
    [line] = Router(rt)._list_stall_lines([rt.state.stories["s2"]])
    assert router.LANDING_HOLD.split("{")[0] not in line


def test_the_stuck_hand_over_gives_the_landing_hold_c6(make_runtime) -> None:
    held = fresh()
    rt = runtime(make_runtime, MOVED, kept("s3", BASE), held)
    found = Router(rt)._hand_over_stuck([held])
    assert any(router.LANDING_HOLD.format(ids="s3") in line for line in found.lines)


# ---------- C2.4 at the lander level ----------


def test_a_story_forked_on_a_moved_commit_refuses_the_carry_c2(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    rt.state.stories["s2"] = StoryState("s2", "T", "implement", sprint=1, base_sha="o2")
    carryable(fake, rt)
    land(rt, story)
    first = dropped(rt)[0]
    assert first.data["not_carried"] == landing.carry.FORKED.format(story="s2", sha="o2")
    assert not [c for c in fake.commands if f"{MERGE}:refs/heads/{SPRINT}" in c.argv]


def test_a_queued_rebase_onto_a_moved_commit_refuses_the_carry_c2(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    other = StoryState("s2", "T", "implement", sprint=1)
    other.rebase = StoryRebase("o1", OLD, OLD, "b-s2", [], "developer")
    rt.state.stories["s2"] = other
    carryable(fake, rt)
    fake.reply(("merge-base", "--is-ancestor"), Done(0))
    land(rt, story)
    first = dropped(rt)[0]
    assert first.data["not_carried"] == landing.carry.FORKED.format(story="s2", sha="o1")

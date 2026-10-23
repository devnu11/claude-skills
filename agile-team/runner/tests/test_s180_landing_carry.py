"""s180 C4 to C7, D1, D2: the lander carries the runner's own commits over a green landing."""

from __future__ import annotations

import asyncio

import pytest
from agile_team import handover
from agile_team.boundary import StackEntry
from agile_team.events import EventKind
from agile_team.gates import StoryState
from agile_team.handover import Scope, Trigger
from agile_team.router import Router
from agile_team.story_branches import Landed
from agile_team.upstream import UpstreamError

from .fake_system import Done
from .s29_helpers import FakePrs
from .test_s159_landing import (
    HEAD,
    MERGE,
    OLD,
    SPRINT,
    checks,
    ff,
    issued,
    land,
    landing,
    setup,
)
from .test_s159_scheduler import setup as sched_setup
from .test_s163_landing_moves import dropped, lander, probed, sprint_pushes

BASE, TIP = "b" * 40, "t" * 40
SPAN = f"{BASE}..{HEAD}"
AFTER = f"{MERGE}..HEAD"
LOG = "abc1234 chore: file s2\nfed9876 chore(team): devops step\n"


def carryable(fake, rt, entry=None) -> list:
    """The merge's first parent is BASE; the span has two plain commits; the carry works."""
    fake.reply(("rev-parse", f"{MERGE}^1"), Done(0, BASE + "\n"))
    fake.reply(("rev-list", SPAN), Done(0, "o1\no2\n"))
    fake.reply(("rev-list", "--reverse", AFTER), Done(0, "n1\nn2\n"))
    fake.reply(("rev-parse", "HEAD"), Done(0, MERGE + "\n"), Done(0, TIP + "\n"))
    fake.reply(("log", "--reverse"), Done(0, LOG))
    resets: list = []

    def reset(old: str, sha: str) -> None:
        resets.append((old, sha))

    rt.upstream.reset_team_branch = reset
    return resets


def event_of(rt, kind: EventKind):
    [event] = [e for e in rt.events.events() if e.kind == kind]
    return event


# ---------- C4: green with a carry ----------


def test_green_with_a_carryable_move_pushes_the_merge_and_resets_to_the_tip_c4(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake)
    resets = carryable(fake, rt)
    out = land(rt, story)
    assert len(sprint_pushes(fake)) == 1
    assert resets == [(HEAD, TIP)] and ff(fake) == []
    assert entry.pushed == MERGE and entry.head == TIP
    assert out["gate"]["verdict"] == "pass" and story.landed.merge == MERGE
    assert dropped(rt) == [] and rt.halted_by is None


def test_story_landed_records_the_carried_pairs_c7(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    carryable(fake, rt)
    land(rt, story)
    event = event_of(rt, EventKind.STORY_LANDED)
    assert event.data["merge"] == MERGE and event.data["carried"] == {"o1": "n1", "o2": "n2"}


def test_the_run_state_is_remapped_to_the_copies_c7(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    other = StoryState("s2", "Two", "design", sprint=1)
    other.file_commits = ["o1", "zzz"]
    rt.state.stories["s2"] = other
    carryable(fake, rt)
    land(rt, story)
    assert other.file_commits == ["n1", "zzz"]


def test_the_carry_is_made_before_the_sprint_push_c4(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    carryable(fake, rt)
    land(rt, story)
    names = [a for a in (tuple(c.argv) for c in fake.commands)]
    pick = next(i for i, a in enumerate(names) if "cherry-pick" in a)
    push = next(i for i, a in enumerate(names) if f"{MERGE}:refs/heads/{SPRINT}" in a)
    assert pick < push


def test_green_with_nothing_moved_fast_forwards_and_carries_nothing_c4(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake)
    land(rt, story)
    assert len(ff(fake)) == 1 and issued(fake, "cherry-pick") == []
    assert entry.head == entry.pushed == MERGE
    assert event_of(rt, EventKind.STORY_LANDED).data["carried"] == {}


def test_nothing_moved_keeps_the_move_and_record_under_the_lock_c4(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    probe = probed(rt, monkeypatch)
    asyncio.run(landing.Lander(rt, probe.lock).land(story))
    assert probe.seen["advance_to"] == [True] and probe.seen["record_checkout"] == [True]


def test_a_refused_move_drops_the_merge_and_names_why_c4(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    fake.reply(("rev-parse", f"{MERGE}^1"), Done(0, BASE + "\n"))
    fake.reply(("log", "--reverse"), Done(0, LOG))
    land(rt, story)
    first = dropped(rt)[0]
    assert first.data["why"] == "sprint head moved"
    assert first.data["not_carried"] == landing.carry.NOT_ABOVE
    assert issued(fake, "cherry-pick") == [] and sprint_pushes(fake) == []


def test_a_carry_that_stops_on_a_conflict_pushes_nothing_and_drops_c4(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    carryable(fake, rt)
    fake.reply(("cherry-pick", "--allow-empty"), Done(1, "conflict"))
    fake.reply(("diff", "--name-only", "--diff-filter=U"), Done(0, "a.py\n"))
    land(rt, story)
    first = dropped(rt)[0]
    assert first.data["not_carried"] == landing.carry.STOPPED.format(files="a.py")
    assert sprint_pushes(fake) == []
    names = [tuple(c.argv) for c in fake.commands]
    abort = next(i for i, a in enumerate(names) if "--abort" in a and "cherry-pick" in a)
    assert any("worktree" in a and "remove" in a for a in names[abort:])


def test_a_failed_reset_halts_as_checkout_drift_after_the_push_c4(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake)
    carryable(fake, rt)

    def refuse(old: str, sha: str) -> None:
        raise UpstreamError("the team branch moved")

    rt.upstream.reset_team_branch = refuse
    land(rt, story)
    assert rt.halted_by is not None and entry.pushed == MERGE


def test_local_mode_carries_with_a_reset_and_no_push_c4(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake, prs=FakePrs(reason="no gh"))
    resets = carryable(fake, rt)
    out = land(rt, story)
    assert issued(fake, "push") == [] and resets == [(HEAD, TIP)] and ff(fake) == []
    assert entry.head == TIP and out["land"]["ci"] == "none"
    assert event_of(rt, EventKind.STORY_LANDED).data["carried"] == {"o1": "n1", "o2": "n2"}


def test_local_mode_with_a_refused_move_drops_c4(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake, prs=FakePrs(reason="no gh"))
    fake.reply(("rev-parse", f"{MERGE}^1"), Done(0, BASE + "\n"))
    land(rt, story)
    assert dropped(rt)[0].data["why"] == "sprint head moved"


# ---------- C5: resuming ----------


def test_a_resumed_landing_with_a_carryable_move_makes_no_new_merge_c5(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake)
    story.landed = Landed(MERGE, pushed=MERGE)
    carryable(fake, rt)
    land(rt, story)
    assert issued(fake, "merge", "--no-ff") == [] and dropped(rt) == []
    assert entry.pushed == MERGE and entry.head == TIP


def test_a_resumed_landing_with_a_refused_move_drops_once_and_merges_afresh_c5(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake)
    story.landed = Landed(MERGE, pushed=MERGE)
    fake.reply(
        ("rev-parse", f"{MERGE}^1"), Done(0, BASE + "\n"), Done(0, BASE + "\n"), Done(0, HEAD)
    )
    fake.reply(("log", "--reverse"), Done(0, LOG))
    out = land(rt, story)
    assert [e.data["why"] for e in dropped(rt)] == ["sprint head moved"]
    assert len(issued(fake, "merge", "--no-ff")) == 1
    assert out["land"]["dropped"] == [
        {"merge": MERGE, "why": "sprint head moved", "moved": LOG.splitlines()}
    ]
    assert entry.pushed == MERGE


def test_a_land_with_no_drop_has_no_dropped_key_d2(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    assert "dropped" not in land(rt, story).get("land", {})


# ---------- D1: a drop names what moved ----------


def test_a_drop_lists_the_moved_commits_and_why_they_were_not_carried_d1(
    make_runtime, fake
) -> None:
    rt, story, entry = setup(make_runtime, fake)
    fake.reply(("rev-parse", f"{MERGE}^1"), Done(0, BASE + "\n"))
    fake.reply(("log", "--reverse"), Done(0, LOG))
    attempt = landing.Attempt(story, entry, HEAD, merge=MERGE)
    attempt.not_carried = "because"
    asyncio.run(lander(rt).give_up(attempt, "sprint head moved"))
    data = event_of(rt, EventKind.LANDING_DROPPED).data
    assert data["moved"] == LOG.splitlines() and data["not_carried"] == "because"
    assert set(data) == {"merge", "why", "sprint_head", "moved", "not_carried"}
    assert attempt.dropped == [
        {"merge": MERGE, "why": "sprint head moved", "moved": LOG.splitlines()}
    ]
    assert attempt.not_carried == ""


# ---------- C6: no fork during a moved landing ----------


def test_the_landing_base_is_the_merges_first_parent_while_ci_runs_c6(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    seen: list[str] = []
    probe = probed(rt, monkeypatch, act=lambda: seen.append(rt.flags.landing_base))
    asyncio.run(landing.Lander(rt, probe.lock).land(story))
    assert seen == [HEAD] and rt.flags.landing_base == ""


def test_the_landing_base_is_set_on_a_resume_c6(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    story.landed = Landed(MERGE, pushed=MERGE)
    carryable(fake, rt)
    seen: list[str] = []
    probe = probed(rt, monkeypatch, act=lambda: seen.append(rt.flags.landing_base))
    asyncio.run(landing.Lander(rt, probe.lock).land(story))
    assert seen == [BASE] and rt.flags.landing_base == ""


def test_the_landing_base_is_cleared_after_a_revert_c6(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    story.landed = Landed(MERGE, pushed=MERGE)
    rt.flags.landing_base = "x" * 40
    asyncio.run(landing.Lander(rt, asyncio.Lock()).land_revert(story, "why"))
    assert rt.flags.landing_base == ""


def test_a_drop_clears_the_landing_base_c6(make_runtime, fake) -> None:
    rt, story, entry = setup(make_runtime, fake)
    rt.flags.landing_base = BASE
    attempt = landing.Attempt(story, entry, HEAD, merge=MERGE)
    asyncio.run(lander(rt).give_up(attempt, "why"))
    assert rt.flags.landing_base == ""


def held(make_runtime, base: str, **story_kw):
    s = StoryState("s1", "T", "implement", sprint=1, **story_kw)
    rt = sched_setup(make_runtime, s)
    rt.state.upstream.stack = [StackEntry(1, SPRINT, OLD, OLD, head=HEAD, pushed=HEAD)]
    rt.flags.landing_base = base
    return [w.story.id for w in Router(rt).list_works(frozenset()) if w.story]


@pytest.mark.parametrize(
    ("base", "kw", "offered"),
    [
        (BASE, {}, False),
        ("", {}, True),
        (HEAD, {}, True),
        (BASE, {"worktree_head": "w" * 40}, True),
    ],
)
def test_a_story_with_no_worktree_waits_while_a_landing_sits_below_the_head_c6(
    make_runtime, base, kw, offered
) -> None:
    assert (held(make_runtime, base, **kw) == ["s1"]) is offered


def test_a_story_at_land_is_never_held_by_a_landing_c6(make_runtime) -> None:
    s = StoryState("s1", "T", "land", sprint=1)
    rt = sched_setup(make_runtime, s)
    rt.state.upstream.stack = [StackEntry(1, SPRINT, OLD, OLD, head=HEAD, pushed=HEAD)]
    rt.flags.landing_base = BASE
    assert [w.story.id for w in Router(rt).list_works(frozenset()) if w.story] == ["s1"]


# ---------- D2: the PO hears of a drop ----------


DROP = {"merge": MERGE, "why": "sprint head moved", "moved": LOG.splitlines()}


def test_landing_dropped_is_a_story_scoped_trigger_d2() -> None:
    assert handover.SCOPES[Trigger.LANDING_DROPPED] is Scope.STORY
    assert Trigger.LANDING_DROPPED.value == "landing_dropped"


def test_a_report_with_drops_raises_landing_dropped_and_names_them_d2() -> None:
    report = {"land": {"dropped": [DROP]}}
    assert handover.triggers(report) == [Trigger.LANDING_DROPPED]
    [line] = handover.report_lines(report, "s1")
    assert MERGE[:12] in line and MERGE[:13] not in line
    assert "sprint head moved" in line and "abc1234 chore: file s2" in line
    assert "fed9876 chore(team): devops step" in line


def test_a_drop_with_no_moved_lines_says_nothing_listed_d2() -> None:
    report = {"land": {"dropped": [{**DROP, "moved": []}]}}
    [line] = handover.report_lines(report, "s1")
    assert "nothing listed" in line


def test_several_drops_are_joined_d2() -> None:
    other = {**DROP, "merge": "z" * 40}
    text = handover.format_drops([DROP, other])
    assert MERGE[:12] in text and "z" * 12 in text and "; " in text


def test_no_drops_raise_nothing_d2() -> None:
    assert handover.triggers({"land": {"dropped": []}}) == []
    assert handover.triggers({"land": {}}) == []

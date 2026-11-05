"""s180 C1 to C9: a landing carries the runner's unpushed commits instead of giving up."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from agile_team.boundary import Permission
from agile_team.events import EventKind
from agile_team.gates import StoryState
from agile_team.story_branches import Landed
from agile_team.story_rebase import ListedCommit

from .fake_system import Done
from .late import Late
from .test_s159_landing import HEAD, MERGE, SPRINT, checks, issued, land, landing, setup

lc = Late("landing_carry")
H2, TIP, NEW = "k" * 40, "t" * 40, "n" * 40
C1 = ListedCommit("1" * 40, "docs(s2): amend")


@dataclass
class Rig:
    """The runtime, story and entry of a carried landing, and the moves it makes."""

    rt: object
    story: object
    entry: object
    resets: list = field(default_factory=list)
    advanced: list = field(default_factory=list)


def events_of(rt, kind: EventKind) -> list:
    return [e for e in rt.events.events() if e.kind == kind]


def carried_setup(make_runtime, fake, monkeypatch, push=Permission.YES):
    """A landing whose merge sits on HEAD while the sprint head is H2, one commit later."""
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake, push=push)
    entry.head = H2
    story.file_commits = [C1.sha]
    fake.reply(("log", "--reverse", f"{HEAD}..{H2}"), Done(0, f"{C1.sha}\t{C1.subject}\n"))
    rig = Rig(rt, story, entry)
    monkeypatch.setattr(rt.upstream, "reset_team_branch", lambda o, n: rig.resets.append((o, n)))
    monkeypatch.setattr(rt.upstream, "advance_to", lambda sha: rig.advanced.append(sha) or True)

    def replay(self, span, commits):
        return lc.Carry(span, commits, tip=TIP, moved={C1.sha: NEW})

    monkeypatch.setattr(lc.Carrier, "carry", replay)
    return rig


def test_a_landing_with_a_commit_after_its_base_pushes_the_merge_not_the_tip_c4(
    make_runtime, fake, monkeypatch
) -> None:
    rig = carried_setup(make_runtime, fake, monkeypatch)
    rt, story, entry = rig.rt, rig.story, rig.entry
    land(rt, story)
    assert len(issued(fake, "push", f"{MERGE}:refs/heads/{SPRINT}")) == 1
    assert issued(fake, "push", f"{TIP}:refs/heads/{SPRINT}") == []
    assert entry.pushed == MERGE and events_of(rt, EventKind.LANDING_DROPPED) == []
    assert story.landed is None or story.landed.merge == MERGE


def test_the_checkout_moves_to_the_replayed_tip_by_reset_not_fast_forward_c4(
    make_runtime, fake, monkeypatch
) -> None:
    rig = carried_setup(make_runtime, fake, monkeypatch)
    land(rig.rt, rig.story)
    assert rig.resets == [(H2, TIP)] and rig.advanced == []


def test_the_story_landed_event_keeps_the_pushed_merge_c5(make_runtime, fake, monkeypatch) -> None:
    rig = carried_setup(make_runtime, fake, monkeypatch)
    rt, story = rig.rt, rig.story
    land(rt, story)
    [landed] = events_of(rt, EventKind.STORY_LANDED)
    assert landed.data["merge"] == MERGE


def test_a_carried_landing_logs_landing_carried_with_the_pairs_c5(
    make_runtime, fake, monkeypatch
) -> None:
    rig = carried_setup(make_runtime, fake, monkeypatch)
    rt, story = rig.rt, rig.story
    land(rt, story)
    [event] = events_of(rt, EventKind.LANDING_CARRIED)
    assert event.role == "runner" and event.story == "s1"
    assert event.data["merge"] == MERGE and event.data["from"] == H2 and event.data["to"] == TIP
    assert event.data["commits"] == [{"old": C1.sha, "new": NEW, "subject": C1.subject}]


def test_the_carried_shas_are_remapped_in_the_state_c5(make_runtime, fake, monkeypatch) -> None:
    rig = carried_setup(make_runtime, fake, monkeypatch)
    rt, story = rig.rt, rig.story
    land(rt, story)
    assert story.file_commits == [NEW]


def test_nothing_carried_is_todays_path_with_no_carry_event_c1(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    land(rt, story)
    assert events_of(rt, EventKind.LANDING_CARRIED) == []
    assert events_of(rt, EventKind.LANDING_DROPPED) == []
    assert issued(fake, "log", "--reverse", f"{HEAD}..{HEAD}") == []


def test_a_refused_carry_pushes_nothing_and_names_the_commits_c6(
    make_runtime, fake, monkeypatch
) -> None:
    rig = carried_setup(make_runtime, fake, monkeypatch)
    rt, story = rig.rt, rig.story
    fake.reply(("merge-base", "--is-ancestor"), Done(1), Done(0))
    report = land(rt, story)
    [drop] = events_of(rt, EventKind.LANDING_DROPPED)
    assert drop.data["why"] == "sprint head moved" and drop.data["merge"] == MERGE
    assert drop.data["moved_by"] == ["1111111 docs(s2): amend"]
    assert drop.data["refusal"] == lc.CARRY_OFF_HEAD.format(head=H2[:12], base=HEAD[:12])
    assert drop.data["sprint_head"] == H2
    assert report["land"]["dropped"] == [
        {
            "merge": MERGE,
            "why": "sprint head moved",
            "moved_by": ["1111111 docs(s2): amend"],
            "refusal": drop.data["refusal"],
        }
    ]


def test_a_refused_carry_gives_up_before_any_sprint_push_c4(
    make_runtime, fake, monkeypatch
) -> None:
    rig = carried_setup(make_runtime, fake, monkeypatch)
    rt, story = rig.rt, rig.story
    fake.reply(("merge-base", "--is-ancestor"), Done(1), Done(0))
    land(rt, story)
    pushes = issued(fake, "push", f"{MERGE}:refs/heads/{SPRINT}")
    assert len(pushes) == 1  # only the fresh merge's push, after the drop
    assert len(issued(fake, "merge", "--no-ff")) == 2


def test_a_land_without_a_drop_has_no_dropped_key_c7(make_runtime, fake, monkeypatch) -> None:
    rig = carried_setup(make_runtime, fake, monkeypatch)
    rt, story = rig.rt, rig.story
    report = land(rt, story)
    assert "dropped" not in report.get("land", {})


# ---------- C8: resume ----------


def resumed(make_runtime, fake, monkeypatch) -> Rig:
    rig = carried_setup(make_runtime, fake, monkeypatch)
    rig.story.landed = Landed(MERGE, pushed=MERGE)
    return rig


def test_a_resume_over_carryable_commits_keeps_the_landing_c8(
    make_runtime, fake, monkeypatch
) -> None:
    rig = resumed(make_runtime, fake, monkeypatch)
    rt = rig.rt
    land(rt, rig.story)
    assert ("list_checks", MERGE) in rt.prs.calls
    assert issued(fake, "merge", "--no-ff") == []
    assert events_of(rt, EventKind.LANDING_DROPPED) == []
    assert rig.resets == [(H2, TIP)]


def test_a_resume_makes_no_replay_while_checking_c8(make_runtime, fake, monkeypatch) -> None:
    rig = resumed(make_runtime, fake, monkeypatch)
    calls: list = []
    original = lc.Carrier.carry
    monkeypatch.setattr(lc.Carrier, "carry", lambda s, sp, c: calls.append(1) or original(s, sp, c))
    land(rig.rt, rig.story)
    assert calls == [1]  # once, at the push, never while checking the resume


def test_a_resume_refused_off_head_gives_up_and_merges_afresh_c8(
    make_runtime, fake, monkeypatch
) -> None:
    rig = resumed(make_runtime, fake, monkeypatch)
    rt, story = rig.rt, rig.story
    fake.reply(("rev-parse", f"{MERGE}^1"), Done(0, HEAD + "\n"), Done(0, H2 + "\n"))
    fake.reply(("merge-base", "--is-ancestor"), Done(1), Done(0))
    land(rt, story)
    [drop] = events_of(rt, EventKind.LANDING_DROPPED)
    assert drop.data["refusal"].startswith("the sprint head")
    assert len(issued(fake, "merge", "--no-ff")) == 1


def test_a_resume_refused_by_a_forked_story_names_it_c8(make_runtime, fake, monkeypatch) -> None:
    rig = resumed(make_runtime, fake, monkeypatch)
    rt, story = rig.rt, rig.story
    rt.state.stories["s2"] = StoryState("s2", "T", "implement", sprint=1, base_sha=C1.sha)
    fake.reply(("rev-parse", f"{MERGE}^1"), Done(0, HEAD + "\n"), Done(0, H2 + "\n"))
    land(rt, story)
    [drop] = events_of(rt, EventKind.LANDING_DROPPED)
    assert drop.data["refusal"] == lc.CARRY_FORKED.format(
        story="s2", commit="1111111 " + C1.subject
    )


def test_a_resume_whose_merge_has_no_first_parent_gives_up_without_listing_c8(
    make_runtime, fake, monkeypatch
) -> None:
    rig = resumed(make_runtime, fake, monkeypatch)
    rt, story = rig.rt, rig.story
    fake.reply(
        ("rev-parse", f"{MERGE}^1"), Done(128, "", "fatal: bad revision"), Done(0, H2 + "\n")
    )
    land(rt, story)
    drop = events_of(rt, EventKind.LANDING_DROPPED)[0]
    assert drop.data["refusal"] == lc.CARRY_NO_BASE.format(merge=MERGE[: lc.SHORT])
    assert drop.data["moved_by"] == []
    assert issued(fake, "log", "--reverse") == []


# ---------- C9: local mode ----------


def test_local_mode_carries_with_no_push_c9(make_runtime, fake, monkeypatch) -> None:
    rig = carried_setup(make_runtime, fake, monkeypatch, push=Permission.NO)
    rt = rig.rt
    land(rt, rig.story)
    assert issued(fake, "push") == []
    assert rig.resets == [(H2, TIP)] and rig.advanced == []
    assert len(events_of(rt, EventKind.LANDING_CARRIED)) == 1
    assert events_of(rt, EventKind.LANDING_DROPPED) == []


def test_local_mode_gives_up_on_a_refused_carry_without_moving_c9(
    make_runtime, fake, monkeypatch
) -> None:
    rig = carried_setup(make_runtime, fake, monkeypatch, push=Permission.NO)
    rt, story = rig.rt, rig.story
    fake.reply(("merge-base", "--is-ancestor"), Done(1), Done(0))
    land(rt, story)
    assert len(events_of(rt, EventKind.LANDING_DROPPED)) == 1


# ---------- a failed move halts; a refused push has no moved_by ----------


def test_a_failed_checkout_move_halts_and_logs_no_carry_c4(make_runtime, fake, monkeypatch) -> None:
    rig = carried_setup(make_runtime, fake, monkeypatch)
    rt, story = rig.rt, rig.story
    monkeypatch.setattr(lc.Carrier, "move_checkout", lambda self, carry: False)
    land(rt, story)
    assert rt.halted_by is not None
    assert events_of(rt, EventKind.LANDING_CARRIED) == []


def test_a_refused_sprint_push_drops_with_no_moved_by_and_no_refusal_c6(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    fake.reply(("push", f"{MERGE}:refs/heads/{SPRINT}"), Done(1, "! [rejected]"))
    fake.reply(("ls-remote",), Done(0, f"{'a' * 40}\trefs/heads/{SPRINT}\n"))
    fake.reply(("merge-base", "--is-ancestor"), Done(0))
    land(rt, story)
    first = events_of(rt, EventKind.LANDING_DROPPED)[0]
    assert first.data["why"] == "sprint push refused"
    assert first.data["moved_by"] == [] and first.data["refusal"] == ""


def test_give_up_adds_the_drop_to_the_attempt_c7(make_runtime, fake) -> None:
    rt, story, entry = setup(make_runtime, fake)
    story.landed = Landed(MERGE, pushed=MERGE)
    attempt = landing.Attempt(story, entry, HEAD, merge=MERGE)
    drop = lc.Drop("sprint head moved", ("1111111 x",), "no")
    asyncio.run(landing.Lander(rt, asyncio.Lock()).give_up(attempt, drop))
    assert attempt.dropped == [lc.describe_drop(drop, MERGE)]
    [event] = events_of(rt, EventKind.LANDING_DROPPED)
    assert event.data == lc.describe_drop(drop, MERGE) | {"sprint_head": HEAD}

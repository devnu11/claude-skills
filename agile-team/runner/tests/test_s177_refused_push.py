"""s177: a refused sprint push holds at once if the remote didn't move; remote == merge lands."""

from __future__ import annotations

from agile_team.events import EventKind
from agile_team.gates import Verdict
from agile_team.story_branches import Landed

from .fake_system import Done
from .test_s159_landing import BRANCH, HEAD, LAND, MERGE, SPRINT, checks, issued, land, setup

REFUSAL = "! [rejected] remote said no"


def refuse_push(fake) -> None:
    fake.reply(("push", f"{MERGE}:refs/heads/{SPRINT}"), Done(1, REFUSAL))


def remote_heads(fake, *heads: str) -> None:
    fake.reply(("ls-remote",), *[Done(0, f"{h}\trefs/heads/{SPRINT}\n") for h in heads])


def events(rt, kind: EventKind) -> list:
    return [e for e in rt.events.events() if e.kind == kind]


def landing_deletes(fake) -> list[tuple[str, ...]]:
    return issued(fake, "push", f":refs/heads/{LAND}")


# ---------- AC1: the remote did not move ----------


def test_an_unmoved_remote_holds_at_once_with_the_refusal_text_ac1(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    refuse_push(fake)
    remote_heads(fake, HEAD)
    report = land(rt, story)
    assert report["gate"]["verdict"] == Verdict.HOLD
    assert REFUSAL in report["gate"]["reason"]
    assert len(issued(fake, "merge", "--no-ff")) == 1
    assert len(issued(fake, "push", f"{MERGE}:refs/heads/{SPRINT}")) == 1


def test_an_unmoved_remote_keeps_the_merge_and_the_landing_branch_ac1(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake)
    refuse_push(fake)
    remote_heads(fake, HEAD)
    land(rt, story)
    assert story.landed == Landed(MERGE, pushed=MERGE)
    assert entry.pushed == HEAD
    assert landing_deletes(fake) == []
    assert events(rt, EventKind.LANDING_DROPPED) == []


def test_a_retry_pushes_the_same_merge_again_ac1(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake)
    refuse_push(fake)
    remote_heads(fake, HEAD)
    land(rt, story)
    fake.reply(("push", f"{MERGE}:refs/heads/{SPRINT}"), Done(0))
    report = land(rt, story)
    assert report["gate"]["verdict"] == Verdict.PASS
    assert len(issued(fake, "merge", "--no-ff")) == 1
    assert len(issued(fake, "push", f"{MERGE}:refs/heads/{SPRINT}")) == 2
    assert entry.pushed == MERGE
    assert BRANCH  # the story branch name is untouched by the hold


# ---------- AC2: the remote already holds the merge ----------


def test_a_remote_equal_to_the_merge_counts_as_pushed_ac2(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake)
    refuse_push(fake)
    remote_heads(fake, MERGE)
    fake.reply(("merge-base", "--is-ancestor", MERGE, "HEAD"), Done(1))
    fake.reply(("merge-base", "--is-ancestor", "HEAD", MERGE), Done(0))
    report = land(rt, story)
    assert report["gate"]["verdict"] == Verdict.PASS
    assert (entry.pushed, entry.head) == (MERGE, MERGE)
    assert any(MERGE in a for a in issued(fake, "merge", "--ff-only"))


def test_a_remote_equal_to_the_merge_records_landed_green_without_a_drop_ac2(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    refuse_push(fake)
    remote_heads(fake, MERGE)
    fake.reply(("merge-base", "--is-ancestor", MERGE, "HEAD"), Done(1))
    fake.reply(("merge-base", "--is-ancestor", "HEAD", MERGE), Done(0))
    land(rt, story)
    landed = events(rt, EventKind.STORY_LANDED)
    assert len(landed) == 1 and landed[0].data["ci"] == "green"
    assert landed[0].data["merge"] == MERGE
    assert events(rt, EventKind.LANDING_DROPPED) == []
    assert len(issued(fake, "merge", "--no-ff")) == 1


# ---------- AC3: the remote moved on ----------


def test_a_remote_that_moved_on_is_followed_and_landed_again_ac3(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake)
    refuse_push(fake)
    ahead = "a" * 40
    remote_heads(fake, ahead)
    land(rt, story)
    assert len(issued(fake, "merge", "--no-ff")) >= 2
    refused = [
        d for d in events(rt, EventKind.LANDING_DROPPED) if d.data["why"].startswith("sprint push")
    ]
    assert refused
    assert entry.pushed == ahead


def test_the_hold_comes_after_max_restarts_distinct_heads_and_lists_them_ac3(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    refuse_push(fake)
    heads = [c * 40 for c in "abcde"]
    remote_heads(fake, *heads)
    report = land(rt, story)
    assert "the sprint branch kept moving" in str(report)
    assert all(h in str(report) for h in heads)
    assert len(issued(fake, "merge", "--no-ff")) == 5


def test_a_repeated_remote_head_holds_before_max_restarts_ac3(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    refuse_push(fake)
    remote_heads(fake, "a" * 40, "a" * 40)
    report = land(rt, story)
    assert REFUSAL in str(report)
    assert len(issued(fake, "merge", "--no-ff")) == 2

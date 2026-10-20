"""s163 G1/K2/R1: a landing never pushes a merge made on an older sprint head."""

from __future__ import annotations

from agile_team.events import EventKind
from agile_team.halt import HaltKind

from .fake_system import Done
from .test_s159_landing import MERGE, SPRINT, checks, issued, land, setup

MOVED = "e" * 40


def sprint_pushes(fake) -> list[tuple[str, ...]]:
    return issued(fake, "push", f"{MERGE}:refs/heads/{SPRINT}")


def test_a_merge_not_on_the_sprint_head_is_given_up_not_pushed_k2(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    fake.reply(("rev-parse", f"{MERGE}^1"), Done(0, MOVED + "\n"))
    land(rt, story)
    assert sprint_pushes(fake) == []
    dropped = [e for e in rt.events.events() if e.kind == EventKind.LANDING_DROPPED]
    assert dropped and dropped[0].data["why"] == "sprint head moved"
    assert dropped[0].data["merge"] == MERGE and dropped[0].story == "s1"


def test_a_merge_on_the_head_is_pushed_and_nothing_is_dropped_k2(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake)
    land(rt, story)
    assert len(sprint_pushes(fake)) == 1
    assert [e for e in rt.events.events() if e.kind == EventKind.LANDING_DROPPED] == []
    assert entry.pushed == MERGE


def test_pushed_names_the_merge_even_when_the_fast_forward_fails_r1(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake)
    fake.reply(("merge", "--ff-only"), Done(1, "not possible"))
    land(rt, story)
    assert entry.pushed == MERGE
    assert rt.halted_by is not None and rt.halted_by.kind is HaltKind.CHECKOUT


def test_a_refused_push_gives_up_the_merge_g4(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    fake.reply(("push", f"{MERGE}:refs/heads/{SPRINT}"), Done(1, "! [rejected]"))
    land(rt, story)
    dropped = [e for e in rt.events.events() if e.kind == EventKind.LANDING_DROPPED]
    assert any(e.data["why"] == "sprint push refused" for e in dropped)

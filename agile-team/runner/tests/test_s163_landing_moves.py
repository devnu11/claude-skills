"""s163 G1 to G5, K1 to K3, R2: giving up a merge, following a remote, and the main lock."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from agile_team.ci import CiResult, CiVerdict
from agile_team.events import EventKind
from agile_team.halt import HaltKind
from agile_team.story_branches import Landed

from .fake_system import Done
from .test_s159_landing import (
    HEAD,
    LAND,
    MERGE,
    SPRINT,
    Permission,
    checks,
    ff,
    issued,
    land,
    landing,
    setup,
)

MOVED, REMOTE = "e" * 40, "a" * 40


def dropped(rt) -> list:
    return [e for e in rt.events.events() if e.kind == EventKind.LANDING_DROPPED]


def sprint_pushes(fake) -> list:
    return issued(fake, "push", f"{MERGE}:refs/heads/{SPRINT}")


def lander(rt, lock=None):
    return landing.Lander(rt, lock or asyncio.Lock())


def attempt_of(rt, story, entry):
    return landing.Attempt(story, entry, HEAD, merge=MERGE)


# ---------- G1, G3: resuming and giving up ----------


def test_a_resume_with_the_merge_on_the_head_reads_ci_and_makes_no_merge_g1(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    story.landed = Landed(MERGE, pushed=MERGE)
    land(rt, story)
    assert ("sha_checks", MERGE) in rt.prs.calls
    assert issued(fake, "merge", "--no-ff") == [] and dropped(rt) == []


def test_a_resume_with_the_merge_off_the_head_gives_up_and_merges_afresh_g1(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake)
    story.landed = Landed(MERGE, pushed=MERGE)
    fake.reply(("rev-parse", f"{MERGE}^1"), Done(0, MOVED + "\n"), Done(0, HEAD + "\n"))
    land(rt, story)
    assert [e.data["why"] for e in dropped(rt)] == ["sprint head moved"]
    assert len(issued(fake, "merge", "--no-ff")) == 1
    assert entry.pushed == MERGE and rt.halted_by is None


def test_giving_up_clears_landed_and_deletes_the_landing_branch_with_its_lease_g3(
    make_runtime, fake
) -> None:
    rt, story, entry = setup(make_runtime, fake)
    story.landed = Landed(MERGE, pushed=MERGE)
    asyncio.run(lander(rt).give_up(attempt_of(rt, story, entry), "why"))
    assert story.landed is None
    [delete] = issued(fake, "push", f":refs/heads/{LAND}")
    assert any(f"{LAND}:{MERGE}" in a for a in delete)


def test_a_landing_branch_that_is_already_gone_is_not_an_error_g3(make_runtime, fake) -> None:
    rt, story, entry = setup(make_runtime, fake)
    fake.reply(("push", f":refs/heads/{LAND}"), Done(1, "unable to delete: remote ref"))
    attempt = attempt_of(rt, story, entry)
    asyncio.run(lander(rt).give_up(attempt, "why"))
    assert attempt.merge == "" and len(dropped(rt)) == 1


# ---------- G4: a refused sprint push ----------


def follow(rt, story, entry) -> tuple[object, object]:
    attempt = attempt_of(rt, story, entry)
    return asyncio.run(lander(rt).follow_remote(attempt)), attempt


def remote_at(fake, sha: str) -> None:
    fake.reply(("ls-remote",), Done(0, f"{sha}\trefs/heads/{SPRINT}\n"))


def test_a_remote_that_is_our_pushed_gives_up_and_starts_again_g4(make_runtime, fake) -> None:
    rt, story, entry = setup(make_runtime, fake)
    story.landed = Landed(MERGE, pushed=MERGE)
    remote_at(fake, HEAD)
    fake.reply(("merge-base", "--is-ancestor"), Done(0))
    report, _ = follow(rt, story, entry)
    assert report is None and rt.halted_by is None
    assert story.landed is None and entry.pushed == HEAD and ff(fake) == []


def test_a_remote_that_moved_ahead_is_followed_with_head_and_pushed_equal_r2(
    make_runtime, fake
) -> None:
    rt, story, entry = setup(make_runtime, fake)
    entry.pushed = "p" * 40
    remote_at(fake, REMOTE)
    fake.reply(("merge-base", "--is-ancestor"), Done(0), Done(1), Done(0))
    report, _ = follow(rt, story, entry)
    assert report is None and rt.halted_by is None
    assert entry.head == entry.pushed == REMOTE
    assert any(REMOTE in a for a in ff(fake))


def test_a_remote_that_does_not_descend_from_pushed_halts_with_landed_cleared_g4(
    make_runtime, fake
) -> None:
    rt, story, entry = setup(make_runtime, fake)
    story.landed = Landed(MERGE, pushed=MERGE)
    remote_at(fake, "d" * 40)
    fake.reply(("merge-base", "--is-ancestor"), Done(1))
    follow(rt, story, entry)
    assert rt.halted_by is not None and rt.halted_by.kind is HaltKind.CHECKOUT
    assert story.landed is None and ff(fake) == []


def test_an_empty_remote_halts_g4(make_runtime, fake) -> None:
    rt, story, entry = setup(make_runtime, fake)
    fake.reply(("ls-remote",), Done(0, ""))
    follow(rt, story, entry)
    assert rt.halted_by is not None and "unknown" in rt.halted_by.reason


def test_a_failed_follow_fast_forward_halts_and_records_nothing_r2(make_runtime, fake) -> None:
    rt, story, entry = setup(make_runtime, fake)
    old = entry.pushed = "p" * 40
    remote_at(fake, REMOTE)
    fake.reply(("merge-base", "--is-ancestor"), Done(0), Done(1), Done(0))
    fake.reply(("merge", "--ff-only"), Done(1, "not possible"))
    follow(rt, story, entry)
    assert rt.halted_by is not None
    assert entry.pushed == old and REMOTE not in (entry.head, entry.pushed)


def test_a_remote_neither_behind_nor_ahead_of_head_halts_g4(make_runtime, fake) -> None:
    rt, story, entry = setup(make_runtime, fake)
    remote_at(fake, REMOTE)
    fake.reply(("merge-base", "--is-ancestor"), Done(0), Done(1), Done(1))
    follow(rt, story, entry)
    assert rt.halted_by is not None and ff(fake) == []


def test_a_refused_landing_whose_remote_is_ours_does_not_halt_g4(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    fake.reply(("push", f"{MERGE}:refs/heads/{SPRINT}"), Done(1, "! [rejected]"))
    remote_at(fake, HEAD)
    fake.reply(("merge-base", "--is-ancestor"), Done(0))
    land(rt, story)
    assert rt.halted_by is None and len(dropped(rt)) >= 1


# ---------- K1, K2: the lock ----------


@dataclass
class Probe:
    """Records whether the main lock was held at each probed moment."""

    lock: asyncio.Lock
    seen: dict[str, list[bool]] = field(default_factory=dict)

    def note(self, name: str) -> None:
        self.seen.setdefault(name, []).append(self.lock.locked())


def watch_with(probe: Probe, act=None):
    @dataclass
    class Watch:
        prs: object
        limit_s: float

        async def result(self, sha: str, reran: list) -> CiResult:
            probe.note("ci")
            if act:
                act()
            return CiResult(0, "", sha, CiVerdict.GREEN, [])

    return Watch


def probed(rt, monkeypatch, act=None) -> Probe:
    probe = Probe(asyncio.Lock())
    monkeypatch.setattr("agile_team.landing.ShaWatch", watch_with(probe, act))
    for owner, name in ((rt.upstream, "fast_forward"), (rt, "record_checkout")):
        original = getattr(owner, name)

        def wrapper(*a, _o=original, _n=name):
            probe.note(_n)
            return _o(*a)

        monkeypatch.setattr(owner, name, wrapper)
    return probe


def run_with(rt, probe, story) -> dict:
    return asyncio.run(landing.Lander(rt, probe.lock).land(story))


def test_the_lock_is_free_during_ci_and_held_for_the_move_on_a_first_landing_k1(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    probe = probed(rt, monkeypatch)
    run_with(rt, probe, story)
    assert probe.seen == {"ci": [False], "fast_forward": [True], "record_checkout": [True]}
    assert not probe.lock.locked()


def test_the_lock_is_held_for_the_move_on_a_resumed_landing_k2(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    story.landed = Landed(MERGE, pushed=MERGE)
    probe = probed(rt, monkeypatch)
    run_with(rt, probe, story)
    assert probe.seen == {"ci": [False], "fast_forward": [True], "record_checkout": [True]}


def test_the_lock_can_be_taken_by_others_while_ci_waits_k1(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    probe = probed(rt, monkeypatch)
    got: list[bool] = []

    def act() -> None:
        got.append(probe.lock.locked())

    monkeypatch.setattr("agile_team.landing.ShaWatch", watch_with(probe, act))
    run_with(rt, probe, story)
    assert got == [False]


def test_a_head_that_moves_during_ci_gives_up_the_merge_before_the_push_k6(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, entry = setup(make_runtime, fake)

    def move_head() -> None:
        entry.head = MOVED

    probe = probed(rt, monkeypatch, act=move_head)
    run_with(rt, probe, story)
    assert sprint_pushes(fake) == []
    assert dropped(rt) and dropped(rt)[0].data["why"] == "sprint head moved"
    assert probe.seen.get("fast_forward") is None


def test_local_mode_holds_the_lock_for_the_fast_forward_k3(make_runtime, fake, monkeypatch) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake, push=Permission.NO)
    probe = probed(rt, monkeypatch)
    run_with(rt, probe, story)
    assert probe.seen == {"fast_forward": [True], "record_checkout": [True]}


def test_local_mode_gives_up_a_stale_merge_without_a_fast_forward_k3(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake, push=Permission.NO)
    fake.reply(("rev-parse", f"{MERGE}^1"), Done(0, MOVED + "\n"))
    land(rt, story)
    assert ff(fake) == []
    assert dropped(rt) and dropped(rt)[0].data["why"] == "sprint head moved"


def test_a_revert_landing_takes_the_lock_only_for_the_move_k4(
    make_runtime, fake, monkeypatch
) -> None:
    checks(monkeypatch)
    rt, story, _ = setup(make_runtime, fake)
    story.landed = Landed(MERGE, pushed=MERGE, pr=1)
    probe = probed(rt, monkeypatch)
    asyncio.run(landing.Lander(rt, probe.lock).land_revert(story, "bad"))
    assert probe.seen["ci"] == [False] and probe.seen["fast_forward"] == [True]

"""s159 C5, C6, C9: the one writer, the PO desk, the turn snapshot; rewrite.pair_replay (R4)."""

from __future__ import annotations

import asyncio

import pytest
from agile_team import rewrite
from agile_team.gates import StoryState
from agile_team.handover import Pass, Trigger
from agile_team.state import RunState

from .lazy import Lazy

po_desk = Lazy("agile_team.po_desk")
rw = Lazy("agile_team.run_writer")

# ---------- RunWriter ----------


def test_unbound_writer_writes_at_once() -> None:
    """s159 rule: unbound writer writes at once."""
    seen: list[str] = []
    writer = rw.RunWriter()
    writer.submit(lambda: seen.append("a"))
    assert seen == ["a"]


def test_bound_writer_holds_until_drained() -> None:
    """s159 rule: bound writer holds until drained."""

    async def go() -> list[str]:
        seen: list[str] = []
        writer = rw.RunWriter()
        writer.bind(asyncio.get_running_loop(), asyncio.current_task())
        writer.submit(lambda: seen.append("a"))
        assert seen == []
        assert writer.drain() == 1
        return seen

    assert asyncio.run(go()) == ["a"]


def test_apply_runs_the_change_and_returns_its_result() -> None:
    """s159 rule: apply runs the change and returns its result."""

    async def go() -> int:
        writer = rw.RunWriter()
        loop = asyncio.get_running_loop()
        writer.bind(loop, asyncio.current_task())
        job = asyncio.ensure_future(writer.apply(lambda: 7))
        await asyncio.sleep(0)
        writer.drain()
        return await job

    assert asyncio.run(go()) == 7


def test_apply_unbound_runs_directly() -> None:
    """s159 rule: apply unbound runs directly."""
    assert asyncio.run(rw.RunWriter().apply(lambda: 3)) == 3


def test_check_owner_refuses_a_worker_thread() -> None:
    """s159 rule: check owner refuses a worker thread."""

    async def go() -> None:
        writer = rw.RunWriter()
        writer.bind(asyncio.get_running_loop(), asyncio.current_task())
        with pytest.raises(rw.WrongWriter):
            await asyncio.to_thread(writer.check_owner)
        writer.check_owner()

    asyncio.run(go())


# ---------- PoDesk (C5) ----------


def p(kind: Trigger, line: str, story: str) -> Pass:
    return Pass([kind], [line], [story])


def test_desk_takes_nothing_when_empty() -> None:
    """s159 rule: desk takes nothing when empty."""
    desk = po_desk.PoDesk()
    assert desk.take() is None and not desk.busy


def test_desk_merges_queued_passes_into_one_turn() -> None:
    """s159 rule: desk merges queued passes into one turn."""
    desk = po_desk.PoDesk()
    desk.queue(p(Trigger.LAND_BOUNCED, "a", "s1"))
    desk.queue(p(Trigger.WORKTREE_DRIFT, "b", "s2"))
    got = desk.take()
    assert got is not None and got.lines == ["a", "b"] and got.stories == ["s1", "s2"]


def test_a_pass_stays_until_the_turn_is_done() -> None:
    """s159 rule: a pass stays until the turn is done."""
    desk = po_desk.PoDesk()
    desk.queue(p(Trigger.LAND_BOUNCED, "a", "s1"))
    assert desk.take() is not None
    assert desk.busy
    again = desk.take()
    assert again is not None and again.lines == ["a"]
    desk.done()
    assert desk.take() is None and not desk.busy


def test_passes_arriving_during_a_turn_wait_for_the_next() -> None:
    """s159 rule: passes arriving during a turn wait for the next."""
    desk = po_desk.PoDesk()
    desk.queue(p(Trigger.LAND_BOUNCED, "a", "s1"))
    desk.take()
    desk.queue(p(Trigger.WORKTREE_DRIFT, "b", "s2"))
    desk.done()
    nxt = desk.take()
    assert nxt is not None and nxt.lines == ["b"]


# ---------- TurnSnapshot (C9) ----------


def state_with(*stories: StoryState) -> RunState:
    state = RunState()
    state.stories = {s.id: s for s in stories}
    return state


def test_snapshot_marks_cover_every_story() -> None:
    """s159 rule: snapshot marks cover every story."""
    s = StoryState(id="s1", title="t", step="implement")
    snap = po_desk.TurnSnapshot.take(state_with(s))
    assert snap.moved(["s1"], state_with(s)) is None


def test_snapshot_refuses_a_story_that_moved() -> None:
    """s159 rule: snapshot refuses a story that moved."""
    s = StoryState(id="s1", title="t", step="implement")
    snap = po_desk.TurnSnapshot.take(state_with(s))
    s.step = "acceptance"
    text = snap.moved(["s1"], state_with(s))
    assert text is not None and text.startswith("story s1 moved since your turn began")


def test_refresh_lets_the_po_follow_its_own_change() -> None:
    """s159 rule: refresh lets the po follow its own change."""
    s = StoryState(id="s1", title="t", step="implement")
    state = state_with(s)
    snap = po_desk.TurnSnapshot.take(state)
    s.step = "acceptance"
    snap.refresh(["s1"], state)
    assert snap.moved(["s1"], state) is None


def test_unnamed_stories_are_not_checked() -> None:
    """s159 rule: unnamed stories are not checked."""
    a = StoryState(id="s1", title="t", step="implement")
    b = StoryState(id="s2", title="t", step="implement")
    state = state_with(a, b)
    snap = po_desk.TurnSnapshot.take(state)
    b.step = "land"
    assert snap.moved(["s1"], state) is None


# ---------- rewrite.pair_replay (R4) ----------


def test_pair_replay_pairs_plain_commits_by_subject_in_order() -> None:
    """s159 rule: pair replay pairs plain commits by subject in order."""
    old = [("o1", "one", ()), ("o2", "two", ("o1",))]
    new = [("n1", "one", ()), ("n2", "two", ("n1",))]
    assert rewrite.pair_replay(old, new) == {"o1": "n1", "o2": "n2"}


def test_pair_replay_pairs_story_commits_and_the_merge_by_id() -> None:
    """s159 rule: pair replay pairs story commits and the merge by id."""
    old = [
        ("a1", "feat s1", ("base",)),
        ("m1", "merge(s1): T", ("base", "a1")),
    ]
    new = [
        ("b1", "feat s1", ("tip",)),
        ("m2", "merge(s1): T", ("tip", "b1")),
    ]
    got = rewrite.pair_replay(old, new)
    assert got["a1"] == "b1" and got["m1"] == "m2"


def test_pair_replay_empty() -> None:
    """s159 rule: pair replay empty."""
    assert rewrite.pair_replay([], []) == {}

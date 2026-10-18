"""s159 C5/C9: queued passes, one PO turn at a time, snapshots of story marks."""

from agile_team import handover as ho
from agile_team import po_desk as pd
from agile_team.gates import StoryState
from agile_team.state import RunState


def pass_of(kind: ho.Trigger, line: str, story: str) -> ho.Pass:
    return ho.Pass([kind], [line], [story])


def test_an_empty_desk_has_nothing_to_take_r1() -> None:
    desk = pd.PoDesk()
    assert desk.take() is None and not desk.busy


def test_a_turn_takes_every_queued_pass_merged_r1() -> None:
    desk = pd.PoDesk()
    desk.queue(pass_of(ho.Trigger.STORY_CI_RED, "a", "s1"))
    desk.queue(pass_of(ho.Trigger.LAND_BOUNCED, "b", "s2"))
    taken = desk.take()
    assert taken.lines == ["a", "b"] and taken.stories == ["s1", "s2"]
    assert desk.busy


def test_passes_stay_queued_until_the_turn_is_done_r1() -> None:
    desk = pd.PoDesk()
    desk.queue(pass_of(ho.Trigger.STORY_CI_RED, "a", "s1"))
    desk.take()
    again = desk.take()
    assert again is not None and again.lines == ["a"]


def test_passes_arriving_during_a_turn_wait_for_the_next_r1() -> None:
    desk = pd.PoDesk()
    desk.queue(pass_of(ho.Trigger.STORY_CI_RED, "a", "s1"))
    desk.take()
    desk.queue(pass_of(ho.Trigger.LAND_BOUNCED, "b", "s2"))
    desk.done()
    assert not desk.busy
    nxt = desk.take()
    assert nxt.lines == ["b"]
    desk.done()
    assert desk.take() is None


def state_with(*ids: str) -> RunState:
    state = RunState()
    for i in ids:
        state.stories[i] = StoryState(id=i, title=i, step="implement")
    return state


def test_a_snapshot_sees_no_move_when_nothing_changed_r1() -> None:
    state = state_with("s1", "s2")
    snap = pd.TurnSnapshot.take(state)
    assert snap.moved(["s1", "s2"], state) is None


def test_a_moved_story_is_refused_with_its_new_state_r1() -> None:
    state = state_with("s1")
    snap = pd.TurnSnapshot.take(state)
    state.stories["s1"].step = "land"
    text = snap.moved(["s1"], state)
    assert text is not None and text.startswith("story s1 moved since your turn began")


def test_a_story_not_named_may_move_r1() -> None:
    state = state_with("s1", "s2")
    snap = pd.TurnSnapshot.take(state)
    state.stories["s2"].rounds = 3
    assert snap.moved(["s1"], state) is None


def test_refresh_accepts_the_pos_own_change_r1() -> None:
    state = state_with("s1")
    snap = pd.TurnSnapshot.take(state)
    state.stories["s1"].rounds = 1
    assert snap.moved(["s1"], state) is not None
    snap.refresh(["s1"], state)
    assert snap.moved(["s1"], state) is None


def test_the_mark_covers_the_documented_fields_r1() -> None:
    mark = pd.Mark("implement", "active", None, None, 0, False)
    assert mark.landed is False

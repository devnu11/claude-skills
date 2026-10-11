"""Story priority (s40): the one ranking rule, refusals, moves and waits."""

from __future__ import annotations

import pytest
from agile_team.gates import PreviousStep, StoryState, StoryStatus
from agile_team.priority import (
    BAD_POSITION,
    DONE,
    NO_STORIES,
    UNKNOWN,
    Placement,
    Priority,
    moves,
    natural,
    order_refusal,
)
from agile_team.waits import WAITS, Wait, WaitReason, wait


def story(sid: str, step: str = "design", **kw) -> StoryState:
    return StoryState(sid, sid, step, **kw)


def stories_of(*items: StoryState) -> dict[str, StoryState]:
    return {s.id: s for s in items}


def ids(items) -> list[str]:
    return [s.id for s in items]


def test_natural_compares_digit_runs_as_numbers() -> None:
    assert natural("s9") < natural("s10") < natural("s100")
    assert natural("a") < natural("b")


def test_legacy_empty_order_in_progress_then_natural_id() -> None:
    s9, s29, s3 = story("s9"), story("s29", "tests"), story("s3")
    ranked = Priority([], "design").ranked([s9, s29, s3])
    assert ids(ranked) == ["s29", "s3", "s9"]


def test_previous_step_counts_as_in_progress() -> None:
    p = Priority([], "design")
    ran = story("s5", previous=PreviousStep("architect", "done"))
    assert p.in_progress(ran) and not p.in_progress(story("s1"))
    assert ids(p.ranked([story("s1"), ran])) == ["s5", "s1"]


def test_done_stories_rank_last_even_when_listed() -> None:
    done = story("s1", "tests", status=StoryStatus.DONE)
    ranked = Priority(["s1"], "design").ranked([done, story("s2")])
    assert ids(ranked) == ["s2", "s1"]


def test_explicit_position_beats_in_progress() -> None:
    p = Priority(["s9"], "design")
    assert ids(p.ranked([story("s2", "tests"), story("s9")])) == ["s9", "s2"]


def test_unlisted_after_listed_and_unknown_ids_ignored() -> None:
    p = Priority(["ghost", "s5", "s7"], "design")
    ranked = p.ranked([story("s1"), story("s7"), story("s5")])
    assert ids(ranked) == ["s5", "s7", "s1"]


def test_queue_excludes_done_and_is_ranked() -> None:
    items = [story("s1", status=StoryStatus.DONE), story("s3"), story("s2")]
    assert Priority(["s3"], "design").queue(items) == ["s3", "s2"]


def test_worked_ranking_example() -> None:
    items = [
        story("s9"),
        story("s26"),
        story("s29", "tests"),
        story("s30"),
        story("s1", status=StoryStatus.DONE),
    ]
    p = Priority(["s30", "s26"], "design")
    assert p.queue(items) == ["s30", "s26", "s29", "s9"]
    assert ids(p.ranked(items))[-1] == "s1"


def test_with_first_lists_ids_then_rest_in_queue_order() -> None:
    items = [story("s1"), story("s2"), story("s3"), story("s4", status=StoryStatus.DONE)]
    p = Priority([], "design")
    assert p.with_first(["s3", "s4"], items) == ["s3", "s1", "s2"]


@pytest.mark.parametrize(
    ("position", "want"),
    [(1, ["s3", "s1", "s2"]), (3, ["s1", "s2", "s3"]), (2, ["s1", "s3", "s2"])],
)
def test_with_move(position: int, want: list[str]) -> None:
    items = [story("s1"), story("s2"), story("s3")]
    p = Priority(["s1", "s2", "s3"], "design")
    assert p.with_move(Placement("s3", position), items) == want


def test_order_refusal_texts() -> None:
    items = stories_of(story("s1"), story("s2", status=StoryStatus.DONE))
    assert order_refusal([], items) == NO_STORIES
    assert order_refusal(["s1", "x", "y"], items) == UNKNOWN.format(ids="x, y")
    assert order_refusal(["s2"], items) == DONE.format(ids="s2")
    assert order_refusal(["s1"], items) is None


@pytest.mark.parametrize("position", [0, 3, "2", True, None, 1.5])
def test_move_refusal_bad_positions(position) -> None:
    items = stories_of(story("s1"), story("s2"))
    p = Priority([], "design")
    assert p.move_refusal(Placement("s1", position), items) == BAD_POSITION.format(count=2)


def test_move_refusal_accepts_bounds_and_refuses_unknown_and_done() -> None:
    items = stories_of(story("s1"), story("s2"), story("s3", status=StoryStatus.DONE))
    p = Priority([], "design")
    assert p.move_refusal(Placement("s1", 1), items) is None
    assert p.move_refusal(Placement("s2", 2), items) is None
    assert p.move_refusal(Placement("zz", 1), items) == UNKNOWN.format(ids="zz")
    assert p.move_refusal(Placement("s3", 1), items) == DONE.format(ids="s3")


def test_moves_lists_only_changed_stories_one_based() -> None:
    got = moves(["s1", "s2", "s3", "s4"], ["s3", "s1", "s2", "s4"])
    assert got == [
        {"story": "s3", "from": 3, "to": 1},
        {"story": "s1", "from": 1, "to": 2},
        {"story": "s2", "from": 2, "to": 3},
    ]
    assert moves(["s1"], ["s1"]) == []


# ----- waits ----------------------------------------------------------------

PREV = PreviousStep("architect", "done", "Asked which")


def test_waits_table_has_the_six_rows_in_order() -> None:
    assert [r.reason for r in WAITS] == [
        WaitReason.HUMAN,
        WaitReason.MANAGER,
        WaitReason.ROUND_CAP,
        WaitReason.QUESTIONS,
        WaitReason.HELD,
        WaitReason.HUMAN,
    ]


def test_wait_blocked_needs_the_human() -> None:
    s = story("s1", status=StoryStatus.BLOCKED, previous=PREV)
    assert wait(s, []) == Wait(WaitReason.HUMAN, ["architect: Asked which"])


def test_wait_needs_manager_with_repeated_uses_first_line() -> None:
    s = story("s1", status=StoryStatus.NEEDS_MANAGER, repeated="same reason\nmore")
    assert wait(s, []) == Wait(WaitReason.MANAGER, ["same reason"])


def test_wait_needs_manager_without_repeated_is_round_cap() -> None:
    s = story("s1", status=StoryStatus.NEEDS_MANAGER, rounds=3)
    assert wait(s, []) == Wait(WaitReason.ROUND_CAP, ["round 3: the manager must rule"])


def test_wait_questions_from_combined_hold() -> None:
    s = story("s1", hold="gate_hold, questions", previous=PREV)
    assert wait(s, ["m1: Q"]) == Wait(WaitReason.QUESTIONS, ["m1: Q", "architect: Asked which"])


def test_s27_worked_example() -> None:
    s = story("s27", hold="questions", previous=PREV)
    got = wait(s, ["m38: Which?"])
    assert got == Wait("questions", ["m38: Which?", "architect: Asked which"])


def test_wait_held_detail_has_hold_and_summary() -> None:
    s = story("s1", hold="quarantine", previous=PREV)
    assert wait(s, []) == Wait(WaitReason.HELD, ["quarantine · architect: Asked which"])
    assert wait(story("s2", hold="quarantine"), []) == Wait(WaitReason.HELD, ["quarantine"])


def test_wait_unheld_with_open_question() -> None:
    assert wait(story("s1"), ["m2: Q"]) == Wait(WaitReason.HUMAN, ["m2: Q"])


def test_wait_none_for_done_and_for_free_stories() -> None:
    done = story("s1", status=StoryStatus.DONE, hold="questions")
    assert wait(done, ["m1: Q"]) is None
    assert wait(story("s2"), []) is None

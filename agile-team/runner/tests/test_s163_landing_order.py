"""s163 Q2/Q3: size counting, smallest-first ranking and the PO's placement (pure parts)."""

from __future__ import annotations

from agile_team import landing_queue as lq
from agile_team.landing_queue import Candidate, Placement, arrange, count_lines, rank_smallest_first


def cands(**sizes: int) -> list[Candidate]:
    return [Candidate(story, size) for story, size in sizes.items()]


def test_count_lines_adds_insertions_and_deletions() -> None:
    line = " 3 files changed, 10 insertions(+), 4 deletions(-)\n"
    assert count_lines(line) == 14


def test_count_lines_insert_only() -> None:
    assert count_lines(" 1 file changed, 7 insertions(+)") == 7


def test_count_lines_delete_only() -> None:
    assert count_lines(" 2 files changed, 5 deletions(-)") == 5


def test_count_lines_of_nothing_is_zero() -> None:
    assert count_lines("") == 0
    assert count_lines("\n") == 0


def test_smallest_first_sorts_by_size() -> None:
    assert rank_smallest_first(cands(s1=30, s2=5, s3=12)) == ["s2", "s3", "s1"]


def test_ties_go_by_story_number_not_text() -> None:
    assert rank_smallest_first(cands(s10=4, s9=4)) == ["s9", "s10"]


def test_no_candidates_rank_to_nothing() -> None:
    assert rank_smallest_first([]) == []


def test_arrange_puts_placed_ids_first_in_the_pos_order() -> None:
    waiting = cands(s1=1, s2=2, s3=3)
    assert arrange(waiting, ["s3", "s2"]) == ["s3", "s2", "s1"]


def test_arrange_skips_a_placed_id_that_no_longer_waits() -> None:
    assert arrange(cands(s1=9, s2=2), ["s7", "s1"]) == ["s1", "s2"]


def test_arrange_with_no_placement_is_smallest_first() -> None:
    assert arrange(cands(s1=9, s2=2), []) == ["s2", "s1"]


def test_arrange_ignores_a_duplicate_placed_id() -> None:
    assert arrange(cands(s1=9, s2=2), ["s1", "s1"]) == ["s1", "s2"]


def test_a_candidate_and_a_placement_hold_their_fields() -> None:
    assert Candidate("s1", 3).size == 3
    placement = Placement(["s2"], "why")
    assert (placement.stories, placement.reason) == (["s2"], "why")


def test_the_refusal_texts_are_exact() -> None:
    assert lq.NO_STORIES == "list the ids of the stories waiting to land"
    assert lq.NOW_LANDING.format(id="s1") == (
        "s1 is landing now; order only the stories waiting behind it"
    )
    assert lq.NOT_WAITING.format(id="s1", ids="s2") == ("s1 is not waiting to land; waiting: s2")
    assert lq.ORDER_NEEDS_REASON.format(smallest="s2, s1") == (
        "this order departs from smallest first (s2, s1); give a reason"
    )

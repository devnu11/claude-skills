"""s180 C1 to C3, D1: the Move, its refusals, and carrying the moved commits (carry.py)."""

from __future__ import annotations

import pytest
from agile_team.git_ops import Git

from .fake_system import FAKE_REPO, Done, FakeSystem
from .late import Late

carry = Late("carry")
MERGE, BASE, HEAD = "m" * 40, "b" * 40, "h" * 40
PUSHED, TIP = "p" * 40, "t" * 40
SPAN = f"{BASE}..{HEAD}"
AFTER = f"{MERGE}..HEAD"


def git() -> Git:
    return Git(FAKE_REPO)


def move(**kw):
    return carry.Move(**{"merge": MERGE, "base": BASE, "head": HEAD, **kw})


def argvs(fake: FakeSystem) -> list[tuple[str, ...]]:
    return [tuple(c.argv) for c in fake.commands]


def issued(fake: FakeSystem, *words: str) -> list[tuple[str, ...]]:
    return [a for a in argvs(fake) if all(w in a for w in words)]


def passing(fake: FakeSystem) -> None:
    """A span of two plain commits, an ancestor base, and nothing else in the way."""
    fake.reply(("merge-base", "--is-ancestor"), Done(0))
    fake.reply(("rev-list", SPAN), Done(0, "c1\nc2\n"))
    fake.reply(("log", "--merges"), Done(0, ""))


# ---------- C1: the move ----------


def test_the_span_is_base_to_head_c1() -> None:
    assert move().span == SPAN


def test_a_move_is_unmoved_only_when_base_equals_head_c1() -> None:
    assert move(base=HEAD).is_unmoved is True
    assert move().is_unmoved is False
    assert move(base="").is_unmoved is False


def test_a_move_defaults_to_no_pushed_record_and_no_forks_c1() -> None:
    assert move().pushed == "" and move().forks == ()


# ---------- C2: when a move is carried ----------


def test_a_span_that_can_be_carried_has_no_refusal_c2(fake) -> None:
    passing(fake)
    assert carry.find_refusal(git(), move()) is None


def test_a_base_that_is_not_an_ancestor_of_the_head_is_refused_c2(fake) -> None:
    passing(fake)
    fake.reply(("merge-base", "--is-ancestor", BASE, HEAD), Done(1))
    assert carry.find_refusal(git(), move()) == carry.NOT_ABOVE


def test_an_empty_span_is_refused_c2(fake) -> None:
    passing(fake)
    fake.reply(("rev-list", SPAN), Done(0, ""))
    assert carry.find_refusal(git(), move()) == carry.NOT_ABOVE


def test_a_merge_in_the_span_is_refused_with_its_first_line_c2(fake) -> None:
    passing(fake)
    fake.reply(("log", "--merges"), Done(0, "abc1234 merge(s2): Two\nfed9876 merge(s3): Three\n"))
    assert carry.find_refusal(git(), move()) == carry.MERGED.format(line="abc1234 merge(s2): Two")


def test_a_pushed_commit_the_merge_lacks_is_refused_c2(fake) -> None:
    passing(fake)
    fake.reply(("merge-base", "--is-ancestor", PUSHED, MERGE), Done(1))
    assert carry.find_refusal(git(), move(pushed=PUSHED)) == carry.PUSHED.format(pushed=PUSHED[:12])


def test_a_pushed_commit_the_merge_has_is_not_refused_c2(fake) -> None:
    passing(fake)
    assert carry.find_refusal(git(), move(pushed=PUSHED)) is None
    assert issued(fake, "merge-base", "--is-ancestor", PUSHED, MERGE)


def test_an_empty_pushed_record_skips_the_pushed_check_c2(fake) -> None:
    passing(fake)
    carry.find_refusal(git(), move(pushed=""))
    assert issued(fake, "merge-base", "--is-ancestor", MERGE) == []


def test_a_story_forked_on_a_moved_commit_is_refused_c2(fake) -> None:
    passing(fake)
    fake.reply(("rev-list", SPAN), Done(0, f"c1\n{'f' * 40}\n"))
    forks = (("s7", "9" * 40), ("s9", "f" * 40))
    refused = carry.find_refusal(git(), move(forks=forks))
    assert refused == carry.FORKED.format(story="s9", sha="f" * 12)


def test_forks_outside_the_span_are_not_refused_c2(fake) -> None:
    passing(fake)
    assert carry.find_refusal(git(), move(forks=(("s7", "9" * 40),))) is None


def test_the_refusals_run_in_table_order_c2(fake) -> None:
    passing(fake)
    fake.reply(("log", "--merges"), Done(0, "abc1234 merge(s2): Two\n"))
    fake.reply(("rev-list", SPAN), Done(0, f"c1\n{'f' * 40}\n"))
    refused = carry.find_refusal(git(), move(forks=(("s9", "f" * 40),)))
    assert refused.startswith("a merge moved the sprint head")
    assert [f.__name__ for f in carry.REFUSALS] == [
        "find_not_above",
        "find_merge",
        "find_pushed",
        "find_fork",
    ]


def test_the_refusal_texts_are_exact_c2() -> None:
    assert carry.NOT_ABOVE == "the sprint head does not descend from the merge's first parent"
    assert carry.MERGED == "a merge moved the sprint head: {line}"
    assert carry.STOPPED == "carrying the moved commits stopped on a conflict in {files}"
    assert carry.UNEVEN == "carrying {old} moved commits made {new}"


# ---------- C3: carrying ----------


def scripted(fake: FakeSystem, old: str = "o1\no2\n", new: str = "n1\nn2\n") -> None:
    fake.reply(("rev-list", "--reverse", SPAN), Done(0, old))
    fake.reply(("rev-list", "--reverse", AFTER), Done(0, new))
    fake.reply(("rev-parse", "HEAD"), Done(0, TIP + "\n"))


def test_carrying_cherry_picks_the_span_and_pairs_old_with_new_c3(fake) -> None:
    scripted(fake)
    out = carry.carry_commits(git(), move())
    assert out == carry.Carried(tip=TIP, head=HEAD, moved={"o1": "n1", "o2": "n2"})
    [pick] = issued(fake, "cherry-pick")
    assert "--allow-empty" in pick and "--keep-redundant-commits" in pick
    assert pick[-1] == SPAN


def test_a_conflicting_cherry_pick_is_aborted_and_names_its_files_c3(fake) -> None:
    scripted(fake)
    fake.reply(("cherry-pick", "--allow-empty"), Done(1, "conflict"))
    fake.reply(("diff", "--name-only", "--diff-filter=U"), Done(0, "a.py\nb.py\n"))
    out = carry.carry_commits(git(), move())
    assert out == carry.STOPPED.format(files="a.py, b.py")
    assert issued(fake, "cherry-pick", "--abort")


def test_uneven_counts_are_refused_c3(fake) -> None:
    scripted(fake, old="o1\no2\n", new="n1\n")
    assert carry.carry_commits(git(), move()) == carry.UNEVEN.format(old=2, new=1)


def test_carried_defaults_to_no_moved_pairs_c3() -> None:
    assert carry.Carried(tip="t", head="h").moved == {}


# ---------- list_shas, list_moved (D1) ----------


def test_list_shas_returns_the_rev_list_lines_oldest_first_c3(fake) -> None:
    fake.reply(("rev-list", "--reverse", SPAN), Done(0, "a\nb\n"))
    assert carry.list_shas(git(), SPAN) == ["a", "b"]


def test_list_shas_is_empty_when_git_fails_c3(fake) -> None:
    fake.reply(("rev-list", "--reverse"), Done(128, "fatal"))
    assert carry.list_shas(git(), SPAN) == []


def test_list_moved_returns_short_sha_and_subject_oldest_first_d1(fake) -> None:
    fake.reply(("log", "--reverse"), Done(0, "abc1234 first\n\nfed9876 second\n"))
    assert carry.list_moved(git(), move()) == ["abc1234 first", "fed9876 second"]
    [log] = issued(fake, "log", "--reverse")
    assert carry.LINE_FORMAT in log and log[-1] == SPAN


def test_list_moved_is_empty_when_git_fails_d1(fake) -> None:
    fake.reply(("log", "--reverse"), Done(128, "fatal"))
    assert carry.list_moved(git(), move()) == []


@pytest.mark.parametrize("text", ["", "\n"])
def test_list_moved_is_empty_for_no_output_d1(fake, text) -> None:
    fake.reply(("log", "--reverse"), Done(0, text))
    assert carry.list_moved(git(), move()) == []

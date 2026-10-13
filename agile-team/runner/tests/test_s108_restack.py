"""s108: the Rebuilder's rebase tools, the Restacker (merged entries, fast plan), big-PR notes.

What git does with a rebase-merged range is proved on real repos in ``tests/e2e/``.
"""

import pytest
from agile_team import boundary as bd
from agile_team.boundary import StackEntry
from agile_team.config import UpstreamSettings
from agile_team.git_ops import Git
from agile_team.restack import FollowOutcome, Plan, Restacker
from agile_team.stack import Move, Rebuilder
from agile_team.upstream import Pr, PrState

from .fake_system import FAKE_ROOT, Done, FakeSystem
from .s29_helpers import FakePrs
from .test_stack import TARGET, WORKTREE, issued, lines

H1, H2, H3 = "1" * 40, "2" * 40, "3" * 40
N1, N2 = "a" * 40, "b" * 40


@pytest.fixture
def rb() -> Rebuilder:
    return Rebuilder(Git(FAKE_ROOT / "repo"), WORKTREE, TARGET)


def stacked(*heads: str) -> list[StackEntry]:
    return [
        StackEntry(9 + i, f"team/sprint-{9 + i}", "s" * 40, h, head=h, pr=i + 1)
        for i, h in enumerate(heads)
    ]


def same_tree(fake: FakeSystem, new: str, old: str, *, equal: bool = True) -> None:
    fake.reply(("rev-parse", f"{new}^{{tree}}"), Done(0, f"T\n{'T' if equal else 'U'}\n"))


# ----- texts and enums -------------------------------------------------------


def test_outcomes_and_follow_outcomes() -> None:
    assert bd.BoundaryOutcome.RESTACKED == "restacked"
    assert bd.BoundaryOutcome.REBUILD == "rebuild"
    assert [o.value for o in FollowOutcome] == ["none", "restacked", "rebuild", "rejected"]


def test_texts_are_exact() -> None:
    assert bd.REBASE_MERGE_LIMIT == 100
    assert bd.BIG_PR_NOTE == (
        "PR #{pr} ({branch}) has {commits} commits, more than the {limit} GitHub allows for "
        '"Rebase and merge". When it is the bottom of the stack, merge it by fast-forward: '
        "git fetch {remote} && git push {remote} {remote}/{branch}:{target}"
    )
    assert bd.RESTACKED_UPDATE == (
        "Merged into {target}: {merged}. The PRs above were rebased onto it with the same tree "
        "and pushed: {prs}. The bottom one is now based on {target}; nothing is called ready "
        "before CI passes."
    )
    assert bd.PUSHED_REPORT == (
        "Sprint {sprint}'s review branches are pushed: {prs}. The runner now waits for CI on "
        "every PR of the stack; nothing is called ready before CI passes on all of them."
    )


def test_restack_texts_are_exact() -> None:
    from agile_team import restack

    assert restack.REBASE_STOPPED == "{branch} did not rebase cleanly onto {onto}"
    assert restack.TREE_CHANGED == "{branch} rebased onto {onto} has a different tree"


def test_no_open_pr_why_no_longer_mentions_drafts() -> None:
    from agile_team import ci

    assert ci.NO_OPEN_PR_WHY == "no open pull request to watch"


def test_a_stack_entry_defaults_to_no_commits() -> None:
    assert StackEntry(1, "b", "s", "e").commits == 0


# ----- big_pr_notes (M12) ----------------------------------------------------


def test_exactly_100_commits_gives_no_note() -> None:
    [e] = stacked(H1)
    e.commits = 100
    assert bd.big_pr_notes([e], UpstreamSettings()) == []


def test_101_commits_gives_the_exact_fast_forward_line() -> None:
    [e] = stacked(H1)
    e.commits = 101
    assert bd.big_pr_notes([e], UpstreamSettings()) == [
        "PR #1 (team/sprint-9) has 101 commits, more than the 100 GitHub allows for "
        '"Rebase and merge". When it is the bottom of the stack, merge it by fast-forward: '
        "git fetch origin && git push origin origin/team/sprint-9:main"
    ]


def test_notes_come_in_stack_order_for_the_big_entries_only() -> None:
    a, b, c = stacked(H1, H2, H3)
    a.commits, b.commits, c.commits = 150, 3, 200
    notes = bd.big_pr_notes([a, b, c], UpstreamSettings(remote="up", branch="trunk"))
    assert [n.split(" ")[1] for n in notes] == ["#1", "#3"]
    assert notes[0].endswith("git fetch up && git push up up/team/sprint-9:trunk")


# ----- Rebuilder.rebase / same_tree / count / point --------------------------


def test_rebase_replays_the_range_onto_the_move_and_returns_the_new_head(
    rb: Rebuilder, fake: FakeSystem
) -> None:
    fake.reply(("git", "rev-parse", "HEAD"), lines(N1))
    assert rb.rebase(H2, Move(TARGET, H1)) == N1
    [checkout] = issued(fake, "checkout")
    assert checkout[-3:] == ("--detach", "--force", H2)
    [argv] = issued(fake, "--onto")
    assert argv[-3:] == ("--onto", TARGET, H1) and "rebase" in argv
    assert "--empty=drop" in argv and "--no-autostash" in argv


def test_a_stopped_rebase_is_aborted_and_gives_none(rb: Rebuilder, fake: FakeSystem) -> None:
    fake.reply(("git", "rebase"), Done(1, "CONFLICT"))
    assert rb.rebase(H2, Move(TARGET, H1)) is None
    assert issued(fake, "rebase", "--abort")


def test_same_tree_compares_the_two_tree_lines(rb: Rebuilder, fake: FakeSystem) -> None:
    same_tree(fake, N1, H1)
    assert rb.same_tree(N1, H1) is True
    [argv] = issued(fake, "rev-parse")
    assert argv[-2:] == (f"{N1}^{{tree}}", f"{H1}^{{tree}}")


def test_same_tree_is_false_when_the_trees_differ(rb: Rebuilder, fake: FakeSystem) -> None:
    same_tree(fake, N1, H1, equal=False)
    assert rb.same_tree(N1, H1) is False


def test_count_is_the_rev_list_count_of_the_range(rb: Rebuilder, fake: FakeSystem) -> None:
    fake.reply(("rev-list", "--count"), Done(0, "101\n"))
    assert rb.count(H1, H2) == 101
    [argv] = issued(fake, "rev-list", "--count")
    assert argv[-1] == f"{H1}..{H2}"


def test_point_moves_the_branch_and_the_entry_head(rb: Rebuilder, fake: FakeSystem) -> None:
    [e] = stacked(H1)
    rb.point(e, N1)
    [branch] = issued(fake, "branch")
    assert branch[-3:] == ("--force", "team/sprint-9", N1) and e.head == N1


# ----- Restacker.merged (M3) -------------------------------------------------


class CountingPrs(FakePrs):
    def find(self, branch: str) -> Pr | None:
        self.calls.append(("find", branch))
        return super().find(branch)


def prs_with(states: list[PrState], numbers: list[int] | None = None) -> CountingPrs:
    prs = CountingPrs()
    for i, state in enumerate(states):
        n = (numbers or [1, 2, 3])[i]
        prs.prs[f"team/sprint-{9 + i}"] = Pr(n, f"https://h/{n}", state, False, "main")
    return prs


def finds(prs: CountingPrs) -> int:
    return sum(1 for c in prs.calls if c[0] == "find")


def test_only_the_leading_merged_entries_are_followed(rb: Rebuilder) -> None:
    prs = prs_with([PrState.MERGED, PrState.OPEN, PrState.MERGED])
    entries = stacked(H1, H2, H3)
    assert Restacker(prs, rb).merged(entries) == [entries[0]]


def test_lookups_stop_at_the_first_entry_that_is_not_merged(rb: Rebuilder) -> None:
    prs = prs_with([PrState.MERGED, PrState.OPEN, PrState.MERGED])
    Restacker(prs, rb).merged(stacked(H1, H2, H3))
    assert finds(prs) == 2


def test_a_different_pr_number_is_not_merged(rb: Rebuilder) -> None:
    prs = prs_with([PrState.MERGED], [99])
    assert Restacker(prs, rb).merged(stacked(H1)) == []


def test_an_entry_without_a_pr_stops_the_scan(rb: Rebuilder) -> None:
    prs = prs_with([PrState.MERGED, PrState.MERGED])
    entries = stacked(H1, H2)
    entries[0].pr = None
    assert Restacker(prs, rb).merged(entries) == []
    assert finds(prs) == 0


def test_a_branch_with_no_pr_on_the_service_is_not_merged(rb: Rebuilder) -> None:
    assert Restacker(CountingPrs(), rb).merged(stacked(H1)) == []


def test_all_merged_entries_are_returned_bottom_first(rb: Rebuilder) -> None:
    prs = prs_with([PrState.MERGED, PrState.MERGED, PrState.OPEN])
    entries = stacked(H1, H2, H3)
    assert Restacker(prs, rb).merged(entries) == entries[:2]
    assert finds(prs) == 3


# ----- Restacker.plan (M6) ---------------------------------------------------


def test_an_empty_rest_gives_an_empty_plan(rb: Rebuilder, fake: FakeSystem) -> None:
    [top] = stacked(H1)
    assert Restacker(FakePrs(), rb).plan([], top) == Plan()
    assert issued(fake, "worktree", "add")  # prepare() ran first


def test_the_chain_is_rebased_bottom_first_each_onto_the_new_head_below(
    rb: Rebuilder, fake: FakeSystem
) -> None:
    top, a, b = stacked(H1, H2, H3)
    fake.reply(("git", "rev-parse", "HEAD"), lines(N1), lines(N2))
    same_tree(fake, N1, H2)
    same_tree(fake, N2, H3)
    plan = Restacker(FakePrs(), rb).plan([a, b], top)
    assert plan == Plan(heads=[N1, N2], refused="")
    first, second = issued(fake, "--onto")
    assert first[-3:] == ("--onto", TARGET, H1)
    assert second[-3:] == ("--onto", N1, H2)
    assert not issued(fake, "branch")  # no ref moved while planning


def test_a_stopped_rebase_refuses_the_whole_plan(rb: Rebuilder, fake: FakeSystem) -> None:
    top, a, b = stacked(H1, H2, H3)
    fake.reply(("git", "rebase"), Done(1, "CONFLICT"))
    plan = Restacker(FakePrs(), rb).plan([a, b], top)
    assert plan.heads == []
    assert plan.refused == f"team/sprint-10 did not rebase cleanly onto {TARGET}"
    assert len(issued(fake, "--onto")) == 1 and not issued(fake, "branch")


def test_a_changed_tree_refuses_the_plan_naming_the_target(rb: Rebuilder, fake: FakeSystem) -> None:
    top, a, b = stacked(H1, H2, H3)
    fake.reply(("git", "rev-parse", "HEAD"), lines(N1))
    same_tree(fake, N1, H2, equal=False)
    plan = Restacker(FakePrs(), rb).plan([a, b], top)
    assert plan.refused == f"team/sprint-10 rebased onto {TARGET} has a different tree"
    assert plan.heads == [] and len(issued(fake, "--onto")) == 1


def test_a_changed_tree_higher_up_names_the_new_head_below(rb: Rebuilder, fake: FakeSystem) -> None:
    top, a, b = stacked(H1, H2, H3)
    fake.reply(("git", "rev-parse", "HEAD"), lines(N1), lines(N2))
    same_tree(fake, N1, H2)
    same_tree(fake, N2, H3, equal=False)
    plan = Restacker(FakePrs(), rb).plan([a, b], top)
    assert plan.refused == f"team/sprint-11 rebased onto {N1[:12]} has a different tree"
    assert plan.heads == []


def test_a_stopped_rebase_higher_up_names_the_new_head_below(
    rb: Rebuilder, fake: FakeSystem
) -> None:
    top, a, b = stacked(H1, H2, H3)
    fake.reply(("git", "rev-parse", "HEAD"), lines(N1))
    same_tree(fake, N1, H2)
    fake.reply(("git", "rebase"), Done(0), Done(1, "CONFLICT"))
    plan = Restacker(FakePrs(), rb).plan([a, b], top)
    assert plan.refused == f"team/sprint-11 did not rebase cleanly onto {N1[:12]}"

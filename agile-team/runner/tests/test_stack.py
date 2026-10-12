"""s29 U8/U15/U16: the Rebuilder's git commands, on a scripted git.

What git does with them (cherry-pick onto a moved main, rerere replay, a rebase-merged
range) is proved on real repos in ``tests/e2e/``.
"""

from pathlib import Path

import pytest
from agile_team import stack, system
from agile_team.boundary import StackEntry
from agile_team.git_ops import Git, GitError
from agile_team.stack import Build, Conflict, Rebuilder

from .fake_system import FAKE_ROOT, Done, FakeSystem

TARGET = "origin/main"
WORKTREE = FAKE_ROOT / "wt"
START, MID, END = "a" * 40, "b" * 40, "c" * 40
S1 = ["1" * 40, "2" * 40]
S2 = ["3" * 40]
PICK_HEAD = ("git", "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD")


@pytest.fixture
def rb() -> Rebuilder:
    return Rebuilder(Git(FAKE_ROOT / "repo"), WORKTREE, TARGET)


def entries() -> list[StackEntry]:
    return [
        StackEntry(1, "team/sprint-1", START, MID),
        StackEntry(2, "team/sprint-2", MID, END),
    ]


def issued(fake: FakeSystem, *words: str) -> list[tuple[str, ...]]:
    """The argv of every command whose words contain ``words`` in order."""
    found = []
    for command in fake.commands:
        rest = iter(command.argv)
        if all(word in rest for word in words):
            found.append(tuple(command.argv))
    return found


def lines(*shas: str) -> Done:
    return Done(0, "".join(sha + "\n" for sha in shas))


def test_constants() -> None:
    assert stack.REVIEW_DIR == "review"
    for option in (
        "rerere.enabled=true",
        "rerere.autoUpdate=true",
        "core.editor=true",
        "core.hooksPath=/dev/null",
    ):
        assert option in stack.REVIEW_GIT


def test_unmerged_lists_the_commits_log_names(rb: Rebuilder, fake: FakeSystem) -> None:
    fake.reply(("git", "log", "--right-only"), lines(*S1, *S2))
    assert rb.unmerged(END) == {*S1, *S2}
    [argv] = issued(fake, "log", "--right-only")
    assert argv[-1] == f"{TARGET}...{END}" and "--cherry-pick" in argv and "--no-merges" in argv


def test_unmerged_is_empty_when_everything_landed(rb: Rebuilder, fake: FakeSystem) -> None:
    fake.reply(("git", "log", "--right-only"), Done(0, ""))
    assert rb.unmerged(END) == set()


def test_picks_are_the_range_in_order(rb: Rebuilder, fake: FakeSystem) -> None:
    e1, _ = entries()
    fake.reply(("git", "rev-list"), lines(*S1))
    assert rb.picks(e1, {*S1, *S2}) == S1
    [argv] = issued(fake, "rev-list")
    assert argv[-1] == f"{START}..{MID}" and "--reverse" in argv and "--no-merges" in argv


def test_picks_skip_commits_already_in_the_target(rb: Rebuilder, fake: FakeSystem) -> None:
    e1, _ = entries()
    fake.reply(("git", "rev-list"), lines(*S1))
    assert rb.picks(e1, {S1[1]}) == [S1[1]]


def test_picks_empty_after_a_rebase_merge(rb: Rebuilder, fake: FakeSystem) -> None:
    e1, _ = entries()
    fake.reply(("git", "rev-list"), lines(*S1))
    assert rb.picks(e1, set()) == []


def test_prepare_makes_a_detached_worktree_when_missing(rb: Rebuilder, fake: FakeSystem) -> None:
    rb.prepare()
    assert issued(fake, "worktree", "prune")
    [add] = issued(fake, "worktree", "add")
    assert add[-3:] == ("--detach", str(WORKTREE), TARGET)
    assert not issued(fake, "clean")


def test_prepare_resets_an_existing_worktree(rb: Rebuilder, fake: FakeSystem) -> None:
    fake.put(WORKTREE / ".git", "gitdir: x")
    rb.prepare()
    assert not issued(fake, "worktree", "add")
    assert issued(fake, "cherry-pick", "--abort")
    [checkout] = issued(fake, "checkout")
    assert checkout[-3:] == ("--detach", "--force", TARGET)
    assert issued(fake, "clean", "-fd")


def test_prepare_survives_a_pruned_worktree(rb: Rebuilder, fake: FakeSystem) -> None:
    fake.put(WORKTREE / ".git", "gitdir: x")
    rb.prepare()
    system.remove_tree(WORKTREE)
    rb.prepare()
    assert len(issued(fake, "worktree", "add")) == 1


def test_build_checks_out_the_base_and_picks_the_commits(rb: Rebuilder, fake: FakeSystem) -> None:
    fake.reply(("git", "rev-parse", "HEAD"), Done(0, "d" * 40 + "\n"))
    e1, _ = entries()
    assert rb.build(e1, Build(TARGET, S1)) is None
    [checkout] = issued(fake, "checkout")
    assert checkout[-3:] == ("--detach", "--force", TARGET)
    [pick] = issued(fake, "cherry-pick")
    assert pick[-2:] == tuple(S1)
    [branch] = issued(fake, "branch")
    assert branch[-3:] == ("--force", "team/sprint-1", "HEAD")
    assert e1.head == "d" * 40


def test_build_stacks_each_sprint_on_the_one_below(rb: Rebuilder, fake: FakeSystem) -> None:
    fake.reply(("git", "rev-parse", "HEAD"), lines("e" * 40), lines("f" * 40))
    e1, e2 = entries()
    rb.build(e1, Build(TARGET, S1))
    rb.build(e2, Build(e1.head, S2))
    bases = [argv[-1] for argv in issued(fake, "checkout")]
    assert bases == [TARGET, "e" * 40] and (e1.head, e2.head) == ("e" * 40, "f" * 40)


def test_all_picks_empty_leaves_head_equal_to_base(rb: Rebuilder, fake: FakeSystem) -> None:
    fake.reply(("git", "rev-parse", "HEAD"), lines("9" * 40))
    e1, _ = entries()
    assert rb.build(e1, Build(TARGET, [])) is None
    assert e1.head == "9" * 40 and not issued(fake, "cherry-pick")


def test_an_empty_pick_is_skipped(rb: Rebuilder, fake: FakeSystem) -> None:
    fake.reply(("git", "cherry-pick"), Done(1, "empty"), Done(0, ""))
    fake.reply(PICK_HEAD, Done(0, S1[0] + "\n"))
    fake.reply(("git", "diff", "--name-only"), Done(0, ""))
    fake.reply(("git", "diff", "--cached", "--quiet"), Done(0))
    e1, _ = entries()
    assert rb.build(e1, Build(TARGET, S1)) is None
    assert issued(fake, "cherry-pick", "--skip")


def test_a_pick_with_staged_changes_is_continued(rb: Rebuilder, fake: FakeSystem) -> None:
    fake.reply(("git", "cherry-pick"), Done(1, "stopped"), Done(0, ""))
    fake.reply(PICK_HEAD, Done(0, S1[0] + "\n"))
    fake.reply(("git", "diff", "--name-only"), Done(0, ""))
    fake.reply(("git", "diff", "--cached", "--quiet"), Done(1))
    e1, _ = entries()
    assert rb.build(e1, Build(TARGET, S1)) is None
    assert issued(fake, "cherry-pick", "--continue")


def test_conflict_reports_branch_commit_subject_and_files(rb: Rebuilder, fake: FakeSystem) -> None:
    fake.reply(("git", "cherry-pick"), Done(1, "CONFLICT in base.txt"))
    fake.reply(PICK_HEAD, Done(0, MID + "\n"))
    fake.reply(("git", "diff", "--name-only"), Done(0, "base.txt\n"))
    fake.reply(("git", "log", "-1"), Done(0, "feat: mine\n"))
    entry = StackEntry(3, "team/sprint-3", END, MID)
    conflict = rb.build(entry, Build(TARGET, [MID]))
    assert isinstance(conflict, Conflict)
    assert (conflict.branch, conflict.commit, conflict.subject) == (
        "team/sprint-3",
        MID,
        "feat: mine",
    )
    assert conflict.files == ("base.txt",) and "CONFLICT" in conflict.output
    assert not issued(fake, "branch")  # the pick is left in progress, no branch made


def test_record_stages_learns_and_aborts_the_pick(rb: Rebuilder, fake: FakeSystem) -> None:
    rb.record(["base.txt"])
    [add] = issued(fake, "add")
    assert add[-3:] == ("--", "base.txt") or add[-2:] == ("--", "base.txt")
    assert issued(fake, "rerere")
    assert issued(fake, "cherry-pick", "--abort")


def test_checkout_detaches_the_worktree_and_cleans_it(rb: Rebuilder, fake: FakeSystem) -> None:
    rb.checkout("team/sprint-1")
    [checkout] = issued(fake, "checkout")
    assert checkout[-3:] == ("--detach", "--force", "team/sprint-1")
    assert issued(fake, "clean", "-fd")


def test_every_worktree_command_carries_the_review_options(rb: Rebuilder, fake: FakeSystem) -> None:
    rb.checkout(TARGET)
    [checkout] = issued(fake, "checkout")
    assert checkout[1 : 1 + len(stack.REVIEW_GIT)] == stack.REVIEW_GIT


def test_cherry_pick_without_a_pick_in_progress_is_a_git_error(
    rb: Rebuilder, fake: FakeSystem
) -> None:
    fake.reply(("git", "cherry-pick"), Done(1, "bad revision"))
    fake.reply(PICK_HEAD, Done(1))
    with pytest.raises(GitError):
        rb.build(entries()[0], Build(TARGET, ["0" * 40]))


def test_a_pick_that_never_settles_is_a_git_error(rb: Rebuilder, fake: FakeSystem) -> None:
    fake.reply(("git", "cherry-pick"), Done(1, "loop"))
    fake.reply(PICK_HEAD, Done(0, S1[0] + "\n"))
    fake.reply(("git", "diff", "--name-only"), Done(0, ""))
    fake.reply(("git", "diff", "--cached", "--quiet"), Done(0))
    with pytest.raises(GitError):
        rb.build(entries()[0], Build(TARGET, S1))


def test_the_worktree_path_is_not_in_the_repo(rb: Rebuilder) -> None:
    assert Path(rb.worktree) == WORKTREE and rb.target == TARGET

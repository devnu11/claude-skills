"""s59 R1/R3/R4/R7: ``Upstream.rebase_onto`` on a scripted git (real git is in e2e)."""

import pytest
from agile_team import upstream as up
from agile_team.config import UpstreamSettings
from agile_team.git_ops import Git, GitError
from agile_team.rewrite import Stamped
from agile_team.upstream import Rebase, SyncOutcome, Upstream, UpstreamError

from .fake_system import FAKE_REPO, Done, FakeSystem

OLD, START, NEW = "a" * 40, "b" * 40, "c" * 40
BASE, TARGET_SHA, FAILED = "d" * 40, "e" * 40, "f" * 40
NO_RENAMES = ("git", "diff", "--name-only", "--no-renames")
REBASE = ("git", "rebase", "--no-verify")


def upstream_for(**kw) -> Upstream:
    return Upstream(Git(FAKE_REPO), UpstreamSettings(**kw))


def record(sha: str, message: str) -> str:
    return f"{sha}\x1fAda\x1fada@example.com\x1f100 +0000\x1f{message}\x1e\n"


def argvs(fake: FakeSystem) -> list[tuple[str, ...]]:
    return [tuple(c.argv) for c in fake.commands]


def seen(fake: FakeSystem, *words: str) -> list[int]:
    """Positions in the command log of the commands holding ``words`` in order."""
    found = []
    for at, argv in enumerate(argvs(fake)):
        rest = iter(argv)
        if all(word in rest for word in words):
            found.append(at)
    return found


def rebased(fake: FakeSystem, head_after: str = NEW) -> None:
    """Script a clean rebase: HEAD is START before the command and ``head_after`` after."""
    fake.reply(("git", "rev-parse", "HEAD"), Done(0, START + "\n"), Done(0, head_after + "\n"))
    fake.reply(("git", "rev-parse", "origin/main"), Done(0, TARGET_SHA + "\n"))
    fake.reply(("git", "merge-base"), Done(0, BASE + "\n"))


def test_the_rebase_argv_is_the_constant_plus_the_target() -> None:
    assert up.REBASE_ARGV == (
        "-c",
        "rebase.updateRefs=false",
        "-c",
        "rebase.rebaseMerges=false",
        "rebase",
        "--no-verify",
        "--no-autostash",
        "--no-autosquash",
        "--empty=drop",
    )
    assert "--reapply-cherry-picks" not in up.REBASE_ARGV


def test_rebase_onto_issues_the_argv_and_never_merges(fake: FakeSystem) -> None:
    rebased(fake)
    upstream_for().rebase_onto(OLD)
    [command] = [a for a in argvs(fake) if "rebase" in a]
    assert command[-len(up.REBASE_ARGV) - 1 :] == (*up.REBASE_ARGV, "origin/main")
    for argv in argvs(fake):
        assert "merge" not in argv and "-s" not in argv and "-X" not in argv
        assert not any("ours" in word for word in argv)


def test_rebase_onto_is_current_when_head_is_still_old(fake: FakeSystem) -> None:
    fake.reply(("git", "rev-parse", "HEAD"), Done(0, OLD + "\n"))
    fake.reply(("git", "rev-parse", "origin/main"), Done(0, TARGET_SHA + "\n"))
    result = upstream_for().rebase_onto(OLD)
    assert result.outcome is SyncOutcome.CURRENT
    assert dict(result.moved) == {} and not result.sha


def test_rebase_onto_rebased_reports_the_new_head_and_the_pairing(fake: FakeSystem) -> None:
    rebased(fake)
    fake.reply(
        ("git", "log", "--reverse", f"origin/main..{OLD}"),
        Done(0, record("o1", "one") + record("o2", "two")),
    )
    fake.reply(
        ("git", "log", "--reverse", "origin/main..HEAD"),
        Done(0, record("n1", "one") + record("n2", "two")),
    )
    result = upstream_for().rebase_onto(OLD)
    assert result.outcome is SyncOutcome.REBASED and result.sha == NEW
    assert dict(result.moved) == {"o1": "n1", "o2": "n2"}


def test_a_hand_rebase_is_rebased_although_the_command_changed_nothing(
    fake: FakeSystem,
) -> None:
    fake.reply(("git", "rev-parse", "HEAD"), Done(0, NEW + "\n"))
    fake.reply(("git", "rev-parse", "origin/main"), Done(0, TARGET_SHA + "\n"))
    fake.reply(("git", "merge-base"), Done(0, BASE + "\n"))
    result = upstream_for().rebase_onto(OLD)
    assert result.outcome is SyncOutcome.REBASED and result.sha == NEW


def test_listing_reads_the_commits_of_a_span_with_their_stamps(fake: FakeSystem) -> None:
    fake.reply(("git", "log"), Done(0, record("o1", "one")))
    [commit] = upstream_for().listing("origin/main..HEAD")
    assert isinstance(commit, Stamped) and commit.sha == "o1"
    [argv] = [a for a in argvs(fake) if a[1] == "log"]
    assert argv[-1] == "origin/main..HEAD"
    assert "--reverse" in argv and "--topo-order" in argv and "--date=raw" in argv
    assert f"--format={up.STAMP_FORMAT}" in argv


def test_the_stamp_format_names_sha_author_date_and_message() -> None:
    assert up.STAMP_FORMAT == "%H%x1f%an%x1f%ae%x1f%ad%x1f%B%x1e"


# ----- R4 conflict -----------------------------------------------------------


def conflict(fake: FakeSystem, names: str = "a/x.py\nb.py\n") -> None:
    fake.reply(("git", "rev-parse", "HEAD"), Done(0, START + "\n"))
    fake.reply(("git", "rev-parse", "origin/main"), Done(0, TARGET_SHA + "\n"))
    fake.reply(REBASE, Done(1, "CONFLICT (content)"))
    fake.reply(("git", "diff", "--name-only", "--diff-filter=U"), Done(0, names))
    fake.reply(("git", "rev-parse", "REBASE_HEAD"), Done(0, FAILED + "\n"))
    fake.reply(("git", "log", "-1", "--format=%s"), Done(0, "fix the thing\n"))


def test_a_conflict_lists_the_files_the_commit_and_aborts(fake: FakeSystem) -> None:
    conflict(fake)
    result = upstream_for().rebase_onto(OLD)
    assert result.outcome is SyncOutcome.CONFLICT
    assert list(result.files) == ["a/x.py", "b.py"]
    assert result.commit == FAILED and result.subject == "fix the thing"
    assert "CONFLICT" in result.output


def test_a_conflict_reads_the_failed_commit_before_it_aborts(fake: FakeSystem) -> None:
    conflict(fake)
    upstream_for().rebase_onto(OLD)
    [abort] = seen(fake, "git", "rebase", "--abort")
    assert seen(fake, "git", "rev-parse", "REBASE_HEAD")[0] < abort
    assert seen(fake, "git", "diff", "--diff-filter=U")[0] < abort


def test_a_conflict_checks_nothing_and_resets_nothing(fake: FakeSystem) -> None:
    conflict(fake)
    upstream_for().rebase_onto(OLD)
    assert not seen(fake, "git", "reset")
    assert not seen(fake, *NO_RENAMES)


def test_a_failure_without_conflicted_files_is_a_git_error(fake: FakeSystem) -> None:
    conflict(fake, names="")
    fake.reply(REBASE, Done(128, "fatal: cannot rebase: You have unstaged changes."))
    with pytest.raises(GitError, match="unstaged changes"):
        upstream_for().rebase_onto(OLD)


# ----- R7 no content lost ----------------------------------------------------


def test_a_path_only_the_team_touched_but_changed_is_lost(fake: FakeSystem) -> None:
    rebased(fake)
    fake.reply((*NO_RENAMES, BASE, "origin/main"), Done(0, ""))
    fake.reply((*NO_RENAMES, BASE, OLD), Done(0, "mine.py\n"))
    fake.reply((*NO_RENAMES, OLD, "HEAD"), Done(0, "mine.py\n"))
    with pytest.raises(UpstreamError, match=r"touched: mine\.py"):
        upstream_for().rebase_onto(OLD)
    [reset] = [a for a in argvs(fake) if "reset" in a]
    assert reset[-3:] == ("reset", "--hard", START)


def test_a_path_only_upstream_touched_but_changed_is_lost(fake: FakeSystem) -> None:
    rebased(fake)
    fake.reply((*NO_RENAMES, BASE, "origin/main"), Done(0, "theirs.py\n"))
    fake.reply((*NO_RENAMES, BASE, OLD), Done(0, ""))
    fake.reply((*NO_RENAMES, "origin/main", "HEAD"), Done(0, "theirs.py\n"))
    with pytest.raises(UpstreamError, match=r"theirs\.py"):
        upstream_for().rebase_onto(OLD)
    assert seen(fake, "git", "reset", "--hard", START)


def test_the_lost_text_names_the_branch_the_target_and_the_paths(fake: FakeSystem) -> None:
    text = up.SYNC_LOST.format(team="agile-team", target="origin/main", paths="a.py, b.py")
    assert text == (
        "rebasing agile-team onto origin/main changed paths only one side touched: "
        "a.py, b.py; the team branch is back where it was"
    )


def test_paths_both_sides_touched_are_trusted_to_git(fake: FakeSystem) -> None:
    rebased(fake)
    fake.reply((*NO_RENAMES, BASE, "origin/main"), Done(0, "both.py\n"))
    fake.reply((*NO_RENAMES, BASE, OLD), Done(0, "both.py\n"))
    fake.reply((*NO_RENAMES, OLD, "HEAD"), Done(0, "both.py\n"))
    fake.reply((*NO_RENAMES, "origin/main", "HEAD"), Done(0, "both.py\n"))
    assert upstream_for().rebase_onto(OLD).outcome is SyncOutcome.REBASED
    assert not seen(fake, "git", "reset")


def test_the_check_does_not_run_when_nothing_changed(fake: FakeSystem) -> None:
    fake.reply(("git", "rev-parse", "HEAD"), Done(0, OLD + "\n"))
    upstream_for().rebase_onto(OLD)
    assert not seen(fake, *NO_RENAMES)


def test_the_push_refuses_the_team_branch(fake: FakeSystem) -> None:
    fake.reply(("git", "symbolic-ref"), Done(0, "agile-team\n"))
    with pytest.raises(UpstreamError, match="refusing to push agile-team"):
        upstream_for().push(up.Lease("agile-team", OLD, NEW))
    assert not seen(fake, "git", "push")


def test_a_rebase_result_moves_nothing_by_default() -> None:
    assert Rebase(SyncOutcome.CURRENT).moved == {}

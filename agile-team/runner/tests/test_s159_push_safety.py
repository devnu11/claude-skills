"""s159 P2/P5/B7: every push is a fast-forward or a creation; delete is for landing branches."""

import pytest
from agile_team import upstream as up
from agile_team.config import UpstreamSettings
from agile_team.git_ops import Git
from agile_team.upstream import Lease, Upstream, UpstreamError

from .fake_system import FAKE_REPO, Done, FakeSystem

OLD, NEW = "a" * 40, "b" * 40


def upstream_for(**kw) -> Upstream:
    return Upstream(Git(FAKE_REPO), UpstreamSettings(**kw))


def issued(fake: FakeSystem, *words: str) -> list[tuple[str, ...]]:
    found = []
    for command in fake.commands:
        rest = iter(command.argv)
        if all(word in rest for word in words):
            found.append(tuple(command.argv))
    return found


def on_team(fake: FakeSystem) -> None:
    fake.reply(("git", "symbolic-ref"), Done(0, "agile-team\n"))


def test_a_non_descendant_expectation_is_refused_and_nothing_is_sent_r1(fake: FakeSystem) -> None:
    on_team(fake)
    fake.reply(("git", "merge-base", "--is-ancestor"), Done(1))
    out = upstream_for().push(Lease("team/sprint-1", OLD, NEW))
    assert out == up.NOT_FAST_FORWARD.format(sha=NEW, branch="team/sprint-1", expect=OLD)
    assert not issued(fake, "push")


def test_a_descendant_pushes_with_its_expected_sha_r1(fake: FakeSystem) -> None:
    on_team(fake)
    fake.reply(("git", "merge-base", "--is-ancestor"), Done(0))
    assert upstream_for().push(Lease("team/sprint-1", OLD, NEW)) is None
    [check] = issued(fake, "merge-base", "--is-ancestor")
    assert check[-2:] == (OLD, NEW)
    [argv] = issued(fake, "push")
    assert f"--force-with-lease=refs/heads/team/sprint-1:{OLD}" in argv
    assert "--force" not in argv and "--force-with-lease" not in argv


def test_a_creation_skips_the_ancestor_check_r1(fake: FakeSystem) -> None:
    on_team(fake)
    assert upstream_for().push(Lease("team/sprint-1", "", NEW)) is None
    assert not issued(fake, "merge-base", "--is-ancestor")
    assert issued(fake, "push")


def test_is_ancestor_reads_the_exit_code_r1(fake: FakeSystem) -> None:
    fake.reply(("git", "merge-base", "--is-ancestor"), Done(1))
    assert upstream_for().is_ancestor(OLD, NEW) is False
    fake.reply(("git", "merge-base", "--is-ancestor"), Done(0))
    assert upstream_for().is_ancestor(OLD, NEW) is True


@pytest.mark.parametrize("branch", ["team/story-s1", "team/story-s1-r2", "team/sprint-3-r1"])
def test_the_guard_accepts_either_prefix_r1(fake: FakeSystem, branch: str) -> None:
    on_team(fake)
    assert upstream_for().push(Lease(branch, "", NEW)) is None


@pytest.mark.parametrize("branch", ["main", "agile-team", "feature/x"])
def test_the_guard_still_refuses_main_team_and_others_r1(fake: FakeSystem, branch: str) -> None:
    on_team(fake)
    with pytest.raises(UpstreamError, match="refusing to push"):
        upstream_for().push(Lease(branch, "", NEW))
    assert not issued(fake, "push")


def test_the_refusal_names_both_prefixes_r1(fake: FakeSystem) -> None:
    on_team(fake)
    with pytest.raises(UpstreamError) as raised:
        upstream_for().push(Lease("main", "", NEW))
    assert "team/sprint-*" in str(raised.value) and "team/story-*" in str(raised.value)


def test_delete_sends_the_leased_delete_r1(fake: FakeSystem) -> None:
    on_team(fake)
    assert upstream_for().delete(Lease("team/story-s1-land", NEW, "")) is None
    [argv] = issued(fake, "push")
    assert f"--force-with-lease=refs/heads/team/story-s1-land:{NEW}" in argv
    assert argv[-1] == ":refs/heads/team/story-s1-land"
    assert not issued(fake, "merge-base", "--is-ancestor")


@pytest.mark.parametrize(
    "branch", ["team/story-s1", "team/sprint-1", "main", "team/story-s1-r1", "other-land"]
)
def test_delete_refuses_anything_but_a_landing_branch_r1(fake: FakeSystem, branch: str) -> None:
    on_team(fake)
    out = upstream_for().delete(Lease(branch, NEW, ""))
    assert out == up.REFUSED_DELETE.format(branch=branch, story_prefix="team/story-")
    assert not issued(fake, "push")


def test_remote_head_reads_ls_remote_r1(fake: FakeSystem) -> None:
    fake.reply(("git", "ls-remote"), Done(0, f"{NEW}\trefs/heads/team/sprint-1\n"))
    assert upstream_for().read_remote_head("team/sprint-1") == NEW


def test_remote_head_of_an_absent_branch_is_empty_r1(fake: FakeSystem) -> None:
    fake.reply(("git", "ls-remote"), Done(0, ""))
    assert upstream_for().read_remote_head("team/sprint-1") == ""


def test_fast_forward_is_a_ff_only_merge_r1(fake: FakeSystem) -> None:
    assert upstream_for().advance_to(NEW) is True
    [argv] = issued(fake, "merge", "--ff-only")
    assert argv[-1] == NEW
    fake.reply(("git", "merge", "--ff-only"), Done(128, "", "fatal: Not possible"))
    assert upstream_for().advance_to(NEW) is False


def test_no_prs_refuses_close_and_sha_checks_r1() -> None:
    prs = up.NoPrs("no gh")
    with pytest.raises(UpstreamError, match="no gh"):
        prs.close(3, "note")
    with pytest.raises(UpstreamError, match="no gh"):
        prs.list_checks(NEW)


def test_gh_close_comments_on_the_pr_r1() -> None:
    calls: list[list[str]] = []

    def run(argv: list[str]) -> tuple[int, str]:
        calls.append(argv)
        return 0, ""

    up.GhPrs(run).close(7, "Landed on x as y.")
    [argv] = calls
    assert argv[:3] == ["gh", "pr", "close"] and "7" in argv
    assert argv[argv.index("--comment") + 1] == "Landed on x as y."

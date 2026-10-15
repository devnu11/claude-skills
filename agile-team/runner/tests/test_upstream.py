"""s29 U4/U5/U17/U19/U24: Upstream on a scripted git, GhPrs over a fake Exec."""

import pytest
from agile_team import upstream as up
from agile_team.config import UpstreamSettings
from agile_team.git_ops import Git
from agile_team.upstream import (
    GhPrs,
    Lease,
    NoPrs,
    Pr,
    PrMode,
    PrSpec,
    PrState,
    Upstream,
    UpstreamError,
)

from .fake_system import FAKE_REPO, Done, FakeSystem

OLD, NEW = "a" * 40, "b" * 40


def upstream_for(**kw) -> Upstream:
    return Upstream(Git(FAKE_REPO), UpstreamSettings(**kw))


def issued(fake: FakeSystem, *words: str) -> list[tuple[str, ...]]:
    """The argv of every command whose words contain ``words`` in order."""
    found = []
    for command in fake.commands:
        rest = iter(command.argv)
        if all(word in rest for word in words):
            found.append(tuple(command.argv))
    return found


def test_target() -> None:
    assert upstream_for().target == "origin/main"
    assert upstream_for(remote="up", branch="dev").target == "up/dev"


def test_missing_none_when_everything_is_there(fake: FakeSystem) -> None:
    assert upstream_for().missing() is None
    assert issued(fake, "fetch", "--prune", "origin")


def test_missing_sync_off(fake: FakeSystem) -> None:
    assert upstream_for(remote="").missing() == "[upstream] remote is empty"
    assert fake.commands == []


def test_missing_no_remote(fake: FakeSystem) -> None:
    fake.reply(("git", "remote", "get-url"), Done(2))
    assert upstream_for().missing() == "no remote 'origin'"
    assert not issued(fake, "fetch")


def test_missing_fetch_failed(fake: FakeSystem) -> None:
    fake.reply(("git", "fetch"), Done(128, "", "fatal: 'gone.git' does not appear to be a repo"))
    reason = upstream_for().missing()
    assert reason == "git fetch origin failed: fatal: 'gone.git' does not appear to be a repo"


def test_missing_no_target(fake: FakeSystem) -> None:
    fake.reply(("git", "rev-parse", "--verify"), Done(1))
    assert upstream_for(branch="nope").missing() == "origin/nope does not exist"
    [verify] = issued(fake, "rev-parse", "--verify")
    assert verify[-1] == "origin/nope"


def test_team_branch_and_detached(fake: FakeSystem) -> None:
    fake.reply(("git", "symbolic-ref"), Done(0, "agile-team\n"))
    assert upstream_for().team_branch() == "agile-team"
    fake.reply(("git", "symbolic-ref"), Done(1))
    with pytest.raises(UpstreamError, match="detached HEAD; check out the team branch"):
        upstream_for().team_branch()


def test_merge_base(fake: FakeSystem) -> None:
    fake.reply(("git", "merge-base"), Done(0, OLD + "\n"))
    assert upstream_for().merge_base() == OLD
    [argv] = issued(fake, "merge-base")
    assert argv[-2:] == ("HEAD", "origin/main")


def test_push_sends_the_sha_with_its_lease(fake: FakeSystem) -> None:
    fake.reply(("git", "symbolic-ref"), Done(0, "agile-team\n"))
    assert upstream_for().push(Lease("team/sprint-1", OLD, NEW)) is None
    [argv] = issued(fake, "push")
    ref = "refs/heads/team/sprint-1"
    assert f"--force-with-lease={ref}:{OLD}" in argv and "--no-verify" in argv
    assert argv[-2:] == ("origin", f"{NEW}:{ref}")


def test_push_with_an_empty_expectation_leases_the_absent_branch(fake: FakeSystem) -> None:
    fake.reply(("git", "symbolic-ref"), Done(0, "agile-team\n"))
    assert upstream_for().push(Lease("team/sprint-1", "", NEW)) is None
    [argv] = issued(fake, "push")
    assert "--force-with-lease=refs/heads/team/sprint-1:" in argv


def test_a_rejected_push_returns_gits_output(fake: FakeSystem) -> None:
    fake.reply(("git", "symbolic-ref"), Done(0, "agile-team\n"))
    fake.reply(("git", "push"), Done(1, "! [rejected] (stale info)"))
    out = upstream_for().push(Lease("team/sprint-1", OLD, NEW))
    assert out == "! [rejected] (stale info)"


@pytest.mark.parametrize("branch", ["main", "agile-team", "feature/x", "teamsprint-1"])
def test_push_refuses_main_team_and_unprefixed_branches(fake: FakeSystem, branch: str) -> None:
    fake.reply(("git", "symbolic-ref"), Done(0, "agile-team\n"))
    with pytest.raises(UpstreamError, match="refusing to push"):
        upstream_for().push(Lease(branch, "", NEW))
    assert not issued(fake, "push")


def test_count_is_the_commits_from_the_target_to_the_head(fake: FakeSystem) -> None:
    fake.reply(("rev-list", "--count"), Done(0, "5\n"))
    assert upstream_for().count(NEW) == 5
    [argv] = issued(fake, "rev-list")
    assert argv[-1] == f"origin/main..{NEW}" and "--count" in argv


def test_refused_push_text() -> None:
    assert up.REFUSED_PUSH.format(branch="main", prefix="team/sprint-") == (
        "refusing to push main: only review branches (team/sprint-*) are pushed"
    )


# ----- Prs ------------------------------------------------------------------


def test_no_prs() -> None:
    p = NoPrs()
    assert p.missing() == "no pull request service is configured"
    assert NoPrs("why").missing() == "why"
    spec = PrSpec("b", "main", "t", "body", PrMode.READY)
    for call in (
        lambda: p.find("b"),
        lambda: p.create(spec),
        lambda: p.edit(Pr(1, "u", PrState.OPEN, False, "main"), spec),
    ):
        with pytest.raises(UpstreamError):
            call()


class FakeExec:
    def __init__(self, results: dict[tuple, tuple[int, str]] | None = None):
        self.results = results or {}
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str]) -> tuple[int, str]:
        self.calls.append(argv)
        return self.results.get(tuple(argv), (0, ""))


def test_gh_missing() -> None:
    assert GhPrs(FakeExec()).missing() is None
    assert up.NO_GH == "gh is not installed" and up.GH_LOGGED_OUT == "gh is not logged in"
    assert GhPrs(FakeExec({("gh", "--version"): (127, "")})).missing() == "gh is not installed"
    ex = FakeExec({("gh", "auth", "status"): (1, "")})
    assert GhPrs(ex).missing() == "gh is not logged in"
    assert ex.calls == [["gh", "--version"], ["gh", "auth", "status"]]


FIND = [
    "gh",
    "pr",
    "list",
    "--head",
    "team/sprint-1",
    "--state",
    "all",
    "--json",
    "number,url,state,isDraft,baseRefName",
    "--limit",
    "1",
]


def test_gh_find() -> None:
    body = '[{"number": 7, "url": "https://h/o/r/pull/7", "state": "OPEN", "isDraft": true, "baseRefName": "main"}]'  # noqa: E501
    ex = FakeExec({tuple(FIND): (0, body)})
    assert GhPrs(ex).find("team/sprint-1") == Pr(
        7, "https://h/o/r/pull/7", PrState.OPEN, True, "main"
    )
    assert ex.calls == [FIND]
    assert GhPrs(FakeExec({tuple(FIND): (0, "[]")})).find("team/sprint-1") is None
    with pytest.raises(UpstreamError, match="nope"):
        GhPrs(FakeExec({tuple(FIND): (1, "nope")})).find("team/sprint-1")


def test_pr_state_values() -> None:
    assert [s.value for s in PrState] == ["OPEN", "CLOSED", "MERGED"]
    assert {m.value for m in PrMode} == {"none", "draft", "ready", "closed"}


def spec(mode: PrMode, base: str = "main") -> PrSpec:
    return PrSpec("team/sprint-1", base, "Sprint 1: g", "the body", mode)


def test_gh_create_ready_and_draft_parse_the_number_from_the_url() -> None:
    base = [
        "gh",
        "pr",
        "create",
        "--head",
        "team/sprint-1",
        "--base",
        "main",
        "--title",
        "Sprint 1: g",
        "--body",
        "the body",
    ]
    out = "Creating pull request\nhttps://github.com/o/r/pull/12\n"
    ex = FakeExec({tuple(base): (0, out), tuple([*base, "--draft"]): (0, out)})
    pr = GhPrs(ex).create(spec(PrMode.READY))
    assert pr == Pr(12, "https://github.com/o/r/pull/12", PrState.OPEN, False, "main")
    draft = GhPrs(ex).create(spec(PrMode.DRAFT))
    assert draft.draft is True and ex.calls == [base, [*base, "--draft"]]


def test_gh_create_failure() -> None:
    bad = GhPrs(lambda argv: (1, "denied"))
    with pytest.raises(UpstreamError, match="denied"):
        bad.create(spec(PrMode.READY))


def test_gh_edit_changes_only_what_differs() -> None:
    ex = FakeExec()
    gh = GhPrs(ex)
    gh.edit(Pr(5, "u", PrState.OPEN, False, "main"), spec(PrMode.READY))
    assert ex.calls == []
    gh.edit(Pr(5, "u", PrState.OPEN, False, "old"), spec(PrMode.READY))
    assert ex.calls == [["gh", "pr", "edit", "5", "--base", "main"]]
    ex.calls.clear()
    gh.edit(Pr(5, "u", PrState.OPEN, True, "main"), spec(PrMode.READY))
    assert ex.calls == [["gh", "pr", "ready", "5"]]
    ex.calls.clear()
    gh.edit(Pr(5, "u", PrState.OPEN, False, "main"), spec(PrMode.DRAFT))
    assert ex.calls == [["gh", "pr", "ready", "5", "--undo"]]
    ex.calls.clear()
    gh.edit(Pr(5, "u", PrState.OPEN, True, "old"), spec(PrMode.READY))
    assert ex.calls == [["gh", "pr", "edit", "5", "--base", "main"], ["gh", "pr", "ready", "5"]]


def test_gh_edit_failure() -> None:
    with pytest.raises(UpstreamError, match="no"):
        GhPrs(lambda argv: (1, "no")).edit(
            Pr(5, "u", PrState.OPEN, False, "old"), spec(PrMode.READY)
        )


def test_command_runner_runs_argv_and_maps_missing_binary(fake: FakeSystem) -> None:
    fake.reply(("git", "--version"), Done(0, "git version 2.50\n"))
    fake.reply(("definitely-not-a-binary-xyz",), FileNotFoundError(2, "No such file"))
    run = up.command_runner(FAKE_REPO)
    code, out = run(["git", "--version"])
    assert code == 0 and "git version" in out
    code, out = run(["definitely-not-a-binary-xyz"])
    assert code == 127 and out
    assert fake.commands[0].cwd == FAKE_REPO


# ----- s153 AC1, AC2: upstreamed, lost_paths, adopt ----------------------------

BASE, TARGET_SHA = "d" * 40, "e" * 40
NO_RENAMES = ("git", "diff", "--name-only", "--no-renames")


def stamped(sha: str, message: str) -> str:
    return f"{sha}\x1fAda\x1fada@example.com\x1f100 +0000\x1f{message}\x1e\n"


def test_s153_up_rebase_argvs_are_the_flags_plus_the_empty_policy() -> None:
    assert (*up.REBASE_FLAGS, "--empty=drop") == up.REBASE_ARGV
    assert (*up.REBASE_FLAGS, "--empty=keep") == up.SCRATCH_REBASE_ARGV
    assert up.REBASE_FLAGS[:5] == (
        "-c",
        "rebase.updateRefs=false",
        "-c",
        "rebase.rebaseMerges=false",
        "rebase",
    )


def test_s153_up_upstreamed_runs_cherry_and_keeps_only_the_minus_shas(fake: FakeSystem) -> None:
    fake.reply(("git", "cherry"), Done(0, "- s1\n+ s2\n- s3\n"))
    assert upstream_for().upstreamed(OLD) == frozenset({"s1", "s3"})
    [argv] = issued(fake, "cherry")
    assert argv[-2:] == ("origin/main", OLD)


def test_s153_up_upstreamed_of_nothing_is_empty(fake: FakeSystem) -> None:
    fake.reply(("git", "cherry"), Done(0, ""))
    assert upstream_for().upstreamed(OLD) == frozenset()


def script_lost(fake: FakeSystem, head: str, mine: str = "", theirs: str = "") -> None:
    fake.reply(("git", "merge-base"), Done(0, BASE + "\n"))
    fake.reply((*NO_RENAMES, OLD, head), Done(0, mine))
    fake.reply((*NO_RENAMES, "origin/main", head), Done(0, theirs))


def test_s153_up_lost_paths_diffs_against_the_given_head(fake: FakeSystem) -> None:
    script_lost(fake, "br", mine="x.py\nb.py\n", theirs="a.py\n")
    spans = up.Spans(OLD, OLD, TARGET_SHA, head="br")
    assert upstream_for().lost_paths(spans) == ["a.py", "b.py", "x.py"]
    diffs = issued(fake, *NO_RENAMES)
    assert all("HEAD" not in argv for argv in diffs)
    assert {argv[-1] for argv in diffs} >= {"br"}


def test_s153_up_lost_paths_default_head_is_head(fake: FakeSystem) -> None:
    assert up.Spans("a", "b", "c").head == "HEAD"
    script_lost(fake, "HEAD")
    assert upstream_for().lost_paths(up.Spans(OLD, OLD, TARGET_SHA)) == []
    assert any(argv[-1] == "HEAD" for argv in issued(fake, *NO_RENAMES))


def script_adopt(fake: FakeSystem, head: str) -> None:
    fake.reply(("git", "rev-parse", "HEAD"), Done(0, head + "\n"))
    fake.reply(("git", "rev-parse", "origin/main"), Done(0, TARGET_SHA + "\n"))
    fake.reply(("git", "log", f"origin/main..{OLD}"), Done(0, stamped("o1", "one")))
    fake.reply(("git", "log", "origin/main..HEAD"), Done(0, stamped("n1", "one")))


def test_s153_up_adopt_resets_keep_and_pairs_the_commits(fake: FakeSystem) -> None:
    script_adopt(fake, OLD)
    result = upstream_for().adopt(OLD, NEW)
    assert result.outcome is up.SyncOutcome.REBASED and result.sha == NEW
    assert dict(result.moved) == {"o1": "n1"}
    [reset] = issued(fake, "reset")
    assert reset[-2:] == ("--keep", NEW)


def test_s153_up_adopt_refuses_when_the_team_branch_moved(fake: FakeSystem) -> None:
    script_adopt(fake, NEW)
    fake.reply(("git", "symbolic-ref"), Done(0, "team\n"))
    with pytest.raises(UpstreamError) as raised:
        upstream_for().adopt(OLD, "c" * 40)
    assert str(raised.value) == up.TEAM_MOVED.format(team="team", old=OLD)
    assert issued(fake, "reset") == []

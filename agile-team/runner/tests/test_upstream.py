"""s29 U4/U5/U17/U19/U24: Upstream over bare repos, GhPrs over a fake Exec."""

from pathlib import Path

import pytest
from agile_team import upstream as up
from agile_team.config import UpstreamSettings
from agile_team.git_ops import Git, GitError
from agile_team.upstream import (
    GhPrs,
    Lease,
    MergeOutcome,
    NoPrs,
    Pr,
    PrMode,
    PrSpec,
    PrState,
    Upstream,
    UpstreamError,
)

from .conftest import git
from .s29_helpers import commit, is_ancestor, land_upstream, make_origin, rev

MSG = "chore(team): merge origin/main at sprint 2 start"


def upstream_for(work: Path, **kw) -> Upstream:
    return Upstream(Git(work), UpstreamSettings(**kw))


def test_target(tmp_path: Path) -> None:
    _, work = make_origin(tmp_path)
    assert upstream_for(work).target == "origin/main"
    assert upstream_for(work, remote="up", branch="dev").target == "up/dev"


def test_missing_none_when_everything_is_there(tmp_path: Path) -> None:
    _, work = make_origin(tmp_path)
    assert upstream_for(work).missing() is None


def test_missing_sync_off(tmp_path: Path) -> None:
    _, work = make_origin(tmp_path)
    assert upstream_for(work, remote="").missing() == "[upstream] remote is empty"


def test_missing_no_remote(repo: Path) -> None:
    assert upstream_for(repo).missing() == "no remote 'origin'"


def test_missing_fetch_failed(tmp_path: Path) -> None:
    _, work = make_origin(tmp_path)
    git(work, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    reason = upstream_for(work).missing()
    assert reason.startswith("git fetch origin failed: ")
    assert len(reason) > len("git fetch origin failed: ")


def test_missing_no_target(tmp_path: Path) -> None:
    _, work = make_origin(tmp_path)
    assert upstream_for(work, branch="nope").missing() == "origin/nope does not exist"


def test_team_branch_and_detached(tmp_path: Path) -> None:
    _, work = make_origin(tmp_path)
    assert upstream_for(work).team_branch() == "agile-team"
    git(work, "checkout", "-q", "--detach")
    with pytest.raises(UpstreamError, match="detached HEAD; check out the team branch"):
        upstream_for(work).team_branch()


def test_merge_in_current_makes_no_commit(tmp_path: Path) -> None:
    _, work = make_origin(tmp_path)
    before = rev(work, "HEAD")
    merge = upstream_for(work).merge_in(MSG)
    assert merge.outcome is MergeOutcome.CURRENT and rev(work, "HEAD") == before


def test_merge_in_merges_and_keeps_old_hashes(tmp_path: Path) -> None:
    origin, work = make_origin(tmp_path)
    mine = commit(work, "mine.txt")
    land_upstream(tmp_path, origin, "theirs.txt")
    u = upstream_for(work)
    assert u.missing() is None
    merge = u.merge_in(MSG)
    assert merge.outcome is MergeOutcome.MERGED and merge.sha == rev(work, "HEAD")
    assert is_ancestor(work, mine, "HEAD")
    assert (work / "theirs.txt").exists()
    body = git(work, "log", "-1", "--format=%B")
    assert body.startswith(MSG) and "Co-Authored-By" in body
    assert u.merge_in(MSG).outcome is MergeOutcome.CURRENT


def test_merge_in_fast_forward_counts_as_merged(tmp_path: Path) -> None:
    origin, work = make_origin(tmp_path)
    git(work, "reset", "-q", "--hard", "origin/main")
    land_upstream(tmp_path, origin, "theirs.txt")
    upstream_for(work).missing()
    assert upstream_for(work).merge_in(MSG).outcome is MergeOutcome.MERGED


def test_merge_in_conflict_aborts_and_lists_files(tmp_path: Path) -> None:
    origin, work = make_origin(tmp_path)
    commit(work, "base.txt", "mine\n")
    land_upstream(tmp_path, origin, "base.txt", "theirs\n")
    u = upstream_for(work)
    u.missing()
    before = rev(work, "HEAD")
    merge = u.merge_in(MSG)
    assert merge.outcome is MergeOutcome.CONFLICT and list(merge.files) == ["base.txt"]
    assert rev(work, "HEAD") == before and (work / "base.txt").read_text() == "mine\n"
    assert not (work / ".git" / "MERGE_HEAD").exists()
    assert git(work, "status", "--porcelain").strip() == ""


def test_merge_in_failure_without_conflict_is_a_git_error(tmp_path: Path) -> None:
    _, work = make_origin(tmp_path)
    u = upstream_for(work, branch="nope")
    with pytest.raises(GitError):
        u.merge_in(MSG)


def test_merge_base(tmp_path: Path) -> None:
    _, work = make_origin(tmp_path)
    base = rev(work, "origin/main")
    commit(work, "mine.txt")
    assert upstream_for(work).merge_base() == base


def branch_to_push(work: Path, name: str = "team/sprint-1") -> str:
    git(work, "branch", "-f", name, "HEAD")
    return name


def test_push_new_branch_with_empty_expectation(tmp_path: Path) -> None:
    origin, work = make_origin(tmp_path)
    commit(work, "mine.txt")
    name = branch_to_push(work)
    assert upstream_for(work).push(Lease(name, "")) is None
    assert rev(origin, name) == rev(work, name)
    assert rev(origin, "main") != rev(work, name)


def test_push_with_matching_lease_updates_and_stale_lease_is_rejected(tmp_path: Path) -> None:
    origin, work = make_origin(tmp_path)
    commit(work, "a.txt")
    name = branch_to_push(work)
    u = upstream_for(work)
    assert u.push(Lease(name, "")) is None
    first = rev(work, name)
    commit(work, "b.txt")
    branch_to_push(work)
    assert u.push(Lease(name, first)) is None
    assert rev(origin, name) == rev(work, name)
    commit(work, "c.txt")
    branch_to_push(work)
    out = u.push(Lease(name, first))
    assert out and rev(origin, name) != rev(work, name)


def test_push_rejected_when_someone_else_created_the_branch(tmp_path: Path) -> None:
    origin, work = make_origin(tmp_path)
    commit(work, "a.txt")
    name = branch_to_push(work)
    git(origin, "branch", name, "main")
    assert upstream_for(work).push(Lease(name, "")) is not None


@pytest.mark.parametrize("branch", ["main", "agile-team", "feature/x", "teamsprint-1"])
def test_push_refuses_main_team_and_unprefixed_branches(tmp_path: Path, branch: str) -> None:
    origin, work = make_origin(tmp_path)
    main_before = rev(origin, "main")
    commit(work, "a.txt")
    git(work, "branch", "-f", "feature/x", "HEAD")
    git(work, "branch", "-f", "teamsprint-1", "HEAD")
    with pytest.raises(UpstreamError, match="refusing to push"):
        upstream_for(work).push(Lease(branch, ""))
    assert rev(origin, "main") == main_before


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


def test_command_runner_runs_argv_and_maps_missing_binary(tmp_path: Path) -> None:
    run = up.command_runner(tmp_path)
    code, out = run(["git", "--version"])
    assert code == 0 and "git version" in out
    code, out = run(["definitely-not-a-binary-xyz"])
    assert code == 127 and out

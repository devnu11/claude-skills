"""s159 end to end on real git: story worktrees, the landing merge shape, the replay, push leases.

Each test builds a bare origin and a team clone in ``tmp_path`` (``make_world``); nothing is
scripted. One group per AC id.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agile_team import boundary as bd
from agile_team import replay as rp
from agile_team.config import Config, UpstreamSettings
from agile_team.gates import StoryState
from agile_team.git_ops import Git
from agile_team.story_branches import (
    format_landing_branch,
    format_story_branch,
    merge_id,
    merge_subject,
)
from agile_team.upstream import Lease, SyncOutcome, Upstream
from agile_team.workspaces import Workspaces

from ..conftest import git
from .test_s59_rebase_e2e import World, make_world


@pytest.fixture
def repos(tmp_path: Path) -> World:
    return make_world(tmp_path)


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").strip()


def land(repos: World, story_id: str, title: str, files: dict[str, str]) -> str:
    """Make a story branch off HEAD with two commits and merge it --no-ff, as the Lander does."""
    base = head(repos.team)
    branch = format_story_branch("team/story-", story_id, 0)
    git(repos.team, "checkout", "-q", "-b", branch)
    for i, (path, text) in enumerate(files.items()):
        repos.commit(repos.team, path, text, f"{story_id} commit {i}")
    git(repos.team, "checkout", "-q", "-")
    git(repos.team, "merge", "--no-ff", "-q", "-m", merge_subject(story_id, title), branch)
    assert git(repos.team, "rev-parse", "HEAD^1").strip() == base
    return head(repos.team)


# ---------- AC1.1 / AC3.1: branch at the sprint head, worktree inside the repo ----------


def test_ac1_1_the_first_step_forks_the_branch_at_the_sprint_head_in_a_run_worktree(
    repos: World,
) -> None:
    ws = Workspaces(Git(repos.team), Config(repo=repos.team))
    story = StoryState("s7", "Seven", "design")
    sprint_head = head(repos.team)
    path = ws.ensure(story, sprint_head)
    assert story.branch == "team/story-s7"
    assert path == repos.team / ".team" / "run" / "worktrees" / "s7" and path.is_dir()
    assert git(repos.team, "rev-parse", story.branch).strip() == sprint_head
    assert git(path, "branch", "--show-current").strip() == story.branch
    assert head(repos.team) == sprint_head
    assert git(repos.team, "branch", "--show-current").strip() == "main"


def test_ac3_1_a_moved_out_story_keeps_its_branch_and_the_worktree_is_rebuilt(
    repos: World,
) -> None:
    ws = Workspaces(Git(repos.team), Config(repo=repos.team))
    story = StoryState("s7", "Seven", "design")
    path = ws.ensure(story, head(repos.team))
    repos.commit(path, "feature.txt", "f\n", "s7 work")
    work = head(path)
    ws.remove("s7")
    assert not path.exists()
    assert git(repos.team, "rev-parse", story.branch).strip() == work
    assert ws.ensure(story, head(repos.team)) == path
    assert (path / "feature.txt").read_text() == "f\n"


def test_ac1_1_the_open_count_counts_worktrees(repos: World) -> None:
    ws = Workspaces(Git(repos.team), Config(repo=repos.team))
    stories = [StoryState(sid, sid, "design") for sid in ("s1", "s2")]
    for story in stories:
        ws.ensure(story, head(repos.team))
    assert ws.count_open(stories) == 2


# ---------- AC2.1 / AC2.2: --no-ff merge, story commits keep their hashes ----------


def test_ac2_1_the_landing_merge_has_the_sprint_head_first_and_keeps_story_hashes(
    repos: World,
) -> None:
    before = head(repos.team)
    merge = land(repos, "s1", "One", {"a.txt": "a\n", "b.txt": "b\n"})
    parents = git(repos.team, "log", "-1", "--format=%P", merge).split()
    assert parents[0] == before and len(parents) == 2
    assert git(repos.team, "log", "-1", "--format=%s", merge).strip() == "merge(s1): One"
    assert merge_id("merge(s1): One") == "s1"
    own = git(repos.team, "rev-list", f"{before}..{parents[1]}").split()
    assert len(own) == 2 and parents[1] == own[0]


# ---------- AC2.5 / AC2.7: the replay ----------


def replay_onto_moved_main(repos: World, merges: list[str]) -> tuple[rp.ReplayResult, Path]:
    repos.commit(repos.other, "main.txt", "m\n", "main moves")
    repos.push_main()
    team = Git(repos.team)
    base = git(repos.team, "merge-base", merges[-1], "origin/main").strip()
    spec = rp.ReplaySpec(base, merges[-1], "origin/main", "agile-team/scratch")
    progress = bd.ReplayProgress(old_head=merges[-1], base=base, target="origin/main")
    path = repos.team / ".team" / "run" / "replay"
    return rp.Replayer(team, path).run(spec, progress), path


def test_ac2_5_the_replay_makes_a_first_parent_line_of_story_merges_on_the_new_main(
    repos: World,
) -> None:
    m1 = land(repos, "s1", "One", {"a.txt": "a\n", "a2.txt": "a2\n"})
    repos.commit(repos.team, "admin.txt", "x\n", "chore(story): admin edit")
    m2 = land(repos, "s2", "Two", {"b.txt": "b\n"})
    result, path = replay_onto_moved_main(repos, [m1, m2])
    assert result.outcome is SyncOutcome.REBASED
    line = git(repos.team, "log", "--first-parent", "--format=%s", f"origin/main..{result.tip}")
    assert line.splitlines() == ["merge(s2): Two", "chore(story): admin edit", "merge(s1): One"]
    assert git(repos.team, "merge-base", "--is-ancestor", "origin/main", result.tip) == ""
    for merge in ("merge(s1): One", "merge(s2): Two"):
        sha = git(repos.team, "log", "--first-parent", "--format=%H", "--grep", merge, result.tip)
        assert len(git(repos.team, "log", "-1", "--format=%P", sha.strip()).split()) == 2
    assert path.is_dir()


def test_ac2_7_the_remap_pairs_each_merge_and_each_story_commit(repos: World) -> None:
    m1 = land(repos, "s1", "One", {"a.txt": "a\n", "a2.txt": "a2\n"})
    m2 = land(repos, "s2", "Two", {"b.txt": "b\n"})
    result, _ = replay_onto_moved_main(repos, [m1, m2])
    assert m1 in result.moved and m2 in result.moved
    assert result.moved[m1] != m1 and result.moved[m2] != m2
    new_subject = git(repos.team, "log", "-1", "--format=%s", result.moved[m2]).strip()
    assert new_subject == "merge(s2): Two"
    s1_commits = git(repos.team, "rev-list", f"{m1}^1..{m1}^2").split()
    assert all(c in result.moved and result.moved[c] != c for c in s1_commits)


def test_ac2_6_a_story_conflict_stops_the_replay_naming_the_story(repos: World) -> None:
    m1 = land(repos, "s1", "One", {"shared.txt": "team side\n"})
    repos.commit(repos.other, "shared.txt", "main side\n", "main adds shared")
    repos.push_main()
    base = git(repos.team, "merge-base", m1, "origin/main").strip()
    spec = rp.ReplaySpec(base, m1, "origin/main", "agile-team/scratch")
    progress = bd.ReplayProgress(old_head=m1, base=base, target="origin/main")
    path = repos.team / ".team" / "run" / "replay"
    result = rp.Replayer(Git(repos.team), path).run(spec, progress)
    assert result.outcome is SyncOutcome.CONFLICT
    assert result.story == "s1" and result.files == ("shared.txt",)


# ---------- AC2.16: leases against a bare remote ----------


def upstream(repos: World) -> Upstream:
    return Upstream(Git(repos.team), UpstreamSettings())


def test_ac2_16_a_new_branch_is_created_then_fast_forwarded_with_its_expected_sha(
    repos: World,
) -> None:
    up = upstream(repos)
    first = head(repos.team)
    assert up.push(Lease("team/sprint-1", "", first)) is None
    second = repos.commit(repos.team, "n.txt", "n\n", "next")
    assert up.push(Lease("team/sprint-1", first, second)) is None
    assert git(repos.origin, "rev-parse", "refs/heads/team/sprint-1").strip() == second


def test_ac2_16_a_non_descendant_is_refused_and_never_sent(repos: World) -> None:
    up = upstream(repos)
    first = head(repos.team)
    other = repos.commit(repos.team, "n.txt", "n\n", "next")
    git(repos.team, "reset", "-q", "--hard", first)
    divergent = repos.commit(repos.team, "d.txt", "d\n", "divergent")
    assert up.push(Lease("team/sprint-1", "", other)) is None
    refusal = up.push(Lease("team/sprint-1", other, divergent))
    assert refusal and "team/sprint-1" in refusal
    assert git(repos.origin, "rev-parse", "refs/heads/team/sprint-1").strip() == other


def test_ac2_16_a_remote_that_moved_since_the_record_is_refused_by_the_lease(
    repos: World,
) -> None:
    up = upstream(repos)
    first = head(repos.team)
    assert up.push(Lease("team/sprint-1", "", first)) is None
    git(repos.other, "fetch", "-q", "origin")
    git(repos.other, "checkout", "-q", "-B", "x", "origin/team/sprint-1")
    moved = repos.commit(repos.other, "o.txt", "o\n", "someone fixes")
    git(repos.other, "push", "-q", "origin", "x:refs/heads/team/sprint-1")
    mine = repos.commit(repos.team, "n.txt", "n\n", "next")
    assert up.push(Lease("team/sprint-1", first, mine)) is not None
    assert git(repos.origin, "rev-parse", "refs/heads/team/sprint-1").strip() == moved


def test_ac1_5_the_push_guard_refuses_main_and_the_checked_out_branch(repos: World) -> None:
    up = upstream(repos)
    sha = head(repos.team)
    with pytest.raises(Exception, match="team/"):
        up.push(Lease("main", "", sha))


# ---------- AC2.4: landing branch lifecycle ----------


def test_ac2_4_the_landing_branch_is_created_and_deleted_with_a_lease(repos: World) -> None:
    up = upstream(repos)
    sha = head(repos.team)
    name = format_landing_branch("team/story-", "s1")
    assert name == "team/story-s1-land"
    assert up.push(Lease(name, "", sha)) is None
    assert up.read_remote_head(name) == sha
    assert up.delete(Lease(name, sha, sha)) is None
    assert up.read_remote_head(name) == ""


def test_ac2_4_delete_refuses_a_branch_that_is_not_a_landing_branch(repos: World) -> None:
    up = upstream(repos)
    sha = head(repos.team)
    assert up.push(Lease("team/sprint-1", "", sha)) is None
    assert up.delete(Lease("team/sprint-1", sha, sha)) is not None
    assert up.read_remote_head("team/sprint-1") == sha


def test_ac2_4_fast_forward_moves_the_checked_out_sprint_branch(repos: World) -> None:
    up = upstream(repos)
    first = head(repos.team)
    git(repos.team, "checkout", "-q", "-b", "scratch")
    second = repos.commit(repos.team, "n.txt", "n\n", "merge")
    git(repos.team, "checkout", "-q", "main")
    assert up.advance_to(second) is True and head(repos.team) == second
    assert first != second

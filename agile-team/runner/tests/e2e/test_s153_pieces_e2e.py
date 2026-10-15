"""e2e: the pieces of the sprint-end rebase conflict path, with real git (s153, AC8).

Each test builds a bare ``origin``, a team clone and a second clone that plays "main",
all in ``tmp_path``. The team branch is ``main`` ahead of ``origin/main``.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from agile_team.config import UpstreamSettings
from agile_team.git_ops import Git
from agile_team.scratch_rebase import (
    COMMITS_CHANGED,
    DIRTY,
    HAS_MERGES,
    LOST_PATHS,
    NOT_ON_TARGET,
    OFF_BRANCH,
    UNFINISHED,
    ScratchRebase,
)
from agile_team.upstream import TEAM_MOVED, Spans, SyncOutcome, Upstream, UpstreamError

from ..conftest import git, set_git_identity

BRANCH = "agile-team/rebase-sprint-1"


@dataclass
class World:
    """The bare origin, the team clone and the clone that pushes to main."""

    origin: Path
    team: Path
    other: Path

    def commit(self, repo: Path, path: str, text: str, message: str) -> str:
        """Write ``path``, commit it and return the new sha."""
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", message)
        return git(repo, "rev-parse", "HEAD").strip()

    def publish(self) -> None:
        """Push the other clone's main and let the team clone fetch it."""
        git(self.other, "push", "-q", "origin", "main")
        git(self.team, "fetch", "-q", "origin")

    def upstream(self) -> Upstream:
        """The runner's seam on the team clone."""
        return Upstream(Git(self.team), UpstreamSettings())

    def scratch(self, tmp_path: Path) -> ScratchRebase:
        """The scratch rebase for sprint 1, under a run dir in ``tmp_path``."""
        return ScratchRebase(self.upstream(), tmp_path / "run" / "rebase", BRANCH)

    def head(self) -> str:
        """The team checkout's HEAD sha."""
        return git(self.team, "rev-parse", "HEAD").strip()


def make_world(tmp_path: Path) -> World:
    """origin with one commit on main, cloned twice, each clone with its own identity."""
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    set_git_identity(seed)
    world = World(tmp_path / "origin.git", tmp_path / "team", tmp_path / "other")
    world.commit(seed, "f.txt", "1\n2\n3\n", "init")
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(world.origin))
    for clone in (world.team, world.other):
        git(tmp_path, "clone", "-q", str(world.origin), str(clone))
        set_git_identity(clone)
    return world


def clean_scene(tmp_path: Path) -> World:
    """One team commit (t.txt) and one upstream commit (o.txt): the rebase is clean."""
    world = make_world(tmp_path)
    world.commit(world.team, "t.txt", "team\n", "team: t")
    world.commit(world.other, "o.txt", "other\n", "main: o")
    world.publish()
    return world


def conflict_scene(tmp_path: Path) -> World:
    """Two team commits, the first conflicting with main on f.txt."""
    world = make_world(tmp_path)
    world.commit(world.team, "f.txt", "A\n2\n3\n", "team: edit f")
    world.commit(world.team, "t2.txt", "two\n", "team: add t2")
    world.commit(world.other, "f.txt", "B\n2\n3\n", "main: edit f")
    world.publish()
    return world


def stopped(tmp_path: Path) -> tuple[World, ScratchRebase, str]:
    """A conflict scene with the scratch rebase prepared; the world, scratch and old head."""
    world = conflict_scene(tmp_path)
    scratch = world.scratch(tmp_path)
    old = world.head()
    scratch.prepare(old)
    return world, scratch, old


def resolve(scratch: ScratchRebase) -> None:
    """Resolve the f.txt conflict and finish the rebase, as DevOps would."""
    (scratch.path / "f.txt").write_text("B\nA\n3\n")
    git(scratch.path, "add", "f.txt")
    env = {**os.environ, "GIT_EDITOR": "true"}
    subprocess.run(
        ["git", "rebase", "--continue"], cwd=scratch.path, env=env, check=True, capture_output=True
    )


def branch_exists(world: World, branch: str) -> bool:
    """True when ``branch`` is a local branch of the team repo."""
    ref = f"refs/heads/{branch}"
    return Git(world.team).attempt("rev-parse", "--verify", "-q", ref)[0] == 0


# ----- AC1


def test_ac1_upstreamed_names_only_team_commits_whose_patch_is_in_the_target(
    tmp_path: Path,
) -> None:
    world = make_world(tmp_path)
    landed = world.commit(world.team, "a.txt", "a\n", "team: a")
    kept = world.commit(world.team, "b.txt", "b\n", "team: b")
    git(world.team, "push", "-q", "origin", "HEAD:refs/heads/feat")
    git(world.other, "fetch", "-q", "origin")
    later = {**os.environ, "GIT_COMMITTER_DATE": "2030-01-01T00:00:00Z"}
    cmd = ["git", "cherry-pick", landed]
    subprocess.run(cmd, cwd=world.other, env=later, check=True, capture_output=True)
    world.publish()
    assert world.upstream().find_upstreamed(kept) == frozenset({landed})


def test_ac1_lost_paths_judges_the_given_head_not_head(tmp_path: Path) -> None:
    world = clean_scene(tmp_path)
    up, old = world.upstream(), world.head()
    target_sha = git(world.team, "rev-parse", up.target).strip()
    git(world.team, "rebase", "-q", "origin/main")
    git(world.team, "branch", "side")
    git(world.team, "checkout", "-q", "side")
    world.commit(world.team, "x.txt", "stray\n", "side: x")
    git(world.team, "checkout", "-q", "main")
    assert up.find_lost_paths(Spans(old, old, target_sha)) == []
    assert up.find_lost_paths(Spans(old, old, target_sha, head="side")) == ["x.txt"]


# ----- AC2


def test_ac2_adopt_moves_the_team_branch_and_maps_each_commit(tmp_path: Path) -> None:
    world = clean_scene(tmp_path)
    up, old = world.upstream(), world.head()
    git(world.team, "rebase", "-q", "origin/main")
    rebased = world.head()
    git(world.team, "reset", "-q", "--hard", old)
    result = up.move_team_branch(old, rebased)
    assert result.outcome is SyncOutcome.REBASED
    assert result.sha == rebased
    assert world.head() == rebased
    assert Git(world.team).branch() == "main"
    assert result.moved == {old: rebased}


def test_ac2_adopt_refuses_when_the_team_branch_moved(tmp_path: Path) -> None:
    world = clean_scene(tmp_path)
    up, old = world.upstream(), world.head()
    world.commit(world.team, "late.txt", "late\n", "team: late")
    moved, tree = world.head(), git(world.team, "write-tree")
    with pytest.raises(UpstreamError, match="moved from"):
        up.move_team_branch(old, old)
    assert TEAM_MOVED.format(team="main", old=old).startswith("the team branch main moved")
    assert world.head() == moved
    assert Git(world.team).branch() == "main"
    assert git(world.team, "write-tree") == tree


# ----- AC3


def test_ac3_prepare_stops_the_rebase_and_leaves_the_team_checkout_alone(tmp_path: Path) -> None:
    world = conflict_scene(tmp_path)
    scratch, old = world.scratch(tmp_path), world.head()
    tree = git(world.team, "write-tree")
    scratch.prepare(old)
    assert scratch.path == tmp_path / "run" / "rebase"
    assert scratch.refusal(old).startswith("the rebase in")
    name = git(scratch.path, "rev-parse", "--git-path", "rebase-merge/head-name").strip()
    assert (scratch.path / name).read_text().strip() == f"refs/heads/{BRANCH}"
    assert world.head() == old
    assert Git(world.team).branch() == "main"
    assert git(world.team, "write-tree") == tree


def test_ac3_prepare_keeps_a_commit_the_target_already_has(tmp_path: Path) -> None:
    world = make_world(tmp_path)
    old = world.commit(world.team, "f.txt", "1\n2\nX\n", "team: x")
    (world.other / "g.txt").write_text("g\n")  # a bigger patch: a different patch id
    world.commit(world.other, "f.txt", "1\n2\nX\n", "main: x and more")
    world.publish()
    scratch = world.scratch(tmp_path)
    scratch.prepare(old)
    shas = git(world.team, "rev-list", f"origin/main..{BRANCH}").split()
    assert len(shas) == 1
    assert git(world.team, "diff-tree", "--no-commit-id", "--name-only", "-r", shas[0]) == ""


def test_ac3_prepare_replaces_a_leftover_worktree(tmp_path: Path) -> None:
    world = conflict_scene(tmp_path)
    scratch, old = world.scratch(tmp_path), world.head()
    scratch.prepare(old)
    (scratch.path / "stray.txt").write_text("left over\n")
    scratch.prepare(old)
    assert not (scratch.path / "stray.txt").exists()
    assert scratch.refusal(old).startswith("the rebase in")


# ----- AC4


def test_ac4_drop_removes_the_directory_the_worktree_entry_and_the_branch(
    tmp_path: Path,
) -> None:
    world, scratch, _ = stopped(tmp_path)
    scratch.drop()
    assert not scratch.path.exists()
    assert str(scratch.path) not in git(world.team, "worktree", "list")
    assert not branch_exists(world, BRANCH)


# ----- AC5


def test_ac5_unfinished(tmp_path: Path) -> None:
    _, scratch, old = stopped(tmp_path)
    got = scratch.refusal(old)
    assert got.startswith(UNFINISHED.split("{operation}")[0].format(path=scratch.path))
    assert "rebase" in got


def test_ac5_off_branch(tmp_path: Path) -> None:
    _, scratch, old = stopped(tmp_path)
    resolve(scratch)
    git(scratch.path, "checkout", "-q", "--detach")
    assert scratch.refusal(old) == OFF_BRANCH.format(path=scratch.path, branch=BRANCH)


def test_ac5_dirty(tmp_path: Path) -> None:
    _, scratch, old = stopped(tmp_path)
    resolve(scratch)
    (scratch.path / "junk.txt").write_text("junk\n")
    want = DIRTY.format(path=scratch.path, status="?? junk.txt")
    assert scratch.refusal(old) == want


def test_ac5_not_on_target(tmp_path: Path) -> None:
    _, scratch, old = stopped(tmp_path)
    resolve(scratch)
    git(scratch.path, "reset", "-q", "--hard", old)
    assert scratch.refusal(old) == NOT_ON_TARGET.format(branch=BRANCH, target="origin/main")


def test_ac5_merge_commit(tmp_path: Path) -> None:
    _, scratch, old = stopped(tmp_path)
    resolve(scratch)
    git(scratch.path, "checkout", "-q", "-b", "side", "HEAD~1")
    (scratch.path / "s.txt").write_text("s\n")
    git(scratch.path, "add", "s.txt")
    git(scratch.path, "commit", "-q", "-m", "side: s")
    git(scratch.path, "checkout", "-q", BRANCH)
    git(scratch.path, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    merge = git(scratch.path, "rev-parse", "HEAD").strip()[:12]
    assert scratch.refusal(old) == HAS_MERGES.format(branch=BRANCH, shas=merge)


def test_ac5_squashed_pair(tmp_path: Path) -> None:
    _, scratch, old = stopped(tmp_path)
    resolve(scratch)
    git(scratch.path, "reset", "-q", "--soft", "HEAD~2")
    git(scratch.path, "commit", "-q", "-m", "squashed")
    assert scratch.refusal(old) == COMMITS_CHANGED.format(branch=BRANCH)


def test_ac5_reworded_commit(tmp_path: Path) -> None:
    _, scratch, old = stopped(tmp_path)
    resolve(scratch)
    git(scratch.path, "commit", "-q", "--amend", "-m", "team: add t2, reworded")
    assert scratch.refusal(old) == COMMITS_CHANGED.format(branch=BRANCH)


def test_ac5_dropped_commit(tmp_path: Path) -> None:
    _, scratch, old = stopped(tmp_path)
    resolve(scratch)
    git(scratch.path, "reset", "-q", "--hard", "HEAD~1")
    assert scratch.refusal(old) == COMMITS_CHANGED.format(branch=BRANCH)


def test_ac5_one_sided_path(tmp_path: Path) -> None:
    _, scratch, old = stopped(tmp_path)
    resolve(scratch)
    (scratch.path / "extra.txt").write_text("extra\n")
    git(scratch.path, "add", "extra.txt")
    git(scratch.path, "commit", "-q", "--amend", "--no-edit")
    assert scratch.refusal(old) == LOST_PATHS.format(branch=BRANCH, paths="extra.txt")


def test_ac5_a_valid_resolution_gives_nothing(tmp_path: Path) -> None:
    _, scratch, old = stopped(tmp_path)
    resolve(scratch)
    assert scratch.refusal(old) == ""


def test_ac5_a_kept_empty_commit_gives_nothing(tmp_path: Path) -> None:
    world, scratch, old = stopped(tmp_path)
    # The first commit's change is already on main in effect: resolve to main's text.
    (scratch.path / "f.txt").write_text("B\n2\n3\n")
    git(scratch.path, "add", "f.txt")
    git(scratch.path, "commit", "-q", "--allow-empty", "-C", "REBASE_HEAD")
    env = {**os.environ, "GIT_EDITOR": "true"}
    cmd = ["git", "rebase", "--continue"]
    subprocess.run(cmd, cwd=scratch.path, env=env, check=True, capture_output=True)
    assert scratch.refusal(old) == ""
    assert world.head() == old

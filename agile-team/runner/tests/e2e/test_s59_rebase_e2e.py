"""e2e: the sprint-start sync rebases the team branch onto origin/main (s59, AC6).

Each test builds a bare ``origin``, a team clone and a second clone that plays "main"
receiving rebased copies, all in ``tmp_path`` with real git.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agile_team import rewrite
from agile_team.config import UpstreamSettings
from agile_team.gates import StoryState
from agile_team.git_ops import Git
from agile_team.handover import group_files
from agile_team.state import RunState
from agile_team.upstream import SyncOutcome, Upstream

from ..conftest import git, set_git_identity


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

    def copy_to_main(self, shas: list[str]) -> None:
        """Land ``shas`` on origin/main as cherry-picked copies (a rebase-merge)."""
        git(self.team, "push", "-q", "origin", "HEAD:refs/heads/feat")
        git(self.other, "fetch", "-q", "origin")
        later = {**os.environ, "GIT_COMMITTER_DATE": "2030-01-01T00:00:00Z"}
        # A later committer date makes the copies differ, as a real rebase-merge does.
        cmd = ["git", "cherry-pick", *shas]
        subprocess.run(cmd, cwd=self.other, env=later, check=True, capture_output=True)

    def push_main(self) -> None:
        """Publish the other clone's main and let the team clone see it."""
        git(self.other, "push", "-q", "origin", "main")
        git(self.team, "fetch", "-q", "origin")

    def upstream(self) -> Upstream:
        """The runner's seam on the team clone."""
        return Upstream(Git(self.team), UpstreamSettings())


def make_world(tmp_path: Path) -> World:
    """origin with one commit on main, cloned twice, each clone with its own identity."""
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    set_git_identity(seed)
    world = World(tmp_path / "origin.git", tmp_path / "team", tmp_path / "other")
    world.commit(seed, "src/f.txt", "1\n2\n3\n", "init")
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(world.origin))
    for clone in (world.team, world.other):
        git(tmp_path, "clone", "-q", str(world.origin), str(clone))
        set_git_identity(clone)
    return world


def state_with(commits: list[str]) -> RunState:
    """A run state whose story and stack record ``commits`` (the last is the story commit)."""
    state = RunState()
    story = StoryState("s1", "t", "dev", commit=commits[-1], code_commits=list(commits))
    state.stories["s1"] = story
    state.upstream.last_end = commits[-1]
    state.upstream.checked = commits[0]
    return state


def is_ancestor(repo: Path, sha: str) -> bool:
    """True when ``sha`` is reachable from HEAD."""
    return Git(repo).attempt("merge-base", "--is-ancestor", sha, "HEAD")[0] == 0


def test_commits_already_on_main_as_copies_leave_head_at_main(tmp_path):
    world = make_world(tmp_path)
    a = world.commit(world.team, "a.txt", "a\n", "A")
    b = world.commit(world.team, "b.txt", "b\n", "B")
    world.copy_to_main([a, b])
    world.push_main()
    old = git(world.team, "rev-parse", "HEAD").strip()
    result = world.upstream().rebase_onto(old)
    main = git(world.team, "rev-parse", "origin/main").strip()
    assert result.outcome is SyncOutcome.REBASED
    assert git(world.team, "rev-parse", "HEAD").strip() == main
    assert git(world.team, "diff", "origin/main").strip() == ""
    state = state_with([a, b])
    rewrite.remap_state(state, result.moved)
    assert state.stories["s1"].commit == main


def test_copies_plus_new_content_rebase_without_conflict(tmp_path):
    world = make_world(tmp_path)
    a = world.commit(world.team, "src/f.txt", "1\nA\n3\n", "A edits f")
    b = world.commit(world.team, "src/f.txt", "1\nB\n3\n", "B edits A's line")
    world.copy_to_main([a])
    world.commit(world.other, "u.txt", "u\n", "U unrelated")
    world.push_main()
    result = world.upstream().rebase_onto(b)
    assert result.outcome is SyncOutcome.REBASED
    assert git(world.team, "rev-list", "--merges", "origin/main..HEAD").strip() == ""
    assert (world.team / "src/f.txt").read_text() == "1\nB\n3\n"
    assert (world.team / "u.txt").read_text() == "u\n"
    assert result.moved[b] == git(world.team, "rev-parse", "HEAD").strip()
    assert result.moved[a] == git(world.team, "rev-parse", "origin/main").strip()


def test_a_real_conflict_aborts_and_leaves_the_branch_unchanged(tmp_path):
    world = make_world(tmp_path)
    mine = world.commit(world.team, "src/f.txt", "team\n2\n3\n", "team edits line 1")
    world.commit(world.other, "src/f.txt", "main\n2\n3\n", "main edits line 1")
    world.push_main()
    result = world.upstream().rebase_onto(mine)
    assert result.outcome is SyncOutcome.CONFLICT
    assert result.files == ("src/f.txt",)
    assert result.subject == "team edits line 1"
    assert git(world.team, "rev-parse", "HEAD").strip() == mine
    for name in ("rebase-merge", "rebase-apply"):
        assert not (world.team / ".git" / name).exists()
    assert group_files(result.files) == "src (1): f.txt"


def test_the_recorded_hashes_are_rewritten_to_reachable_commits(tmp_path):
    world = make_world(tmp_path)
    a = world.commit(world.team, "src/f.txt", "1\nA\n3\n", "A edits f")
    b = world.commit(world.team, "b.txt", "b\n", "B adds b")
    world.copy_to_main([a])
    world.commit(world.other, "u.txt", "u\n", "U unrelated")
    world.push_main()
    state = state_with([a, b])
    result = world.upstream().rebase_onto(b)
    changed = rewrite.remap_state(state, result.moved)
    story = state.stories["s1"]
    assert changed == 4
    assert story.commit == result.moved[b] == git(world.team, "rev-parse", "HEAD").strip()
    assert all(is_ancestor(world.team, sha) for sha in story.code_commits)
    assert is_ancestor(world.team, state.upstream.last_end)
    assert state.upstream.checked == a


def test_a_hand_rebase_after_a_conflict_is_remapped_from_the_pinned_start(tmp_path):
    world = make_world(tmp_path)
    first = world.commit(world.team, "src/f.txt", "team\n2\n3\n", "team edits line 1")
    second = world.commit(world.team, "b.txt", "b\n", "B adds b")
    world.commit(world.other, "src/f.txt", "main\n2\n3\n", "main edits line 1")
    world.push_main()
    up = world.upstream()
    assert up.rebase_onto(second).outcome is SyncOutcome.CONFLICT
    Git(world.team).attempt("rebase", "origin/main")
    (world.team / "src/f.txt").write_text("resolved\n2\n3\n")
    git(world.team, "add", "-A")
    Git(world.team, ("-c", "core.editor=true")).run("rebase", "--continue")
    result = up.rebase_onto(second)
    head = git(world.team, "rev-parse", "HEAD").strip()
    assert result.outcome is SyncOutcome.REBASED
    assert result.moved[second] == head
    assert is_ancestor(world.team, result.moved[first])
    assert result.moved[first] != first

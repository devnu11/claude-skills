"""e2e: the story-rebase step's git may move only its own rebase branch (s176).

Real git in ``tmp_path``: a main repo with story branches and a rebase worktree.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agile_team import guard
from agile_team.git_check import Allows
from agile_team.git_ops import Git
from agile_team.story_branches import StoryRebase
from agile_team.story_rebase import list_moved_branches, put_back_branch, read_branch_heads

from ..conftest import git, set_git_identity

OWN = "team/story-s165-r1"
OTHER = "team/story-s164-r1"


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path]:
    """A repo with branches ``OTHER`` and ``sprint``, and a worktree on ``OWN``."""
    root = tmp_path.resolve() / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    set_git_identity(root)
    git(root, "commit", "-q", "--allow-empty", "-m", "base")
    git(root, "branch", OTHER)
    git(root, "branch", "sprint")
    wt = tmp_path.resolve() / "wt"
    git(root, "worktree", "add", "-q", "-b", OWN, str(wt))
    return root, wt


def scope_in(root: Path, wt: Path) -> guard.Scope:
    """The rebase step's scope: LOCAL git in the worktree, one movable branch."""
    scope = guard.Scope(role="devops", repo=root, write=["**"])
    scope.git_workspace = wt
    scope.cwd = wt
    scope.git_allows = Allows.LOCAL
    scope.git_branch = OWN
    return scope


def test_ac1_moves_of_another_branch_are_refused(repos: tuple[Path, Path]) -> None:
    """AC1: each command that would move another branch is refused, naming the own branch."""
    root, wt = repos
    scope = scope_in(root, wt)
    commands = [
        f"git checkout -B {OTHER}",
        f"git switch -C {OTHER}",
        f"git rebase sprint {OTHER}",
        f"git checkout {OTHER} && git reset --hard sprint",
        f"git checkout {OTHER} && git rebase sprint",
        f"git branch -f {OTHER} sprint",
        f"git update-ref refs/heads/{OTHER} sprint",
        f"git symbolic-ref refs/heads/{OTHER} refs/heads/sprint",
    ]
    for command in commands:
        assert guard.check_bash(scope, command), command
    refusal = guard.check_bash(scope, f"git checkout -B {OTHER}")
    assert refusal and OWN in refusal
    assert git(root, "rev-parse", OTHER) == git(root, "rev-parse", "main")


def test_ac2_rebase_commands_still_run(repos: tuple[Path, Path]) -> None:
    """AC2: the rebase's own commands and read-only commands pass the guard."""
    root, wt = repos
    scope = scope_in(root, wt)
    commands = [
        "git rebase --continue",
        "git rebase --abort",
        "git rebase --skip",
        "git add -A",
        "git checkout -- file.txt",
        "git reset --hard",
        f"git checkout -B {OWN}",
        "git status",
        "git log --oneline",
        "git diff",
    ]
    for command in commands:
        assert guard.check_bash(scope, command) is None, command


def test_ac3_moved_branch_is_found_and_put_back(repos: tuple[Path, Path]) -> None:
    """AC3: a branch moved behind the guard is reported with both shas and restored."""
    root, _ = repos
    run = Git(root)
    rebase = StoryRebase("sprint", "main", "x", OWN, [], "devops")
    rebase.heads = read_branch_heads(run, rebase)
    assert OTHER in rebase.heads and OWN not in rebase.heads
    old = git(root, "rev-parse", OTHER).strip()
    tree = git(root, "rev-parse", "main^{tree}").strip()
    elsewhere = git(root, "commit-tree", tree, "-p", old, "-m", "more").strip()
    git(root, "branch", "-f", OTHER, elsewhere)
    new = git(root, "rev-parse", OTHER).strip()
    assert new != old
    moved = list_moved_branches(run, rebase)
    assert [(m.branch, m.old, m.new) for m in moved] == [(OTHER, old, new)]
    message = put_back_branch(run, moved[0])
    assert OTHER in message and old in message and new in message
    assert git(root, "rev-parse", OTHER).strip() == old
    assert list_moved_branches(run, rebase) == []

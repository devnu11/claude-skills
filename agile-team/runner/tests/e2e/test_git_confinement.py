"""e2e: a confined role's git never reaches the team repo (s65, AC1 and AC9).

Real git in ``tmp_path``: a "team" repo with a git-less presentation workspace inside it.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from agile_team import guard
from agile_team.git_check import git_env

from ..conftest import git, set_git_identity

IDENTITY = {"NAME": "Tester", "EMAIL": "t@example.com"}


@pytest.fixture
def team(tmp_path: Path) -> Path:
    """A team repo with one commit."""
    root = tmp_path.resolve() / "team"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    set_git_identity(root)
    git(root, "commit", "-q", "--allow-empty", "-m", "base")
    return root


@pytest.fixture
def workspace(team: Path) -> Path:
    """The presentation workspace, with no ``.git`` of its own."""
    ws = team / ".team/run/presentation/s1/workspace"
    ws.mkdir(parents=True)
    return ws


def confined_env(team: Path) -> dict[str, str]:
    """The process env, a commit identity (the isolated git has none) and the git ceiling."""
    who = {f"GIT_{r}_{k}": v for r in ("AUTHOR", "COMMITTER") for k, v in IDENTITY.items()}
    return {**os.environ, **who, **git_env(team / ".team/run")}


def scope_for(team: Path, workspace: Path) -> guard.Scope:
    """The integration-tester's confined scope."""
    scope = guard.Scope(role="integration-tester", repo=team, write=["**"])
    scope.git_workspace = workspace
    return scope


def attempt(team: Path, scope: guard.Scope, command: str) -> tuple[str | None, int | None]:
    """Guard a command, then run it at the team root if allowed."""
    denial = guard.check_bash(scope, command)
    if denial:
        return denial, None
    done = subprocess.run(
        command, shell=True, cwd=team, env=confined_env(team), capture_output=True, text=True
    )
    return None, done.returncode


def heads(team: Path) -> tuple[str, str]:
    """The team repo's refs and HEAD."""
    return git(team, "for-each-ref"), git(team, "rev-parse", "HEAD")


def test_ceiling_stops_git_finding_the_team_repo(team: Path, workspace: Path) -> None:
    """AC1: with the ceiling git finds no repo; without it, it finds the team's."""
    plain = subprocess.run(["git", "status"], cwd=workspace, capture_output=True, text=True)
    assert plain.returncode == 0
    fenced = subprocess.run(
        ["git", "status"], cwd=workspace, env=confined_env(team), capture_output=True, text=True
    )
    assert fenced.returncode != 0 and "not a git repository" in fenced.stderr


def test_confined_git_works_inside_and_is_denied_outside(team: Path, workspace: Path) -> None:
    """AC9: allowed git runs in the workspace; the team repo is denied and untouched."""
    before = heads(team)
    scope = scope_for(team, workspace)
    ws = str(workspace)
    allowed = [
        f"cd {ws} && git init -b main demo",
        f"cd {ws}/demo && git commit --allow-empty -m one",
        f"cd {ws} && git -C demo checkout -b topic",
        f"cd {ws}/demo && git commit --allow-empty -m two",
        f"cd {ws} && git -C demo rebase main",
        f"cd {ws} && git clone demo copy",
    ]
    for command in allowed:
        assert attempt(team, scope, command) == (None, 0), command
    for command in (f"git -C {team} status", f"git --git-dir {team}/.git log"):
        denial, code = attempt(team, scope, command)
        assert denial and str(team) in denial and code is None
    denial, code = attempt(team, scope, f"cd {ws} && git checkout -B main")
    assert denial is None and code != 0
    assert heads(team) == before

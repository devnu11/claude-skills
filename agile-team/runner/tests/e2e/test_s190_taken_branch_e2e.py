"""s190 end to end on real git: a leftover story branch is adopted or held, never lost."""

from __future__ import annotations

from pathlib import Path

import pytest
from agile_team import handover
from agile_team.config import Config
from agile_team.gates import StoryState
from agile_team.git_ops import Git
from agile_team.workspaces import ADOPTED_WHY, Workspaces

from ..conftest import git
from .test_s59_rebase_e2e import World, make_world

NAME = "team/story-s7"


@pytest.fixture
def repos(tmp_path: Path) -> World:
    return make_world(tmp_path)


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").strip()


def space(repos: World) -> Workspaces:
    return Workspaces(Git(repos.team), Config(repo=repos.team))


def leave_branch_ahead(repos: World) -> str:
    """A reverted story's kept branch: one commit past the sprint head."""
    git(repos.team, "checkout", "-q", "-b", NAME)
    repos.commit(repos.team, "old.txt", "old\n", "s7 old work")
    tip = head(repos.team)
    git(repos.team, "checkout", "-q", "-")
    return tip


def test_ac1_ac3_a_leftover_at_the_sprint_head_is_adopted_unchanged(repos: World) -> None:
    sprint_head = head(repos.team)
    git(repos.team, "branch", NAME, sprint_head)
    ws, story = space(repos), StoryState("s7", "Seven", "design")
    assert ws.describe_branch_start(story, sprint_head) == {
        "action": "adopted",
        "why": ADOPTED_WHY,
    }
    path = ws.ensure(story, sprint_head)
    assert story.branch == NAME and git(path, "branch", "--show-current").strip() == NAME
    assert git(repos.team, "rev-parse", NAME).strip() == sprint_head


def test_ac2_ac3_a_leftover_elsewhere_is_held_with_the_way_out_and_loses_nothing(
    repos: World,
) -> None:
    tip = leave_branch_ahead(repos)
    sprint_head = head(repos.team)
    ws, story = space(repos), StoryState("s7", "Seven", "design")
    taken = ws.find_taken_branch(story, sprint_head)
    assert taken is not None and not taken.is_at_base
    for part in (NAME, tip[:12], sprint_head[:12], "continue_story(s7)", taken.aside_branch):
        assert part in taken.reason
    report = {"status": "refused", "reason": taken.reason, "role": "tests"}
    line = handover.report_lines(report, "s7")
    assert line == [f"s7: tests was refused: {taken.reason}"]
    assert git(repos.team, "rev-parse", NAME).strip() == tip  # untouched by the refusal

    git(repos.team, "branch", "-m", NAME, taken.aside_branch)  # the way out
    assert git(repos.team, "rev-parse", taken.aside_branch).strip() == tip
    assert ws.describe_branch_start(story, sprint_head) == {"action": "created"}
    path = ws.ensure(story, sprint_head)
    assert git(repos.team, "rev-parse", NAME).strip() == sprint_head
    assert git(path, "branch", "--show-current").strip() == NAME

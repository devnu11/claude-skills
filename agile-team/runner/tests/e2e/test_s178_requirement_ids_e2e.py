"""s178 end to end: real git branches, parallel stories get distinct requirement ids."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from agile_team import config as config_mod
from agile_team import state
from agile_team.gates import StoryState, StoryStatus
from agile_team.git_ops import Git
from agile_team.requirement_ids import RequirementIds

FOLDER = "docs/requirements"


def git(repo: Path, *args: str) -> str:
    """Run real git in ``repo``."""
    env = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    done = subprocess.run(
        ["git", *env, *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def commit_reqs(repo: Path, *numbers: int) -> None:
    """Write requirement files and commit them."""
    (repo / FOLDER).mkdir(parents=True, exist_ok=True)
    for n in numbers:
        (repo / FOLDER / f"REQ-{n:03d}.md").write_text("x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "reqs")


class Sprint:
    """A real repo with a head holding REQ-001..010 and stories forked from it."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo
        git(repo, "init", "-q", "-b", "main")
        commit_reqs(repo, *range(1, 11))
        self.base = git(repo, "rev-parse", "HEAD")
        self.config = config_mod.from_raw(repo, {})
        self.state = state.RunState(sprint=1, story_branches=True)

    def story(self, story_id: str) -> StoryState:
        git(self.repo, "branch", f"s/{story_id}", self.base)
        story = StoryState(story_id, story_id, "design", sprint=1)
        story.branch, story.base_sha = f"s/{story_id}", self.base
        self.state.stories[story_id] = story
        return story

    def ids(self, story_id: str) -> RequirementIds:
        runtime = SimpleNamespace(state=self.state, config=self.config, main=Git(self.repo))
        return RequirementIds(runtime)  # type: ignore[arg-type]

    def write_on_branch(self, story_id: str, *numbers: int) -> None:
        git(self.repo, "checkout", "-q", f"s/{story_id}")
        commit_reqs(self.repo, *numbers)
        git(self.repo, "checkout", "-q", "main")


def test_parallel_architects_are_offered_different_ids(tmp_path: Path) -> None:
    sprint = Sprint(tmp_path)
    a, b = sprint.story("s1"), sprint.story("s2")
    first = sprint.ids("s1").reserve(a)
    second = sprint.ids("s2").reserve(b)
    assert first.next_free == "REQ-011"
    assert second.next_free != first.next_free
    assert b.req_block > a.req_block


def test_id_used_on_another_branch_is_not_offered(tmp_path: Path) -> None:
    sprint = Sprint(tmp_path)
    a, b = sprint.story("s1"), sprint.story("s2")
    sprint.write_on_branch("s1", 11, 12)
    assert sprint.ids("s2").reserve(b).next_free == "REQ-013"
    assert a.req_block == 0


def test_clash_names_the_id_and_the_other_story(tmp_path: Path) -> None:
    sprint = Sprint(tmp_path)
    sprint.story("s1")
    sprint.story("s2")
    sprint.write_on_branch("s1", 11)
    sprint.config = config_mod.from_raw(tmp_path, {})
    (tmp_path / FOLDER / "REQ-011.md").write_text("x\n")  # s2's design adds REQ-011 too
    lines = sprint.ids("s2").list_clashes("s2")
    assert any("REQ-011 is already used by s1" in line for line in lines)


def test_cancelled_story_frees_its_ids(tmp_path: Path) -> None:
    sprint = Sprint(tmp_path)
    a, b = sprint.story("s1"), sprint.story("s2")
    sprint.write_on_branch("s1", 11)
    assert sprint.ids("s2").reserve(b).next_free == "REQ-012"
    a.status = StoryStatus.CANCELLED
    git(tmp_path, "branch", "-D", "s/s1")
    b.req_block = 0
    assert sprint.ids("s2").reserve(b).next_free == "REQ-011"

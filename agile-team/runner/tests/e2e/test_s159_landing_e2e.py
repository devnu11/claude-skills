"""s159 landing end to end on real git: a story branch lands on the sprint branch only when green.

The scene is the s151 one (scratch repo, bare origin, FakePrs as the PR/CI service, green fake
checks); the checked-out team branch is renamed so ``team/story-*`` branches can exist beside it.
One group per AC id.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from agile_team import boundary as bd
from agile_team.ci import Bucket, Check
from agile_team.events import EventKind
from agile_team.gates import StoryState, Verdict
from agile_team.landing import Lander
from agile_team.upstream import Lease
from agile_team.workspaces import Workspaces

from ..conftest import git
from ..s29_helpers import FakePrs
from .test_s151_as_built_end_e2e import Scene
from .test_s151_as_built_end_e2e import scene as scene_fixture

scene = scene_fixture
SPRINT = "team/sprint-1"
RED = [Check("unit", Bucket.FAIL, "ci", "https://github.com/o/r/actions/runs/1/job/77")]


@dataclass
class LandPrs(FakePrs):
    """FakePrs that reads check runs by sha, as the landing branch (no PR) needs."""

    sha_list: list = field(default_factory=lambda: [Check("build", Bucket.PASS, "ci")])
    sha_seen: list[str] = field(default_factory=list)

    def sha_checks(self, sha: str) -> list:
        self.sha_seen.append(sha)
        return self.sha_list


def start_sprint(scene: Scene) -> str:
    """AC2.17: the sprint branch exists on the remote at the sprint's start head."""
    git(scene.repo, "branch", "-m", "team", "agile-team")
    scene.rt.state.upstream.team_branch = "agile-team"
    scene.rt.prs = LandPrs()
    start = scene.head()
    assert scene.rt.upstream.push(Lease(SPRINT, "", start)) is None
    scene.rt.state.upstream.stack = [
        bd.StackEntry(1, SPRINT, start, start, head=start, pushed=start)
    ]
    return start


def open_story(scene: Scene, story_id: str, path: str, text: str) -> StoryState:
    """Fork the story's branch at the sprint head in its worktree and commit one file."""
    rt = scene.rt
    story = StoryState(story_id, f"Title {story_id}", "land", sprint=1)
    rt.state.stories[story_id] = story
    ws = Workspaces(rt.git, rt.config)
    tree = ws.ensure(story, rt.state.upstream.stack[0].head)
    story.base_sha = rt.state.upstream.stack[0].head
    scene.commit(tree, path, text, f"{story_id}: add {path}")
    return story


def land(scene: Scene, story: StoryState) -> dict:
    return asyncio.run(Lander(scene.rt, asyncio.Lock()).land(story))


def entry(scene: Scene) -> bd.StackEntry:
    return scene.rt.state.upstream.stack[0]


def remote_sprint(scene: Scene) -> str:
    return git(scene.origin, "rev-parse", f"refs/heads/{SPRINT}").strip()


def test_ac2_1_ac2_4_a_green_story_lands_through_a_landing_branch_and_moves_the_sprint(
    scene: Scene,
) -> None:
    start = start_sprint(scene)
    story = open_story(scene, "s1", "src/a.py", "a = 1\n")
    own = git(scene.repo, "rev-parse", story.branch).strip()
    report = land(scene, story)
    assert report["gate"]["verdict"] == Verdict.PASS
    merge = report["land"]["merge"]
    parents = git(scene.repo, "log", "-1", "--format=%P", merge).split()
    assert parents == [start, own]
    assert git(scene.repo, "log", "-1", "--format=%s", merge).strip() == "merge(s1): Title s1"
    assert scene.head() == merge == entry(scene).head == entry(scene).pushed == remote_sprint(scene)
    assert scene.rt.prs.sha_seen and set(scene.rt.prs.sha_seen) == {merge}
    assert git(scene.origin, "branch", "--list", "team/story-s1-land").strip() == ""
    assert not (scene.rt.config.run_dir / "land").exists()
    assert story.landed.merge == merge
    [landed] = [e for e in scene.rt.events.events() if e.kind == EventKind.STORY_LANDED]
    assert landed.data["parents"] == parents


def test_ac2_2_the_story_commits_keep_their_hashes_at_landing(scene: Scene) -> None:
    start_sprint(scene)
    story = open_story(scene, "s1", "src/a.py", "a = 1\n")
    before = git(scene.repo, "rev-list", f"{story.base_sha}..{story.branch}").split()
    merge = land(scene, story)["land"]["merge"]
    after = git(scene.repo, "rev-list", f"{merge}^1..{merge}^2").split()
    assert after == before


def test_ac2_4_red_landing_ci_bounces_the_story_and_leaves_the_sprint_untouched(
    scene: Scene,
) -> None:
    start = start_sprint(scene)
    scene.rt.prs.sha_list = list(RED)
    story = open_story(scene, "s1", "src/a.py", "a = 1\n")
    report = land(scene, story)
    assert (
        report["gate"]["verdict"] == Verdict.BOUNCE and report["gate"]["bounce_to"] == "implement"
    )
    assert scene.head() == entry(scene).head == remote_sprint(scene) == start
    assert git(scene.origin, "branch", "--list", "team/story-s1-land").strip() == ""
    assert story.landed is None


def test_ac2_3_red_checks_bounce_before_any_push(scene: Scene) -> None:
    start = start_sprint(scene)
    scene.runner.results = {"pytest --cov": (1, "FAILED tests/test_x.py::test_x")}
    story = open_story(scene, "s1", "src/a.py", "a = 1\n")
    report = land(scene, story)
    assert (
        report["gate"]["verdict"] == Verdict.BOUNCE and report["gate"]["bounce_to"] == "implement"
    )
    assert scene.head() == remote_sprint(scene) == start
    assert scene.rt.prs.sha_seen == []


def test_ac2_4_no_check_runs_at_the_timeout_is_never_green(scene: Scene) -> None:
    start = start_sprint(scene)
    scene.rt.prs.sha_list = []
    scene.rt.config.gates.ci_timeout_s = 0
    story = open_story(scene, "s1", "src/a.py", "a = 1\n")
    report = land(scene, story)
    assert report["gate"]["verdict"] == Verdict.HOLD
    assert scene.head() == remote_sprint(scene) == start
    assert git(scene.origin, "branch", "--list", "team/story-s1-land").strip() == ""


def test_ac5_2_stories_land_in_the_order_they_are_landed_each_on_the_last(scene: Scene) -> None:
    start_sprint(scene)
    first = open_story(scene, "s1", "src/a.py", "a = 1\n")
    second = open_story(scene, "s2", "src/b.py", "b = 1\n")
    m1 = land(scene, first)["land"]["merge"]
    m2 = land(scene, second)["land"]["merge"]
    assert git(scene.repo, "log", "-1", "--format=%P", m2).split()[0] == m1
    subjects = git(scene.repo, "log", "--first-parent", "-2", "--format=%s", m2).splitlines()
    assert subjects == ["merge(s2): Title s2", "merge(s1): Title s1"]


def test_ac2_10_a_conflicting_story_goes_back_as_a_step_and_the_sprint_is_untouched(
    scene: Scene,
) -> None:
    start_sprint(scene)
    first = open_story(scene, "s1", "src/shared.py", "one\n")
    second = open_story(scene, "s2", "src/shared.py", "two\n")
    land(scene, first)
    sprint = scene.head()
    report = land(scene, second)
    assert report["gate"]["verdict"] == Verdict.BOUNCE and report["gate"]["bounce_to"] == "land"
    assert second.rebase is not None and second.rebase.files == ["src/shared.py"]
    assert scene.head() == sprint == remote_sprint(scene)


def test_ac2_11_unasked_permission_commits_but_pushes_nothing(scene: Scene) -> None:
    start = start_sprint(scene)
    scene.rt.state.upstream.push = bd.Permission.UNASKED
    story = open_story(scene, "s1", "src/a.py", "a = 1\n")
    report = land(scene, story)
    assert report["status"] == "waiting"
    assert scene.head() == remote_sprint(scene) == start
    assert git(scene.origin, "branch", "--list", "team/story-s1*").strip() == ""

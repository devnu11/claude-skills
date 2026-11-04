"""s180 end to end on real git: the runner's own commits during a landing's CI wait are carried.

The s159 scene (scratch repo, bare origin, ``FakePrs`` as the CI service). While the landing
waits on CI, a hook makes the runner's own bookkeeping commit on the main checkout and records
it, as ``story_intake`` and ``commit_step`` do. One group per AC id.
"""

from __future__ import annotations

from agile_team.events import EventKind
from agile_team.gates import Verdict
from agile_team.git_ops import Authored

from ..conftest import git
from .test_s151_as_built_end_e2e import Scene
from .test_s151_as_built_end_e2e import scene as scene_fixture
from .test_s159_landing_e2e import (
    entry,
    land,
    open_story,
    remote_sprint,
    start_sprint,
)

scene = scene_fixture


def during_ci(scene: Scene, action) -> None:
    """Run ``action`` once, on the first CI read of the landing."""
    prs, done = scene.rt.prs, []
    original = prs.list_checks

    def hooked(sha: str) -> list:
        if not done:
            done.append(sha)
            action()
        return original(sha)

    prs.list_checks = hooked


def bookkeeping_commit(scene: Scene, path: str, message: str) -> None:
    """The runner's own commit: write, commit on the main checkout, record it."""
    (scene.repo / path).parent.mkdir(parents=True, exist_ok=True)
    (scene.repo / path).write_text("data\n")
    scene.rt.git.commit_by([path], Authored(message))
    scene.rt.record_checkout()


def events(scene: Scene, kind: EventKind) -> list:
    return [e for e in scene.rt.events.events() if e.kind == kind]


def first_parent_subjects(scene: Scene) -> list[str]:
    out = git(scene.repo, "log", "--first-parent", "-3", "--format=%s", "HEAD")
    return out.splitlines()


def test_ac1_a_story_filed_during_ci_does_not_cost_the_landing_its_merge(scene: Scene) -> None:
    start_sprint(scene)
    story = open_story(scene, "s1", "src/a.py", "a = 1\n")
    during_ci(
        scene, lambda: bookkeeping_commit(scene, ".team/stories/s9.md", "docs(s9): file story")
    )
    report = land(scene, story)
    assert report["gate"]["verdict"] == Verdict.PASS
    merge = report["land"]["merge"]
    assert events(scene, EventKind.LANDING_DROPPED) == []
    [carried] = events(scene, EventKind.LANDING_CARRIED)
    assert carried.data["merge"] == merge
    assert story.landed.merge == merge
    assert git(scene.repo, "log", "-1", "--format=%P", scene.head()).split() == [merge]
    assert first_parent_subjects(scene)[:2] == ["docs(s9): file story", "merge(s1): Title s1"]
    assert scene.head() == entry(scene).head
    assert remote_sprint(scene) == merge


def test_ac2_a_storyless_step_commit_during_ci_follows_the_landed_merge(scene: Scene) -> None:
    start_sprint(scene)
    story = open_story(scene, "s1", "src/a.py", "a = 1\n")
    during_ci(
        scene, lambda: bookkeeping_commit(scene, "ci/config.toml", "chore: devops config change")
    )
    report = land(scene, story)
    merge = report["land"]["merge"]
    assert events(scene, EventKind.LANDING_DROPPED) == []
    assert story.landed.merge == merge == remote_sprint(scene)
    assert first_parent_subjects(scene)[:2] == [
        "chore: devops config change",
        "merge(s1): Title s1",
    ]


def test_ac3_a_dropped_landing_names_the_commits_that_moved_the_head(scene: Scene) -> None:
    start = start_sprint(scene)
    story = open_story(scene, "s1", "src/a.py", "a = 1\n")

    def merge_in_a_branch() -> None:
        git(scene.repo, "checkout", "-q", "-b", "side", start)
        bookkeeping_commit(scene, "side.txt", "side: work")
        git(scene.repo, "checkout", "-q", "agile-team")
        git(scene.repo, "merge", "--no-ff", "-q", "-m", "merge side", "side")
        scene.rt.record_checkout()

    during_ci(scene, merge_in_a_branch)
    report = land(scene, story)
    [dropped] = events(scene, EventKind.LANDING_DROPPED)
    subjects = [line for line in dropped.data["moved_by"]]
    assert any("side: work" in s for s in subjects) and any("merge side" in s for s in subjects)
    assert all(s[:7].isalnum() for s in subjects)
    assert dropped.data["refusal"]
    assert report["land"]["dropped"][0]["moved_by"] == dropped.data["moved_by"]

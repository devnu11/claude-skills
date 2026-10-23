"""s180 end to end on real git: the runner's own commits ride over a pushed, green landing."""

from __future__ import annotations

from pathlib import Path

from agile_team.ci import CiResult, CiVerdict
from agile_team.gates import Verdict

from ..conftest import git
from .test_s151_as_built_end_e2e import Scene
from .test_s159_landing_e2e import (
    entry,
    land,
    open_story,
    remote_sprint,
    start_sprint,
)
from .test_s159_landing_e2e import scene as scene_fixture
from .test_s163_resume_e2e import GREEN, PENDING, dropped

scene = scene_fixture


def own_commit(scene: Scene, path: str, subject: str) -> str:
    """The runner's bookkeeping commit on the main checkout, then recorded as the head."""
    (Path(scene.repo) / path).parent.mkdir(parents=True, exist_ok=True)
    (Path(scene.repo) / path).write_text(subject + "\n")
    sha = scene.rt.git.commit([path], subject)
    scene.rt.record_checkout()
    return sha


def held(scene: Scene):
    """Open s1, land it on pending CI (HOLD) and return the story and its pushed merge."""
    start_sprint(scene)
    rt = scene.rt
    story = open_story(scene, "s1", "src/a.py", "a = 1\n")
    rt.prs.sha_list, rt.config.gates.ci_timeout_s = list(PENDING), 0
    assert land(scene, story)["gate"]["verdict"] == Verdict.HOLD
    assert story.landed.pushed
    return story, story.landed.merge


def first_parent(scene: Scene) -> list[str]:
    return git(scene.repo, "log", "--first-parent", "--format=%s", "HEAD").splitlines()


def check_carried(scene: Scene, report: dict, merge: str, subject: str) -> None:
    """The landing kept its merge; the own commit follows it on the sprint branch."""
    assert report["land"]["merge"] == merge
    assert dropped(scene) == []
    log = first_parent(scene)
    assert log[0] == subject
    assert log[1].startswith("merge(s1)")
    assert entry(scene).pushed == remote_sprint(scene) == merge
    assert entry(scene).head == git(scene.repo, "rev-parse", "HEAD").strip() != merge


def resume_green(scene: Scene, story) -> dict:
    scene.rt.prs.sha_list, scene.rt.config.gates.ci_timeout_s = list(GREEN), 30
    return land(scene, story)


def test_ac1_a_story_file_committed_while_held_is_carried_after_the_merge(scene: Scene) -> None:
    story, merge = held(scene)
    own_commit(scene, ".team/stories/s9.md", "story(s9): file")
    report = resume_green(scene, story)
    check_carried(scene, report, merge, "story(s9): file")


def test_ac1_a_story_file_committed_during_the_ci_wait_carries(scene: Scene, monkeypatch) -> None:
    story, merge = held(scene)

    class Watch:
        def __init__(self, prs: object, limit_s: float) -> None:
            pass

        async def poll_result(self, sha: str, reran: list) -> CiResult:
            own_commit(scene, ".team/stories/s9.md", "story(s9): file")
            return CiResult(0, "", sha, CiVerdict.GREEN, [])

    monkeypatch.setattr("agile_team.landing.ShaWatch", Watch)
    check_carried(scene, resume_green(scene, story), merge, "story(s9): file")


def test_ac2_a_storyless_step_commit_follows_the_landed_merge(scene: Scene) -> None:
    story, merge = held(scene)
    own_commit(scene, "agile-team.toml.d/ci.toml", "chore(team): devops step")
    report = resume_green(scene, story)
    check_carried(scene, report, merge, "chore(team): devops step")


def test_ac3_a_dropped_landing_names_every_moved_commit(scene: Scene) -> None:
    story, old = held(scene)
    rt = scene.rt
    second = open_story(scene, "s2", "src/b.py", "b = 1\n")
    rt.prs.sha_list, rt.config.gates.ci_timeout_s = list(GREEN), 30
    m2 = land(scene, second)["land"]["merge"]
    report = land(scene, story)
    drops = dropped(scene)
    assert [d["why"] for d in drops] == ["sprint head moved"]
    assert drops[0]["merge"] == old
    assert any(m2[:7] in line and "merge(s2)" in line for line in drops[0]["moved"])
    assert report["land"]["dropped"][0]["moved"] == drops[0]["moved"]

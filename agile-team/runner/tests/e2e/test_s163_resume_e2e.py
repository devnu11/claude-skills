"""s163 AC3 end to end on real git: the B2 scenario, a pushed landing whose sprint head moved."""

from __future__ import annotations

from agile_team.ci import Bucket, Check
from agile_team.events import EventKind
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

scene = scene_fixture

PENDING = [Check("build", Bucket.PENDING, "ci")]
GREEN = [Check("build", Bucket.PASS, "ci")]


def dropped(scene: Scene) -> list[dict]:
    return [e.data for e in scene.rt.events.events() if e.kind == EventKind.LANDING_DROPPED]


def test_ac3_s1_holds_on_pending_ci_s2_lands_and_s1_merges_afresh_on_s2(scene: Scene) -> None:
    start_sprint(scene)
    rt = scene.rt
    first = open_story(scene, "s1", "src/a.py", "a = 1\n")
    second = open_story(scene, "s2", "src/b.py", "b = 1\n")
    rt.prs.sha_list, rt.config.gates.ci_timeout_s = list(PENDING), 0
    held = land(scene, first)
    assert held["gate"]["verdict"] == Verdict.HOLD
    old = first.landed.merge
    assert first.landed.pushed

    rt.prs.sha_list, rt.config.gates.ci_timeout_s = list(GREEN), 30
    m2 = land(scene, second)["land"]["merge"]
    assert remote_sprint(scene) == entry(scene).head == m2

    report = land(scene, first)
    m1 = report["land"]["merge"]
    assert m1 != old
    assert git(scene.repo, "log", "-1", "--format=%P", m1).split()[0] == m2
    assert remote_sprint(scene) == entry(scene).head == entry(scene).pushed == m1
    drops = dropped(scene)
    assert [d["why"] for d in drops] == ["sprint head moved"]
    assert drops[0]["merge"] == old
    assert first.landed.merge == m1


def test_ac3_a_resume_with_the_merge_still_on_the_head_makes_no_new_merge(scene: Scene) -> None:
    start_sprint(scene)
    rt = scene.rt
    story = open_story(scene, "s1", "src/a.py", "a = 1\n")
    rt.prs.sha_list, rt.config.gates.ci_timeout_s = list(PENDING), 0
    assert land(scene, story)["gate"]["verdict"] == Verdict.HOLD
    merge = story.landed.merge
    rt.prs.sha_list, rt.config.gates.ci_timeout_s = list(GREEN), 30
    assert land(scene, story)["land"]["merge"] == merge
    assert dropped(scene) == []

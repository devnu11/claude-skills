"""s163 AC4 end to end on real git: stack entries main already has are dropped."""

from __future__ import annotations

from agile_team import boundary as bd
from agile_team.events import EventKind
from agile_team.switchover import drop_entries, find_merged

from ..conftest import git
from .test_s151_as_built_end_e2e import Scene, team_work
from .test_s151_as_built_end_e2e import scene as scene_fixture

scene = scene_fixture


def push_entry(scene: Scene, head: str) -> bd.StackEntry:
    rt = scene.rt
    base = bd.StackEntry(1, "team/sprint-1", head, head, head=head, pushed=head)
    rt.state.upstream.stack = [base]
    return base


def drop_all(scene: Scene) -> list[bd.StackEntry]:
    rt = scene.rt
    merged = find_merged(rt.upstream, [e.head for e in rt.state.upstream.stack])
    return drop_entries(rt, merged)


def reasons(scene: Scene) -> list[str]:
    return [e.data["why"] for e in scene.rt.events.events() if e.kind == EventKind.STACK_DROPPED]


def test_ac4_an_entry_whose_head_main_contains_is_dropped(scene: Scene) -> None:
    head = team_work(scene)
    git(scene.repo, "push", "-q", "origin", f"{head}:refs/heads/main")
    git(scene.repo, "fetch", "-q", "origin")
    push_entry(scene, head)
    assert len(drop_all(scene)) == 1
    assert scene.rt.state.upstream.stack == []
    assert reasons(scene) == ["contained"]


def test_ac4_an_entry_main_has_as_rebased_copies_is_dropped(scene: Scene) -> None:
    head = team_work(scene)
    scene.commit(scene.other, "main.txt", "m\n", "main moves first")
    git(scene.other, "fetch", "-q", str(scene.repo), "team")
    git(scene.other, "cherry-pick", head)
    git(scene.other, "push", "-q", "origin", "main")
    git(scene.repo, "fetch", "-q", "origin")
    push_entry(scene, head)
    assert len(drop_all(scene)) == 1
    assert reasons(scene) == ["patch-equivalent"]


def test_ac4_an_entry_with_a_commit_main_lacks_stays(scene: Scene) -> None:
    head = team_work(scene)
    push_entry(scene, head)
    assert drop_all(scene) == []
    assert len(scene.rt.state.upstream.stack) == 1
    assert reasons(scene) == []

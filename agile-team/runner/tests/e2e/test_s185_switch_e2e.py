"""s185/AC3 (REQ-241): the story-branch switch against real git, ahead and patch-equivalent."""

from __future__ import annotations

from agile_team.gates import StoryState
from agile_team.switchover import AHEAD, count_ahead, list_refusals, read_facts

from ..conftest import git
from .test_s151_as_built_end_e2e import Scene, scene, team_work  # noqa: F401


def refusals(scene: Scene) -> list[str]:  # noqa: F811
    """The switch refusals for a Sprint Backlog story still in design."""
    scene.rt.state.stories["s2"] = StoryState("s2", "Two", "design", sprint=1)
    return list_refusals(read_facts(scene.rt, ["s2"]))


def test_ac3_a_commit_main_lacks_is_ahead(scene: Scene) -> None:  # noqa: F811
    main_before = git(scene.repo, "rev-parse", "origin/main").strip()
    team_work(scene)
    assert count_ahead(scene.rt) >= 1
    found = refusals(scene)
    assert found == [AHEAD.format(n=count_ahead(scene.rt))]
    assert git(scene.repo, "rev-parse", "origin/main").strip() == main_before


def test_ac3_a_patch_equivalent_copy_is_not_ahead(scene: Scene) -> None:  # noqa: F811
    sha = team_work(scene)
    git(scene.other, "fetch", "-q", scene.repo.as_posix(), "team")
    git(scene.other, "cherry-pick", sha)
    git(scene.other, "push", "-q", "origin", "main")
    git(scene.repo, "fetch", "-q", "origin")
    assert count_ahead(scene.rt) == 0
    assert not any(AHEAD.split("{")[0] in line for line in refusals(scene))

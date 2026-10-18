"""s151 AC6 end to end on real git: a sprint-end rebase conflict goes to DevOps in a worktree.

Reuses the scene of the as-built e2e (scratch repo, bare origin, FakePrs, green fake checks).
The DevOps step is played by hand: the test resolves the conflict inside the scratch worktree
exactly as the role's brief says, then hands the runner the role's report.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from agile_team import scratch_rebase as sr
from agile_team.boundary import BoundaryHold, FixCase, Stage, StepKind
from agile_team.dispatch import StepRequest

from ..conftest import git
from .test_s151_as_built_end_e2e import SCRATCH_BRANCH, Scene, team_work
from .test_s151_as_built_end_e2e import scene as scene_fixture

scene = scene_fixture


def conflicting(scene: Scene) -> str:
    """The team and main both add ``shared.txt`` with different text; stops at the DevOps step."""
    built = team_work(scene, "shared.txt", "team side\n")
    scene.main_moves("shared.txt", "main side\n")
    scene.open_end()
    scene.drive()
    return built


def worktree(scene: Scene) -> Path:
    return scene.rt.config.run_dir / sr.REBASE_DIR


def resolve_by_hand(scene: Scene, text: str = "both sides\n") -> None:
    """What DevOps does in the worktree: edit, add, ``git rebase --continue``."""
    wt = worktree(scene)
    (wt / "shared.txt").write_text(text)
    git(wt, "add", "shared.txt")
    env = {**os.environ, "GIT_EDITOR": "true"}
    subprocess.run(
        ["git", "rebase", "--continue"], cwd=wt, env=env, check=True, capture_output=True
    )


def devops_reports(scene: Scene, status: str = "done", summary: str = "kept both") -> None:
    scene.br.after_fix({"role": "devops", "status": status, "summary": summary})


def test_ac6_1_a_conflict_aborts_leaves_the_team_branch_and_hands_it_to_devops(
    scene: Scene,
) -> None:
    built = conflicting(scene)
    b = scene.boundary
    assert b.hold is None and b.stage is Stage.REPLAY
    assert scene.head() == built and git(scene.repo, "status", "--porcelain").strip() == ""
    assert not (scene.repo / ".git" / "rebase-merge").exists()
    assert b.failure.case is FixCase.REBASE_CONFLICT and b.failure.files == ["shared.txt"]
    due = scene.br.due()
    assert due.kind is StepKind.REBASE_FIX and due.role == "devops"
    assert "shared.txt" in due.brief and b.failure.commit[:12] in due.brief
    assert not any("by hand" in n for n in scene.notes())


def test_ac6_2_the_devops_step_works_in_a_worktree_outside_the_team_checkout(
    scene: Scene,
) -> None:
    built = conflicting(scene)
    wt = worktree(scene)
    assert wt.is_dir() and SCRATCH_BRANCH in git(scene.repo, "branch", "--list")
    assert git(scene.repo, "branch", "--show-current").strip() == "team"
    plan = scene.rt.plan(StepRequest("devops", "fix", None, StepKind.REBASE_FIX))
    rel = wt.relative_to(scene.rt.config.repo).as_posix()
    assert plan.scope.write == [f"{rel}/**"] and plan.launch.env["GIT_EDITOR"] == "true"
    assert "Never merge, squash" in scene.br.due().brief
    resolve_by_hand(scene)
    assert git(wt, "rev-list", "--merges", "origin/main..HEAD").strip() == ""
    assert scene.head() == built


def test_ac6_2_the_full_checks_run_in_the_worktree(scene: Scene) -> None:
    conflicting(scene)
    resolve_by_hand(scene)
    devops_reports(scene)
    scene.br.step()
    assert worktree(scene) in scene.shell_paths


def test_ac6_3_a_clean_result_moves_the_team_branch_remaps_and_continues(scene: Scene) -> None:
    built = conflicting(scene)
    resolve_by_hand(scene)
    devops_reports(scene)
    scene.drive()
    assert scene.head() != built and scene.rt.state.stories["s1"].commit == scene.head()
    assert git(scene.repo, "merge-base", "--is-ancestor", "origin/main", "HEAD") == ""
    assert (scene.repo / "shared.txt").read_text() == "both sides\n"
    replayed = git(scene.origin, "rev-parse", "refs/heads/team/sprint-1-r1").strip()
    assert replayed == scene.head() and scene.own.as_is == built
    assert scene.boundary is None
    assert not worktree(scene).exists()
    assert SCRATCH_BRANCH not in git(scene.repo, "branch", "--list")


def test_ac6_4_a_failed_devops_step_holds_with_conflict_notes_and_scratch_branch(
    scene: Scene,
) -> None:
    built = conflicting(scene)
    devops_reports(scene, "failed", "the two edits contradict")
    scene.br.step()
    assert scene.boundary.hold is BoundaryHold.REBASE_CONFLICT and scene.head() == built
    [note] = [n for n in scene.notes() if "could not settle" in n]
    for part in ("shared.txt", "the two edits contradict", SCRATCH_BRANCH):
        assert part in note
    assert worktree(scene).is_dir()


def test_ac6_4_a_result_with_a_merge_commit_is_refused_and_holds(scene: Scene) -> None:
    built = conflicting(scene)
    wt = worktree(scene)
    git(wt, "rebase", "--abort")
    git(wt, "reset", "-q", "--hard", "origin/main")
    git(wt, "merge", "-q", "--no-ff", "-s", "ours", "-m", "merge", built)
    devops_reports(scene)
    scene.br.step()
    assert scene.boundary.hold is BoundaryHold.REBASE_CONFLICT and scene.head() == built
    assert scene.remote_branch() == built

"""s151 end to end on real git: the sprint end pushes as built, gates on CI, rebases, pushes again.

A scratch repo whose ``origin`` is a bare clone, a second clone that moves ``origin/main``,
``FakePrs`` as the PR service and CI, and green fake full checks. One group per AC id.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from agile_team import boundary as bd
from agile_team import handover
from agile_team import scratch_rebase as sr
from agile_team.boundary import BoundaryHold, Edge, Stage, StepKind
from agile_team.boundary_runner import BoundaryRunner
from agile_team.ci import Bucket, Check
from agile_team.dispatch import StepRequest
from agile_team.events import EventKind
from agile_team.gates import StoryState, StoryStatus
from agile_team.git_ops import Git
from agile_team.po_tools import Tools
from agile_team.upstream import Pr, PrMode, PrState

from ..conftest import git, set_git_identity
from ..s29_helpers import FakePrs
from ..test_boundary_runner import GREEN as GOOD_CHECKS
from ..test_boundary_runner import PrefixRunner

LINK = "https://github.com/o/r/actions/runs/1/job/77"
PASS = [Check("unit", Bucket.PASS, "ci", LINK)]
FAIL = [Check("unit", Bucket.FAIL, "ci", LINK)]
BRANCH = "team/sprint-1"
SCRATCH_BRANCH = "agile-team/rebase-sprint-1"


class Prs(FakePrs):
    """FakePrs whose CI watch times out while the checks are pending (no sleeping)."""

    def wait_checks(self, number: int, seconds: float) -> bool:
        return all(c.bucket is not Bucket.PENDING for c in self.check_list)


@dataclass
class Scene:
    """The team repo, its bare origin, a clone that moves main, and the runtime on the team repo."""

    repo: Path
    origin: Path
    other: Path
    rt: object
    prs: Prs
    runner: PrefixRunner
    shell_paths: list[Path] = field(default_factory=list)

    @property
    def br(self) -> BoundaryRunner:
        return BoundaryRunner(self.rt)

    @property
    def boundary(self) -> bd.Boundary:
        return self.rt.state.boundary

    @property
    def own(self) -> bd.StackEntry:
        return self.rt.state.upstream.stack[0]

    def head(self) -> str:
        return git(self.repo, "rev-parse", "HEAD").strip()

    def remote_branch(self) -> str:
        return git(self.origin, "rev-parse", f"refs/heads/{BRANCH}").strip()

    def commit(self, repo: Path, path: str, text: str, message: str) -> str:
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", message)
        return git(repo, "rev-parse", "HEAD").strip()

    def main_moves(self, path: str = "main.txt", text: str = "m\n") -> str:
        """The other clone lands a commit on origin/main; the team repo then fetches."""
        sha = self.commit(self.other, path, text, f"main adds {path}")
        git(self.other, "push", "-q", "origin", "main")
        git(self.repo, "fetch", "-q", "origin")
        return sha

    def open_end(self) -> bd.Boundary:
        self.rt.state.boundary = bd.Boundary(Edge.END, 1)
        return self.boundary

    def run_to(self, stage: Stage) -> None:
        """Step the boundary until it reaches ``stage``, holds or finishes."""
        while self.boundary and self.boundary.stage is not stage and not self.boundary.hold:
            self.br.step()

    def drive(self) -> None:
        """Step until the boundary is held, due for a fix, or finished."""
        while (due := self.br.due()) is not None and due.kind is StepKind.BOUNDARY:
            self.br.step()

    def notes(self) -> list[str]:
        return [m.text for m in self.rt.relay.messages()]

    def outcomes(self) -> list[dict]:
        events = [e for e in self.rt.events.events() if e.kind == EventKind.BOUNDARY]
        return [e.data for e in events]


@pytest.fixture
def scene(configured: Path, tmp_path: Path, make_runtime) -> Scene:
    origin, other = tmp_path / "origin.git", tmp_path / "other"
    git(tmp_path, "clone", "-q", "--bare", str(configured), str(origin))
    git(configured, "remote", "add", "origin", str(origin))
    git(configured, "fetch", "-q", "origin")
    git(configured, "checkout", "-q", "-b", "team")
    git(tmp_path, "clone", "-q", str(origin), str(other))
    set_git_identity(other)
    prs, runner = Prs(), PrefixRunner(GOOD_CHECKS)
    seen: list[Path] = []

    def shell(path: Path) -> PrefixRunner:
        seen.append(path)
        return runner

    rt = make_runtime(prs=prs, shell=shell)
    rt.state.sprint = 1
    rt.state.upstream.push = bd.Permission.YES
    rt.state.stories["s1"] = StoryState("s1", "One", "done", status=StoryStatus.DONE, sprint=1)
    prs.check_list = list(PASS)
    return Scene(configured, origin, other, rt, prs, runner, seen)


def team_work(scene: Scene, path: str = "src/team.py", text: str = "t = 1\n") -> str:
    sha = scene.commit(scene.repo, path, text, "team adds " + path)
    scene.rt.state.stories["s1"].commit = sha
    return sha


# ----- AC1.1 / AC1.2: the as-built push and the PR -----------------------------------------


def test_ac1_1_the_first_push_sends_the_team_branch_as_it_is(scene: Scene) -> None:
    built = team_work(scene)
    scene.main_moves()
    scene.open_end()
    scene.run_to(Stage.CI)
    assert scene.remote_branch() == built == scene.head()
    main = git(scene.repo, "rev-parse", "origin/main").strip()
    assert git(scene.repo, "merge-base", built, "origin/main").strip() != main
    assert scene.own.as_is == scene.own.pushed == built


def test_ac1_1_a_remote_moved_by_someone_else_is_refused_by_the_lease(scene: Scene) -> None:
    team_work(scene)
    scene.open_end()
    scene.run_to(Stage.CI)
    scene.commit(scene.other, "x.txt", "x\n", "someone pushes")
    git(scene.other, "push", "-q", "-f", "origin", f"HEAD:refs/heads/{BRANCH}")
    scene.boundary.stage = Stage.PUSH
    team_work(scene, "src/more.py", "m = 1\n")
    scene.br.step()
    assert scene.boundary.hold is BoundaryHold.PUSH_REJECTED


def test_ac1_2_the_pr_is_opened_from_the_sprint_branch_onto_the_target(scene: Scene) -> None:
    team_work(scene)
    scene.open_end()
    scene.run_to(Stage.CI)
    [(_, spec)] = [c for c in scene.prs.calls if c[0] == "create"]
    assert spec.branch == BRANCH and spec.base == "main" and spec.mode is PrMode.READY
    assert scene.own.pr == 1


def test_ac1_2_an_open_pr_for_the_branch_is_reused(scene: Scene) -> None:
    team_work(scene)
    scene.prs.prs[BRANCH] = Pr(7, "https://example/pull/7", PrState.OPEN, False, "main")
    scene.open_end()
    scene.run_to(Stage.CI)
    assert [c for c in scene.prs.calls if c[0] in ("create", "edit")] == []
    assert scene.own.pr == 7


# ----- AC2: the CI gate --------------------------------------------------------------------


def test_ac2_1_nothing_is_rebased_before_green_and_it_is_after(scene: Scene) -> None:
    built = team_work(scene)
    scene.main_moves()
    scene.prs.check_list = [Check("unit", Bucket.PENDING, "ci", "")]
    scene.open_end()
    scene.drive()
    assert scene.boundary.hold is BoundaryHold.CI_PENDING and scene.boundary.stage is Stage.CI
    assert scene.head() == built
    scene.prs.check_list = list(PASS)
    scene.boundary.hold = None
    scene.drive()
    assert scene.boundary is None
    assert scene.head() != built
    assert git(scene.repo, "merge-base", "--is-ancestor", "origin/main", "HEAD") == ""


def test_ac2_2_red_holds_the_boundary_and_tells_the_liaison_the_failing_checks(
    scene: Scene,
) -> None:
    built = team_work(scene)
    scene.main_moves()
    scene.prs.check_list = list(FAIL)
    scene.open_end()
    scene.drive()
    assert scene.boundary.hold is BoundaryHold.CI_FAILED and scene.head() == built
    [note] = [n for n in scene.notes() if "failed on the team branch as built" in n]
    assert "unit" in note and "nothing is rebased" in note
    out = json.loads(asyncio.run(Tools(scene.rt).continue_boundary({"note": ""}))["content"][0]["text"])
    assert "refused" in json.dumps(out).lower() or out.get("status") != "continued"
    assert scene.boundary.hold is BoundaryHold.CI_FAILED


# ----- AC3: the rebase, the second push, the second CI -------------------------------------


def test_ac3_1_after_green_the_team_branch_is_rebased_onto_the_target(scene: Scene) -> None:
    built = team_work(scene)
    scene.main_moves()
    scene.open_end()
    scene.drive()
    assert git(scene.repo, "merge-base", "--is-ancestor", "origin/main", "HEAD") == ""
    assert git(scene.repo, "rev-list", "--merges", "origin/main..HEAD").strip() == ""
    story = scene.rt.state.stories["s1"].commit
    assert story != built and story == scene.head()
    assert any(o["outcome"] == "rebased" for o in scene.outcomes())


def test_ac3_2_the_rebased_branch_goes_to_the_same_branch_and_keeps_the_as_built_sha(
    scene: Scene,
) -> None:
    built = team_work(scene)
    scene.main_moves()
    scene.open_end()
    scene.run_to(Stage.PUSH_REBASED)
    scene.drive()
    assert scene.remote_branch() == scene.head() != built
    assert scene.own.as_is == built
    assert len([c for c in scene.prs.calls if c[0] == "create"]) == 1
    assert any("rebased onto" in n and built[:7] in n for n in scene.notes())


def test_ac3_2_a_remote_moved_since_the_as_built_push_holds_push_rejected(scene: Scene) -> None:
    team_work(scene)
    scene.main_moves()
    scene.open_end()
    scene.run_to(Stage.PUSH_REBASED)
    scene.commit(scene.other, "x.txt", "x\n", "someone pushes")
    git(scene.other, "push", "-q", "-f", "origin", f"HEAD:refs/heads/{BRANCH}")
    scene.br.step()
    assert scene.boundary.hold is BoundaryHold.PUSH_REJECTED


def test_ac3_2_a_rebase_that_changes_nothing_pushes_nothing_and_finishes_green(
    scene: Scene,
) -> None:
    built = team_work(scene)
    scene.open_end()
    scene.drive()
    assert scene.boundary is None and scene.remote_branch() == built == scene.head()
    assert scene.outcomes()[-1]["ci"] == "green"
    assert not any("now holds the team branch rebased" in n for n in scene.notes())


def test_ac3_3_a_red_rebased_ci_is_reported_and_does_not_hold(scene: Scene) -> None:
    team_work(scene)
    scene.main_moves()
    scene.open_end()
    scene.run_to(Stage.CI_REBASED)
    scene.prs.check_list = list(FAIL)
    scene.drive()
    assert scene.boundary is None and scene.rt.state.boundary is None
    assert scene.outcomes()[-1]["outcome"] == "done" and scene.outcomes()[-1]["ci"] == "red"
    assert scene.own.ci.verdict.value == "red"
    assert any("is NOT ready" in n for n in scene.notes())


def test_ac3_3_a_green_rebased_ci_finishes_ready(scene: Scene) -> None:
    team_work(scene)
    scene.main_moves()
    scene.open_end()
    scene.drive()
    assert scene.outcomes()[-1]["outcome"] == "done" and scene.outcomes()[-1]["ci"] == "green"
    assert scene.own.ci.head == scene.head()


# ----- AC4: the order in code, no review stage ---------------------------------------------


@pytest.mark.parametrize("ci", ["none", "red", "other"])
def test_ac4_1_the_rebase_is_refused_without_green_ci_on_the_pushed_sha(
    scene: Scene, ci: str
) -> None:
    from agile_team.ci import CiResult, CiVerdict

    built = team_work(scene)
    scene.main_moves()
    scene.open_end()
    scene.run_to(Stage.CI)
    states = {
        "none": None,
        "red": CiResult(1, "u", built, CiVerdict.RED, list(FAIL)),
        "other": CiResult(1, "u", "f" * 40, CiVerdict.GREEN, list(PASS)),
    }
    scene.own.ci = states[ci]
    scene.boundary.stage = Stage.REBASE
    calls: list[str] = []
    scene.rt.upstream.rebase_onto = lambda old: calls.append(old)
    scene.br.step()
    assert calls == [] and scene.head() == built
    assert scene.outcomes()[-1]["outcome"] == "refused"
    assert scene.boundary.stage is Stage.CI


def test_ac4_1_the_stages_run_in_the_documented_order() -> None:
    order = [s.value for s in bd.STAGES]
    assert order == ["sync", "check", "push", "ci", "rebase", "push-rebased", "ci-rebased"]
    assert bd.rebase_refusal(None) == bd.NO_AS_IS


def test_ac4_2_there_is_no_review_stage_no_restack_and_no_cherry_pick(scene: Scene) -> None:
    assert {s.value for s in Stage}.isdisjoint({"review", "restack"})
    for name in ("agile_team.stack", "agile_team.restack"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(name)
    team_work(scene)
    scene.main_moves()
    scene.open_end()
    scene.drive()
    assert "cherry-pick" not in git(scene.repo, "reflog", "--format=%gs", "HEAD")
    assert not (scene.rt.config.run_dir / "review").exists()


# ----- AC6: a conflict goes to DevOps in a scratch worktree --------------------------------


def conflict_scene(scene: Scene) -> str:
    """Two team commits, the first conflicts with main; the sprint end is at its rebase stage."""
    scene.commit(scene.repo, "src/app.py", "x = 2\n", "team edits app")
    team_work(scene, "src/two.py", "two = 1\n")
    scene.main_moves("src/app.py", "x = 3\n")
    scene.open_end()
    scene.run_to(Stage.REBASE)
    return scene.head()


def worktree(scene: Scene) -> Path:
    return scene.rt.config.run_dir / sr.REBASE_DIR


def resolve(scene: Scene, text: str = "x = 5\n") -> None:
    path = worktree(scene)
    (path / "src" / "app.py").write_text(text)
    git(path, "add", "src/app.py")
    env_git = Git(path)
    env_git.attempt("-c", "core.editor=true", "rebase", "--continue")


def test_ac6_1_a_conflict_is_aborted_and_handed_to_a_devops_step(scene: Scene) -> None:
    built = conflict_scene(scene)
    scene.br.step()
    assert scene.head() == built and scene.boundary.hold is None
    assert git(scene.repo, "status", "--porcelain").strip() == ""
    last = scene.outcomes()[-1]
    assert last["outcome"] == "conflict" and last["files"] == ["src/app.py"]
    due = scene.br.due()
    assert due.kind is StepKind.REBASE_FIX and due.role == "devops"
    for part in ("team edits app", "src/app.py", str(worktree(scene)), SCRATCH_BRANCH):
        assert part in due.brief
    assert git(worktree(scene), "branch", "--show-current").strip() == SCRATCH_BRANCH
    assert "rebas" in git(worktree(scene), "status")
    assert not any("by hand" in n for n in scene.notes())


def test_ac6_2_the_fix_step_writes_only_the_worktree_and_runs_checks_there(scene: Scene) -> None:
    conflict_scene(scene)
    scene.br.step()
    plan = scene.rt.plan(StepRequest("devops", "fix", None, StepKind.REBASE_FIX))
    rel = worktree(scene).relative_to(scene.repo).as_posix()
    assert plan.scope.write == [f"{rel}/**"]
    assert str(plan.scope.git_workspace) == str(worktree(scene).resolve())
    assert plan.launch.env["GIT_EDITOR"] == "true"
    resolve(scene)
    scene.br.after_fix({"status": "done", "summary": "kept both"})
    scene.shell_paths.clear()
    scene.br.step()
    assert worktree(scene).resolve() in [p.resolve() for p in scene.shell_paths]


def test_ac6_2_each_bad_resolution_is_refused(scene: Scene) -> None:
    old = conflict_scene(scene)
    scene.br.step()
    scratch = sr.ScratchRebase(scene.rt.upstream, worktree(scene), SCRATCH_BRANCH)
    assert "not finished" in scratch.refusal(old)
    resolve(scene)
    assert scratch.refusal(old) == ""
    tree = Git(worktree(scene))
    (worktree(scene) / "dirty.txt").write_text("d\n")
    assert "uncommitted" in scratch.refusal(old)
    (worktree(scene) / "dirty.txt").unlink()
    git(worktree(scene), "commit", "-q", "--amend", "-m", "reworded")
    assert "not the team branch's commits" in scratch.refusal(old)
    git(worktree(scene), "reset", "-q", "--hard", "HEAD~1")
    assert "not the team branch's commits" in scratch.refusal(old)
    assert tree.head() == scratch.head()


def test_ac6_3_a_clean_resolution_moves_the_team_branch_remaps_and_pushes(scene: Scene) -> None:
    built = conflict_scene(scene)
    scene.br.step()
    resolve(scene)
    result_head = git(worktree(scene), "rev-parse", "HEAD").strip()
    scene.br.after_fix({"status": "done", "summary": "kept both"})
    scene.br.step()
    assert scene.head() == result_head != built
    assert scene.rt.state.stories["s1"].commit == result_head
    assert scene.boundary.stage is Stage.PUSH_REBASED
    assert not worktree(scene).exists()
    assert git(scene.repo, "branch", "--list", SCRATCH_BRANCH).strip() == ""
    scene.drive()
    assert scene.remote_branch() == result_head and scene.own.as_is == built


def test_ac6_3_a_team_branch_that_moved_meanwhile_is_never_reset(scene: Scene) -> None:
    conflict_scene(scene)
    scene.br.step()
    resolve(scene)
    scene.br.after_fix({"status": "done", "summary": "kept both"})
    moved = scene.commit(scene.repo, "src/late.py", "l = 1\n", "late")
    scene.br.step()
    assert scene.boundary.hold is BoundaryHold.ERROR and scene.head() == moved
    assert "moved" in scene.outcomes()[-1]["reason"]


def test_ac6_4_a_failed_devops_step_holds_with_notes_and_the_scratch_branch(scene: Scene) -> None:
    built = conflict_scene(scene)
    scene.br.step()
    scene.br.after_fix({"status": "failed", "summary": "cannot merge the intent"})
    scene.br.step()
    assert scene.boundary.hold is BoundaryHold.REBASE_CONFLICT and scene.head() == built
    [note] = [n for n in scene.notes() if "could not settle it" in n]
    assert "cannot merge the intent" in note and SCRATCH_BRANCH in note
    assert worktree(scene).exists()
    line = next(r.line for r in handover.HANDOVERS if r.trigger.value == "rebase_conflict")
    assert "{branch}" in line and "{notes}" in line


def test_ac6_4_failing_full_checks_hold_the_same_way(scene: Scene) -> None:
    built = conflict_scene(scene)
    scene.br.step()
    resolve(scene)
    scene.runner.results = {"pytest --cov": (1, "FAILED tests/test_x.py")}
    scene.br.after_fix({"status": "done", "summary": "kept both"})
    scene.br.step()
    assert scene.boundary.hold is BoundaryHold.REBASE_CONFLICT and scene.head() == built
    assert "full checks failed" in scene.outcomes()[-1]["reason"]


def test_ac6_4_continue_boundary_runs_the_rebase_and_devops_again_with_the_note(
    scene: Scene,
) -> None:
    conflict_scene(scene)
    scene.br.step()
    scene.br.after_fix({"status": "failed", "summary": "stuck"})
    scene.br.step()
    asyncio.run(Tools(scene.rt).continue_boundary({"note": "prefer main's wording"}))
    assert scene.boundary.rebase_fix is None
    scene.br.step()
    due = scene.br.due()
    assert due.kind is StepKind.REBASE_FIX and due.brief.endswith("prefer main's wording")
    assert "rebas" in git(worktree(scene), "status")

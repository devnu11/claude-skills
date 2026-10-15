"""s153 AC6: the conflict path's data, state loading and scope exist; no step of it is due yet."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from agile_team import boundary as bd
from agile_team import dispatch, guard, roles, system
from agile_team.boundary import BoundaryHold, Edge, FixCase, Stage, StepKind
from agile_team.state import RunState
from agile_team.upstream import Rebase, SyncOutcome

from .test_boundary_runner import Env
from .test_s151_end import at, green_read, stub_rebase


class _Late:
    """The module, imported on first use, so each test fails alone while it is missing."""

    def __getattr__(self, name: str):
        return getattr(importlib.import_module("agile_team.scratch_rebase"), name)


sr = _Late()


def conflict(**kw) -> bd.Failure:
    fields = {"files": ["a.py", "b.py"], "commit": "c" * 12, "subject": "Edit a", **kw}
    return bd.Failure(Stage.REBASE, FixCase.REBASE_CONFLICT, "the output", **fields)


def stored(boundary: bd.Boundary) -> dict:
    st = RunState(sprint=1)
    st.boundary = boundary
    return json.loads(st.to_json())


def load(data: dict) -> RunState:
    return RunState.from_json(json.dumps(data))


def test_s153_the_new_enum_members_and_values() -> None:
    assert StepKind.REBASE_FIX.value == "rebase-fix"
    assert list(StepKind)[-1] is StepKind.REBASE_FIX
    assert FixCase.REBASE_CONFLICT.value == "rebase_conflict"
    assert BoundaryHold.REBASE_CONFLICT.value == "rebase_conflict"
    holds = list(BoundaryHold)
    assert holds.index(BoundaryHold.REBASE_CONFLICT) == holds.index(BoundaryHold.SYNC_CONFLICT) + 1


def test_s153_the_tables_hold_the_conflict_path() -> None:
    assert bd.FIX_KINDS[FixCase.REBASE_CONFLICT] is StepKind.REBASE_FIX
    assert len(bd.FIX_LINES[FixCase.REBASE_CONFLICT]) == 2
    hint = bd.STALL_HINTS[BoundaryHold.REBASE_CONFLICT]
    assert "continue_boundary(note)" in hint


def test_s153_a_failure_worktree_defaults_to_empty() -> None:
    assert conflict().worktree == ""


def test_s153_failure_worktree_round_trips_through_state_json() -> None:
    b = bd.Boundary(Edge.END, 1, failure=conflict(worktree="/w/rebase", branch="agile-team/x"))
    assert load(stored(b)).boundary.failure.worktree == "/w/rebase"


def test_s153_a_stored_failure_without_worktree_loads_empty() -> None:
    data = stored(bd.Boundary(Edge.END, 1, failure=conflict(worktree="/w")))
    del data["boundary"]["failure"]["worktree"]
    assert load(data).boundary.failure.worktree == ""


def test_s153_a_stored_boundary_without_rebase_fix_loads_none() -> None:
    data = stored(bd.Boundary(Edge.END, 1))
    data["boundary"].pop("rebase_fix", None)
    assert load(data).boundary.rebase_fix is None
    assert bd.Boundary(Edge.END, 1).rebase_fix is None


def test_s153_a_rebase_fix_loads_with_its_conflict_as_a_failure() -> None:
    fix = bd.RebaseFix(conflict(worktree="/w"), "done", "notes")
    loaded = load(stored(bd.Boundary(Edge.END, 1, rebase_fix=fix))).boundary.rebase_fix
    assert loaded == fix and isinstance(loaded.conflict, bd.Failure)
    assert (loaded.status, loaded.notes) == ("done", "notes")


def test_s153_a_rebase_conflict_hold_loads_as_a_known_hold() -> None:
    data = stored(bd.Boundary(Edge.END, 1, hold=BoundaryHold.REBASE_CONFLICT))
    state = load(data)
    assert state.boundary.hold == BoundaryHold.REBASE_CONFLICT
    assert state.load_faults == []


def test_s153_fix_brief_names_the_commit_files_worktree_and_branch() -> None:
    b = bd.Boundary(Edge.END, 3, failure=conflict(worktree="/w/rebase", branch="agile-team/r3"))
    brief = bd.fix_brief(b, bd.FixContext("team/s", "origin/main", "f" * 40))
    for text in ("c" * 12, '"Edit a"', "a.py, b.py", "/w/rebase", "agile-team/r3", "team/s"):
        assert text in brief
    assert "origin/main" in brief
    assert brief.rstrip().endswith("the output\n```") or "the output" in brief
    assert brief.index("/w/rebase") < brief.index("the output")


def test_s153_the_texts_format_with_their_fields() -> None:
    assert bd.FIX_NOT_DONE.format(status="failed") == "the DevOps step ended failed"
    assert bd.CHECKS_FAILED.format(path="/w", reason="r") == "the full checks failed in /w: r"
    held = bd.REBASE_FIX_HELD.format(
        sprint=2, target="origin/main", commit="c1", subject="s", files="a.py",
        reason="why", notes="n", branch="agile-team/r2",
    )  # fmt: skip
    for text in ("Sprint 2", "origin/main", "c1", '"s"', "a.py", "why", "n", "agile-team/r2"):
        assert text in held


def test_s153_dispatch_has_the_rebase_fix_scope_table_entries() -> None:
    assert frozenset({StepKind.TEAM_FIX, StepKind.REBASE_FIX}) == dispatch.FIX_KINDS_SET
    assert dispatch.REBASE_FIX_ENV == {"GIT_EDITOR": "true"}
    assert dispatch.FIX_SETUPS[StepKind.REBASE_FIX] == dispatch.Runtime._rebase_fix_scope


@pytest.fixture
def env(make_runtime) -> Env:
    return Env(make_runtime)


def test_s153_the_rebase_fix_scope_confines_writes_and_git_to_the_worktree(env: Env) -> None:
    rt = env.rt
    role = roles.RoleBook.for_repo(Path("."), {}).resolve("devops")
    plan = dispatch.Plan(role, guard.Scope("devops", rt.config.repo, ["**"], []), prompt="x")
    rt._rebase_fix_scope(plan)
    worktree = rt.config.run_dir / sr.REBASE_DIR
    rel = worktree.relative_to(rt.config.repo).as_posix()
    assert plan.scope.write == [f"{rel}/**"]
    assert plan.scope.git_workspace == system.resolve(worktree)
    assert plan.launch.env["GIT_EDITOR"] == "true"
    assert "GIT_CEILING_DIRECTORIES" in plan.launch.env


def test_p1_a_sprint_end_conflict_goes_to_devops_and_holds_nothing(env: Env) -> None:
    e = at(env, Stage.REBASE)
    green_read(e)
    stub_rebase(env, Rebase(SyncOutcome.CONFLICT, files=("a.py",), commit="c" * 40, subject="s"))
    env.br.step()
    b = env.rt.state.boundary
    assert b.hold is None  # s151 AC6 (R13/R15/R16): conflict goes to DevOps, no hold

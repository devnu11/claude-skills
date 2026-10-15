"""s151 AC6: a sprint-end rebase conflict goes to a DevOps step in a scratch worktree.

Unit level: a stubbed ``Upstream`` and a stubbed ``ScratchRebase`` (real git is proven in e2e).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from agile_team import boundary as bd
from agile_team import handover, upstream
from agile_team import scratch_rebase as sr
from agile_team.boundary import BoundaryHold, FixCase, Stage, StepKind
from agile_team.ci import CiVerdict
from agile_team.dispatch import StepRequest
from agile_team.po_tools import Tools
from agile_team.upstream import Rebase, SyncOutcome, UpstreamError

from .test_boundary_runner import Env
from .test_s151_end import (
    AS_BUILT,
    REBASED,
    TARGET,
    at,
    green_read,
    head_is,
    last,
    posted,
    stub_rebase,
)

OLD_COMMIT = "c0" * 20
BRANCH = "agile-team/rebase-sprint-1"
CONFLICT = Rebase(SyncOutcome.CONFLICT, files=("a.py", "b.py"), commit=OLD_COMMIT, subject="Edit a")
MOVED = {OLD_COMMIT: "d1" * 20}


def rule_line(trigger) -> str:
    return next(r.line for r in handover.HANDOVERS if r.trigger is trigger)


@pytest.fixture
def env(make_runtime) -> Env:
    return Env(make_runtime)


class Scratch:
    """Stands in for ``ScratchRebase``: records calls, answers refusal and head as scripted."""

    def __init__(self, monkeypatch, path: Path) -> None:
        self.calls: list[tuple] = []
        self.why = ""
        self.new_head = REBASED
        self.path = path
        for name in ("prepare", "drop", "remove"):
            monkeypatch.setattr(sr.ScratchRebase, name, self._record(name))
        monkeypatch.setattr(sr.ScratchRebase, "head", lambda s: self.new_head)
        monkeypatch.setattr(sr.ScratchRebase, "refusal", self._refusal_method())

    def _record(self, name):
        def method(scratch, *args):
            self.calls.append((name, *args))

        return method

    def _refusal_method(self):
        def refusal(scratch, old: str) -> str:
            self.calls.append(("refusal", old))
            return self.why

        return refusal

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]


@pytest.fixture
def scratch(monkeypatch, env: Env) -> Scratch:
    """The scratch worktree is at ``run_dir / REBASE_DIR`` (R14), never a temp dir."""
    return Scratch(monkeypatch, env.rt.config.run_dir / sr.REBASE_DIR)


def conflicted(env: Env, scratch: Scratch) -> bd.Boundary:
    """Sprint 1 at the rebase stage with green as-built CI, and main conflicting."""
    e = at(env, Stage.REBASE)
    green_read(e)
    stub_rebase(env, CONFLICT)
    env.br.step()
    return env.rt.state.boundary


def fixed(env: Env, scratch: Scratch, status: str = "done", summary: str = "resolved") -> None:
    """DevOps ran: its report comes back."""
    env.br.after_fix({"role": "devops", "status": status, "summary": summary})


# ----- AC6.1: abort, leave the team branch, hand the conflict to DevOps ---------------


def test_s151_devops_conflict_ac6_1_a_conflict_holds_nothing_and_prepares_the_scratch_worktree(
    env: Env, scratch: Scratch
) -> None:
    """Pins s151/AC6.1 (slice 2): the DevOps conflict path."""
    b = conflicted(env, scratch)
    assert b.hold is None and b.stage is Stage.REBASE
    assert ("prepare", AS_BUILT) in scratch.calls
    assert b.sync_from == AS_BUILT and env.rt.git.head() == AS_BUILT


def test_s151_devops_conflict_ac6_1_the_failure_names_the_commit_files_and_scratch_branch(
    env: Env, scratch: Scratch
) -> None:
    """Pins s151/AC6.1 (slice 2): the DevOps conflict path."""
    b = conflicted(env, scratch)
    f = b.failure
    assert (f.stage, f.case) == (Stage.REBASE, FixCase.REBASE_CONFLICT)
    assert (f.branch, f.files, f.commit, f.subject) == (
        BRANCH,
        ["a.py", "b.py"],
        OLD_COMMIT,
        "Edit a",
    )
    data = last(env)
    assert data["outcome"] == "conflict" and data["files"] == ["a.py", "b.py"]
    assert data["commit"] == OLD_COMMIT[:12] and data["branch"] == BRANCH
    assert "hold" not in data or not data["hold"]


def test_s151_devops_conflict_ac6_1_devops_is_due_with_a_brief_that_names_everything(
    env: Env, scratch: Scratch
) -> None:
    """Pins s151/AC6.1 (slice 2): the DevOps conflict path."""
    conflicted(env, scratch)
    due = env.br.due()
    assert (due.kind, due.role) == (StepKind.REBASE_FIX, "devops")
    for text in (OLD_COMMIT, "Edit a", "a.py, b.py", str(scratch.path), BRANCH, TARGET):
        assert text in due.brief


def test_s151_devops_conflict_ac6_1_nothing_asks_the_human_to_rebase_by_hand(
    env: Env, scratch: Scratch
) -> None:
    """Pins s151/AC6.1 (slice 2): the DevOps conflict path."""
    conflicted(env, scratch)
    assert not [t for t in posted(env) if "by hand" in t]
    assert "by hand" not in rule_line(handover.Trigger.SYNC_CONFLICT)


def test_s151_devops_conflict_ac6_1_the_fix_kind_table_maps_the_case_to_the_step() -> None:
    assert bd.FIX_KINDS[FixCase.REBASE_CONFLICT] is StepKind.REBASE_FIX
    assert bd.FIX_KINDS[FixCase.TEAM_CHECK] is StepKind.TEAM_FIX
    assert FixCase.REBASE_CONFLICT in bd.FIX_LINES


# ----- AC6.2: the scratch worktree, its scope, its checks ------------------------------


def test_s151_devops_conflict_ac6_2_scratch_rebase_keeps_empty_commits_team_one_drops_them() -> (
    None
):
    assert "--empty=keep" in upstream.SCRATCH_REBASE_ARGV
    assert "--empty=drop" not in upstream.SCRATCH_REBASE_ARGV
    assert upstream.REBASE_ARGV[-1] == "--empty=drop"
    assert upstream.SCRATCH_REBASE_ARGV[:-1] == upstream.REBASE_ARGV[:-1]


def test_s151_devops_conflict_ac6_2_the_worktree_and_branch_names() -> None:
    assert sr.REBASE_DIR == "rebase"
    assert sr.REBASE_BRANCH.format(sprint=7) == "agile-team/rebase-sprint-7"


def test_s151_devops_conflict_ac6_2_the_judging_checks_run_in_the_documented_order() -> None:
    names = [c.__name__ for c in sr.SCRATCH_CHECKS]
    assert names == [
        "_unfinished",
        "_off_branch",
        "_dirty",
        "_off_target",
        "_merges",
        "_commits_changed",
        "_lost",
    ]


def test_s151_devops_conflict_ac6_2_the_first_reason_wins(monkeypatch) -> None:
    monkeypatch.setattr(sr, "SCRATCH_CHECKS", (lambda s, old: "", lambda s, old: "second"))
    scratch = sr.ScratchRebase(None, Path("/w"), "b")
    assert scratch.refusal("old") == "second"
    monkeypatch.setattr(sr, "SCRATCH_CHECKS", (lambda s, old: "",))
    assert scratch.refusal("old") == ""


def test_s151_devops_conflict_ac6_2_the_fix_step_may_write_only_the_worktree(make_runtime) -> None:
    rt = make_runtime()
    plan = rt.plan(StepRequest("devops", "fix", None, StepKind.REBASE_FIX))
    rel = (rt.config.run_dir / sr.REBASE_DIR).relative_to(rt.config.repo).as_posix()
    assert plan.scope.write == [f"{rel}/**"]


def test_s151_devops_conflict_ac6_2_git_is_confined_to_the_worktree_without_an_editor(
    make_runtime,
) -> None:
    rt = make_runtime()
    plan = rt.plan(StepRequest("devops", "fix", None, StepKind.REBASE_FIX))
    assert str(plan.scope.git_workspace).endswith(f"/{sr.REBASE_DIR}")
    assert plan.launch.env["GIT_EDITOR"] == "true"
    assert "GIT_CEILING_DIRECTORIES" in plan.launch.env


def test_s151_devops_conflict_ac6_2_the_full_checks_run_in_the_worktree_not_the_team_checkout(
    env: Env, scratch: Scratch
) -> None:
    """Pins s151/AC6.2 (slice 2): the DevOps conflict path."""
    ran: list[Path] = []
    green = type("R", (), {"passed": True, "reason": lambda s: ""})()
    env.br._run_checks = lambda path: ran.append(path) or green
    env.rt.upstream.adopt = Adopts(Rebase(SyncOutcome.REBASED, sha=REBASED, moved=MOVED))
    conflicted(env, scratch)
    fixed(env, scratch)
    env.br.step()
    assert ran == [scratch.path]
    assert env.rt.config.repo not in ran


def test_s151_devops_conflict_ac6_2_devops_never_merges_or_squashes_is_in_its_brief(
    env: Env, scratch: Scratch
) -> None:
    """Pins s151/AC6.2 (slice 2): the DevOps conflict path."""
    conflicted(env, scratch)
    brief = env.br.due().brief
    assert "Never merge, squash" in brief and "git rebase --continue" in brief


# ----- AC6.3: a clean result moves the team branch and carries on ---------------------


class Adopts:
    """Stands in for ``Upstream.adopt``."""

    def __init__(self, result: Rebase) -> None:
        self.result, self.args = result, []

    def __call__(self, old: str, sha: str) -> Rebase:
        self.args.append((old, sha))
        return self.result


def resolved(env: Env, scratch: Scratch) -> Adopts:
    adopt = Adopts(Rebase(SyncOutcome.REBASED, sha=REBASED, moved=MOVED))
    env.rt.upstream.adopt = adopt
    env.br._run_checks = lambda path: type("R", (), {"passed": True, "reason": lambda s: ""})()
    conflicted(env, scratch)
    fixed(env, scratch)
    return adopt


def test_s151_devops_conflict_ac6_3_after_devops_the_rebase_stage_adopts_without_fetching(
    env: Env, scratch: Scratch, fake
) -> None:
    """Pins s151/AC6.3 (slice 2): the DevOps conflict path."""
    adopt = resolved(env, scratch)
    seen = len(fake.commands)
    env.br.step()
    assert adopt.args == [(AS_BUILT, REBASED)]
    assert not [c for c in fake.commands[seen:] if "fetch" in c.argv]


def test_s151_devops_conflict_ac6_3_hashes_are_remapped_and_the_next_stage_is_push_rebased(
    env: Env, scratch: Scratch
) -> None:
    """Pins s151/AC6.3 (slice 2): the DevOps conflict path."""
    story = env.rt.state.stories["s1"]
    story.commit = OLD_COMMIT
    resolved(env, scratch)
    env.br.step()
    b = env.rt.state.boundary
    assert story.commit == MOVED[OLD_COMMIT] and b.stage is Stage.PUSH_REBASED
    assert last(env)["outcome"] == "rebased" and b.sync_from == "" and b.rebase_fix is None
    assert b.hold is None


def test_s151_devops_conflict_ac6_3_the_scratch_worktree_and_branch_are_dropped(
    env: Env, scratch: Scratch
) -> None:
    """Pins s151/AC6.3 (slice 2): the DevOps conflict path."""
    resolved(env, scratch)
    env.br.step()
    assert "drop" in scratch.names()


def test_s151_devops_conflict_ac6_3_a_moved_team_branch_holds_error_and_resets_nothing(
    env: Env, scratch: Scratch
) -> None:
    """Pins s151/AC6.3 (slice 2): the DevOps conflict path."""
    resolved(env, scratch)

    def moved(old: str, sha: str) -> Rebase:
        raise UpstreamError(upstream.TEAM_MOVED.format(team="main", old=old))

    env.rt.upstream.adopt = moved
    env.br.step()
    assert env.rt.state.boundary.hold is BoundaryHold.ERROR
    assert "moved from" in last(env)["reason"]


def test_s151_devops_conflict_ac6_3_a_moved_team_branch_can_recover_without_adopting_again(
    env: Env, scratch: Scratch
) -> None:
    """Pins s151/AC6.3 (R16, R17): after the error hold the rebase reruns from the new HEAD."""
    adopt = resolved(env, scratch)

    def moved(old: str, sha: str) -> Rebase:
        raise UpstreamError(upstream.TEAM_MOVED.format(team="main", old=old))

    env.rt.upstream.adopt = moved
    env.br.step()
    b = env.rt.state.boundary
    assert b.hold is BoundaryHold.ERROR
    assert b.rebase_fix is None and b.sync_from == "" and "drop" in scratch.names()
    ran: list[Path] = []
    env.br._run_checks = lambda path: ran.append(path)
    env.rt.upstream.adopt = adopt
    json.loads(
        asyncio.run(Tools(env.rt).continue_boundary({"note": "moved"}))["content"][0]["text"]
    )
    head_is(env, "ee" * 20)
    rebases = stub_rebase(env, Rebase(SyncOutcome.CURRENT))
    env.br.step()
    assert rebases.olds == ["ee" * 20]
    assert adopt.args == [] and ran == []


def test_s151_devops_conflict_ac6_4_a_crashed_devops_step_holds_rebase_conflict(
    env: Env, scratch: Scratch
) -> None:
    """Pins s151/AC6.4 (R15, R17): an error report has no summary and must not raise."""
    b = conflicted(env, scratch)
    env.br.after_fix({"status": "error", "role": "devops", "reason": "boom"})
    assert b.rebase_fix.status == "error" and b.rebase_fix.notes == ""
    env.br.step()
    assert b.hold is BoundaryHold.REBASE_CONFLICT
    assert last(env)["reason"] == bd.FIX_NOT_DONE.format(status="error")
    assert last(env)["notes"] == "none"


def test_s151_devops_conflict_ac6_3_after_fix_records_the_devops_report_and_clears_the_failure(
    env: Env, scratch: Scratch
) -> None:
    """Pins s151/AC6.3 (slice 2): the DevOps conflict path."""
    b = conflicted(env, scratch)
    failure = b.failure
    fixed(env, scratch, "done", "kept both")
    assert b.failure is None and b.hold is None
    assert (b.rebase_fix.conflict, b.rebase_fix.status, b.rebase_fix.notes) == (
        failure,
        "done",
        "kept both",
    )


def test_s151_devops_conflict_ac6_3_the_gate_still_applies_before_an_adopt(
    env: Env, scratch: Scratch
) -> None:
    resolved(env, scratch)
    env.rt.state.upstream.stack[0].ci = None
    env.br.step()
    assert env.rt.state.boundary.stage is Stage.CI and last(env)["outcome"] == "refused"
    assert env.rt.git.head() == AS_BUILT


def test_s151_devops_conflict_ac6_3_the_pushed_green_read_survives_an_adopt(
    env: Env, scratch: Scratch
) -> None:
    resolved(env, scratch)
    env.br.step()
    e = env.rt.state.upstream.stack[0]
    assert (e.as_is, e.pushed) == (AS_BUILT, AS_BUILT) and e.ci.verdict is CiVerdict.GREEN
    head_is(env, REBASED)


# ----- AC6.4: DevOps cannot settle it: hold with the conflict, notes and branch ------------


def hold_text(env: Env) -> str:
    return next(t for t in posted(env) if BRANCH in t and "could not settle" in t)


def test_s151_devops_conflict_ac6_4_a_failed_devops_step_holds_rebase_conflict(
    env: Env, scratch: Scratch
) -> None:
    """Pins s151/AC6.4 (slice 2): the DevOps conflict path."""
    conflicted(env, scratch)
    fixed(env, scratch, "failed", "the two edits contradict")
    env.br.step()
    b = env.rt.state.boundary
    assert b.hold is BoundaryHold.REBASE_CONFLICT and b.stage is Stage.REBASE
    data = last(env)
    assert data["outcome"] == "conflict" and data["branch"] == BRANCH
    assert data["notes"] == "the two edits contradict"
    assert data["files"] == ["a.py", "b.py"] and data["commit"] == OLD_COMMIT[:12]
    assert "ended failed" in data["reason"]
    assert env.rt.git.head() == AS_BUILT and "drop" not in scratch.names()


def test_s151_devops_conflict_ac6_4_the_liaison_gets_the_conflict_notes_and_branch(
    env: Env, scratch: Scratch
) -> None:
    """Pins s151/AC6.4 (slice 2): the DevOps conflict path."""
    conflicted(env, scratch)
    fixed(env, scratch, "failed", "the two edits contradict")
    env.br.step()
    text = hold_text(env)
    for part in ("a.py, b.py", "the two edits contradict", BRANCH, "Edit a", OLD_COMMIT[:12]):
        assert part in text


def test_s151_devops_conflict_ac6_4_a_refused_scratch_result_holds_with_the_reason(
    env: Env, scratch: Scratch
) -> None:
    """Pins s151/AC6.4 (slice 2): the DevOps conflict path."""
    conflicted(env, scratch)
    fixed(env, scratch)
    scratch.why = "the branch has merge commits: abc"
    env.br.step()
    assert env.rt.state.boundary.hold is BoundaryHold.REBASE_CONFLICT
    assert last(env)["reason"] == "the branch has merge commits: abc"
    assert ("refusal", AS_BUILT) in scratch.calls


def test_s151_devops_conflict_ac6_4_failing_full_checks_hold_with_the_checks_reason(
    env: Env, scratch: Scratch
) -> None:
    """Pins s151/AC6.4 (slice 2): the DevOps conflict path."""
    conflicted(env, scratch)
    fixed(env, scratch)
    env.br._run_checks = lambda path: type(
        "R", (), {"passed": False, "reason": lambda s: "lint failed"}
    )()
    env.br.step()
    assert env.rt.state.boundary.hold is BoundaryHold.REBASE_CONFLICT
    assert bd.CHECKS_FAILED.format(path=scratch.path, reason="lint failed") == last(env)["reason"]


def test_s151_devops_conflict_ac6_4_the_checks_run_only_when_the_scratch_result_passes(
    env: Env, scratch: Scratch
) -> None:
    ran: list[Path] = []
    env.br._run_checks = lambda path: ran.append(path)
    conflicted(env, scratch)
    fixed(env, scratch, "failed", "no")
    env.br.step()
    assert ran == [] and ("refusal", AS_BUILT) not in scratch.calls


def test_s151_devops_conflict_ac6_4_the_po_handover_names_the_branch_and_notes() -> None:
    """Pins s151/AC6.4 (slice 2): the DevOps conflict path."""
    assert handover.Trigger.REBASE_CONFLICT == "rebase_conflict"
    text = rule_line(handover.Trigger.REBASE_CONFLICT)
    for placeholder in ("{branch}", "{reason}", "{notes}", "{commit}", "{subject}"):
        assert placeholder in text


def test_s151_devops_conflict_ac6_4_continue_boundary_clears_the_fix_and_reruns_the_rebase(
    env: Env, scratch: Scratch
) -> None:
    """Pins s151/AC6.4 (slice 2): the DevOps conflict path."""
    conflicted(env, scratch)
    fixed(env, scratch, "failed", "no")
    env.br.step()
    out = json.loads(
        asyncio.run(Tools(env.rt).continue_boundary({"note": "try theirs"}))["content"][0]["text"]
    )
    b = env.rt.state.boundary
    assert out["status"] != "refused" and b.hold is None and b.rebase_fix is None
    stub_rebase(env, CONFLICT)
    env.br.step()
    assert env.br.due().kind is StepKind.REBASE_FIX
    assert env.br.due().brief.endswith("From the PO: try theirs")


def test_s151_devops_conflict_ac6_4_the_stall_hint_exists() -> None:
    assert BoundaryHold.REBASE_CONFLICT in bd.STALL_HINTS
    assert "continue_boundary" in bd.STALL_HINTS[BoundaryHold.REBASE_CONFLICT]


def test_s151_devops_conflict_ac6_4_a_legacy_sync_conflict_hold_still_exists() -> None:
    assert BoundaryHold.SYNC_CONFLICT.value == "sync_conflict"

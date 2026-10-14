"""s29: boundary data, texts and pure helpers (no I/O)."""

from dataclasses import asdict

import pytest
from agile_team import boundary as b
from agile_team.events import Event, EventKind
from agile_team.loops import Author


def failure(**kw) -> b.Failure:
    base = {"stage": b.Stage.CHECK, "case": b.FixCase.TEAM_CHECK, "reason": "test failed"}
    return b.Failure(**{**base, **kw})


def test_enum_values() -> None:
    assert [e.value for e in b.Edge] == ["start", "end"]
    assert [e.value for e in b.Stage] == [
        "sync",
        "check",
        "review",
        "push",
        "rebase",
        "restack",
        "ci",
    ]
    assert [e.value for e in b.StepKind] == [
        "role",
        "boundary",
        "team-fix",
        "review-fix",
        "gate-fix",
    ]
    assert {e.value for e in b.BoundaryHold} == {
        "sync_conflict",
        "escalated",
        "reviewed",
        "push_permission",
        "push_rejected",
        "ci_failed",
        "ci_infra",
        "main_broken",
        "ci_pending",
        "error",
        "fix_handover",
    }
    assert [e.value for e in b.FixCase] == ["team_check", "review_check", "review_conflict"]
    assert [e.value for e in b.Permission] == ["unasked", "yes", "no"]
    assert [e.value for e in b.CheckState] == ["unchecked", "pass", "fail"]
    assert {e.value for e in b.BoundaryOutcome} == {
        "skipped", "current", "merged", "rebased", "conflict", "pass", "fail", "escalate", "built",
        "held", "pushed", "local", "error", "done", "continued", "permission", "restacked",
        "rebuild", "rerun",
    }  # fmt: skip


def test_boundary_defaults_and_coercion() -> None:
    bd = b.Boundary("end", 3, stage="review", hold="escalated")
    assert bd.edge is b.Edge.END and bd.stage is b.Stage.REVIEW
    assert bd.hold is b.BoundaryHold.ESCALATED
    fresh = b.Boundary(b.Edge.START, 1)
    assert fresh.stage is b.Stage.SYNC and fresh.hold is None and fresh.failure is None
    assert (fresh.streak, fresh.rounds, fresh.escalated, fresh.restack, fresh.note) == (
        [],
        0,
        None,
        False,
        "",
    )


def test_stack_entry_and_upstream_state_defaults() -> None:
    e = b.StackEntry(1, "team/sprint-1", "a", "b")
    assert e.check is b.CheckState.UNCHECKED and e.pr is None and e.pushed == "" and e.stories == []
    u = b.UpstreamState()
    assert u.push is b.Permission.UNASKED and u.stack == [] and u.closed == 0 and u.last_end == ""


def test_next_stage_end_goes_through_every_stage() -> None:
    bd = b.Boundary(b.Edge.END, 1)
    seen = []
    while (nxt := b.next_stage(bd)) is not None:
        seen.append(nxt)
        bd.stage = nxt
    assert seen == [
        b.Stage.CHECK,
        b.Stage.REVIEW,
        b.Stage.PUSH,
        b.Stage.REBASE,
        b.Stage.RESTACK,
        b.Stage.CI,
    ]


def test_next_stage_start_skips_every_end_only_stage() -> None:
    bd = b.Boundary(b.Edge.START, 1, stage=b.Stage.CHECK)
    assert b.next_stage(bd) is None
    bd.stage = b.Stage.SYNC
    assert b.next_stage(bd) is b.Stage.CHECK


def test_next_stage_start_ignores_restack_and_stops_after_check() -> None:
    """M3: the START edge runs SYNC and CHECK only, whatever ``restack`` says."""
    bd = b.Boundary(b.Edge.START, 1, stage=b.Stage.CHECK, restack=True)
    assert b.next_stage(bd) is None


def test_fix_kinds_table() -> None:
    assert b.FIX_KINDS == {
        b.FixCase.TEAM_CHECK: b.StepKind.TEAM_FIX,
        b.FixCase.REVIEW_CHECK: b.StepKind.TEAM_FIX,
        b.FixCase.REVIEW_CONFLICT: b.StepKind.REVIEW_FIX,
    }
    assert (
        frozenset({b.Stage.REVIEW, b.Stage.PUSH, b.Stage.REBASE, b.Stage.RESTACK, b.Stage.CI})
        == b.END_ONLY
    )


def test_setback_key_uses_edge_stage_and_normalised_reason() -> None:
    bd = b.Boundary(b.Edge.END, 2)
    a = b.setback(bd, failure(reason="FAILED test_x in 1.2s at /tmp/a1"))
    c = b.setback(bd, failure(reason="FAILED test_x in 9.9s at /tmp/zz"))
    assert (a.step, a.to_step, a.role, a.verdict, a.author) == (
        "end",
        "check",
        "runner",
        "bounce",
        Author.RUNNER,
    )
    assert a.key == c.key and a.key.startswith("end>check ")
    assert b.setback(bd, failure(reason="other thing")).key != a.key


def test_held_text() -> None:
    assert b.held_text(b.Boundary(b.Edge.END, 1)) == ""
    held = b.Boundary(b.Edge.END, 1, hold=b.BoundaryHold.ERROR)
    assert b.held_text(held) == ", held: error"


CTX = b.FixContext(
    team="agile-team",
    target="origin/main",
    worktree="/r/.team/run/review",
    sha="abc",
    sprints="1, 2",
)


def test_fix_brief_team_check() -> None:
    bd = b.Boundary(b.Edge.START, 4, stage=b.Stage.CHECK)
    bd.failure = failure(reason="lint failed (exit 1)")
    brief = b.fix_brief(bd, CTX)
    assert brief.startswith(b.FIX_HEADING.format(sprint=4, edge="start", stage="check"))
    assert "The full checks failed on the team branch agile-team at abc." in brief
    assert "lint failed (exit 1)" in brief
    assert brief.endswith("```")
    assert "From the PO" not in brief


def test_fix_brief_review_check_names_branch_and_sprints() -> None:
    bd = b.Boundary(b.Edge.END, 2, stage=b.Stage.REVIEW)
    bd.failure = failure(stage=b.Stage.REVIEW, case=b.FixCase.REVIEW_CHECK, branch="team/sprint-2")
    brief = b.fix_brief(bd, CTX)
    assert "review branch team/sprint-2 (sprints 1, 2 rebased onto origin/main)" in brief
    assert "/r/.team/run/review" in brief and "do not edit it" in brief


def test_fix_brief_review_conflict_names_commit_and_files() -> None:
    bd = b.Boundary(b.Edge.END, 2, stage=b.Stage.REVIEW)
    bd.failure = failure(
        stage=b.Stage.REVIEW,
        case=b.FixCase.REVIEW_CONFLICT,
        branch="team/sprint-2",
        commit="deadbeef",
        subject="feat: x",
        files=["a.py", "b.py"],
    )
    brief = b.fix_brief(bd, CTX)
    assert "commit deadbeef (feat: x) conflicts in a.py, b.py" in brief
    assert "git rerere" in brief


def test_fix_brief_carries_the_po_note_last() -> None:
    bd = b.Boundary(b.Edge.END, 2, note="the human fixed the token")
    bd.failure = failure()
    assert b.fix_brief(bd, CTX).endswith("\n\nFrom the PO: the human fixed the token")


def test_output_block_format() -> None:
    assert b.OUTPUT_BLOCK == "Output:\n```\n{output}\n```"


def test_exact_strings() -> None:
    assert not hasattr(b, "MERGE_MESSAGE")
    assert b.SYNC_OFF == "[upstream] remote is empty"
    assert b.NO_REMOTE.format(remote="origin") == "no remote 'origin'"
    assert b.NO_TARGET.format(target="origin/main") == "origin/main does not exist"
    assert b.NOT_PERMITTED == "the human said no to pushing"
    assert b.BOUNDARY_ROLE == "runner" and b.FIX_ROLE == "devops"


def test_manager_view_shape_and_event_filter() -> None:
    first = failure(reason="boom 1")
    bd = b.Boundary(b.Edge.END, 2, escalated="boom 1", failure=first)
    s1 = b.setback(bd, first)
    s1.event = "e0005"
    s2 = b.setback(bd, failure(reason="boom 2"))
    s2.event = "e0008"
    bd.streak = [s1, s2]
    events = [
        Event(EventKind.BOUNDARY, "runner", None, {"stage": "check"}, id="e0004"),
        Event(EventKind.BOUNDARY, "runner", None, {"stage": "check"}, id="e0005"),
        Event(EventKind.STEP_END, "devops", None, {}, id="e0006"),
        Event(EventKind.STEP_END, "devops", "s1", {}, id="e0007"),
        Event(EventKind.STEP_END, "developer", None, {}, id="e0009"),
    ]
    view = b.manager_view(bd, events)
    assert view["edge"] == "end" and view["sprint"] == 2 and view["stage"] == "check"
    assert view["reason"] == "boom 1" and view["count"] == 2 and view["key"] == s2.key
    assert view["history"] == [asdict(s1), asdict(s2)]
    assert [e["id"] for e in view["events"]] == ["e0005", "e0006"]


def test_due_holds_kind_role_and_brief() -> None:
    d = b.Due(b.StepKind.BOUNDARY, "runner", "")
    assert (d.kind, d.role, d.brief) == (b.StepKind.BOUNDARY, "runner", "")


@pytest.mark.parametrize("case", list(b.FixCase))
def test_every_fix_case_has_lines(case) -> None:
    assert len(b.FIX_LINES[case]) == 2

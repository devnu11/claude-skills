"""s29 U1-U3, U10, U13, U20-U21, U23, U26: PO tools, the Router, dispatch refusals, hand-overs."""

import asyncio
import json

import pytest
from agile_team import boundary as bd
from agile_team import handover, system
from agile_team.boundary import BoundaryHold, Edge, Stage, StepKind
from agile_team.dispatch import StepRequest
from agile_team.gates import StoryState
from agile_team.guard import ToolCall, check_tool_use
from agile_team.handover import Trigger as T
from agile_team.po_tools import Tools
from agile_team.roles import Handoff


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


def writable(scope, path: str) -> bool:
    return check_tool_use(scope, ToolCall("Write", {"file_path": str(scope.base / path)})) is None


def manager_report(rt, handoff: Handoff | None = None) -> dict:
    plan = rt.plan(StepRequest("manager", "review", None))
    return rt.apply_manager(plan, handoff or Handoff("done"))


def sprint_story(rt, sid: str = "s1", **kw) -> None:
    rt.state.sprint = 1
    rt.state.stories[sid] = StoryState(sid, "T", kw.pop("step", "design"), sprint=1, **kw)


# ----- U1/U14: start_sprint, continue_boundary, set_push_permission ----------


def test_start_sprint_opens_a_start_boundary_and_sets_the_goal(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    call(t.open_story({"id": "s1", "title": "Add"}))
    call(t.start_sprint({"goal": "MVP", "stories": ["s1"]}))
    assert rt.state.boundary == bd.Boundary(Edge.START, 1) and rt.state.goal == "MVP"


def test_start_sprint_is_refused_while_a_boundary_is_pending(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    call(t.open_story({"id": "s1", "title": "Add"}))
    rt.state.boundary = bd.Boundary(Edge.END, 3, stage=Stage.CHECK, hold=BoundaryHold.ERROR)
    out = call(t.start_sprint({"goal": "MVP", "stories": ["s1"]}))
    assert out["status"] == "refused"
    assert (
        out["reason"]
        == "sprint 3 end boundary is still pending (check, held: error); finish it first"
    )
    assert rt.state.sprint == 0 and rt.state.stories["s1"].sprint is None


def test_continue_boundary_refusals(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    assert call(t.continue_boundary({"note": ""}))["reason"] == "no sprint boundary is pending"
    rt.state.boundary = bd.Boundary(Edge.END, 2)
    out = call(t.continue_boundary({"note": ""}))
    assert out["reason"] == "the sprint 2 end boundary is not held; the runner is on it"


def test_continue_boundary_releases_a_hold_and_keeps_the_note(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    rt.state.boundary = bd.Boundary(Edge.END, 2, hold=BoundaryHold.ERROR)
    rt.state.boundary.failure = bd.Failure(Stage.CHECK, bd.FixCase.TEAM_CHECK, "r")
    rt.state.boundary.streak = [bd.setback(rt.state.boundary, rt.state.boundary.failure)]
    rt.state.boundary.rounds = 2
    call(t.continue_boundary({"note": "token rotated"}))
    b = rt.state.boundary
    assert (b.hold, b.failure, b.note) == (None, None, "token rotated")
    assert len(b.streak) == 1 and b.rounds == 2
    event = rt.events.events()[-1]
    assert (
        event.kind == "boundary"
        and event.data["outcome"] == "continued"
        and event.data["note"] == "token rotated"
    )


@pytest.mark.parametrize("hold", [BoundaryHold.ESCALATED, BoundaryHold.REVIEWED])
def test_continue_after_escalation_clears_streak_rounds_and_escalated(make_runtime, hold) -> None:
    rt = make_runtime()
    b = rt.state.boundary = bd.Boundary(Edge.END, 2, hold=hold, rounds=3, escalated="x")
    b.streak = [bd.setback(b, bd.Failure(Stage.CHECK, bd.FixCase.TEAM_CHECK, "r"))]
    call(Tools(rt).continue_boundary({"note": "n"}))
    assert (b.streak, b.rounds, b.escalated, b.hold) == ([], 0, None, None)


def test_set_push_permission_refuses_anything_but_yes_or_no(make_runtime) -> None:
    rt = make_runtime()
    out = call(Tools(rt).set_push_permission({"answer": "maybe"}))
    assert out["status"] == "refused" and out["reason"] == 'answer must be "yes" or "no"'
    assert rt.state.upstream.push is bd.Permission.UNASKED


@pytest.mark.parametrize("answer", ["yes", "no"])
def test_set_push_permission_records_the_answer_and_releases_the_hold(make_runtime, answer) -> None:
    rt = make_runtime()
    rt.state.boundary = bd.Boundary(
        Edge.END, 2, stage=Stage.PUSH, hold=BoundaryHold.PUSH_PERMISSION
    )
    call(Tools(rt).set_push_permission({"answer": answer}))
    assert rt.state.upstream.push == answer and rt.state.boundary.hold is None
    event = rt.events.events()[-1]
    assert event.data["outcome"] == "permission" and event.data["answer"] == answer


def test_set_push_permission_leaves_other_holds_and_can_change_the_answer(make_runtime) -> None:
    rt = make_runtime()
    rt.state.boundary = bd.Boundary(Edge.END, 2, hold=BoundaryHold.ERROR)
    t = Tools(rt)
    call(t.set_push_permission({"answer": "yes"}))
    assert rt.state.boundary.hold is BoundaryHold.ERROR
    call(t.set_push_permission({"answer": "no"}))
    assert rt.state.upstream.push == "no"


def test_tool_schemas() -> None:
    from agile_team.po_tools import SCHEMAS

    assert SCHEMAS["continue_boundary"][1] == {"note": str}
    assert SCHEMAS["set_push_permission"][1] == {"answer": str}
    assert "sprint boundary" in SCHEMAS["continue_boundary"][0]


def test_story_status_shows_the_boundary(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    assert call(t.story_status({}))["boundary"] is None
    rt.state.boundary = bd.Boundary(Edge.END, 2)
    shown = call(t.story_status({}))["boundary"]
    assert shown["edge"] == "end" and shown["sprint"] == 2 and shown["stage"] == "sync"


# ----- U2/U10: dispatch refusals and scopes ----------------------------------


def test_a_pending_boundary_refuses_sprint_story_roles(make_runtime) -> None:
    rt = make_runtime()
    sprint_story(rt, step="implement")
    rt.state.boundary = bd.Boundary(Edge.START, 1)
    out = asyncio.run(rt.run_role(StepRequest("developer", "go", "s1")))
    assert out["status"] == "refused"
    assert out["reason"] == bd.BOUNDARY_REFUSAL.format(
        sprint=1, edge="start", stage="sync", held=""
    )


def test_the_manager_is_not_refused_by_a_pending_boundary(make_runtime) -> None:
    rt = make_runtime()
    sprint_story(rt)
    rt.state.boundary = bd.Boundary(Edge.START, 1, stage=Stage.CHECK)
    out = asyncio.run(rt.run_role(StepRequest("manager", "review", None)))
    assert out["status"] != "refused"


def test_refusal_names_a_hold(make_runtime) -> None:
    rt = make_runtime()
    sprint_story(rt, step="implement")
    rt.state.boundary = bd.Boundary(Edge.START, 1, hold=BoundaryHold.SYNC_CONFLICT)
    reason = asyncio.run(rt.run_role(StepRequest("developer", "go", "s1")))["reason"]
    assert reason.endswith(", held: sync_conflict; the sprint's stories move once it passes")


def test_fix_steps_are_not_refused_by_manager_due(make_runtime) -> None:
    rt = make_runtime()
    rt.state.manager_due.append("sprint 1 start: g (s1)")
    rt.state.boundary = bd.Boundary(Edge.START, 1, stage=Stage.CHECK)
    out = asyncio.run(rt.run_role(StepRequest("devops", "fix it", None, StepKind.TEAM_FIX)))
    assert "manager review due" not in out.get("reason", "")


def test_a_team_fix_may_write_source_and_tests_but_not_elsewhere(make_runtime) -> None:
    rt = make_runtime()
    plan = rt.plan(StepRequest("devops", "fix", None, StepKind.TEAM_FIX))
    assert writable(plan.scope, "src/app.py") and writable(plan.scope, "tests/test_x.py")
    assert not writable(plan.scope, "random/notes.txt")


def test_a_review_fix_works_in_the_worktree_and_writes_only_the_files(make_runtime) -> None:
    rt = make_runtime()
    wt = rt.config.run_dir / "review"
    system.make_dirs(wt)
    rt.state.boundary = bd.Boundary(Edge.END, 1, stage=Stage.REVIEW)
    rt.state.boundary.failure = bd.Failure(
        Stage.REVIEW, bd.FixCase.REVIEW_CONFLICT, "c", files=["a.py"]
    )
    plan = rt.plan(StepRequest("devops", "fix", None, StepKind.REVIEW_FIX))
    assert plan.scope.repo == wt
    assert writable(plan.scope, "a.py") and not writable(plan.scope, "b.py")


# ----- U13: the Manager sees the boundary -----------------------------------


def test_apply_manager_marks_an_escalated_boundary_reviewed(make_runtime) -> None:
    rt = make_runtime()
    b = rt.state.boundary = bd.Boundary(Edge.END, 2, hold=BoundaryHold.ESCALATED, escalated="boom")
    b.failure = bd.Failure(Stage.CHECK, bd.FixCase.TEAM_CHECK, "boom")
    b.streak = [bd.setback(b, b.failure)]
    out = manager_report(rt)
    assert out["boundary"]["reviewed"] is True and b.hold is BoundaryHold.REVIEWED


def test_apply_manager_leaves_other_boundaries_alone(make_runtime) -> None:
    rt = make_runtime()
    rt.state.boundary = bd.Boundary(Edge.END, 2, hold=BoundaryHold.ERROR)
    assert "boundary" not in manager_report(rt)
    assert rt.state.boundary.hold is BoundaryHold.ERROR


def test_manager_context_has_repeated_boundary_only_while_escalated(make_runtime) -> None:
    rt = make_runtime()
    assert "repeated_boundary" not in rt._manager_context()
    b = rt.state.boundary = bd.Boundary(Edge.END, 2, hold=BoundaryHold.ESCALATED, escalated="boom")
    b.failure = bd.Failure(Stage.CHECK, bd.FixCase.TEAM_CHECK, "boom")
    b.streak = [bd.setback(b, b.failure)]
    context = json.loads(rt._manager_context().split("\n", 1)[1])
    assert context["repeated_boundary"]["edge"] == "end"


# ----- hand-over rows -------------------------------------------------------


def brep(hold=None, **fields) -> dict:
    base = {
        "edge": "end",
        "sprint": 2,
        "stage": "push",
        "target": "origin/main",
        "team_branch": "agile-team",
    }
    return {"role": "runner", "status": "boundary", "boundary": {**base, "hold": hold, **fields}}


BOUNDARY_ROWS = [
    (
        brep("sync_conflict", edge="start", stage="sync", files=["a.py", "b.py"]),
        T.SYNC_CONFLICT,
        "run: sprint 2 start: merging origin/main into agile-team conflicts in a.py, b.py; the merge was "  # noqa: E501
        "aborted and the team branch is unchanged. Ask the human to merge origin/main into agile-team by "  # noqa: E501
        "hand and commit it, then continue_boundary",
    ),
    (
        brep("push_permission", branches=["team/sprint-1", "team/sprint-2"]),
        T.PUSH_PERMISSION,
        "run: sprint 2's review branches are built and checked: team/sprint-1, team/sprint-2. Ask the human "  # noqa: E501
        "once: may the team push review branches and open or update pull requests? Then "
        'set_push_permission with "yes" or "no"; it applies to every later sprint',
    ),
    (
        brep("push_rejected", branch="team/sprint-2", reason="stale info"),
        T.PUSH_REJECTED,
        "run: pushing team/sprint-2 was rejected and nothing after it was pushed: stale info. Tell the human "  # noqa: E501
        "(someone else may have pushed to it), then continue_boundary",
    ),
    (
        brep("error", reason="GitError: x"),
        T.BOUNDARY_ERROR,
        "run: sprint 2 end boundary failed at push: GitError: x; details in .team/run/crash.log. Fix it, "  # noqa: E501
        "then continue_boundary",
    ),
]


@pytest.mark.parametrize(("report", "trigger", "line"), BOUNDARY_ROWS)
def test_boundary_rows_match_and_format(report, trigger, line) -> None:
    assert handover.triggers(report) == [trigger]
    assert handover.report_lines(report, None) == [line]


def test_escalated_row_matches_only_a_reviewed_boundary() -> None:
    report = {
        **brep("reviewed", stage="check", reviewed=True),
        "role": "manager",
        "summary": "flaky test",
    }
    assert handover.triggers(report) == [T.BOUNDARY_ESCALATED]
    assert handover.report_lines(report, None) == [
        "run: sprint 2 end boundary failed the same way again at check; the manager reviewed it: flaky test. "  # noqa: E501
        "Once something has changed (a fix, the human's answer), continue_boundary(note); your note reaches "  # noqa: E501
        "the next devops fix"
    ]


BOUNDARY_TRIGGERS = {
    T.SYNC_CONFLICT,
    T.PUSH_PERMISSION,
    T.PUSH_REJECTED,
    T.BOUNDARY_ERROR,
    T.BOUNDARY_ESCALATED,
}


@pytest.mark.parametrize(
    "report",
    [
        brep(None, outcome="merged"),
        brep("escalated"),
        {"role": "runner", "status": "boundary", "boundary": {}},
    ],
)
def test_other_boundary_reports_hand_over_nothing(report) -> None:
    assert not set(handover.triggers(report)) & BOUNDARY_TRIGGERS


def test_a_hold_reason_for_a_fix_step_is_the_usual_one() -> None:
    assert handover.hold_reason({"role": "devops", "status": "done"}) is None
    assert (
        handover.hold_reason({"role": "devops", "status": "blocked", "open_questions": ["q"]})
        is not None
    )

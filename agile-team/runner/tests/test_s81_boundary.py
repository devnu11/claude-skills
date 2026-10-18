"""s81: boundary CI outcomes, record_ci_bug, the bug-first rule, and state reload."""

from __future__ import annotations

import asyncio
import json

import pytest
from agile_team import boundary as bd
from agile_team import ci, state
from agile_team.boundary import BoundaryHold, Edge, Stage
from agile_team.ci import Bucket, Check, CiResult, CiVerdict
from agile_team.gates import StoryState, StoryStatus
from agile_team.po_tools import (
    DONE_BUG,
    NO_CI_HOLD,
    UNKNOWN_BUG,
    Tools,
)
from agile_team.upstream import PrMode, UpstreamError

from .fake_system import FakeSystem
from .test_boundary_runner import Env, at_push, entry

LINK = "https://github.com/o/r/actions/runs/1/job/77"
RED = [Check("unit", Bucket.FAIL, "ci", LINK)]
GREEN = [Check("unit", Bucket.PASS, "ci", LINK)]
FAILED_LINE = "FAILED tests/x.py::test_y"


@pytest.fixture
def env(make_runtime) -> Env:
    return Env(make_runtime)


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


def at_ci(env: Env, checks: list[Check], **kw) -> bd.Boundary:
    env.prs.check_list = checks
    env.prs.failed_log = lambda link: FAILED_LINE
    env.rt.state.upstream.stack = [
        env.as_built(entry(1, pr=5, mode=PrMode.READY, url="https://h/5"))
    ]
    return env.open(Edge.END, stage=Stage.CI, **kw)


def done_event(env: Env) -> dict:
    return env.events()[-1].data


# ----- outcomes of the ci stage ----------------------------------------------


def test_red_holds_with_the_failing_lines_and_says_nothing_is_ready(env: Env) -> None:
    b = at_ci(env, RED)
    env.drive()
    data = done_event(env)
    assert b.hold is BoundaryHold.CI_FAILED and env.rt.state.boundary is b
    assert data["outcome"] == "held" and data["ci"] == "red"
    assert FAILED_LINE in data["checks"]
    assert ci.READY_PHRASE not in env.rt.state.upstream.report
    assert env.rt.state.upstream.stack[0].ci.verdict is CiVerdict.RED
    assert not unsaid_ready(env)


def unsaid_ready(env: Env) -> list:
    """The posted notes that call a PR ready."""
    return [m for m in env.rt.relay.messages() if ci.READY_PHRASE in m.text]


def test_red_report_becomes_the_ci_failed_handover_line(env: Env) -> None:
    from agile_team import handover

    at_ci(env, RED)
    (report,) = env.drive()
    assert handover.triggers(report) == [handover.Trigger.CI_FAILED]
    (line,) = handover.report_lines(report, None)
    assert "unit" in line and FAILED_LINE in line and "NOT ready" in line
    assert "record_ci_bug" in line and ci.READY_PHRASE not in line
    due = env.br.due()
    assert due is None or due.kind is not bd.StepKind.BOUNDARY


def test_a_held_boundary_makes_a_sprint_story_wait(env: Env) -> None:
    at_ci(env, RED)
    env.drive()
    assert env.rt.state.boundary.hold is BoundaryHold.CI_FAILED
    assert env.br.open_end() is False


def test_timeout_holds_pending_then_continue_goes_green(env: Env) -> None:
    b = at_ci(env, [Check("unit", Bucket.PENDING, "ci", "")])
    env.prs.wait_checks = lambda n, s: False
    env.drive()
    data = done_event(env)
    assert b.hold is BoundaryHold.CI_PENDING and data["ci"] == "pending"
    assert "CI checks still running" in data["reason"]
    assert "unit" in data["checks"]
    assert not unsaid_ready(env)
    env.prs.check_list, env.prs.wait_checks = GREEN, lambda n, s: True
    call(Tools(env.rt).continue_boundary({"note": ""}))
    env.drive()
    up = env.rt.state.upstream
    assert env.rt.state.boundary is None and up.closed == 1
    assert ci.READY_PHRASE in up.report and done_event(env)["ci"] == "green"


def test_continue_at_ci_failed_is_refused_and_changes_nothing(env: Env) -> None:
    b = at_ci(env, RED)
    env.drive()
    seen = len(env.events())
    out = call(Tools(env.rt).continue_boundary({"note": "retry"}))
    assert out["status"] == "refused"
    assert b.hold is BoundaryHold.CI_FAILED and len(env.events()) == seen


def test_no_checks_finish_as_none_and_never_call_it_ready(env: Env) -> None:
    at_ci(env, [])
    env.drive()
    up = env.rt.state.upstream
    assert env.rt.state.boundary is None and done_event(env)["ci"] == "none"
    assert up.report.startswith("Sprint 1's review branches are pushed")
    assert ci.NO_CHECKS_WHY in up.report and ci.READY_PHRASE not in up.report
    assert not unsaid_ready(env)


def test_a_draft_pr_is_watched_like_a_ready_one_r5(env: Env) -> None:
    at_ci(env, GREEN)
    env.rt.state.upstream.stack[0].mode = PrMode.DRAFT
    env.drive()
    up = env.rt.state.upstream
    assert done_event(env)["ci"] == "green"  # s159 R5: the draft is watched, no longer "none"
    assert ci.NO_OPEN_PR_WHY not in up.report


@pytest.mark.parametrize("why", ["no", "gh"])
def test_no_permission_or_no_gh_is_local_with_ci_none(env: Env, fake: FakeSystem, why: str) -> None:
    at_push(env, entry(1))
    if why == "no":
        env.rt.state.upstream.push = bd.Permission.NO
    else:
        env.prs.reason = "gh is not installed"

    def never(n, s):
        raise AssertionError("the ci stage must not run")

    env.prs.wait_checks = never
    env.drive()
    done = env.events()[-1].data
    assert done["outcome"] == "done" and done["ci"] == "none"
    assert "not rebased" in env.rt.state.upstream.report
    assert env.rt.state.boundary is None and ci.READY_PHRASE not in env.rt.state.upstream.report


def test_start_never_reaches_ci_and_push_is_followed_by_ci_then_replay() -> None:
    """START never runs PUSH or CI; END runs PUSH, CI, REPLAY, PUSH_REPLAYED, CI_REPLAYED."""
    assert bd.next_stage(bd.Boundary(Edge.START, 1, stage=Stage.CHECK)) is Stage.PUSH_REPLAYED
    assert Stage.CI not in bd.EDGE_STAGES[Edge.START]
    assert bd.next_stage(bd.Boundary(Edge.END, 1, stage=Stage.PUSH)) is Stage.CI
    assert bd.next_stage(bd.Boundary(Edge.END, 1, stage=Stage.CI)) is Stage.REPLAY


def test_a_pr_service_error_holds_as_error(env: Env) -> None:
    b = at_ci(env, GREEN)

    def boom(n, s):
        raise UpstreamError("gh broke")

    env.prs.wait_checks = boom
    env.drive()
    assert b.hold is BoundaryHold.ERROR


def test_a_full_push_run_records_ci_on_the_entry(env: Env, fake: FakeSystem) -> None:
    first = env.as_built(entry(1))
    first.pushed = first.as_is = ""
    at_push(env, first)
    env.rt.state.upstream.push = bd.Permission.YES
    env.drive()
    [e] = env.rt.state.upstream.stack
    assert isinstance(e.ci, CiResult) and e.ci.verdict is CiVerdict.GREEN
    assert "ready to merge" in env.rt.state.upstream.report


# ----- record_ci_bug ---------------------------------------------------------


def add_story(env: Env, sid: str, status: StoryStatus = StoryStatus.ACTIVE) -> None:
    env.rt.state.stories[sid] = StoryState(sid, "Bug", "design", status=status)


def test_record_ci_bug_refused_without_a_boundary(env: Env) -> None:
    out = call(Tools(env.rt).record_ci_bug({"story": "s2"}))
    assert out["status"] == "refused" and out["reason"] == NO_CI_HOLD


def test_record_ci_bug_refused_on_another_hold(env: Env) -> None:
    env.open(Edge.END, hold=BoundaryHold.ERROR)
    out = call(Tools(env.rt).record_ci_bug({"story": "s2"}))
    assert out["reason"] == NO_CI_HOLD and env.rt.state.boundary is not None


def test_record_ci_bug_refused_for_an_unknown_story(env: Env) -> None:
    at_ci(env, RED, hold=BoundaryHold.CI_FAILED)
    out = call(Tools(env.rt).record_ci_bug({"story": "s9"}))
    assert out["reason"] == UNKNOWN_BUG.format(story="s9")


def test_record_ci_bug_refused_for_a_done_story(env: Env) -> None:
    at_ci(env, RED, hold=BoundaryHold.CI_FAILED)
    out = call(Tools(env.rt).record_ci_bug({"story": "s1"}))
    assert out["reason"] == DONE_BUG.format(story="s1")
    assert env.rt.state.boundary is not None


def test_record_ci_bug_closes_the_boundary_and_records_the_story(env: Env) -> None:
    at_ci(env, RED)
    env.drive()
    add_story(env, "s2")
    out = call(Tools(env.rt).record_ci_bug({"story": "s2"}))
    up = env.rt.state.upstream
    assert out == {"status": "recorded", "story": "s2"}
    assert env.rt.state.boundary is None and up.closed == 1 and up.ci_bug == "s2"
    assert "checks failed" in up.report and "story s2 opened" in up.report
    assert ci.READY_PHRASE not in up.report
    data = done_event(env)
    assert data["outcome"] == "done" and data["ci"] == "red" and data["story"] == "s2"


# ----- bug first -------------------------------------------------------------


def start(env: Env, ids: list[str]) -> dict:
    return call(Tools(env.rt).start_sprint({"goal": "g", "stories": ids}))


def test_start_sprint_refuses_when_the_bug_is_not_first(env: Env) -> None:
    add_story(env, "s2")
    add_story(env, "s3")
    env.rt.state.upstream.ci_bug = "s2"
    out = start(env, ["s3", "s2"])
    assert out["status"] == "refused"
    assert out["reason"] == bd.CI_BUG_FIRST.format(story="s2")
    assert env.rt.state.upstream.ci_bug == "s2"


def test_start_sprint_accepts_the_bug_first_and_clears_it(env: Env) -> None:
    add_story(env, "s2")
    add_story(env, "s3")
    env.rt.state.upstream.ci_bug = "s2"
    out = start(env, ["s2", "s3"])
    assert out.get("status") != "refused"
    assert env.rt.state.upstream.ci_bug == ""


def test_a_done_bug_story_gives_no_refusal_and_is_cleared(env: Env) -> None:
    add_story(env, "s3")
    add_story(env, "s2", StoryStatus.DONE)
    env.rt.state.upstream.ci_bug = "s2"
    out = start(env, ["s3"])
    assert out.get("status") != "refused"
    assert env.rt.state.upstream.ci_bug == ""


# ----- state reload ----------------------------------------------------------


def test_a_legacy_state_without_ci_or_ci_bug_loads() -> None:
    legacy = state.RunState()
    data = json.loads(legacy.to_json())
    legacy.upstream.stack = [entry(1, pr=5)]
    data = json.loads(legacy.to_json())
    data["upstream"].pop("ci_bug", None)
    for e in data["upstream"]["stack"]:
        e.pop("ci", None)
    loaded = state.RunState.from_json(json.dumps(data))
    assert loaded.upstream.ci_bug == "" and loaded.upstream.stack[0].ci is None


def test_a_saved_entry_ci_loads_back_as_a_ci_result() -> None:
    result = CiResult(
        5, "https://h/5", "abc", CiVerdict.RED, [Check("u", Bucket.FAIL, "ci", "l", ["x"])]
    )
    st = state.RunState()
    st.upstream.stack = [entry(1, pr=5, ci=result)]
    st.upstream.ci_bug = "s2"
    loaded = state.RunState.from_json(st.to_json())
    got = loaded.upstream.stack[0].ci
    assert isinstance(got, CiResult) and got.verdict is CiVerdict.RED and got.pr == 5
    assert loaded.upstream.ci_bug == "s2"

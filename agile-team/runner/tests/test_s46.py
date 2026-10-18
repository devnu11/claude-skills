"""s46: code already in passes the tests gate (K), `advance` ruling (A), dispute output (D)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from agile_team import dispatch, gates, handover, roles, state, system
from agile_team.config import PIPELINE_STEPS
from agile_team.dispatch import Runtime, StepRequest
from agile_team.gates import OpenDispute, StoryState, StoryStatus, Verdict
from agile_team.loops import Setback
from agile_team.roles import Dispute, Handoff, HandoffError

from .conftest import FakeQuery, FakeRunner, handoff
from .pipeline_helpers import add_story

STEPS = list(PIPELINE_STEPS)
SHA = "abc1234"
SHA2 = "def5678"
ANCESTOR = "git merge-base --is-ancestor {sha} HEAD"
ADVANCE_LAST = "story s1 is at {step}, its last step; advance cannot mark it done"


def story(step: str = "tests", **kw: Any) -> StoryState:
    kw.setdefault("sprint", 1)
    return StoryState("s1", "Add todo", step, **kw)


def pipeline(results=None, steps=STEPS, cap=3):
    runner = FakeRunner(results)
    checks = gates.Checks({"test": "T", "coverage": "C"}, 95.0, runner)
    return gates.Pipeline(list(steps), cap, checks), runner


def landed(*shas: str) -> dict[str, tuple[int, str]]:
    """Ancestor results: ``shas`` are in the branch, anything else exits ``rest``."""
    return {ANCESTOR.format(sha=s): (0, "") for s in shas}


def done() -> Handoff:
    return Handoff("done", summary="s")


# ----- K1 ------------------------------------------------------------------


def write(repo: Path, rel: str, text: str = "x\n"):
    def action() -> None:
        system.make_dirs((repo / rel).parent)
        system.write_text(repo / rel, text)

    return action


@pytest.fixture(autouse=True)
def tracked(configured: Path, fake) -> None:
    """Model the working tree so a step's edits are committed."""
    fake.track()


def repeated_story(rt: Runtime, step: str = "tests", **kw: Any) -> StoryState:
    """An escalated story with a one-entry streak, as the Manager gets it."""
    st = add_story(rt, step=step, status=StoryStatus.NEEDS_MANAGER, repeated="same", **kw)
    st.streak = [Setback(step, step, "unit-tester", "bounce", "runner", "same")]
    return st


def run_step(rt: Runtime, role: str, sid: str = "s1") -> dict[str, Any]:
    return asyncio.run(rt.run_role(StepRequest(role, "go", sid)))


def test_developer_commit_is_recorded(make_runtime, configured: Path) -> None:
    rt = make_runtime(FakeQuery(action=write(configured, "src/todo.py")), FakeRunner())
    add_story(rt, step="implement")
    report = run_step(rt, "developer-cli")
    assert rt.state.stories["s1"].code_commits == [report["commit"]]


def test_developer_commit_is_recorded_on_a_bounce(make_runtime, configured: Path) -> None:
    text = handoff("changes_requested", summary="no", next_role="architect")
    rt = make_runtime(FakeQuery(text, action=write(configured, "src/todo.py")), FakeRunner())
    add_story(rt, step="implement")
    report = run_step(rt, "developer-cli")
    assert rt.state.stories["s1"].code_commits == [report["commit"]]


def test_later_developer_commits_append(make_runtime, configured: Path) -> None:
    q = FakeQuery(action=write(configured, "src/a.py"))
    rt = make_runtime(q, FakeRunner())
    add_story(rt, step="implement")
    first = run_step(rt, "developer-cli")["commit"]
    rt.state.stories["s1"].step = "implement"
    q.action = write(configured, "src/b.py")
    second = run_step(rt, "developer-cli")["commit"]
    assert rt.state.stories["s1"].code_commits == [first, second]


def test_other_roles_do_not_record(make_runtime, configured: Path) -> None:
    rt = make_runtime(FakeQuery(action=write(configured, "docs/design.md")), FakeRunner())
    add_story(rt, step="design")
    assert run_step(rt, "architect")["commit"]
    assert rt.state.stories["s1"].code_commits == []


def test_nothing_to_commit_records_nothing(make_runtime) -> None:
    rt = make_runtime(FakeQuery(), FakeRunner())
    add_story(rt, step="implement")
    run_step(rt, "developer-cli")
    assert rt.state.stories["s1"].code_commits == []


def test_code_commits_round_trip_and_legacy() -> None:
    assert story().code_commits == []
    st = state.RunState()
    st.stories["s1"] = story("review", code_commits=[SHA, SHA2])
    back = state.RunState.from_json(st.to_json())
    assert back.stories["s1"].code_commits == [SHA, SHA2]
    data = json.loads(st.to_json())
    del data["stories"]["s1"]["code_commits"]
    assert state.RunState.from_json(json.dumps(data)).stories["s1"].code_commits == []


# ----- K2 ------------------------------------------------------------------


def test_code_in_with_implemented_runs_nothing() -> None:
    p, runner = pipeline()
    assert p.checks.code_in(story(implemented=1, code_commits=[SHA])) is True
    assert runner.calls == []


def test_code_in_without_commits_runs_nothing() -> None:
    p, runner = pipeline()
    assert p.checks.code_in(story()) is False
    assert runner.calls == []


def test_code_in_any_commit_in_branch_counts() -> None:
    p, runner = pipeline({ANCESTOR.format(sha=SHA): (1, ""), ANCESTOR.format(sha=SHA2): (0, "")})
    assert p.checks.code_in(story(code_commits=[SHA, SHA2])) is True
    assert runner.calls == [ANCESTOR.format(sha=SHA), ANCESTOR.format(sha=SHA2)]


@pytest.mark.parametrize("code", [1, 128])
def test_code_in_false_when_no_commit_is_an_ancestor(code) -> None:
    p, _ = pipeline({ANCESTOR.format(sha=SHA): (code, "")})
    assert p.checks.code_in(story(code_commits=[SHA])) is False


# ----- K3 / K4 ---------------------------------------------------------------


def settle(st, h, results=None):
    p, runner = pipeline(results)
    out = p.evaluate(st, h)
    p.advance(st, out)
    return out, runner


def test_a_done_tests_step_passes_whatever_the_recorded_commits() -> None:
    st = story(code_commits=[SHA])
    out, runner = settle(st, done(), {ANCESTOR.format(sha=SHA): (128, "")})
    assert out.verdict is Verdict.PASS and st.step == "implement"
    assert runner.calls == []


def test_open_dispute_wins_and_runs_no_ancestor_command() -> None:
    d = OpenDispute("t::a", "W6", "why", "tests/t.py", "h")
    st = story(code_commits=[SHA], dispute=d)
    p, runner = pipeline({"T": (0, "")})
    p.checks.read = lambda _path: None
    out = p.evaluate(st, done())
    assert out.verdict is Verdict.PASS and out.reason == "disputed test changed"
    assert not any("merge-base" in c for c in runner.calls)


# ----- AC1 end to end ---------------------------------------------------------


def test_s40_route_dispute_cleared_by_fault_then_done_passes(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff(summary="ok", fault="unit-tester")), FakeRunner())
    st = repeated_story(rt)
    st.code_commits = [SHA]
    st.dispute = OpenDispute("t::a", "W6", "why", "tests/t.py", "h")
    run_step(rt, "manager")
    assert st.dispute is None and st.step == "tests" and st.implemented == 0
    rt.query_fn.text = handoff(summary="green")
    report = run_step(rt, "unit-tester")
    assert report["gate"]["verdict"] is Verdict.PASS
    assert st.step == "implement" and st.implemented == 0
    assert handover.triggers(report) == []


# ----- K5 ----------------------------------------------------------------------


def prompt_at(make_runtime, step, results=None, role="unit-tester", **kw) -> str:
    rt = make_runtime(FakeQuery(), FakeRunner(results))
    add_story(rt, step=step, **kw)
    run_step(rt, role)
    return rt.query_fn.calls[0]["prompt"]


# ----- K6 ----------------------------------------------------------------------


def code_view(make_runtime, results, **kw) -> dict[str, Any]:
    rt = make_runtime(FakeQuery(), FakeRunner(results))
    st = repeated_story(rt, **kw)
    return rt._repeated_context(st)["repeated_setback"]["code"]


def test_manager_sees_only_in_branch_commits(make_runtime) -> None:
    results = {**landed(SHA2), ANCESTOR.format(sha=SHA): (1, "")}
    view = code_view(make_runtime, results, code_commits=[SHA, SHA2])
    assert view == {"implemented": 0, "code_commits": [SHA2], "code_in": True}


def test_manager_sees_no_code(make_runtime) -> None:
    view = code_view(make_runtime, None)
    assert view == {"implemented": 0, "code_commits": [], "code_in": False}


def test_manager_sees_implemented_counts(make_runtime) -> None:
    view = code_view(make_runtime, None, implemented=2)
    assert view == {"implemented": 2, "code_commits": [], "code_in": True}


# ----- A1 ----------------------------------------------------------------------


def dirty(**kw) -> StoryState:
    base = dict(
        rounds=3,
        disputes=2,
        dispute=OpenDispute("t", "r", "x"),
        streak=[Setback("tests", "tests", "unit-tester", "bounce", "runner", "k")],
        run=[],
        repeated="k",
        escalated_by="repeat",
        status=StoryStatus.NEEDS_MANAGER,
    )
    return story(**{**base, **kw})


def test_advance_moves_one_step_and_clears_the_loop() -> None:
    p, _ = pipeline()
    st = dirty()
    p.apply_ruling(st, "advance")
    assert (st.step, st.status) == ("implement", StoryStatus.ACTIVE)
    assert (st.rounds, st.disputes, st.dispute) == (0, 0, None)
    assert (st.streak, st.run, st.repeated, st.escalated_by) == ([], [], None, None)


def test_advance_from_implement_counts_implemented() -> None:
    p, _ = pipeline()
    st = story("implement")
    p.apply_ruling(st, "advance")
    assert (st.step, st.implemented) == ("quality", 1)


def test_advance_activates_blocked_story() -> None:
    p, _ = pipeline()
    st = story(status=StoryStatus.BLOCKED)
    p.apply_ruling(st, "advance")
    assert st.status is StoryStatus.ACTIVE and st.step == "implement"


def test_ruling_move_refusal_only_at_last_step() -> None:
    p, _ = pipeline()
    last = p.steps[-1]
    msg = p.ruling_move_refusal(story(last), "advance")
    assert msg == ADVANCE_LAST.format(step=last)
    assert p.ruling_move_refusal(story("tests"), "advance") is None
    assert p.ruling_move_refusal(story(last), "rescope") is None


def test_advance_is_a_ruling() -> None:
    assert roles.RULINGS[-1] == "advance"
    assert roles.parse_handoff(handoff(ruling="advance")).ruling == "advance"


def test_bad_ruling_message_lists_advance() -> None:
    with pytest.raises(HandoffError) as e:
        roles.parse_handoff(handoff(ruling="nope"))
    assert "'advance'" in str(e.value)


# ----- A2 / A3 / A4 --------------------------------------------------------------


def events_of(rt: Runtime, kind: str) -> list[Any]:
    return [e for e in rt.events.events() if e.kind == kind]


def test_runner_fault_then_advance(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff(summary="why", fault="runner", ruling="advance")))
    st = repeated_story(rt)
    report = run_step(rt, "manager")
    assert report["fault"]["kind"] == "runner" and report["ruling"]["applied"] is True
    assert (st.step, st.status) == ("implement", StoryStatus.ACTIVE)
    assert events_of(rt, "fault")[0].data["kind"] == "runner"
    assert events_of(rt, "ruling")[0].data["now_at"] == "implement"


def test_pipeline_fault_then_advance(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff(fault="unit-tester", ruling="advance")))
    st = repeated_story(rt, "implement")
    run_step(rt, "manager")
    assert st.step == "implement" and st.implemented == 0
    assert [e.data["now_at"] for e in events_of(rt, "ruling")] == ["implement"]
    assert events_of(rt, "fault")[0].data["fault"] == "unit-tester"


def test_advance_at_last_step_is_refused(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff(ruling="advance")))
    last = rt.pipeline.steps[-1]
    st = add_story(rt, step=last, status=StoryStatus.NEEDS_MANAGER, rounds=3)
    report = run_step(rt, "manager")
    assert report["ruling"] == {
        "ruling": "advance",
        "applied": False,
        "why": ADVANCE_LAST.format(step=last),
    }
    assert (st.step, st.rounds) == (last, 3)
    assert events_of(rt, "ruling") == []
    assert handover.Trigger.RULING_NOT_APPLIED in handover.triggers(report)


def test_advance_on_done_story_gives_the_done_text(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff(ruling="advance")))
    add_story(rt, step=rt.pipeline.steps[-1], status=StoryStatus.DONE)
    why = run_step(rt, "manager")["ruling"]["why"]
    assert why == "story s1 is done; a ruling cannot move it"


def test_ruling_reason_parsing() -> None:
    parse = roles.parse_handoff
    assert parse(handoff(ruling="advance", ruling_reason="x", summary="s")).ruling_reason == "x"
    assert parse(handoff(ruling="advance", summary="s")).ruling_reason == "s"
    assert parse(handoff(ruling="advance", ruling_reason="", summary="s")).ruling_reason == "s"


def test_ruling_reason_must_be_a_string() -> None:
    with pytest.raises(HandoffError, match="handoff ruling_reason must be a string"):
        roles.parse_handoff(handoff(ruling="advance", ruling_reason=3))


@pytest.mark.parametrize("ruling", ["rescope", "escalate", "advance"])
def test_ruling_event_logs_the_reason(make_runtime, ruling) -> None:
    rt = make_runtime(FakeQuery(handoff(ruling=ruling, ruling_reason="because", summary="s")))
    add_story(rt, step="tests", status=StoryStatus.NEEDS_MANAGER, rounds=3)
    run_step(rt, "manager")
    data = events_of(rt, "ruling")[0].data
    assert set(data) == {"ruling", "reason", "now_at"} and data["reason"] == "because"
    assert data["ruling"] == ruling


def test_ruling_event_reason_defaults_to_summary(make_runtime) -> None:
    rt = make_runtime(FakeQuery(handoff(ruling="rescope", summary="the summary")))
    add_story(rt, step="tests", status=StoryStatus.NEEDS_MANAGER, rounds=3)
    run_step(rt, "manager")
    assert events_of(rt, "ruling")[0].data["reason"] == "the summary"


# ----- D1 / D2 -------------------------------------------------------------------


class Disputes:
    """Command runner for raising a dispute on a tracked file."""

    def __init__(self, code: int, out: str, tracked: bool = True):
        self.code, self.out, self.tracked = code, out, tracked
        self.calls: list[str] = []

    def __call__(self, command: str) -> tuple[int, str]:
        self.calls.append(command)
        if command == "T":
            return self.code, self.out
        if command.startswith("git ls-files"):
            return (0, "tests/test_x.py\n") if self.tracked else (0, "")
        return 0, ""


def raise_dispute(runner: Disputes) -> gates.Outcome:
    checks = gates.Checks({"test": "T", "coverage": "C"}, 95.0, runner)
    checks.read = lambda _p: "def test_x(): pass\n"
    p = gates.Pipeline(list(STEPS), 3, checks)
    h = Handoff("done", summary="s", dispute=Dispute("tests/test_x.py::test_x", "W6", "why"))
    return p.evaluate(story("implement"), h)


def test_name_helper() -> None:
    assert gates.test_name("a.py") == "a.py"
    assert gates.test_name("a.py::C::t[1]") == "t[1]"


def test_dispute_with_passing_tests_stores_green_text() -> None:
    runner = Disputes(0, "all good")
    out = raise_dispute(runner)
    assert runner.calls.count("T") == 1
    expected = gates.TEST_GREEN.format(test="tests/test_x.py::test_x")
    assert out.verdict is Verdict.DISPUTE and out.dispute.output == expected


def test_dispute_with_failing_tests_stores_excerpt() -> None:
    lines = ["collected", "noise"] + [f"test_x line {i}" for i in range(60)]
    lines += ["FAILED tests/test_x.py::test_x - AssertionError: boom"]
    runner = Disputes(1, "\n".join(lines))
    got = raise_dispute(runner).dispute.output.splitlines()
    assert got[0] == "test_x line 0" and "noise" not in got
    assert got[:40] == [f"test_x line {i}" for i in range(40)]
    assert got[-1] == "FAILED tests/test_x.py::test_x - AssertionError: boom"
    assert "test_x line 59" in got and "test_x line 41" in got
    assert len(got) <= 40 + 21


def test_dispute_with_failing_tests_not_naming_the_test() -> None:
    out_text = "\n".join(f"line {i}" for i in range(50))
    runner = Disputes(1, out_text)
    expected = gates.TEST_NOT_IN_OUTPUT.format(name="test_x", tail=gates.tail(out_text))
    assert raise_dispute(runner).dispute.output == expected


def test_rejected_dispute_runs_no_test_command() -> None:
    runner = Disputes(1, "x", tracked=False)
    out = raise_dispute(runner)
    assert out.verdict is Verdict.BOUNCE and "T" not in runner.calls


def test_legacy_dispute_has_empty_output() -> None:
    assert OpenDispute("t", "r", "x").output == ""
    st = state.RunState()
    st.stories["s1"] = story(dispute=OpenDispute("t", "r", "x", "f", "h"))
    data = json.loads(st.to_json())
    data["stories"]["s1"]["dispute"].pop("output", None)
    back = state.RunState.from_json(json.dumps(data))
    assert back.stories["s1"].dispute.output == ""


# ----- D3 ------------------------------------------------------------------------


def test_dispute_brief_quotes_the_output(make_runtime) -> None:
    d = OpenDispute("t::a", "W6", "why", "abc", output="AssertionError: nope")
    p = prompt_at(make_runtime, "tests", dispute=d)
    head = "Test dispute (raised): t::a contradicts W6: why"
    block = dispatch.DISPUTE_OUTPUT.format(output="AssertionError: nope")
    assert f"{head}\n{block}" in p


def test_dispute_brief_without_output_has_no_block(make_runtime) -> None:
    d = OpenDispute("t::a", "W6", "why", "abc")
    p = prompt_at(make_runtime, "tests", dispute=d)
    assert "Test dispute (raised)" in p and "Output of the test command" not in p


def test_architect_gets_the_output_too(make_runtime) -> None:
    d = OpenDispute("t::a", "W6", "why", "abc", output="boom")
    p = prompt_at(make_runtime, "design", role="architect", dispute=d)
    assert "Output of the test command when the dispute was raised:\n```\nboom\n```" in p

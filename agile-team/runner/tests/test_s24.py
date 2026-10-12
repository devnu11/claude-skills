"""s24: tests gate on reworked stories (G1-G7) and holds on done stories (G8, G9)."""

import asyncio
import json

import pytest
from agile_team import gates, roles, state, system
from agile_team.config import PIPELINE_STEPS
from agile_team.dispatch import REWORK_BRIEF, StepRequest
from agile_team.gates import StoryState, StoryStatus, Verdict
from agile_team.roles import Handoff, HandoffError, TestClaim
from agile_team.router import _scribable

from .conftest import FakeQuery, FakeRunner, handoff

STEPS = list(PIPELINE_STEPS)
RED = {"T": (1, "FAILED")}
COVERED = {"C": (0, "TOTAL 100%")}
UNCLAIMED = (
    "tests pass on code from an earlier pass; write a failing test, "
    'or hand off "tests": "changed" or "tests": "confirmed"'
)
FIRST_PASS = "tests pass before implementation; write a failing test"


def story(step: str = "tests", **kw) -> StoryState:
    kw.setdefault("sprint", 1)
    return StoryState("s1", "Add todo", step, **kw)


def pipeline(results=None, steps=STEPS, cap=3):
    runner = FakeRunner(results)
    checks = gates.Checks({"test": "T", "coverage": "C"}, 95.0, runner)
    return gates.Pipeline(list(steps), cap, checks), runner


def settle(st, h, results=None, **kw):
    p, runner = pipeline(results, **kw)
    out = p.evaluate(st, h)
    p.advance(st, out)
    return out, runner


def done(claim=None) -> Handoff:
    return Handoff("done", summary="s", tests=claim)


# ----- G3 ----------------------------------------------------------------------


def test_claims_parse() -> None:
    assert roles.parse_handoff(handoff("done", tests="changed")).tests is TestClaim.CHANGED
    assert roles.parse_handoff(handoff("done", tests="confirmed")).tests is TestClaim.CONFIRMED
    assert roles.parse_handoff(handoff("done")).tests is None


@pytest.mark.parametrize("bad", ["yes", "", 1])
def test_bad_claims_are_malformed(bad) -> None:
    with pytest.raises(HandoffError) as e:
        roles.parse_handoff(handoff("done", tests=bad))
    assert "handoff tests must be one of ('changed', 'confirmed')" in str(e.value)


def test_report_has_no_tests_key() -> None:
    assert "tests" not in roles.handoff_report(done(TestClaim.CHANGED))


# ----- G1 ----------------------------------------------------------------------


def test_implement_pass_counts() -> None:
    st = story("implement")
    settle(st, done(), COVERED)
    assert (st.implemented, st.step) == (1, "quality")
    st.step = "implement"
    settle(st, done(), COVERED)
    assert st.implemented == 2


def test_other_steps_bounces_and_returns_do_not_count() -> None:
    st = story("design")
    settle(st, done())
    assert (st.implemented, st.step) == (0, "tests")
    st = story("implement")
    settle(st, Handoff("changes_requested", summary="x", next_role="architect"))
    assert st.implemented == 0
    p, _ = pipeline()
    p.advance(st, gates.Outcome(Verdict.RETURN, "r", "e2e"))
    assert st.implemented == 0


def test_last_step_implement_counts_and_finishes() -> None:
    st = story("implement")
    settle(st, done(), COVERED, steps=["implement"])
    assert (st.implemented, st.status) == (1, StoryStatus.DONE)


# ----- G4-G6 -------------------------------------------------------------------


def test_rework_red_passes_to_implement() -> None:
    st = story(implemented=1)
    out, _ = settle(st, done(), RED)
    assert (out.verdict, out.reason, st.step) == (Verdict.PASS, "", "implement")


@pytest.mark.parametrize("claim", [TestClaim.CHANGED, TestClaim.CONFIRMED])
def test_rework_green_with_claim_passes(claim) -> None:
    st = story(implemented=1)
    out, runner = settle(st, done(claim))
    assert out.verdict is Verdict.PASS
    assert out.reason == f"tests pass on code from an earlier pass; tests {claim}"
    assert (st.step, runner.calls) == ("implement", ["T"])


def test_rework_green_without_claim_bounces() -> None:
    st = story(implemented=1)
    out, runner = settle(st, done())
    assert (out.verdict, out.reason) == (Verdict.BOUNCE, UNCLAIMED)
    assert (st.step, st.rounds, runner.calls) == ("tests", 1, ["T"])


def test_first_pass_ignores_claim() -> None:
    st = story()
    out, _ = settle(st, done(TestClaim.CHANGED))
    assert (out.verdict, out.reason, st.step) == (Verdict.BOUNCE, FIRST_PASS, "tests")


def test_first_pass_changes_requested_still_runs_tests_red() -> None:
    st = story()
    out, runner = settle(st, Handoff("changes_requested", summary="x", next_role="architect"))
    assert runner.calls == ["T"] and out.reason == FIRST_PASS


def test_open_dispute_wins_over_rework() -> None:
    st = story(implemented=1, dispute=gates.OpenDispute("t::a", "W6", "why", "abc"))
    p, runner = pipeline({"git diff --quiet abc HEAD -- t": (1, "")})
    out = p.evaluate(st, done(TestClaim.CHANGED))
    assert out.verdict is Verdict.PASS
    assert "T" not in runner.calls


def test_rework_changes_requested_skips_the_suite() -> None:
    st = story(implemented=1)
    out, runner = settle(st, Handoff("changes_requested", summary="x", next_role="architect"))
    assert (st.step, st.rounds, runner.calls) == ("design", 1, [])
    assert out.verdict is Verdict.BOUNCE


# ----- G2 ----------------------------------------------------------------------


def load(step: str, **extra) -> StoryState:
    d = {"id": "s1", "title": "t", "step": step, "status": "active", **extra}
    return state.RunState.from_json(json.dumps({"stories": {"s1": d}})).stories["s1"]


@pytest.mark.parametrize("step", STEPS[STEPS.index("implement") + 1 :])
def test_legacy_past_implement_loads_one(step) -> None:
    assert load(step).implemented == 1


@pytest.mark.parametrize("step", ["design", "tests", "implement"])
def test_legacy_before_implement_loads_zero(step) -> None:
    assert load(step).implemented == 0


def test_explicit_value_wins_and_round_trips() -> None:
    assert load("e2e", implemented=0).implemented == 0
    st = state.RunState()
    st.stories["s1"] = story("review", implemented=2)
    assert state.RunState.from_json(st.to_json()).stories["s1"].implemented == 2


# ----- G7 ----------------------------------------------------------------------


def prompt_at(make_runtime, step, role="unit-tester", **kw) -> str:
    rt = make_runtime(FakeQuery(), runner=FakeRunner())
    rt.state.stories["s1"] = story(step, **kw)
    asyncio.run(rt.run_role(StepRequest(role, "go", "s1")))
    return rt.query_fn.calls[0]["prompt"]


def test_rework_brief_shows_on_reworked_tests(make_runtime) -> None:
    p = prompt_at(make_runtime, "tests", implemented=1)
    assert REWORK_BRIEF in p
    assert p.index("Story s1: Add todo") < p.index(REWORK_BRIEF)


def test_no_rework_brief_on_first_pass_or_other_step(make_runtime) -> None:
    assert REWORK_BRIEF not in prompt_at(make_runtime, "tests")
    assert REWORK_BRIEF not in prompt_at(make_runtime, "design", "architect", implemented=1)


def test_dispute_replaces_rework_brief(make_runtime) -> None:
    d = gates.OpenDispute("t::a", "W6", "why", "abc")
    p = prompt_at(make_runtime, "tests", implemented=1, dispute=d)
    assert REWORK_BRIEF not in p and "Test dispute" in p


# ----- G8, G9 ------------------------------------------------------------------


def test_done_story_hold_clearing_note_and_no_movement(make_runtime) -> None:
    from agile_team.po_tools import Tools

    rt = make_runtime(FakeQuery(), runner=FakeRunner())
    st = rt.state.stories["s1"] = story("review", status=StoryStatus.DONE, hold="x")
    rt.state.scribe_due = ["s1"]
    t = Tools(rt)
    out = json.loads(
        asyncio.run(t.continue_story({"story": "s1", "note": "n"}))["content"][0]["text"]
    )
    assert out["status"] == "continued" and st.hold is None and st.note == "n"
    assert st.status is StoryStatus.DONE
    assert _scribable(st)
    res = asyncio.run(rt.run_role(StepRequest("developer", "go", "s1")))
    assert "story s1 is done" in json.dumps(res)


# ----- G1: disputes and rulings leave `implemented` alone ------------------------


def test_a_dispute_verdict_leaves_implemented_alone() -> None:
    st = story("implement", implemented=1)
    p, _ = pipeline()
    p.advance(st, gates.Outcome(Verdict.DISPUTE, "d", "unit-tester"))
    assert st.implemented == 1


@pytest.mark.parametrize("ruling", ["revise_design", "rescope", "escalate"])
def test_rulings_leave_implemented_alone(ruling) -> None:
    st = story("review", implemented=1, rounds=3)
    pipeline()[0].apply_ruling(st, ruling)
    assert st.implemented == 1


# ----- G8: the hold clearing is saved ---------------------------------------------


def test_clearing_a_done_story_hold_is_saved(make_runtime) -> None:
    from agile_team.po_tools import Tools

    rt = make_runtime(FakeQuery(), runner=FakeRunner())
    rt.state.stories["s1"] = story("review", status=StoryStatus.DONE, hold="x")
    asyncio.run(Tools(rt).continue_story({"story": "s1", "note": "n"}))
    saved = json.loads(system.read_text(rt.config.run_dir / "state.json"))
    assert saved["stories"]["s1"]["hold"] is None and saved["stories"]["s1"]["note"] == "n"

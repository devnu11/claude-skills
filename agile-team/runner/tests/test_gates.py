"""Story pipeline state machine and gates."""

import json
from pathlib import Path

import pytest
from agile_team import gates
from agile_team.config import PIPELINE_STEPS
from agile_team.gates import StoryStatus, Verdict
from agile_team.roles import Handoff

from .conftest import FakeRunner

STEPS = list(PIPELINE_STEPS)


def story(step: str = "design", **kw) -> gates.StoryState:
    kw.setdefault("sprint", 1)
    return gates.StoryState("s1", "Add todo", step, **kw)


def checks(results=None, baseline=None, presentation=None) -> gates.Checks:
    made = gates.Checks({"test": "T", "coverage": "C"}, 95.0, FakeRunner(results), baseline)
    if presentation:
        made.presentation = presentation
    return made


def pipeline(results=None, baseline=None, steps=STEPS, presentation=None) -> gates.Pipeline:
    return gates.Pipeline(list(steps), 3, checks(results, baseline, presentation))


def test_role_fits_step() -> None:
    assert gates.role_fits_step("developer-cli", "implement")
    assert not gates.role_fits_step("developer", "tests")
    assert pipeline().step_for_role("developer-api") == "implement"
    assert pipeline().step_for_role(None) is None
    assert pipeline().step_for_role("manager") is None


@pytest.mark.parametrize(
    ("st", "role", "needle"),
    [
        (None, "developer", "only runs on a story"),
        (story(status=StoryStatus.DONE), "architect", "is done"),
        (story(status=StoryStatus.BLOCKED), "architect", "blocked"),
        (story(status=StoryStatus.NEEDS_MANAGER), "architect", "round cap"),
        (story("tests"), "developer", "needs unit-tester"),
    ],
)
def test_dispatch_refusals(st, role, needle) -> None:
    assert needle in gates.dispatch_refusal(role, st)


def test_dispatch_allowed() -> None:
    assert gates.dispatch_refusal("architect", None) is None
    assert gates.dispatch_refusal("manager", story(status=StoryStatus.NEEDS_MANAGER)) is None
    assert gates.dispatch_refusal("developer-cli", story("implement")) is None


def test_advance_through_pipeline_to_done() -> None:
    s, p = story(), pipeline()
    for _ in STEPS:
        p.advance(s, gates.Outcome(Verdict.PASS))
    assert s.status is StoryStatus.DONE and s.step == "acceptance"


def test_bounce_counts_rounds_and_caps() -> None:
    s, p = story("review"), pipeline()
    for i in range(3):
        p.advance(s, gates.Outcome(Verdict.BOUNCE, bounce_to="implement"))
        assert s.rounds == i + 1
    assert s.status is StoryStatus.NEEDS_MANAGER and s.step == "implement"


def test_hold_does_not_count() -> None:
    s = story("review")
    pipeline().advance(s, gates.Outcome(Verdict.HOLD))
    assert s.rounds == 0 and s.step == "review"


@pytest.mark.parametrize(
    ("ruling", "step", "status"),
    [
        ("rescope", "design", StoryStatus.ACTIVE),
        ("revise_design", "design", StoryStatus.ACTIVE),
        ("upgrade_model", "implement", StoryStatus.ACTIVE),
        ("escalate", "implement", StoryStatus.BLOCKED),
    ],
)
def test_rulings(ruling, step, status) -> None:
    s = story("implement", rounds=3, status=StoryStatus.NEEDS_MANAGER)
    pipeline().apply_ruling(s, ruling)
    assert (s.step, s.status, s.rounds) == (step, status, 0)


def test_revise_design_without_design_step() -> None:
    s = story("implement")
    pipeline(steps=["tests", "implement"]).apply_ruling(s, "revise_design")
    assert s.step == "tests"


@pytest.mark.parametrize(
    ("out", "pct"),
    [
        ("Name Stmts\nTOTAL 10 1 90%\n", 90.0),
        ("lines......: 97.5% (39/40)", 97.5),
        ("TOTAL 10 0 100%\nother 50%", 100.0),
        ("nothing", None),
    ],
)
def test_parse_coverage(out, pct) -> None:
    assert gates.parse_coverage(out) == pct


def test_tests_red_gate() -> None:
    passed = pipeline({"T": (1, "")}).evaluate(story("tests"), Handoff("done"))
    assert passed.verdict is Verdict.PASS
    out = pipeline({"T": (0, "")}).evaluate(story("tests"), Handoff("done"))
    assert out.verdict is Verdict.BOUNCE and out.bounce_to == "tests"
    assert "failing test" in out.reason


def test_green_gate() -> None:
    done = Handoff("done")
    ok = pipeline({"T": (0, ""), "C": (0, "TOTAL 96%")}).evaluate(story("implement"), done)
    assert ok.verdict is Verdict.PASS
    red = pipeline({"T": (1, "boom")}).evaluate(story("implement"), done)
    assert red.verdict is Verdict.BOUNCE and "boom" in red.reason
    assert red.bounce_to == "implement"
    low = pipeline({"C": (0, "TOTAL 80%")}).evaluate(story("implement"), done)
    assert "below 95.0%" in low.reason
    none = pipeline({"C": (0, "n/a")}).evaluate(story("implement"), done)
    assert "could not read" in none.reason


def test_baseline_lowers_requirement() -> None:
    assert checks(baseline=78.0).required_coverage() == 78.0
    out = pipeline({"C": (0, "TOTAL 80%")}, baseline=78.0).evaluate(
        story("implement"), Handoff("done")
    )
    assert out.verdict is Verdict.PASS


def test_handoff_gates() -> None:
    p = pipeline()
    assert p.evaluate(story("review"), Handoff("done")).verdict is Verdict.PASS
    back = p.evaluate(story("review"), Handoff("changes_requested", next_role="unit-tester"))
    assert back.bounce_to == "tests"
    default = p.evaluate(story("review"), Handoff("changes_requested"))
    assert default.bounce_to == "implement" and default.reason == "changes requested"
    assert p.evaluate(story("tests"), Handoff("blocked", summary="?")).verdict is Verdict.HOLD


def test_load_baseline(tmp_path: Path) -> None:
    assert gates.load_baseline(tmp_path) == {}
    (tmp_path / ".team").mkdir()
    (tmp_path / gates.BASELINE).write_text(json.dumps({"coverage": 70}))
    assert gates.load_baseline(tmp_path)["coverage"] == 70


BACKLOG = "story s1 is in the backlog; add it to a sprint"


def test_story_sprint_defaults_to_backlog() -> None:
    assert gates.StoryState("s1", "Add", "design").sprint is None


def test_backlog_refusal_for_story_bound_roles() -> None:
    assert gates.dispatch_refusal("architect", story(sprint=None)) == BACKLOG
    assert gates.dispatch_refusal("developer", story("implement", sprint=None)) == BACKLOG
    assert gates.dispatch_refusal("developer", story("implement", sprint=2)) is None


def test_backlog_refusal_ignored_for_ungated_and_storyless_roles() -> None:
    assert gates.dispatch_refusal("manager", story(sprint=None)) is None
    assert gates.dispatch_refusal("scribe", story(sprint=None)) is None
    assert gates.dispatch_refusal("architect", None) is None


def test_status_refusal_beats_backlog_refusal() -> None:
    done = story(sprint=None, status=StoryStatus.DONE)
    capped = story(sprint=None, status=StoryStatus.NEEDS_MANAGER)
    assert "is done" in gates.dispatch_refusal("architect", done)
    assert "round cap" in gates.dispatch_refusal("architect", capped)
    assert "blocked" in gates.dispatch_refusal(
        "architect", story(sprint=None, status=StoryStatus.BLOCKED)
    )


# ----- s13: presentation gates (E4, E6) -------------------------------------

REASON = "story s1 has no presentation: .team/run/presentation/s1/PRESENTATION.md is missing"


def unpresented(_story) -> str:
    return REASON


def presented(_story) -> None:
    return None


def test_checks_default_presentation_is_complete() -> None:
    assert checks().presentation(story("e2e")) is None


def test_presented_passes_when_nothing_is_missing() -> None:
    out = checks(presentation=presented).presented(story("e2e"))
    assert out.verdict is Verdict.PASS and out.reason == "presentation ready"


def test_presented_bounces_with_the_missing_reason() -> None:
    out = checks(presentation=unpresented).presented(story("e2e"))
    assert out.verdict is Verdict.BOUNCE and out.reason == REASON


def test_e2e_done_without_presentation_bounces_to_e2e() -> None:
    p = pipeline(presentation=unpresented)
    s = story("e2e")
    out = p.evaluate(s, Handoff("done"))
    assert (out.verdict, out.bounce_to, out.reason) == (Verdict.BOUNCE, "e2e", REASON)
    p.advance(s, out)
    assert (s.step, s.rounds) == ("e2e", 1)


def test_e2e_done_with_presentation_passes_to_acceptance() -> None:
    p = pipeline(presentation=presented)
    s = story("e2e")
    assert p.evaluate(s, Handoff("done")).verdict is Verdict.PASS
    p.advance(s, p.evaluate(s, Handoff("done")))
    assert s.step == "acceptance"


def test_e2e_done_without_acceptance_step_needs_no_presentation() -> None:
    steps = [x for x in STEPS if x != "acceptance"]
    p = pipeline(steps=steps, presentation=unpresented)
    assert p.evaluate(story("e2e"), Handoff("done")).verdict is Verdict.PASS


def test_e2e_changes_requested_still_bounces_to_the_named_role() -> None:
    p = pipeline(presentation=unpresented)
    out = p.evaluate(story("e2e"), Handoff("changes_requested", next_role="developer-cli"))
    assert out.verdict is Verdict.BOUNCE and out.bounce_to == "implement"


@pytest.mark.parametrize("status", ["blocked", "failed"])
def test_e2e_stopped_handoffs_hold(status: str) -> None:
    out = pipeline(presentation=unpresented).evaluate(story("e2e"), Handoff(status, summary="?"))
    assert out.verdict is Verdict.HOLD


def test_other_steps_do_not_consult_the_presentation() -> None:
    p = pipeline(presentation=unpresented)
    assert p.evaluate(story("review"), Handoff("done")).verdict is Verdict.PASS
    assert p.evaluate(story("acceptance"), Handoff("done")).verdict is Verdict.PASS


def test_return_verdict_value() -> None:
    assert Verdict.RETURN == "return"


def test_unpresented_returns_the_story_to_e2e() -> None:
    out = pipeline(presentation=unpresented).unpresented(story("acceptance"))
    assert out.verdict is Verdict.RETURN and out.bounce_to == "e2e"
    assert out.reason == f"{REASON}; run the integration-tester on it"


def test_unpresented_is_none_when_complete() -> None:
    assert pipeline(presentation=presented).unpresented(story("acceptance")) is None


def test_unpresented_is_none_without_an_e2e_step() -> None:
    steps = [x for x in STEPS if x != "e2e"]
    assert pipeline(steps=steps, presentation=unpresented).unpresented(story("acceptance")) is None


def test_return_moves_back_without_counting_a_round() -> None:
    s, p = story("acceptance", rounds=2), pipeline()
    p.advance(s, gates.Outcome(Verdict.RETURN, "no presentation", "e2e"))
    assert (s.step, s.rounds, s.status) == ("e2e", 2, StoryStatus.ACTIVE)


def test_return_at_the_cap_does_not_escalate() -> None:
    s, p = story("acceptance", rounds=2), pipeline()
    p.advance(s, gates.Outcome(Verdict.RETURN, "x", "e2e"))
    assert s.status is StoryStatus.ACTIVE

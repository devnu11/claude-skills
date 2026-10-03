"""Story pipeline state machine and gates."""

import json
from pathlib import Path

import pytest
from agile_team import gates
from agile_team.config import PIPELINE_STEPS
from agile_team.roles import Handoff

from .conftest import FakeRunner

STEPS = list(PIPELINE_STEPS)


def story(step: str = "design", **kw) -> gates.StoryState:
    return gates.StoryState("s1", "Add todo", step, **kw)


def checks(results=None, baseline=None) -> gates.Checks:
    return gates.Checks({"test": "T", "coverage": "C"}, 95.0, FakeRunner(results), baseline)


def test_role_fits_step() -> None:
    assert gates.role_fits_step("developer-cli", "implement")
    assert not gates.role_fits_step("developer", "tests")
    assert gates.step_for_role("developer-api", STEPS) == "implement"
    assert gates.step_for_role(None, STEPS) is None
    assert gates.step_for_role("manager", STEPS) is None


@pytest.mark.parametrize(
    ("st", "role", "blocked", "needle"),
    [
        (None, "developer", set(), "only runs on a story"),
        (story(done=True), "architect", set(), "is done"),
        (story(blocked=True), "architect", set(), "blocked"),
        (story(), "architect", {"s1"}, "blocked"),
        (story(needs_manager=True), "architect", set(), "round cap"),
        (story("tests"), "developer", set(), "needs unit-tester"),
    ],
)
def test_dispatch_refusals(st, role, blocked, needle) -> None:
    assert needle in gates.dispatch_refusal(st, role, blocked)


def test_dispatch_allowed() -> None:
    assert gates.dispatch_refusal(None, "architect", set()) is None
    assert gates.dispatch_refusal(story(needs_manager=True), "manager", set()) is None
    assert gates.dispatch_refusal(story("implement"), "developer-cli", set()) is None


def test_advance_through_pipeline_to_done() -> None:
    s = story()
    for _ in STEPS:
        gates.advance(s, gates.Outcome(True), STEPS, 3)
    assert s.done and s.step == "acceptance"


def test_bounce_counts_rounds_and_caps() -> None:
    s = story("review")
    for i in range(3):
        gates.advance(s, gates.Outcome(False, bounce_to="implement"), STEPS, 3)
        assert s.rounds == i + 1
    assert s.needs_manager and s.step == "implement"


def test_block_does_not_count() -> None:
    s = story("review")
    gates.advance(s, gates.Outcome(False, counts=False), STEPS, 3)
    assert s.rounds == 0 and s.step == "review"


@pytest.mark.parametrize(
    ("ruling", "step", "blocked"),
    [
        ("rescope", "design", False),
        ("revise_design", "design", False),
        ("upgrade_model", "implement", False),
        ("escalate", "implement", True),
    ],
)
def test_rulings(ruling, step, blocked) -> None:
    s = story("implement", rounds=3, needs_manager=True)
    gates.apply_ruling(s, ruling, STEPS)
    assert (s.step, s.blocked, s.rounds, s.needs_manager) == (step, blocked, 0, False)


def test_revise_design_without_design_step() -> None:
    s = story("implement")
    gates.apply_ruling(s, "revise_design", ["tests", "implement"])
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
    assert gates.evaluate("tests", Handoff("done"), checks({"T": (1, "")}), STEPS).passed
    out = gates.evaluate("tests", Handoff("done"), checks({"T": (0, "")}), STEPS)
    assert not out.passed and out.bounce_to == "tests" and "failing test" in out.reason


def test_green_gate() -> None:
    ok = checks({"T": (0, ""), "C": (0, "TOTAL 96%")})
    assert gates.evaluate("implement", Handoff("done"), ok, STEPS).passed
    red = gates.evaluate("implement", Handoff("done"), checks({"T": (1, "boom")}), STEPS)
    assert not red.passed and "boom" in red.reason and red.bounce_to == "implement"
    low = gates.evaluate("implement", Handoff("done"), checks({"C": (0, "TOTAL 80%")}), STEPS)
    assert "below 95.0%" in low.reason
    none = gates.evaluate("implement", Handoff("done"), checks({"C": (0, "n/a")}), STEPS)
    assert "could not read" in none.reason


def test_baseline_lowers_requirement() -> None:
    c = checks({"C": (0, "TOTAL 80%")}, baseline=78.0)
    assert c.required_coverage() == 78.0
    assert gates.evaluate("implement", Handoff("done"), c, STEPS).passed


def test_handoff_gates() -> None:
    c = checks()
    assert gates.evaluate("review", Handoff("done"), c, STEPS).passed
    back = gates.evaluate("review", Handoff("changes_requested", next_role="unit-tester"), c, STEPS)
    assert back.bounce_to == "tests"
    default = gates.evaluate("review", Handoff("changes_requested"), c, STEPS)
    assert default.bounce_to == "implement" and default.reason == "changes requested"
    blocked = gates.evaluate("tests", Handoff("blocked", summary="?"), c, STEPS)
    assert not blocked.counts


def test_load_baseline(tmp_path: Path) -> None:
    assert gates.load_baseline(tmp_path) == {}
    (tmp_path / ".team").mkdir()
    (tmp_path / gates.BASELINE).write_text(json.dumps({"coverage": 70}))
    assert gates.load_baseline(tmp_path)["coverage"] == 70

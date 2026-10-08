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


def checks(results=None, baseline=None) -> gates.Checks:
    return gates.Checks({"test": "T", "coverage": "C"}, 95.0, FakeRunner(results), baseline)


def pipeline(results=None, baseline=None, steps=STEPS) -> gates.Pipeline:
    return gates.Pipeline(list(steps), 3, checks(results, baseline))


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
    passed = pipeline({"T": (1, "")}).evaluate("tests", Handoff("done"))
    assert passed.verdict is Verdict.PASS
    out = pipeline({"T": (0, "")}).evaluate("tests", Handoff("done"))
    assert out.verdict is Verdict.BOUNCE and out.bounce_to == "tests"
    assert "failing test" in out.reason


def test_green_gate() -> None:
    done = Handoff("done")
    ok = pipeline({"T": (0, ""), "C": (0, "TOTAL 96%")}).evaluate("implement", done)
    assert ok.verdict is Verdict.PASS
    red = pipeline({"T": (1, "boom")}).evaluate("implement", done)
    assert red.verdict is Verdict.BOUNCE and "boom" in red.reason
    assert red.bounce_to == "implement"
    low = pipeline({"C": (0, "TOTAL 80%")}).evaluate("implement", done)
    assert "below 95.0%" in low.reason
    none = pipeline({"C": (0, "n/a")}).evaluate("implement", done)
    assert "could not read" in none.reason


def test_baseline_lowers_requirement() -> None:
    assert checks(baseline=78.0).required_coverage() == 78.0
    out = pipeline({"C": (0, "TOTAL 80%")}, baseline=78.0).evaluate("implement", Handoff("done"))
    assert out.verdict is Verdict.PASS


def test_handoff_gates() -> None:
    p = pipeline()
    assert p.evaluate("review", Handoff("done")).verdict is Verdict.PASS
    back = p.evaluate("review", Handoff("changes_requested", next_role="unit-tester"))
    assert back.bounce_to == "tests"
    default = p.evaluate("review", Handoff("changes_requested"))
    assert default.bounce_to == "implement" and default.reason == "changes requested"
    assert p.evaluate("tests", Handoff("blocked", summary="?")).verdict is Verdict.HOLD


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

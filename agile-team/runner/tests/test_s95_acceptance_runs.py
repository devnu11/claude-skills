"""s95: the acceptance verdict of one Proxy step per environment (AE6-AE9, AE12)."""

import json
from dataclasses import asdict

from agile_team import acceptance, gates, state
from agile_team.acceptance import Mark, Tried
from agile_team.config import PIPELINE_STEPS
from agile_team.gates import Verdict
from agile_team.roles import Handoff

from .conftest import FakeRunner

NAMES = ["cli", "dashboard"]


def pipe(report: str | None = None, names: list[str] | None = None) -> gates.Pipeline:
    checks = gates.Checks({"test": "T", "coverage": "C"}, 95.0, FakeRunner(None), None)
    checks.environments = lambda _story: NAMES if names is None else names
    sections = "".join(f"## Environment: {n}\n" for n in NAMES)
    checks.read = lambda _path: sections if report is None else report
    return gates.Pipeline(list(PIPELINE_STEPS), 3, checks)


def at_acceptance(**kw) -> gates.StoryState:
    return gates.StoryState("s1", "T", "acceptance", sprint=1, **kw)


def fail(*ids: str, role: str | None = "developer") -> Handoff:
    return Handoff("changes_requested", "broken", next_role=role, failed_acs=list(ids))


def test_first_pass_is_next_and_recorded() -> None:
    story = at_acceptance()
    out = pipe().evaluate(story, Handoff("done"))
    assert out.verdict is Verdict.NEXT
    assert out.tried == Tried("cli", Mark.PASS)
    assert story.tried == [Tried("cli", Mark.PASS)]
    assert "dashboard" in out.reason


def test_next_moves_nothing_and_counts_no_round() -> None:
    p, story = pipe(), at_acceptance()
    p.advance(story, p.evaluate(story, Handoff("done")))
    assert (story.step, story.rounds) == ("acceptance", 0)


def test_both_pass_forwards() -> None:
    p, story = pipe(), at_acceptance()
    p.evaluate(story, Handoff("done"))
    out = p.evaluate(story, Handoff("done"))
    assert out.verdict is Verdict.PASS
    assert out.reason == "acceptance passed in every environment: cli, dashboard"
    p.advance(story, out)
    assert story.step == "land" and story.status is gates.StoryStatus.ACTIVE


def test_a_failure_in_the_first_still_runs_the_second_and_one_bounce_lists_both() -> None:
    p, story = pipe(), at_acceptance()
    first = p.evaluate(story, fail("AC1", role="architect"))
    assert first.verdict is Verdict.NEXT
    out = p.evaluate(story, fail("AC4", role="developer"))
    assert out.verdict is Verdict.BOUNCE
    assert "- cli: AC1: broken" in out.reason and "- dashboard: AC4: broken" in out.reason
    assert out.bounce_to == "design"
    p.advance(story, out)
    assert (story.step, story.rounds) == ("design", 1)


def test_only_the_second_failing_names_only_it() -> None:
    p, story = pipe(), at_acceptance()
    p.evaluate(story, Handoff("done"))
    out = p.evaluate(story, fail("AC4"))
    assert out.verdict is Verdict.BOUNCE
    assert out.reason.startswith("acceptance failed in 1 of 2 environments")
    assert "- cli" not in out.reason
    assert out.bounce_to == "implement"


def test_bounce_without_a_role_goes_to_implement() -> None:
    p, story = pipe(), at_acceptance()
    p.evaluate(story, Handoff("done"))
    assert p.evaluate(story, fail("AC4", role=None)).bounce_to == "implement"


def test_rework_reentry_clears_the_round() -> None:
    p, story = pipe(), at_acceptance()
    p.evaluate(story, Handoff("done"))
    story.step = "e2e"
    p.advance(story, gates.Outcome(Verdict.PASS))
    assert story.step == "acceptance" and story.tried == []
    assert acceptance.Round(tuple(NAMES), tuple(story.tried)).due() == "cli"


def test_missing_section_bounces_to_acceptance_and_records_nothing() -> None:
    p, story = pipe(report="## Environment: dashboard\n"), at_acceptance()
    out = p.evaluate(story, Handoff("done"))
    assert out.verdict is Verdict.BOUNCE and out.bounce_to == "acceptance"
    assert "## Environment: cli" in out.reason
    assert story.tried == []


def test_blocked_holds_and_records_nothing() -> None:
    story = at_acceptance()
    out = pipe().evaluate(story, Handoff("blocked", "stuck"))
    assert out.verdict is Verdict.HOLD and story.tried == []


def test_a_story_naming_no_environments_keeps_the_old_verdict() -> None:
    out = pipe(names=[]).evaluate(at_acceptance(), Handoff("done"))
    assert out.verdict is Verdict.PASS and out.tried is None


def test_tried_survives_a_state_round_trip() -> None:
    story = at_acceptance(tried=[Tried("cli", Mark.FAIL, ("AC1",), "s", "developer")])
    data = json.loads(json.dumps(asdict(story)))
    assert state._story(data).tried == story.tried


def test_old_state_loads_with_no_tried() -> None:
    data = {"id": "s1", "title": "T", "step": "acceptance"}
    assert state._story(data).tried == []

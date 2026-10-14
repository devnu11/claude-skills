"""s95 runner checklist: one Proxy step per environment through run_role (AE5, AE8-AE12)."""

import asyncio
from functools import partial

import pytest
from agile_team import gates, sandbox, story_spec, system
from agile_team.config import Environment
from agile_team.dispatch import StepRequest
from agile_team.gates import PreviousStep, StoryStatus, Verdict
from agile_team.git_ops import Git
from agile_team.router import Work, standard_brief

from .conftest import FakeQuery, handoff, present, write_story
from .fake_system import FakeSystem

REPORT = ".team/acceptance/s1.md"
BOTH = "## Environment: cli\nok\n## Environment: api\nok\n"


@pytest.fixture(autouse=True)
def tracked(configured, fake: FakeSystem) -> None:
    fake.track()


def build(make_runtime, text: str = "", report: str | None = BOTH):
    """A runtime with a ``cli`` and a ``api`` (package) AC, at acceptance, fully presented."""
    orders: list[sandbox.Order] = []

    def fake_prepare(config, order):
        orders.append(order)
        return sandbox.Preparer().prepare(config, order)

    def write_report() -> None:
        if report is not None:
            system.make_dirs(rt.config.repo / ".team/acceptance")
            system.write_text(rt.config.repo / REPORT, report)

    rt = make_runtime(FakeQuery(text, action=write_report), prepare_fn=fake_prepare)
    rt.config.environments = [*rt.config.environments, Environment("api", "package")]
    rt.pipeline.checks.environments = partial(story_spec.environment_names, rt.config)
    write_story(rt.config, "s1", "cli", "api", "cli")
    rt.state.stories["s1"] = gates.StoryState("s1", "T", "acceptance", sprint=1)
    present(rt.config, environment="cli")
    present(rt.config, environment="api")
    return rt, orders


def step(rt) -> dict:
    return asyncio.run(rt.run_role(StepRequest("customer-proxy", "go", "s1")))


def gate_events(rt) -> list:
    return [e for e in rt.events.events() if e.kind == "gate"]


def criteria(prompt: str) -> str:
    """The prompt's '## Criteria for this step' section, up to the next '## ' heading."""
    rest = prompt.split("## Criteria for this step", 1)[1]
    return rest.split("\n## ", 1)[0]


def test_each_step_prepares_only_its_environment_and_lists_only_its_acs(make_runtime) -> None:
    rt, orders = build(make_runtime)
    story = rt.state.stories["s1"]
    first = step(rt)
    assert [o.environment.name for o in orders] == ["cli"]
    assert orders[0].presentation == rt.config.run_dir / "presentation/s1/cli"
    prompt = rt.query_fn.calls[0]["prompt"]
    assert "acceptance environment cli" in prompt and "- AC1:" in prompt and "- AC3:" in prompt
    assert "- AC2:" not in criteria(prompt)
    assert first["gate"]["verdict"] == "next" and first["gate"]["now_at"] == "acceptance"
    assert (story.step, story.rounds) == ("acceptance", 0)
    step(rt)
    assert [o.environment.name for o in orders] == ["cli", "api"]
    assert orders[1].presentation == rt.config.run_dir / "presentation/s1/api"
    second = rt.query_fn.calls[1]["prompt"]
    assert "acceptance environment api" in second and "- AC2:" in second
    assert "- AC1:" not in criteria(second)
    assert story.status is StoryStatus.DONE


def test_a_requirement_covering_the_other_environments_ac_is_not_in_the_criteria(
    make_runtime,
) -> None:
    rt, _ = build(make_runtime)
    system.make_dirs(rt.config.requirements_dir)
    body = "---\nid: REQ-001\ntitle: Api thing\nstatus: active\ncovers: ['s1/AC2']\n---\n\nWords.\n"
    system.write_text(rt.config.requirements_dir / "REQ-001.md", body)
    git = Git(rt.config.repo)
    git.run("add", "docs")
    git.run("commit", "-q", "-m", "req")
    step(rt)
    prompt = rt.query_fn.calls[0]["prompt"]
    assert "- AC2: REQ-001 (Api thing)" in prompt.split("## Requirements", 1)[1]
    assert "- AC2:" not in criteria(prompt)


def test_a_next_verdict_hands_nothing_over(make_runtime) -> None:
    rt, _ = build(make_runtime)
    step(rt)
    assert [e for e in rt.events.events() if e.kind == "handover"] == []
    assert rt.state.stories["s1"].previous.verdict == "next"


def test_the_gate_event_carries_environment_mark_and_failed_acs(make_runtime) -> None:
    text = handoff("changes_requested", failed_acs=["AC1"], summary="broken", next_role="developer")
    rt, _ = build(make_runtime, text)
    step(rt)
    [event] = gate_events(rt)
    assert event.data["verdict"] == "next"
    assert event.data["environment"] == "cli"
    assert event.data["mark"] == "fail"
    assert event.data["failed_acs"] == ["AC1"]


def test_a_passing_step_marks_pass_with_no_failed_acs(make_runtime) -> None:
    rt, _ = build(make_runtime)
    step(rt)
    [event] = gate_events(rt)
    assert (event.data["mark"], event.data["failed_acs"]) == ("pass", [])


def test_a_missing_section_bounces_to_acceptance_and_runs_the_same_environment(
    make_runtime,
) -> None:
    rt, orders = build(make_runtime, report="## Environment: api\nonly\n")
    story = rt.state.stories["s1"]
    report = step(rt)
    assert (
        report["gate"]["verdict"] == "bounce" and "## Environment: cli" in report["gate"]["reason"]
    )
    assert (story.step, story.rounds, story.tried) == ("acceptance", 1, [])
    step(rt)
    assert [o.environment.name for o in orders] == ["cli", "cli"]


def test_a_blocked_step_holds_and_the_same_environment_runs_again(make_runtime) -> None:
    rt, orders = build(make_runtime, handoff("blocked", summary="stuck"))
    story = rt.state.stories["s1"]
    step(rt)
    assert story.tried == [] and story.status is not StoryStatus.DONE
    rt.query_fn.text = handoff()
    assert story.hold
    story.hold = None
    step(rt)
    assert [o.environment.name for o in orders] == ["cli", "cli"]


def test_a_rework_runs_both_environments_again(make_runtime) -> None:
    rt, orders = build(make_runtime, handoff("changes_requested", summary="bad"))
    story = rt.state.stories["s1"]
    step(rt)
    step(rt)
    assert story.step == "implement" and story.rounds == 1
    story.step = "e2e"
    rt.pipeline.advance(story, gates.Outcome(Verdict.PASS))
    assert story.step == "acceptance" and story.tried == []
    rt.query_fn.text = handoff()
    step(rt)
    step(rt)
    assert [o.environment.name for o in orders] == ["cli", "api", "cli", "api"]
    assert story.status is StoryStatus.DONE


def test_the_brief_after_a_next_verdict_has_no_previous_step_line(make_runtime) -> None:
    rt, _ = build(make_runtime)
    story = rt.state.stories["s1"]
    story.previous = PreviousStep("customer-proxy", "done", "fine", verdict="next")
    assert "Previous step" not in standard_brief(rt.config, Work("customer-proxy", story, ""))
    story.previous = PreviousStep("customer-proxy", "done", "fine", verdict="pass")
    assert "Previous step" in standard_brief(rt.config, Work("customer-proxy", story, ""))


def test_the_tester_prompt_names_every_presentation_to_build(make_runtime) -> None:
    rt, _ = build(make_runtime)
    rt.state.stories["s1"].step = "e2e"
    asyncio.run(rt.run_role(StepRequest("integration-tester", "go", "s1")))
    prompt = rt.query_fn.calls[0]["prompt"]
    assert "## Presentations to build" in prompt
    assert "- cli (package): .team/run/presentation/s1/cli/ (AC1, AC3)" in prompt
    assert "- api (package): .team/run/presentation/s1/api/ (AC2)" in prompt

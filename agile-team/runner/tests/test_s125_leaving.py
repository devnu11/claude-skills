"""s125: the git diff pins (P10) and serving (P16). The pending registry is gone (s159 G1)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from agile_team import gates, stages
from agile_team.boundary import StepKind
from agile_team.dispatch import Plan, Runtime, StepRequest
from agile_team.git_ops import Git
from agile_team.stop_checks import StopChecks

from .fake_system import FAKE_REPO, FakeSystem
from .pipeline_helpers import add_story


@pytest.fixture(autouse=True)
def tracked(configured: Path, fake: FakeSystem) -> None:
    fake.track()


def test_the_diff_pins_its_prefixes_and_quoting_whatever_the_humans_git_config(
    fake: FakeSystem,
) -> None:
    Git(FAKE_REPO).diff_lines("base1")
    (argv,) = [c.argv for c in fake.commands]
    assert argv[1:3] == ("-c", "core.quotePath=false")
    assert "--src-prefix=a/" in argv and "--dst-prefix=b/" in argv
    assert "-U0" in argv and argv[-1] == "base1"


# ---- P16: serving ---------------------------------------------------------------------------


@dataclass
class Head:
    """A git that knows only HEAD."""

    sha: str = "head1"

    def head(self) -> str:
        return self.sha

    def content_digest(self, base: str) -> str:
        return "d"

    def changed_paths(self) -> list[str]:
        return []


def test_a_story_plan_starts_from_head(make_runtime: Callable[..., Runtime]) -> None:
    rt = make_runtime()
    add_story(rt, "s1", "tests")
    rt.git = Head()
    plan = rt.plan(StepRequest("unit-tester", "go", "s1"))
    assert plan.base == "head1"
    plan.stop()


def test_a_plan_with_no_story_has_no_base(make_runtime: Callable[..., Runtime]) -> None:
    rt = make_runtime()
    rt.git = Head()
    plan = rt.plan(StepRequest("manager", "review", None))
    assert plan.base == ""
    plan.stop()


def story_plan(rt: Runtime, step: str, base: str) -> Plan:
    story = add_story(rt, "s1", step)
    role = rt.resolve("developer")
    plan = Plan(role, rt.scope_for(role), story, kind=StepKind.ROLE)
    plan.base = base
    return plan


def test_gating_serves_the_plans_story_and_base(make_runtime: Callable[..., Runtime]) -> None:
    rt = make_runtime()
    plan = story_plan(rt, "implement", "base1")
    assert rt._gating(plan).checks.serving == gates.Serving("s1", "base1")


def test_gating_with_a_stop_hook_still_serves_the_story(
    make_runtime: Callable[..., Runtime],
) -> None:
    rt = make_runtime()
    plan = story_plan(rt, "implement", "base1")
    plan.stop_hook = StopChecks(rt, plan)
    pipeline = rt._gating(plan)
    assert pipeline.checks.serving == gates.Serving("s1", "base1")
    assert pipeline.checks.reuse == plan.stop_hook.reused


def test_the_runtime_serves_nothing_without_a_story(make_runtime: Callable[..., Runtime]) -> None:
    rt = make_runtime()
    role = rt.resolve("manager")
    plan = Plan(role, rt.scope_for(role), None)
    assert rt.served(plan).checks.serving == gates.Serving()


def test_the_stop_hooks_gates_serve_the_plans_story_and_base(
    make_runtime: Callable[..., Runtime],
) -> None:
    rt = make_runtime()
    plan = story_plan(rt, "implement", "base1")
    hook = StopChecks(rt, plan)
    hooked = hook._hooked(stages.Name.STOP_SUITE)
    assert hooked.checks.serving == gates.Serving("s1", "base1")


def test_the_plain_runtime_pipeline_is_not_changed_by_serving(
    make_runtime: Callable[..., Runtime],
) -> None:
    rt = make_runtime()
    rt.served(story_plan(rt, "implement", "base1"))
    assert rt.pipeline.checks.serving == gates.Serving()

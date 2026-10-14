"""s125 P16: the Stop hook's red check sees the agent's uncommitted test file as touched."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from agile_team import pending_tests, test_reports
from agile_team.boundary import StepKind
from agile_team.dispatch import Plan, Runtime
from agile_team.git_ops import Git
from agile_team.pending_tests import Registry
from agile_team.roles import Handoff
from agile_team.stop_checks import StopChecks

from .fake_system import FAKE_REPO, Done, FakeSystem
from .pipeline_helpers import add_story
from .s125_helpers import FOLDER, OPTIONS, ROOT, Writer
from .test_s125_pending_tests import new_file

UNCOMMITTED = f"{ROOT}/tests/test_new.py"


@pytest.fixture(autouse=True)
def tracked(configured: Path, fake: FakeSystem) -> None:
    fake.track()
    fake.reply(("git", "diff"), Done(0, ""))
    fake.reply(("git", "ls-files"), Done(0, UNCOMMITTED + "\0"))


def hook(rt: Runtime) -> StopChecks:
    """A Stop hook on a tests-step plan whose checks report, run on a scripted report."""
    story = add_story(rt, "s1", "tests")
    role = rt.resolve("unit-tester")
    plan = Plan(role, rt.scope_for(role), story, kind=StepKind.ROLE)
    plan.base = "base1"
    reporting = test_reports.Reporting(
        OPTIONS, FOLDER, Registry, test_reports.changed_for(Git(FAKE_REPO))
    )
    run_in = f"pytest -q {{report:{ROOT}}}"
    commands = {"test": run_in, "coverage": run_in}
    checks = replace(
        rt.pipeline.checks,
        commands=commands,
        run=Writer([new_file()], code=1),
        reporting=reporting,
    )
    rt.pipeline = replace(rt.pipeline, checks=checks)
    return StopChecks(rt, plan)


def test_the_red_check_counts_an_uncommitted_new_test_file_as_touched(
    make_runtime: Callable[..., Runtime],
) -> None:
    rt = make_runtime()
    refusal = hook(rt)._red(Handoff("done"))
    assert refusal is None


def test_the_stop_hooks_pass_writes_no_registry_and_makes_no_commit(
    make_runtime: Callable[..., Runtime], fake: FakeSystem
) -> None:
    rt = make_runtime()
    hook(rt)._red(Handoff("done"))
    assert pending_tests.read(rt.config.repo) == Registry()
    assert not [c for c in fake.tree.commits if "pending tests" in c.subject()]

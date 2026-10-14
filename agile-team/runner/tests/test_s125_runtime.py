"""s125: the runtime applies a pending change in its own runner commit, before the next step."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from agile_team import gates, pending_tests
from agile_team.dispatch import Runtime
from agile_team.gates import Outcome, Verdict
from agile_team.pending_tests import PendingSet, Registry
from agile_team.roles import Handoff

from .conftest import FakeRunner
from .fake_system import FakeSystem
from .s125_helpers import NEW_FAIL

SET = PendingSet("s1", (NEW_FAIL,))


@pytest.fixture(autouse=True)
def tracked(configured: Path, fake: FakeSystem) -> None:
    fake.track()


def subjects(fake: FakeSystem) -> list[str]:
    return [c.subject() for c in fake.tree.commits]


def gate_with(
    rt: Runtime, step: str, outcome: Outcome, seen: list[list[str]], fake: FakeSystem
) -> None:
    """Run ``Runtime.gate`` with a stubbed evaluation; record the commits seen at advance."""
    rt.verify_checkout = lambda: None
    rt._evaluate = lambda plan, handoff: outcome

    def advance(plan: object, got: Outcome) -> dict:
        seen.append(subjects(fake))
        return {}

    rt._advance_and_log = advance
    plan = SimpleNamespace(story=gates.StoryState("s1", "t", step, sprint=1))
    rt.gate(plan, Handoff("done"))


def test_a_passing_tests_gate_commits_the_registry_before_the_story_advances(
    make_runtime: Callable[..., Runtime], configured: Path, fake: FakeSystem
) -> None:
    rt, seen, before = make_runtime(runner=FakeRunner()), [], len(fake.tree.commits)
    gate_with(rt, "tests", Outcome(Verdict.PASS, pending=SET), seen, fake)
    assert pending_tests.read(configured) == Registry({"s1": (NEW_FAIL,)})
    assert len(fake.tree.commits) == before + 1
    last = fake.tree.commits[-1]
    assert last.subject() == "chore(s1): pending tests (tests step)"
    assert last.paths() == {pending_tests.REGISTRY}
    assert seen[0][-1] == "chore(s1): pending tests (tests step)"  # committed before advancing


def test_the_implement_gate_commit_names_the_gate(
    make_runtime: Callable[..., Runtime], configured: Path, fake: FakeSystem
) -> None:
    rt = make_runtime(runner=FakeRunner())
    pending_tests.write(configured, Registry({"s1": (NEW_FAIL,)}))
    gate_with(rt, "implement", Outcome(Verdict.PASS, pending=PendingSet("s1", ())), [], fake)
    assert subjects(fake)[-1] == "chore(s1): pending tests (implement gate)"
    assert pending_tests.read(configured) == Registry()


def test_a_gate_that_does_not_pass_commits_nothing(
    make_runtime: Callable[..., Runtime], configured: Path, fake: FakeSystem
) -> None:
    rt, before = make_runtime(runner=FakeRunner()), len(fake.tree.commits)
    gate_with(rt, "tests", Outcome(Verdict.BOUNCE, "no", pending=SET), [], fake)
    assert len(fake.tree.commits) == before
    assert pending_tests.read(configured) == Registry()


def test_an_unchanged_registry_makes_no_commit(
    make_runtime: Callable[..., Runtime], configured: Path, fake: FakeSystem
) -> None:
    rt = make_runtime(runner=FakeRunner())
    pending_tests.write(configured, Registry({"s1": (NEW_FAIL,)}))
    before = len(fake.tree.commits)
    assert rt.set_pending(SET) is None
    assert len(fake.tree.commits) == before


def test_set_pending_returns_the_sha_and_names_the_story(
    make_runtime: Callable[..., Runtime], configured: Path, fake: FakeSystem
) -> None:
    rt = make_runtime(runner=FakeRunner())
    sha = rt.set_pending(SET)
    assert sha and fake.tree.commits[-1].subject().startswith("chore(s1): pending tests")


def test_a_pass_without_a_pending_change_commits_nothing(
    make_runtime: Callable[..., Runtime], configured: Path, fake: FakeSystem
) -> None:
    rt, before = make_runtime(runner=FakeRunner()), len(fake.tree.commits)
    gate_with(rt, "tests", Outcome(Verdict.PASS), [], fake)
    assert len(fake.tree.commits) == before


def test_serving_defaults_to_no_story_and_no_base() -> None:
    assert gates.Serving() == gates.Serving("", "")

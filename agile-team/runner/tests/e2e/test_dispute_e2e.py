"""s11 end to end: the dispute route through the real router, real git and real rulings."""

from __future__ import annotations

import asyncio
from typing import Any

from agile_team.dispatch import StepRequest, shell_runner
from agile_team.events import EventKind
from agile_team.gates import DisputeStage, StoryStatus

from ..conftest import git, handoff
from ..pipeline_helpers import Script, add_story, drive, step_roles

TEST_FILE = "tests/test_x.py"
TEST_ID = f"{TEST_FILE}::test_a"
DISPUTE = {"test": TEST_ID, "rule": "W6", "reason": "rule says X, test expects Y"}
RAISE = handoff("changes_requested", summary="test contradicts design", dispute=DISPUTE)
TO_ARCHITECT = handoff("changes_requested", summary="the test is right", next_role="architect")


class GitRunner:
    """Gate commands: git runs for real; the test run is red at ``tests`` only."""

    def __init__(self, repo):
        self.repo, self.rt, self.real = repo, None, shell_runner(repo)
        self.test_runs = 0

    def __call__(self, command: str) -> tuple[int, str]:
        if command.startswith("git "):
            return self.real(command)
        if command == "pytest --cov":
            return 0, "TOTAL   10   0   100%"
        self.test_runs += 1
        return (1, "red") if self.rt.state.stories["s1"].step == "tests" else (0, "ok")


def fix_test(text: str):
    """A unit-tester action that rewrites the disputed test file."""

    async def action(rt) -> None:
        (rt.config.repo / TEST_FILE).write_text(text)

    return action


def build_rt(make_runtime, configured, replies, steps):
    (configured / "tests").mkdir(exist_ok=True)
    (configured / TEST_FILE).write_text("def test_a(): assert 1 == 2\n")
    git(configured, "add", "-A")
    git(configured, "commit", "-q", "-m", "tests")
    script = Script(replies)
    runner = GitRunner(configured)
    rt = make_runtime(script, runner=runner)
    script.rt = runner.rt = rt
    rt.pipeline.steps = list(steps)
    return script, rt, runner


def kinds(rt, kind: EventKind) -> list[Any]:
    return [e for e in rt.events.events() if e.kind == kind]


def test_upheld_dispute_goes_to_tests_and_back_free(make_runtime, configured) -> None:
    """AC1-AC3: implement -> tests -> implement, no round, one test-dispute event."""
    replies = {"developer": [RAISE], "unit-tester": [fix_test("def test_a(): assert 1 == 1\n")]}
    script, rt, _ = build_rt(make_runtime, configured, replies, ["tests", "implement"])
    add_story(rt, step="implement")
    drive(rt)
    story = rt.state.stories["s1"]
    assert step_roles(rt) == ["developer", "unit-tester", "developer", "scribe"]
    assert (story.status, story.rounds, story.disputes) == (StoryStatus.DONE, 0, 1)
    assert story.dispute is None
    (event,) = kinds(rt, EventKind.TEST_DISPUTE)
    assert event.data["now_at"] == "tests" and event.data["rounds"] == 0
    assert (event.data["test"], event.data["rule"], event.data["disputes"]) == (TEST_ID, "W6", 1)
    assert [e.data["step"] for e in kinds(rt, EventKind.GATE)][:1] == ["tests"]
    prompt = script.prompts["unit-tester"][0]
    assert f"Test dispute (raised): {TEST_ID} contradicts W6: rule says X, test expects Y" in prompt
    assert "Test dispute" not in script.prompts["developer"][1]
    assert git(configured, "log", "-1", "--format=%s", "--", TEST_FILE).strip()


def test_malformed_dispute_is_refused_and_costs_a_round(make_runtime, configured) -> None:
    """AC1: no rule means a bad handoff; the story stays at implement."""
    bad = handoff("changes_requested", summary="s", dispute={"test": TEST_ID})
    _, rt, _ = build_rt(make_runtime, configured, {"developer": [bad]}, ["tests", "implement"])
    add_story(rt, step="implement")
    report = asyncio.run(rt.run_role(StepRequest("developer", "go", "s1")))
    story = rt.state.stories["s1"]
    assert "dispute needs a test id and a design rule" in str(report)
    assert (story.step, story.rounds, story.disputes) == ("implement", 1, 0)
    assert not kinds(rt, EventKind.TEST_DISPUTE)


def test_unchanged_test_file_bounces_with_the_reason(make_runtime, configured) -> None:
    """AC3: a tester that touches nothing fails the gate (real git diff exit 0)."""
    replies = {"developer": [RAISE]}
    _, rt, _ = build_rt(make_runtime, configured, replies, ["tests", "implement"])
    add_story(rt, step="implement")
    asyncio.run(rt.run_role(StepRequest("developer", "go", "s1")))
    report = asyncio.run(rt.run_role(StepRequest("unit-tester", "go", "s1")))
    story = rt.state.stories["s1"]
    assert f"the disputed test file {TEST_FILE} has not changed" in str(report)
    assert (story.step, story.rounds) == ("tests", 1)
    assert story.dispute is not None and story.dispute.stage is DisputeStage.RAISED


def test_confirmed_dispute_goes_through_the_architect_and_costs_a_round(
    make_runtime, configured
) -> None:
    """AC2/AC3: tester confirms -> design (+1 round) -> tests passes unchanged -> implement."""
    replies = {"unit-tester": [TO_ARCHITECT, handoff()], "developer": [RAISE]}
    script, rt, _ = build_rt(make_runtime, configured, replies, ["design", "tests", "implement"])
    add_story(rt, step="implement")
    drive(rt)
    story = rt.state.stories["s1"]
    assert step_roles(rt)[:5] == [
        "developer",
        "unit-tester",
        "architect",
        "unit-tester",
        "developer",
    ]
    assert (story.status, story.rounds) == (StoryStatus.DONE, 1)
    assert story.dispute is None
    assert f"Test dispute (confirmed): {TEST_ID}" in script.prompts["architect"][0]
    assert f"Test dispute (confirmed): {TEST_ID}" in script.prompts["unit-tester"][1]


def test_free_disputes_are_capped_at_round_cap(make_runtime, configured) -> None:
    """AC2: the first round_cap disputes are free; the next counts a round."""
    _, rt, _ = build_rt(make_runtime, configured, {}, ["tests", "implement"])
    cap = rt.pipeline.cap
    add_story(rt, step="implement")
    rounds = []
    for n in range(cap + 1):
        asyncio.run(_dispute_cycle(rt, n))
        rounds.append(rt.state.stories["s1"].rounds)
    assert rounds == [0] * cap + [1]
    assert len(kinds(rt, EventKind.TEST_DISPUTE)) == cap + 1


async def _dispute_cycle(rt, n: int) -> None:
    rt.query_fn.replies["developer"] = [RAISE]
    rt.query_fn.replies["unit-tester"] = [fix_test(f"def test_a(): assert {n} == {n}\n")]
    await rt.run_role(StepRequest("developer", "go", "s1"))
    await rt.run_role(StepRequest("unit-tester", "go", "s1"))


def test_dispute_at_cap_stops_the_story_for_the_manager(make_runtime, configured) -> None:
    """AC2: a dispute that counts the last round caps the story."""
    _, rt, _ = build_rt(make_runtime, configured, {"developer": [RAISE]}, ["tests", "implement"])
    story = add_story(rt, step="implement", disputes=rt.pipeline.cap, rounds=rt.pipeline.cap - 1)
    asyncio.run(rt.run_role(StepRequest("developer", "go", "s1")))
    assert story.status is StoryStatus.NEEDS_MANAGER and story.step == "tests"


# ----- rulings at any step (AC4) -------------------------------------------------------


def rule(rt, story_id: str | None = "s1", ruling: str = "revise_design") -> dict:
    reply = handoff("done", ruling=ruling)
    rt.query_fn.replies["manager"] = [reply]
    return asyncio.run(rt.run_role(StepRequest("manager", "rule", story_id)))


def test_ruling_below_the_cap_moves_the_story_and_resets_counters(make_runtime, configured) -> None:
    _, rt, _ = build_rt(make_runtime, configured, {}, ["design", "tests", "implement", "review"])
    story = add_story(rt, step="review", rounds=1, disputes=2)
    report = rule(rt)
    assert report["ruling"] == {"ruling": "revise_design", "applied": True, "now_at": "design"}
    assert (story.step, story.rounds, story.disputes, story.dispute) == ("design", 0, 0, None)
    (event,) = kinds(rt, EventKind.RULING)
    assert event.data == {"ruling": "revise_design", "now_at": "design"}


def test_ruling_on_a_done_story_is_reported_not_applied(make_runtime, configured) -> None:
    _, rt, _ = build_rt(make_runtime, configured, {}, ["design", "tests", "implement"])
    story = add_story(rt, step="implement", status=StoryStatus.DONE)
    report = rule(rt)
    why = "story s1 is done; a ruling cannot move it"
    assert report["ruling"] == {"ruling": "revise_design", "applied": False, "why": why}
    assert (story.step, story.status) == ("implement", StoryStatus.DONE)
    assert not kinds(rt, EventKind.RULING)


def test_storyless_ruling_is_reported_not_applied(make_runtime, configured) -> None:
    _, rt, _ = build_rt(make_runtime, configured, {}, ["design", "tests", "implement"])
    add_story(rt, step="review")
    report = rule(rt, story_id=None)
    why = "a ruling needs a story; run the manager on that story"
    assert report["ruling"] == {"ruling": "revise_design", "applied": False, "why": why}
    assert not kinds(rt, EventKind.RULING)


def test_manager_prompt_lists_disputes_since_last_review(make_runtime, configured) -> None:
    script, rt, _ = build_rt(
        make_runtime, configured, {"developer": [RAISE]}, ["tests", "implement"]
    )
    add_story(rt, step="implement")
    asyncio.run(rt.run_role(StepRequest("developer", "go", "s1")))
    rule(rt, ruling="revise_design")
    assert "test_disputes_since_last_review" in script.prompts["manager"][0]
    assert TEST_ID in script.prompts["manager"][0]

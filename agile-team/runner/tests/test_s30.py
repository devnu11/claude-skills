"""s30: pass_tests (F8-F11) and the read wiring (F3)."""

import asyncio
import json

import pytest
from agile_team import cli, gates, po_tools
from agile_team import config as cfg
from agile_team.gates import DisputeStage, OpenDispute, StoryState, StoryStatus
from agile_team.po_tools import Tools

from .conftest import FakeRunner

TEST_CMD = "pytest"
NOT_STUCK = (
    "story s1 is not stuck at tests (no open dispute, round cap, block or "
    "repeated setback); let the tests gate decide"
)


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


def stuck_tools(make_runtime, exit_code=0, step="tests", **kw):
    runner = FakeRunner({TEST_CMD: (exit_code, "boom\n")})
    rt = make_runtime(runner=runner)
    rt.state.sprint = 1
    kw.setdefault("sprint", 1)
    rt.state.stories["s1"] = StoryState("s1", "Add", step, **kw)
    rt.record_checkout()  # s61: the first check records it; snapshots start after that
    return Tools(rt), rt.state.stories["s1"], runner


def test_the_schema_and_tool_name_exist() -> None:
    desc, schema = po_tools.SCHEMAS["pass_tests"]
    assert schema == {"story": str, "reason": str} and "reason is required" in desc
    assert "mcp__team__pass_tests" in po_tools.tool_names()
    keys = list(po_tools.SCHEMAS)
    assert keys.index("pass_tests") == keys.index("continue_story") + 1


def snap(rt) -> str:
    return rt.state.to_json()


def test_unknown_story_is_refused(make_runtime) -> None:
    t, _, _ = stuck_tools(make_runtime)
    out = call(t.pass_tests({"story": "s9", "reason": "r"}))
    assert out == {"status": "refused", "reason": "unknown story 's9'; open it with open_story"}


def test_an_empty_reason_is_refused_and_changes_nothing(make_runtime) -> None:
    t, _, _ = stuck_tools(make_runtime, status=StoryStatus.BLOCKED)
    before = snap(t.runtime)
    out = call(t.pass_tests({"story": "s1", "reason": ""}))
    assert out == {"status": "refused", "reason": "a reason is required"}
    assert snap(t.runtime) == before


def test_a_story_not_at_tests_is_refused(make_runtime) -> None:
    t, _, runner = stuck_tools(make_runtime, step="review", status=StoryStatus.BLOCKED)
    out = call(t.pass_tests({"story": "s1", "reason": "r"}))
    assert out["reason"] == "story s1 is at step 'review'; pass_tests only moves a story from tests"
    assert runner.calls == []


def test_a_story_that_is_not_stuck_is_refused_without_running_the_suite(make_runtime) -> None:
    t, _, runner = stuck_tools(make_runtime, exit_code=1)
    before = snap(t.runtime)
    out = call(t.pass_tests({"story": "s1", "reason": "r"}))
    assert out == {"status": "refused", "reason": NOT_STUCK}
    assert runner.calls == [] and snap(t.runtime) == before


def test_a_red_suite_is_refused(make_runtime) -> None:
    dispute = OpenDispute("t.py::a", "W6", "r", "t.py", "abc")
    t, _, runner = stuck_tools(make_runtime, exit_code=1, dispute=dispute)
    before = snap(t.runtime)
    out = call(t.pass_tests({"story": "s1", "reason": "r"}))
    assert out["status"] == "refused"
    assert out["reason"].startswith(
        "the suite is red; pass_tests needs a green suite. tests fail:\n"
    )
    assert "boom" in out["reason"] and runner.calls == [TEST_CMD]
    assert snap(t.runtime) == before


STUCK = {
    "dispute": {"dispute": OpenDispute("t.py::a", "W6", "r", "t.py", "abc"), "disputes": 2},
    "needs_manager": {"status": StoryStatus.NEEDS_MANAGER},
    "blocked": {"status": StoryStatus.BLOCKED},
    "repeated": {"repeated": "same reason"},
}


@pytest.mark.parametrize("kind", STUCK)
def test_a_stuck_story_with_a_green_suite_moves_to_implement(make_runtime, kind) -> None:
    extra = dict(rounds=3, streak=["k"], run=["x"], escalated_by="repeat", hold="stopped")
    t, story, _ = stuck_tools(make_runtime, **STUCK[kind], **extra)
    out = call(t.pass_tests({"story": "s1", "reason": "tests fixed"}))
    assert out == {"status": "passed", "story": "s1", "now_at": "implement"}
    assert (story.step, story.status) == ("implement", StoryStatus.ACTIVE)
    assert (story.rounds, story.disputes, story.dispute) == (0, 0, None)
    assert (story.streak, story.run, story.repeated, story.escalated_by) == ([], [], None, None)
    assert (story.hold, story.note) == (None, "tests fixed")
    assert t.runtime.state.manager_due == ["s1: PO passed tests by hand: tests fixed"]
    saved = json.loads((t.runtime.config.run_dir / "state.json").read_text())
    assert saved["stories"]["s1"]["step"] == "implement"


def test_the_event_carries_the_open_dispute_test(make_runtime) -> None:
    t, _, _ = stuck_tools(make_runtime, **STUCK["dispute"])
    call(t.pass_tests({"story": "s1", "reason": "fixed"}))
    [e] = [e for e in t.runtime.events.events() if e.kind == "tests-passed"]
    assert (e.role, e.story) == (po_tools.PO, "s1")
    assert e.data == {"from": "tests", "now_at": "implement", "reason": "fixed", "test": "t.py::a"}


def test_the_event_has_no_test_without_a_dispute(make_runtime) -> None:
    t, _, _ = stuck_tools(make_runtime, status=StoryStatus.BLOCKED)
    call(t.pass_tests({"story": "s1", "reason": "fixed"}))
    [e] = [e for e in t.runtime.events.events() if e.kind == "tests-passed"]
    assert e.data["test"] is None


def test_the_event_kind_value() -> None:
    from agile_team.events import EventKind

    assert EventKind.TESTS_PASSED == "tests-passed"


def test_a_confirmed_dispute_counts_as_stuck(make_runtime) -> None:
    d = OpenDispute("t.py::a", "W6", "r", "t.py", "abc", stage=DisputeStage.CONFIRMED)
    t, _, _ = stuck_tools(make_runtime, dispute=d)
    assert call(t.pass_tests({"story": "s1", "reason": "r"}))["status"] == "passed"


def test_make_pipeline_reads_repo_files(configured) -> None:
    (configured / "a.txt").write_text("hello\n")
    read = cli.make_pipeline(cfg.load(configured)).checks.read
    assert read("a.txt") == "hello\n" and read("missing.txt") is None


def test_pass_tests_refusal_is_none_when_allowed(make_runtime) -> None:
    t, story, _ = stuck_tools(make_runtime, status=StoryStatus.BLOCKED)
    assert t.runtime.pipeline.pass_tests_refusal(story) is None
    assert isinstance(gates.PASS_TESTS_RED, str)

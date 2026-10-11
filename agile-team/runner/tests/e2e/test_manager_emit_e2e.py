"""s45 end to end: the manager step through the real emit path, crash log, continue_story."""

from __future__ import annotations

import asyncio

import pytest
from agile_team import halt
from agile_team.dispatch import StepRequest
from agile_team.gates import PreviousStep, StoryStatus
from agile_team.po_tools import Tools

from ..conftest import handoff
from ..pipeline_helpers import Script, add_story, build


def run_manager(rt, sid: str = "s1") -> dict:
    return asyncio.run(rt.run_role(StepRequest("manager", "rule on it", sid)))


def escalated(make_runtime, reply: str):
    """A story escalated by a unit-tester verdict: needs_manager, no repeated setback."""
    rt = build(make_runtime, Script({"manager": [reply]}), steps=["design", "tests", "implement"])
    prev = PreviousStep("unit-tester", "changes_requested", reason="runner fault: prepare fails")
    add_story(
        rt, "s1", "tests", status=StoryStatus.NEEDS_MANAGER, rounds=3, hold="x", previous=prev
    )
    return rt


@pytest.mark.parametrize("ruling", ["rescope", "revise_design", "escalate"])
def test_each_ruling_goes_through_the_real_emit(make_runtime, ruling) -> None:
    rt = escalated(make_runtime, handoff("done", ruling=ruling))
    report = run_manager(rt)
    assert report["ruling"]["applied"] is True
    assert [e.kind for e in rt.events.events() if e.kind == "ruling"] == ["ruling"]


def test_a_fault_on_a_story_without_a_repeated_setback_moves_it(make_runtime) -> None:
    rt = escalated(make_runtime, handoff("done", fault="developer"))
    report = run_manager(rt)
    assert report["fault"]["applied"] is True
    story = rt.state.stories["s1"]
    assert story.step == "implement" and story.status is StoryStatus.ACTIVE
    assert story.hold is None and story.rounds == 0 and story.dispute is None
    assert [e.kind for e in rt.events.events() if e.kind == "fault"] == ["fault"]


def test_a_fault_on_a_done_story_is_reported_unapplied(make_runtime) -> None:
    rt = escalated(make_runtime, handoff("done", fault="developer"))
    rt.state.stories["s1"].status = StoryStatus.DONE
    report = run_manager(rt)
    assert report["fault"]["applied"] is False and "done" in report["fault"]["why"]


def test_a_crash_outside_the_sdk_call_is_logged(make_runtime) -> None:
    rt = escalated(make_runtime, handoff("done", ruling="rescope"))

    def broken(*args, **kw):
        raise TypeError("emit() got multiple values for argument 'kind'")

    rt.emit = broken  # type: ignore[method-assign]
    with pytest.raises(TypeError):
        run_manager(rt)
    log = (rt.config.run_dir / halt.CRASH_LOG).read_text()
    assert "TypeError: emit() got multiple values" in log and "Traceback" in log


def test_continue_story_refuses_a_blocked_story(make_runtime) -> None:
    rt = escalated(make_runtime, handoff("done"))
    story = rt.state.stories["s1"]
    story.status, story.hold = StoryStatus.BLOCKED, None
    result = asyncio.run(Tools(rt).continue_story({"story": "s1", "note": "go"}))
    text = result["content"][0]["text"]
    assert "blocked" in text and "manager" in text
    assert story.status is StoryStatus.BLOCKED

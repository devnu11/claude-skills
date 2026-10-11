"""s27 end to end: a repeated setback stops the loop and the runner runs the Manager."""

from __future__ import annotations

from agile_team.gates import StoryStatus

from ..conftest import handoff
from ..pipeline_helpers import Script, add_story, build, drive, step_roles

BOUNCE = handoff("changes_requested", summary="tests missing for module x")


def run_loop(make_runtime, manager_reply: str):
    script = Script({"code-reviewer": [BOUNCE, BOUNCE], "manager": [manager_reply]})
    rt = build(make_runtime, script, steps=["implement", "review"])
    add_story(rt, "s1", "review")
    drive(rt)
    return rt, script


def kinds(rt) -> list[str]:
    return [e.kind for e in rt.events.events()]


def test_same_reason_twice_escalates_to_the_manager_with_no_extra_round(make_runtime) -> None:
    rt, script = run_loop(make_runtime, handoff("done", fault="developer"))
    roles = step_roles(rt)
    assert "manager" in roles
    assert roles.index("manager") > roles.index("code-reviewer")
    esc = [e for e in rt.events.events() if e.kind == "escalation"]
    assert len(esc) == 1 and esc[0].data["count"] == 2
    assert "repeated_setback" in script.prompts["manager"][0]
    assert "tests missing" in script.prompts["manager"][0]
    story = rt.state.stories["s1"]
    assert story.repeated is None and story.streak == [] and story.rounds == 0
    fault = [e for e in rt.events.events() if e.kind == "fault"]
    assert fault and fault[0].data["kind"] == "pipeline" and fault[0].data["now_at"] == "implement"


def test_a_runner_fault_blocks_the_story_and_notes_the_human(make_runtime) -> None:
    rt, _ = run_loop(make_runtime, handoff("done", fault="runner", summary="prepare fails"))
    story = rt.state.stories["s1"]
    assert story.status is StoryStatus.BLOCKED
    fault = [e for e in rt.events.events() if e.kind == "fault"]
    assert fault and fault[0].data["kind"] == "runner"
    notes = [m for m in rt.relay.messages() if "Runner fault on s1" in m.text]
    assert len(notes) == 1 and "prepare fails" in notes[0].text


def test_a_missing_fault_leaves_the_story_escalated(make_runtime) -> None:
    rt, _ = run_loop(make_runtime, handoff("done"))
    story = rt.state.stories["s1"]
    assert story.status is StoryStatus.NEEDS_MANAGER and story.repeated

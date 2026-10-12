"""s45: manager step through the real emit path, crash log, faults on any story, blocked release."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from agile_team import dispatch, gates, halt, handover, system
from agile_team.dispatch import Runtime, StepRequest
from agile_team.gates import OpenDispute, PreviousStep, StoryStatus
from agile_team.handover import Trigger
from agile_team.loops import Setback
from agile_team.po_tools import Tools
from agile_team.relay import Relay
from agile_team.router import Router

from .conftest import FakeQuery, handoff
from .pipeline_helpers import add_story
from .test_halt import RaisingQuery, crash_log, limit_error
from .test_po_tools import call, refusal_snapshot

RULING_AFTER_FAULT = "the fault was not applied, so the ruling was not either"
NEW_RUNNER_NOTE = (
    "Runner fault on s1: no role can fix this setback: {reason}. "
    "The manager says: {summary} The story is blocked until the runner is fixed."
)


def manager(rt: Runtime, sid: str | None = "s1") -> dict[str, Any]:
    return asyncio.run(rt.run_role(StepRequest("manager", "rule", sid)))


def manager_rt(make_runtime, **extra: Any) -> Runtime:
    return make_runtime(FakeQuery(handoff(summary="because", **extra)))


def repeated_story(rt: Runtime, **kw: Any) -> gates.StoryState:
    story = add_story(rt, step="tests", status=StoryStatus.NEEDS_MANAGER, repeated="same", **kw)
    story.streak = [Setback("tests", "tests", "unit-tester", "bounce", "runner", "same")]
    return story


def blocked_story(rt: Runtime) -> gates.StoryState:
    return add_story(
        rt,
        step="tests",
        status=StoryStatus.BLOCKED,
        hold="gate",
        rounds=2,
        disputes=1,
        dispute=OpenDispute("t", "r", "x"),
        previous=PreviousStep("unit-tester", "done", "", "bounce", "prior reason"),
    )


def events_of(rt: Runtime, kind: str) -> list[Any]:
    return [e for e in rt.events.events() if e.kind == kind]


def entries(rt: Runtime) -> list[str]:
    path = rt.config.run_dir / halt.CRASH_LOG
    text = system.read_text(path) if system.exists(path) else ""
    return [line for line in text.splitlines() if line.startswith("--- ")]


# ----- AC2: manager through the real emit ------------------------------------


@pytest.mark.parametrize(
    ("fault", "kind"),
    [("developer-cli", "pipeline"), ("devops", "off_pipeline"), ("runner", "runner")],
)
def test_repeated_story_fault_reports_and_logs_the_event(make_runtime, fault, kind) -> None:
    rt = manager_rt(make_runtime, fault=fault)
    repeated_story(rt)
    report = manager(rt)
    assert report["status"] == "done"
    assert report["fault"]["applied"] is True and report["fault"]["kind"] == kind
    data = events_of(rt, "fault")[0].data
    assert data["kind"] == kind and data["reason"] == "same" and data["fault"] == fault


def test_runner_fault_posts_the_human_note(make_runtime) -> None:
    rt = manager_rt(make_runtime, fault="runner")
    repeated_story(rt)
    manager(rt)
    texts = [m.text for m in Relay(rt.config.run_dir).messages()]
    assert NEW_RUNNER_NOTE.format(reason="same", summary="because") in texts


def test_repeated_story_without_a_fault_is_not_applied(make_runtime) -> None:
    rt = manager_rt(make_runtime)
    repeated_story(rt)
    report = manager(rt)
    assert report["fault"]["applied"] is False
    assert Trigger.FAULT_NOT_APPLIED in handover.triggers(report)


@pytest.mark.parametrize("ruling", ["rescope", "upgrade_model", "revise_design", "escalate"])
def test_each_ruling_on_a_capped_story_through_real_emit(make_runtime, ruling) -> None:
    rt = manager_rt(make_runtime, ruling=ruling)
    add_story(rt, step="tests", status=StoryStatus.NEEDS_MANAGER, rounds=3)
    report = manager(rt)
    assert report["status"] == "done" and report["ruling"]["applied"] is True
    assert events_of(rt, "ruling")[0].data["ruling"] == ruling


def test_old_emit_signature_fails_on_the_fault_kind(make_runtime, monkeypatch) -> None:
    original = Runtime.emit

    def emit(self, kind, plan=None, **data):
        return original(self, kind, plan, **data)

    monkeypatch.setattr(Runtime, "emit", emit)
    rt = manager_rt(make_runtime, fault="developer-cli")
    repeated_story(rt)
    with pytest.raises(TypeError, match="multiple values for argument 'kind'"):
        manager(rt)


# ----- AC3: the crash log ----------------------------------------------------


def boom(*_a: Any, **_k: Any) -> None:
    raise TypeError("boom in step")


def test_settle_crash_is_logged_once_and_reraised(make_runtime, monkeypatch) -> None:
    monkeypatch.setattr(Runtime, "apply_manager", boom)
    rt = manager_rt(make_runtime)
    add_story(rt)
    with pytest.raises(TypeError, match="boom in step"):
        manager(rt)
    log = crash_log(rt)
    assert len(entries(rt)) == 1 and entries(rt)[0].endswith("TypeError")
    assert "Traceback" in log and "boom in step" in log


def test_execute_crash_is_logged_exactly_once(make_runtime) -> None:
    rt = make_runtime(RaisingQuery(TypeError("from query")))
    add_story(rt)
    with pytest.raises(TypeError, match="from query"):
        asyncio.run(rt.run_role(StepRequest("architect", "b", "s1")))
    assert len(entries(rt)) == 1


def test_plan_crash_is_logged_once(make_runtime, monkeypatch) -> None:
    monkeypatch.setattr(Runtime, "plan", boom)
    rt = make_runtime()
    add_story(rt)
    with pytest.raises(TypeError):
        asyncio.run(rt.run_role(StepRequest("architect", "b", "s1")))
    assert len(entries(rt)) == 1


def test_router_settle_crash_is_an_error_report_with_one_entry(make_runtime, monkeypatch) -> None:
    monkeypatch.setattr(Runtime, "settle", boom)
    rt = make_runtime()
    add_story(rt)
    router = Router(rt)
    report = asyncio.run(router._dispatch(router.next_work()))
    assert report["status"] == "error"
    assert len(entries(rt)) == 1


def test_limit_error_is_halted_with_one_entry(make_runtime) -> None:
    rt = make_runtime(RaisingQuery(limit_error()))
    add_story(rt)
    report = asyncio.run(rt.run_role(StepRequest("architect", "b", "s1")))
    assert report["status"] == "halted"
    assert len(entries(rt)) == 1


def test_settle_crash_saves_the_edits_like_an_execute_crash(
    make_runtime, configured, monkeypatch
) -> None:
    monkeypatch.setattr(Runtime, "settle", boom)
    query = FakeQuery(action=lambda: system.write_text(configured / "stray.txt", "edit"))
    rt = make_runtime(query)
    add_story(rt)
    with pytest.raises(TypeError):
        asyncio.run(rt.run_role(StepRequest("architect", "b", "s1")))
    saved = events_of(rt, "step-interrupted")
    assert len(saved) == 1 and saved[0].data["cause"] == "error"


# ----- AC5, AC6: faults on any story -----------------------------------------


def test_fault_moves_a_blocked_story_and_clears_its_loop(make_runtime) -> None:
    rt = manager_rt(make_runtime, fault="developer-cli")
    story = blocked_story(rt)
    report = manager(rt)
    assert report["fault"]["applied"] is True
    assert report["fault"]["reason"] == "prior reason"
    assert (story.step, story.status, story.hold) == ("implement", StoryStatus.ACTIVE, None)
    assert (story.rounds, story.disputes, story.dispute) == (0, 0, None)


def test_runner_fault_on_a_blocked_story_keeps_it_blocked_and_held(make_runtime) -> None:
    rt = manager_rt(make_runtime, fault="runner")
    story = blocked_story(rt)
    manager(rt)
    assert story.status is StoryStatus.BLOCKED and story.hold == "runner_fault"
    texts = [m.text for m in Relay(rt.config.run_dir).messages()]
    assert NEW_RUNNER_NOTE.format(reason="prior reason", summary="because") in texts


def test_fault_without_a_story_is_not_applied(make_runtime) -> None:
    rt = manager_rt(make_runtime, fault="developer-cli")
    report = manager(rt, None)
    assert report["fault"] == {
        "fault": "developer-cli",
        "applied": False,
        "why": "a fault needs a story; run the manager on that story",
    }


def test_fault_on_a_done_story_is_not_applied(make_runtime) -> None:
    rt = manager_rt(make_runtime, fault="developer-cli")
    add_story(rt, step="acceptance", status=StoryStatus.DONE)
    why = manager(rt)["fault"]["why"]
    assert why == "story s1 is done; a fault cannot move it"


def test_unknown_fault_on_a_plain_story_hands_over_not_applied(make_runtime) -> None:
    rt = manager_rt(make_runtime, fault="nobody")
    add_story(rt, step="tests", status=StoryStatus.NEEDS_MANAGER)
    report = manager(rt)
    why = dispatch.FAULT_UNKNOWN.format(fault="nobody")
    assert report["fault"] == {"fault": "nobody", "applied": False, "why": why}
    assert Trigger.FAULT_NOT_APPLIED in handover.triggers(report)
    line = f"s1: the manager's fault ruling was not applied: {why}; run the manager on s1 again"
    assert line in handover.report_lines(report, "s1")


def test_unapplied_fault_holds_back_the_ruling_and_reports_both(make_runtime) -> None:
    rt = manager_rt(make_runtime, fault="nobody", ruling="rescope")
    story = add_story(rt, step="tests", status=StoryStatus.NEEDS_MANAGER, rounds=3)
    before = (story.step, story.status, story.rounds)
    report = manager(rt)
    assert report["ruling"] == {
        "ruling": "rescope",
        "applied": False,
        "why": RULING_AFTER_FAULT,
    }
    triggers = handover.triggers(report)
    assert Trigger.FAULT_NOT_APPLIED in triggers and Trigger.RULING_NOT_APPLIED in triggers
    assert (story.step, story.status, story.rounds) == before


def test_ruling_wins_after_an_applied_fault(make_runtime) -> None:
    rt = manager_rt(make_runtime, fault="developer-cli", ruling="revise_design")
    story = blocked_story(rt)
    report = manager(rt)
    assert report["fault"]["applied"] and report["ruling"]["applied"]
    assert story.step == "design"


def test_manager_without_fault_or_ruling_on_a_plain_story_reports_neither(make_runtime) -> None:
    rt = manager_rt(make_runtime)
    add_story(rt, step="tests", status=StoryStatus.NEEDS_MANAGER)
    report = manager(rt)
    assert "fault" not in report and "ruling" not in report


def test_ruling_refusal_default_messages_are_unchanged() -> None:
    assert gates.ruling_refusal(None) == "a ruling needs a story; run the manager on that story"
    done = gates.StoryState("s9", "t", "design", status=StoryStatus.DONE)
    assert gates.ruling_refusal(done) == "story s9 is done; a ruling cannot move it"
    assert gates.ruling_refusal(None, "a fault") == (
        "a fault needs a story; run the manager on that story"
    )
    assert gates.ruling_refusal(done, "a fault") == "story s9 is done; a fault cannot move it"


def test_setback_reason_prefers_repeated_then_previous_then_empty() -> None:
    st = gates.StoryState("s1", "t", "tests", repeated="rep")
    st.previous = PreviousStep("a", "done", verdict="bounce", reason="prev")
    assert gates.setback_reason(st) == "rep"
    st.repeated = None
    assert gates.setback_reason(st) == "prev"
    st.previous = None
    assert gates.setback_reason(st) == ""


# ----- AC7: continue_story on a blocked story --------------------------------


def blocked_reason(sid: str) -> str:
    return (
        f"story {sid} is blocked (escalated to the human); continue_story would leave it "
        f"stalled. Run the manager on {sid} with a ruling or a fault to move it"
    )


@pytest.mark.parametrize("hold", [None, "runner_fault"])
def test_continue_story_refuses_a_blocked_story(make_runtime, hold) -> None:
    rt = make_runtime()
    story = add_story(rt, status=StoryStatus.BLOCKED, hold=hold)
    out = refusal_snapshot(Tools(rt), "continue_story", {"story": "s1", "note": "go"})
    assert out["status"] == "refused" and out["reason"] == blocked_reason("s1")
    assert story.hold == hold and gates.CONTINUE_BLOCKED.format(id="s1") == blocked_reason("s1")


def test_continue_story_still_releases_active_and_done_stories(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1", hold="error")
    add_story(rt, "s2", status=StoryStatus.DONE, hold="x")
    t = Tools(rt)
    assert call(t.continue_story({"story": "s1"}))["status"] == "continued"
    assert call(t.continue_story({"story": "s2"}))["status"] == "continued"
    assert rt.state.stories["s2"].hold is None

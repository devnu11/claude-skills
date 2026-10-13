"""s53: the PO's story admin tools (hold, release, request_cancel) and cancel settling."""

import asyncio
import json
from dataclasses import asdict

import pytest
from agile_team import backlog, gates, priority, waits
from agile_team import story_admin as sa
from agile_team.events import EventKind
from agile_team.gates import FINISHED, StoryState, StoryStatus
from agile_team.holds import HoldKind, PoHold
from agile_team.po_tools import SCHEMAS, Tools
from agile_team.state import RunState


def call(coro) -> dict:
    return asyncio.run(coro)


def open_story(rt, sid: str = "s1") -> StoryState:
    call(Tools(rt).open_story({"id": sid, "title": f"title {sid}", "text": "t"}))
    return rt.state.stories[sid]


def clerk(rt) -> sa.Clerk:
    return sa.Clerk(rt)


def admin_events(rt) -> list:
    return [e for e in rt.events.events() if e.kind is EventKind.STORY_ADMIN]


def outbox(rt) -> list:
    return rt.relay.messages()


# ----- holds.py ------------------------------------------------------------------


def test_po_hold_kind_values_and_shown() -> None:
    assert (HoldKind.HOLD, HoldKind.CANCEL) == ("PO hold", "cancel requested")
    assert PoHold("PO hold", "waits on s38").kind is HoldKind.HOLD
    assert PoHold(HoldKind.CANCEL, "why", "m3").shown == "cancel requested: why"
    assert PoHold(HoldKind.HOLD, "r").question is None


# ----- gates / state -------------------------------------------------------------


def test_cancelled_is_finished() -> None:
    assert StoryStatus.CANCELLED == "cancelled"
    assert {StoryStatus.DONE, StoryStatus.CANCELLED} == FINISHED


def test_dispatch_refusal_on_a_cancelled_story(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt)
    story.status = StoryStatus.CANCELLED
    assert "was cancelled by the human" in (gates.dispatch_refusal("developer", story) or "")


def test_ruling_refusal_on_finished_stories() -> None:
    for status in (StoryStatus.DONE, StoryStatus.CANCELLED):
        story = StoryState("s1", "t", "design", status=status)
        reason = gates.ruling_refusal(story, "a ruling")
        assert reason == f"story s1 is {status}; a ruling cannot move it"


def test_state_round_trip_keeps_po_hold_as_enum() -> None:
    state = RunState()
    state.stories["s1"] = StoryState(
        "s1", "t", "design", po_hold=PoHold(HoldKind.CANCEL, "r", "m2")
    )
    back = RunState.from_json(state.to_json()).stories["s1"]
    assert back.po_hold == PoHold(HoldKind.CANCEL, "r", "m2")
    assert back.po_hold.kind is HoldKind.CANCEL


def test_old_state_without_po_hold_loads_none() -> None:
    state = RunState()
    state.stories["s1"] = StoryState("s1", "t", "design")
    data = json.loads(state.to_json())
    del data["stories"]["s1"]["po_hold"]
    assert RunState.from_json(json.dumps(data)).stories["s1"].po_hold is None


# ----- pure rules ----------------------------------------------------------------


def test_decision_table() -> None:
    assert sa.decision(" Cancel. ") is sa.Decision.CANCEL
    assert sa.decision('"KEEP"!') is sa.Decision.KEEP
    assert sa.decision("maybe") is sa.Decision.UNCLEAR
    assert sa.decision("") is sa.Decision.UNCLEAR
    assert sa.decision("cancel it") is sa.Decision.UNCLEAR


def test_tools_table_has_a_row_per_act() -> None:
    assert set(sa.TOOLS) == set(sa.Act)
    assert [a.value for a in sa.Act] == ["hold_story", "release_story", "request_cancel"]
    assert [sa.TOOLS[a].verb for a in sa.Act] == ["hold", "release", "cancel"]
    assert [sa.TOOLS[a].status for a in sa.Act] == ["held", "released", "cancel requested"]


def case(act, story, reason="why", asked=()) -> sa.Case:
    return sa.Case(act, story.id if story else "s9", reason, story, tuple(asked))


def test_refusal_order_unknown_then_reason_then_finished() -> None:
    done = StoryState("s1", "t", "design", status=StoryStatus.DONE)
    assert sa.refusal(case(sa.Act.HOLD, None, "  ")) == sa.UNKNOWN.format(story="s9")
    assert sa.refusal(case(sa.Act.HOLD, done, "  ")) == sa.NO_REASON
    assert sa.refusal(case(sa.Act.HOLD, done)) == sa.FINISHED_TEXT.format(
        story="s1", status="done", verb="hold"
    )
    gone = StoryState("s2", "t", "design", status=StoryStatus.CANCELLED)
    assert sa.refusal(case(sa.Act.REQUEST_CANCEL, gone)) == sa.FINISHED_TEXT.format(
        story="s2", status="cancelled", verb="cancel"
    )


def test_refusal_pending_cancel_blocks_hold_and_request() -> None:
    story = StoryState("s1", "t", "design", po_hold=PoHold(HoldKind.CANCEL, "r", "m4"))
    want = sa.CANCEL_PENDING.format(story="s1", question="m4")
    assert sa.refusal(case(sa.Act.HOLD, story)) == want
    assert sa.refusal(case(sa.Act.REQUEST_CANCEL, story)) == want


def test_refusal_release_checks() -> None:
    active = StoryState("s1", "t", "design")
    assert sa.refusal(case(sa.Act.RELEASE, active)) == sa.NOTHING_HELD.format(story="s1")
    assert sa.refusal(case(sa.Act.RELEASE, active, asked=("m12", "m13"))) == sa.ASKED.format(
        story="s1", ids="m12, m13"
    )
    mgr = StoryState("s1", "t", "design", status=StoryStatus.NEEDS_MANAGER)
    assert sa.refusal(case(sa.Act.RELEASE, mgr)) == sa.MANAGER_WAIT.format(story="s1")
    held = StoryState("s1", "t", "design", po_hold=PoHold(HoldKind.HOLD, "r"))
    assert sa.refusal(case(sa.Act.RELEASE, held)) is None
    blocked = StoryState("s1", "t", "design", status=StoryStatus.BLOCKED)
    assert sa.refusal(case(sa.Act.RELEASE, blocked)) is None


def test_refusal_code_unsaid_for_stories_with_commits() -> None:
    story = StoryState("s1", "t", "design", commit="abc", code_commits=["abc", "def"])
    want = sa.CODE_UNSAID.format(story="s1", count=2)
    assert sa.refusal(case(sa.Act.REQUEST_CANCEL, story, "out of scope")) == want
    assert sa.refusal(case(sa.Act.REQUEST_CANCEL, story, "its CODE stays")) is None
    assert sa.refusal(case(sa.Act.REQUEST_CANCEL, story, "one Commit reverted")) is None
    plain = StoryState("s2", "t", "design")
    assert sa.refusal(case(sa.Act.REQUEST_CANCEL, plain, "out of scope")) is None


def test_facts_shape() -> None:
    story = StoryState("s1", "t", "design", po_hold=PoHold(HoldKind.HOLD, "r"))
    facts = sa.facts(story)
    assert list(facts) == ["status", "step", "sprint", "hold", "po_hold"]
    assert facts["po_hold"] == asdict(story.po_hold)
    assert sa.facts(StoryState("s2", "t", "design"))["po_hold"] is None


# ----- Clerk.run: hold -----------------------------------------------------------


def test_hold_sets_po_hold_without_a_question(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt)
    out = clerk(rt).run(sa.Act.HOLD, {"story": "s1", "reason": "  waits on s38  "})
    assert out["status"] == "held" and out["story"] == "s1" and out["question"] is None
    assert story.po_hold == PoHold(HoldKind.HOLD, "waits on s38")
    assert outbox(rt) == []
    events = admin_events(rt)
    assert len(events) == 1 and events[0].story == "s1"
    assert events[0].role == "product-owner"
    assert events[0].data["tool"] == "hold_story"
    assert events[0].data["reason"] == "waits on s38"
    assert events[0].data["before"]["po_hold"] is None
    assert events[0].data["after"]["po_hold"]["reason"] == "waits on s38"


def test_hold_again_replaces_the_reason_and_keeps_the_old_one_in_before(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt)
    clerk(rt).run(sa.Act.HOLD, {"story": "s1", "reason": "first"})
    clerk(rt).run(sa.Act.HOLD, {"story": "s1", "reason": "second"})
    assert story.po_hold.reason == "second"
    last = admin_events(rt)[-1]
    assert last.data["before"]["po_hold"]["reason"] == "first"


def test_hold_keeps_the_board_position(make_runtime) -> None:
    rt = make_runtime()
    open_story(rt, "s1")
    open_story(rt, "s2")
    rt.state.order = ["s1", "s2"]
    rt.state.pulled = ["s2"]
    before = (list(rt.state.order), list(rt.state.pulled))
    clerk(rt).run(sa.Act.HOLD, {"story": "s1", "reason": "r"})
    assert (rt.state.order, rt.state.pulled) == before
    assert not priority.held(rt.state.stories["s1"])


@pytest.mark.parametrize(
    "setup,args",
    [
        (lambda s: None, {"story": "s9", "reason": "r"}),
        (lambda s: None, {"story": "s1", "reason": "  "}),
        (lambda s: None, {"story": "s1"}),
        (lambda s: setattr(s, "status", StoryStatus.DONE), {"story": "s1", "reason": "r"}),
        (lambda s: setattr(s, "status", StoryStatus.CANCELLED), {"story": "s1", "reason": "r"}),
        (
            lambda s: setattr(s, "po_hold", PoHold(HoldKind.CANCEL, "r", "m1")),
            {"story": "s1", "reason": "r"},
        ),
    ],
)
def test_hold_refusals_change_nothing(make_runtime, setup, args) -> None:
    rt = make_runtime()
    setup(open_story(rt))
    rt.save()
    before = rt.state.to_json()
    out = clerk(rt).run(sa.Act.HOLD, args)
    assert out["status"] == "refused" and out["reason"]
    assert rt.state.to_json() == before
    assert admin_events(rt) == [] and outbox(rt) == []


# ----- Clerk.run: release --------------------------------------------------------


def test_release_s4_case_blocked_no_hold_no_question(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt)
    story.status, story.hold, step = StoryStatus.BLOCKED, None, story.step
    out = clerk(rt).run(sa.Act.RELEASE, {"story": "s1", "reason": " try again "})
    assert out["status"] == "released"
    assert story.status is StoryStatus.ACTIVE
    assert story.po_hold is None and story.hold is None
    assert story.note == "try again" and story.step == step
    assert not (story.po_hold or story.hold or story.status is StoryStatus.BLOCKED)
    assert admin_events(rt)[0].data["before"]["status"] == "blocked"


def test_release_clears_a_po_hold(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt)
    clerk(rt).run(sa.Act.HOLD, {"story": "s1", "reason": "r"})
    out = clerk(rt).run(sa.Act.RELEASE, {"story": "s1", "reason": "go"})
    assert out["status"] == "released" and story.po_hold is None and story.note == "go"


def test_release_refused_with_an_open_question_names_it(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt)
    story.status = StoryStatus.BLOCKED
    rt.save()
    rt.relay.post(sa.Note("question", "q?", ["s1"]))
    before = rt.state.to_json()
    out = clerk(rt).run(sa.Act.RELEASE, {"story": "s1", "reason": "r"})
    assert out["status"] == "refused" and "answer m1 instead" in out["reason"]
    assert rt.state.to_json() == before and admin_events(rt) == []


def test_release_refusals_manager_and_nothing_held(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt)
    out = clerk(rt).run(sa.Act.RELEASE, {"story": "s1", "reason": "r"})
    assert out["reason"] == sa.NOTHING_HELD.format(story="s1")
    story.status = StoryStatus.NEEDS_MANAGER
    out = clerk(rt).run(sa.Act.RELEASE, {"story": "s1", "reason": "r"})
    assert out["reason"] == sa.MANAGER_WAIT.format(story="s1")
    assert story.status is StoryStatus.NEEDS_MANAGER


def test_continue_story_leaves_a_po_hold(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt)
    clerk(rt).run(sa.Act.HOLD, {"story": "s1", "reason": "r"})
    story.hold = "stopped"
    call(Tools(rt).continue_story({"story": "s1", "note": "n"}))
    assert story.hold is None and story.po_hold is not None


# ----- Clerk.run: request_cancel -------------------------------------------------


def test_request_cancel_posts_one_question_and_holds(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt)
    status = story.status
    out = clerk(rt).run(sa.Act.REQUEST_CANCEL, {"story": "s1", "reason": "not needed"})
    assert out["status"] == "cancel requested" and out["question"] == "m1"
    (msg,) = outbox(rt)
    assert msg.kind == "question" and msg.stories == ["s1"]
    assert msg.text == sa.CANCEL_QUESTION.format(story="s1", title="title s1", reason="not needed")
    assert story.po_hold == PoHold(HoldKind.CANCEL, "not needed", "m1")
    assert story.status is status
    assert admin_events(rt)[0].data["question"] == "m1"


def test_request_cancel_code_rule(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt)
    story.commit, story.code_commits = "abc", ["abc"]
    out = clerk(rt).run(sa.Act.REQUEST_CANCEL, {"story": "s1", "reason": "out of scope"})
    assert out["reason"] == sa.CODE_UNSAID.format(story="s1", count=1)
    assert outbox(rt) == [] and story.po_hold is None
    out = clerk(rt).run(
        sa.Act.REQUEST_CANCEL, {"story": "s1", "reason": "its code stays; s99 replaces it"}
    )
    assert out["status"] == "cancel requested"


# ----- settle --------------------------------------------------------------------


def requested(rt, sid: str = "s1") -> StoryState:
    story = open_story(rt, sid)
    clerk(rt).run(sa.Act.REQUEST_CANCEL, {"story": sid, "reason": "gone"})
    return story


def test_cancel_answer_cancels_and_cleans_up(make_runtime) -> None:
    rt = make_runtime()
    story = requested(rt)
    story.commit, story.code_commits, story.sprint = "abc", ["abc"], 1
    rt.state.order, rt.state.pulled = ["s1", "s2"], ["s1"]
    rt.state.human_order, rt.state.scribe_due = ["s1"], ["s1"]
    rt.relay.answer("m1", " Cancel. ")
    assert clerk(rt).settle() == ["s1"]
    assert story.status is StoryStatus.CANCELLED
    assert story.po_hold is None and story.hold is None and story.sprint is None
    assert (rt.state.order, rt.state.pulled) == (["s2"], [])
    assert (rt.state.human_order, rt.state.scribe_due) == ([], [])
    assert story.commit == "abc" and story.code_commits == ["abc"]
    event = admin_events(rt)[-1]
    assert event.role is None and event.data["tool"] == "answer"
    assert event.data["decision"] == "cancel" and event.data["question"] == "m1"
    assert event.data["after"]["status"] == "cancelled"
    assert json.loads(rt.state.to_json())["stories"]["s1"]["status"] == "cancelled"


def test_keep_answer_releases_the_hold(make_runtime) -> None:
    rt = make_runtime()
    story = requested(rt)
    status = story.status
    rt.relay.answer("m1", "keep")
    assert clerk(rt).settle() == ["s1"]
    assert story.po_hold is None and story.status is status
    assert admin_events(rt)[-1].data["decision"] == "keep"


def test_unclear_answer_holds_for_the_po(make_runtime) -> None:
    rt = make_runtime()
    story = requested(rt)
    rt.relay.answer("m1", "maybe")
    clerk(rt).settle()
    assert story.po_hold.kind is HoldKind.HOLD
    assert story.po_hold.reason == sa.UNCLEAR_ANSWER.format(question="m1", answer="maybe")
    assert story.status is not StoryStatus.CANCELLED


def test_unanswered_request_settles_nothing(make_runtime) -> None:
    rt = make_runtime()
    story = requested(rt)
    count = len(admin_events(rt))
    assert clerk(rt).settle() == []
    assert story.po_hold.kind is HoldKind.CANCEL and len(admin_events(rt)) == count


def test_answers_to_other_questions_do_not_cancel(make_runtime) -> None:
    rt = make_runtime()
    open_story(rt, "s1")
    open_story(rt, "s2")
    other = rt.relay.post(sa.Note("question", "unrelated", ["s2"]))
    rt.relay.answer(other.id, "cancel")
    clerk(rt).run(sa.Act.HOLD, {"story": "s1", "reason": "r"})
    assert rt.state.stories["s2"].status is not StoryStatus.CANCELLED
    assert rt.state.stories["s1"].status is not StoryStatus.CANCELLED


def test_run_settles_first(make_runtime) -> None:
    rt = make_runtime()
    requested(rt)
    rt.relay.answer("m1", "cancel")
    out = clerk(rt).run(sa.Act.RELEASE, {"story": "s1", "reason": "go"})
    assert out == {
        "status": "refused",
        "reason": sa.FINISHED_TEXT.format(story="s1", status="cancelled", verb="release"),
    }


def test_wait_for_answers_settles_before_reading(make_runtime, fake) -> None:
    rt = make_runtime()
    story = requested(rt)
    fake.on_sleep = [lambda: rt.relay.answer("m1", "cancel")]
    call(Tools(rt).wait_for_answers({"ids": ["m1"]}))
    assert story.status is StoryStatus.CANCELLED


# ----- only the answer cancels ---------------------------------------------------


def test_no_tool_effect_cancels(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt)
    for act in sa.Act:
        sa.TOOLS[act].effect(story, sa.Change("cancel", "m1"))
        assert story.status is not StoryStatus.CANCELLED


# ----- schemas, waits, labels, priority ------------------------------------------


def test_schemas_rows() -> None:
    for name in ("hold_story", "release_story", "request_cancel"):
        assert name in SCHEMAS
        assert len(SCHEMAS[name]) > 1
        assert set(SCHEMAS[name][1]) == {"story", "reason"}


def tool(rt, name: str, reason: str) -> dict:
    result = call(getattr(Tools(rt), name)({"story": "s1", "reason": reason}))
    return json.loads(result["content"][0]["text"])


def test_hold_story_wrapper_holds(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt)
    out = tool(rt, "hold_story", "waits")
    assert out["status"] == "held"
    assert story.po_hold == PoHold(HoldKind.HOLD, "waits")


def test_release_story_wrapper_releases(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt)
    tool(rt, "hold_story", "waits")
    out = tool(rt, "release_story", "go")
    assert out["status"] == "released"
    assert story.po_hold is None


def test_request_cancel_wrapper_asks(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt)
    out = tool(rt, "request_cancel", "gone")
    assert out["status"] == "cancel requested" and out["question"] == "m1"
    assert story.po_hold.kind is HoldKind.CANCEL


def test_wait_titles(make_runtime) -> None:
    rt = make_runtime()
    story = open_story(rt)
    clerk(rt).run(sa.Act.HOLD, {"story": "s1", "reason": "waits on s38"})
    w = waits.wait(story, [])
    assert w.title == "PO hold: waits on s38"
    clerk(rt).run(sa.Act.REQUEST_CANCEL, {"story": "s1", "reason": "gone"})
    w = waits.wait(story, ["m1"])
    assert w.title == "cancel requested: gone"
    story.status = StoryStatus.CANCELLED
    assert waits.wait(story, []) is None


def test_label_table() -> None:
    def label(**kw) -> str:
        return backlog.label(StoryState("s1", "t", "design", **kw))

    assert label(status=StoryStatus.CANCELLED) == "cancelled"
    assert label(hold="cancelled by human") == "cancelled"
    assert label(po_hold=PoHold(HoldKind.CANCEL, "r", "m1")) == "cancel requested"
    assert label(po_hold=PoHold(HoldKind.HOLD, "r")) == "held"
    assert label(status=StoryStatus.BLOCKED) == "held"
    assert label() == ""


def test_cancelled_story_is_out_of_the_queue(make_runtime) -> None:
    rt = make_runtime()
    open_story(rt, "s1")
    open_story(rt, "s2")
    rt.state.stories["s2"].status = StoryStatus.CANCELLED
    assert priority.Priority(rt.state.order, rt.state.pulled).queue(rt.state.stories.values()) == [
        "s1"
    ]
    assert "s2" in (priority.order_refusal(["s2"], rt.state.stories) or "")


def test_po_hold_keeps_tier_and_rank(make_runtime) -> None:
    rt = make_runtime()
    open_story(rt, "s1")
    open_story(rt, "s2")
    rt.state.order = ["s1", "s2"]
    before = priority.Priority(rt.state.order, rt.state.pulled).queue(rt.state.stories.values())
    rt.state.stories["s1"].po_hold = PoHold(HoldKind.HOLD, "r")
    assert (
        priority.Priority(rt.state.order, rt.state.pulled).queue(rt.state.stories.values())
        == before
    )

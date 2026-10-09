"""s19: the Router passes, standard briefs, role choice and the driver."""

import asyncio

import pytest
from agile_team import cli, po_tools, router
from agile_team.gates import PreviousStep, StoryState, StoryStatus
from agile_team.handover import Trigger as T
from agile_team.po_tools import RESUME_NOTE, Start, StartMode, Tools
from agile_team.relay import Note
from agile_team.router import Router, Work, standard_brief
from agile_team.state import RunStatus

from .pipeline_helpers import (
    PO_ROLE,
    Script,
    add_story,
    ask_and_answer,
    build,
    drive,
    handover_events,
    step_roles,
    write_file,
)

LIMIT = RuntimeError("You've hit your session limit · resets 2:20pm (America/Edmonton)")
HEADING = "Standard brief from the runner. Read the files below; they hold the details."


def advance(rt, sleep=None):
    r = Router(rt, sleep=sleep) if sleep else Router(rt)
    return asyncio.run(r.advance())


def blocked_reply(summary="stuck"):
    return f'x\n```handoff\n{{"status": "blocked", "summary": "{summary}"}}\n```'


# ----- role choice (R3, AC4) ---------------------------------------------------


def prev(**kw) -> PreviousStep:
    return PreviousStep(**{"role": "code-reviewer", "status": "changes_requested", **kw})


ROLE_CASES = [
    ("implement", {}, "developer"),
    ("implement", {"developer": "developer-cli"}, "developer-cli"),
    ("implement", {"developer": "developer-cli", "po_developer": "developer-db"}, "developer-db"),
    (
        "implement",
        {
            "po_developer": "developer-db",
            "previous": prev(verdict="bounce", next_role="developer-gui"),
        },
        "developer-db",
    ),
    (
        "implement",
        {
            "developer": "developer-api",
            "previous": prev(verdict="bounce", next_role="developer-gui"),
        },
        "developer-gui",
    ),
    (
        "implement",
        {"developer": "developer-cli", "previous": prev(role="developer-api", verdict="bounce")},
        "developer-api",
    ),
    (
        "implement",
        {"developer": "developer-cli", "previous": prev(verdict="bounce", next_role=None)},
        "developer-cli",
    ),
    (
        "implement",
        {"developer": "developer-cli", "previous": prev(verdict="pass")},
        "developer-cli",
    ),
    ("implement", {"previous": prev(role="developer-api", verdict="return")}, "developer"),
    ("review", {"developer": "developer-cli"}, "code-reviewer"),
    ("design", {"po_developer": "developer-db"}, "architect"),
    ("review", {"previous": prev(verdict="bounce", next_role="developer-gui")}, "code-reviewer"),
    ("tests", {"developer": "developer-cli"}, "unit-tester"),
]


@pytest.mark.parametrize(("step", "fields", "role"), ROLE_CASES)
def test_step_role_follows_the_hints_in_order(step, fields, role) -> None:
    assert router.step_role(StoryState("s1", "t", step, **fields)) == role


def test_role_hints_is_a_tuple_of_functions() -> None:
    assert isinstance(router.ROLE_HINTS, tuple) and len(router.ROLE_HINTS) == 5
    assert all(callable(h) for h in router.ROLE_HINTS)


# ----- standard brief (R4) -------------------------------------------------------


def brief(rt, story, role="developer"):
    return standard_brief(rt.config, Work(role, story, ""))


def test_brief_without_files_is_just_the_heading(make_runtime) -> None:
    rt = make_runtime()
    assert brief(rt, add_story(rt)) == HEADING


def test_brief_points_at_story_design_and_review(make_runtime) -> None:
    rt = make_runtime()
    story = add_story(rt, "s19")
    write_file(rt, ".team/stories/s19.md")
    write_file(rt, "docs/design/s19.md")
    write_file(rt, "docs/architecture.md")
    write_file(rt, ".team/reviews/s19.md")
    assert brief(rt, story) == "\n".join(
        [
            HEADING,
            "- Story: .team/stories/s19.md",
            "- Design: docs/design/s19.md",
            "- Review: .team/reviews/s19.md",
        ]
    )


def test_design_falls_back_to_architecture(make_runtime) -> None:
    rt = make_runtime()
    story = add_story(rt)
    write_file(rt, "docs/architecture.md")
    assert brief(rt, story).splitlines()[1:] == ["- Design: docs/architecture.md"]


def test_docs_dir_trailing_slash_is_ignored(make_runtime) -> None:
    rt = make_runtime()
    rt.config.team.docs_dir = "docs/"
    write_file(rt, "docs/design/s1.md")
    assert "- Design: docs/design/s1.md" in brief(rt, add_story(rt))


def test_brief_shows_previous_step_with_and_without_summary(make_runtime) -> None:
    rt = make_runtime()
    with_summary = add_story(rt, previous=prev(summary="two functions exceed 8 lines"))
    assert brief(rt, with_summary).splitlines()[1:] == [
        "- Previous step: code-reviewer reported changes_requested: two functions exceed 8 lines"
    ]
    bare = add_story(rt, "s2", previous=prev(status="done"))
    assert brief(rt, bare).splitlines()[1:] == ["- Previous step: code-reviewer reported done"]


@pytest.mark.parametrize(
    ("verdict", "sent_back"), [("bounce", True), ("return", True), ("pass", False)]
)
def test_sent_back_line_only_for_bounce_and_return(make_runtime, verdict, sent_back) -> None:
    rt = make_runtime()
    story = add_story(rt, previous=prev(verdict=verdict, reason="the reason", summary="s"))
    assert ("- Sent back to this step: the reason" in brief(rt, story).splitlines()) is sent_back


def test_review_bounce_example(make_runtime) -> None:
    rt = make_runtime()
    story = add_story(
        rt,
        "s19",
        "implement",
        previous=prev(
            summary="two functions exceed 8 lines",
            verdict="bounce",
            reason="two functions exceed 8 lines",
        ),
    )
    for rel in (".team/stories/s19.md", "docs/design/s19.md", ".team/reviews/s19.md"):
        write_file(rt, rel)
    assert brief(rt, story) == "\n".join(
        [
            HEADING,
            "- Story: .team/stories/s19.md",
            "- Design: docs/design/s19.md",
            "- Review: .team/reviews/s19.md",
            "- Previous step: code-reviewer reported changes_requested: "
            "two functions exceed 8 lines",
            "- Sent back to this step: two functions exceed 8 lines",
        ]
    )


def test_brief_carries_the_po_note(make_runtime) -> None:
    rt = make_runtime()
    story = add_story(rt, note="use sqlite")
    assert brief(rt, story).splitlines()[-1] == "- From the PO: use sqlite"


def test_scribe_heading(make_runtime) -> None:
    rt = make_runtime()
    story = add_story(rt, "s7", status=StoryStatus.DONE)
    text = brief(rt, story, "scribe")
    assert text.splitlines()[0] == (
        "Story s7 is done. Record its decisions as ADRs and refresh the role briefs. "
        "Read the files below."
    )


# ----- picking work (R2, R13) ------------------------------------------------------


def test_pickers_is_manager_scribe_story() -> None:
    names = [p.__name__ for p in Router.PICKERS]
    assert names == ["_manager_work", "_scribe_work", "_story_work"]


def test_manager_comes_first_and_runs_story_less(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1", status=StoryStatus.DONE)
    add_story(rt, "s2")
    rt.state.scribe_due = ["s1"]
    rt.state.manager_due = ["sprint 1 start: G (s1)", "review model override for developer"]
    work = Router(rt).next_work()
    assert (work.role, work.story) == ("manager", None)


def test_scribe_comes_before_stories(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1", status=StoryStatus.DONE)
    add_story(rt, "s2")
    rt.state.scribe_due = ["s1"]
    work = Router(rt).next_work()
    assert (work.role, work.story.id) == ("scribe", "s1")


def test_scribe_skips_held_and_question_blocked_done_stories(make_runtime) -> None:
    rt = make_runtime()
    held = add_story(rt, "s1", status=StoryStatus.DONE, hold="stopped")
    add_story(rt, "s2", status=StoryStatus.DONE)
    rt.state.scribe_due = ["s1", "s2"]
    rt.relay.post(Note("question", "Accept?", ["s2"]))
    assert Router(rt).next_work() is None
    held.hold = None
    assert Router(rt).next_work().story.id == "s1"
    rt.relay.answer("m1", "yes")
    held.hold = "x"
    assert Router(rt).next_work().story.id == "s2"


def test_story_picker_takes_the_first_movable_story(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s0", sprint=None)
    add_story(rt, "s1", hold="stopped")
    add_story(rt, "s2", status=StoryStatus.NEEDS_MANAGER)
    add_story(rt, "s3", status=StoryStatus.BLOCKED)
    add_story(rt, "s4", status=StoryStatus.DONE)
    add_story(rt, "s5", sprint=2)
    add_story(rt, "s6")
    add_story(rt, "s7")
    rt.relay.post(Note("question", "?", ["s6"]))
    work = Router(rt).next_work()
    assert (work.role, work.story.id) == ("architect", "s7")


def test_story_work_uses_the_chosen_developer(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1", "implement", developer="developer-api")
    assert Router(rt).next_work().role == "developer-api"


def test_no_work_when_nothing_is_movable(make_runtime) -> None:
    rt = make_runtime()
    assert Router(rt).next_work() is None


# ----- run-level passes (R7, R8) -------------------------------------------------


def test_sprint_end_when_every_story_is_done(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1", status=StoryStatus.DONE)
    add_story(rt, "s2", sprint=None)
    p = advance(rt)
    assert (p.kinds, p.lines, p.stories, p.steps) == (
        [T.SPRINT_END],
        ["Sprint 1 is complete: every story in it is done."],
        [],
        0,
    )


def test_empty_sprint_is_stalled_not_ended(make_runtime) -> None:
    rt = make_runtime()
    rt.state.sprint = 1
    p = advance(rt)
    assert p.kinds == [T.STALLED]
    assert p.lines[0] == "Nothing in sprint 1 can move."
    assert p.lines[1] == "No story is in sprint 1; start_sprint with the stories to work on."
    assert len(p.lines) == 2 and p.stories == []


def test_empty_sprint_lists_the_backlog(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s9", sprint=None)
    rt.state.stories["s8"] = StoryState("s8", "t", "design", sprint=1, status=StoryStatus.DONE)
    rt.state.sprint = 2
    p = advance(rt)
    assert p.lines[-1] == "Backlog: s9" and p.lines[0] == "Nothing in sprint 2 can move."


STALLS = [
    ({"hold": "stopped, questions"}, "s1 at implement: held (stopped, questions)"),
    ({"status": StoryStatus.NEEDS_MANAGER}, "s1 at implement: at the round cap"),
    ({"status": StoryStatus.BLOCKED}, "s1 at implement: escalated to the human"),
]


@pytest.mark.parametrize(("fields", "line"), STALLS)
def test_stalled_explains_each_unfinished_story(make_runtime, fields, line) -> None:
    rt = make_runtime()
    add_story(rt, "s1", "implement", **fields)
    add_story(rt, "s2", status=StoryStatus.DONE)
    p = advance(rt)
    assert p.kinds == [T.STALLED]
    assert p.lines == ["Nothing in sprint 1 can move.", line]
    assert p.stories == ["s1"]


def test_stall_reasons_table() -> None:
    keys = set(router.STALL_REASONS)
    assert StoryStatus.NEEDS_MANAGER in keys and StoryStatus.BLOCKED in keys and "hold" in keys


def test_stop_request_ends_the_pass_with_no_kinds(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt)
    (rt.config.run_dir).mkdir(parents=True, exist_ok=True)
    (rt.config.run_dir / "stop").write_text("")
    p = advance(rt)
    assert p.kinds == [] and p.steps == 0
    assert step_roles(rt) == []


def test_halted_run_ends_the_pass(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt)
    rt.state.status = RunStatus.BLOCKED
    assert advance(rt).kinds == []
    rt.state.status = RunStatus.IDLE
    rt.halted_by = object()
    assert advance(rt).kinds == []


def test_new_answers_hand_over_before_any_step(make_runtime) -> None:
    rt = build(make_runtime, Script())
    add_story(rt)
    rt.state.delivered = []
    qid = ask_and_answer(rt, "Which DB?", ["s1"], "sqlite")
    ask_and_answer(rt, "Which port?", ["s2"], "80")
    p = advance(rt)
    assert p.kinds == [T.HUMAN_MESSAGE] and p.steps == 0
    assert p.lines == [
        'The human answered m1 ("Which DB?"): sqlite',
        'The human answered m2 ("Which port?"): 80',
    ]
    assert p.stories == ["s1", "s2"] and qid == "m1"
    assert rt.state.delivered == ["m1", "m2"]
    assert step_roles(rt) == []


def test_delivered_answers_are_not_handed_over_again(make_runtime) -> None:
    rt = build(make_runtime, Script(), steps=["design"])
    add_story(rt, status=StoryStatus.DONE)
    ask_and_answer(rt)
    rt.state.delivered = ["m1"]
    assert advance(rt).kinds == [T.SPRINT_END]


def test_waiting_for_an_answer_polls_until_it_arrives(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1", "implement")
    rt.relay.post(Note("question", "Which DB?", ["s1"]))
    rt.state.delivered = []
    slept = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) == 2:
            rt.relay.answer("m1", "sqlite")

    p = advance(rt, sleep)
    assert slept == [5.0, 5.0]
    assert p.kinds == [T.HUMAN_MESSAGE]
    assert p.lines == ['The human answered m1 ("Which DB?"): sqlite']
    assert rt.state.delivered == ["m1"]


def test_waiting_ends_on_a_stop_request(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1", "implement")
    rt.relay.post(Note("question", "?", ["s1"]))
    rt.state.delivered = []

    async def sleep(_s: float) -> None:
        (rt.config.run_dir / "stop").write_text("")

    p = advance(rt, sleep)
    assert p.kinds == []


def test_a_question_that_blocks_nothing_still_makes_the_router_wait(make_runtime) -> None:
    rt = make_runtime()
    add_story(rt, "s1", hold="stopped")
    rt.relay.post(Note("question", "?", []))
    rt.state.delivered = []

    async def sleep(_s: float) -> None:
        rt.relay.answer("m1", "ok")

    assert advance(rt, sleep).kinds == [T.HUMAN_MESSAGE]


# ----- the pass runs steps (AC1) ------------------------------------------------------


def test_one_run_drives_a_story_to_done_and_ends_at_sprint_end(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script)
    add_story(rt)
    drive(rt)
    assert step_roles(rt) == ["architect", "unit-tester", "developer", "code-reviewer", "scribe"]
    story = rt.state.stories["s1"]
    assert story.status is StoryStatus.DONE and rt.state.scribe_due == []
    assert [r for r, _ in script.calls].count(PO_ROLE) == 2
    assert "Sprint 1 is complete: every story in it is done." in script.po_prompts[1]
    assert rt.state.status is RunStatus.IDLE
    events = handover_events(rt)
    assert len(events) == 1
    assert (events[0].role, events[0].story) == (PO_ROLE, None)
    assert events[0].data == {"triggers": ["sprint_end"], "stories": [], "steps": 5}


def test_the_scribe_step_is_story_bound_and_the_manager_is_not(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script, steps=["design"])
    add_story(rt)
    rt.state.manager_due = ["sprint 1 start: G (s1)"]
    drive(rt)
    starts = [(e.role, e.story) for e in rt.events.events() if e.kind == "step-start"]
    assert starts == [("manager", None), ("architect", "s1"), ("scribe", "s1")]
    assert rt.state.manager_due == []
    manager_prompt = script.prompts["manager"][0]
    assert manager_prompt.startswith("Manager review due: sprint 1 start: G (s1)")
    assert "- Story:" not in manager_prompt


def test_each_step_gets_a_standard_brief(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script, steps=["design", "review"])
    add_story(rt)
    write_file(rt, ".team/stories/s1.md")
    drive(rt)
    first = script.prompts["architect"][0]
    assert first.startswith(HEADING) and "- Story: .team/stories/s1.md" in first
    assert "Story s1: Title s1 (step design, round 0)" in first
    assert "- Previous step: architect reported done" in script.prompts["code-reviewer"][0]
    assert script.prompts["scribe"][0].startswith("Story s1 is done. Record its decisions")


def test_the_architects_developer_pick_reaches_the_implement_step(make_runtime) -> None:
    pick = '```handoff\n{"status": "done", "developer": "developer-cli"}\n```'
    script = Script({"architect": [pick]})
    rt = build(make_runtime, script, steps=["design", "tests", "implement"])
    add_story(rt)
    drive(rt)
    assert step_roles(rt)[:3] == ["architect", "unit-tester", "developer-cli"]


def test_the_pos_developer_beats_the_architects(make_runtime) -> None:
    pick = '```handoff\n{"status": "done", "developer": "developer-cli"}\n```'
    rt = build(make_runtime, Script({"architect": [pick]}), steps=["design", "implement"])
    add_story(rt, po_developer="developer-db")
    drive(rt)
    assert step_roles(rt)[:2] == ["architect", "developer-db"]


# ----- bounces (AC3) -------------------------------------------------------------------


def test_a_review_bounce_goes_to_the_named_developer_with_the_reason(make_runtime) -> None:
    bounce = (
        '```handoff\n{"status": "changes_requested", "summary": "two functions exceed 8 lines",'
        ' "next_role": "developer-gui"}\n```'
    )
    script = Script({"code-reviewer": [bounce]})
    rt = build(make_runtime, script, steps=["implement", "review"])
    add_story(rt, "s1", "implement")
    write_file(rt, ".team/reviews/s1.md")
    rt.git.commit([".team/reviews/s1.md"], "docs: review")  # settle quarantines untracked files
    drive(rt)
    assert step_roles(rt)[:4] == ["developer", "code-reviewer", "developer-gui", "code-reviewer"]
    text = script.prompts["developer-gui"][0]
    assert "- Review: .team/reviews/s1.md" in text
    assert "- Sent back to this step: two functions exceed 8 lines" in text
    assert "- Previous step: code-reviewer reported changes_requested:" in text
    assert len(handover_events(rt)) == 1  # only the sprint end


def test_a_red_implement_gate_reruns_the_same_developer_with_the_test_tail(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script, steps=["implement", "review"], failures=1)
    add_story(rt, "s1", "implement", developer="developer-api")
    drive(rt)
    assert step_roles(rt)[:3] == ["developer-api", "developer-api", "code-reviewer"]
    retry = script.prompts["developer-api"][1]
    assert "- Sent back to this step: tests fail:" in retry and "boom: assertion failed" in retry
    assert rt.state.stories["s1"].rounds == 1


def test_the_third_bounce_hands_over_the_round_cap(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script, steps=["implement", "review"], failures=99)
    rt.pipeline.cap = 3
    add_story(rt, "s1", "implement")
    drive(rt)
    assert step_roles(rt) == ["developer"] * 3
    story = rt.state.stories["s1"]
    assert story.status is StoryStatus.NEEDS_MANAGER and story.hold == "round_cap"
    events = handover_events(rt)
    assert events[0].data == {"triggers": ["round_cap"], "stories": ["s1"], "steps": 3}
    assert "s1: hit the round cap; run the manager on it for a ruling" in script.po_prompts[1]
    assert len(script.po_prompts) == 2  # then stalled and quiet after the PO


def test_an_unroutable_bounce_hands_over(make_runtime) -> None:
    bounce = (
        '```handoff\n{"status": "changes_requested", "summary": "s", "next_role": "devops"}\n```'
    )
    script = Script({"code-reviewer": [bounce]})
    rt = build(make_runtime, script, steps=["implement", "review"])
    add_story(rt, "s1", "review")
    drive(rt)
    assert handover_events(rt)[0].data["triggers"] == ["unroutable"]
    assert "devops, which owns no pipeline step" in script.po_prompts[1]
    assert rt.state.stories["s1"].hold == "unroutable"


# ----- holds and the PO's tools (R6) -----------------------------------------------------


def test_a_blocked_step_holds_the_story_until_continue_story(make_runtime) -> None:
    async def continue_it(rt) -> None:
        out = await Tools(rt).continue_story({"story": "s1", "note": "use sqlite"})
        assert "continued" in out["content"][0]["text"]

    script = Script({"architect": [blocked_reply("need a database")]}, po=[None, continue_it])
    rt = build(make_runtime, script, steps=["design", "review"])
    add_story(rt)
    drive(rt)
    assert step_roles(rt) == ["architect", "architect", "code-reviewer", "scribe"]
    assert "s1: architect reported blocked: need a database" in script.po_prompts[1]
    assert "- From the PO: use sqlite" in script.prompts["architect"][1]
    story = rt.state.stories["s1"]
    assert story.hold is None and story.note == ""
    assert "From the PO" not in script.prompts["code-reviewer"][0]


def test_the_router_skips_a_held_story_and_runs_the_others(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script, steps=["design"])
    add_story(rt, "s0", sprint=None)
    add_story(rt, "s1", hold="stopped")
    add_story(rt, "s2")
    p = advance(rt)
    assert step_roles(rt) == ["architect", "scribe"]
    assert p.kinds == [T.STALLED]
    assert p.lines[-1] == "s1 at design: held (stopped)"
    assert p.steps == 2


def test_the_note_is_cleared_after_the_step_runs(make_runtime) -> None:
    rt = build(make_runtime, Script(), steps=["design", "review"])
    story = add_story(rt, note="remember X")
    advance(rt)
    assert story.note == ""


def test_a_refused_router_step_keeps_the_note_and_holds_the_story(make_runtime) -> None:
    rt = build(make_runtime, Script(), steps=["design", "implement"])
    story = add_story(rt, step="implement", note="remember X", po_developer="developer-ghost")
    p = advance(rt)
    assert p.kinds == [T.REFUSED] and "unknown role 'developer-ghost'" in p.lines[0]
    assert story.note == "remember X" and story.hold == "refused"


def test_a_crash_in_a_step_hands_over_an_error_and_holds(make_runtime) -> None:
    script = Script({"architect": [RuntimeError("boom")]})
    rt = build(make_runtime, script, steps=["design"])
    add_story(rt)
    drive(rt)
    story = rt.state.stories["s1"]
    assert story.hold == "error"
    assert "s1: architect crashed: crashed: RuntimeError: boom" in script.po_prompts[1]
    assert "details in .team/run/crash.log" in script.po_prompts[1]
    assert (rt.config.run_dir / "crash.log").is_file()
    assert handover_events(rt)[0].data == {"triggers": ["error"], "stories": ["s1"], "steps": 1}


def test_a_step_that_asks_a_question_hands_over(make_runtime) -> None:
    asking = '```handoff\n{"status": "done", "open_questions": ["which db?"]}\n```'
    script = Script({"architect": [asking]})
    rt = build(make_runtime, script, steps=["design", "review"])
    add_story(rt)
    drive(rt)
    assert step_roles(rt) == ["architect"]
    assert "s1: architect asks: which db?" in script.po_prompts[1]
    assert rt.state.stories["s1"].hold == "questions"
    assert rt.state.stories["s1"].step == "review"


def test_a_quarantine_hands_over(make_runtime) -> None:
    async def stray(rt_) -> None:
        write_file(rt_, "src/stray.py", "y = 2\n")

    rt = build(make_runtime, Script({"architect": [stray]}), steps=["design", "review"])
    add_story(rt)
    p = advance(rt)
    assert p.kinds == [T.QUARANTINE]
    assert "out-of-scope changes are quarantined in" in p.lines[0]


# ----- scribe and manager (AC5) ----------------------------------------------------------


def test_a_bad_scribe_handoff_still_clears_scribe_due(make_runtime) -> None:
    script = Script({"scribe": ["no handoff block at all"]})
    rt = build(make_runtime, script, steps=["design"])
    add_story(rt)
    drive(rt)
    assert rt.state.scribe_due == []
    assert handover_events(rt)[0].data["triggers"] == ["bad_handoff"]
    assert "s1: scribe gave no valid handoff:" in script.po_prompts[1]
    assert len(script.po_prompts) == 2


def test_a_budget_checkpoint_runs_the_manager_before_the_next_step(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script, steps=["design", "review"])
    add_story(rt)

    async def cross_budget(rt_) -> None:
        rt_.state.manager_due.append("budget checkpoint at $5.00")

    script.replies["architect"] = [cross_budget]
    drive(rt)
    assert step_roles(rt)[:3] == ["architect", "manager", "code-reviewer"]
    assert script.prompts["manager"][0].startswith("Manager review due: budget checkpoint")


# ----- driver ends (R9, R10, R11, R16) ---------------------------------------------------


def test_a_kickoff_with_no_sprint_runs_one_po_turn(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script)
    result = drive(rt, "Build it")
    assert len(script.po_prompts) == 1 and "Build it" in script.po_prompts[0]
    assert result.session_id == "sess"
    assert handover_events(rt) == [] and rt.state.status is RunStatus.IDLE


def test_a_bare_resume_runs_the_router_first(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script, steps=["design"])
    rt.state.po_session = "old"
    add_story(rt)
    asyncio.run(po_tools.run_po(rt, Start("", StartMode.RESUME)))
    assert step_roles(rt) == ["architect", "scribe"]
    prompt = script.po_prompts[0]
    assert prompt.startswith(RESUME_NOTE + "\n\nThe runner needs you (sprint 1; 2 steps")
    assert "Sprint 1 is complete" in prompt
    assert len(script.po_prompts) == 1


def test_a_resume_with_a_message_starts_with_the_po(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script, steps=["design"])
    rt.state.po_session = "old"
    add_story(rt)
    asyncio.run(po_tools.run_po(rt, Start("Also X", StartMode.RESUME)))
    assert script.calls[0] == (PO_ROLE, f"{RESUME_NOTE}\n\nNew from the human:\nAlso X")
    assert step_roles(rt) == ["architect", "scribe"]


def test_a_resume_without_a_session_gets_the_kickoff(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script)
    asyncio.run(po_tools.run_po(rt, Start("Redo", StartMode.RESUME)))
    assert "Task from the human:\nRedo" in script.po_prompts[0]


def test_old_answers_are_not_handed_over_on_a_fresh_run(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script, steps=["design"])
    add_story(rt)
    ask_and_answer(rt, stories=())
    assert rt.state.delivered is None
    drive(rt)
    assert rt.state.delivered == ["m1"]
    assert all("The human answered" not in p for p in script.po_prompts)


def test_a_human_message_hands_over_and_is_marked_delivered(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script, steps=["design"])
    rt.state.po_session = "old"
    add_story(rt, status=StoryStatus.ACTIVE)
    rt.state.delivered = []
    ask_and_answer(rt, "Which DB?", ["s1"], "sqlite")
    asyncio.run(po_tools.run_po(rt, Start("", StartMode.RESUME)))
    first = script.po_prompts[0]
    assert first.startswith(RESUME_NOTE) and 'The human answered m1 ("Which DB?"): sqlite' in first
    assert rt.state.delivered == ["m1"]
    assert handover_events(rt)[0].data == {
        "triggers": ["human_message"],
        "stories": ["s1"],
        "steps": 0,
    }
    assert step_roles(rt) == ["architect", "scribe"]


def test_a_stop_during_the_po_turn_ends_the_run(make_runtime) -> None:
    async def stop(rt) -> None:
        rt.config.run_dir.mkdir(parents=True, exist_ok=True)
        (rt.config.run_dir / "stop").write_text("")

    script = Script(po=[stop])
    rt = build(make_runtime, script)
    add_story(rt)
    drive(rt)
    assert step_roles(rt) == [] and len(script.po_prompts) == 1
    assert rt.state.status is RunStatus.IDLE


def test_sprint_end_notice_under_sprint_cadence_ends_the_run(make_runtime) -> None:
    async def finish(rt) -> None:
        await Tools(rt).notify_user({"text": "done", "kind": "sprint-end"})

    script = Script(po=[finish])
    rt = build(make_runtime, script)
    add_story(rt)
    drive(rt)
    assert step_roles(rt) == []
    assert rt.state.status is RunStatus.SPRINT_END


def test_a_limit_in_a_router_step_halts_without_another_po_turn(make_runtime, capsys) -> None:
    script = Script({"architect": [LIMIT]})
    rt = build(make_runtime, script, steps=["design"])
    add_story(rt)
    result = drive(rt)
    assert len(script.po_prompts) == 1 and rt.halted_by is not None
    assert rt.state.status is RunStatus.BLOCKED
    assert handover_events(rt) == []
    assert cli._finish(rt, result) == 75

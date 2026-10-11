"""s19 end to end: the Router drives stories through fake roles; the PO only judges."""

from __future__ import annotations

from typing import Any

from agile_team.gates import StoryStatus
from agile_team.po_tools import Tools

from ..conftest import handoff
from ..pipeline_helpers import (
    PO_ROLE,
    Script,
    add_story,
    ask_and_answer,
    build,
    drive,
    handover_events,
    step_roles,
)


def po_turns(script: Script) -> int:
    return [r for r, _ in script.calls].count(PO_ROLE)


def tool_text(out: dict[str, Any]) -> str:
    return out["content"][0]["text"]


def test_two_stories_advance_with_no_po_turn_between_steps(make_runtime) -> None:
    """Auto-advance: kickoff turn, then one pass to sprint end, then the PO's closing turn."""
    script = Script()
    # No "tests" step: the shared fake runner reads the first story's step to decide red/green.
    rt = build(make_runtime, script, steps=["design", "implement", "review"])
    add_story(rt, "s1")
    add_story(rt, "s2")
    drive(rt)
    one = ["architect", "developer", "code-reviewer", "scribe"]
    assert step_roles(rt) == one + one
    assert po_turns(script) == 2
    assert all(s.status is StoryStatus.DONE for s in rt.state.stories.values())
    assert rt.state.scribe_due == []


def test_open_questions_hand_over_to_the_po(make_runtime) -> None:
    ask = handoff("done", open_questions=["Which DB?"])
    script = Script({"architect": [ask]})
    rt = build(make_runtime, script, steps=["design", "review"])
    add_story(rt)
    drive(rt)
    assert "s1: architect asks: Which DB?" in script.po_prompts[1]
    assert handover_events(rt)[0].data["triggers"] == ["questions"]
    assert rt.state.stories["s1"].hold == "questions"


def test_blocked_hands_over_and_continue_story_resumes_with_the_note(make_runtime) -> None:
    async def release(rt) -> None:
        out = await Tools(rt).continue_story({"story": "s1", "note": "use sqlite"})
        assert "continued" in tool_text(out)

    script = Script({"architect": [handoff("blocked", summary="no db")]}, po=[None, release])
    rt = build(make_runtime, script, steps=["design", "review"])
    add_story(rt)
    drive(rt)
    assert "s1: architect reported blocked: no db" in script.po_prompts[1]
    assert step_roles(rt) == ["architect", "architect", "code-reviewer", "scribe"]
    assert "- From the PO: use sqlite" in script.prompts["architect"][1]
    assert rt.state.stories["s1"].status is StoryStatus.DONE


def test_round_cap_hands_over_and_stops_routing_that_story(make_runtime) -> None:
    script = Script()
    rt = build(make_runtime, script, steps=["implement", "review"], failures=99)
    rt.pipeline.cap = 2
    add_story(rt, "s1", "implement")
    drive(rt)
    assert step_roles(rt) == ["developer", "developer"]
    assert rt.state.stories["s1"].status is StoryStatus.NEEDS_MANAGER
    assert "hit the round cap" in script.po_prompts[1]
    assert handover_events(rt)[0].data["triggers"] == ["round_cap"]


def test_a_human_answer_arriving_mid_run_is_handed_to_the_po(make_runtime) -> None:
    async def human_replies(rt) -> None:
        ask_and_answer(rt, "Which DB?", stories=("s1",), answer="sqlite")

    script = Script({"architect": [human_replies]})
    rt = build(make_runtime, script, steps=["design", "review"])
    add_story(rt)
    drive(rt)
    assert 'The human answered m1 ("Which DB?"): sqlite' in script.po_prompts[1]
    assert handover_events(rt)[0].data["triggers"] == ["human_message"]
    assert rt.state.delivered == ["m1"]
    assert rt.state.stories["s1"].status is StoryStatus.DONE


def test_set_developer_overrides_the_architects_pick(make_runtime) -> None:
    async def choose(rt) -> None:
        tools = Tools(rt)
        assert "set" in tool_text(
            await tools.set_developer({"story": "s1", "role": "developer-db"})
        )
        await tools.continue_story({"story": "s1", "note": ""})

    arch = handoff("done", developer="developer-api")
    stop = handoff("blocked", summary="pause")
    script = Script({"architect": [arch], "unit-tester": [stop]}, po=[None, choose])
    rt = build(make_runtime, script, steps=["design", "tests", "implement", "review"])
    add_story(rt)
    drive(rt)
    assert rt.state.stories["s1"].developer == "developer-api"
    assert rt.state.stories["s1"].po_developer == "developer-db"
    assert "developer-db" in step_roles(rt)
    assert "developer-api" not in step_roles(rt)


def test_the_architects_developer_field_picks_the_implement_role(make_runtime) -> None:
    script = Script({"architect": [handoff("done", developer="developer-cli")]})
    rt = build(make_runtime, script)
    add_story(rt)
    drive(rt)
    assert step_roles(rt) == [
        "architect",
        "unit-tester",
        "developer-cli",
        "code-reviewer",
        "scribe",
    ]


def test_the_scribe_runs_after_done_even_when_the_final_step_held_the_story(make_runtime) -> None:
    """R12: a reviewer that finishes with a question holds a DONE story; the Scribe still runs."""
    ask = handoff("done", open_questions=["Ship it?"])
    script = Script({"code-reviewer": [ask]})
    rt = build(make_runtime, script, steps=["review"])
    add_story(rt, "s1", "review")
    drive(rt)
    assert rt.state.stories["s1"].status is StoryStatus.DONE
    assert "s1: code-reviewer asks: Ship it?" in script.po_prompts[1]
    assert step_roles(rt) == ["code-reviewer", "scribe"]
    assert rt.state.scribe_due == []
    assert "Story s1 is done. Record its decisions as ADRs" in script.prompts["scribe"][0]


def test_the_product_owner_runs_on_sonnet(make_runtime) -> None:
    models: list[str] = []
    script = Script()

    def spy(*, prompt: str, options: Any):
        if options.mcp_servers:
            models.append(options.model)
        return script(prompt=prompt, options=options)

    rt = build(make_runtime, script)
    rt.query_fn = spy
    add_story(rt)
    drive(rt)
    assert models and set(models) == {"sonnet"}

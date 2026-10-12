"""s47 end to end: an answer wakes a waiting run with no PO session."""

from __future__ import annotations

import asyncio

from agile_team import system
from agile_team.po_tools import PoRun, Start
from agile_team.relay import Note

from ..pipeline_helpers import Script, add_story, build, handover_events


def test_an_answer_wakes_the_router_and_the_po_gets_it(make_runtime, monkeypatch) -> None:
    async def ask(rt) -> None:
        rt.relay.post(Note("question", "Which DB?", ["s1"]))

    script = Script(po=[ask])
    rt = build(make_runtime, script, steps=["design"])
    add_story(rt)
    run = PoRun(rt, Start("go"))
    slept: list[float] = []
    seen: list[str | None] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        seen.append(rt.state.status_reason)
        rt.relay.answer("m1", "sqlite")

    monkeypatch.setattr(system, "async_sleep", sleep)
    asyncio.run(run.run())
    assert slept == [5.0]
    assert seen == ["waiting on answers: s1 waits on m1"]
    assert rt.state.status_reason is None
    assert 'The human answered m1 ("Which DB?"): sqlite' in script.po_prompts[1]
    assert ["human_message"] in [e.data["triggers"] for e in handover_events(rt)]

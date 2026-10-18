"""s53 end to end: the PO holds, releases and asks to cancel; the router obeys."""

from __future__ import annotations

import asyncio
import json

from agile_team.dashboard import snapshot
from agile_team.gates import StoryStatus
from agile_team.po_tools import Tools

from ..pipeline_helpers import Script, add_story, build, drive
from .test_priority_e2e import first_steps


async def hold_and_request(rt) -> None:
    tools = Tools(rt)
    await tools.hold_story({"story": "s2", "reason": "wait for s1"})
    await tools.request_cancel({"story": "s3", "reason": "not needed; code stays unmerged"})


def stories(rt):
    for sid in ("s1", "s2", "s3"):
        add_story(rt, sid)


async def human_cancels(rt) -> None:
    """The human answers the cancel question while the run goes on."""
    (q,) = [m for m in rt.relay.messages() if m.kind == "question"]
    assert rt.state.stories["s3"].status is not StoryStatus.CANCELLED
    rt.relay.answer(q.id, "cancel")


def test_hold_cancel_request_and_release_end_to_end(make_runtime) -> None:
    script = Script({"architect": [human_cancels]}, po=[hold_and_request])
    rt = build(make_runtime, script, steps=["design", "review"])
    stories(rt)
    drive(rt)
    assert rt.state.stories["s3"].status is StoryStatus.CANCELLED
    assert "s3" not in rt.state.order and "s3" not in first_steps(rt)
    assert rt.state.stories["s2"].po_hold is not None
    assert "s2" not in first_steps(rt)
    questions = [m for m in rt.relay.messages() if m.kind == "question"]
    assert len(questions) == 1 and questions[0].stories == ["s3"]
    out = asyncio.run(Tools(rt).release_story({"story": "s2", "reason": "s1 done"}))
    assert "released" in json.dumps(out)
    del rt.stop_requested  # the idle stop of the first drive is not the human's stop
    drive(rt)
    assert rt.state.stories["s2"].status is StoryStatus.DONE
    snap = json.loads(json.dumps(snapshot.build(rt.config, rt.book)))
    by_id = {s["id"]: s for s in snap["stories"]}
    assert "cancelled" in json.dumps(by_id["s3"])

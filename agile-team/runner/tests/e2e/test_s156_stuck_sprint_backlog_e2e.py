"""s156 end to end: a stuck Sprint Backlog is reported through the router, tools and CLI."""

from __future__ import annotations

import asyncio
import json

import pytest
from agile_team import cli, sprint_end
from agile_team.gates import StoryState, StoryStatus
from agile_team.handover import Trigger
from agile_team.holds import HoldKind, PoHold
from agile_team.po_tools import Tools
from agile_team.router import Router
from agile_team.state import RunStatus

UB = "until-blocker"


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


def product_backlog(rt, sid: str) -> None:
    rt.state.stories[sid] = StoryState(sid, f"T {sid}", "design", sprint=None)
    rt.state.order.append(sid)


def stuck(make_runtime, cadence: str = UB):
    rt = make_runtime()
    rt.state.cadence, rt.state.sprint = cadence, 1
    rt.state.stories["s2"] = StoryState("s2", "T s2", "design", sprint=1)
    rt.state.stories["s2"].po_hold = PoHold(HoldKind.HOLD, "r")
    rt.state.order = ["s2"]
    product_backlog(rt, "s3")
    rt.save()
    return rt


def test_ac1_stuck_sprint_backlog_gives_reasons_not_product_backlog(make_runtime) -> None:
    """s156/AC1: reasons per Sprint Backlog story, no Product Backlog story offered."""
    found = Router(stuck(make_runtime))._idle()
    assert found.kinds == [Trigger.SPRINT_BACKLOG_STUCK]
    assert found.lines[1].startswith("s2 at design: ")
    assert not any("s3" in line or "add_to_sprint" in line for line in found.lines)


def test_ac2_ac5_blocks_after_three_and_add_to_sprint_still_works(make_runtime, capsys) -> None:
    """s156/AC2, AC5: wait with the reason after 3 hand-overs (I4); add_to_sprint is deliberate."""
    rt = stuck(make_runtime)
    for _ in range(3):
        assert Router(rt)._idle().kinds == [Trigger.SPRINT_BACKLOG_STUCK]
    assert Router(rt)._idle().kinds == []
    assert rt.state.status is RunStatus.RUNNING  # s159 I4: waiting on the human ends nothing
    assert "the Sprint Backlog is stuck" in rt.state.status_reason
    assert rt.relay.messages()[-1].kind == "blocked"
    assert cli.main(["--repo", str(rt.config.repo), "status"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] != "blocked"  # s159 I4
    out = call(Tools(rt).add_to_sprint({"stories": ["s3"], "reason": "deliberate"}))
    assert out.get("status") != "refused" and rt.state.stories["s3"].sprint == 1


@pytest.mark.parametrize("kind", ["done", "blocked"])
def test_ac3_notify_refused_only_for_a_movable_sprint_backlog(make_runtime, kind) -> None:
    """s156/AC3: ready Product Backlog stories never refuse; a movable story does."""
    assert "id" in call(Tools(stuck(make_runtime)).notify_user({"kind": kind, "text": "x"}))
    rt = make_runtime()
    rt.state.cadence, rt.state.sprint = UB, 1
    rt.state.stories["s1"] = StoryState("s1", "T", "design", sprint=1)
    rt.state.order = ["s1"]
    out = call(Tools(rt).notify_user({"kind": kind, "text": "x"}))
    assert out["status"] == "refused"


def test_ac4_ac6_next_sprint_lists_product_backlog(make_runtime) -> None:
    """s156/AC4, AC6: at a sprint end the ready Product Backlog is still listed."""
    rt = make_runtime()
    rt.state.cadence, rt.state.sprint = UB, 1
    rt.state.stories["s1"] = StoryState("s1", "T", "done", sprint=1, status=StoryStatus.DONE)
    rt.state.order = ["s1"]
    product_backlog(rt, "s3")
    found = Router(rt)._idle()
    assert found.kinds == [Trigger.NEXT_SPRINT]
    assert sprint_end.READY_HEAD in found.lines and "- s3" in " ".join(found.lines)
    assert "ready_backlog" not in " ".join(found.lines)

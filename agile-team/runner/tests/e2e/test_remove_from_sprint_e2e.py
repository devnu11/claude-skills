"""s189 end to end: a story that crashed before its first commit leaves the running sprint."""

from __future__ import annotations

import json

from agile_team import sprint_end, system
from agile_team.cli import status_report
from agile_team.gates import StoryStatus
from agile_team.po_tools import Tools

from ..test_po_tools import call
from ..test_s189_remove_from_sprint import CRASH, REASON, leave, setup


def sprints(rt) -> dict:
    return {k: v["sprint"] for k, v in status_report(rt.config)["stories"].items()}


def test_ac1_the_crashed_story_goes_to_the_product_backlog(make_runtime) -> None:
    rt, t = setup(make_runtime)
    print("BEFORE", json.dumps(sprints(rt)))
    out = leave(t)
    print("RESULT", json.dumps(out))
    print("AFTER", json.dumps(sprints(rt)))
    assert sprints(rt) == {"s1": None, "s2": 1}
    s = rt.state.stories["s1"]
    assert s.step == "design" and s.hold is None and rt.state.order == ["s1", "s2"]
    assert rt.state.sprint == 1 and rt.state.goal == "the goal"
    text = system.read_text(rt.config.stories_dir / "s1.md")
    print("STORY FILE TAIL", text[text.index("## Left the sprint") :])
    assert REASON in text and CRASH in text
    ev = [e for e in rt.events.events() if e.kind == "story-admin"]
    print("EVENT", ev[-1].to_json() if hasattr(ev[-1], "to_json") else ev[-1])
    assert REASON in str(ev[-1]) and CRASH in str(ev[-1])


def test_ac2_the_sprint_can_end(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.stories["s2"].status = StoryStatus.DONE
    rt.save()
    end = {"kind": "sprint-end", "text": "done"}
    assert call(t.notify_user(end))["status"] == "refused"
    leave(t)
    assert sprint_end.end_refusal(rt.state) is None
    assert call(Tools(rt).notify_user(end)).get("status") != "refused"


def test_ac3_work_is_refused_pointing_at_revert_story(make_runtime) -> None:
    rt, t = setup(make_runtime)
    rt.state.stories["s1"].commit = "1" * 40
    rt.save()
    out = leave(t)
    print("REFUSAL", json.dumps(out))
    assert out["status"] == "refused" and "revert_story" in out["reason"]
    assert rt.state.stories["s1"].sprint == 1 and rt.state.stories["s1"].hold == CRASH

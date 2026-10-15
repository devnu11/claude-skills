"""s128 AC1: with cadence until-blocker a sprint end hands over the next sprint (K1-K6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agile_team import cli, po_tools, sprint_end
from agile_team.boundary import PrMode, StackEntry
from agile_team.gates import StoryState, StoryStatus
from agile_team.handover import QUIET_AFTER_PO, Trigger
from agile_team.holds import HoldKind, PoHold
from agile_team.po_tools import SCHEMAS, Tools
from agile_team.router import Router
from agile_team.state import RunState, RunStatus

from .conftest import FakeQuery
from .fake_system import Done, FakeSystem
from .test_cli import any_tool, start_args
from .test_po_tools import call, open_stories, snapshot

UB = "until-blocker"


@pytest.fixture(autouse=True)
def tracked(configured, fake: FakeSystem) -> None:
    fake.track()
    fake.reply(("git", "remote", "get-url"), Done(2))


def backlog(rt, sid: str, **kw) -> None:
    rt.state.stories[sid] = StoryState(sid, f"Title {sid}", "design", sprint=None, **kw)
    rt.state.order.append(sid)


def ended_sprint(make_runtime, cadence: str = UB):
    """Sprint 1 is complete (s1 done, no boundary pending); s3 waits in the backlog."""
    rt = make_runtime()
    rt.state.cadence, rt.state.sprint = cadence, 1
    rt.state.stories["s1"] = StoryState("s1", "Title s1", "done", sprint=1, status=StoryStatus.DONE)
    rt.state.order = ["s1"]
    backlog(rt, "s3")
    return rt


def stuck_sprint(make_runtime, cadence: str = UB):
    """Sprint 1 holds s2 on a PO hold (stuck); s3 is ready in the backlog."""
    rt = ended_sprint(make_runtime, cadence)
    rt.state.stories["s1"].status = StoryStatus.DONE
    rt.state.stories["s2"] = StoryState("s2", "Title s2", "design", sprint=1)
    rt.state.stories["s2"].po_hold = PoHold(HoldKind.HOLD, "r")
    rt.state.order.insert(1, "s2")
    return rt


# ----- K2: the hand-over ----------------------------------------------------------------


def test_the_sprint_end_hands_over_the_next_sprint(make_runtime) -> None:
    rt = ended_sprint(make_runtime)
    found = Router(rt)._idle()
    assert found.kinds == [Trigger.NEXT_SPRINT] and found.stories == []
    assert not found.quiet()
    assert found.lines[0].startswith("Sprint 1 is complete")
    assert found.lines[-1] == sprint_end.NEXT_SPRINT_ADVICE
    assert sprint_end.NEXT_SPRINT_LEAD in found.lines and "- s3: Title s3" in found.lines
    assert sprint_end.READY_HEAD in found.lines


def test_the_review_line_stays_in_the_hand_over(make_runtime) -> None:
    rt = ended_sprint(make_runtime)
    rt.state.upstream.report = "reports/r1.md"
    assert "Review: reports/r1.md" in Router(rt)._idle().lines


def test_without_a_ready_story_it_is_the_plain_sprint_end(make_runtime) -> None:
    rt = ended_sprint(make_runtime)
    rt.state.stories["s3"].po_hold = PoHold(HoldKind.HOLD, "r")
    assert Router(rt)._idle().kinds == [Trigger.SPRINT_END]


def test_under_sprint_cadence_it_is_always_the_plain_sprint_end(make_runtime) -> None:
    rt = ended_sprint(make_runtime, "sprint")
    assert Router(rt)._idle().kinds == [Trigger.SPRINT_END]
    assert rt.state.keep_going_asks == 0


def test_the_trigger_is_not_quiet_after_the_po() -> None:
    assert Trigger.NEXT_SPRINT == "next_sprint"
    assert Trigger.NEXT_SPRINT not in QUIET_AFTER_PO


def test_next_sprint_lines_are_the_lead_the_list_and_the_advice() -> None:
    stories = {"s3": StoryState("s3", "Title s3", "design", sprint=None)}
    lines = sprint_end.next_sprint_lines(stories, ["s3"])
    assert lines == [
        sprint_end.NEXT_SPRINT_LEAD,
        *sprint_end._ready_list(stories, ["s3"]),
        sprint_end.NEXT_SPRINT_ADVICE,
    ]


# ----- K4: the ask cap ------------------------------------------------------------------------


def test_a_turn_that_starts_no_sprint_gets_the_hand_over_again_up_to_the_cap(make_runtime) -> None:
    rt = ended_sprint(make_runtime)
    for asks in (1, 2, 3):
        assert Router(rt)._idle().kinds == [Trigger.NEXT_SPRINT]
        assert rt.state.keep_going_asks == asks
    assert sprint_end.KEEP_GOING_CAP == 3
    last = Router(rt)._idle()
    text = sprint_end.KEEP_GOING_STUCK.format(count=3, ids="s3")
    assert (last.kinds, last.lines, last.stories) == ([], [], [])
    assert rt.state.status is RunStatus.BLOCKED and rt.state.status_reason == text
    [note] = rt.relay.messages()
    assert (note.kind, note.text) == ("blocked", text)
    assert json.loads(rt.state.to_json())["keep_going_asks"] == 3


def test_start_sprint_and_add_to_sprint_reset_the_count() -> None:
    state = RunState(keep_going_asks=2, sprint=1)
    state.stories["s3"] = StoryState("s3", "t", "design", sprint=None)
    state.add_to_sprint(["s3"])
    assert state.keep_going_asks == 0
    state.keep_going_asks = 2
    state.begin_sprint(["s3"])
    assert state.keep_going_asks == 0


def test_an_old_state_loads_the_new_fields_empty() -> None:
    old = json.loads(RunState().to_json())
    old.pop("keep_going_asks", None)
    old.pop("repin", None)
    loaded = RunState.from_json(json.dumps(old))
    assert (loaded.keep_going_asks, loaded.repin) == (0, "")


# ----- K5: no early end -----------------------------------------------------------------------


def test_keep_going_refusal() -> None:
    state = RunState(cadence=UB, sprint=1)
    assert sprint_end.keep_going_refusal(state, set()) is None
    state.stories["s3"] = StoryState("s3", "t", "design", sprint=None)
    assert sprint_end.keep_going_refusal(state, set()) is None
    state.stories["s3"].sprint = 1
    want = sprint_end.KEEP_GOING_REFUSED.format(ids="s3")
    assert sprint_end.keep_going_refusal(state, set()) == want
    assert sprint_end.keep_going_refusal(state, {"s3"}) is None
    state.cadence = "sprint"
    assert sprint_end.keep_going_refusal(state, set()) is None


@pytest.mark.parametrize("kind", ["done", "blocked"])
def test_done_and_blocked_are_refused_while_sprint_stories_can_move(
    make_runtime, kind: str
) -> None:
    rt = ended_sprint(make_runtime)
    rt.state.stories["s3"].sprint = 1
    rt.save()
    before, messages = snapshot(rt), len(rt.relay.messages())
    out = call(Tools(rt).notify_user({"kind": kind, "text": "bye"}))
    want = sprint_end.KEEP_GOING_REFUSED.format(ids="s3")
    assert out == {"status": "refused", "reason": want}
    assert len(rt.relay.messages()) == messages and snapshot(rt) == before


@pytest.mark.parametrize("kind", ["done", "blocked"])
def test_done_and_blocked_are_accepted_when_nothing_in_the_sprint_moves(
    make_runtime, kind: str
) -> None:
    rt = ended_sprint(make_runtime)
    del rt.state.stories["s3"]
    assert "id" in call(Tools(rt).notify_user({"kind": kind, "text": "bye"}))
    assert rt.state.status is RunStatus(kind)


@pytest.mark.parametrize("kind", ["done", "blocked"])
def test_done_and_blocked_are_always_accepted_under_sprint(make_runtime, kind: str) -> None:
    rt = ended_sprint(make_runtime, "sprint")
    assert "id" in call(Tools(rt).notify_user({"kind": kind, "text": "bye"}))


def test_the_refusals_are_wired_to_the_kinds() -> None:
    assert po_tools.KIND_REFUSALS["done"] is po_tools.KIND_REFUSALS["blocked"]
    assert "sprint-end" in po_tools.KIND_REFUSALS


# ----- K6: nothing else gates the next sprint -------------------------------------------------


def test_start_sprint_ignores_an_open_unmerged_pr(make_runtime) -> None:
    rt = make_runtime()
    t = Tools(rt)
    open_stories(t, "s1", "s2")
    assert call(t.start_sprint({"goal": "G", "stories": ["s1"]}))["sprint"] == 1
    rt.state.boundary = None
    rt.state.stories["s1"].status = StoryStatus.DONE
    rt.state.upstream.stack = [
        StackEntry(1, "team/s1", "a" * 40, "b" * 40, pr=7, url="http://pr/7", mode=PrMode.DRAFT)
    ]
    assert call(t.start_sprint({"goal": "two", "stories": ["s2"]}))["sprint"] == 2


# ----- K1: a resume keeps the cadence ---------------------------------------------------------


def stored_cadence(configured: Path) -> str:
    return json.loads((configured / ".team/run/state.json").read_text())["cadence"]


def test_a_resume_keeps_the_stored_cadence(configured: Path, key_home: Path, fake: FakeSystem):
    any_tool(fake)
    first = start_args(configured, key_home, "--task", "go", "--cadence", UB)
    assert cli.cmd_start(first, FakeQuery()) == 0
    assert cli.cmd_start(start_args(configured, key_home, "--resume"), FakeQuery()) == 0
    assert json.loads(fake.text_of(configured / ".team/run/state.json"))["cadence"] == UB


def test_a_resume_with_a_cadence_replaces_it(configured: Path, key_home: Path, fake: FakeSystem):
    any_tool(fake)
    cli.cmd_start(start_args(configured, key_home, "--task", "go", "--cadence", UB), FakeQuery())
    cli.cmd_start(start_args(configured, key_home, "--resume", "--cadence", "sprint"), FakeQuery())
    assert json.loads(fake.text_of(configured / ".team/run/state.json"))["cadence"] == "sprint"


def test_a_fresh_start_uses_the_config_cadence(configured: Path, key_home: Path, fake: FakeSystem):
    any_tool(fake)
    cli.cmd_start(start_args(configured, key_home, "--task", "go"), FakeQuery())
    assert json.loads(fake.text_of(configured / ".team/run/state.json"))["cadence"] == "sprint"


def test_the_schema_text_names_the_refusal() -> None:
    assert "done" in SCHEMAS["notify_user"][0]

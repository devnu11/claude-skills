"""s156: a stuck Sprint Backlog is reported, not refilled from the Product Backlog (S1-S11)."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from agile_team import gates, handover, po_tools, reverts, router, runner_tools, sprint_end, system
from agile_team.gates import StoryState, StoryStatus
from agile_team.handover import HANDOVERS, Trigger
from agile_team.holds import HoldKind, PoHold
from agile_team.po_tools import SCHEMAS, Tools
from agile_team.relay import Note
from agile_team.router import Router
from agile_team.state import RunState, RunStatus

from .fake_system import Done, FakeSystem
from .test_po_tools import call, snapshot

UB = "until-blocker"
RESETTING = [
    "continue_story",
    "release_story",
    "run_role",
    "revert_story",
    "request_cancel",
    "request_story",
    "pass_tests",
]
ROLE = Path(__file__).parent.parent / "agile_team" / "roles" / "product-owner.md"


@pytest.fixture(autouse=True)
def tracked(configured, fake: FakeSystem) -> None:
    fake.track()
    fake.reply(("git", "remote", "get-url"), Done(2))


def product_backlog(rt, sid: str, **kw) -> None:
    rt.state.stories[sid] = StoryState(sid, f"Title {sid}", "design", sprint=None, **kw)
    rt.state.order.append(sid)


def stuck_sprint(make_runtime, cadence: str = "sprint"):
    """Sprint 1: s2 on a PO hold, s4 waits on s9 (Product Backlog); s3 is ready in it."""
    rt = make_runtime()
    rt.state.cadence, rt.state.sprint = cadence, 1
    rt.state.stories["s2"] = StoryState("s2", "Title s2", "design", sprint=1)
    rt.state.stories["s2"].po_hold = PoHold(HoldKind.HOLD, "r")
    rt.state.stories["s4"] = StoryState("s4", "Title s4", "design", sprint=1, depends_on=["s9"])
    rt.state.order = ["s2", "s4"]
    product_backlog(rt, "s9")
    product_backlog(rt, "s3")
    return rt


def movable_sprint(make_runtime, cadence: str = UB):
    rt = make_runtime()
    rt.state.cadence, rt.state.sprint = cadence, 1
    rt.state.stories["s1"] = StoryState("s1", "Title s1", "design", sprint=1)
    rt.state.order = ["s1"]
    product_backlog(rt, "s3")
    return rt


def words(*texts: str) -> list[str]:
    """Every 'backlog' in ``texts`` with the 6 characters before it, lowercased."""
    found = []
    for text in texts:
        found += [m.group(0).lower() for m in re.finditer(r".{0,8}backlog", text, re.I | re.S)]
    return found


def named(found: list[str]) -> bool:
    return all(w.endswith(("product backlog", "sprint backlog", "product_backlog",
                           "sprint_backlog")) for w in found)  # fmt: skip


# ----- AC1 ---------------------------------------------------------------------------------


def test_ac1_a_stuck_sprint_backlog_hands_over_reasons_and_no_product_backlog(make_runtime) -> None:
    rt = stuck_sprint(make_runtime)
    found = Router(rt)._idle()
    assert found.kinds == [Trigger.SPRINT_BACKLOG_STUCK] and found.stories == ["s2", "s4"]
    assert found.lines[0] == sprint_end.SPRINT_STUCK_LEAD.format(sprint=1)
    assert found.lines[1].startswith("s2 at design: ")
    assert found.lines[2] == "s4 at design: waiting on s9"
    assert found.lines[-1] == sprint_end.SPRINT_STUCK_ADVICE.format(count=1, cap=3)
    assert len(found.lines) == 4
    assert not any("s3" in line or sprint_end.READY_HEAD in line for line in found.lines)
    assert not found.quiet()
    assert Trigger.SPRINT_BACKLOG_STUCK == "sprint_backlog_stuck"
    assert Trigger.SPRINT_BACKLOG_STUCK not in handover.QUIET_AFTER_PO
    assert not hasattr(Trigger, "READY_BACKLOG")
    assert not hasattr(sprint_end, "ready_lines") and not hasattr(sprint_end, "READY_ADVICE")
    assert not hasattr(RunState(), "offered")


def test_ac1_an_open_question_makes_the_router_wait(make_runtime) -> None:
    rt = stuck_sprint(make_runtime)
    rt.relay.post(Note("question", "which?"))
    assert Router(rt)._idle() is None
    assert rt.state.stuck_asks == 0


def test_ac1_an_empty_sprint_stays_the_quiet_stall(make_runtime) -> None:
    rt = make_runtime()
    rt.state.sprint = 1
    assert Router(rt)._idle().kinds == [Trigger.STALLED]


# ----- AC2 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("cadence", ["sprint", UB])
def test_ac2_three_hand_overs_then_the_run_is_blocked(make_runtime, cadence: str) -> None:
    rt = stuck_sprint(make_runtime, cadence)
    for count in (1, 2, 3):
        found = Router(rt)._idle()
        assert found.kinds == [Trigger.SPRINT_BACKLOG_STUCK]
        assert found.lines[-1] == sprint_end.SPRINT_STUCK_ADVICE.format(count=count, cap=3)
        assert rt.state.stuck_asks == count
    last = Router(rt)._idle()
    assert (last.kinds, last.lines, last.stories) == ([], [], [])
    assert rt.state.status is RunStatus.RUNNING  # I4: it waits on the human
    assert "the Sprint Backlog is stuck" in rt.state.status_reason
    assert "s4 at design: waiting on s9" in rt.state.status_reason
    assert sprint_end.SPRINT_STUCK_CAP == 3
    [note] = rt.relay.messages()
    assert (note.kind, note.text) == ("blocked", rt.state.status_reason)
    assert json.loads(rt.state.to_json())["stuck_asks"] == 3


def test_ac2_stuck_blocked_text_names_each_story(make_runtime) -> None:
    state = RunState(sprint=2, stuck_asks=3)
    text = sprint_end.format_stuck_blocked_text(state, ["a: x", "b: y"])
    assert "Sprint 2" in text and "a: x; b: y" in text and "the Sprint Backlog is stuck" in text


def held_for_continue(make_runtime):
    rt = stuck_sprint(make_runtime)
    rt.state.stories["s2"].po_hold = None
    rt.state.stories["s2"].hold = "stopped"
    rt.state.stuck_asks = 2
    rt.save()
    return rt


def run_tool(rt, name: str, args: dict) -> dict:
    return asyncio.run(Tools(rt).noted(name)(args))


def test_ac2_a_continue_resets_the_count_but_a_refused_one_does_not(make_runtime) -> None:
    rt = held_for_continue(make_runtime)
    refused = run_tool(rt, "continue_story", {"story": "s99"})
    assert runner_tools.is_refused(refused) and rt.state.stuck_asks == 2
    done = run_tool(rt, "continue_story", {"story": "s2"})
    assert not runner_tools.is_refused(done) and rt.state.stuck_asks == 0


def test_ac2_ask_user_hold_story_and_notify_do_not_reset(make_runtime) -> None:
    rt = held_for_continue(make_runtime)
    run_tool(rt, "ask_user", {"text": "q?", "stories": ["s2"]})
    run_tool(rt, "hold_story", {"story": "s4", "reason": "r"})
    run_tool(rt, "notify_user", {"text": "fyi", "kind": "update"})
    assert rt.state.stuck_asks == 2


def test_ac2_the_resetting_tools_are_the_listed_ones() -> None:
    assert frozenset({
        "continue_story", "release_story", "run_role", "revert_story",
        "request_cancel", "request_story", "pass_tests",
    }) == po_tools.STUCK_RESETS  # fmt: skip


@pytest.mark.parametrize("name", RESETTING)
def test_ac2_each_resetting_tool_clears_the_count(make_runtime, monkeypatch, name: str) -> None:
    rt = held_for_continue(make_runtime)

    async def fine(_self, _args):
        return runner_tools.text_result({"status": "ok"})

    monkeypatch.setattr(Tools, po_tools.METHODS.get(name, name), fine)
    asyncio.run(Tools(rt).noted(name)({}))
    assert rt.state.stuck_asks == 0
    rt.state.stuck_asks = 2

    async def no(_self, _args):
        return runner_tools.text_result({"status": "refused", "reason": "x"})

    monkeypatch.setattr(Tools, po_tools.METHODS.get(name, name), no)
    asyncio.run(Tools(rt).noted(name)({}))
    assert rt.state.stuck_asks == 2


def test_ac2_is_refused_reads_the_json_status() -> None:
    assert runner_tools.is_refused(runner_tools.text_result({"status": "refused"}))
    assert not runner_tools.is_refused(runner_tools.text_result({"status": "ok"}))
    assert not runner_tools.is_refused(runner_tools.text_result([1]))
    assert not runner_tools.is_refused({"content": [{"type": "text", "text": "not json"}]})


def test_ac2_a_step_resets_the_count(make_runtime, monkeypatch) -> None:
    rt = stuck_sprint(make_runtime)
    rt.state.stuck_asks = 2

    async def report(_self, _work):
        return {"status": "done", "summary": "x"}

    monkeypatch.setattr(Router, "_dispatch", report)
    asyncio.run(Router(rt)._step(SimpleNamespace(story=None)))
    assert rt.state.stuck_asks == 0


def test_ac2_sprint_changes_reset_and_old_states_load() -> None:
    state = RunState(stuck_asks=2, sprint=1)
    state.stories["s3"] = StoryState("s3", "t", "design", sprint=None)
    state.add_to_sprint(["s3"])
    assert state.stuck_asks == 0
    state.stuck_asks = 2
    state.begin_sprint(["s3"])
    assert state.stuck_asks == 0
    state.stuck_asks = 2
    state.clear_stuck()
    assert RunState.from_json(state.to_json()).stuck_asks == 0
    old = json.loads(RunState(stuck_asks=1).to_json())
    assert RunState.from_json(json.dumps(old)).stuck_asks == 1
    old.pop("stuck_asks")
    old["offered"] = ["s2", "s3"]
    assert RunState.from_json(json.dumps(old)).stuck_asks == 0


# ----- AC3 ---------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["done", "blocked"])
def test_ac3_a_movable_sprint_backlog_story_refuses_done_and_blocked(make_runtime, kind) -> None:
    rt = movable_sprint(make_runtime)
    rt.save()
    before, messages = snapshot(rt), len(rt.relay.messages())
    out = call(Tools(rt).notify_user({"kind": kind, "text": "bye"}))
    assert out == {"status": "refused", "reason": sprint_end.KEEP_GOING_REFUSED.format(ids="s1")}
    assert len(rt.relay.messages()) == messages and snapshot(rt) == before


@pytest.mark.parametrize("kind", ["done", "blocked"])
def test_ac3_a_stuck_sprint_backlog_accepts_it_despite_ready_stories(make_runtime, kind) -> None:
    rt = stuck_sprint(make_runtime, UB)
    assert "id" in call(Tools(rt).notify_user({"kind": kind, "text": "bye"}))


@pytest.mark.parametrize("kind", ["done", "blocked"])
def test_ac3_a_story_waiting_on_a_question_cannot_move(make_runtime, kind) -> None:
    rt = movable_sprint(make_runtime)
    rt.relay.post(Note("question", "which?", ["s1"]))
    assert "id" in call(Tools(rt).notify_user({"kind": kind, "text": "bye"}))


@pytest.mark.parametrize("kind", ["done", "blocked"])
def test_ac3_sprint_cadence_never_refuses(make_runtime, kind) -> None:
    rt = movable_sprint(make_runtime, "sprint")
    assert "id" in call(Tools(rt).notify_user({"kind": kind, "text": "bye"}))


def test_ac3_one_can_move_rule(make_runtime) -> None:
    rt = movable_sprint(make_runtime)
    s1 = rt.state.stories["s1"]
    assert sprint_end.can_move(s1, rt.state)
    assert sprint_end.list_movable_sprint_backlog(rt.state, set()) == ["s1"]
    assert sprint_end.list_movable_sprint_backlog(rt.state, {"s1"}) == []
    assert not sprint_end.can_move(rt.state.stories["s3"], rt.state)
    s1.hold = "h"
    assert not sprint_end.can_move(s1, rt.state)
    s1.hold, s1.status = None, StoryStatus.BLOCKED
    assert not sprint_end.can_move(s1, rt.state)
    assert sprint_end.keep_going_refusal(rt.state, set()) is None


@pytest.mark.parametrize("cadence", ["sprint", UB])
def test_the_waiting_run_posts_the_stuck_note_once_i4(make_runtime, cadence: str) -> None:
    """AC11.3: the run keeps polling while it waits, so the same note must not repeat each poll."""
    rt = stuck_sprint(make_runtime, cadence)
    for _ in range(sprint_end.SPRINT_STUCK_CAP + 3):
        Router(rt)._idle()
    assert len([m for m in rt.relay.messages() if m.kind == "blocked"]) == 1
    assert rt.state.status == RunStatus.RUNNING
    assert (rt.state.status_reason or "").startswith("Sprint 1: the Sprint Backlog is stuck")


# ----- AC4 ---------------------------------------------------------------------------------


def test_ac4_the_next_sprint_hand_over_lists_ready_product_backlog_stories(make_runtime) -> None:
    rt = make_runtime()
    rt.state.cadence, rt.state.sprint = UB, 1
    rt.state.stories["s1"] = StoryState("s1", "T1", "done", sprint=1, status=StoryStatus.DONE)
    rt.state.order = ["s1"]
    for n in range(3, 9):
        product_backlog(rt, f"s{n}")
    found = Router(rt)._idle()
    assert found.kinds == [Trigger.NEXT_SPRINT]
    assert sprint_end.NEXT_SPRINT_LEAD in found.lines and sprint_end.READY_HEAD in found.lines
    assert len([x for x in found.lines if x.startswith("- s")]) == 5
    assert sprint_end.READY_MORE.format(count=1) in found.lines
    assert found.lines[-1] == sprint_end.NEXT_SPRINT_ADVICE
    for _ in range(2):
        assert Router(rt)._idle().kinds == [Trigger.NEXT_SPRINT]
    assert Router(rt)._idle().kinds == []
    assert rt.state.status is RunStatus.RUNNING  # I4: it waits on the human
    ids = sprint_end.ids_text(["s3", "s4", "s5", "s6", "s7", "s8"])
    assert rt.state.status_reason == sprint_end.KEEP_GOING_STUCK.format(count=3, ids=ids)


def test_ac4_ready_product_backlog_selects_in_queue_order(make_runtime) -> None:
    rt = make_runtime()
    product_backlog(rt, "s3")
    product_backlog(rt, "s4", depends_on=["s9"])
    product_backlog(rt, "s5", hold="stopped")
    product_backlog(rt, "s6", po_hold=PoHold(HoldKind.HOLD, "r"))
    product_backlog(rt, "s7", status=StoryStatus.CANCELLED)
    queue = rt.priority().queue(rt.state.stories.values())
    assert sprint_end.select_ready_product_backlog(rt.state.stories, queue) == ["s3"]
    assert not hasattr(sprint_end, "ready_backlog")


# ----- AC5 ---------------------------------------------------------------------------------


def test_ac5_add_to_sprint_still_works_with_a_reason(make_runtime) -> None:
    rt = stuck_sprint(make_runtime)
    rt.state.stuck_asks = 2
    rt.save()
    out = call(Tools(rt).add_to_sprint({"stories": ["s3"], "reason": "deliberate"}))
    assert out.get("status") != "refused" and rt.state.stories["s3"].sprint == 1
    assert rt.state.stuck_asks == 0
    again = call(Tools(rt).add_to_sprint({"stories": ["s9"]}))
    assert again["status"] == "refused"


def section(text: str, heading: str) -> str:
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def test_ac5_nothing_suggests_add_to_sprint_for_a_stuck_sprint_backlog(make_runtime) -> None:
    consts = [v for k, v in vars(sprint_end).items() if k.isupper() and isinstance(v, str)]
    assert not [c for c in consts if "add_to_sprint" in c]
    rt = stuck_sprint(make_runtime)
    assert not any("add_to_sprint" in line for line in Router(rt)._idle().lines)
    lines = [line for rule in HANDOVERS for line in vars(rule).values() if isinstance(line, str)]
    assert not [x for x in lines if "add_to_sprint" in x and "stuck" in x.lower()]
    role = system.read_text(ROLE)
    assert "add_to_sprint" not in section(role, "\n## Cadence")
    assert not [x for x in role.splitlines() if "stuck" in x.lower() and "add_to_sprint" in x]
    assert "Sprint Backlog stuck" in role


# ----- AC6 ---------------------------------------------------------------------------------


def test_ac6_no_plain_backlog_in_names_and_texts(make_runtime) -> None:
    values = [t.value for t in Trigger]
    assert named(words(*values))
    consts = [v for k, v in vars(sprint_end).items() if isinstance(v, str)]
    assert named(words(*consts, *[k for k in vars(sprint_end) if not k.startswith("__")]))
    assert named(words(*[str(x) for rule in HANDOVERS for x in vars(rule).values()]))
    assert named(words(reverts.NOTICE, po_tools.DASHBOARD_REASON, po_tools.RESTART_NEEDS_REASON))
    assert named(words(*[desc for desc, _params in SCHEMAS.values()]))
    story = StoryState("s5", "t", "design", sprint=None)
    assert "Product Backlog" in gates._product_backlog_refusal(story)
    assert named(words(gates._product_backlog_refusal(story)))


def test_ac6_the_empty_sprint_lists_the_product_backlog(make_runtime) -> None:
    rt = make_runtime()
    product_backlog(rt, "s9")
    rt.state.stories["s8"] = StoryState("s8", "t", "design", sprint=1, status=StoryStatus.DONE)
    rt.state.sprint = 2
    lines = Router(rt)._idle().lines
    assert lines[-1] == "Product Backlog: s9"
    assert not hasattr(router, "_in_backlog") and hasattr(router, "_is_in_product_backlog")

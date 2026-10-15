"""Tool-call spans through the pulse, step-end and po-turn events (s98, TC3-TC5, TC11-TC14)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from agile_team import live, system
from agile_team import tool_calls as tc
from agile_team.dashboard.step_times import Mark
from agile_team.events import Event, EventKind
from agile_team.po_tools import Start, StartMode
from agile_team.providers import Billing
from agile_team.salvage import Cause
from claude_agent_sdk import AssistantMessage, ToolResultBlock, ToolUseBlock, UserMessage

from .clock import about
from .conftest import FakeQuery
from .fake_system import FakeSystem
from .test_halt import PoCallingRole, RaisingQuery, Router, limit_error
from .test_s9 import open_story, run_step

RUN_DIR = Path("/fake/run")
TOOLS_FILE = RUN_DIR / tc.TOOLS
WHO = live.Who("developer", "s1", "implement", "sonnet", Billing.REPORTED)
PO = live.Who("product-owner", None, None, "opus", Billing.REPORTED)
SPLIT_KEYS = {"opened_at", "tool_s", "model_s", "waiting_s", "rate"}


def pulse_of(fake: FakeSystem) -> live.Pulse:
    fake.make_dirs(RUN_DIR)
    pulse = live.Pulse(RUN_DIR, 20.0)
    pulse.write = lambda: None  # type: ignore[method-assign]
    return pulse


def asks(uid: str, name: str = "Bash", **tool_input: Any) -> AssistantMessage:
    block = ToolUseBlock(id=uid, name=name, input=tool_input)
    return AssistantMessage(content=[block], model="m", usage={}, message_id=f"m-{uid}")


def answers(uid: str) -> UserMessage:
    return UserMessage(content=[ToolResultBlock(tool_use_id=uid, content="ok")])


def lines() -> list[dict[str, Any]]:
    try:
        text = system.read_text(TOOLS_FILE)
    except OSError:
        return []
    return [json.loads(x) for x in text.splitlines()]


def test_a_span_is_written_on_the_result_not_on_the_use(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    meter = pulse.open(WHO)
    opened = fake.clock
    meter.take(asks("u1", command="ls", description="list"))
    assert lines() == []
    fake.clock += 3.0
    meter.take(answers("u1"))
    (row,) = lines()
    assert row["seconds"] == about(3.0) and row["status"] == "ok" and row["label"] == "Dev: list"
    assert (row["role"], row["story"], row["step"], row["opened_at"]) == (
        "developer", "s1", "implement", opened,
    )  # fmt: skip
    assert row["at"] == opened and row["ended_at"] == opened + 3.0


def test_a_po_span_carries_the_po_step(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    meter = pulse.open(PO)
    meter.take(asks("u1", "mcp__team__run_role", role="architect"))
    meter.take(answers("u1"))
    (row,) = lines()
    assert row["role"] == "product-owner" and row["story"] is None
    assert row["step"] == "po-session" and row["label"] == "po.run_role"
    assert row["detail"] == "architect"


def test_closing_a_meter_writes_open_calls_as_unfinished(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    meter = pulse.open(WHO)
    meter.take(asks("u1"))
    fake.clock += 4.0
    pulse.close(meter)
    (row,) = lines()
    assert row["status"] == "unfinished" and row["seconds"] == about(4.0)
    pulse.close(meter)
    assert len(lines()) == 1


def test_the_time_split_has_the_four_keys(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    meter = pulse.open(WHO)
    fake.clock += 10.0
    meter.take(asks("u1"))
    fake.clock += 3.0
    meter.take(answers("u1"))
    fake.clock += 2.0
    pulse.close(meter)
    split = meter.time_split()
    assert set(split) == SPLIT_KEYS
    assert (split["tool_s"], split["model_s"], split["waiting_s"]) == (3.0, 12.0, 0.0)
    assert split["opened_at"] == meter.reading.started_at


def test_awake_seconds_ignore_a_faked_sleep_on_posix(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    meter = pulse.open(WHO)
    meter.take(asks("u1"))
    fake.doze(600.0)
    fake.clock += 2.0
    pulse.close(meter)
    assert lines()[0]["seconds"] == about(2.0)


def test_awake_seconds_ignore_a_counted_sleep_on_windows(fake: FakeSystem) -> None:
    fake.platform_name = "win32"
    pulse = pulse_of(fake)
    meter = pulse.open(WHO)
    meter.take(asks("u1"))
    fake.clock += 600.0
    pulse.slept_s = 600.0
    fake.clock += 2.0
    pulse.close(meter)
    assert lines()[0]["seconds"] == about(2.0)
    assert lines()[0]["slept"] == about(0.0)


def test_the_pulse_mark_reads_the_three_clocks(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    fake.doze(5.0)
    mark = pulse.mark()
    assert (mark.at, mark.mono, mark.slept) == (fake.clock, fake.monotonic(), about(0.0))


def test_a_failed_write_of_spans_is_ignored(
    fake: FakeSystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    pulse = pulse_of(fake)
    meter = pulse.open(WHO)

    def boom(path: Path, text: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(system, "append_text", boom)
    meter.take(asks("u1"))
    meter.take(answers("u1"))
    pulse.close(meter)


def test_reading_and_take_keep_their_old_signatures(fake: FakeSystem) -> None:
    reading = live.Reading(WHO, 5.0)
    turn = reading.take(asks("u1"), 6.0)
    same = live.Reading(WHO, 5.0).take_at(asks("u1"), Mark(6.0))
    assert turn == same


def test_an_interrupted_end_carries_the_split(fake: FakeSystem) -> None:
    pulse = pulse_of(fake)
    meter = pulse.open(WHO)
    meter.take(asks("u1"))
    fake.clock += 2.0
    pulse.close(meter)
    event = meter.interrupted(live.Stop(Cause.ERROR))
    assert set(event.data) >= SPLIT_KEYS
    assert event.data["tool_s"] == 2.0


def test_no_meter_has_no_split() -> None:
    assert live.time_split(None) == {}


def step_ends(rt: Any) -> list[Event]:
    return [e for e in rt.events.events() if e.kind is EventKind.STEP_END]


def test_a_role_steps_end_has_the_split(make_runtime: Any, fake: FakeSystem) -> None:
    rt = make_runtime(FakeQuery())
    open_story(rt)
    run_step(rt)
    [end] = step_ends(rt)
    assert set(end.data) >= SPLIT_KEYS
    assert end.data["waiting_s"] == 0.0 and end.data["tool_s"] == 0.0
    assert "mono" in end.data and "slept" in end.data


def po_turns(rt: Any) -> list[Event]:
    return [e for e in rt.events.events() if e.kind is EventKind.PO_TURN]


def test_the_event_kind_exists() -> None:
    assert EventKind.PO_TURN.value == "po-turn"


def test_every_po_query_emits_one_po_turn(make_runtime: Any) -> None:
    holder: list = []
    rt = make_runtime(Router(PoCallingRole(holder), FakeQuery()))
    holder.append(rt)
    rt.state.po_session = "po-sess"
    asyncio.run(po_tools_run(rt))
    turns = po_turns(rt)
    assert turns
    for turn in turns:
        assert turn.role == "product-owner" and turn.story is None
        assert SPLIT_KEYS | {"mono", "slept"} <= set(turn.data)
    sessions = [e for e in rt.events.events() if e.kind is EventKind.PO_SESSION]
    assert not [e for e in sessions if "tool_s" in e.data]


def test_a_po_query_that_raises_still_emits_a_po_turn(make_runtime: Any) -> None:
    holder: list = []
    rt = make_runtime(Router(PoCallingRole(holder), RaisingQuery(limit_error())))
    holder.append(rt)
    asyncio.run(po_tools_run(rt))
    assert po_turns(rt)


async def po_tools_run(rt: Any) -> Any:
    from agile_team import po_tools

    return await po_tools.run_po(rt, Start("", StartMode.RESUME))

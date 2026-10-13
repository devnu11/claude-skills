"""The runner records two clocks on step events and counts sleep (s97, AW1-AW2)."""

from __future__ import annotations

from typing import Any

import pytest
from agile_team.events import EventKind

from .conftest import FakeQuery
from .fake_system import FakeSystem
from .test_s9 import open_story, raising_action, run_step
from .test_s78_health import make_pulse

BEAT = 20.0


def test_a_gap_of_one_or_two_beats_is_not_sleep(fake: FakeSystem) -> None:
    pulse, _ = make_pulse(fake)
    for gap in (BEAT, 2 * BEAT):
        fake.clock += gap
        pulse._count_sleep(fake.clock)
    assert pulse.slept_s == 0.0


def test_a_long_gap_counts_all_but_one_beat(fake: FakeSystem) -> None:
    pulse, _ = make_pulse(fake)
    fake.clock += 10 * BEAT
    pulse._count_sleep(fake.clock)
    assert pulse.slept_s == 9 * BEAT
    assert pulse.heartbeat()["slept"] == 9 * BEAT


def test_sleeps_add_up_and_the_gap_restarts_at_each_beat(fake: FakeSystem) -> None:
    pulse, _ = make_pulse(fake)
    fake.clock += 5 * BEAT
    pulse._count_sleep(fake.clock)
    fake.clock += BEAT
    pulse._count_sleep(fake.clock)
    assert pulse.slept_s == 4 * BEAT


def test_the_heartbeat_slept_is_rounded_to_a_tenth(fake: FakeSystem) -> None:
    pulse, _ = make_pulse(fake)
    fake.clock += 3 * BEAT + 0.04
    pulse._count_sleep(fake.clock)
    assert pulse.heartbeat()["slept"] == 40.0


def test_a_beat_counts_then_writes(fake: FakeSystem) -> None:
    pulse, writes = make_pulse(fake)
    fake.clock += 6 * BEAT
    pulse._beat()
    assert pulse.slept_s == 5 * BEAT and writes == [1]


def test_clocks_are_the_monotonic_reading_and_the_counter(fake: FakeSystem) -> None:
    pulse, _ = make_pulse(fake)
    fake.doze(300.0)
    pulse._count_sleep(fake.clock)
    assert pulse.clocks() == {"mono": fake.monotonic(), "slept": 300.0 - BEAT}


def step_events(rt: Any, kind: EventKind) -> list:
    return [e for e in rt.events.events() if e.kind is kind]


def test_a_step_writes_both_clocks_on_start_and_end(make_runtime: Any, fake: FakeSystem) -> None:
    rt = make_runtime(FakeQuery())
    open_story(rt)
    fake.doze(7.0)
    run_step(rt)
    [start] = step_events(rt, EventKind.STEP_START)
    [end] = step_events(rt, EventKind.STEP_END)
    for event in (start, end):
        assert event.data["mono"] == pytest.approx(fake.monotonic())
        assert event.data["slept"] == 0.0


def test_an_interrupted_end_carries_both_clocks(make_runtime: Any, fake: FakeSystem) -> None:
    holder: list = []

    class Query(FakeQuery):
        async def _gen(self):
            raising_action(holder, ValueError("boom"))()
            yield None

    rt = make_runtime(Query())
    holder.append(rt)
    open_story(rt)
    with pytest.raises(ValueError):
        run_step(rt)
    [end] = step_events(rt, EventKind.STEP_END)
    assert end.data["status"] == "interrupted"
    assert end.data["mono"] == fake.monotonic() and end.data["slept"] == 0.0

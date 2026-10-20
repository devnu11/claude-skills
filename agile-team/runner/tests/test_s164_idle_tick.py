"""s164: the scheduler's own writes never wake it (W1 to W5, REQ-174)."""

from __future__ import annotations

import asyncio

from agile_team import run_writer as rw
from agile_team.handover import Pass, Trigger
from agile_team.po_tools import Start

from .clock import about, real_monotonic
from .late import Late

sched = Late("scheduler")

SMALL_POLL_S = 0.05
WINDOW_S = 0.5


async def bound_writer() -> rw.RunWriter:
    writer = rw.RunWriter()
    writer.bind(asyncio.get_running_loop(), asyncio.current_task())
    return writer


def test_owner_submit_does_not_wake_w1() -> None:
    async def scenario() -> tuple[bool, int]:
        writer = await bound_writer()
        writer.submit(lambda: None)
        await asyncio.sleep(0)
        return writer.wake.is_set(), writer.drain()

    assert asyncio.run(scenario()) == (False, 1)


def test_another_task_submit_wakes_w1() -> None:
    async def scenario() -> bool:
        writer = await bound_writer()
        await asyncio.create_task(_submit(writer))
        await asyncio.sleep(0)
        return writer.wake.is_set()

    async def _submit(writer: rw.RunWriter) -> None:
        writer.submit(lambda: None)

    assert asyncio.run(scenario()) is True


def test_worker_thread_submit_wakes_w1() -> None:
    async def scenario() -> bool:
        writer = await bound_writer()
        await asyncio.to_thread(writer.submit, lambda: None)
        await asyncio.sleep(0)
        return writer.wake.is_set()

    assert asyncio.run(scenario()) is True


def test_unbound_writes_at_once_and_is_not_owner_w5() -> None:
    writer = rw.RunWriter()
    done: list[int] = []
    writer.submit(lambda: done.append(1))
    assert done == [1] and writer.is_on_owner is False


def test_release_forgets_the_owner() -> None:
    async def scenario() -> tuple[bool, bool]:
        writer = await bound_writer()
        before = writer.is_on_owner
        writer.release()
        return before, writer.is_on_owner

    assert asyncio.run(scenario()) == (True, False)


def test_is_on_owner_false_on_a_thread_without_a_loop() -> None:
    async def scenario() -> bool:
        writer = await bound_writer()
        return await asyncio.to_thread(lambda: writer.is_on_owner)

    assert asyncio.run(scenario()) is False


def test_own_lines_land_before_the_wait_w2(make_runtime, monkeypatch) -> None:
    monkeypatch.setattr("agile_team.scheduler.POLL_S", SMALL_POLL_S)
    rt = make_runtime()
    seen: list[int] = []

    async def scenario() -> float:
        s = sched.Scheduler(rt, Start("task"))
        rt.writer.bind(asyncio.get_running_loop(), asyncio.current_task())
        s.tasks["k"] = asyncio.ensure_future(asyncio.Event().wait())
        rt.writer.submit(lambda: seen.append(1))
        began = real_monotonic()
        await s.wait_for_change()
        s.tasks["k"].cancel()
        return real_monotonic() - began

    elapsed = asyncio.run(scenario())
    assert seen == [1] and elapsed == about(SMALL_POLL_S)


def test_idle_loop_does_not_spin_ac1(make_runtime, monkeypatch) -> None:
    monkeypatch.setattr("agile_team.scheduler.POLL_S", SMALL_POLL_S)
    rt = make_runtime()
    ticks: list[int] = []
    real_tick = sched.Scheduler.tick

    def counted_tick(self) -> None:
        real_tick(self)
        ticks.append(1)
        self.runtime.writer.submit(lambda: None)  # the guard's own stage event

    monkeypatch.setattr(sched.Scheduler, "tick", counted_tick)
    window_s = 0.5

    async def scenario() -> None:
        s = sched.Scheduler(rt, Start("task"))
        rt.writer.bind(asyncio.get_running_loop(), asyncio.current_task())
        s.tasks["k"] = asyncio.ensure_future(asyncio.Event().wait())
        s.opening = None
        try:
            await asyncio.wait_for(s.run_loop(), timeout=window_s)
        except TimeoutError:
            pass
        finally:
            s.tasks["k"].cancel()

    asyncio.run(scenario())
    assert len(ticks) <= window_s / SMALL_POLL_S + 2


def test_a_write_from_a_step_wakes_the_wait_at_once_ac1(make_runtime) -> None:
    rt = make_runtime()

    async def step_write() -> None:
        await asyncio.sleep(0.02)
        rt.writer.submit(lambda: None)

    async def scenario() -> float:
        s = sched.Scheduler(rt, Start("task"))
        rt.writer.bind(asyncio.get_running_loop(), asyncio.current_task())
        s.tasks["k"] = asyncio.ensure_future(asyncio.Event().wait())
        writer_task = asyncio.create_task(step_write())
        began = real_monotonic()
        await s.wait_for_change()
        elapsed = real_monotonic() - began
        s.tasks["k"].cancel()
        await writer_task
        return elapsed

    assert asyncio.run(scenario()) < 1.0


def count_loop_ticks(rt, monkeypatch, found: Pass, halted: bool) -> int:
    """Run the loop for a window with one never-ending step and ``found`` on the desk."""
    monkeypatch.setattr("agile_team.scheduler.POLL_S", SMALL_POLL_S)
    ticks: list[int] = []
    real_tick = sched.Scheduler.tick

    def counted_tick(self) -> None:
        real_tick(self)
        ticks.append(1)

    monkeypatch.setattr(sched.Scheduler, "tick", counted_tick)

    async def scenario() -> None:
        s = sched.Scheduler(rt, Start("task"))
        rt.writer.bind(asyncio.get_running_loop(), asyncio.current_task())
        s.tasks["k"] = asyncio.ensure_future(asyncio.Event().wait())
        s.opening = None
        s.desk.queue(found)
        rt.halted_by = "halt" if halted else None
        try:
            await asyncio.wait_for(s.run_loop(), timeout=WINDOW_S)
        except TimeoutError:
            pass
        finally:
            s.tasks["k"].cancel()

    asyncio.run(scenario())
    return len(ticks)


def test_ended_run_with_a_queued_pass_still_awaits_d1(make_runtime, monkeypatch) -> None:
    found = Pass([Trigger.STORY_CI_RED], ["x"], [])
    ticks = count_loop_ticks(make_runtime(), monkeypatch, found, halted=True)
    assert ticks <= WINDOW_S / SMALL_POLL_S + 2


def test_queued_pass_without_kinds_still_awaits_d1(make_runtime, monkeypatch) -> None:
    ticks = count_loop_ticks(make_runtime(), monkeypatch, Pass([], [], []), halted=False)
    assert ticks <= WINDOW_S / SMALL_POLL_S + 2

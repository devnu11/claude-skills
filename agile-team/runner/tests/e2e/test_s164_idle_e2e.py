"""s164 end to end: an idle run loop ticks once per POLL_S and still wakes on a foreign write."""

from __future__ import annotations

import asyncio

from agile_team.po_tools import Start

from ..clock import real_monotonic
from ..late import Late

sched = Late("scheduler")

POLL_S = 0.05
WINDOW_S = 0.6


def guard_events(rt) -> int:
    return sum(1 for e in rt.events.events() if "checkout.guard" in str(e.data))


def idle_window(rt, monkeypatch) -> None:
    """Run the real loop for a window with one never-ending step."""
    monkeypatch.setattr("agile_team.scheduler.POLL_S", POLL_S)

    async def scenario() -> None:
        s = sched.Scheduler(rt, Start("task"))
        rt.writer.bind(asyncio.get_running_loop(), asyncio.current_task())
        s.tasks["k"] = asyncio.ensure_future(asyncio.Event().wait())
        s.opening = None
        try:
            await asyncio.wait_for(s.run_loop(), timeout=WINDOW_S)
        except TimeoutError:
            pass
        finally:
            s.tasks["k"].cancel()

    asyncio.run(scenario())


def test_ac1_ac2_idle_loop_writes_at_most_one_guard_per_poll(make_runtime, monkeypatch) -> None:
    rt = make_runtime()
    idle_window(rt, monkeypatch)
    rt.writer.drain()
    assert guard_events(rt) <= WINDOW_S / POLL_S + 2


def test_ac1_a_foreign_write_wakes_the_wait_at_once(make_runtime) -> None:
    rt = make_runtime()

    async def scenario() -> float:
        s = sched.Scheduler(rt, Start("task"))
        rt.writer.bind(asyncio.get_running_loop(), asyncio.current_task())
        s.tasks["k"] = asyncio.ensure_future(asyncio.Event().wait())

        async def step_write() -> None:
            await asyncio.sleep(0.02)
            rt.writer.submit(lambda: None)

        task = asyncio.create_task(step_write())
        began = real_monotonic()
        await s.wait_for_change()
        elapsed = real_monotonic() - began
        s.tasks["k"].cancel()
        await task
        return elapsed

    assert asyncio.run(scenario()) < 1.0

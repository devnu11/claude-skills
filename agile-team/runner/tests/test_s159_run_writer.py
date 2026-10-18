"""s159 C6/AC6.4: one writer for state, events and ledger."""

import asyncio

import pytest
from agile_team import run_writer as rw


def test_unbound_submit_writes_at_once_r1() -> None:
    writer = rw.RunWriter()
    done: list[int] = []
    writer.submit(lambda: done.append(1))
    assert done == [1]


def test_unbound_apply_runs_and_returns_r1() -> None:
    writer = rw.RunWriter()
    assert asyncio.run(writer.apply(lambda: 42)) == 42


def test_bound_submit_waits_for_drain_r1() -> None:
    async def scenario() -> list[int]:
        writer = rw.RunWriter()
        done: list[int] = []
        writer.bind(asyncio.get_running_loop(), asyncio.current_task())
        writer.submit(lambda: done.append(1))
        assert done == []
        assert writer.drain() == 1
        return done

    assert asyncio.run(scenario()) == [1]


def test_drain_of_nothing_is_zero_r1() -> None:
    async def scenario() -> int:
        writer = rw.RunWriter()
        writer.bind(asyncio.get_running_loop(), asyncio.current_task())
        return writer.drain()

    assert asyncio.run(scenario()) == 0


def test_check_owner_passes_on_the_loop_thread_r1() -> None:
    async def scenario() -> None:
        writer = rw.RunWriter()
        writer.bind(asyncio.get_running_loop(), asyncio.current_task())
        writer.check_owner()

    asyncio.run(scenario())


def test_check_owner_raises_off_the_loop_thread_r1() -> None:
    async def scenario() -> None:
        writer = rw.RunWriter()
        writer.bind(asyncio.get_running_loop(), asyncio.current_task())
        await asyncio.to_thread(writer.check_owner)

    with pytest.raises(rw.WrongWriter):
        asyncio.run(scenario())

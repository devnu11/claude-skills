"""s163 B1 to B7: boundary stages work off the loop and take the lock for moves."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from agile_team.boundary import BoundaryHold, Edge, ReplayProgress, StackEntry, Stage

from .fake_system import FakeSystem
from .test_boundary_runner import Env


@pytest.fixture
def env(make_runtime) -> Env:
    return Env(make_runtime)


def lock_it(env: Env) -> asyncio.Lock:
    env.rt.main_lock = asyncio.Lock()
    return env.rt.main_lock


class Blocker:
    """A ``run_off`` that waits on an event, so the test can look at the loop meanwhile."""

    def __init__(self, env: Env) -> None:
        self.gate = asyncio.Event()
        self.called: list[str] = []
        self.lock_held: list[bool] = []
        self.env = env

    async def run_off(self, call, *args):
        self.called.append(getattr(call, "__name__", str(call)))
        self.lock_held.append(bool(self.env.rt.main_lock and self.env.rt.main_lock.locked()))
        await self.gate.wait()
        return call(*args)


async def drive_blocked(env: Env, blocker: Blocker) -> list[str]:
    """Start a stage, let it block, and show other tasks run meanwhile; then let it finish."""
    seen: list[str] = []

    async def other() -> None:
        seen.append("po turn")

    task = asyncio.create_task(env.br.run_step())
    await asyncio.sleep(0)
    await asyncio.create_task(other())
    seen.append("stage still blocked" if not task.done() else "stage done early")
    await env.rt.writer.apply(lambda: seen.append("writer"))
    blocker.gate.set()
    await task
    return seen


def run_blocked(env: Env, blocker: Blocker) -> list[str]:
    env.br.run_off = blocker.run_off
    return asyncio.run(drive_blocked(env, blocker))


EXPECTED = ["po turn", "stage still blocked", "writer"]


def test_a_blocked_check_leaves_the_loop_free_and_the_lock_open_b2(env: Env) -> None:
    lock_it(env)
    env.open(Edge.START, stage=Stage.CHECK)
    blocker = Blocker(env)
    assert run_blocked(env, blocker) == EXPECTED
    assert blocker.called[0] == "_run_checks" and blocker.lock_held[0] is False


def test_a_blocked_ci_wait_leaves_the_loop_free_and_the_lock_open_b2(env: Env) -> None:
    lock_it(env)
    env.open(Edge.START, stage=Stage.CI)

    def results(entries):
        return []

    env.br.watch = SimpleNamespace(results=results)
    blocker = Blocker(env)
    assert run_blocked(env, blocker) == EXPECTED
    assert blocker.called[0] == "results" and blocker.lock_held[0] is False


def test_the_sync_stage_holds_the_main_lock_while_it_reads_the_remote_b4(env: Env) -> None:
    lock_it(env)
    env.open(Edge.START, stage=Stage.SYNC)
    blocker = Blocker(env)
    run_blocked(env, blocker)
    assert blocker.called[0] == "missing" and blocker.lock_held[0] is True


def test_the_lock_is_released_when_the_stage_ends_b4(env: Env) -> None:
    lock = lock_it(env)
    env.open(Edge.START, stage=Stage.SYNC)
    run_blocked(env, Blocker(env))
    assert not lock.locked()


def test_step_runs_a_stage_with_no_running_loop_and_no_lock_b7(env: Env) -> None:
    env.open(Edge.START, stage=Stage.CHECK)
    assert env.rt.main_lock is None
    report = env.br.step()
    assert report["status"] == "boundary" and report["boundary"]["outcome"] == "pass"


def test_follow_remote_runs_with_no_running_loop_b7(env: Env, fake: FakeSystem) -> None:
    env.br.follow_remote()  # no boundary: nothing to follow, and no loop needed
    assert env.rt.state.boundary is None


# ---------- B3: the replay's checkpoint goes through the writer ----------


def test_a_replay_checkpoint_saves_a_copy_through_call_from_thread_b3(env: Env) -> None:
    b = env.open(Edge.START, stage=Stage.SYNC)
    through: list[object] = []
    writer = env.rt.writer
    original = writer.call_from_thread

    def record(change):
        through.append(change)
        return original(change)

    writer.call_from_thread = record
    work = ReplayProgress("o" * 40, "b" * 40, "t" * 40, done=2)
    env.br._checkpoint(b, work)()
    work.done = 9
    assert len(through) == 1
    assert b.replay == ReplayProgress("o" * 40, "b" * 40, "t" * 40, done=2)
    assert b.replay is not work


# ---------- B4: the REPLAY stage and the R9 follow take the lock ----------


def test_the_replay_stage_holds_the_main_lock_b4(env: Env) -> None:
    lock = lock_it(env)
    held: list[bool] = []

    async def locked_replay(b) -> None:
        held.append(lock.locked())

    env.br._run_locked_replay = locked_replay
    env.open(Edge.END, stage=Stage.REPLAY)
    asyncio.run(env.br._replay(env.rt.state.boundary))
    assert held == [True] and not lock.locked()


def test_the_r9_follow_fast_forwards_under_the_main_lock_b4(env: Env, fake: FakeSystem) -> None:
    lock = lock_it(env)
    held: list[bool] = []
    own = StackEntry(1, "team/sprint-1", "o" * 40, "p" * 40, "S", ["s1"], head="p" * 40)
    own.pushed = "p" * 40
    env.rt.state.upstream.stack = [own]
    b = env.open(Edge.END, stage=Stage.CI)
    b.hold = BoundaryHold.CI_FAILED
    env.br.remote.remote_head = lambda branch: "n" * 40

    def fast_forward(sha: str) -> bool:
        held.append(lock.locked())
        return True

    env.br.remote.fast_forward = fast_forward
    env.rt.record_checkout = lambda: None
    asyncio.run(env.br.run_follow())
    assert held == [True] and not lock.locked()
    assert own.head == own.pushed == "n" * 40

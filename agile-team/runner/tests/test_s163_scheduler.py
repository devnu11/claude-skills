"""s163 AC1, AC4, AC7: a revert holds the landing slot, start_sprint prunes, run_role locks."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from agile_team import po_tools
from agile_team.boundary import Permission, StepKind
from agile_team.dispatch import StepRequest
from agile_team.gates import StoryState
from agile_team.po_tools import Start, Tools
from agile_team.router import Work
from agile_team.scheduler import BOUNDARY_KEY, REVERT_KEY, Scheduler
from agile_team.story_branches import Landed

from .fake_system import Done


def story(sid: str, step: str = "land") -> StoryState:
    return StoryState(sid, "T", step, sprint=1, branch=f"team/story-{sid}", base_sha="b" * 40)


def revert_setup(make_runtime):
    rt = make_runtime()
    rt.state.sprint = 1
    rt.state.upstream.push = Permission.YES
    done, waiting = story("s1", "done"), story("s2")
    done.landed = Landed("m" * 40, "m" * 40)
    rt.state.stories = {"s1": done, "s2": waiting}
    rt.revert_queue.append(SimpleNamespace(story_id="s1", reason="r"))
    return rt, Scheduler(rt, Start("task")), done, waiting


def land_work(s: StoryState) -> Work:
    return Work("runner", s, "", StepKind.LAND)


async def start_blocked(sched, gate: asyncio.Event) -> None:
    async def blocked(story, reason):
        await gate.wait()
        return {"gate": {"verdict": "bounce"}}

    sched.lander.land_revert = blocked
    assert sched.start_revert()
    await asyncio.sleep(0)


def test_a_running_revert_keeps_a_waiting_land_from_starting_d1(make_runtime, fake) -> None:
    rt, sched, _, waiting = revert_setup(make_runtime)

    async def scenario() -> str | None:
        gate = asyncio.Event()
        await start_blocked(sched, gate)
        wait = sched.check_land(land_work(waiting))
        gate.set()
        await asyncio.gather(*sched.tasks.values(), return_exceptions=True)
        return wait

    wait = asyncio.run(scenario())
    assert wait is not None and "s1" in wait
    assert rt.state.landing == ""


def test_a_land_may_start_once_the_revert_has_finished_d1(make_runtime, fake) -> None:
    _, sched, _, waiting = revert_setup(make_runtime)

    async def scenario() -> None:
        gate = asyncio.Event()
        await start_blocked(sched, gate)
        gate.set()
        await asyncio.gather(*sched.tasks.values(), return_exceptions=True)

    asyncio.run(scenario())
    assert sched.check_land(land_work(waiting)) is None


def test_a_revert_that_raises_still_frees_the_slot_d4(make_runtime, fake) -> None:
    rt, sched, done, waiting = revert_setup(make_runtime)

    async def boom(story, reason):
        raise RuntimeError("git exploded")

    sched.lander.land_revert = boom
    rt.revert_queue.clear()
    sched.landings.begin_revert("s1")
    with pytest.raises(RuntimeError):
        asyncio.run(sched.run_revert(done, SimpleNamespace(story_id="s1", reason="r")))
    assert rt.state.landing == "" and sched.landings.reverting == ""
    assert sched.check_land(land_work(waiting)) is None


def test_no_revert_starts_while_one_is_running_e3(make_runtime, fake) -> None:
    _, sched, _, _ = revert_setup(make_runtime)
    sched.tasks[REVERT_KEY] = object()
    assert sched.start_revert() is False


def test_a_revert_waits_for_its_turn_in_the_queue_ac1(make_runtime, fake) -> None:
    rt, sched, _, _ = revert_setup(make_runtime)
    rt.state.landing_order = ["s2"]
    fake.reply(("diff", "--shortstat"), Done(0, " 1 file changed, 1 insertion(+)\n"))
    assert sched.start_revert() is False


# ---------- start_sprint prunes the stack (S1, S2) ----------


def test_start_sprint_does_not_look_for_merged_heads_without_an_upstream_d5(
    make_runtime, fake, monkeypatch
) -> None:
    rt = make_runtime()
    rt.state.upstream.stack = [SimpleNamespace(head="h" * 40)]
    rt.upstream = None
    calls: list[object] = []
    monkeypatch.setattr(po_tools.system, "run_in_thread", lambda *a: calls.append(a))
    asyncio.run(Tools(rt)._drop_merged_entries())
    assert calls == []


def test_start_sprint_does_not_look_for_merged_heads_with_an_empty_stack_d5(
    make_runtime, fake, monkeypatch
) -> None:
    rt = make_runtime()
    rt.upstream = object()
    calls: list[object] = []
    monkeypatch.setattr(po_tools.system, "run_in_thread", lambda *a: calls.append(a))
    asyncio.run(Tools(rt)._drop_merged_entries())
    assert calls == []


# ---------- a PO run_role step takes the main lock (AC7) ----------


def locked_during_run(rt) -> list[bool]:
    seen: list[bool] = []

    async def run_role(request):
        seen.append(bool(rt.main_lock and rt.main_lock.locked()))
        return {"status": "done"}

    rt.run_role = run_role
    return seen


def test_a_storyless_po_run_role_holds_the_main_lock_ac7(make_runtime, fake) -> None:
    rt = make_runtime()
    rt.main_lock = asyncio.Lock()
    seen = locked_during_run(rt)
    asyncio.run(Tools(rt).run_role({"role": "devops", "brief": "b"}))
    assert seen == [True] and not rt.main_lock.locked()


def test_the_lock_is_the_same_as_the_schedulers_dispatch_ac7(make_runtime, fake) -> None:
    rt = make_runtime()
    rt.main_lock = asyncio.Lock()
    assert rt.lock_for(StepRequest("devops", "b", None)) is rt.main_lock


def test_a_run_without_a_lock_runs_the_step_unlocked_ac7(make_runtime, fake) -> None:
    rt = make_runtime()
    seen = locked_during_run(rt)
    rt.main_lock = None
    asyncio.run(Tools(rt).run_role({"role": "devops", "brief": "b"}))
    assert seen == [False]


# ---------- K1, B5: the queues wait for a stage task or the lock; B6: the follow task ----------


def sched_with_lock(make_runtime) -> Scheduler:
    rt = make_runtime()
    sched = Scheduler(rt, Start("task"))
    sched.main_lock = asyncio.Lock()
    return sched


def test_the_queues_may_be_applied_when_nothing_holds_the_checkout_k1(make_runtime, fake) -> None:
    assert sched_with_lock(make_runtime).may_apply_queues is True


def test_the_queues_wait_while_the_main_lock_is_held_k1(make_runtime, fake) -> None:
    sched = sched_with_lock(make_runtime)

    async def scenario() -> bool:
        async with sched.main_lock:
            return sched.may_apply_queues

    assert asyncio.run(scenario()) is False


def test_the_queues_wait_while_a_boundary_stage_task_runs_b5(make_runtime, fake) -> None:
    sched = sched_with_lock(make_runtime)

    async def scenario() -> bool:
        gate = asyncio.Event()
        sched.tasks[BOUNDARY_KEY] = asyncio.create_task(gate.wait())
        seen = sched.may_apply_queues
        gate.set()
        await sched.tasks[BOUNDARY_KEY]
        return seen

    assert asyncio.run(scenario()) is False


def follow_calls(sched: Scheduler) -> list[str]:
    calls: list[str] = []

    async def run_follow() -> None:
        calls.append("followed")

    sched.router.boundaries.run_follow = run_follow
    return calls


def test_follow_boundary_starts_the_follow_as_a_task_b6(make_runtime, fake) -> None:
    sched = sched_with_lock(make_runtime)
    calls = follow_calls(sched)

    async def scenario() -> None:
        sched.follow_boundary()
        assert sched.follow_task is not None
        await sched.follow_task

    asyncio.run(scenario())
    assert calls == ["followed"]


def test_follow_boundary_waits_while_a_boundary_stage_task_runs_b6(make_runtime, fake) -> None:
    sched = sched_with_lock(make_runtime)
    calls = follow_calls(sched)

    async def scenario() -> None:
        gate = asyncio.Event()
        sched.tasks[BOUNDARY_KEY] = asyncio.create_task(gate.wait())
        sched.follow_boundary()
        gate.set()
        await sched.tasks[BOUNDARY_KEY]

    asyncio.run(scenario())
    assert sched.follow_task is None and calls == []

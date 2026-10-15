"""s44 round 1: quiet clock (H7), waiting chore (D9), graceful stop (R15), wiring (review D4)."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agile_team import boundary as bd
from agile_team import cli, halt, live, po_tools, system, watch
from agile_team import state as state_mod
from agile_team.boundary import Edge
from agile_team.boundary_runner import BoundaryRunner
from agile_team.checkout import ACCEPTED_REASON
from agile_team.health import Clock, Health, Level, Runner, Vitals, judge
from agile_team.po_tools import PoRun, Start, Tools
from agile_team.providers import DEFAULT, Billing
from agile_team.state import RunState, RunStatus
from claude_agent_sdk import ResultError

from .clock import about
from .conftest import FakeQuery
from .fake_system import FakeSystem
from .test_s44_live import (
    LIMITS,
    NOW,
    WHO,
    beat,
    beat_file,
    make_pulse,
    reply,
    step,
    tool_done,
)

PO_WHO = live.Who("product-owner", None, None, "opus", Billing.REPORTED)


# ----- quiet clock (H7) --------------------------------------------------------------


def test_quiet_since_starts_at_started_at_and_turns_move_it() -> None:
    reading = live.Reading(WHO, NOW)
    assert reading.quiet_since == NOW
    reading.take(reply("a", {"input_tokens": 1}), NOW + 7)
    assert reading.quiet_since == NOW + 7
    assert reading.view()["quiet_since"] == NOW + 7


def test_a_tool_result_for_an_open_tool_wakes_and_an_unknown_one_does_not() -> None:
    reading = live.Reading(WHO, NOW)
    reading.take(reply("a", {"input_tokens": 1}, tools=("Bash",)), NOW + 1)
    reading.take(tool_done("nope"), NOW + 50)
    assert reading.quiet_since == NOW + 1
    reading.take(tool_done("id-Bash"), NOW + 90)
    assert reading.quiet_since == NOW + 90


def test_the_heartbeat_step_carries_quiet_since(scratch: Path, fake: FakeSystem) -> None:
    pulse, clock = make_pulse(scratch, fake)
    meter = pulse.open(WHO)
    clock.t += 5
    meter.take(reply("a", {"input_tokens": 1}))
    assert beat_file(scratch)["step"]["quiet_since"] == NOW + 5


def test_a_nested_role_closing_wakes_the_po_reading(scratch: Path, fake: FakeSystem) -> None:
    pulse, clock = make_pulse(scratch, fake)
    po = pulse.open(PO_WHO)
    po.take(reply("a", {"input_tokens": 1}, tools=("run_role",), model="claude-opus-4"))
    clock.t = NOW + 10
    role = pulse.open(WHO)
    clock.t = NOW + 1510
    pulse.close(role)
    assert po.reading.quiet_since == NOW + 1510
    clock.t = NOW + 1520
    heartbeat = beat_file(scratch)
    verdict = judge(Vitals(clock.t, RunStatus.RUNNING, None, heartbeat, Runner.UP, LIMITS))
    assert verdict == Health(Level.GREEN, "turns arriving", None)


def test_closing_the_last_reading_does_not_fail(scratch: Path, fake: FakeSystem) -> None:
    pulse, _ = make_pulse(scratch, fake)
    pulse.close(pulse.open(WHO))
    assert beat_file(scratch)["step"] is None


def test_a_chore_ending_wakes_the_innermost_reading_even_on_error(
    scratch: Path, fake: FakeSystem
) -> None:
    pulse, clock = make_pulse(scratch, fake)
    meter = pulse.open(WHO)
    with pytest.raises(ValueError), pulse.doing("x"):
        clock.t = NOW + 900
        raise ValueError
    assert meter.reading.quiet_since == NOW + 900


def test_a_chore_with_nothing_open_ends_quietly(scratch: Path, fake: FakeSystem) -> None:
    pulse, _ = make_pulse(scratch, fake)
    with pulse.doing("x"):
        pass
    assert beat_file(scratch)["chore"] is None


def test_quiet_for_uses_quiet_since_and_falls_back_without_it() -> None:
    quiet = Vitals(
        NOW, RunStatus.RUNNING, None, beat(step=step(quiet_since=NOW - 100)), Runner.UP, LIMITS
    )
    assert quiet.quiet_for == about(100)
    old = step(last_turn_at=NOW - 40)
    old.pop("quiet_since", None)
    assert Vitals(
        NOW, RunStatus.RUNNING, None, beat(step=old), Runner.UP, LIMITS
    ).quiet_for == about(40)
    old["last_turn_at"] = None
    assert Vitals(
        NOW, RunStatus.RUNNING, None, beat(step=old), Runner.UP, LIMITS
    ).quiet_for == about(30)


# ----- waiting for answers is a chore (D9) -------------------------------------------


def test_wait_for_answers_is_a_chore_and_stays_green(make_runtime, fake: FakeSystem) -> None:
    rt = make_runtime()
    system.make_dirs(rt.config.run_dir)
    rt.pulse.open(PO_WHO)
    seen: list[Any] = []

    def poll() -> None:
        seen.append(live.read_heartbeat(rt.config.run_dir))

    def answer() -> None:
        poll()
        rt.relay.answer("m1", "a")
        rt.relay.answer("m2", "b")

    fake.on_sleep = [poll, answer]
    t = Tools(rt)
    asyncio.run(t.ask_user({"text": "?"}))
    asyncio.run(t.ask_user({"text": "?"}))
    asyncio.run(t.wait_for_answers({"ids": ["m1", "m2"]}))
    chore = seen[0]["chore"]
    assert chore["what"] == po_tools.WAIT_CHORE.format(ids="m1, m2")
    late = {**seen[0], "at": seen[0]["at"]}
    late["step"] = {**late["step"], "quiet_since": late["at"] - 700}
    v = Vitals(late["at"], RunStatus.RUNNING, None, late, Runner.UP, LIMITS)
    assert judge(v).level is Level.GREEN
    assert live.read_heartbeat(rt.config.run_dir)["chore"] is None


def test_wait_chore_text_has_a_dash_without_ids(make_runtime, fake: FakeSystem) -> None:
    rt = make_runtime()
    system.make_dirs(rt.config.run_dir)
    seen: list[Any] = []
    fake.on_sleep = [lambda: seen.append(live.read_heartbeat(rt.config.run_dir)["chore"]["what"])]

    asyncio.run(Tools(rt).wait_for_answers({"ids": [], "timeout_s": 1}))
    assert seen == []  # nothing to wait for: no poll, no chore left behind
    asyncio.run(Tools(rt).wait_for_answers({"ids": ["m9"], "timeout_s": 1}))
    assert seen == ["waiting for answers to m9"]


# ----- a graceful stop is neutral (R15) ----------------------------------------------


def stopped(reason: str | None, kind: str | None, heartbeat: dict[str, Any]) -> Vitals:
    return Vitals(NOW, RunStatus.STOPPED, reason, heartbeat, Runner.GONE, LIMITS, kind)


def test_a_graceful_stop_is_idle_even_with_a_stale_beating_heartbeat() -> None:
    stale = beat(at=NOW - 1200, step=step(quiet_since=NOW - 1800))
    verdict = judge(stopped(None, None, stale))
    assert (verdict.level, verdict.reason) == (Level.IDLE, "stopped")


def test_stop_now_stays_red() -> None:
    stale = beat(at=NOW - 1200, step=step(quiet_since=NOW - 1800))
    verdict = judge(stopped("stopped by stop --now", "sigterm", stale))
    assert verdict.level is Level.RED
    assert verdict.reason.startswith("halted: stopped by stop --now, ")


def test_an_accepted_checkout_stop_is_idle() -> None:
    verdict = judge(stopped(ACCEPTED_REASON, None, beat()))
    assert (verdict.level, verdict.reason) == (Level.IDLE, ACCEPTED_REASON)


def test_resting_and_halted_derive_from_the_halt_kind() -> None:
    assert stopped(None, None, beat()).resting
    assert not stopped(None, None, beat()).halted
    assert not stopped("x", "sigterm", beat()).resting
    assert stopped("x", "sigterm", beat()).halted


def test_mark_clears_the_halt_kind() -> None:
    state = RunState()
    state.halt_kind = "sigterm"
    state.mark(RunStatus.RUNNING)
    assert state.halt_kind is None


def test_a_legacy_state_loads_no_halt_kind(scratch: Path, fake: FakeSystem) -> None:
    system.write_text(scratch / "state.json", '{"status": "stopped"}')
    assert state_mod.load(scratch).halt_kind is None


def test_halt_run_records_the_kind_and_a_new_run_clears_it(make_runtime) -> None:
    rt = make_runtime()
    system.make_dirs(rt.config.run_dir)
    rt.halt_run(halt.Halt(halt.HaltKind.SIGTERM, "stopped by stop --now"))
    assert state_mod.load(rt.config.run_dir).halt_kind == "sigterm"
    rt.state.mark(RunStatus.RUNNING)
    rt.save()
    assert state_mod.load(rt.config.run_dir).halt_kind is None


def test_vitals_read_carries_the_saved_halt_kind(configured: Path) -> None:
    from agile_team.config import load

    config = load(configured)
    state = RunState()
    state.mark(RunStatus.STOPPED, "stopped by stop --now")
    state.halt_kind = "sigterm"
    state_mod.save(config.run_dir, state)
    assert Vitals.read(config, Clock(NOW)).halt_kind == "sigterm"


def test_watch_ignores_a_change_to_a_graceful_stop() -> None:
    idle = watch.Look([], "stopped", None, "idle", "stopped")
    assert "health" not in watch.fired(watch.Seen(health="green"), idle)
    red = watch.Look([], "stopped", "stopped by stop --now", "red", "halted: x")
    assert "health" in watch.fired(watch.Seen(health="green"), red)


# ----- wiring (review D4) ------------------------------------------------------------


class SpyPulse:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def start(self) -> None:
        self.calls.append("start")

    def end(self) -> None:
        self.calls.append("end")


def test_po_until_sigterm_starts_the_pulse_and_ends_it_when_the_po_raises(
    make_runtime, monkeypatch
) -> None:
    rt = make_runtime()
    system.make_dirs(rt.config.run_dir)
    spy = SpyPulse()
    rt.pulse = spy

    async def boom(runtime, start):
        spy.calls.append("run")
        raise RuntimeError("x")

    monkeypatch.setattr(cli, "run_po", boom)
    with pytest.raises(RuntimeError):
        asyncio.run(cli._po_until_sigterm(rt, Start("t")))
    assert spy.calls == ["start", "run", "end"]


def test_the_boundary_step_runs_as_a_chore(make_runtime, monkeypatch) -> None:
    rt = make_runtime()
    system.make_dirs(rt.config.run_dir)
    rt.state.sprint = 1
    rt.state.boundary = bd.Boundary(Edge.START, 1)
    runner = BoundaryRunner(rt)
    seen: list[Any] = []
    monkeypatch.setattr(
        runner, "_step", lambda: seen.append(live.read_heartbeat(rt.config.run_dir)["chore"])
    )
    runner.step()
    assert seen[0]["what"] == f"sprint boundary: {rt.state.boundary.stage}"


@pytest.mark.parametrize("failing", [False, True])
def test_the_po_query_runs_under_a_po_meter(make_runtime, failing) -> None:
    seen: list[Any] = []

    def action() -> None:
        seen.append(live.read_heartbeat(rt.config.run_dir)["step"])
        if failing:
            raise ResultError("bad", data={}, exit_code=1)

    rt = make_runtime(FakeQuery(action=action))
    system.make_dirs(rt.config.run_dir)
    role = SimpleNamespace(name="product-owner", model="opus", provider=DEFAULT)
    plan = SimpleNamespace(role=role, story=None, prompt="p", options=None, meter=None)
    run = PoRun(rt, Start("t"))
    if failing:
        with pytest.raises(ResultError):
            asyncio.run(run._collect(plan))
    else:
        asyncio.run(run._collect(plan))
    assert seen[0]["role"] == "product-owner"
    assert live.read_heartbeat(rt.config.run_dir)["step"] is None

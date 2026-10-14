"""s78: health gives no false reds while work runs (design/s78.md R16-R20, H7-H10)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agile_team import config as cfg
from agile_team import health, live
from agile_team import state as state_mod
from agile_team.dashboard.snapshot import RunFiles, _health
from agile_team.dispatch import GATE_CHORE, Runtime
from agile_team.health import Clock, Level, Runner, Vitals
from agile_team.providers import Billing
from agile_team.state import RunStatus
from claude_agent_sdk import AssistantMessage, TextBlock, ToolResultBlock, ToolUseBlock, UserMessage

from .fake_system import FAKE_IDS, START_CLOCK, FakeSystem

LIMITS = cfg.HealthLimits()
NOW = 1_000_000.0
MONO = 523_000.0
WHO = live.Who("developer-cli", "s71", "implement", "sonnet", Billing.REPORTED)
RUN_DIR = Path("/fake/run")
BASH = {"name": "Bash", "started_at": NOW - 240}


def step(**over: Any) -> dict[str, Any]:
    base = {
        "role": "developer-cli", "story": "s71", "step": "implement", "started_at": NOW - 900,
        "turn": 3, "model": "claude-sonnet-4-5", "configured_model": "sonnet",
        "last_turn_at": NOW - 5, "tool": None, "tokens": {}, "cost_usd": 0.1,
    }  # fmt: skip
    return {**base, **over}


def beat(age: float = 5, slept: float | None = 0, **over: Any) -> dict[str, Any]:
    """A version-2 beat ``age`` s old whose monotonic stamp says it slept ``slept`` s."""
    base: dict[str, Any] = {
        "version": 2, "pid": 77, "beat": "beating", "at": NOW - age,
        "started_at": NOW - 900, "chore": None, "step": step(),
    }  # fmt: skip
    if slept is not None:
        base["mono"] = MONO - (age - slept)
    return {**base, **over}


def vitals(heartbeat: dict[str, Any] | None, **over: Any) -> Vitals:
    fields: dict[str, Any] = {
        "now": NOW, "status": RunStatus.RUNNING, "reason": None, "beat": heartbeat,
        "runner": Runner.UP, "limits": LIMITS, "mono": MONO,
    }  # fmt: skip
    return Vitals(**{**fields, **over})


def verdict(heartbeat: dict[str, Any], **over: Any) -> health.Health:
    return health.judge(vitals(heartbeat, **over))


def chore(what: str, seconds: float) -> dict[str, Any]:
    return {"what": what, "since": NOW - seconds}


# ----- rules ------------------------------------------------------------------------


def test_a_late_beat_while_a_tool_runs_is_amber() -> None:
    heartbeat = beat(240, step=step(last_turn_at=NOW - 240, tool=BASH))
    v = verdict(heartbeat)
    assert v.level is Level.AMBER
    assert "heartbeat 4 min old while Bash runs" in v.reason


def test_a_late_beat_during_the_gate_chore_is_amber() -> None:
    v = verdict(beat(100, chore=chore("gate: implement on s71", 100)))
    assert v.level is Level.AMBER
    assert v.reason == "heartbeat 1 min old while runner: gate: implement on s71 for 1 min"


def test_a_chore_wins_over_a_tool_in_the_words() -> None:
    heartbeat = beat(100, chore=chore("tests", 100), step=step(tool=BASH))
    assert verdict(heartbeat).reason == "heartbeat 1 min old while runner: tests for 1 min"


def test_the_gate_chore_with_a_fresh_beat_is_green() -> None:
    v = verdict(beat(5, chore=chore("gate: implement on s71", 120)))
    assert v.level is Level.GREEN
    assert v.reason == "runner: gate: implement on s71 for 2 min"


def test_a_sleeping_machine_is_red_and_says_so() -> None:
    heartbeat = beat(660, slept=650, step=step(tool=BASH))
    v = verdict(heartbeat)
    assert v.level is Level.RED
    assert "the machine slept for 10 min" in v.reason
    assert "heartbeat" not in v.reason


def test_a_dead_runner_is_red_even_when_the_late_beat_looks_excused() -> None:
    v = verdict(beat(240, step=step(tool=BASH)), runner=Runner.GONE)
    assert v.level is Level.RED
    assert "the runner is not running" in v.reason


def test_a_late_beat_with_nothing_declared_is_red() -> None:
    v = verdict(beat(120))
    assert (v.level, v.reason) == (Level.RED, "heartbeat 2 min old")


def test_a_late_beat_beyond_red_quiet_is_not_excused() -> None:
    late = LIMITS.red_quiet_s + 1
    v = verdict(beat(late, step=step(tool=BASH)))
    assert (v.level, v.reason) == (Level.RED, "heartbeat 10 min old")


def test_a_late_beat_exactly_at_red_quiet_is_still_excused() -> None:
    v = verdict(beat(LIMITS.red_quiet_s, step=step(tool=BASH)))
    assert v.level is Level.AMBER


def test_a_version_1_beat_cannot_tell_sleep_from_delay_so_stays_red() -> None:
    v = verdict(beat(240, slept=None, version=1, step=step(tool=BASH)))
    assert (v.level, v.reason) == (Level.RED, "heartbeat 4 min old")


def test_an_unknown_reader_clock_stays_red() -> None:
    v = verdict(beat(240, step=step(tool=BASH)), mono=None)
    assert (v.level, v.reason) == (Level.RED, "heartbeat 4 min old")


def test_a_non_numeric_beat_mono_means_slept_is_unknown() -> None:
    assert vitals(beat(10, mono="soon")).slept is None
    assert vitals(beat(10, slept=None)).slept is None
    assert vitals(None).slept is None


def test_slept_is_wall_age_minus_monotonic_age() -> None:
    assert vitals(beat(660, slept=650)).slept == 650


def test_slept_exactly_stale_s_is_not_a_sleep_and_can_be_excused() -> None:
    v = vitals(beat(100, slept=LIMITS.stale_s, step=step(tool=BASH)))
    assert v.slept == LIMITS.stale_s
    assert not v.slept_over(LIMITS.stale_s) and v.excused
    assert health.judge(v).level is Level.AMBER


def test_a_fresh_beat_is_not_stale() -> None:
    assert not vitals(beat(10)).stale
    assert vitals(beat(91)).stale
    assert not vitals(beat(500, beat="ended")).stale


def test_busy_means_a_tool_or_a_chore() -> None:
    assert not vitals(beat()).busy
    assert vitals(beat(step=step(tool=BASH))).busy
    assert vitals(beat(chore=chore("x", 1))).busy


def test_clock_read_gives_both_clocks_from_the_system(fake: FakeSystem) -> None:
    fake.clock = 1234.0
    assert Clock.read() == Clock(1234.0, 1234.0)
    assert Clock(5.0).mono is None


# ----- the pulse --------------------------------------------------------------------


def make_pulse(fake: FakeSystem, ticks: int = 0) -> tuple[live.Pulse, list[int]]:
    """A pulse whose ``write`` only counts and whose turn log is silent; ``ticks`` beats."""
    fake.ticks = ticks
    pulse = live.Pulse(RUN_DIR, 20.0)
    writes: list[int] = []
    pulse.write = lambda: writes.append(1)  # type: ignore[method-assign]
    pulse._log = lambda turn: None  # type: ignore[method-assign]
    return pulse, writes


def test_the_heartbeat_is_version_2_with_a_monotonic_stamp_in_order(fake: FakeSystem) -> None:
    pulse, _ = make_pulse(fake)
    data = pulse.heartbeat()
    assert live.HEARTBEAT_VERSION == 2 and data["version"] == 2
    assert data["mono"] == fake.clock and data["at"] == fake.clock
    assert data["pid"] == FAKE_IDS[0]
    # s101 N11 adds "calls"; s102 HB3 adds "stages"; s97 adds "slept" (test_s97_clocks)
    keys = [k for k in data if k != "slept"]
    assert keys == [
        "version",
        "pid",
        "beat",
        "at",
        "mono",
        "started_at",
        "chore",
        "step",
        "calls",
        "stages",
    ]


def test_tool_calls_and_results_write_the_heartbeat(fake: FakeSystem) -> None:
    pulse, writes = make_pulse(fake)
    meter = pulse.open(WHO)
    writes.clear()
    use = AssistantMessage(
        content=[TextBlock(text="x"), ToolUseBlock(id="t1", name="Bash", input={})],
        model="m1",
        usage={},
        message_id="m1",
    )
    meter.take(use)
    assert len(writes) == 1
    meter.take(UserMessage(content=[ToolResultBlock(tool_use_id="nope", content="ok")]))
    assert len(writes) == 1
    meter.take(UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="ok")]))
    assert len(writes) == 2


def test_the_beat_thread_survives_failed_writes_and_logs_the_first(fake: FakeSystem) -> None:
    pulse, _ = make_pulse(fake, ticks=2)

    def broken() -> None:
        raise RuntimeError("boom")

    pulse.write = broken  # type: ignore[method-assign]
    pulse.beats()
    assert fake.ticks == 0 and fake.clock == START_CLOCK + 2 * 20.0  # two beats, then it stopped
    log = fake.text_of(RUN_DIR / "crash.log")
    assert log.count("--- ") == 1 and "RuntimeError" in log and "boom" in log


def test_a_beat_that_works_after_a_failure_keeps_beating(fake: FakeSystem) -> None:
    pulse, _ = make_pulse(fake, ticks=2)
    calls: list[int] = []

    def flaky() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("once")

    pulse.write = flaky  # type: ignore[method-assign]
    pulse.beats()
    assert len(calls) == 2
    assert fake.text_of(RUN_DIR / "crash.log").count("--- ") == 1


def test_reporting_into_an_unwritable_crash_log_raises_nothing(fake: FakeSystem) -> None:
    fake.fill_disk()
    pulse, _ = make_pulse(fake)
    pulse._report(RuntimeError("x"))
    pulse._report(RuntimeError("y"))


# ----- wiring -----------------------------------------------------------------------


def make_runtime(seen: list[Any], fake: FakeSystem) -> tuple[Runtime, live.Pulse]:
    pulse, _ = make_pulse(fake)
    runtime = object.__new__(Runtime)
    runtime.pulse = pulse

    def evaluate(story: Any, handoff: Any) -> Any:
        seen.append(pulse.heartbeat()["chore"]["what"])
        return SimpleNamespace(verdict="fail", pending=None)

    pipeline = SimpleNamespace(evaluate=evaluate)
    pipeline.serving = lambda serving: pipeline  # type: ignore[attr-defined]
    runtime.pipeline = pipeline  # type: ignore[assignment]
    runtime.verify_checkout = lambda: None  # type: ignore[method-assign]
    runtime._advance_and_log = lambda plan, outcome: {"outcome": "outcome", "step": "implement"}  # type: ignore[method-assign]
    return runtime, pulse


def test_the_gate_runs_inside_a_chore_and_restores_the_outer_one(fake: FakeSystem) -> None:
    seen: list[Any] = []
    runtime, pulse = make_runtime(seen, fake)
    story = SimpleNamespace(step="implement", id="s71")
    plan = SimpleNamespace(story=story, stop_hook=None, base="abc")
    assert GATE_CHORE == "gate: {step} on {story}"
    with pulse.doing("settling developer-cli on s71"):
        assert runtime.gate(plan, object()) == {"outcome": "outcome", "step": "implement"}  # type: ignore[arg-type]
        assert pulse.heartbeat()["chore"]["what"] == "settling developer-cli on s71"
    assert seen == ["gate: implement on s71"]
    runtime.gate(plan, object())  # type: ignore[arg-type]
    assert pulse.heartbeat()["chore"] is None


def seed_run(fake: FakeSystem) -> cfg.Config:
    """A running state and a late v2 heartbeat with a tool open, written to the fake."""
    config = cfg.from_raw(Path("/fake/repo"), {})
    state = state_mod.RunState()
    state.mark(RunStatus.RUNNING)
    state_mod.save(config.run_dir, state)
    now = fake.clock
    late = {
        "version": 2, "pid": fake.pid(), "beat": "beating", "at": now - 240, "mono": now - 240,
        "started_at": now - 900, "chore": None,
        "step": step(last_turn_at=now - 240, tool={"name": "Bash", "started_at": now - 240}),
    }  # fmt: skip
    fake.put(config.run_dir / live.HEARTBEAT, json.dumps(late))
    fake.put(config.run_dir / state_mod.PID_FILE, str(fake.pid()))
    return config


def test_current_reads_both_clocks_through_the_system(fake: FakeSystem) -> None:
    config = seed_run(fake)
    current = health.current(config)
    assert current.level is Level.AMBER
    assert "heartbeat 4 min old while Bash runs" in current.reason


def test_watch_and_snapshot_give_the_same_verdict(fake: FakeSystem) -> None:
    config = seed_run(fake)
    t = fake.clock
    files = RunFiles(config, None, state_mod.load(config.run_dir), [], now=t, mono=t)  # type: ignore[arg-type]
    snap = _health(files)
    current = health.current(config)
    assert (snap["level"], snap["reason"]) == (str(current.level), current.reason)
    assert snap["level"] == "amber"


def test_the_reader_clock_decides_sleep_in_the_snapshot(fake: FakeSystem) -> None:
    config = seed_run(fake)
    t = fake.clock
    state = state_mod.load(config.run_dir)
    slept = RunFiles(config, None, state, [], now=t, mono=t - 200)  # type: ignore[arg-type]
    assert _health(slept)["level"] == "red"
    assert "the machine slept" in _health(slept)["reason"]


@pytest.mark.parametrize("name", ["Vitals", "Clock"])
def test_the_health_module_exports_its_types(name: str) -> None:
    assert hasattr(health, name)

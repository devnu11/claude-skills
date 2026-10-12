"""s44: the live meter (turns, heartbeat, chores), health rules, config and stop reasons."""

import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agile_team import config as cfg
from agile_team import health, live, salvage
from agile_team.events import INTERRUPTED, EventKind
from agile_team.health import Level, Runner, Vitals
from agile_team.ledger import Tokens
from agile_team.providers import Billing
from agile_team.salvage import Cause
from agile_team.state import RunStatus
from claude_agent_sdk import AssistantMessage, TextBlock, ToolResultBlock, ToolUseBlock, UserMessage

LIMITS = cfg.HealthLimits()
NOW = 1_000_000.0
WHO = live.Who("developer-cli", "s29", "implement", "sonnet", Billing.REPORTED)


class Clock:
    """A fake pace: ``wait`` never sleeps; it advances the clock and says stop after ``beats``."""

    def __init__(self, beats: int = 0) -> None:
        self.t = NOW
        self.beats = beats
        self.waits: list[float] = []

    def now(self) -> float:
        return self.t

    def wait(self, event: threading.Event, seconds: float) -> bool:
        self.waits.append(seconds)
        self.t += seconds
        return len(self.waits) > self.beats

    def pace(self) -> live.Pace:
        return live.Pace(self.now, self.wait)


def usage(i: int = 0, o: int = 0, r: int = 0, c: int = 0) -> dict[str, int]:
    return {
        "input_tokens": i,
        "output_tokens": o,
        "cache_read_input_tokens": r,
        "cache_creation_input_tokens": c,
    }


def reply(mid: str | None, u: dict[str, int], tools: tuple[str, ...] = (), model: str = "m1"):
    blocks: list[Any] = [TextBlock(text="x")]
    blocks += [ToolUseBlock(id=f"id-{t}", name=t, input={}) for t in tools]
    return AssistantMessage(content=blocks, model=model, usage=u, message_id=mid)


def tool_done(tool_id: str) -> UserMessage:
    return UserMessage(content=[ToolResultBlock(tool_use_id=tool_id, content="ok")])


def make_pulse(tmp_path: Path, clock: Clock | None = None) -> tuple[live.Pulse, Clock]:
    clock = clock or Clock()
    return live.Pulse(tmp_path, 20.0, clock.pace(), pid=4242), clock


def beat_file(tmp_path: Path) -> dict[str, Any]:
    return json.loads((tmp_path / live.HEARTBEAT).read_text())


def turn_lines(tmp_path: Path) -> list[dict[str, Any]]:
    path = tmp_path / live.TURNS
    return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []


# ----- estimate, family, age ---------------------------------------------------------


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-sonnet-4-5-20250929", 3 + 15 + 0.3 + 3.75),
        ("claude-opus-4-1", 5 + 25 + 0.5 + 6.25),
        ("Claude-Haiku-4", 1 + 5 + 0.1 + 1.25),
    ],
)
def test_estimate_prices_a_million_of_each_kind(model: str, expected: float) -> None:
    million = Tokens(1_000_000, 1_000_000, 1_000_000, 1_000_000)
    assert live.estimate(model, million) == pytest.approx(expected)


def test_estimate_unknown_family_is_none() -> None:
    assert live.estimate("gpt-9", Tokens(1, 1, 1, 1)) is None


def test_family_and_model_note() -> None:
    assert live.family("claude-OPUS-4") == "opus"
    assert live.family("weird") == "weird"
    assert health.model_note({"model": "claude-sonnet-4", "configured_model": "sonnet"}) is None
    note = health.model_note({"model": "claude-opus-4", "configured_model": "sonnet"})
    assert note == "configured sonnet, answering opus"
    assert health.model_note({"model": None, "configured_model": "sonnet"}) is None
    assert health.model_note(None) is None


@pytest.mark.parametrize(
    "seconds,text",
    [(8, "8 s"), (89, "89 s"), (90, "1 min"), (660, "11 min"), (5400, "1 h 30 min")],
)
def test_age(seconds: float, text: str) -> None:
    assert health.age(seconds) == text


# ----- turns (T1-T7) -----------------------------------------------------------------


def test_each_distinct_message_id_is_one_turn_line(tmp_path: Path) -> None:
    pulse, clock = make_pulse(tmp_path)
    meter = pulse.open(WHO)
    meter.take(reply("m1", usage(3, 400, 80000, 1200), ("Bash",), "claude-sonnet-4-5"))
    clock.t += 5
    meter.take(reply("m2", usage(1, 10), ("Read", "Edit")))
    meter.take(reply("m3", usage(2, 20)))
    lines = turn_lines(tmp_path)
    assert [x["turn"] for x in lines] == [1, 2, 3]
    assert list(lines[0]) == [
        "at", "role", "story", "step", "turn", "model", "tokens", "tools", "cost_usd", "message_id",
    ]  # fmt: skip
    first = lines[0]
    assert first["tokens"] == {
        "input": 3,
        "output": 400,
        "cache_read": 80000,
        "cache_creation": 1200,
    }
    assert (first["role"], first["story"], first["step"]) == ("developer-cli", "s29", "implement")
    assert first["tools"] == ["Bash"] and first["model"] == "claude-sonnet-4-5"
    assert first["at"] == NOW and lines[1]["at"] == NOW + 5
    assert first["message_id"] == "m1" and lines[1]["tools"] == ["Read", "Edit"]
    assert first["cost_usd"] == pytest.approx(live.estimate("sonnet", Tokens(3, 400, 80000, 1200)))
    assert meter.reading.turns == 3


def test_same_message_id_folds_into_one_turn_and_counts_once(tmp_path: Path) -> None:
    pulse, _ = make_pulse(tmp_path)
    meter = pulse.open(WHO)
    meter.take(reply("m1", usage(1, 10)))
    meter.take(reply("m1", usage(1, 10), ("Bash",)))  # same usage, a tool: line, no new tokens
    meter.take(reply("m1", usage(1, 25)))  # larger output: only the excess
    assert meter.reading.turns == 1
    assert meter.reading.tokens == Tokens(1, 25, 0, 0)
    lines = turn_lines(tmp_path)
    assert {x["turn"] for x in lines} == {1}
    assert sum(x["tokens"]["output"] for x in lines) == 25
    assert lines[1]["tokens"] == {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}


def test_a_message_without_news_writes_nothing(tmp_path: Path) -> None:
    pulse, _ = make_pulse(tmp_path)
    meter = pulse.open(WHO)
    meter.take(reply("m1", usage(1, 10)))
    meter.take(reply("m1", usage(1, 10)))
    meter.take(reply("m1", usage(0, 5)))  # lower than counted: no excess, no tool
    meter.take("not a message")
    assert len(turn_lines(tmp_path)) == 1


def test_a_message_without_an_id_is_always_a_new_turn(tmp_path: Path) -> None:
    pulse, _ = make_pulse(tmp_path)
    meter = pulse.open(WHO)
    meter.take(reply(None, usage(1, 1)))
    meter.take(reply(None, usage(1, 1)))
    assert meter.reading.turns == 2 and meter.reading.tokens == Tokens(2, 2, 0, 0)


def test_off_story_turns_have_null_story_and_step(tmp_path: Path) -> None:
    pulse, _ = make_pulse(tmp_path)
    pulse.open(live.Who("product-owner", None, None, "opus", Billing.REPORTED)).take(
        reply("m1", usage(1, 1))
    )
    line = turn_lines(tmp_path)[0]
    assert line["story"] is None and line["step"] is None


def test_free_billing_costs_zero_and_unknown_family_is_null(tmp_path: Path) -> None:
    pulse, _ = make_pulse(tmp_path)
    free = pulse.open(live.Who("developer-cli", "s1", "implement", "local", Billing.FREE))
    free.take(reply("a", usage(10, 10)))
    unknown = pulse.open(live.Who("architect", "s1", "design", "gpt", Billing.REPORTED))
    unknown.take(reply("b", usage(10, 10), model="gpt-9"))
    first, second = turn_lines(tmp_path)
    assert first["cost_usd"] == 0.0 and second["cost_usd"] is None
    assert free.reading.cost_usd == 0.0 and unknown.reading.cost_usd is None
    assert beat_file(tmp_path)["step"]["cost_usd"] is None


def test_tools_open_and_close_and_the_earliest_is_current(tmp_path: Path) -> None:
    pulse, clock = make_pulse(tmp_path)
    meter = pulse.open(WHO)
    meter.take(reply("m1", usage(1, 1), ("Bash",)))
    clock.t += 10
    meter.take(reply("m2", usage(1, 1), ("Read",)))
    assert beat_file(tmp_path)["step"]["tool"] == {"name": "Bash", "started_at": NOW}
    meter.take(tool_done("id-Bash"))
    assert beat_file(tmp_path)["step"]["tool"] == {"name": "Read", "started_at": NOW + 10}
    meter.take(tool_done("id-Read"))
    assert beat_file(tmp_path)["step"]["tool"] is None


# ----- heartbeat (H1-H6) -------------------------------------------------------------


def test_heartbeat_shape_and_atomic_write(tmp_path: Path) -> None:
    pulse, clock = make_pulse(tmp_path)
    pulse.start()
    pulse.end()
    clock = Clock()
    # The beat thread must not move the shared clock: it just waits for end().
    quiet = live.Pace(clock.now, lambda event, seconds: event.wait(5))
    pulse2 = live.Pulse(tmp_path, 20.0, quiet, pid=4242)
    pulse2.start()
    meter = pulse2.open(WHO)
    clock.t += 3
    meter.take(reply("m1", usage(2, 7), ("Bash",), "claude-sonnet-4-5"))
    beat = beat_file(tmp_path)
    pulse2.end()
    assert list(beat) == ["version", "pid", "beat", "at", "mono", "started_at", "chore", "step"]
    assert beat["version"] == 2 and beat["pid"] == 4242 and beat["beat"] == "beating"
    assert beat["at"] == NOW + 3 and beat["started_at"] == NOW and beat["chore"] is None
    assert list(beat["step"]) == [
        "role", "story", "step", "started_at", "turn", "model", "configured_model",
        "last_turn_at", "quiet_since", "tool", "tokens", "cost_usd",
    ]  # fmt: skip
    step = beat["step"]
    assert (step["role"], step["story"], step["step"], step["turn"]) == (
        "developer-cli", "s29", "implement", 1,
    )  # fmt: skip
    assert step["model"] == "claude-sonnet-4-5" and step["configured_model"] == "sonnet"
    assert step["last_turn_at"] == NOW + 3 and step["tool"]["name"] == "Bash"
    assert step["tokens"] == {"input": 2, "output": 7, "cache_read": 0, "cache_creation": 0}
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_fresh_step_has_null_model_and_last_turn(tmp_path: Path) -> None:
    pulse, _ = make_pulse(tmp_path)
    pulse.open(WHO)
    step = beat_file(tmp_path)["step"]
    assert step["model"] is None and step["last_turn_at"] is None and step["turn"] == 0
    assert step["tool"] is None and step["cost_usd"] == 0.0


def test_heartbeat_is_written_on_open_and_close(tmp_path: Path) -> None:
    pulse, _ = make_pulse(tmp_path)
    meter = pulse.open(WHO)
    assert beat_file(tmp_path)["step"]["role"] == "developer-cli"
    pulse.close(meter)
    assert beat_file(tmp_path)["step"] is None


def test_beats_writes_each_time_with_the_beat_pace_and_keeps_a_long_tool(tmp_path: Path) -> None:
    pulse, clock = make_pulse(tmp_path, Clock(beats=3))
    meter = pulse.open(WHO)
    meter.take(reply("m1", usage(1, 1), ("Bash",)))
    seen: list[dict[str, Any]] = []
    real_write = pulse.write

    def spy() -> None:
        real_write()
        seen.append(beat_file(tmp_path))

    pulse.write = spy  # type: ignore[method-assign]
    pulse.beats()
    assert clock.waits == [20.0] * 4
    assert len(seen) == 3
    assert [x["at"] for x in seen] == [NOW + 20, NOW + 40, NOW + 60]
    assert all(x["step"]["tool"]["name"] == "Bash" for x in seen)


def test_start_and_end_run_the_thread_and_mark_ended(tmp_path: Path) -> None:
    pulse, _ = make_pulse(tmp_path, Clock(beats=0))
    pulse.start()
    pulse.end()
    assert beat_file(tmp_path)["beat"] == "ended"
    assert beat_file(tmp_path)["step"] is None and beat_file(tmp_path)["chore"] is None


def test_a_close_after_end_keeps_it_ended(tmp_path: Path) -> None:
    pulse, _ = make_pulse(tmp_path)
    pulse.start()
    meter = pulse.open(WHO)
    pulse.end()
    pulse.close(meter)
    pulse.write()
    assert beat_file(tmp_path)["beat"] == "ended"


def test_a_failed_write_does_not_raise(tmp_path: Path) -> None:
    pulse = live.Pulse(tmp_path / "missing" / "deeper", 20.0, Clock().pace(), pid=1)
    pulse.write()
    pulse.open(WHO)  # also writes


def test_doing_sets_and_restores_the_chore_nested(tmp_path: Path) -> None:
    pulse, clock = make_pulse(tmp_path)
    with pulse.doing("outer"):
        assert beat_file(tmp_path)["chore"] == {"what": "outer", "since": NOW}
        clock.t += 1
        with pulse.doing("inner"):
            assert beat_file(tmp_path)["chore"]["what"] == "inner"
        assert beat_file(tmp_path)["chore"]["what"] == "outer"
    assert beat_file(tmp_path)["chore"] is None


def test_doing_restores_after_an_exception(tmp_path: Path) -> None:
    pulse, _ = make_pulse(tmp_path)
    with pytest.raises(ValueError), pulse.doing("x"):
        raise ValueError
    assert beat_file(tmp_path)["chore"] is None


def test_nested_meters_show_the_innermost(tmp_path: Path) -> None:
    pulse, _ = make_pulse(tmp_path)
    po = pulse.open(live.Who("product-owner", None, None, "opus", Billing.REPORTED))
    role = pulse.open(WHO)
    assert beat_file(tmp_path)["step"]["role"] == "developer-cli"
    pulse.close(role)
    assert beat_file(tmp_path)["step"]["role"] == "product-owner"
    pulse.close(po)
    assert beat_file(tmp_path)["step"] is None


def test_close_removes_a_reading_wherever_it_is(tmp_path: Path) -> None:
    pulse, _ = make_pulse(tmp_path)
    po = pulse.open(live.Who("product-owner", None, None, "opus", Billing.REPORTED))
    pulse.open(WHO)
    pulse.close(po)
    assert beat_file(tmp_path)["step"]["role"] == "developer-cli"
    pulse.close(po)  # twice is harmless


def test_read_heartbeat(tmp_path: Path) -> None:
    assert live.read_heartbeat(tmp_path) is None
    (tmp_path / live.HEARTBEAT).write_text("{torn")
    assert live.read_heartbeat(tmp_path) is None
    (tmp_path / live.HEARTBEAT).write_text("[1]")
    assert live.read_heartbeat(tmp_path) is None
    (tmp_path / live.HEARTBEAT).write_text('{"pid": 3}')
    assert live.read_heartbeat(tmp_path) == {"pid": 3}


# ----- interrupted data --------------------------------------------------------------


def test_interrupted_data_and_event(tmp_path: Path) -> None:
    data = live.interrupted_data(live.Stop(Cause.SIGTERM, "stopped by stop --now"))
    assert data == {
        "status": INTERRUPTED,
        "reason": "exit 143 (SIGTERM)",
        "cause": "sigterm",
        "halt": "stopped by stop --now",
    }
    pulse, _ = make_pulse(tmp_path)
    meter = pulse.open(WHO)
    meter.take(reply("m1", usage(1, 2), model="claude-sonnet-4-5"))
    event = meter.reading.interrupted(live.Stop(Cause.ERROR))
    assert event.kind is EventKind.STEP_END
    assert (event.role, event.story) == ("developer-cli", "s29")
    assert event.data["status"] == INTERRUPTED and event.data["halt"] is None
    assert event.data["turns"] == 1 and event.data["model"] == "claude-sonnet-4-5"
    assert event.data["tokens"] == {"input": 1, "output": 2, "cache_read": 0, "cache_creation": 0}
    assert "cost_usd" not in event.data and "estimate_usd" in event.data


def test_stop_reasons_cover_every_cause() -> None:
    assert set(salvage.STOP_REASONS) == set(Cause)
    assert salvage.STOP_REASONS[Cause.SIGTERM] == "exit 143 (SIGTERM)"
    assert salvage.STOP_REASONS[Cause.KILLED] == "the runner was killed (no clean exit)"
    assert salvage.STOP_REASONS[Cause.LIMIT] == "usage limit"


# ----- health rules (R0-R11) ---------------------------------------------------------


def step(**over: Any) -> dict[str, Any]:
    base = {
        "role": "developer-cli", "story": "s29", "step": "implement", "started_at": NOW - 30,
        "turn": 3, "model": "claude-sonnet-4-5", "configured_model": "sonnet",
        "last_turn_at": NOW - 5, "tool": None, "tokens": {}, "cost_usd": 0.1,
    }  # fmt: skip
    return {**base, **over}


def beat(**over: Any) -> dict[str, Any]:
    base = {"version": 1, "pid": 77, "beat": "beating", "at": NOW - 5, "started_at": NOW - 900}
    return {**base, "chore": None, "step": step(), **over}


def vitals(
    status: RunStatus = RunStatus.RUNNING,
    heartbeat: dict[str, Any] | None = None,
    reason: str | None = None,
    runner: Runner = Runner.UP,
    halt_kind: str | None = None,
) -> Vitals:
    return Vitals(NOW, status, reason, heartbeat, runner, LIMITS, halt_kind)


def test_r11_idle_without_a_heartbeat() -> None:
    verdict = health.judge(vitals(RunStatus.IDLE))
    assert (verdict.level, verdict.reason) == (Level.IDLE, "idle")
    verdict = health.judge(vitals(RunStatus.SPRINT_END, reason="sprint 2 done"))
    assert (verdict.level, verdict.reason) == (Level.IDLE, "sprint 2 done")


def test_r10_green_turns_arriving() -> None:
    verdict = health.judge(vitals(heartbeat=beat()))
    assert (verdict.level, verdict.reason) == (Level.GREEN, "turns arriving")
    assert verdict.key() == "green|turns arriving"


def test_r9_green_chore_and_it_silences_the_quiet_rules() -> None:
    quiet = step(last_turn_at=NOW - 5000)
    chore = {"what": "settling developer-cli on s29", "since": NOW - 120}
    verdict = health.judge(vitals(heartbeat=beat(step=quiet, chore=chore)))
    assert verdict.level is Level.GREEN
    assert verdict.reason == "runner: settling developer-cli on s29 for 2 min"


BASH = {"name": "Bash", "started_at": NOW - 100}


@pytest.mark.parametrize(
    "quiet,tool,level,reason",
    [
        (200, None, Level.GREEN, "turns arriving"),
        (301, None, Level.AMBER, "no turn for 5 min"),
        (181, BASH, Level.AMBER, "no turn for 3 min while Bash runs"),
        (301, BASH, Level.AMBER, "no turn for 5 min while Bash runs"),
        (601, None, Level.RED, "no turn for 10 min"),
        (601, BASH, Level.RED, "no turn for 10 min"),
    ],
)  # fmt: skip
def test_r5_r7_r8_quiet_steps(quiet: int, tool: Any, level: Level, reason: str) -> None:
    heartbeat = beat(step=step(last_turn_at=NOW - quiet, tool=tool))
    verdict = health.judge(vitals(heartbeat=heartbeat))
    assert (verdict.level, verdict.reason) == (level, reason)


def test_quiet_counts_from_the_start_before_the_first_turn() -> None:
    heartbeat = beat(step=step(last_turn_at=None, started_at=NOW - 700))
    assert health.judge(vitals(heartbeat=heartbeat)).level is Level.RED


def test_r6_red_stale_heartbeat_and_words_join_at_the_worst_level() -> None:
    heartbeat = beat(at=NOW - 240, step=step(last_turn_at=NOW - 660))
    verdict = health.judge(vitals(heartbeat=heartbeat))
    assert verdict.level is Level.RED
    assert verdict.reason == "no turn for 11 min, heartbeat 4 min old"


def test_r6_alone() -> None:
    verdict = health.judge(vitals(heartbeat=beat(at=NOW - 91)))
    assert (verdict.level, verdict.reason) == (Level.RED, "heartbeat 1 min old")


def test_r4_dead_runner_and_interrupted_status() -> None:
    gone = health.judge(vitals(heartbeat=beat(), runner=Runner.GONE))
    assert gone.level is Level.RED and "the runner is not running (pid 77)" in gone.reason
    interrupted = health.judge(vitals(RunStatus.INTERRUPTED, heartbeat=beat(pid=None)))
    assert interrupted.level is Level.RED and "the runner is not running" in interrupted.reason
    bare = health.judge(vitals(RunStatus.INTERRUPTED))
    assert bare.reason == "the runner is not running"


@pytest.mark.parametrize(
    "status",
    [RunStatus.BLOCKED, RunStatus.FAILED, RunStatus.STOPPED, RunStatus.CHECKOUT_CHANGED],
)
def test_r2_a_halted_run_is_red_with_its_reason(status: RunStatus) -> None:
    verdict = health.judge(vitals(status, reason="session limit, resets 9pm", halt_kind="limit"))
    assert verdict.level is Level.RED
    assert verdict.reason == "halted: session limit, resets 9pm"
    assert health.judge(vitals(status, halt_kind="limit")).reason == f"halted: {status}"


def test_r3_turns_arriving_while_halted() -> None:
    stopped = vitals(RunStatus.STOPPED, heartbeat=beat(), reason="stop", halt_kind="sigterm")
    verdict = health.judge(stopped)
    assert verdict.reason == "halted: stop, turns arriving while the run is stopped"


def test_an_ended_heartbeat_is_not_beating() -> None:
    v = vitals(heartbeat=beat(beat="ended"))
    assert not v.beating and v.step is None and v.chore is None and v.quiet_for is None
    assert health.judge(v).level is Level.IDLE


def test_vitals_derived_values() -> None:
    v = vitals(heartbeat=beat(at=NOW - 12, step=step(last_turn_at=NOW - 40, tool={"name": "X"})))
    assert v.beating and v.beat_age == 12 and v.quiet_for == 40 and v.pid == 77
    assert v.tool == {"name": "X"} and not v.halted
    assert vitals(RunStatus.BLOCKED).halted


def test_the_judgement_carries_the_model_note() -> None:
    heartbeat = beat(step=step(model="claude-opus-4"))
    assert (
        health.judge(vitals(heartbeat=heartbeat)).model_note == "configured sonnet, answering opus"
    )


def test_every_rule_level_is_ranked_and_the_last_row_always_matches() -> None:
    assert health.RANK[Level.IDLE] < health.RANK[Level.GREEN]
    assert health.RANK[Level.GREEN] < health.RANK[Level.AMBER] < health.RANK[Level.RED]
    assert health.RULES[-1].level is Level.IDLE and health.RULES[-1].test(vitals())
    assert len(health.RULES) == 12


def test_read_vitals_from_disk(configured: Path) -> None:
    from agile_team import state as state_mod

    config = cfg.load(configured)
    config.run_dir.mkdir(parents=True, exist_ok=True)
    state = state_mod.RunState()
    state.mark(RunStatus.RUNNING)
    state_mod.save(config.run_dir, state)
    assert health.Vitals.read(config, health.Clock(NOW)).runner is Runner.UP
    (config.run_dir / live.HEARTBEAT).write_text(json.dumps(beat(pid=2_000_000_000)))
    assert health.Vitals.read(config, health.Clock(NOW)).runner is Runner.GONE
    current = health.current(config)
    assert current.level is Level.RED


# ----- config ------------------------------------------------------------------------


def test_health_defaults_and_reading(tmp_path: Path) -> None:
    default = cfg.from_raw(tmp_path, {}).health
    assert (default.beat_s, default.stale_s, default.amber_tool_s) == (20.0, 90.0, 180.0)
    assert (default.amber_quiet_s, default.red_quiet_s) == (300.0, 600.0)
    raw = {"health": {"beat_s": 5, "stale_s": 30, "red_quiet_s": 900}}
    read = cfg.from_raw(tmp_path, raw).health
    assert (read.beat_s, read.stale_s, read.red_quiet_s) == (5, 30, 900)
    assert read.amber_tool_s == 180.0


KNOWN = cfg.Known({"developer"}, {"package"})


@pytest.mark.parametrize(
    "key", ["beat_s", "stale_s", "amber_tool_s", "amber_quiet_s", "red_quiet_s"]
)
@pytest.mark.parametrize("bad", [0, -1])
def test_health_values_must_be_positive(tmp_path: Path, key: str, bad: int) -> None:
    config = cfg.from_raw(tmp_path, {"health": {key: bad}})
    assert f"health.{key} must be positive" in cfg.validate(config, KNOWN)


def test_health_cross_checks(tmp_path: Path) -> None:
    config = cfg.from_raw(tmp_path, {"health": {"beat_s": 90, "stale_s": 90}})
    assert "health.beat_s must be below health.stale_s" in cfg.validate(config, KNOWN)
    config = cfg.from_raw(tmp_path, {"health": {"amber_quiet_s": 700}})
    problems = cfg.validate(config, KNOWN)
    assert (
        "health.amber_tool_s and health.amber_quiet_s must not exceed health.red_quiet_s"
        in problems
    )
    assert not [p for p in cfg.validate(cfg.from_raw(tmp_path, {}), KNOWN) if "health" in p]


def test_providers_billing() -> None:
    from agile_team.providers import DEFAULT, Provider, Providers

    free = Provider("local", "http://x", billing=Billing.FREE)
    providers = Providers({"local": free})
    assert providers.billing(SimpleNamespace(provider=DEFAULT)) is Billing.REPORTED
    assert providers.billing(SimpleNamespace(provider="local")) is Billing.FREE

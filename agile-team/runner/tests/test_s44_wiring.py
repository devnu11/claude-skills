"""s44: interrupted step-ends, recovery, insights, snapshot sections, server push, URLs, watch."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from agile_team import cli, live, recovery, system, watch
from agile_team import config as cfg
from agile_team import state as state_mod
from agile_team.dashboard import server, snapshot
from agile_team.dispatch import StepRequest
from agile_team.events import INTERRUPTED, Event, EventKind
from agile_team.insights import friction_since_review
from agile_team.salvage import Cause, InFlight
from agile_team.state import RunState, RunStatus

from .conftest import FakeQuery, result_message
from .fake_system import FAKE_HOSTNAME, FAKE_IDS, FREE_PORT, Done, FakeSystem
from .test_s9 import STEP, dirty, limit_error, open_story, raising_action, run_step
from .test_snapshot import book_for, make_config, write_jsonl

NOW = 1_800_000_000.0
FAMILY_USAGE = {"input_tokens": 2, "output_tokens": 9}


def ends(rt: Any) -> list[Event]:
    return [e for e in rt.events.events() if e.kind is EventKind.STEP_END]


# ----- runtime: meter per step, one step-end per step-start (I1-I3) ------------------


def test_a_step_with_an_error_closes_with_one_interrupted_end(make_runtime) -> None:
    from claude_agent_sdk import AssistantMessage, TextBlock

    holder: list = []

    class Query(FakeQuery):
        async def _gen(self):
            yield AssistantMessage(
                content=[TextBlock(text="a")], model="claude-sonnet-4-5",
                usage=FAMILY_USAGE, message_id="m1",
            )  # fmt: skip
            raising_action(holder, ValueError("boom"))()
            yield result_message("x")

    rt = make_runtime(Query())
    holder.append(rt)
    open_story(rt)
    with pytest.raises(ValueError):
        run_step(rt)
    (end,) = ends(rt)
    assert end.role == "architect" and end.story == "s1"
    assert end.data["status"] == INTERRUPTED and end.data["cause"] == "error"
    assert end.data["reason"] == "error in the step (details in crash.log)"
    assert end.data["turns"] == 1 and end.data["tokens"]["output"] == 9
    assert end.data["halt"] is None and "cost_usd" not in end.data
    assert rt.step_meter is None
    assert live.read_heartbeat(rt.config.run_dir)["step"] is None


def test_a_limit_halt_closes_the_step_with_the_halt_reason(make_runtime) -> None:
    holder: list = []
    rt = make_runtime(FakeQuery(action=raising_action(holder, limit_error())))
    holder.append(rt)
    open_story(rt)
    assert run_step(rt)["status"] == "halted"
    (end,) = ends(rt)
    assert end.data["cause"] == "limit" and end.data["reason"] == "usage limit"
    assert end.data["halt"] == rt.halted_by.reason


def test_sigterm_through_halt_exit_says_exit_143(make_runtime) -> None:
    rt = make_runtime()
    open_story(rt)
    rt.state.in_flight = STEP
    rt.step_meter = rt.pulse.open(rt.who(rt.plan(StepRequest("architect", "go", "s1"))))
    cli._halt_exit(rt, asyncio.CancelledError())
    (end,) = ends(rt)
    assert end.data["reason"] == "exit 143 (SIGTERM)" and end.data["cause"] == "sigterm"


def test_a_checkout_halt_still_closes_the_step(make_runtime, fake: FakeSystem) -> None:
    rt = make_runtime()
    open_story(rt)
    rt.step_meter = rt.pulse.open(rt.who(rt.plan(StepRequest("architect", "go", "s1"))))
    fake.reply(("git", "symbolic-ref"), Done(0, "elsewhere\n"))
    rt.save_interrupted(Cause.CHECKOUT)
    (end,) = ends(rt)
    assert end.data["cause"] == "checkout" and end.data["status"] == INTERRUPTED


def test_a_settled_step_emits_no_second_end(make_runtime) -> None:
    rt = make_runtime()
    open_story(rt)
    run_step(rt)
    before = len(ends(rt))
    assert before == 1 and ends(rt)[0].data.get("status") != INTERRUPTED
    assert ends(rt)[0].data["model"] == "m"
    rt.save_interrupted(Cause.CRASH)
    assert len(ends(rt)) == before


def test_settle_runs_as_a_chore(make_runtime, monkeypatch) -> None:
    rt = make_runtime()
    open_story(rt)
    seen: list[Any] = []
    real = rt._settle

    def spy(plan, result):
        seen.append(live.read_heartbeat(rt.config.run_dir)["chore"])
        return real(plan, result)

    monkeypatch.setattr(rt, "_settle", spy)
    run_step(rt)
    assert seen[0]["what"] == "settling architect on s1"
    assert live.read_heartbeat(rt.config.run_dir)["chore"] is None


def test_a_role_step_turns_land_in_turns_jsonl(make_runtime) -> None:
    rt = make_runtime()
    open_story(rt)
    run_step(rt)
    lines = [
        json.loads(x) for x in system.read_text(rt.config.run_dir / "turns.jsonl").splitlines()
    ]
    assert lines == [] or all(x["role"] == "architect" and x["story"] == "s1" for x in lines)


# ----- recovery (I4) and insights (I6) -----------------------------------------------


def test_recover_cut_of_a_killed_run_closes_the_step(configured: Path, make_runtime) -> None:
    rt = make_runtime()
    open_story(rt)
    rt.state.in_flight = InFlight("developer-cli", "s1", "build it")
    rt.state.mark(RunStatus.RUNNING)
    state_mod.save(rt.config.run_dir, rt.state)
    dirty(configured)
    assert recovery.recover_cut(rt.config.run_dir, rt.git) is not None
    (end,) = ends(rt)
    assert (end.role, end.story) == ("developer-cli", "s1")
    assert end.data == live.interrupted_data(live.Stop(Cause.KILLED))
    assert end.data["reason"] == "the runner was killed (no clean exit)"


def test_recover_cut_without_a_step_emits_no_end(configured: Path, make_runtime) -> None:
    rt = make_runtime()
    rt.state.mark(RunStatus.RUNNING)
    state_mod.save(rt.config.run_dir, rt.state)
    dirty(configured)
    recovery.recover_cut(rt.config.run_dir, rt.git)
    assert ends(rt) == []


def test_an_interrupted_manager_end_is_not_a_review() -> None:
    work = Event(EventKind.STEP_END, "developer-cli", "s1", {"friction": "slow"})
    cut = Event(EventKind.STEP_END, "manager", None, {"status": INTERRUPTED})
    done = Event(EventKind.STEP_END, "manager", None, {"status": "done"})
    assert friction_since_review([work, cut]) == [
        {"role": "developer-cli", "story": "s1", "friction": "slow"}
    ]
    assert friction_since_review([work, done]) == []


# ----- snapshot (S1-S5) --------------------------------------------------------------


def built(scratch: Path, **extra: Any) -> tuple[cfg.Config, dict[str, Any]]:
    config = make_config(scratch / "repo", **extra)
    return config, json.loads(json.dumps(snapshot.build(config, book_for(config, scratch))))


def test_snapshot_has_the_new_sections_in_order(scratch: Path) -> None:
    _, snap = built(scratch)
    keys = list(snap)
    assert keys.index("upstream") < keys.index("turns") < keys.index("heartbeat")
    assert keys.index("heartbeat") < keys.index("health")
    assert snap["turns"] == [] and snap["heartbeat"] is None
    assert snap["health"] == {"level": "idle", "reason": "idle", "model_note": None}


def test_run_files_watch_heartbeat_and_turns(scratch: Path) -> None:
    config = make_config(scratch / "repo")
    names = {p.name for p in snapshot.watched_files(config)}
    assert {"heartbeat.json", "turns.jsonl"} <= names


def test_turns_keep_the_window_and_cap(scratch: Path) -> None:
    config = make_config(scratch / "repo")
    rows = [{"at": NOW - 601, "turn": 0}, {"at": NOW - 600, "turn": 1}, {"at": NOW - 5, "turn": 2}]
    write_jsonl(config.run_dir / "turns.jsonl", rows)
    system.append_text(config.run_dir / "turns.jsonl", "{torn\n[1]\n")
    snap = snapshot.build(config, book_for(config, scratch))
    assert [t["turn"] for t in snap["turns"]] == [1, 2]
    assert snap["generated_at"] == NOW
    many = [{"at": NOW - 1, "turn": i} for i in range(600)]
    write_jsonl(config.run_dir / "turns.jsonl", many)
    turns = snapshot.build(config, book_for(config, scratch))["turns"]
    assert len(turns) == snapshot.TURNS_SHOWN == 500 and turns[-1]["turn"] == 599


def test_read_tail_drops_a_partial_first_line(scratch: Path) -> None:
    path = scratch / "t.jsonl"
    rows = [{"at": 1, "n": i, "pad": "x" * 40} for i in range(20)]
    write_jsonl(path, rows)
    whole = snapshot.read_tail(path, 1_000_000)
    assert whole == rows
    tail = snapshot.read_tail(path, 200)
    assert tail and tail[-1] == rows[-1] and len(tail) < 20
    assert all(isinstance(x, dict) for x in tail)
    assert snapshot.read_tail(scratch / "missing.jsonl", 100) == []


def test_heartbeat_section_and_health_match_judge(scratch: Path) -> None:
    config = make_config(scratch / "repo")
    state_mod.save(config.run_dir, RunState(status=RunStatus.RUNNING))
    system.write_text(config.run_dir / "runner.pid", str(FAKE_IDS[0]))
    beat = {
        "version": 1, "pid": FAKE_IDS[0], "beat": "beating", "at": NOW - 2,
        "started_at": NOW - 99, "chore": None,
        "step": {
            "role": "architect", "story": "s1", "step": "design", "started_at": NOW - 50,
            "turn": 2, "model": "claude-opus-4", "configured_model": "sonnet",
            "last_turn_at": NOW - 3, "tool": None, "tokens": {}, "cost_usd": 0.0,
        },
    }  # fmt: skip
    system.write_text(config.run_dir / "heartbeat.json", json.dumps(beat))
    snap = snapshot.build(config, book_for(config, scratch))
    assert snap["heartbeat"] == beat
    assert snap["health"] == {
        "level": "green", "reason": "turns arriving",
        "model_note": "configured sonnet, answering opus",
    }  # fmt: skip
    system.write_text(config.run_dir / "heartbeat.json", "{torn")
    assert snapshot.build(config, book_for(config, scratch))["heartbeat"] is None


def test_vital_sign_is_the_level_and_reason(scratch: Path) -> None:
    config = make_config(scratch / "repo")
    state = RunState(status=RunStatus.STOPPED, status_reason="stop --now", halt_kind="sigterm")
    state_mod.save(config.run_dir, state)
    assert snapshot.vital_sign(config) == "red|halted: stop --now"


# ----- server: push on verdict change, URLs (S6, S7) ---------------------------------


class Stop(Exception):
    pass


class Sink:
    def __init__(self, stop_after: int) -> None:
        self.writes: list[bytes] = []
        self.stop_after = stop_after

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        if len(self.writes) == self.stop_after:
            raise Stop
        return len(data)

    def flush(self) -> None:
        pass


def test_pump_pushes_when_only_the_vital_sign_changes(scratch: Path) -> None:
    file = scratch / "f"
    system.write_text(file, "x")
    signs = iter(["green|a", "green|a", "red|b", "red|b", "red|b"])
    snaps = iter(range(10))
    app = server.Dashboard(
        lambda: {"n": next(snaps)}, lambda: [file], poll_seconds=0.0, vital_sign=lambda: next(signs)
    )
    out = Sink(5)
    with pytest.raises(Stop):
        server._pump(out, app)
    assert out.writes[:4] == [
        server.sse_data({"n": 0}), server.KEEPALIVE, server.sse_data({"n": 1}), server.KEEPALIVE,
    ]  # fmt: skip


def test_vital_sign_defaults_to_blank_and_for_run_wires_it(scratch: Path) -> None:
    assert server.Dashboard(lambda: {}, lambda: []).vital_sign() == ""
    config = make_config(scratch / "repo")
    app = server.Dashboard.for_run(config, book_for(config, scratch))
    assert app.vital_sign() == "idle|idle"


def test_lan_name(monkeypatch: pytest.MonkeyPatch) -> None:
    assert server.lan_name() == f"{FAKE_HOSTNAME}.local"
    monkeypatch.setattr(system, "hostname", lambda: "labbox.example.org")
    assert server.lan_name() == "labbox.example.org"


def test_dashboard_urls() -> None:
    expected = server.Urls("http://localhost:8765/", f"http://{FAKE_HOSTNAME}.local:8765/")
    assert server.dashboard_urls("0.0.0.0", 8765) == expected
    assert server.dashboard_urls("", 8765) == expected
    for loop in ("127.0.0.1", "localhost", "::1"):
        assert server.dashboard_urls(loop, 9) == server.Urls("http://localhost:9/", None)
    assert server.dashboard_urls("10.0.0.5", 9) == server.Urls("http://10.0.0.5:9/", None)
    assert not hasattr(server, "display_url")


def test_cmd_dashboard_prints_both_links_and_opens_local(
    configured: Path, capsys, fake: FakeSystem
) -> None:
    from .test_cli import dashboard_args

    args = dashboard_args(configured, "--host", "0.0.0.0", "--port", "0")
    assert cli.cmd_dashboard(args) == 0
    assert capsys.readouterr().out == (
        f"dashboard: http://localhost:{FREE_PORT}/\n"
        f"from other machines: http://{FAKE_HOSTNAME}.local:{FREE_PORT}/\n"
    )
    assert fake.opened == [f"http://localhost:{FREE_PORT}/"]


# ----- watch: the health trigger (W1, W2) --------------------------------------------


def test_health_trigger_fires_on_a_change_into_red() -> None:
    names = [name for name, _ in watch.TRIGGERS]
    assert names == ["message", "status", "health"]
    red = watch.Look([], "running", None, "red")
    assert watch.fired(watch.Seen(health="green"), red) == ["health"]
    assert watch.fired(watch.Seen(health=""), red) == ["health"]
    assert watch.fired(watch.Seen(health="red"), red) == []
    amber = watch.Look([], "running", None, "amber")
    assert watch.fired(watch.Seen(health="green"), amber) == []


def test_watch_memory_and_line_carry_health(scratch: Path) -> None:
    now = watch.Look([], "running", None, "red")
    assert now.seen().health == "red"
    path = scratch / "w.json"
    now.seen().save(path)
    assert watch.Seen.load(path).health == "red"
    line = watch.line(["health"], watch.Basis(watch.Seen(), now))
    assert line["health"]["level"] == "red"


def test_look_reads_health_from_the_run(configured: Path) -> None:
    config = cfg.load(configured)
    state = RunState(status=RunStatus.STOPPED, status_reason="stop", halt_kind="sigterm")
    state_mod.save(config.run_dir, state)
    found = watch.look(config.run_dir)
    assert found is not None and found.health == "red"

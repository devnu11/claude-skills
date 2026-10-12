"""s44: interrupted step-ends, recovery, insights, snapshot sections, server push, URLs, watch."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from agile_team import cli, live, recovery, watch
from agile_team import config as cfg
from agile_team import state as state_mod
from agile_team.dashboard import server, snapshot
from agile_team.dispatch import StepRequest
from agile_team.events import INTERRUPTED, Event, EventKind
from agile_team.insights import friction_since_review
from agile_team.salvage import Cause, InFlight
from agile_team.state import RunState, RunStatus

from .conftest import FakeQuery, git, result_message
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


def test_a_checkout_halt_still_closes_the_step(make_runtime) -> None:
    rt = make_runtime()
    open_story(rt)
    rt.step_meter = rt.pulse.open(rt.who(rt.plan(StepRequest("architect", "go", "s1"))))
    git(rt.config.repo, "checkout", "-q", "-b", "elsewhere")
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
    lines = [json.loads(x) for x in (rt.config.run_dir / "turns.jsonl").read_text().splitlines()]
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


def built(tmp_path: Path, **extra: Any) -> tuple[cfg.Config, dict[str, Any]]:
    config = make_config(tmp_path / "repo", **extra)
    return config, json.loads(json.dumps(snapshot.build(config, book_for(config, tmp_path))))


def test_snapshot_has_the_new_sections_in_order(tmp_path: Path) -> None:
    _, snap = built(tmp_path)
    keys = list(snap)
    assert keys.index("upstream") < keys.index("turns") < keys.index("heartbeat")
    assert keys.index("heartbeat") < keys.index("health")
    assert snap["turns"] == [] and snap["heartbeat"] is None
    assert snap["health"] == {"level": "idle", "reason": "idle", "model_note": None}


def test_run_files_watch_heartbeat_and_turns(tmp_path: Path) -> None:
    config = make_config(tmp_path / "repo")
    names = {p.name for p in snapshot.watched_files(config)}
    assert {"heartbeat.json", "turns.jsonl"} <= names


def test_turns_keep_the_window_and_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = make_config(tmp_path / "repo")
    monkeypatch.setattr("time.time", lambda: NOW)
    rows = [{"at": NOW - 601, "turn": 0}, {"at": NOW - 600, "turn": 1}, {"at": NOW - 5, "turn": 2}]
    write_jsonl(config.run_dir / "turns.jsonl", rows)
    with (config.run_dir / "turns.jsonl").open("a") as out:
        out.write("{torn\n[1]\n")
    snap = snapshot.build(config, book_for(config, tmp_path))
    assert [t["turn"] for t in snap["turns"]] == [1, 2]
    assert snap["generated_at"] == NOW
    many = [{"at": NOW - 1, "turn": i} for i in range(600)]
    write_jsonl(config.run_dir / "turns.jsonl", many)
    turns = snapshot.build(config, book_for(config, tmp_path))["turns"]
    assert len(turns) == snapshot.TURNS_SHOWN == 500 and turns[-1]["turn"] == 599


def test_read_tail_drops_a_partial_first_line(tmp_path: Path) -> None:
    path = tmp_path / "t.jsonl"
    rows = [{"at": 1, "n": i, "pad": "x" * 40} for i in range(20)]
    write_jsonl(path, rows)
    whole = snapshot.read_tail(path, 1_000_000)
    assert whole == rows
    tail = snapshot.read_tail(path, 200)
    assert tail and tail[-1] == rows[-1] and len(tail) < 20
    assert all(isinstance(x, dict) for x in tail)
    assert snapshot.read_tail(tmp_path / "missing.jsonl", 100) == []


def test_heartbeat_section_and_health_match_judge(tmp_path: Path, monkeypatch) -> None:
    config = make_config(tmp_path / "repo")
    monkeypatch.setattr("time.time", lambda: NOW)
    state_mod.save(config.run_dir, RunState(status=RunStatus.RUNNING))
    (config.run_dir / "runner.pid").write_text(str(os.getpid()))
    beat = {
        "version": 1, "pid": os.getpid(), "beat": "beating", "at": NOW - 2,
        "started_at": NOW - 99, "chore": None,
        "step": {
            "role": "architect", "story": "s1", "step": "design", "started_at": NOW - 50,
            "turn": 2, "model": "claude-opus-4", "configured_model": "sonnet",
            "last_turn_at": NOW - 3, "tool": None, "tokens": {}, "cost_usd": 0.0,
        },
    }  # fmt: skip
    (config.run_dir / "heartbeat.json").write_text(json.dumps(beat))
    snap = snapshot.build(config, book_for(config, tmp_path))
    assert snap["heartbeat"] == beat
    assert snap["health"] == {
        "level": "green", "reason": "turns arriving",
        "model_note": "configured sonnet, answering opus",
    }  # fmt: skip
    (config.run_dir / "heartbeat.json").write_text("{torn")
    assert snapshot.build(config, book_for(config, tmp_path))["heartbeat"] is None


def test_vital_sign_is_the_level_and_reason(tmp_path: Path) -> None:
    config = make_config(tmp_path / "repo")
    state_mod.save(config.run_dir, RunState(status=RunStatus.STOPPED, status_reason="stop --now"))
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


def test_pump_pushes_when_only_the_vital_sign_changes(tmp_path: Path) -> None:
    file = tmp_path / "f"
    file.write_text("x")
    signs = iter(["green|a", "green|a", "red|b", "red|b"])
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


def test_vital_sign_defaults_to_blank_and_for_run_wires_it(tmp_path: Path) -> None:
    assert server.Dashboard(lambda: {}, lambda: []).vital_sign() == ""
    config = make_config(tmp_path / "repo")
    app = server.Dashboard.for_run(config, book_for(config, tmp_path))
    assert app.vital_sign() == "idle|idle"


def test_lan_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("socket.gethostname", lambda: "labbox")
    assert server.lan_name() == "labbox.local"
    monkeypatch.setattr("socket.gethostname", lambda: "labbox.example.org")
    assert server.lan_name() == "labbox.example.org"


def test_dashboard_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("socket.gethostname", lambda: "labbox")
    expected = server.Urls("http://localhost:8765/", "http://labbox.local:8765/")
    assert server.dashboard_urls("0.0.0.0", 8765) == expected
    assert server.dashboard_urls("", 8765) == expected
    for loop in ("127.0.0.1", "localhost", "::1"):
        assert server.dashboard_urls(loop, 9) == server.Urls("http://localhost:9/", None)
    assert server.dashboard_urls("10.0.0.5", 9) == server.Urls("http://10.0.0.5:9/", None)
    assert not hasattr(server, "display_url")


def test_cmd_dashboard_prints_both_links_and_opens_local(
    configured: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    from .test_cli import dashboard_args

    monkeypatch.setattr("socket.gethostname", lambda: "labbox")
    opened: list[str] = []
    ports: list[int] = []

    def serve(httpd) -> None:
        ports.append(httpd.server_address[1])
        httpd.server_close()

    io = cli.DashboardIO(browse=opened.append, serve=serve)
    args = dashboard_args(configured, "--host", "0.0.0.0", "--port", "0")
    assert cli.cmd_dashboard(args, io) == 0
    port = ports[0]
    assert capsys.readouterr().out == (
        f"dashboard: http://localhost:{port}/\nfrom other machines: http://labbox.local:{port}/\n"
    )
    assert opened == [f"http://localhost:{port}/"]


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


def test_watch_memory_and_line_carry_health(tmp_path: Path) -> None:
    now = watch.Look([], "running", None, "red")
    assert now.seen().health == "red"
    path = tmp_path / "w.json"
    now.seen().save(path)
    assert watch.Seen.load(path).health == "red"
    line = watch.line(["health"], watch.Basis(watch.Seen(), now))
    assert line["health"]["level"] == "red"


def test_look_reads_health_from_the_run(configured: Path) -> None:
    config = cfg.load(configured)
    state_mod.save(config.run_dir, RunState(status=RunStatus.STOPPED, status_reason="stop"))
    found = watch.look(config.run_dir)
    assert found is not None and found.health == "red"

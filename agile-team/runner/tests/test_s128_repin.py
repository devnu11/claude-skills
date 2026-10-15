"""s128 AC2: the runner re-pins itself at a sprint end, or rolls back (P1-P11)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agile_team import cli, repin, system
from agile_team import state as state_mod
from agile_team.boundary import Edge, Stage
from agile_team.events import EventKind
from agile_team.repin import Marker, Outcome, Pin, RepinError
from agile_team.router import Router
from agile_team.state import RunStatus

from .conftest import FakeQuery
from .fake_system import FAKE_HEAD, Done, Exec, FakeSystem, Hang
from .test_boundary_runner import Env
from .test_cli import any_tool, start_args

OLD = "0" * 40
NEW = "1" * 40
UV = "/bin/uv"


@pytest.fixture
def run_dir(configured: Path) -> Path:
    return configured / ".team/run"


@pytest.fixture
def pin_dir(run_dir: Path) -> Path:
    return run_dir / "runner-pin"


@pytest.fixture
def pinned(monkeypatch: pytest.MonkeyPatch, fake: FakeSystem, run_dir: Path, pin_dir: Path):
    """This runner runs from the pin, whose commit file says ``OLD``."""
    monkeypatch.setattr(repin, "PACKAGE_DIR", pin_dir / "agile_team")
    fake.put(run_dir / "runner-pin.commit", OLD + "\n")
    fake.programs["uv"] = UV


def exe(pin_dir: Path) -> str:
    return str(pin_dir / ".venv/bin/agile-team")


def argv_of(fake: FakeSystem) -> list[tuple[str, ...]]:
    return [tuple(c.argv) for c in fake.commands if c.argv[0] in ("sh", UV)]


def swapped(fake: FakeSystem, run_dir: Path) -> None:
    """Pretend the pin script ran: the commit file now says ``NEW``."""
    fake.put(run_dir / "runner-pin.commit", NEW + "\n")


def trial() -> Marker:
    return Marker(OLD, NEW, 2, Outcome.TRIAL)


# ----- P1, P11: what the pin is ---------------------------------------------------------------


def test_the_constants() -> None:
    assert (repin.PIN_DIR, repin.COMMIT_FILE, repin.MARKER_FILE) == (
        "runner-pin",
        "runner-pin.commit",
        "repin.json",
    )
    assert repin.PIN_SCRIPT == "agile-team/runner/scripts/pin-runner.sh"
    assert repin.PIN_EXE == ".venv/bin/agile-team"
    assert (repin.PIN_TIMEOUT_S, repin.CHECK_TIMEOUT_S) == (300.0, 600.0)
    assert [o.value for o in Outcome] == ["trial", "pinned", "rolled_back"]


def test_pinned_is_true_only_inside_the_pin(pinned, run_dir: Path, monkeypatch) -> None:
    assert repin.pinned(run_dir) is True
    monkeypatch.setattr(repin, "PACKAGE_DIR", Path("/elsewhere/agile_team"))
    assert repin.pinned(run_dir) is False


def test_pin_commit_is_stripped_or_empty(fake: FakeSystem, run_dir: Path) -> None:
    assert repin.pin_commit(run_dir) == ""
    fake.put(run_dir / "runner-pin.commit", f" {OLD}\n")
    assert repin.pin_commit(run_dir) == OLD


def test_due_needs_a_pin_and_a_new_head(pinned, run_dir: Path, monkeypatch) -> None:
    assert repin.due(run_dir, NEW) is True
    assert repin.due(run_dir, OLD) is False
    monkeypatch.setattr(repin, "PACKAGE_DIR", Path("/elsewhere"))
    assert repin.due(run_dir, NEW) is False


def test_the_marker_round_trips(fake: FakeSystem, run_dir: Path) -> None:
    assert repin.read_marker(run_dir) is None
    marker = Marker(OLD, NEW, 3, Outcome.ROLLED_BACK, "why")
    repin.write_marker(run_dir, marker)
    assert repin.read_marker(run_dir) == marker
    assert json.loads(fake.text_of(run_dir / "repin.json")) == {
        "old": OLD,
        "new": NEW,
        "sprint": 3,
        "outcome": "rolled_back",
        "reason": "why",
    }
    assert marker.data()["outcome"] == "rolled_back"
    assert Marker(OLD, NEW, 1, Outcome.TRIAL).data()["reason"] == ""


@pytest.mark.parametrize("text", ["{nope", "[]", '{"old": "x"}'])
def test_a_marker_that_does_not_parse_is_absent(fake: FakeSystem, run_dir: Path, text) -> None:
    fake.put(run_dir / "repin.json", text)
    assert repin.read_marker(run_dir) is None


def test_start_argv(configured: Path) -> None:
    assert repin.start_argv(configured, None) == ("start", "--resume", "--repo", str(configured))
    assert repin.start_argv(configured, "/h") == (
        "start",
        "--resume",
        "--repo",
        str(configured),
        "--home",
        "/h",
    )


def test_the_event_kind() -> None:
    assert EventKind.RUNNER_REPIN == "runner-repin"


# ----- P2: when the boundary asks -------------------------------------------------------------


def check_end(env: Env, edge: Edge = Edge.END) -> None:
    env.open(edge, stage=Stage.CHECK)
    env.br.step()


def test_a_passing_end_check_on_a_pinned_runner_asks_to_repin(pinned, make_runtime) -> None:
    env = Env(make_runtime)
    check_end(env)
    assert env.rt.state.repin == FAKE_HEAD
    assert env.rt.state.boundary is not None and env.rt.state.boundary.stage is not Stage.CHECK


def test_the_already_checked_branch_asks_too(pinned, make_runtime) -> None:
    env = Env(make_runtime)
    env.rt.state.upstream.checked = FAKE_HEAD
    check_end(env)
    assert env.events()[-1].data["note"] == f"already checked at {FAKE_HEAD}"
    assert env.rt.state.repin == FAKE_HEAD


def test_a_failing_check_asks_for_nothing(pinned, make_runtime) -> None:
    env = Env(make_runtime)
    env.runner.results = {"ruff check .": (1, "E501")}
    check_end(env)
    assert env.rt.state.repin == ""


def test_the_start_edge_never_repins(pinned, make_runtime) -> None:
    env = Env(make_runtime)
    check_end(env, Edge.START)
    assert env.rt.state.repin == ""


def test_an_unpinned_runner_never_repins(
    pinned, make_runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(repin, "PACKAGE_DIR", Path("/skills/agile_team"))
    env = Env(make_runtime)
    check_end(env)
    assert env.rt.state.repin == ""


def test_a_head_equal_to_the_pin_asks_for_nothing(pinned, make_runtime, fake, run_dir) -> None:
    fake.put(run_dir / "runner-pin.commit", FAKE_HEAD)
    env = Env(make_runtime)
    check_end(env)
    assert env.rt.state.repin == ""


def test_a_skipped_boundary_does_not_repin(pinned, make_runtime, fake: FakeSystem) -> None:
    fake.reply(("git", "remote", "get-url"), Done(2))
    env = Env(make_runtime)
    env.open(Edge.END)
    env.drive()
    assert env.rt.state.repin == ""


# ----- P3: the loop ends, then the exec -------------------------------------------------------


def test_a_repin_request_ends_the_router_loop(make_runtime) -> None:
    rt = make_runtime()
    assert Router(rt)._ended() is False
    rt.state.repin = NEW
    assert Router(rt)._ended() is True


def test_an_unpinned_start_drops_the_request(make_runtime, monkeypatch) -> None:
    rt = make_runtime()
    monkeypatch.setattr(repin, "PACKAGE_DIR", Path("/skills/agile_team"))
    rt.state.repin = NEW
    repin.drop_unpinned(rt)
    assert rt.state.repin == ""
    assert state_mod.load(rt.config.run_dir).repin == ""


def test_a_pinned_start_keeps_the_request(pinned, make_runtime) -> None:
    rt = make_runtime()
    rt.state.repin = NEW
    repin.drop_unpinned(rt)
    assert rt.state.repin == NEW


def resume_with_request(configured: Path, key_home: Path, run_dir: Path, fake: FakeSystem):
    any_tool(fake)
    cli.cmd_start(start_args(configured, key_home, "--task", "go"), FakeQuery())
    st = state_mod.load(run_dir)
    st.repin, st.sprint = NEW, 2
    state_mod.save(run_dir, st)
    return start_args(configured, key_home, "--resume")


def test_the_start_pins_checks_and_execs_in_order(
    pinned,
    configured: Path,
    key_home: Path,
    run_dir: Path,
    pin_dir: Path,
    fake: FakeSystem,
    monkeypatch,
) -> None:
    args = resume_with_request(configured, key_home, run_dir, fake)
    seen: list[bool] = []
    runner = fake.run

    def watching(command):
        seen.append(system.exists(run_dir / "runner.pid"))
        return runner(command)

    monkeypatch.setattr(system, "run", watching)
    with pytest.raises(Exec):
        cli.cmd_start(args, FakeQuery())
    assert argv_of(fake) == [
        ("sh", str(configured / repin.PIN_SCRIPT), NEW),
        (
            UV,
            "run",
            "--frozen",
            "--quiet",
            "--project",
            str(pin_dir),
            "agile-team",
            "config",
            "check",
            "--repo",
            str(configured),
        ),
    ]
    assert seen == [False, False]
    assert fake.execs == [
        (exe(pin_dir), "start", "--resume", "--repo", str(configured), "--home", str(key_home))
    ]
    timeouts = [c.timeout for c in fake.commands if c.argv[0] in ("sh", UV)]
    assert timeouts == [repin.PIN_TIMEOUT_S, repin.CHECK_TIMEOUT_S]
    assert repin.read_marker(run_dir) == Marker(OLD, NEW, 2, Outcome.TRIAL)
    saved = state_mod.load(run_dir)
    assert saved.repin == "" and saved.status is RunStatus.IDLE
    assert saved.status_reason == repin.REPINNING.format(new7=NEW[:7])


def test_a_stop_request_keeps_the_request_and_does_not_repin(
    pinned, make_runtime, fake: FakeSystem, configured: Path
) -> None:
    rt = make_runtime()
    rt.state.repin = NEW
    system.make_dirs(rt.config.run_dir)
    system.write_text(rt.config.run_dir / "stop", "")
    assert cli._repin_or(0, rt, Pin(configured, ("start",))) == 0
    assert rt.state.repin == NEW and fake.execs == [] and argv_of(fake) == []


def test_a_failed_exit_or_a_halt_does_not_repin(pinned, make_runtime, fake, configured) -> None:
    rt = make_runtime()
    rt.state.repin = NEW
    assert cli._repin_or(1, rt, Pin(configured, ("start",))) == 1
    rt.halted_by = object()
    assert cli._repin_or(0, rt, Pin(configured, ("start",))) == 0
    assert fake.execs == [] and rt.state.repin == NEW


# ----- P4, P8: the roll back ------------------------------------------------------------------


def run_repin(configured: Path, run_dir: Path) -> None:
    Pin(configured, repin.start_argv(configured, None)).repin(Marker(OLD, NEW, 2, Outcome.TRIAL))


def rollback_argv(configured: Path) -> tuple[str, ...]:
    return ("sh", str(configured / repin.PIN_SCRIPT), "--rollback")


def start_tuple(configured: Path) -> tuple[str, ...]:
    return ("start", "--resume", "--repo", str(configured))


def test_a_clean_repin_execs_the_new_pin(pinned, configured, run_dir, pin_dir, fake) -> None:
    with pytest.raises(Exec):
        run_repin(configured, run_dir)
    assert fake.execs == [(exe(pin_dir), *start_tuple(configured))]
    assert repin.read_marker(run_dir).outcome is Outcome.TRIAL
    assert rollback_argv(configured) not in argv_of(fake)


def test_a_failing_check_rolls_back_and_execs_the_old_pin(
    pinned, configured, run_dir, pin_dir, fake
) -> None:
    swapped(fake, run_dir)
    fake.reply(("config", "check"), Done(1, "", "boom"))
    with pytest.raises(Exec):
        run_repin(configured, run_dir)
    assert argv_of(fake)[-1] == rollback_argv(configured)
    marker = repin.read_marker(run_dir)
    assert (marker.outcome, marker.old, marker.new) == (Outcome.ROLLED_BACK, OLD, NEW)
    assert marker.reason
    assert fake.execs == [(exe(pin_dir), *start_tuple(configured))]


def test_a_check_timeout_rolls_back(pinned, configured, run_dir, pin_dir, fake) -> None:
    swapped(fake, run_dir)
    fake.reply(("config", "check"), Hang())
    with pytest.raises(Exec):
        run_repin(configured, run_dir)
    assert argv_of(fake)[-1] == rollback_argv(configured)
    assert repin.read_marker(run_dir).outcome is Outcome.ROLLED_BACK


def test_an_exec_error_rolls_back(pinned, configured, run_dir, pin_dir, fake) -> None:
    swapped(fake, run_dir)
    fake.exec_error = OSError("exec format error")
    with pytest.raises(Exec):
        run_repin(configured, run_dir)
    assert argv_of(fake)[-1] == rollback_argv(configured)
    assert fake.execs == [(exe(pin_dir), *start_tuple(configured))] * 2
    assert "exec format error" in repin.read_marker(run_dir).reason


def test_a_missing_uv_rolls_back(pinned, configured, run_dir, fake) -> None:
    swapped(fake, run_dir)
    del fake.programs["uv"]
    with pytest.raises(Exec):
        run_repin(configured, run_dir)
    assert argv_of(fake)[-1] == rollback_argv(configured)


def test_a_pin_script_failure_before_the_swap_runs_no_rollback(
    pinned, configured, run_dir, pin_dir, fake
) -> None:
    fake.reply(("sh",), Done(1, "", "not an ancestor"))
    with pytest.raises(Exec):
        run_repin(configured, run_dir)
    assert argv_of(fake) == [("sh", str(configured / repin.PIN_SCRIPT), NEW)]
    assert repin.read_marker(run_dir).outcome is Outcome.ROLLED_BACK
    assert fake.execs == [(exe(pin_dir), *start_tuple(configured))]


def test_a_failing_rollback_raises(pinned, configured, run_dir, fake) -> None:
    swapped(fake, run_dir)
    fake.reply(("config", "check"), Done(1))
    fake.reply(("--rollback",), Done(1, "", "no previous pin to roll back to"))
    with pytest.raises(RepinError, match="rollback failed"):
        run_repin(configured, run_dir)
    assert fake.execs == []


def test_roll_back_does_nothing_before_the_swap(pinned, configured, run_dir, fake) -> None:
    with pytest.raises(Exec):
        Pin(configured, start_tuple(configured)).roll_back(trial(), "x")
    assert argv_of(fake) == []


# ----- P9: the first start --------------------------------------------------------------------


def test_a_failed_first_start_rolls_back(
    pinned, configured, key_home, run_dir, pin_dir, fake: FakeSystem
) -> None:
    swapped(fake, run_dir)
    repin.write_marker(run_dir, trial())
    with pytest.raises(Exec):  # no toolchain on PATH: preflight raises CliError
        cli.cmd_start(start_args(configured, key_home, "--task", "go"), FakeQuery())
    assert rollback_argv(configured) in argv_of(fake)
    assert repin.read_marker(run_dir).outcome is Outcome.ROLLED_BACK
    assert fake.execs[0][0] == exe(pin_dir)


def test_without_a_marker_the_error_propagates(pinned, configured, key_home, fake) -> None:
    with pytest.raises(cli.CliError):
        cli.cmd_start(start_args(configured, key_home, "--task", "go"), FakeQuery())
    assert fake.execs == []


def test_after_a_rollback_a_failed_start_does_nothing(
    pinned, configured, key_home, run_dir, fake
) -> None:
    repin.write_marker(run_dir, Marker(OLD, NEW, 2, Outcome.ROLLED_BACK, "x"))
    with pytest.raises(cli.CliError):
        cli.cmd_start(start_args(configured, key_home, "--task", "go"), FakeQuery())
    assert fake.execs == [] and argv_of(fake) == []


def test_failed_start_ignores_a_clean_marker_state(configured, fake) -> None:
    repin.failed_start(Pin(configured, ()), RuntimeError("x"))
    assert fake.execs == []


# ----- P10: confirm and the event -------------------------------------------------------------


def repin_events(rt) -> list:
    return [e for e in rt.events.events() if e.kind == "runner-repin"]


def test_confirm_with_no_marker_does_nothing(make_runtime) -> None:
    rt = make_runtime()
    repin.confirm(rt)
    assert repin_events(rt) == [] and rt.relay.messages() == []


def test_confirm_a_trial_logs_pinned_and_deletes_the_marker(make_runtime) -> None:
    rt = make_runtime()
    repin.write_marker(rt.config.run_dir, trial())
    repin.confirm(rt)
    [event] = repin_events(rt)
    assert (event.role, event.story) == ("runner", None)
    assert event.data == {"old": OLD, "new": NEW, "sprint": 2, "outcome": "pinned", "reason": ""}
    assert rt.relay.messages() == []
    assert repin.read_marker(rt.config.run_dir) is None
    repin.confirm(rt)
    assert len(repin_events(rt)) == 1


def test_confirm_a_rollback_logs_it_and_tells_the_human(make_runtime) -> None:
    rt = make_runtime()
    repin.write_marker(rt.config.run_dir, Marker(OLD, NEW, 2, Outcome.ROLLED_BACK, "check failed"))
    repin.confirm(rt)
    [event] = repin_events(rt)
    assert event.data["outcome"] == "rolled_back" and event.data["reason"] == "check failed"
    [note] = rt.relay.messages()
    assert note.kind == "update"
    assert note.text == repin.ROLLED_BACK_NOTE.format(
        old7=OLD[:7], new7=NEW[:7], sprint=2, reason="check failed"
    )
    assert repin.read_marker(rt.config.run_dir) is None


def test_confirm_runs_before_the_run_on_a_good_start(
    pinned, configured, key_home, run_dir, fake
) -> None:
    any_tool(fake)
    repin.write_marker(run_dir, trial())
    assert cli.cmd_start(start_args(configured, key_home, "--task", "go"), FakeQuery()) == 0
    assert repin.read_marker(run_dir) is None
    rows = [json.loads(x) for x in fake.text_of(run_dir / "events.jsonl").splitlines()]
    assert [r["kind"] for r in rows].count("runner-repin") == 1

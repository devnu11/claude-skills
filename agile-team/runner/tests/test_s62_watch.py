"""s62: ``agile-team watch`` polls the run files and prints one JSON line (V1-V8)."""

import json
import os
from pathlib import Path

import pytest
from agile_team import cli, system, watch
from agile_team import state as state_mod
from agile_team.relay import Note, Relay
from agile_team.state import RunState, RunStatus

WAITING = "waiting on answers: s1 waits on m1"
BUDGET = "budget reached"


class FakePace:
    """A fake clock that only moves when the watch sleeps; ``act`` may change files."""

    def __init__(self, acts=None, limit: int = 60):
        self.now = 0.0
        self.sleeps: list[float] = []
        self.acts = list(acts or [])
        self.limit = limit

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if len(self.sleeps) > self.limit:
            raise AssertionError("the watch never ended")
        self.now += seconds
        if self.acts:
            self.acts.pop(0)()

    def clock(self) -> float:
        return self.now

    def patch(self, mp: pytest.MonkeyPatch) -> None:
        """Make the watch sleep and read the clock through this fake (LEGACY file: patch system)."""
        mp.setattr(system, "sleep", self.sleep)
        mp.setattr(system, "monotonic", self.clock)


def put(run_dir: Path, status: RunStatus, reason: str | None = None) -> None:
    """Store a status; ``running`` gets a live pid so it is not shown as interrupted."""
    state_mod.save(run_dir, RunState(status=status, status_reason=reason))
    pid = run_dir / state_mod.PID_FILE
    if status is RunStatus.RUNNING:
        pid.write_text(str(os.getpid()))
    else:
        pid.unlink(missing_ok=True)


def remember(run_dir: Path, messages=0, status=None, reason=None) -> None:
    watch.Seen(messages, status, reason).save(run_dir / "liaison" / "watch.json")


def memory(run_dir: Path) -> dict:
    return json.loads((run_dir / "liaison" / "watch.json").read_text())


def note(run_dir: Path, kind: str = "update", text: str = "hello") -> None:
    Relay(run_dir).post(Note(kind, text))


def until(run_dir: Path, fake: FakePace, timeout=None) -> dict:
    with pytest.MonkeyPatch.context() as mp:
        fake.patch(mp)
        return watch.Watcher(run_dir).until(timeout)


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    path = tmp_path / "run"
    path.mkdir()
    return path


def test_triggers_table_names() -> None:
    assert tuple(name for name, _ in watch.TRIGGERS) == ("message", "status", "health")


def test_a_first_watch_with_a_populated_outbox_does_not_report_it(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING)
    note(run_dir)
    line = until(run_dir, FakePace(), timeout=4)
    assert line["triggers"] == ["heartbeat"] and line["messages"] == []
    assert line["was"] == {"status": "running", "status_reason": None}
    assert memory(run_dir) == {
        "messages": 1, "status": "running", "status_reason": None, "health": "idle",
    }  # fmt: skip


def test_a_first_watch_takes_a_non_quiet_status_as_seen(run_dir: Path) -> None:
    put(run_dir, RunStatus.STOPPED, "stop requested")
    line = until(run_dir, FakePace(), timeout=4)
    assert line["triggers"] == ["heartbeat"] and line["messages"] == []
    assert line["status"] == "stopped" and line["status_reason"] == "stop requested"


def test_the_record_is_written_before_the_wait(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING)
    note(run_dir)
    found: list[int] = []
    fake = FakePace(acts=[lambda: found.append(memory(run_dir)["messages"])])
    until(run_dir, fake, timeout=2)
    assert found == [1]


def test_a_message_after_the_record_is_new(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING)
    note(run_dir)
    fake = FakePace(acts=[lambda: note(run_dir, text="two")])
    line = until(run_dir, fake)
    assert line["triggers"] == ["message"]
    assert [m["id"] for m in line["messages"]] == ["m2"]
    assert memory(run_dir)["messages"] == 2


def test_a_status_change_after_the_record_fires(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING)
    fake = FakePace(acts=[lambda: put(run_dir, RunStatus.STOPPED, "x")])
    line = until(run_dir, fake)
    assert line["triggers"] == ["status"]
    assert line["was"] == {"status": "running", "status_reason": None}


def test_nothing_fires_against_the_record_itself() -> None:
    look = watch.Look([], "stopped", "x", "red", "silent")
    assert watch.fired(look.seen(), look) == []


def test_a_torn_first_look_is_not_recorded(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING)
    outbox = run_dir / "outbox.jsonl"
    outbox.write_text('{"id": "m1", "kind": "upd')

    def complete() -> None:
        outbox.write_text(
            json.dumps({"id": "m1", "kind": "update", "text": "t", "stories": [], "at": 1.0}) + "\n"
        )

    fake = FakePace(acts=[complete])
    line = until(run_dir, fake, timeout=2)
    assert fake.sleeps == [2.0] and memory(run_dir)["messages"] == 1
    assert line["triggers"] == ["heartbeat"] and line["messages"] == []


def test_the_deadline_counts_from_the_call(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING)
    outbox = run_dir / "outbox.jsonl"
    outbox.write_text("{")
    fake = FakePace(acts=[lambda: outbox.write_text("")])
    line = until(run_dir, fake, timeout=2)
    assert line["triggers"] == ["heartbeat"] and fake.sleeps == [2.0]


def test_a_quiet_first_look_waits(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING)
    fake = FakePace(acts=[lambda: note(run_dir)])
    line = until(run_dir, fake)
    assert fake.sleeps == [2.0] and line["triggers"] == ["message"]


def test_heartbeat_after_the_timeout(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING)
    remember(run_dir, 0, "running")
    fake = FakePace()
    line = until(run_dir, fake, timeout=10)
    assert line["triggers"] == ["heartbeat"] and line["messages"] == []
    assert fake.sleeps and set(fake.sleeps) == {2.0} and sum(fake.sleeps) >= 10
    assert memory(run_dir) == {
        "messages": 0, "status": "running", "status_reason": None, "health": "idle",
    }  # fmt: skip


def test_a_zero_timeout_answers_at_the_first_look(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING)
    remember(run_dir, 0, "running")
    fake = FakePace()
    assert until(run_dir, fake, timeout=0)["triggers"] == ["heartbeat"]
    assert fake.sleeps == []


def test_two_messages_between_watches_are_both_reported(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING)
    note(run_dir)
    remember(run_dir, 0, "running")
    assert len(until(run_dir, FakePace())["messages"]) == 1
    note(run_dir, text="two")
    note(run_dir, text="three")
    line = until(run_dir, FakePace())
    assert [m["id"] for m in line["messages"]] == ["m2", "m3"]


def test_a_message_during_the_sleep_fires_at_the_next_poll(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING)
    remember(run_dir, 0, "running")
    fake = FakePace(acts=[lambda: None, lambda: note(run_dir)])
    line = until(run_dir, fake)
    assert fake.sleeps == [2.0, 2.0] and line["triggers"] == ["message"]


def test_a_new_status_fires_with_the_old_one_as_was(run_dir: Path) -> None:
    put(run_dir, RunStatus.BLOCKED, BUDGET)
    remember(run_dir, 0, "running")
    line = until(run_dir, FakePace())
    assert line["triggers"] == ["status"]
    assert line["status"] == "blocked" and line["status_reason"] == BUDGET
    assert line["was"] == {"status": "running", "status_reason": None}


def test_the_same_status_does_not_fire(run_dir: Path) -> None:
    put(run_dir, RunStatus.BLOCKED, BUDGET)
    remember(run_dir, 0, "blocked", BUDGET)
    assert until(run_dir, FakePace(), timeout=4)["triggers"] == ["heartbeat"]


def test_a_waiting_reason_fires(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING, WAITING)
    remember(run_dir, 0, "running")
    line = until(run_dir, FakePace())
    assert line["triggers"] == ["status"] and line["status_reason"] == WAITING


def test_waiting_then_plain_running_is_quiet_but_moves_the_baseline(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING, WAITING)
    remember(run_dir, 0, "running", WAITING)
    acts = [lambda: put(run_dir, RunStatus.RUNNING), lambda: put(run_dir, RunStatus.STOPPED, "x")]
    fake = FakePace(acts=[lambda: put(run_dir, RunStatus.RUNNING), acts[1]])
    line = until(run_dir, fake)
    assert line["triggers"] == ["status"] and line["status"] == "stopped"
    assert line["was"] == {"status": "running", "status_reason": None}
    assert len(fake.sleeps) == 2


def test_a_dead_pid_reads_interrupted_and_fires(run_dir: Path) -> None:
    state_mod.save(run_dir, RunState(status=RunStatus.RUNNING))
    (run_dir / state_mod.PID_FILE).write_text("999999999")
    remember(run_dir, 0, "running")
    line = until(run_dir, FakePace())
    assert line["triggers"] == ["status"] and line["status"] == "interrupted"


def test_a_shorter_outbox_counts_every_entry_as_new(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING)
    note(run_dir)
    note(run_dir, text="b")
    remember(run_dir, 9, "running")
    line = until(run_dir, FakePace())
    assert [m["id"] for m in line["messages"]] == ["m1", "m2"]
    assert memory(run_dir)["messages"] == 2


def test_a_torn_outbox_line_is_not_a_look(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING)
    remember(run_dir, 0, "running")
    outbox = run_dir / "outbox.jsonl"
    outbox.write_text('{"id": "m1", "kind": "upd')

    def complete() -> None:
        outbox.write_text(
            json.dumps({"id": "m1", "kind": "update", "text": "t", "stories": [], "at": 1.0}) + "\n"
        )

    fake = FakePace(acts=[complete])
    line = until(run_dir, fake)
    assert fake.sleeps == [2.0] and [m["id"] for m in line["messages"]] == ["m1"]


def test_a_torn_line_never_ends_a_timed_watch(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING)
    (run_dir / "outbox.jsonl").write_text("{")
    fake = FakePace(limit=5)
    with pytest.raises(AssertionError):
        until(run_dir, fake, timeout=1)


def test_garbage_memory_acts_as_fresh(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING)
    note(run_dir)
    path = run_dir / "liaison" / "watch.json"
    path.parent.mkdir(parents=True)
    path.write_text("not json {")
    assert until(run_dir, FakePace())["triggers"] == ["message"]


def test_seen_defaults_and_atomic_save(tmp_path: Path) -> None:
    path = tmp_path / "a" / "watch.json"
    assert watch.Seen.load(path) is None
    watch.Seen(2, "idle", "r").save(path)
    assert watch.Seen.load(path) == watch.Seen(2, "idle", "r")
    assert [p.name for p in path.parent.iterdir()] == ["watch.json"]


def test_other_read_errors_are_fresh_memory(run_dir: Path) -> None:
    path = run_dir / "liaison" / "watch.json"
    path.mkdir(parents=True)
    assert watch.Seen.load(path) == watch.Seen()


def test_look_is_none_on_a_torn_outbox(run_dir: Path) -> None:
    (run_dir / "outbox.jsonl").write_text("{")
    assert watch.look(run_dir) is None


def test_quiet_means_running_without_a_reason() -> None:
    assert watch.Look([], "running", None).quiet()
    assert not watch.Look([], "running", WAITING).quiet()
    assert not watch.Look([], "stopped", None).quiet()


def test_the_line_is_json_ready(run_dir: Path) -> None:
    put(run_dir, RunStatus.RUNNING)
    remember(run_dir, 0, "running")
    note(run_dir)
    json.dumps(until(run_dir, FakePace()))


def test_the_poll_interval() -> None:
    assert watch.POLL_S == 2.0


# ----- cli ---------------------------------------------------------------------------


def test_cmd_watch_prints_one_json_line(configured: Path, capsys) -> None:
    run_dir = configured / ".team" / "run"
    put(run_dir, RunStatus.BLOCKED, BUDGET)
    args = cli.build_parser().parse_args(["--repo", str(configured), "watch", "--timeout", "0"])
    assert args.timeout_s == 0.0
    with pytest.MonkeyPatch.context() as mp:
        FakePace().patch(mp)
        assert cli.cmd_watch(args) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert json.loads(out)["status"] == "blocked"


def test_watch_timeout_defaults_to_none() -> None:
    args = cli.build_parser().parse_args(["watch"])
    assert args.timeout_s is None
    assert "watch" in [c.name for c in cli.COMMANDS]

"""s71 P1: converted modules reach files and the clock only through ``system``.

Every test runs in the fake world: the guard fails it if a module still calls the OS.
"""

import errno
import json
from pathlib import Path

import pytest
from agile_team import config as config_mod
from agile_team import events, halt, roles, state, system, watch
from agile_team.ledger import Entry, Ledger
from agile_team.relay import Note, Relay

from . import fake_system
from .fake_system import FAKE_REPO, START_CLOCK, FakeSystem

RUN = FAKE_REPO / ".team" / "run"


def test_state_save_writes_tmp_then_replaces(fake: FakeSystem) -> None:
    state.save(RUN, state.RunState(sprint=3))
    names = [(op, path.name) for op, path in fake.ops if op in ("write_text", "replace")]
    assert names == [("write_text", "state.json.tmp"), ("replace", "state.json")]
    assert state.load(RUN).sprint == 3
    assert not system.exists(RUN / "state.json.tmp")


def test_full_disk_during_save_raises_and_keeps_the_old_state(fake: FakeSystem) -> None:
    state.save(RUN, state.RunState(sprint=1))
    fake.fill_disk()
    with pytest.raises(OSError) as raised:
        state.save(RUN, state.RunState(sprint=2))
    assert raised.value.errno == errno.ENOSPC
    assert state.load(RUN).sprint == 1


def test_unreadable_state_is_reported_not_swallowed(fake: FakeSystem) -> None:
    state.save(RUN, state.RunState())
    fake.deny(RUN / "state.json")
    with pytest.raises(PermissionError):
        state.load(RUN)


def test_ledger_appends_through_the_seam(fake: FakeSystem) -> None:
    led = Ledger(RUN / "ledger.jsonl")
    led.record(Entry("developer", "sonnet", 1.0, "s1"))
    led.record(Entry("developer", "sonnet", 0.5, "s1"))
    assert [op for op, _ in fake.ops if op == "append_text"] == ["append_text"] * 2
    assert led.total() == 1.5
    assert len(fake.text_of(RUN / "ledger.jsonl").splitlines()) == 2


def test_events_are_stamped_with_the_fake_clock(fake: FakeSystem) -> None:
    fake.clock = START_CLOCK + 90
    log = events.EventLog(RUN / "events.jsonl")
    made = log.emit(events.Event(events.EventKind.GATE, None, "s1", {}))
    assert made.at == START_CLOCK + 90
    assert ("append_text", RUN / "events.jsonl") in fake.ops


def test_crash_log_entry_has_the_fake_clock_stamp(fake: FakeSystem) -> None:
    halt.log_traceback(RUN, ValueError("boom"))
    entry = fake.text_of(RUN / halt.CRASH_LOG)
    assert entry.startswith("--- 2027-01-15 08:00:00 ValueError\n")
    assert "boom" in entry


def test_relay_posts_with_the_fake_clock(fake: FakeSystem) -> None:
    fake.clock = START_CLOCK + 5
    relay = Relay(RUN)
    message = relay.post(Note("update", "hello"))
    assert message.at == START_CLOCK + 5
    assert [m.text for m in relay.messages()] == ["hello"]


def test_builtin_roles_load_from_package_data() -> None:
    book = roles.RoleBook.for_repo(FAKE_REPO, {})
    assert "unit-tester" in book.names()
    assert system.is_file(roles.BUILTIN_DIR / "unit-tester.md")


def test_repo_roles_come_from_the_fake_files(fake: FakeSystem) -> None:
    fake.put(FAKE_REPO / roles.REPO_ROLES / "extra-role.md", "# extra\n")
    assert "extra-role" in roles.load_dir(FAKE_REPO / roles.REPO_ROLES)


def test_config_load_reads_the_fake_toml(configured: Path) -> None:
    config = config_mod.load(configured)
    assert config.repo == FAKE_REPO
    assert config.toolchain.commands["test"] == "pytest"


def test_config_missing_file_is_an_error(repo: Path) -> None:
    with pytest.raises(config_mod.ConfigError, match="not found"):
        config_mod.load(repo)


def test_watch_times_out_on_the_fake_clock(fake: FakeSystem, configured: Path) -> None:
    run_dir = configured / ".team" / "run"
    Relay(run_dir).post(Note("update", "first"))
    first = watch.Watcher(run_dir).until(None)
    assert "message" in first["triggers"]
    fake.slept.clear()
    second = watch.Watcher(run_dir).until(30.0)
    assert second["triggers"] == [watch.HEARTBEAT]
    assert fake.slept and set(fake.slept) == {watch.POLL_S}
    assert sum(fake.slept) >= 30.0 - watch.POLL_S


def test_watch_memory_is_saved_through_the_seam(fake: FakeSystem, configured: Path) -> None:
    run_dir = configured / ".team" / "run"
    Relay(run_dir).post(Note("update", "x"))
    watch.Watcher(run_dir).until(None)
    memory = run_dir / "liaison" / watch.WATCH_FILE
    assert json.loads(fake.text_of(memory))["messages"] == 1
    assert ("replace", memory) in fake.ops


def test_the_fake_is_installed_on_system() -> None:
    assert system.now() == fake_system.START_CLOCK

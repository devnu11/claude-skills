"""s41: the runner signals only process groups it created (G1-G6), on the fake (s76)."""

import signal
from types import SimpleNamespace

import pytest
from agile_team import commands, process_groups, sandbox, system
from agile_team.process_groups import PS_TIMEOUT_S, Recorded, RunnerIds

from .clock import about
from .fake_system import FAKE_IDS, FAKE_REPO, FAKE_ROOT, START_CLOCK, Done, FakeSystem, Hang

FAKE = RunnerIds(*FAKE_IDS)  # literals: test ids must not hold live values (s70)
SAME = 5000  # a child in the runner's own group
OWN = 5001  # a child that leads its own group
GONE = 5002  # a pid that has been reaped
BASE = FAKE_ROOT / "sandboxes"
PID_FILE = BASE / f"web{sandbox.PID_SUFFIX}"
STARTED_5S_AGO = Done(0, "00:05\n")


@pytest.fixture(autouse=True)
def children(fake: FakeSystem) -> None:
    """One child in the runner's group, one in its own; ``GONE`` was never there."""
    fake.groups[SAME] = FAKE_IDS[1]
    fake.groups[OWN] = OWN
    system.make_dirs(BASE)


def _sent(fake: FakeSystem) -> list[tuple[int, int]]:
    return [(group, sig) for name, group, sig in fake.signals if name == "killpg"]


def _proc(pid: int) -> SimpleNamespace:
    return SimpleNamespace(pid=pid)


# 1
def test_same_group_child_is_never_signalled(fake: FakeSystem) -> None:
    process_groups.signal_child_group(SAME, signal.SIGTERM)
    sandbox._signal_group(_proc(SAME), signal.SIGTERM)  # type: ignore[arg-type]
    assert fake.signals == []


def test_runner_and_bad_pids_are_never_signalled(fake: FakeSystem) -> None:
    sandbox._signal_group(_proc(system.pid()), signal.SIGTERM)  # type: ignore[arg-type]
    for pid in (*FAKE_IDS, 0, 1, -5):
        process_groups.signal_child_group(pid, signal.SIGKILL)
    assert fake.signals == []


# 2
def test_new_session_child_is_signalled(fake: FakeSystem) -> None:
    process_groups.signal_child_group(OWN, signal.SIGTERM)
    assert _sent(fake) == [(OWN, signal.SIGTERM)]


def test_vanished_leader_is_signalled(fake: FakeSystem) -> None:
    process_groups.signal_child_group(GONE, signal.SIGKILL)
    assert _sent(fake) == [(GONE, signal.SIGKILL)]


@pytest.mark.parametrize("error", [ProcessLookupError, PermissionError])
def test_killpg_errors_are_suppressed(monkeypatch, error) -> None:
    def boom(pgid, sig):
        raise error

    monkeypatch.setattr(system, "killpg", boom)
    process_groups.signal_child_group(OWN, signal.SIGTERM)


def test_other_errors_from_pgid_refuse_the_signal(fake: FakeSystem, monkeypatch) -> None:
    def denied(pid):
        raise PermissionError

    monkeypatch.setattr(system, "pgid", denied)
    process_groups.signal_child_group(OWN, signal.SIGTERM)
    assert fake.signals == []


# 3
def test_leads_own_group() -> None:
    assert process_groups.leads_own_group(OWN)
    assert not process_groups.leads_own_group(SAME)
    assert not process_groups.leads_own_group(system.pid())
    assert not process_groups.leads_own_group(GONE)


# 4
def test_in_runner_group() -> None:
    assert process_groups.in_runner_group(system.pid())
    assert process_groups.in_runner_group(SAME)
    assert not process_groups.in_runner_group(OWN)
    assert not process_groups.in_runner_group(GONE)
    assert not process_groups.in_runner_group(10**30)


# 5
@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("07", None),
        ("05:07", 307),
        ("1:02:03", 3723),
        ("2-01:00:00", 176400),
        ("  00:05\n", 5),
        ("", None),
        ("abc", None),
        ("1:2:3:4", None),
        ("x-01:00", None),
    ],
)
def test_parse_etime(text: str, seconds) -> None:
    assert about(process_groups.parse_etime(text)) == seconds


# 6
def test_started_at_asks_ps_for_the_pid(fake: FakeSystem) -> None:
    fake.reply(("ps",), STARTED_5S_AGO)
    assert process_groups.started_at(OWN) == START_CLOCK - 5
    assert fake.commands == [
        system.Command(("ps", "-o", "etime=", "-p", str(OWN)), timeout=PS_TIMEOUT_S)
    ]


def test_started_at_of_a_reaped_pid(fake: FakeSystem) -> None:
    fake.reply(("ps",), Done(1, "", "no such process"))
    assert process_groups.started_at(GONE) is None


@pytest.mark.parametrize(
    "outcome",
    [
        system.TimeoutExpired("ps", 1),
        OSError("no ps"),
        FileNotFoundError("ps"),
        Done(1, "00:05\n"),
    ],
    ids=["timeout", "oserror", "missing", "exit-1"],
)
def test_started_at_without_a_usable_ps(fake: FakeSystem, outcome) -> None:
    fake.reply(("ps",), outcome)
    assert process_groups.started_at(system.pid()) is None


# 7
def test_recorded_is_ours(fake: FakeSystem) -> None:
    fake.reply(("ps",), STARTED_5S_AGO)
    assert Recorded(OWN, START_CLOCK).is_ours()
    assert not Recorded(OWN, START_CLOCK - 3600).is_ours()
    assert not Recorded(SAME, START_CLOCK).is_ours()
    assert not Recorded(system.pid(), START_CLOCK).is_ours()
    fake.reply(("ps",), Done(1))
    assert not Recorded(OWN, START_CLOCK).is_ours()


# 8
def test_stale_pid_reused_after_the_file_was_written_is_left_alone(fake: FakeSystem) -> None:
    fake.reply(("ps",), STARTED_5S_AGO)
    fake.put(PID_FILE, str(OWN), mtime=START_CLOCK - 3600)
    sandbox.stop_stale(BASE / "web")
    assert OWN in fake.groups
    assert _sent(fake) == []
    assert not system.exists(PID_FILE)


# 9
@pytest.mark.parametrize("pid", [FAKE.pid, FAKE.pgrp], ids=["pid", "pgrp"])
def test_stop_stale_never_signals_the_runner(fake: FakeSystem, monkeypatch, pid) -> None:
    monkeypatch.setattr(Recorded, "is_ours", lambda self: True)
    fake.put(PID_FILE, str(pid))
    sandbox.stop_stale(BASE / "web", FAKE)
    assert fake.signals == []
    assert not system.exists(PID_FILE)


def test_stop_stale_signals_a_pid_the_ids_do_not_name(fake: FakeSystem, monkeypatch) -> None:
    monkeypatch.setattr(Recorded, "is_ours", lambda self: True)
    fake.put(PID_FILE, "4244")
    sandbox.stop_stale(BASE / "web", FAKE)
    assert _sent(fake)[0] == (4244, signal.SIGTERM)


def test_stop_stale_defaults_to_the_live_runner_ids(fake: FakeSystem, monkeypatch) -> None:
    monkeypatch.setattr(Recorded, "is_ours", lambda self: True)
    fake.put(PID_FILE, str(system.pid()))
    sandbox.stop_stale(BASE / "web")
    assert fake.signals == []
    assert not system.exists(PID_FILE)


def test_runner_ids_current_reads_the_live_process() -> None:
    assert RunnerIds.current() == RunnerIds(*FAKE_IDS)


def test_runner_ids_names_its_pid_and_group() -> None:
    ids = RunnerIds(1, 2)
    assert ids.names(1) and ids.names(2)
    assert not ids.names(3)


def test_is_ours_is_not_asked_when_the_ids_name_the_pid(fake: FakeSystem, monkeypatch) -> None:
    def boom(self):
        raise AssertionError("is_ours must not run")

    monkeypatch.setattr(Recorded, "is_ours", boom)
    fake.put(PID_FILE, str(FAKE.pid))
    sandbox.stop_stale(BASE / "web", FAKE)
    assert fake.signals == []


def test_stop_stale_ends_a_group_it_recorded(fake: FakeSystem) -> None:
    fake.reply(("ps",), STARTED_5S_AGO)
    fake.put(PID_FILE, str(OWN))
    sandbox.stop_stale(BASE / "web")
    assert _sent(fake) == [(OWN, signal.SIGTERM)]
    assert OWN not in fake.groups
    assert not system.exists(PID_FILE)


def test_stop_stale_ignores_unreadable_pid_files(fake: FakeSystem) -> None:
    fake.put(PID_FILE, "not a pid")
    sandbox.stop_stale(BASE / "web")
    assert fake.signals == []
    assert not system.exists(PID_FILE)


# 11
def test_no_sigkill_when_the_group_stopped_being_ours(fake: FakeSystem, monkeypatch) -> None:
    fake.put(PID_FILE, str(OWN))
    fake.survivors.add(OWN)
    answers = iter([True, False])
    monkeypatch.setattr(Recorded, "is_ours", lambda self: next(answers))
    sandbox.stop_stale(BASE / "web")
    assert _sent(fake) == [(OWN, signal.SIGTERM)]


def test_sigkill_when_the_group_is_still_ours(fake: FakeSystem, monkeypatch) -> None:
    fake.put(PID_FILE, str(OWN))
    fake.survivors.add(OWN)
    monkeypatch.setattr(Recorded, "is_ours", lambda self: True)
    sandbox.stop_stale(BASE / "web")
    assert _sent(fake) == [(OWN, signal.SIGTERM), (OWN, signal.SIGKILL)]
    assert fake.clock >= START_CLOCK + sandbox.STOP_WAIT_S


# 12
def test_kill_group_spares_the_runners_group(fake: FakeSystem) -> None:
    commands.kill_group(_proc(SAME))  # type: ignore[arg-type]
    assert fake.signals == []


def test_kill_group_kills_a_new_session(fake: FakeSystem) -> None:
    fake.reply(("sleep",), Hang())
    child = system.spawn_piped(system.ShellCommand("sleep 30", FAKE_REPO))
    commands.kill_group(child)
    assert child.poll() == -signal.SIGKILL

"""The in-memory ``FakeSystem`` that stands in for ``agile_team.system`` (s71 P1)."""

import errno
import signal
import threading
from pathlib import Path

import pytest
from agile_team import system

from .fake_system import (
    FAKE_HOME,
    FAKE_IDS,
    FAKE_REPO,
    FIRST_CHILD_PID,
    START_CLOCK,
    Done,
    FakeSystem,
    Hang,
)

A = FAKE_REPO / "a.txt"


def test_fake_implements_every_system_function() -> None:
    missing = [name for name in system.__all__ if not hasattr(FakeSystem, name)]
    assert missing == []


def test_install_swaps_every_function(fake: FakeSystem) -> None:
    for name in system.__all__:
        assert getattr(system, name) == getattr(fake, name)


def test_write_then_read_round_trip(fake: FakeSystem) -> None:
    system.write_text(A, "hello")
    assert system.read_text(A) == "hello"
    assert system.read_bytes(A) == b"hello"
    assert system.is_file(A) and system.exists(A) and not system.is_dir(A)


def test_missing_file_raises_file_not_found() -> None:
    with pytest.raises(FileNotFoundError):
        system.read_text(A)
    assert not system.is_file(A) and not system.exists(A)


def test_write_under_a_missing_directory_raises() -> None:
    with pytest.raises(FileNotFoundError):
        system.write_text(FAKE_REPO / "nope" / "a.txt", "x")


def test_relative_paths_resolve_against_the_fake_repo(fake: FakeSystem) -> None:
    system.write_text(Path("a.txt"), "rel")
    assert system.read_text(A) == "rel"
    assert system.resolve(Path("a.txt")) == A


def test_deny_makes_reads_raise_permission_error(fake: FakeSystem) -> None:
    fake.put(A, "secret")
    fake.deny(A)
    with pytest.raises(PermissionError):
        system.read_text(A)


@pytest.mark.parametrize(
    "act",
    [
        lambda: system.write_text(A, "x"),
        lambda: system.append_text(A, "x"),
        lambda: system.replace(FAKE_REPO / "b", A),
        lambda: system.make_dirs(FAKE_REPO / "d"),
        lambda: system.copy_tree(FAKE_REPO, FAKE_REPO / "copy"),
    ],
    ids=["write", "append", "replace", "make_dirs", "copy_tree"],
)
def test_full_disk_fails_every_write(fake: FakeSystem, act) -> None:
    fake.put(FAKE_REPO / "b", "b")
    fake.fill_disk()
    with pytest.raises(OSError) as raised:
        act()
    assert raised.value.errno == errno.ENOSPC


def test_ops_record_in_call_order(fake: FakeSystem) -> None:
    system.make_dirs(FAKE_REPO / "d")
    system.write_text(FAKE_REPO / "d" / "x", "1")
    system.append_text(FAKE_REPO / "d" / "x", "2")
    assert [op for op, _ in fake.ops] == ["make_dirs", "write_text", "append_text"]
    assert system.read_text(FAKE_REPO / "d" / "x") == "12"


def test_replace_moves_the_file(fake: FakeSystem) -> None:
    fake.put(A, "one")
    system.replace(A, FAKE_REPO / "b.txt")
    assert not system.exists(A)
    assert system.read_text(FAKE_REPO / "b.txt") == "one"


def test_remove_of_a_missing_file_is_fine(fake: FakeSystem) -> None:
    system.remove(A)
    fake.put(A, "x")
    system.remove(A)
    assert not system.exists(A)


def test_list_dir_and_glob_are_sorted_direct_children(fake: FakeSystem) -> None:
    for name in ("b.md", "a.md", "c.txt"):
        fake.put(FAKE_REPO / "d" / name, "")
    fake.put(FAKE_REPO / "d" / "sub" / "deep.md", "")
    assert [p.name for p in system.list_dir(FAKE_REPO / "d")] == ["a.md", "b.md", "c.txt", "sub"]
    assert [p.name for p in system.glob(FAKE_REPO / "d", "*.md")] == ["a.md", "b.md"]
    assert system.glob(FAKE_REPO / "empty", "*") == []


def test_list_dir_of_a_missing_dir_raises() -> None:
    with pytest.raises(FileNotFoundError):
        system.list_dir(FAKE_REPO / "nope")


def test_stat_reports_mode_size_and_mtime(fake: FakeSystem) -> None:
    fake.put(A, "abc", mode=0o600, mtime=12.5)
    found = system.stat(A)
    assert (found.mode, found.size, found.mtime, found.mtime_ns) == (0o600, 3, 12.5, 12_500_000_000)
    with pytest.raises(FileNotFoundError):
        system.stat(FAKE_REPO / "nope")


def test_write_stamps_the_fake_clock_as_mtime(fake: FakeSystem) -> None:
    fake.clock = 77.0
    system.write_text(A, "x")
    assert system.stat(A).mtime == 77.0


def test_read_end_cuts_to_the_tail(fake: FakeSystem) -> None:
    fake.put(A, "0123456789")
    assert system.read_end(A, 4) == (b"6789", 10)
    assert system.read_end(A, 99) == (b"0123456789", 10)


def test_remove_tree_and_copy_tree(fake: FakeSystem) -> None:
    fake.put(FAKE_REPO / "src" / "a" / "f.txt", "f")
    system.copy_tree(FAKE_REPO / "src", FAKE_REPO / "dst")
    assert system.read_text(FAKE_REPO / "dst" / "a" / "f.txt") == "f"
    with pytest.raises(FileExistsError):
        system.copy_tree(FAKE_REPO / "src", FAKE_REPO / "dst")
    system.remove_tree(FAKE_REPO / "dst")
    assert not system.exists(FAKE_REPO / "dst" / "a" / "f.txt")
    with pytest.raises(FileNotFoundError):
        system.remove_tree(FAKE_REPO / "dst")


def test_expand_user_maps_tilde_to_the_fake_home() -> None:
    assert system.expand_user(Path("~/x")) == FAKE_HOME / "x"
    assert system.expand_user(Path("/abs")) == Path("/abs")


def test_sleep_advances_now_and_monotonic(fake: FakeSystem) -> None:
    system.sleep(2.5)
    assert fake.slept == [2.5]
    assert system.now() == START_CLOCK + 2.5
    assert system.monotonic() == START_CLOCK + 2.5


def test_local_time_formats_the_fake_clock() -> None:
    assert system.local_time("%H:%M") == "08:00"


def test_pid_and_kill(fake: FakeSystem) -> None:
    assert system.pid() == FAKE_IDS[0]
    system.kill(FAKE_IDS[0], 0)
    with pytest.raises(ProcessLookupError):
        system.kill(99999, 0)
    assert fake.signals == [("kill", FAKE_IDS[0], 0), ("kill", 99999, 0)]


def test_package_data_is_present() -> None:
    assert system.read_text(system_role_path()).strip()


def system_role_path() -> Path:
    import agile_team

    return Path(agile_team.__file__).parent / "roles" / "unit-tester.md"


SPAWNED = FIRST_CHILD_PID


def shell(text: str = "sleep 30") -> "system.ShellCommand":
    return system.ShellCommand(text, FAKE_REPO)


def test_runner_group_is_the_runners_own() -> None:
    assert system.pgid(system.pid()) == system.pgrp() == FAKE_IDS[1]


def test_pgid_of_an_unknown_pid_raises() -> None:
    with pytest.raises(ProcessLookupError):
        system.pgid(99999)


def test_run_answers_a_scripted_command_and_records_it(fake: FakeSystem) -> None:
    fake.reply(("git", "status"), Done(3, "out", "err"))
    done = system.run(system.Command(("git", "-c", "x=y", "status"), FAKE_REPO))
    assert (done.code, done.out, done.err) == (3, "out", "err")
    assert fake.commands == [system.Command(("git", "-c", "x=y", "status"), FAKE_REPO)]


def test_run_with_no_rule_succeeds_quietly() -> None:
    assert system.run(system.Command(("anything",))) == system.Completed(0, "", "")


def test_the_last_matching_rule_wins_and_results_repeat(fake: FakeSystem) -> None:
    fake.reply(("git",), Done(1))
    fake.reply(("git", "log"), Done(0, "a"), Done(0, "b"))
    codes = [system.run(system.Command(("git", "log"))).out for _ in range(3)]
    assert codes == ["a", "b", "b"]
    assert system.run(system.Command(("git", "add"))).code == 1


def test_a_rule_whose_words_are_out_of_order_does_not_match(fake: FakeSystem) -> None:
    fake.reply(("b", "a"), Done(9))
    assert system.run(system.Command(("a", "b"))).code == 0


def test_a_scripted_exception_is_raised(fake: FakeSystem) -> None:
    fake.reply(("nope",), FileNotFoundError("nope"))
    with pytest.raises(FileNotFoundError):
        system.run(system.Command(("nope",)))


def test_a_scripted_hang_times_out_on_the_fake_clock(fake: FakeSystem) -> None:
    fake.reply(("slow",), Hang())
    with pytest.raises(system.TimeoutExpired):
        system.run(system.Command(("slow",), None, 5.0))
    assert fake.clock == START_CLOCK + 5.0


def test_run_shell_matches_on_the_words_of_the_line(fake: FakeSystem) -> None:
    fake.reply(("make", "test"), Done(2))
    assert system.run_shell(shell("make test -j4")) == 2
    assert fake.commands == [shell("make test -j4")]


def test_a_done_child_has_exited(fake: FakeSystem) -> None:
    fake.reply(("echo",), Done(4, "hi"))
    child = system.spawn_piped(shell("echo hi"))
    assert (child.pid, child.poll(), child.communicate(1)) == (SPAWNED, 4, ("hi", None))


def test_a_hung_child_times_out_until_its_group_is_signalled(fake: FakeSystem) -> None:
    fake.reply(("sleep",), Hang("so far"))
    with system.spawn_piped(shell()) as child:
        assert child.poll() is None
        with pytest.raises(system.TimeoutExpired):
            child.communicate(timeout=2)
        assert fake.clock == START_CLOCK + 2
        system.killpg(system.pgid(child.pid), signal.SIGKILL)
        assert child.poll() == child.returncode == -signal.SIGKILL
        assert child.communicate(timeout=1) == ("so far", None)


def test_each_spawn_takes_the_next_pid_as_its_own_group_leader(fake: FakeSystem) -> None:
    first, second = system.spawn_piped(shell()), system.spawn_piped(shell())
    assert (first.pid, second.pid) == (SPAWNED, SPAWNED + 1)
    assert system.pgid(first.pid) == first.pid
    assert system.pgid(second.pid) == second.pid


def test_spawn_logged_writes_the_output_to_the_log(fake: FakeSystem) -> None:
    fake.reply(("serve",), Hang("listening\n"))
    system.spawn_logged(shell("serve"), FAKE_REPO / "svc.log")
    assert fake.text_of(FAKE_REPO / "svc.log") == "listening\n"


def test_a_spawn_of_a_missing_binary_raises(fake: FakeSystem) -> None:
    fake.reply(("ghost",), FileNotFoundError("ghost"))
    with pytest.raises(FileNotFoundError):
        system.spawn_piped(shell("ghost"))


def test_sigterm_ends_a_group_and_records_the_signal(fake: FakeSystem) -> None:
    fake.reply(("sleep",), Hang())
    child = system.spawn_piped(shell())
    system.killpg(child.pid, signal.SIGTERM)
    assert child.poll() == -signal.SIGTERM
    assert ("killpg", child.pid, signal.SIGTERM) in fake.signals
    with pytest.raises(ProcessLookupError):
        system.pgid(child.pid)


def test_sigterm_spares_a_survivor_and_sigkill_ends_it(fake: FakeSystem) -> None:
    fake.reply(("sleep",), Hang())
    child = system.spawn_piped(shell())
    fake.survivors.add(child.pid)
    system.killpg(child.pid, signal.SIGTERM)
    assert child.poll() is None
    system.killpg(child.pid, signal.SIGKILL)
    assert child.poll() == -signal.SIGKILL


def test_signalling_a_dead_group_raises(fake: FakeSystem) -> None:
    with pytest.raises(ProcessLookupError):
        system.killpg(77777, signal.SIGTERM)
    with pytest.raises(ProcessLookupError):
        system.killpg(77777, 0)


def test_signal_zero_checks_liveness_and_records_nothing(fake: FakeSystem) -> None:
    child = system.spawn_piped(shell())
    system.killpg(child.pid, 0)
    assert fake.signals == []


def test_a_group_member_outlives_its_reaped_leader(fake: FakeSystem) -> None:
    fake.reply(("sleep",), Hang())
    leader = system.spawn_piped(shell())
    fake.groups[leader.pid + 100] = leader.pid
    fake.survivors.add(leader.pid + 100)
    system.kill(leader.pid, signal.SIGKILL)
    assert leader.poll() == -signal.SIGKILL
    system.killpg(leader.pid, 0)
    system.killpg(leader.pid, signal.SIGKILL)
    with pytest.raises(ProcessLookupError):
        system.killpg(leader.pid, 0)


def test_kill_ends_one_pid(fake: FakeSystem) -> None:
    fake.reply(("sleep",), Hang())
    child = system.spawn_piped(shell())
    system.kill(child.pid, signal.SIGTERM)
    assert child.poll() == -signal.SIGTERM


def test_ending_a_pid_frees_the_port_it_held(fake: FakeSystem) -> None:
    fake.reply(("serve",), Hang())
    child = system.spawn_piped(shell("serve"))
    address = ("127.0.0.1", 8799)
    fake.listening.add(address)
    fake.holds[child.pid] = address
    system.connect(address)
    system.killpg(child.pid, signal.SIGKILL)
    with pytest.raises(ConnectionRefusedError):
        system.connect(address)


def test_connect_refuses_an_address_nobody_listens_on() -> None:
    with pytest.raises(ConnectionRefusedError):
        system.connect(("127.0.0.1", 1))


def test_http_get_answers_a_scripted_url_and_refuses_others(fake: FakeSystem) -> None:
    fake.web["http://h/"] = system.HttpReply(200, "application/json", b"{}")
    fake.web["http://bad/"] = OSError("boom")
    assert system.http_get("http://h/", 1.0).status == 200
    with pytest.raises(OSError, match="boom"):
        system.http_get("http://bad/", 1.0)
    with pytest.raises(ConnectionRefusedError):
        system.http_get("http://other/", 1.0)


def test_hostname_and_environ(fake: FakeSystem) -> None:
    fake.env["K"] = "v"
    assert system.hostname() == "fakehost"
    assert dict(system.environ()) == {"AGILE_TEAM_HOME": str(FAKE_HOME / "agile-team"), "K": "v"}


def test_listen_http_records_the_address_and_serves_nothing(fake: FakeSystem) -> None:
    server = system.listen_http(("0.0.0.0", 0), object)
    server.app = "app"
    server.serve_forever()
    assert fake.listened == [("0.0.0.0", 0)]
    assert server.server_address[1] > 0


def test_listen_http_on_a_busy_address_raises(fake: FakeSystem) -> None:
    fake.listening.add(("h", 80))
    with pytest.raises(OSError, match="in use"):
        system.listen_http(("h", 80), object)


def test_wait_event_returns_true_at_once_when_set() -> None:
    event = threading.Event()
    event.set()
    assert system.wait_event(event, 5.0) is True


def test_wait_event_gives_the_scripted_number_of_beats(fake: FakeSystem) -> None:
    fake.ticks = 2
    event = threading.Event()
    answers = [system.wait_event(event, 3.0) for _ in range(3)]
    assert answers == [False, False, True]
    assert fake.clock == START_CLOCK + 6.0


# ----- s77: machine, browser, signals, async sleep ---------------------------------------

P3_NAMES = ("async_sleep", "cwd", "home", "on_signal", "open_browser", "which")


def test_the_p3_names_are_in_the_seam() -> None:
    assert all(name in system.__all__ for name in P3_NAMES)


def test_cwd_and_home_are_fixed_paths() -> None:
    assert system.cwd() == FAKE_REPO
    assert system.home() == FAKE_HOME


def test_which_answers_from_programs(fake: FakeSystem) -> None:
    fake.programs["uv"] = "/usr/bin/uv"
    assert system.which("uv") == "/usr/bin/uv"
    assert system.which("nope") is None


def test_open_browser_records_and_succeeds(fake: FakeSystem) -> None:
    assert system.open_browser("http://h:1/") is True
    assert fake.opened == ["http://h:1/"]


def test_on_signal_records_the_handler(fake: FakeSystem) -> None:
    def callback() -> None:
        return None

    system.on_signal(signal.SIGTERM, callback)
    assert fake.handlers == [(signal.SIGTERM, callback)]


def test_async_sleep_advances_the_clock_and_records(fake: FakeSystem) -> None:
    import asyncio

    asyncio.run(system.async_sleep(4.0))
    assert fake.slept == [4.0]
    assert system.now() == START_CLOCK + 4.0


def test_on_sleep_callbacks_run_once_each_in_order(fake: FakeSystem) -> None:
    import asyncio

    seen: list[str] = []
    fake.on_sleep = [lambda: seen.append("a"), lambda: seen.append("b")]
    system.sleep(1.0)
    asyncio.run(system.async_sleep(1.0))
    system.sleep(1.0)
    assert seen == ["a", "b"]
    assert fake.slept == [1.0, 1.0, 1.0]

"""The in-memory ``FakeSystem`` that stands in for ``agile_team.system`` (s71 P1)."""

import errno
import time
from pathlib import Path

import pytest
from agile_team import system

from .fake_system import FAKE_HOME, FAKE_IDS, FAKE_REPO, START_CLOCK, FakeSystem

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
    expected = time.strftime("%H:%M", time.gmtime(START_CLOCK))
    assert system.local_time("%H:%M") == expected


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

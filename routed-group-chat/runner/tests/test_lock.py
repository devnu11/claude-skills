"""Unit tests for ``lock``: the owned lock file, staleness and ``pid_alive``."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest
from group_chat.lock import LockError, LockFile, new_owner, pid_alive

from .lockutil import dead_pid, live_pid, write_owner

pytestmark = pytest.mark.unit


def never(_pid: int) -> bool:
    return False


def always(_pid: int) -> bool:
    return True


def test_new_owner_names_this_process() -> None:
    owner = new_owner()
    assert owner["pid"] == os.getpid()
    assert owner["host"] == socket.gethostname()
    assert len(owner["token"]) == 32
    assert new_owner()["token"] != owner["token"]


def test_held_writes_owner_and_releases(tmp_path: Path) -> None:
    lock = LockFile(tmp_path / "lock")
    with lock.held():
        holder = lock.holder()
        assert holder is not None
        assert holder["pid"] == os.getpid()
    assert not lock.path.exists()


def test_released_after_exception(tmp_path: Path) -> None:
    lock = LockFile(tmp_path / "lock")
    with pytest.raises(RuntimeError), lock.held():
        raise RuntimeError("boom")
    assert not lock.path.exists()


def test_release_keeps_a_lock_someone_else_retook(tmp_path: Path) -> None:
    lock = LockFile(tmp_path / "lock")
    with lock.held():
        write_owner(lock.path, live_pid(), token="other")
    assert json.loads(lock.path.read_text())["token"] == "other"


def test_release_when_lock_was_deleted(tmp_path: Path) -> None:
    lock = LockFile(tmp_path / "lock")
    with lock.held():
        lock.path.unlink()
    assert not lock.path.exists()


def test_live_holder_refuses_with_pid_and_host(tmp_path: Path) -> None:
    lock = LockFile(tmp_path / "lock", alive=always)
    write_owner(lock.path, 4242, host="box")
    with pytest.raises(LockError, match="is held by pid 4242 on box; delete it if"), lock.held():
        pass  # pragma: no cover
    assert json.loads(lock.path.read_text())["pid"] == 4242


def test_unreadable_holder_is_never_stale(tmp_path: Path) -> None:
    lock = LockFile(tmp_path / "lock", alive=never)
    lock.path.write_text("not json")
    with pytest.raises(LockError, match="held by another process"), lock.held():
        pass  # pragma: no cover
    assert lock.path.read_text() == "not json"


def test_non_dict_holder_is_unreadable(tmp_path: Path) -> None:
    lock = LockFile(tmp_path / "lock")
    lock.path.write_text("[1, 2]")
    assert lock.holder() is None


def test_missing_lock_has_no_holder(tmp_path: Path) -> None:
    assert LockFile(tmp_path / "lock").holder() is None


def test_dead_holder_on_this_host_is_taken_over(tmp_path: Path) -> None:
    lock = LockFile(tmp_path / "lock", alive=never)
    write_owner(lock.path, 4242)
    with lock.held():
        holder = lock.holder()
        assert holder is not None
        assert holder["pid"] == os.getpid()
    assert not lock.path.exists()


def test_dead_pid_with_real_pid_alive_is_taken_over(tmp_path: Path) -> None:
    lock = LockFile(tmp_path / "lock")
    write_owner(lock.path, dead_pid())
    with lock.held():
        assert lock.holder() is not None
    assert not lock.path.exists()


def test_foreign_host_is_never_stale(tmp_path: Path) -> None:
    lock = LockFile(tmp_path / "lock", alive=never)
    write_owner(lock.path, 4242, host="elsewhere")
    with pytest.raises(LockError, match="pid 4242 on elsewhere"), lock.held():
        pass  # pragma: no cover


HOST = socket.gethostname()


@pytest.mark.parametrize(
    "holder",
    [None, {}, {"host": "elsewhere", "pid": 1}, {"host": HOST}, {"host": HOST, "pid": "12"}],
)
def test_is_stale_false_cases(tmp_path: Path, holder: dict[str, object] | None) -> None:
    assert not LockFile(tmp_path / "lock", alive=never).is_stale(holder)


def test_bool_pid_is_not_stale(tmp_path: Path) -> None:
    assert not LockFile(tmp_path / "lock", alive=never).is_stale({"host": HOST, "pid": True})


def test_is_stale_true_for_dead_local_pid(tmp_path: Path) -> None:
    holder = {"pid": 4242, "host": HOST}
    assert LockFile(tmp_path / "lock", alive=never).is_stale(holder)
    assert not LockFile(tmp_path / "lock", alive=always).is_stale(holder)


def test_takeover_race_lost_to_new_holder(tmp_path: Path) -> None:
    path = tmp_path / "lock"

    def racing(_pid: int) -> bool:
        write_owner(path, live_pid(), token="winner")
        return False

    write_owner(path, 4242, token="dead")
    with pytest.raises(LockError, match=f"pid {live_pid()}"), LockFile(path, racing).held():
        pass  # pragma: no cover
    assert json.loads(path.read_text())["token"] == "winner"


def test_takeover_race_lost_after_removal(tmp_path: Path) -> None:
    path = tmp_path / "lock"
    calls: list[int] = []

    class Sneaky(LockFile):
        def _remove_if(self, holder: dict[str, object] | None) -> None:
            super()._remove_if(holder)
            calls.append(1)
            write_owner(path, live_pid(), token="winner")

    write_owner(path, 4242, token="dead")
    with pytest.raises(LockError), Sneaky(path, never).held():
        pass  # pragma: no cover
    assert calls == [1]


def test_pid_alive_is_always_true_on_windows() -> None:
    assert pid_alive(dead_pid(), platform="win32") is True


def test_pid_alive_posix_live_and_dead() -> None:
    assert pid_alive(live_pid(), platform="linux") is True
    assert pid_alive(dead_pid(), platform="linux") is False


def test_pid_alive_permission_error_means_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(pid: int, sig: int) -> None:
        raise PermissionError

    monkeypatch.setattr("group_chat.lock.os.kill", denied)
    assert pid_alive(1, platform="linux") is True

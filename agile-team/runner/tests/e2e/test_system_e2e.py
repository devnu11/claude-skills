"""e2e: the P1 functions of ``agile_team.system`` on the real OS (s71)."""

from __future__ import annotations

import errno
import os
import stat as stat_bits
import time
from pathlib import Path

import pytest
from agile_team import system


def test_text_round_trip_append_and_bytes(tmp_path):
    f = tmp_path / "a.txt"
    system.write_text(f, "héllo\n")
    system.append_text(f, "more\n")
    assert system.read_text(f) == "héllo\nmore\n"
    assert system.read_bytes(f) == "héllo\nmore\n".encode()


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        system.read_text(tmp_path / "none")


def test_read_end_cuts_and_reports_length(tmp_path):
    f = tmp_path / "log"
    f.write_bytes(b"0123456789")
    assert system.read_end(f, 4) == (b"6789", 10)
    assert system.read_end(f, 100) == (b"0123456789", 10)


def test_replace_moves_over_target(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_text("new")
    b.write_text("old")
    system.replace(a, b)
    assert b.read_text() == "new" and not a.exists()


def test_hard_link_shares_bytes_and_refuses_existing(tmp_path):
    target, link = tmp_path / "t", tmp_path / "l"
    target.write_text("x")
    system.hard_link(link, target)
    assert link.read_text() == "x"
    assert os.stat(link).st_ino == os.stat(target).st_ino
    with pytest.raises(FileExistsError):
        system.hard_link(link, target)


def test_make_dirs_is_idempotent_and_remove_ignores_missing(tmp_path):
    d = tmp_path / "a" / "b"
    system.make_dirs(d)
    system.make_dirs(d)
    assert d.is_dir()
    f = d / "f"
    f.write_text("1")
    system.remove(f)
    system.remove(f)
    assert not f.exists()


def test_copy_tree_keeps_symlinks_and_remove_tree_deletes(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "f").write_text("1")
    (src / "ln").symlink_to("f")
    dst = tmp_path / "dst"
    system.copy_tree(src, dst)
    assert (dst / "ln").is_symlink() and (dst / "f").read_text() == "1"
    with pytest.raises(FileExistsError):
        system.copy_tree(src, dst)
    system.remove_tree(dst)
    assert not dst.exists()
    with pytest.raises(FileNotFoundError):
        system.remove_tree(dst)


def test_predicates_list_and_glob_are_sorted(tmp_path):
    (tmp_path / "b.md").write_text("")
    (tmp_path / "a.md").write_text("")
    (tmp_path / "c.txt").write_text("")
    (tmp_path / "sub").mkdir()
    assert system.is_file(tmp_path / "a.md") and not system.is_file(tmp_path / "sub")
    assert system.is_dir(tmp_path / "sub") and not system.is_dir(tmp_path / "a.md")
    assert system.exists(tmp_path / "sub") and not system.exists(tmp_path / "zz")
    assert [p.name for p in system.list_dir(tmp_path)] == ["a.md", "b.md", "c.txt", "sub"]
    assert [p.name for p in system.glob(tmp_path, "*.md")] == ["a.md", "b.md"]


def test_stat_reports_mode_size_and_mtime(tmp_path):
    f = tmp_path / "k"
    f.write_text("abc")
    f.chmod(0o600)
    info = system.stat(f)
    assert info.mode == 0o600 == stat_bits.S_IMODE(os.stat(f).st_mode)
    assert info.size == 3
    assert info.mtime_ns == os.stat(f).st_mtime_ns
    assert abs(info.mtime - time.time()) < 60


def test_resolve_and_expand_user(tmp_path, monkeypatch):
    (tmp_path / "real").mkdir()
    (tmp_path / "ln").symlink_to("real")
    assert system.resolve(tmp_path / "ln") == (tmp_path / "real").resolve()
    monkeypatch.setenv("HOME", str(tmp_path))
    assert system.expand_user(Path("~/x")) == tmp_path / "x"


def test_clock_functions():
    assert abs(system.now() - time.time()) < 5
    a = system.monotonic()
    system.sleep(0.02)
    assert system.monotonic() - a >= 0.015
    assert system.local_time("%Y") == time.strftime("%Y")


def test_pid_and_kill_signal_zero():
    assert system.pid() == os.getpid()
    system.kill(os.getpid(), 0)
    with pytest.raises(OSError) as err:
        system.kill(2**22 + 12345, 0)
    assert err.value.errno in (errno.ESRCH, errno.EPERM, errno.EINVAL)

"""In-memory stand-in for ``agile_team.system`` (s71, ADR-011).

``FakeSystem`` implements every function in ``system.__all__`` on a dict of
files, a clock and a list of records, so a unit test never reaches the OS.
Paths are normalised with ``posixpath`` (pure string work); no ``Path`` method
that touches the OS is ever called here, because the guard would fail it.

Only the functions of the phases that exist are implemented; a phase adds its
own rows (P2: processes, signals by group, network; P3: machine and browser).
"""

from __future__ import annotations

import errno
import fnmatch
import os
import posixpath
import time
from pathlib import Path

import agile_team
import pytest
from agile_team import system

FAKE_ROOT = Path("/fake")
FAKE_REPO = FAKE_ROOT / "repo"
FAKE_HOME = FAKE_ROOT / "home"
FAKE_HEAD = "c0ffee0000000000000000000000000000000000"
FAKE_IDS = (4242, 4243)  # the runner's pid and process group in the fake
START_CLOCK = 1_800_000_000.0
DEFAULT_MODE = 0o644
DIR_MODE = 0o755

PACKAGE_DIR = Path(agile_team.__file__).parent
PACKAGE_DATA = ("roles/*.md", "presets.toml", "dashboard/index.html")


def _snapshot_package_data() -> dict[Path, bytes]:
    """Read the built-in roles, presets and UI once, at import (before any guard)."""
    found = (path for pattern in PACKAGE_DATA for path in sorted(PACKAGE_DIR.glob(pattern)))
    return {path: path.read_bytes() for path in found}


PACKAGE_FILES = _snapshot_package_data()


class FakeSystem:
    """In-memory files, clock and signals standing in for ``agile_team.system``."""

    def __init__(self) -> None:
        self.cwd = FAKE_REPO
        self.files: dict[str, bytes] = {}
        self.modes: dict[str, int] = {}
        self.mtimes: dict[str, float] = {}
        self.dirs: set[str] = {"/"}
        self.ops: list[tuple[str, Path]] = []
        self.denied: set[str] = set()
        self.full = False
        self.clock = START_CLOCK
        self.slept: list[float] = []
        self.signals: list[tuple[str, int, int]] = []
        self.groups: dict[int, int] = {}
        self._add_dirs(str(FAKE_REPO))
        for path, data in PACKAGE_FILES.items():
            self.put(path, data)

    # -- setup and failure injection (not part of ``system``) ---------------

    def put(
        self,
        path: Path,
        text: str | bytes,
        mode: int = DEFAULT_MODE,
        mtime: float | None = None,
    ) -> None:
        """Create a file (and its parents) without recording an op."""
        key = self._key(path)
        self._add_dirs(posixpath.dirname(key))
        self.files[key] = text.encode() if isinstance(text, str) else text
        self.modes[key] = mode
        self.mtimes[key] = self.clock if mtime is None else mtime

    def deny(self, path: Path) -> None:
        """Make reads of ``path`` raise ``PermissionError``."""
        self.denied.add(self._key(path))

    def fill_disk(self) -> None:
        """Make every write, append, replace, make_dirs and copy raise ENOSPC."""
        self.full = True

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Swap every function in ``system.__all__`` for this fake's method."""
        for name in system.__all__:
            monkeypatch.setattr(system, name, getattr(self, name))

    def text_of(self, path: Path) -> str:
        """The text stored at ``path`` (a test helper; ``FileNotFoundError`` if absent)."""
        return self.files[self._key(path)].decode()

    # -- paths ----------------------------------------------------------------

    def _key(self, path: Path | str) -> str:
        return posixpath.normpath(posixpath.join(str(self.cwd), os.fspath(path)))

    def _add_dirs(self, key: str) -> None:
        while key not in self.dirs:
            self.dirs.add(key)
            key = posixpath.dirname(key)

    def _need_parent(self, key: str) -> None:
        if posixpath.dirname(key) not in self.dirs:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", key)

    def _write_check(self) -> None:
        if self.full:
            raise OSError(errno.ENOSPC, "No space left on device")

    def _record(self, name: str, key: str) -> None:
        self.ops.append((name, Path(key)))

    def _children(self, key: str) -> list[str]:
        names = [*self.files, *self.dirs]
        return sorted({n for n in names if n != key and posixpath.dirname(n) == key})

    # -- reading --------------------------------------------------------------

    def read_bytes(self, path: Path) -> bytes:
        """Return the bytes of a file."""
        key = self._key(path)
        if key in self.denied:
            raise PermissionError(errno.EACCES, "Permission denied", key)
        if key in self.dirs:
            raise IsADirectoryError(errno.EISDIR, "Is a directory", key)
        if key not in self.files:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", key)
        return self.files[key]

    def read_text(self, path: Path) -> str:
        """Return the text of a file."""
        return self.read_bytes(path).decode()

    def read_end(self, path: Path, size: int) -> tuple[bytes, int]:
        """Return the last ``size`` bytes of a file and its length."""
        data = self.read_bytes(path)
        return data[max(0, len(data) - size) :], len(data)

    # -- writing --------------------------------------------------------------

    def _store(self, key: str, data: bytes) -> None:
        self._need_parent(key)
        if key in self.dirs:
            raise IsADirectoryError(errno.EISDIR, "Is a directory", key)
        self.files[key] = data
        self.modes.setdefault(key, DEFAULT_MODE)
        self.mtimes[key] = self.clock

    def write_text(self, path: Path, text: str) -> None:
        """Create or overwrite a file."""
        self._write_check()
        key = self._key(path)
        self._store(key, text.encode())
        self._record("write_text", key)

    def append_text(self, path: Path, text: str) -> None:
        """Append to a file, creating it."""
        self._write_check()
        key = self._key(path)
        self._store(key, self.files.get(key, b"") + text.encode())
        self._record("append_text", key)

    def replace(self, source: Path, target: Path) -> None:
        """Move a file over another."""
        self._write_check()
        src, dst = self._key(source), self._key(target)
        data = self.read_bytes(source)
        mode = self.modes[src]
        self._store(dst, data)
        self.modes[dst] = mode
        self._drop(src)
        self._record("replace", dst)

    def hard_link(self, link: Path, target: Path) -> None:
        """Make ``link`` another name for ``target``; fails if ``link`` exists."""
        self._write_check()
        name, src = self._key(link), self._key(target)
        data = self.read_bytes(target)
        if name in self.files or name in self.dirs:
            raise FileExistsError(errno.EEXIST, "File exists", name)
        self._store(name, data)
        self.modes[name] = self.modes[src]
        self._record("hard_link", name)

    def make_dirs(self, path: Path) -> None:
        """Create a directory and its parents."""
        self._write_check()
        key = self._key(path)
        if key in self.files:
            raise FileExistsError(errno.EEXIST, "File exists", key)
        self._add_dirs(key)
        self._record("make_dirs", key)

    def _drop(self, key: str) -> None:
        for table in (self.files, self.modes, self.mtimes):
            table.pop(key, None)

    def remove(self, path: Path) -> None:
        """Delete a file; a missing one is fine."""
        key = self._key(path)
        self._drop(key)
        self._record("remove", key)

    def _under(self, key: str) -> list[str]:
        prefix = key.rstrip("/") + "/"
        return [n for n in [*self.files, *self.dirs] if n == key or n.startswith(prefix)]

    def remove_tree(self, path: Path) -> None:
        """Delete a directory and everything in it."""
        key = self._key(path)
        if key not in self.dirs:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", key)
        for name in self._under(key):
            self._drop(name)
            self.dirs.discard(name)
        self._record("remove_tree", key)

    def copy_tree(self, source: Path, target: Path) -> None:
        """Copy a directory tree onto a path that does not exist yet."""
        self._write_check()
        src, dst = self._key(source), self._key(target)
        if src not in self.dirs:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", src)
        if dst in self.dirs or dst in self.files:
            raise FileExistsError(errno.EEXIST, "File exists", dst)
        self._add_dirs(dst)
        for name in self._under(src):
            moved = dst + name[len(src) :]
            self._copy_one(name, moved)
        self._record("copy_tree", dst)

    def _copy_one(self, name: str, moved: str) -> None:
        if name in self.dirs:
            self._add_dirs(moved)
            return
        self.put(Path(moved), self.files[name], self.modes[name], self.mtimes[name])

    # -- looking ---------------------------------------------------------------

    def is_file(self, path: Path) -> bool:
        """Whether the path is a file."""
        return self._key(path) in self.files

    def is_dir(self, path: Path) -> bool:
        """Whether the path is a directory."""
        return self._key(path) in self.dirs

    def exists(self, path: Path) -> bool:
        """Whether the path is a file or a directory."""
        return self.is_file(path) or self.is_dir(path)

    def list_dir(self, path: Path) -> list[Path]:
        """Direct children, sorted."""
        key = self._key(path)
        if key not in self.dirs:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", key)
        return [Path(name) for name in self._children(key)]

    def glob(self, path: Path, pattern: str) -> list[Path]:
        """Direct children matching ``pattern``, sorted (no ``**``)."""
        key = self._key(path)
        return [
            Path(name)
            for name in self._children(key)
            if fnmatch.fnmatchcase(posixpath.basename(name), pattern)
        ]

    def stat(self, path: Path) -> system.FileStat:
        """Mtime, size and permission bits."""
        key = self._key(path)
        if key in self.files:
            mtime, size, mode = self.mtimes[key], len(self.files[key]), self.modes[key]
        elif key in self.dirs:
            mtime, size, mode = self.clock, 0, DIR_MODE
        else:
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", key)
        return system.FileStat(mtime, int(mtime * 1e9), size, mode)

    def resolve(self, path: Path) -> Path:
        """The normalised absolute path."""
        return Path(self._key(path))

    def expand_user(self, path: Path) -> Path:
        """Map a leading ``~`` to the fake home."""
        text = os.fspath(path)
        return FAKE_HOME / text[2:] if text.startswith("~") else path

    # -- clock and ids ----------------------------------------------------------

    def now(self) -> float:
        """The fake wall clock."""
        return self.clock

    def monotonic(self) -> float:
        """The fake monotonic clock (the same timeline)."""
        return self.clock

    def local_time(self, fmt: str) -> str:
        """The fake clock formatted (UTC, so tests do not depend on a zone)."""
        return time.strftime(fmt, time.gmtime(self.clock))

    def sleep(self, seconds: float) -> None:
        """Record the sleep and advance the clock by it."""
        self.slept.append(seconds)
        self.clock += seconds

    def pid(self) -> int:
        """The runner's pid in the fake."""
        return FAKE_IDS[0]

    def kill(self, pid: int, sig: int) -> None:
        """Record a signal to a pid; signal 0 and dead pids raise like the OS."""
        self.signals.append(("kill", pid, sig))
        if pid != FAKE_IDS[0] and pid not in self.groups:
            raise ProcessLookupError(errno.ESRCH, "No such process")

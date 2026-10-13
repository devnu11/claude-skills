"""In-memory stand-in for ``agile_team.system`` (s71, ADR-011).

``FakeSystem`` implements every function in ``system.__all__`` on a dict of
files, a clock and a list of records, so a unit test never reaches the OS.
Paths are normalised with ``posixpath`` (pure string work); no ``Path`` method
that touches the OS is ever called here, because the guard would fail it.

Every function of ``system.__all__`` is implemented (P3 closed the seam): scripted
commands, children that run until their group is signalled, process groups, the
environment, the network, the machine, the browser and signals. ``track()`` adds a
small git working-tree model (``fake_git.py``) for tests that follow commits.
"""

from __future__ import annotations

import errno
import fnmatch
import os
import posixpath
import signal
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, NamedTuple

import agile_team
import pytest
from agile_team import system

from .fake_git import FakeTree, tree_reply

FAKE_ROOT = Path("/fake")
FAKE_REPO = FAKE_ROOT / "repo"
FAKE_HOME = FAKE_ROOT / "home"
FAKE_HEAD = "c0ffee0000000000000000000000000000000000"
FAKE_IDS = (4242, 4243)  # the runner's pid and process group in the fake
START_CLOCK = 1_800_000_000.0
DEFAULT_MODE = 0o644
DIR_MODE = 0o755
FIRST_CHILD_PID = 5000  # the first spawned child's pid; each spawn adds 1
FAKE_HOSTNAME = "fakehost"
FREE_PORT = 50000  # what a server asked for port 0 is given

PACKAGE_DIR = Path(agile_team.__file__).parent
PACKAGE_DATA = (
    "roles/*.md",
    "presets.toml",
    "dashboard/index.html",
    "dashboard/fixtures/*.json",
    "dashboard/seed/.agile-team.toml",
)


def _snapshot_package_data() -> dict[Path, bytes]:
    """Read the built-in roles, presets and UI once, at import (before any guard)."""
    found = (path for pattern in PACKAGE_DATA for path in sorted(PACKAGE_DIR.glob(pattern)))
    return {path: path.read_bytes() for path in found}


PACKAGE_FILES = _snapshot_package_data()


class Done(NamedTuple):
    """One scripted command result: it has already exited."""

    code: int = 0
    out: str = ""
    err: str = ""


class Hang(NamedTuple):
    """A scripted child that runs until its group is signalled; ``out`` is what it wrote."""

    out: str = ""


class FakeProcess:
    """A spawned child: ``Done`` has exited; ``Hang`` runs until the fake signals it."""

    def __init__(self, fake: FakeSystem, pid: int, result: Done | Hang) -> None:
        self.fake = fake
        self.pid = pid
        self.out = result.out
        self.returncode: int | None = result.code if isinstance(result, Done) else None

    def poll(self) -> int | None:
        """The exit code, or ``None`` while the child runs."""
        return self.returncode

    def _hang(self, timeout: float | None) -> None:
        self.fake.clock += timeout or 0.0
        raise system.TimeoutExpired("fake", timeout or 0.0)

    def wait(self, timeout: float | None = None) -> int:
        """The exit code; a running child times out on the fake clock."""
        if self.returncode is None:
            self._hang(timeout)
        return self.returncode  # type: ignore[return-value]

    def communicate(self, timeout: float | None = None) -> tuple[str, None]:
        """The output once the child has ended; a running child times out."""
        if self.returncode is None:
            self._hang(timeout)
        return self.out, None

    def __enter__(self) -> FakeProcess:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeServer:
    """What ``listen_http`` returns: records the address, ``serve_forever`` returns at once."""

    def __init__(self, address: tuple[str, int], handler: type) -> None:
        port = address[1] or FREE_PORT
        self.server_address = (address[0], port)
        self.RequestHandlerClass = handler
        self.daemon_threads = False
        self.app: Any = None
        self.closed = False

    def serve_forever(self) -> None:
        """Return at once."""

    def shutdown(self) -> None:
        """Nothing to stop."""

    def server_close(self) -> None:
        """Record the close."""
        self.closed = True

    def __enter__(self) -> FakeServer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.server_close()


class _Rule:
    """A scripted reply: the words to find in the argv, in order, and the results to give."""

    def __init__(self, words: tuple[str, ...], results: tuple[Any, ...]) -> None:
        self.words = words
        self.results = results
        self.used = 0

    def matches(self, argv: list[str]) -> bool:
        """Whether the words appear in ``argv`` in order (a subsequence)."""
        rest = iter(argv)
        return all(word in rest for word in self.words)

    def next(self) -> Any:
        """The next result; the last one repeats."""
        result = self.results[min(self.used, len(self.results) - 1)]
        self.used += 1
        return result


class FakeSystem:
    """In-memory files, clock and signals standing in for ``agile_team.system``."""

    def __init__(self) -> None:
        self.workdir = FAKE_REPO
        self.files: dict[str, bytes] = {}
        self.modes: dict[str, int] = {}
        self.mtimes: dict[str, float] = {}
        self.dirs: set[str] = {"/"}
        self.ops: list[tuple[str, Path]] = []
        self.denied: set[str] = set()
        self.full = False
        self.clock = START_CLOCK
        self.asleep = 0.0
        self.platform_name = "darwin"
        self.slept: list[float] = []
        self.signals: list[tuple[str, int, int]] = []
        self.groups: dict[int, int] = {FAKE_IDS[0]: FAKE_IDS[1]}
        self.tokens = 0
        self.survivors: set[int] = set()
        self.commands: list[Any] = []
        self.rules: list[_Rule] = []
        self.procs: dict[int, FakeProcess] = {}
        self.next_pid = FIRST_CHILD_PID
        self.ticks = 0
        self.env: dict[str, str] = {}
        self.listening: set[tuple[str, int]] = set()
        self.holds: dict[int, tuple[str, int]] = {}
        self.web: dict[str, Any] = {}
        self.listened: list[tuple[str, int]] = []
        self.servers: list[FakeServer] = []
        self.programs: dict[str, str] = {}
        self.opened: list[str] = []
        self.handlers: list[tuple[int, Callable[[], object]]] = []
        self.on_sleep: list[Callable[[], object]] = []
        self.tree: FakeTree | None = None
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

    def reply(self, words: tuple[str, ...], *results: Any) -> None:
        """Script a command: the last matching rule wins; results go in turn, the last repeats."""
        self.rules.append(_Rule(words, results or (Done(),)))

    def track(self) -> FakeTree:
        """Model the repo's working tree: status, add, commit, revert and log follow the files."""
        seeded = (("git", "rev-parse", "HEAD"), ("git", "symbolic-ref"))
        self.rules = [r for r in self.rules if r.words not in seeded]
        self.tree = FakeTree(self, FAKE_HEAD)
        return self.tree

    def text_of(self, path: Path) -> str:
        """The text stored at ``path`` (a test helper; ``FileNotFoundError`` if absent)."""
        return self.files[self._key(path)].decode()

    # -- paths ----------------------------------------------------------------

    def _key(self, path: Path | str) -> str:
        return posixpath.normpath(posixpath.join(str(self.workdir), os.fspath(path)))

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
        """The fake monotonic clock: the wall timeline less the time spent asleep."""
        return self.clock - self.asleep

    def doze(self, seconds: float) -> None:
        """The machine sleeps: wall time moves on, the monotonic clock does not (s97)."""
        self.clock += seconds
        self.asleep += seconds

    def platform(self) -> str:
        """The fake OS name (``darwin`` unless a test sets ``platform_name``)."""
        return self.platform_name

    def local_time(self, fmt: str) -> str:
        """The fake clock formatted (UTC, so tests do not depend on a zone)."""
        return time.strftime(fmt, time.gmtime(self.clock))

    def sleep(self, seconds: float) -> None:
        """Record the sleep, advance the clock, run the next ``on_sleep`` callback."""
        self.slept.append(seconds)
        self.clock += seconds
        if self.on_sleep:
            self.on_sleep.pop(0)()

    async def async_sleep(self, seconds: float) -> None:
        """Behave as ``sleep`` (no real wait)."""
        self.sleep(seconds)

    def cwd(self) -> Path:
        """The fake working directory (the fake repo)."""
        return FAKE_REPO

    def home(self) -> Path:
        """The fake home directory."""
        return FAKE_HOME

    def which(self, name: str) -> str | None:
        """The path scripted for ``name`` in ``programs``, else ``None``."""
        return self.programs.get(name)

    def open_browser(self, url: str) -> bool:
        """Record the url; report success."""
        self.opened.append(url)
        return True

    def on_signal(self, sig: int, callback: Callable[[], object]) -> None:
        """Record the handler; no signal is ever delivered."""
        self.handlers.append((sig, callback))

    def pid(self) -> int:
        """The runner's pid in the fake."""
        return FAKE_IDS[0]

    def token(self) -> str:
        """A predictable token: ``tok1``, ``tok2``, ... (s83)."""
        self.tokens += 1
        return f"tok{self.tokens}"

    def pgrp(self) -> int:
        """The runner's process group in the fake."""
        return FAKE_IDS[1]

    def pgid(self, pid: int) -> int:
        """The group of a live pid; ``ProcessLookupError`` for an unknown one."""
        if pid not in self.groups:
            raise ProcessLookupError(errno.ESRCH, "No such process")
        return self.groups[pid]

    def _end(self, pid: int, sig: int) -> None:
        self.groups.pop(pid, None)
        address = self.holds.pop(pid, None)
        self.listening.discard(address)  # type: ignore[arg-type]
        child = self.procs.get(pid)
        if child is not None and child.returncode is None:
            child.returncode = -sig

    def _deliver(self, pids: list[int], sig: int) -> None:
        for pid in pids:
            spared = sig == signal.SIGTERM and pid in self.survivors
            if pid != FAKE_IDS[0] and not spared:
                self._end(pid, sig)

    def kill(self, pid: int, sig: int) -> None:
        """Record a signal to a pid; a dead pid raises; a live one ends unless it survives."""
        self.signals.append(("kill", pid, sig))
        if pid not in self.groups:
            raise ProcessLookupError(errno.ESRCH, "No such process")
        if sig != 0:
            self._deliver([pid], sig)

    def killpg(self, pgid: int, sig: int) -> None:
        """Signal every member of a group; signal 0 only checks that one is alive."""
        members = [pid for pid, group in self.groups.items() if group == pgid]
        if sig != 0:
            self.signals.append(("killpg", pgid, sig))
        if not members:
            raise ProcessLookupError(errno.ESRCH, "No such process")
        if sig != 0:
            self._deliver(members, sig)

    def wait_event(self, event: threading.Event, timeout: float) -> bool:
        """True at once if set; else advance the clock and time out while ``ticks`` last."""
        if event.is_set():
            return True
        if self.ticks <= 0:
            return True
        self.ticks -= 1
        self.clock += timeout
        return False

    def environ(self) -> Mapping[str, str]:
        """The scripted environment (empty by default)."""
        return self.env

    # -- commands and children -------------------------------------------------

    def _result(self, argv: list[str]) -> Any:
        for rule in reversed(self.rules):
            if rule.matches(argv):
                return rule.next()
        modelled = tree_reply(self.tree, argv[1:]) if self.tree and argv[:1] == ["git"] else None
        return modelled or Done()

    def _scripted(self, command: Any, argv: list[str]) -> Any:
        self.commands.append(command)
        result = self._result(argv)
        if isinstance(result, BaseException):
            raise result
        return result

    def run(self, command: Any) -> Any:
        """Run a scripted argv; a ``Hang`` times out on the fake clock."""
        result = self._scripted(command, list(command.argv))
        if isinstance(result, Hang):
            self.clock += command.timeout or 0.0
            raise system.TimeoutExpired(list(command.argv), command.timeout or 0.0)
        return system.Completed(result.code, result.out, result.err)

    def run_shell(self, command: Any) -> int:
        """Run a scripted shell line and return its exit code."""
        result = self._scripted(command, command.text.split())
        return result.code if isinstance(result, Done) else 0

    def _spawn(self, command: Any) -> FakeProcess:
        result = self._scripted(command, command.text.split())
        pid = self.next_pid
        self.next_pid += 1
        self.groups[pid] = pid
        child = FakeProcess(self, pid, result)
        self.procs[pid] = child
        return child

    def spawn_piped(self, command: Any) -> FakeProcess:
        """Start a scripted child in its own session, its output piped."""
        return self._spawn(command)

    def spawn_logged(self, command: Any, log: Path) -> FakeProcess:
        """Start a scripted child in its own session; its output is written to ``log``."""
        child = self._spawn(command)
        self.write_text(log, child.out)
        return child

    # -- network -----------------------------------------------------------------

    def http_get(self, url: str, timeout: float) -> Any:
        """The scripted reply for ``url``; an unknown URL refuses the connection."""
        reply = self.web.get(url, ConnectionRefusedError(errno.ECONNREFUSED, "refused"))
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def connect(self, address: tuple[str, int]) -> None:
        """Succeed only for an address in ``listening``."""
        if address not in self.listening:
            raise ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused")

    def hostname(self) -> str:
        """The fake machine's name."""
        return FAKE_HOSTNAME

    def listen_http(self, address: tuple[str, int], handler: type) -> FakeServer:
        """A fake server; an address already in ``listening`` is in use."""
        if address in self.listening:
            raise OSError(errno.EADDRINUSE, "Address already in use")
        self.listened.append(address)
        server = FakeServer(address, handler)
        self.servers.append(server)
        return server

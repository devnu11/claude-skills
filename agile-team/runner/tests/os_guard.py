"""Fail a unit test that reaches the real OS (s71, ADR-011).

Two mechanisms, both driven by tables:

* an audit hook (``hook``) for calls that raise an audit event (files, processes,
  signals, network, ...);
* a patch table (``PATCHED``) for calls with no audit event (pids, waits, signal
  handlers, ``shutil.which``, ``platform``, ``os.stat``, ...).

Both raise ``RealOsCall``. It is a ``BaseException`` so ``except Exception`` in
the code under test cannot swallow it; a violation is also recorded, so one
swallowed anyway still fails the test when the phase ends.

An audited call made while ``traceback``/``linecache`` read source is the stdlib's (s89).
"""

from __future__ import annotations

import importlib
import itertools
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from enum import Enum
from typing import Any, NamedTuple

import pytest

GUIDANCE = "inject it, or move the test to tests/e2e/"
MESSAGE = "unit test reached the real OS: {call} ({category}); " + GUIDANCE
CALLER_NOTE = " (caller: {caller})"


class RealOsCall(BaseException):
    """A unit test (or the code under it) reached the real OS."""


class World(Enum):
    """Which world a test runs in."""

    FAKE = "fake"  # unit tests: the fake is installed and the guard is on
    REAL = "real"  # tests/e2e/


class Patched(NamedTuple):
    """A call with no audit event: module, attribute, category."""

    module: str
    name: str
    category: str


AUDITED: dict[str, str] = {
    "open": "filesystem",
    "os.mkdir": "filesystem",
    "os.listdir": "filesystem",
    "os.scandir": "filesystem",
    "glob.glob": "filesystem",
    "os.rename": "filesystem",
    "os.remove": "filesystem",
    "os.rmdir": "filesystem",
    "shutil.copyfile": "filesystem",
    "shutil.copytree": "filesystem",
    "shutil.rmtree": "filesystem",
    "shutil.move": "filesystem",
    "os.chmod": "filesystem",
    "os.chown": "filesystem",
    "os.symlink": "filesystem",
    "os.link": "filesystem",
    "os.utime": "filesystem",
    "os.chdir": "filesystem",
    "tempfile.mkdtemp": "filesystem",
    "tempfile.mkstemp": "filesystem",
    "subprocess.Popen": "process",
    "os.system": "process",
    "os.exec": "process",
    "os.spawn": "process",
    "os.posix_spawn": "process",
    "os.fork": "process",
    "os.forkpty": "process",
    "os.kill": "signal",
    "os.killpg": "signal",
    "signal.pthread_kill": "signal",
    "time.sleep": "clock",
    "socket.connect": "network",
    "socket.bind": "network",
    "socket.getaddrinfo": "network",
    "socket.gethostname": "machine",
    "socket.gethostbyname": "network",
    "urllib.Request": "network",
    "webbrowser.open": "network",
}

OS_IDS = ("getpid", "getppid", "getpgrp", "getpgid", "getsid", "setsid", "setpgid", "setpgrp")
OS_WAITS = ("wait", "waitpid", "wait3", "wait4", "waitid")
OS_MACHINE = ("getuid", "geteuid", "getgid", "uname", "cpu_count")
OS_FILES = ("getcwd", "stat", "lstat")  # stat/lstat catch exists, is_file, stat, resolve
PLATFORM = ("system", "machine", "node", "platform", "release", "version", "uname", "processor")

PATCHED: tuple[Patched, ...] = (
    *(Patched("os", name, "process") for name in (*OS_IDS, *OS_WAITS)),
    *(Patched("os", name, "machine") for name in OS_MACHINE),
    *(Patched("os", name, "filesystem") for name in OS_FILES),
    Patched("signal", "signal", "signal"),
    Patched("signal", "alarm", "signal"),
    Patched("signal", "setitimer", "signal"),
    Patched("time", "sleep", "clock"),
    Patched("shutil", "which", "machine"),
    Patched("shutil", "disk_usage", "machine"),
    *(Patched("platform", name, "machine") for name in PLATFORM),
    Patched("getpass", "getuser", "machine"),
)

# Top-level stdlib modules skipped when finding who made a call (pathlib._local counts).
PASS_THROUGH: frozenset[str] = frozenset(
    [
        "os",
        "posixpath",
        "genericpath",
        "pathlib",
        "io",
        "shutil",
        "subprocess",
        "glob",
        "fnmatch",
        "tempfile",
        "socket",
    ]
)

# Callers whose audited events are allowed (imports, source lines, tracebacks, coverage, xdist).
EXEMPT_CALLERS: tuple[str, ...] = (
    "importlib._bootstrap",
    "importlib._bootstrap_external",
    "_frozen_importlib",
    "zipimport",
    "linecache",
    "tokenize",
    "traceback",
    "coverage",
    "execnet",
    "xdist",
    "_pytest.capture",
    "_pytest.logging",
)

# Stdlib modules that read source for a traceback; an audited call beneath them is theirs (s89).
SOURCE_READERS: tuple[str, ...] = ("traceback", "linecache")

# Callers whose patched calls are refused; every other caller gets the real function.
GUARDED_CALLERS: tuple[str, ...] = ("agile_team", "tests")


class _Guard:
    """Whether the guard is on, and the violations recorded while it was."""

    def __init__(self) -> None:
        self.on = False
        self.violations: list[str] = []


_guard = _Guard()


def _modules() -> Iterator[str]:
    """Module names on the stack, innermost first, skipping this file's frames."""
    frame = sys._getframe()
    while frame is not None:
        name = frame.f_globals.get("__name__", "")
        if name != __name__:
            yield name
        frame = frame.f_back


def _caller() -> str:
    """The module of the first frame outside the stdlib wrappers and this file."""
    return next((n for n in _modules() if n.split(".")[0] not in PASS_THROUGH), "")


def _reading_source() -> bool:
    """Whether a source reader is on the stack inside the nearest guarded frame (T1)."""
    inside = itertools.takewhile(lambda n: not n.startswith(GUARDED_CALLERS), _modules())
    return any(n.startswith(SOURCE_READERS) for n in inside)


def _allowed() -> bool:
    """Allowed from an exempt caller (T2) or while the stdlib reads source (T1)."""
    return _caller().startswith(EXEMPT_CALLERS) or _reading_source()


def _violation(call: str, category: str) -> RealOsCall:
    message = MESSAGE.format(call=call, category=category) + CALLER_NOTE.format(
        caller=_caller() or "no python frame"
    )
    _guard.violations.append(message)
    return RealOsCall(message)


def hook(event: str, args: tuple[Any, ...]) -> None:
    """The audit hook: refuse an audited event unless it is allowed (T1, T2)."""
    category = AUDITED.get(event)
    if category is None or not _guard.on or _allowed():
        return
    raise _violation(event, category)


def _wrapper(row: Patched, real: Callable[..., Any]) -> Callable[..., Any]:
    def guarded(*args: Any, **kwargs: Any) -> Any:
        if _guard.on and _caller().startswith(GUARDED_CALLERS):
            raise _violation(f"{row.module}.{row.name}", row.category)
        return real(*args, **kwargs)

    return guarded


def _patch(patcher: pytest.MonkeyPatch, row: Patched) -> None:
    module = importlib.import_module(row.module)
    real = getattr(module, row.name, None)
    if real is not None:
        patcher.setattr(module, row.name, _wrapper(row, real))


@contextmanager
def _fake_world() -> Iterator[None]:
    patcher = pytest.MonkeyPatch()
    outer_on, outer_seen = _guard.on, _guard.violations
    _guard.violations = []
    for row in PATCHED:
        _patch(patcher, row)
    _guard.on = True
    try:
        yield
        seen = _guard.violations
    finally:
        _guard.on, _guard.violations = outer_on, outer_seen
        patcher.undo()
    if seen:
        pytest.fail(seen[0], pytrace=False)


WORLD_CONTEXTS: dict[World, Callable[[], Any]] = {
    World.FAKE: _fake_world,
    World.REAL: nullcontext,
}


def watching(world: World) -> Any:
    """Context manager: the guard is on for ``FAKE`` and does nothing for ``REAL``."""
    return WORLD_CONTEXTS[world]()


def reset() -> None:
    """Forget recorded violations (for the guard's own tests, after a deliberate hit)."""
    _guard.violations.clear()


WORLDS = {True: World.REAL, False: World.FAKE}


def world_of(item: Any) -> World:
    """``REAL`` for ``tests/e2e/``, else ``FAKE``."""
    return WORLDS[item.path.parent.name == "e2e"]

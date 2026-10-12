"""Fail a unit test that reaches the real OS (s71, ADR-011).

Two mechanisms, both driven by tables:

* an audit hook (``hook``) for calls that raise an audit event (files, processes,
  signals, network, ...);
* a patch table (``PATCHED``) for calls with no audit event (pids, waits, signal
  handlers, ``shutil.which``, ``platform``, ``os.stat``, ...).

Both raise ``RealOsCall``. It is a ``BaseException`` so ``except Exception`` in
the code under test cannot swallow it; a violation is also recorded, so one
swallowed anyway still fails the test when the phase ends.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from enum import Enum
from typing import Any, NamedTuple

import pytest

GUIDANCE = "inject it, or move the test to tests/e2e/"
MESSAGE = "unit test reached the real OS: {call} ({category}); " + GUIDANCE


class RealOsCall(BaseException):
    """A unit test (or the code under it) reached the real OS."""


class World(Enum):
    """Which world a test runs in."""

    FAKE = "fake"  # unit tests: the fake is installed and the guard is on
    REAL = "real"  # tests/e2e/ (and LEGACY files until P3)


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

# Callers whose audited events are allowed (imports, source lines, coverage, xdist).
EXEMPT_CALLERS: tuple[str, ...] = (
    "importlib._bootstrap",
    "importlib._bootstrap_external",
    "_frozen_importlib",
    "zipimport",
    "linecache",
    "tokenize",
    "coverage",
    "execnet",
    "xdist",
    "_pytest.capture",
    "_pytest.logging",
)

# Callers whose patched calls are refused; every other caller gets the real function.
GUARDED_CALLERS: tuple[str, ...] = ("agile_team", "tests")

# Unit-test files not yet migrated to the fake (s71 P1 to P3); they run in the real world.
LEGACY: frozenset[str] = frozenset(
    {
        "test_boundary.py",
        "test_boundary_runner.py",
        "test_boundary_wiring.py",
        "test_cli.py",
        "test_dispatch.py",
        "test_disputes.py",
        "test_fullcheck.py",
        "test_halt.py",
        "test_lean_context.py",
        "test_po_cost.py",
        "test_po_tools.py",
        "test_preflight.py",
        "test_router.py",
        "test_s24.py",
        "test_s27_backstop.py",
        "test_s30.py",
        "test_s38.py",
        "test_s40.py",
        "test_s44_wiring.py",
        "test_s45.py",
        "test_s46.py",
        "test_s47.py",
        "test_s61.py",
        "test_s62_pin.py",
        "test_s62_resume.py",
        "test_s62_tell.py",
        "test_s69_runtime.py",
        "test_s69_suite.py",
        "test_s9.py",
        "test_stack.py",
        "test_upstream.py",
    }
)


class _Guard:
    """Whether the guard is on, and the violations recorded while it was."""

    def __init__(self) -> None:
        self.on = False
        self.violations: list[str] = []


_guard = _Guard()


def _caller() -> str:
    """The module of the first frame outside the stdlib wrappers and this file."""
    frame = sys._getframe(1)
    while frame is not None:
        name = frame.f_globals.get("__name__", "")
        if name.split(".")[0] not in PASS_THROUGH and name != __name__:
            return name
        frame = frame.f_back
    return ""


def _violation(call: str, category: str) -> RealOsCall:
    message = MESSAGE.format(call=call, category=category)
    _guard.violations.append(message)
    return RealOsCall(message)


def hook(event: str, args: tuple[Any, ...]) -> None:
    """The audit hook: refuse an audited event unless an exempt module made it."""
    category = AUDITED.get(event)
    if category is None or not _guard.on:
        return
    if _caller().startswith(EXEMPT_CALLERS):
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
    """``REAL`` for ``tests/e2e/`` and ``LEGACY`` files, else ``FAKE``."""
    is_real = item.path.parent.name == "e2e" or item.path.name in LEGACY
    return WORLDS[is_real]

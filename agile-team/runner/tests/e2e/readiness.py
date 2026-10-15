"""Readiness waits for e2e tests: conditions with generous monotonic deadlines (s107 F1)."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agile_team import events as events_mod

from .. import clock

STARTUP_S = 120.0
POLL_S = 0.05
BOOT = "import sys; from agile_team.cli import main; sys.exit(main())"
RUNNER = Path(events_mod.__file__).parent.parent
DASHBOARD_URL = re.compile(r"dashboard: (http://\S+)")
LOCAL = ("--host", "127.0.0.1", "--port", "0", "--no-open")


def wait_until(check: Callable[[], bool], what: str) -> None:
    """Poll ``check`` every POLL_S; fail at the monotonic deadline naming ``what``."""
    deadline = clock.Deadline(STARTUP_S)
    while not check():
        assert not deadline.passed(), f"{what} not within {STARTUP_S:.0f} s"
        time.sleep(POLL_S)


class Output:
    """A child's merged stdout, read line by line on a daemon thread and kept (F5)."""

    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self.proc = proc
        self._lines: list[str] = []
        self._eof = False
        self._cond = threading.Condition()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for line in self.proc.stdout:
            with self._cond:
                self._lines.append(line)
                self._cond.notify_all()
        with self._cond:
            self._eof = True
            self._cond.notify_all()

    def wait_for(self, pattern: re.Pattern[str]) -> re.Match[str]:
        """The first kept line matching ``pattern``, waiting for new ones."""
        deadline = clock.Deadline(STARTUP_S)
        seen = 0
        with self._cond:
            while True:
                for line in self._lines[seen:]:
                    match = pattern.search(line)
                    if match:
                        return match
                seen = len(self._lines)
                left = deadline.left()
                if self._eof or left <= 0:
                    break
                self._cond.wait(left)
        self._fail(pattern)

    def _fail(self, pattern: re.Pattern[str]) -> None:
        try:
            code = self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            code = None
        raise AssertionError(
            f"{pattern.pattern} not printed within {STARTUP_S:.0f} s (exit {code}); "
            f"output:\n{self.text()}"
        )

    def lines(self) -> list[str]:
        """Every line kept so far."""
        with self._cond:
            return list(self._lines)

    def text(self) -> str:
        """Every line kept so far, joined."""
        return "".join(self.lines())


@dataclass(frozen=True)
class Launch:
    """How to start ``agile-team dashboard`` for a test."""

    repo: Path
    home: Path
    args: tuple[str, ...] = LOCAL


@dataclass(frozen=True)
class Dashboard:
    """A running dashboard process, its kept output and its URL."""

    proc: subprocess.Popen[str]
    output: Output
    url: str


@contextmanager
def dashboard(launch: Launch) -> Iterator[Dashboard]:
    """Start the dashboard, wait for its URL line, yield, then kill it."""
    env = {**os.environ, "AGILE_TEAM_HOME": str(launch.home)}
    cmd = [sys.executable, "-c", BOOT, "--repo", str(launch.repo), "dashboard", *launch.args]
    proc = subprocess.Popen(
        cmd, cwd=RUNNER, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    try:
        output = Output(proc)
        yield Dashboard(proc, output, output.wait_for(DASHBOARD_URL).group(1))
    finally:
        proc.kill()
        proc.wait(timeout=10)


def _accepts(address: tuple[str, int]) -> bool:
    try:
        socket.create_connection(address, timeout=5).close()
    except OSError:
        return False
    return True


def serving(handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    """Start an in-thread server on 127.0.0.1:0 and wait until it accepts a connection."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    where = f"{handler.__name__} at {server.server_address}"
    wait_until(lambda: _accepts(server.server_address[:2]), where)
    return server

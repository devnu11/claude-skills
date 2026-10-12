"""Which process groups the runner may signal (s41): only groups it created, never its own."""

from __future__ import annotations

import contextlib
import os
import subprocess
import time
from dataclasses import dataclass

STARTED_SLACK_S = 2.0  # etime has 1 s resolution, and mtime and now are both truncated
PS_TIMEOUT_S = 5.0
ETIME_COMMAND = ("ps", "-o", "etime=", "-p")


def leads_own_group(pid: int) -> bool:
    """True for a live process, not the runner's group, that leads its own group."""
    try:
        return pid > 1 and pid != os.getpgrp() and os.getpgid(pid) == pid
    except OSError:
        return False


def may_signal_child_group(pid: int) -> bool:
    """True when ``pid`` is a child's group the runner may signal (G2)."""
    if pid <= 1 or pid == os.getpgrp():
        return False
    try:
        return os.getpgid(pid) == pid
    except ProcessLookupError:
        return True  # the leader exited; an unreaped Popen still holds the pid
    except OSError:
        return False


def signal_child_group(pid: int, sig: int) -> None:
    """Send ``sig`` to the group led by child ``pid``, if it is the child's own."""
    if may_signal_child_group(pid):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, sig)


def in_runner_group(pid: int) -> bool:
    """True when ``pid`` is alive and in the runner's process group."""
    try:
        return os.getpgid(pid) == os.getpgrp()
    except (OSError, OverflowError):
        return False


@dataclass(frozen=True)
class RunnerIds:
    """The runner's own pid and process group: never a signal target (s70)."""

    pid: int
    pgrp: int

    @classmethod
    def current(cls) -> RunnerIds:
        """The live process's ids, read now."""
        return cls(os.getpid(), os.getpgrp())

    def names(self, pid: int) -> bool:
        """True when ``pid`` is the runner's pid or its process group."""
        return pid in (self.pid, self.pgrp)


def parse_etime(text: str) -> float | None:
    """Seconds in ``ps`` elapsed time ``[[dd-]hh:]mm:ss``, or ``None``."""
    days, _, clock = text.strip().rpartition("-")
    parts = clock.split(":")
    if len(parts) not in (2, 3) or not all(
        p.isdigit() for p in (*parts, *([days] if days else []))
    ):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return float(seconds + int(days or 0) * 86400)


def _elapsed(pid: int) -> str | None:
    """The ``etime`` text from ``ps``, or ``None`` when it cannot be read."""
    try:
        done = subprocess.run(
            [*ETIME_COMMAND, str(pid)],
            timeout=PS_TIMEOUT_S,
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def started_at(pid: int) -> float | None:
    """When ``pid`` started (epoch seconds), or ``None`` when unknown."""
    elapsed = parse_etime(_elapsed(pid) or "")
    return None if elapsed is None else time.time() - elapsed


@dataclass(frozen=True)
class Recorded:
    """A process group named in a pid file, and when that file was written."""

    pid: int
    written: float

    def is_ours(self) -> bool:
        """True when the pid leads its own group and started before the file was written."""
        if not leads_own_group(self.pid):
            return False
        started = started_at(self.pid)
        return started is not None and started <= self.written + STARTED_SLACK_S

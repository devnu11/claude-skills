"""Keep the machine from idle-sleeping while a job is supervised.

The inhibitor watches the supervisor's pid and exits with it, even after a
crash: ``caffeinate -i -w`` on macOS, ``systemd-inhibit`` around
``tail --pid`` on Linux. Other platforms (Windows) have no inhibitor here; the
job still runs and its log says sleep is not prevented. Closing a laptop lid
still sleeps it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from enum import StrEnum
from typing import Any

Spawn = Callable[[list[str]], Any]


class SleepPolicy(StrEnum):
    """Whether a job keeps the machine awake while it runs and waits."""

    PREVENT = "prevent"
    ALLOW = "allow"


INHIBITORS: dict[str, Callable[[int], list[str]]] = {
    "darwin": lambda pid: ["caffeinate", "-i", "-w", str(pid)],
    "linux": lambda pid: [
        "systemd-inhibit", "--what=idle:sleep", "--who=unattended", "--why=job running",
        "tail", f"--pid={pid}", "-f", "/dev/null",
    ],
}  # fmt: skip


def inhibitor(pid: int, platform: str = sys.platform) -> list[str] | None:
    """The command that blocks idle sleep until ``pid`` exits, if one is installed."""
    make = INHIBITORS.get(platform)
    command = make(pid) if make else None
    return command if command and shutil.which(command[0]) else None


def detached(command: list[str]) -> subprocess.Popen[bytes]:
    devnull = subprocess.DEVNULL
    return subprocess.Popen(command, stdin=devnull, stdout=devnull, stderr=devnull)


spawn: Spawn = detached


def keep_awake(pid: int) -> str | None:
    """Start the inhibitor for ``pid``; the tool's name, or None when there is none."""
    command = inhibitor(pid)
    if command:
        spawn(command)
    return command[0] if command else None

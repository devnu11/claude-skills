"""The command's process group, per platform: how to start one and how to end it.

On macOS and Linux the command gets a new session, and its group is signalled
(SIGTERM, then SIGKILL). On Windows it gets a new process group: a graceful
stop sends CTRL_BREAK to the group, and the hard stop runs ``taskkill /T /F``
on its process tree.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

TASKKILL = ("taskkill", "/T", "/F", "/PID")


@dataclass(frozen=True)
class Group:
    """How one platform starts a process group (``Popen`` keywords) and ends it."""

    spawn: Mapping[str, Any]
    terminate: Callable[[int], None]
    kill: Callable[[int], None]


def current() -> Group:
    """The running platform's group."""
    return GROUPS.get(sys.platform, by_session)()


def by_session() -> Group:
    """A new session whose group is signalled."""
    return Group(
        {"start_new_session": True},
        lambda pid: os.killpg(pid, signal.SIGTERM),
        lambda pid: os.killpg(pid, signal.SIGKILL),
    )


def by_process_group() -> Group:
    """A Windows process group: CTRL_BREAK to it, then ``taskkill`` on its tree."""
    return Group(
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP},  # type: ignore[attr-defined]
        send_break,
        kill_tree,
    )


def send_break(pid: int) -> None:
    """CTRL_BREAK to the group led by ``pid``."""
    # The event needs a console the group shares; without one, kill_tree ends it after the grace
    with contextlib.suppress(OSError):
        os.kill(pid, signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]


def kill_tree(pid: int) -> None:
    """End ``pid`` and every process it started."""
    subprocess.run(
        [*TASKKILL, str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
    )


GROUPS: dict[str, Callable[[], Group]] = {"win32": by_process_group}

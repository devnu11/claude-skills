"""The command's process group, per platform: how to start one and how to end it.

On macOS and Linux the command gets a new session, and its group is signalled
(SIGTERM, then SIGKILL). On Windows it gets a new process group, ended at once
with ``taskkill /T /F`` on its process tree. A graceful end there is the job's
``--stop-command``: a CTRL_BREAK can end the leader first, and ``taskkill /T``
then can't find the children it left.
"""

from __future__ import annotations

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
    """A Windows process group, ended by ``taskkill`` on its tree while its leader lives."""
    return Group(
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP},  # type: ignore[attr-defined]
        kill_tree,
        kill_tree,
    )


def kill_tree(pid: int) -> None:
    """End ``pid`` and every process it started."""
    subprocess.run(
        [*TASKKILL, str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
    )


GROUPS: dict[str, Callable[[], Group]] = {"win32": by_process_group}

"""Helpers for lock tests: owner records and a pid that is certainly not running."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path


def dead_pid() -> int:
    """The pid of a child that has exited and been reaped, so nothing runs as it."""
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    return child.pid


def write_owner(path: Path, pid: int, host: str | None = None, token: str = "theirs") -> None:
    """Write a lock file as another holder would."""
    record = {"pid": pid, "host": host or socket.gethostname(), "token": token}
    path.write_text(json.dumps(record))


def live_pid() -> int:
    """A pid that is running for the whole test: this process."""
    return os.getpid()

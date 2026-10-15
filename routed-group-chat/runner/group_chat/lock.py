"""An owned, exclusive lock file for one chat directory.

The lock is created with ``O_EXCL`` (atomic on POSIX and Windows) and holds a
JSON owner record: pid, host and a random token. Release removes the file only
if it still holds this holder's token, so a lock somebody deleted and another
process re-took is never removed by the first holder.

A lock left behind by a killed process is stale when its host is this host and
its pid is gone; it is then taken over. That check is POSIX only: on Windows,
``os.kill(pid, 0)`` would send a console control event, so a pid is always
treated as alive there and a stale lock must be deleted by hand.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import fits

type Owner = dict[str, Any]


class LockError(RuntimeError):
    """Another live process holds the lock."""


def is_pid_alive(pid: int, platform: str = sys.platform) -> bool:
    """Whether ``pid`` runs on this host; always ``True`` on Windows (see module doc)."""
    if platform == "win32":
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def new_owner() -> Owner:
    """This process's owner record."""
    return {"pid": os.getpid(), "host": socket.gethostname(), "token": uuid.uuid4().hex}


@dataclass(frozen=True)
class LockFile:
    """The lock at ``path``; ``alive`` is injectable for tests."""

    path: Path
    alive: Callable[[int], bool] = is_pid_alive

    @contextmanager
    def hold(self) -> Iterator[None]:
        """Hold the lock for the ``with`` body; ``LockError`` if a live process has it."""
        owner = self._claim()
        try:
            yield
        finally:
            self._release(owner["token"])

    @property
    def holder(self) -> Owner | None:
        """The current owner record, or ``None`` if absent or unreadable."""
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def is_stale(self, holder: Owner | None) -> bool:
        """True when ``holder`` is a dead process on this host."""
        if holder is None or holder.get("host") != socket.gethostname():
            return False
        pid = holder.get("pid")
        return fits(pid, int) and not self.alive(pid)

    def _claim(self) -> Owner:
        owner = new_owner()
        if self._create(owner):
            return owner
        holder = self.holder
        if self.is_stale(holder):
            self._remove_if(holder)
            if self._create(owner):
                return owner
        raise LockError(self._describe_busy(self.holder))

    def _create(self, owner: Owner) -> bool:
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w") as handle:
            json.dump(owner, handle)
        return True

    def _release(self, token: str) -> None:
        holder = self.holder
        if holder is not None and holder.get("token") == token:
            self.path.unlink(missing_ok=True)

    def _remove_if(self, holder: Owner | None) -> None:
        """Remove the lock only if it still holds ``holder``'s record."""
        if holder is not None and self.holder == holder:
            self.path.unlink(missing_ok=True)

    def _describe_busy(self, holder: Owner | None) -> str:
        who = f"pid {holder.get('pid')} on {holder.get('host')}" if holder else "another process"
        return f"{self.path} is held by {who}; delete it if that process is not running"

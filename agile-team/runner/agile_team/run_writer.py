"""The one writer of run files (s159 C6). Direct until bound to a running scheduler."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

Write = Callable[[], object]


class WrongWriter(Exception):
    """A save was submitted from a worker thread."""


class RunWriter:
    """Collects writes and runs them on the scheduler task; direct mode until ``bind``."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: int | None = None
        self._queue: list[Write] = []
        self._lock = threading.Lock()

    def bind(self, loop: asyncio.AbstractEventLoop, task: asyncio.Task) -> None:
        """Make ``task`` on ``loop`` the writer."""
        self._loop = loop
        self._thread = threading.get_ident()

    def submit(self, write: Write) -> None:
        """Queue a write (thread-safe), or run it at once when unbound."""
        if self._loop is None:
            write()
            return
        with self._lock:
            self._queue.append(write)
        self._loop.call_soon_threadsafe(lambda: None)  # wakes the loop for the next drain

    async def apply[T](self, change: Callable[[], T]) -> T:
        """Run ``change`` on the writer and return its result."""
        if self._loop is None:
            return change()
        done: asyncio.Future[T] = self._loop.create_future()
        self.submit(lambda: _settle(done, change))
        return await done

    def drain(self) -> int:
        """Run every queued write; the scheduler task only."""
        with self._lock:
            queued, self._queue = self._queue, []
        for write in queued:
            write()
        return len(queued)

    def check_owner(self) -> None:
        """Raise ``WrongWriter`` off the loop thread."""
        if self._thread is not None and threading.get_ident() != self._thread:
            raise WrongWriter("run files are written by the scheduler task only")


def _settle[T](done: asyncio.Future[T], change: Callable[[], T]) -> None:
    try:
        done.set_result(change())
    except Exception as error:
        done.set_exception(error)

"""The one writer of run files (s159 C6). Direct until bound to a running scheduler."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable

type Write = Callable[[], object]


class WrongWriter(Exception):
    """A save was submitted from a worker thread."""


class RunWriter:
    """Collects writes and runs them on the scheduler task; direct mode until ``bind``."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: int | None = None
        self._queue: list[Write] = []
        self._lock = threading.Lock()
        self.wake: asyncio.Event | None = None

    def bind(self, loop: asyncio.AbstractEventLoop, task: asyncio.Task) -> None:
        """Make ``task`` on ``loop`` the writer."""
        self._loop = loop
        self._thread = threading.get_ident()
        self.wake = asyncio.Event()

    def release(self) -> None:
        """Write what is queued, then write directly again."""
        self.drain()
        self._loop, self._thread, self.wake = None, None, None

    def submit(self, write: Write) -> None:
        """Queue a write (thread-safe), or run it at once when unbound."""
        if self._loop is None:
            write()
            return
        with self._lock:
            self._queue.append(write)
        self._loop.call_soon_threadsafe(self._wake)  # wakes the scheduler for the next drain

    async def apply[T](self, change: Callable[[], T]) -> T:
        """Run ``change`` as the writer and return its result.

        Every caller is a task on the loop thread, and nothing else runs between two awaits, so
        the change is atomic with respect to the other tasks.
        """
        self.flush()
        return change()

    def call_from_thread[T](self, change: Callable[[], T]) -> T:
        """B3: run ``change`` on the loop and wait for it; at once on the loop or when unbound."""
        if self._loop is None or threading.get_ident() == self._thread:
            return change()
        return asyncio.run_coroutine_threadsafe(self.apply(change), self._loop).result()

    def drain(
        self,
    ) -> int:
        """Run every queued write; the scheduler task only."""
        with self._lock:
            queued, self._queue = self._queue, []
        for write in queued:
            write()
        return len(queued)

    def flush(self) -> None:
        """Make queued writes visible to a reader on the loop thread."""
        if self._loop is not None and threading.get_ident() == self._thread:
            self.drain()

    def _wake(self) -> None:
        if self.wake is not None:
            self.wake.set()

    def check_owner(self) -> None:
        """Raise ``WrongWriter`` off the loop thread."""
        here = threading.get_ident()
        if self._thread is not None and here != self._thread:
            raise WrongWriter("run files are written by the scheduler task only")

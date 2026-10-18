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
        self._lent: set[int] = set()
        self.wake: asyncio.Event | None = None

    def bind(self, loop: asyncio.AbstractEventLoop, task: asyncio.Task) -> None:
        """Make ``task`` on ``loop`` the writer."""
        self._loop = loop
        self._thread = threading.get_ident()
        self.wake = asyncio.Event()

    async def run_off_loop[T](self, work: Callable[[], T]) -> T:
        """Run long ``work`` in a worker thread while the loop serves the others (C6, D2).

        The awaiting task is the work's owner: its saves are queued for the scheduler task, so
        the thread may call ``Runtime.save``. Any other worker thread is still refused.
        """

        def run_lent() -> T:
            ident = threading.get_ident()
            self._lent.add(ident)
            try:
                return work()
            finally:
                self._lent.discard(ident)

        return await asyncio.to_thread(run_lent)

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

    def drain(  # house-rules: allow query-property -- name fixed by the s159 tests
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
        if self._thread is not None and here != self._thread and here not in self._lent:
            raise WrongWriter("run files are written by the scheduler task only")

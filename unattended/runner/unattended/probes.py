"""Progress probes: what tells the supervisor that a running job is making progress."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Stamp:
    """A counter a runner bumps each time it sees progress; the ``spend`` probe reads it."""

    count: int = 0

    def tick(self) -> None:
        self.count += 1

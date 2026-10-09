"""Run activity log in ``.team/run/events.jsonl``, read by the dashboard.

Every role step, gate, quarantine, story and sprint change, model override,
Manager ruling and requirement change is one line. Relay questions and answers
stay in the outbox and inbox; the dashboard merges them in by time.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

EVENTS = "events.jsonl"


class EventKind(StrEnum):
    """What happened."""

    STEP_START = "step-start"
    STEP_END = "step-end"
    GATE = "gate"
    QUARANTINE = "quarantine"
    RULING = "ruling"
    STORY_OPENED = "story-opened"
    SPRINT_START = "sprint-start"
    OVERRIDE = "override"
    REQUIREMENT_CHANGED = "requirement-changed"
    HANDOVER = "handover"
    TEST_DISPUTE = "test-dispute"


@dataclass
class Event:
    """One line of the log; ``emit`` fills ``id`` and ``at``."""

    kind: EventKind
    role: str | None = None
    story: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    at: float = 0.0
    id: str = ""


@dataclass
class EventLog:
    """Append-only JSONL log with sequential ids (``e1``, ``e2`` …)."""

    path: Path
    _count: int | None = field(default=None, repr=False)

    def emit(self, event: Event) -> Event:
        self._count = self._next_number()
        event.id, event.at = f"e{self._count}", event.at or time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a") as fh:
            fh.write(json.dumps(asdict(event)) + "\n")
        return event

    def events(self) -> list[Event]:
        if not self.path.is_file():
            return []
        lines = self.path.read_text().splitlines()
        return [_event(json.loads(line)) for line in lines if line.strip()]

    def _next_number(self) -> int:
        if self._count is None:
            self._count = len(self.events())
        return self._count + 1


def _event(data: dict[str, Any]) -> Event:
    return Event(**{**data, "kind": EventKind(data["kind"])})

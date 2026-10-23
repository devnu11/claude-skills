"""Run activity log in ``.team/run/events.jsonl``, read by the dashboard.

Every role step, gate, quarantine, story and sprint change, model override,
Manager ruling and requirement change is one line. Relay questions and answers
stay in the outbox and inbox; the dashboard merges them in by time.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import system
from .run_writer import RunWriter

EVENTS = "events.jsonl"
INTERRUPTED = "interrupted"  # step-end status of a step cut short (s44)


class EventKind(StrEnum):
    """What happened."""

    STORY_ADMIN = "story-admin"
    SHARE = "share"
    STORY_REVERTED = "story-reverted"
    STEP_START = "step-start"
    CHECKOUT = "checkout"
    STEP_END = "step-end"
    GATE = "gate"
    GATE_FIX = "gate-fix"
    QUARANTINE = "quarantine"
    RULING = "ruling"
    STORY_OPENED = "story-opened"
    STORY_AMENDED = "story-amended"
    STORY_REFUSED = "story-refused"
    STORY_REQUEST = "story-request"
    SPRINT_START = "sprint-start"
    SPRINT_ADD = "sprint-add"
    RUNNER_REPIN = "runner-repin"
    OVERRIDE = "override"
    REQUIREMENT_CHANGED = "requirement-changed"
    HANDOVER = "handover"
    TEST_DISPUTE = "test-dispute"
    PO_SESSION = "po-session"
    PO_TURN = "po-turn"
    ESCALATION = "escalation"
    FAULT = "fault"
    BOUNDARY = "boundary"
    PRIORITY = "priority"
    TESTS_PASSED = "tests-passed"
    STEP_INTERRUPTED = "step-interrupted"
    TESTS_RUN = "tests-run"
    RUNNER_STAGE = "runner-stage"
    STOP_CHECK = "stop-check"
    STORY_BRANCH = "story-branch"
    STORY_LANDED = "story-landed"
    LANDING_ORDER = "landing-order"
    LANDING_DROPPED = "landing-dropped"
    OVERLAP_LIFTED = "overlap-lifted"
    STACK_DROPPED = "stack-dropped"
    STORY_CI = "story-ci"
    WORKTREE_PRUNED = "worktree-pruned"


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
    writer: RunWriter = field(default_factory=RunWriter, repr=False, compare=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def emit(self, event: Event) -> Event:
        """Give the event its id and time now; the writer appends its line (thread-safe)."""
        with self._lock:
            self._count = self._next_number()
            event.id, event.at = f"e{self._count}", event.at or system.now()
            line = json.dumps(asdict(event)) + "\n"
            self.writer.submit(lambda: self._append(line))
        return event

    def _append(self, line: str) -> None:
        system.make_dirs(self.path.parent)
        system.append_text(self.path, line)

    def events(self) -> list[Event]:
        self.writer.flush()
        if not system.is_file(self.path):
            return []
        lines = system.read_text(self.path).splitlines()
        return [_event(json.loads(line)) for line in lines if line.strip()]

    def _next_number(self) -> int:
        if self._count is None:
            self._count = len(self.events())
        return self._count + 1


def _event(data: dict[str, Any]) -> Event:
    return Event(**{**data, "kind": EventKind(data["kind"])})

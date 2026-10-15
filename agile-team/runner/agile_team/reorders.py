"""Reorder requests from the dashboard (s83).

Queued as files by the server, applied between steps by the router.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from . import backlog, priority, system
from .backlog import Ask, View
from .dispatch import Runtime
from .numbered_queue import Entry, NumberedQueue
from .priority import Change, Reorder, Source

REORDERS_DIR = "reorders"
REQUEST_PREFIX = "r"
REQUEST_SUFFIX = ".json"
MAX_VERSION = 64
APPLIED = "applied"
HUMAN_REASON = "moved on the dashboard ({id})"
TOLD_HEAD = "From the dashboard:"
TOLD = (
    "The human moved {story} to backlog place {position} on the dashboard ({id}). "
    "The backlog now reads: {backlog}. "
    "Keep it: a prioritise or move_story that changes it needs a reason."
)


def parse_ask(body: bytes) -> Ask | None:
    """The request in a POST body, or None when its shape is wrong (B18)."""
    try:
        data = json.loads(body)
        return _ask(data["story"], data["position"], data["version"])
    except (ValueError, TypeError, KeyError):
        return None


def _ask(story: object, position: object, version: object) -> Ask | None:
    if not (isinstance(story, str) and backlog.STORY_ID.match(story)):
        return None
    if type(position) is not int:
        return None
    if not (isinstance(version, str) and len(version) <= MAX_VERSION):
        return None
    return Ask(story, position, version)


@dataclass(frozen=True)
class Request:
    """A queued reorder: its id, the ask and when it was made."""

    id: str
    ask: Ask
    at: float = 0.0

    def to_json(self) -> str:
        """The request file's text."""
        return json.dumps({"ask": asdict(self.ask), "at": self.at})

    @classmethod
    def from_json(cls, rid: str, text: str) -> Request | None:
        """Read a request file, or None for bad JSON or shape."""
        try:
            data = json.loads(text)
            return cls(rid, Ask(**data["ask"]), float(data["at"]))
        except (ValueError, TypeError, KeyError):
            return None


@dataclass(frozen=True)
class Requests:
    """The request files under the run directory."""

    run_dir: Path

    @property
    def folder(self) -> Path:
        """Where the request files live."""
        return self.run_dir / REORDERS_DIR

    @property
    def _queue(self) -> NumberedQueue:
        return NumberedQueue(self.folder, REQUEST_PREFIX, REQUEST_SUFFIX)

    def queue(self, ask: Ask) -> Request:
        """Queue ``ask`` as the next ``r<N>.json``, written whole, never overwriting."""
        request = Request("", ask, system.now())
        entry = self._queue.publish(request.to_json())
        return replace(request, id=entry.id)

    def all(self) -> list[Request]:
        """Every readable request, in number order."""
        read = (self._read(entry) for entry in self._queue.entries())
        return [r for r in read if r]

    def pending(self, settled: dict[str, str]) -> list[Request]:
        """Requests whose ids are not in ``settled``."""
        return [r for r in self.all() if r.id not in settled]

    @staticmethod
    def _read(entry: Entry) -> Request | None:
        try:
            return Request.from_json(entry.id, system.read_text(entry.path))
        except OSError:
            return None


def told_section(lines: list[str]) -> str:
    """The PO's hand-over section for the human's dashboard moves (B15)."""
    if not lines:
        return ""
    return "\n".join([TOLD_HEAD, *(f"- {line}" for line in lines)]) + "\n\n"


@dataclass
class Desk:
    """Applies pending reorder requests through the PO's priority code (B11-B13)."""

    runtime: Runtime

    def apply(self) -> None:
        """Settle every pending request in number order."""
        requests = Requests(self.runtime.config.run_dir)
        for request in requests.pending(self.runtime.state.reorders):
            self._settle(request)

    def _settle(self, request: Request) -> None:
        refusal = self._refusal(request.ask)
        if refusal:
            self.runtime.state.reorders[request.id] = refusal
            self.runtime.save()
        else:
            self._move(request)

    def _refusal(self, ask: Ask) -> str | None:
        """The first refusal of B12, or None."""
        state = self.runtime.state
        view, stories = View.of(state), state.stories
        prio = self.runtime.priority()
        return priority.first_refusal(
            [
                lambda: backlog.stale_refusal(ask, view),
                lambda: priority.order_refusal([ask.story], stories),
                lambda: backlog.sprint_refusal(ask.story, view),
                lambda: backlog.place_refusal(ask.position, view),
                lambda: prio.move_refusal(view.placement(ask), stories),
            ]
        )

    def _move(self, request: Request) -> None:
        state, ask = self.runtime.state, request.ask
        stories, prio = state.stories, self.runtime.priority()
        placement = View.of(state).placement(ask)
        pull = prio.move_pull(placement, stories)
        order = prio.with_move(placement, stories)
        state.reorders[request.id] = APPLIED
        reason = HUMAN_REASON.format(id=request.id)
        self.runtime.reorder(Reorder(Change.MOVE, order, ask.story, reason, pull, Source.HUMAN))
        self._told(request)

    def _told(self, request: Request) -> None:
        state = self.runtime.state
        now = View.of(state).backlog
        line = TOLD.format(
            story=request.ask.story,
            position=request.ask.position,
            id=request.id,
            backlog=", ".join(now),
        )
        state.human_order = now
        state.reorders_told.append(line)
        self.runtime.save()

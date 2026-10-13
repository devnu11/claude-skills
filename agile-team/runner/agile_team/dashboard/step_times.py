"""Wall time of agent steps, paired from the event log (s96)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from ..events import EventKind
from ..salvage import Cause

Key = tuple[str | None, str | None]


@dataclass(frozen=True)
class Span:
    """One agent step: start time, and end, status and wall time once it ends."""

    role: str
    story: str | None
    at: float
    sprint: int | None = None
    ended_at: float | None = None
    status: str | None = None
    model: str | None = None
    seconds: float | None = None

    def as_dict(self) -> dict[str, Any]:
        """The snapshot's object for this step."""
        return asdict(self)


@dataclass
class Pairing:
    """One walk over the log: the steps found, the open ones by key, the running sprint."""

    found: list[Span | None] = field(default_factory=list)
    open: dict[Key, int] = field(default_factory=dict)
    sprint: int | None = None

    def start(self, event: dict) -> None:
        """ST1/ST2: open the key, dropping an earlier open start of the same key."""
        key = (event.get("role"), event.get("story"))
        if key in self.open:
            self.found[self.open[key]] = None
        self.open[key] = len(self.found)
        self.found.append(Span(key[0], key[1], event["at"], self.sprint))  # type: ignore[arg-type]

    def end(self, event: dict) -> None:
        """ST1/ST3/ST4: close the key's open step; ignore an end with none open."""
        index = self.open.pop((event.get("role"), event.get("story")), None)
        if index is not None:
            self.found[index] = closed(self.found[index], event)  # type: ignore[arg-type]

    def sprint_start(self, event: dict) -> None:
        """ST6: remember ``data.sprint``."""
        self.sprint = (event.get("data") or {}).get("sprint")


FEEDS: dict[str, Callable[[Pairing, dict], None]] = {
    EventKind.STEP_START: Pairing.start,
    EventKind.STEP_END: Pairing.end,
    EventKind.SPRINT_START: Pairing.sprint_start,
}


def spans(events: list[dict]) -> list[Span]:
    """Every agent step in start order; open ones are running (ST1 to ST6)."""
    pairing = Pairing()
    for event in events:
        feed = FEEDS.get(event.get("kind"))  # type: ignore[arg-type]
        if feed:
            feed(pairing, event)
    return [s for s in pairing.found if s is not None]


def closed(span: Span, end: dict) -> Span:
    """``span`` finished by the ``end`` event: ``ended_at``, ``status``, ``model``, ``seconds``."""
    data = end.get("data") or {}
    return replace(
        span,
        ended_at=end["at"],
        status=data.get("status"),
        model=data.get("model"),
        seconds=wall_seconds(span, end),
    )


def wall_seconds(span: Span, end: dict) -> float | None:
    """ST3, or None for a killed step (ST4)."""
    if (end.get("data") or {}).get("cause") == Cause.KILLED:
        return None
    return round(max(0, end["at"] - span.at), 1)

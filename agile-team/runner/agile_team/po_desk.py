"""The PO desk: queued passes for one PO turn at a time, and the turn snapshot (s159 C5, C9)."""

from __future__ import annotations

from dataclasses import dataclass

from . import handover
from .gates import StoryState
from .handover import Pass
from .state import RunState

STORY_MOVED = "story {id} moved since your turn began; it is now {now}. Check it and retry"


class PoDesk:
    """Passes wait here; a turn takes them merged and drops them when it is done."""

    def __init__(self) -> None:
        self._queued: list[Pass] = []
        self._taken = 0

    def queue(self, found: Pass) -> None:
        """Add a pass; it reaches the next turn that has not taken it yet."""
        self._queued.append(found)

    def take(self) -> Pass | None:
        """The merged passes queued now (or taken and not yet done), or None."""
        if not self._taken:
            self._taken = len(self._queued)
        if not self._taken:
            return None
        return handover.merge(self._queued[: self._taken])

    def done(self) -> None:
        """Drop the passes the finished turn took."""
        del self._queued[: self._taken]
        self._taken = 0

    @property
    def busy(self) -> bool:
        """True while a turn holds taken passes."""
        return bool(self._taken)


@dataclass(frozen=True)
class Mark:
    """What the PO saw of one story when its turn began."""

    step: str
    status: str
    hold: str | None
    po_hold: str | None
    rounds: int
    landed: bool

    def text(self) -> str:
        """The mark as one line for a refusal."""
        held = f", held {self.hold}" if self.hold else ""
        return f"at {self.step} ({self.status}, round {self.rounds}{held})"


def mark_of(story: StoryState) -> Mark:
    """The mark of ``story`` now."""
    po_hold = story.po_hold.kind if story.po_hold else None
    return Mark(
        story.step, str(story.status), story.hold, po_hold, story.rounds, story.landed is not None
    )


class TurnSnapshot:
    """The marks of every story at the start of a PO turn."""

    def __init__(self, marks: dict[str, Mark]) -> None:
        self.marks = marks

    @classmethod
    def take(cls, state: RunState) -> TurnSnapshot:
        """Snapshot every story in ``state``."""
        return cls({i: mark_of(s) for i, s in state.stories.items()})

    def moved(self, ids: list[str], state: RunState) -> str | None:
        """The refusal text for the first named story that moved since the snapshot."""
        for story_id in ids:
            live = state.stories.get(story_id)
            if live is not None and self.marks.get(story_id) not in (None, mark_of(live)):
                return STORY_MOVED.format(id=story_id, now=mark_of(live).text())
        return None

    def refresh(self, ids: list[str], state: RunState) -> None:
        """Accept the live marks of the named stories."""
        for story_id in ids:
            if story_id in state.stories:
                self.marks[story_id] = mark_of(state.stories[story_id])

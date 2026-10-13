"""The dashboard's Backlog (s83): the groups, the order version, apply refusals and the
human's order rule; no I/O.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from . import priority
from .gates import StoryState
from .priority import Placement, Priority
from .state import RunState

STORY_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
STALE = "the order changed since the dashboard showed it; reload"
SPRINT_STORY = "{story} is in the current sprint; only backlog stories can be moved"
BAD_PLACE = "position must be a whole number from 1 to {count} (the backlog's length)"
HUMAN_ORDER = (
    "this changes the order the human set for the backlog ({stories}); "
    "give a reason, or keep their order"
)
CANCELLED = "cancelled"
HELD = "held"


@dataclass(frozen=True)
class Ask:
    """A reorder request: the story, its backlog place and the order version seen."""

    story: str
    position: Any
    version: str


def order_version(queue: list[str], backlog: list[str]) -> str:
    """A short digest of the queue and the sprint membership (B10)."""
    digest = hashlib.sha256(json.dumps([queue, backlog]).encode()).hexdigest()
    return digest[:12]


@dataclass(frozen=True)
class View:
    """The queue and the Backlog group within it, with the order version."""

    queue: list[str]
    backlog: list[str]
    version: str

    @classmethod
    def of(cls, state: RunState) -> View:
        """The groups of ``state`` (B1)."""
        stories = state.stories
        queue = Priority(state.order, state.pulled).queue(stories.values())
        backlog = [i for i in queue if stories[i].sprint != state.sprint]
        return cls(queue, backlog, order_version(queue, backlog))

    def placement(self, ask: Ask) -> Placement:
        """The queue position of the backlog place asked for (B13)."""
        return Placement(ask.story, self.queue.index(self.backlog[ask.position - 1]) + 1)


def label(story: StoryState) -> str:
    """``cancelled``, ``held`` or empty (B3)."""
    if (story.hold or "").strip().lower().startswith(CANCELLED):
        return CANCELLED
    return HELD if priority.held(story) else ""


def stale_refusal(ask: Ask, view: View) -> str | None:
    """Refuse a request made against another order version."""
    return STALE if ask.version != view.version else None


def sprint_refusal(story: str, view: View) -> str | None:
    """Refuse a queued story that is not in the Backlog."""
    if story in view.queue and story not in view.backlog:
        return SPRINT_STORY.format(story=story)
    return None


def place_refusal(position: Any, view: View) -> str | None:
    """Refuse a place outside ``1..len(backlog)``."""
    count = len(view.backlog)
    ok = type(position) is int and 1 <= position <= count
    return None if ok else BAD_PLACE.format(count=count)


@dataclass(frozen=True)
class HumanCheck:
    """The human's guarded stories and the queue before and after a PO change."""

    guarded: list[str]
    before: list[str]
    after: list[str]


def guarded(human_order: list[str], view: View) -> list[str]:
    """The human's ordered stories that are still in the Backlog (B17)."""
    return [i for i in human_order if i in view.backlog]


def human_refusal(check: HumanCheck, reason: str) -> str | None:
    """Refuse a change to the human's order that gives no reason (B17)."""
    was = [i for i in check.before if i in check.guarded]
    now = [i for i in check.after if i in check.guarded]
    if was == now or reason.strip():
        return None
    moved = [i for n, i in enumerate(was) if now.index(i) != n]
    return HUMAN_ORDER.format(stories=", ".join(moved))

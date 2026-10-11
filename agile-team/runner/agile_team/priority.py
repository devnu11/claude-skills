"""Story priority (s40): the PO's explicit order and the one rule that ranks stories."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .gates import StoryState, StoryStatus

NO_STORIES = "no stories listed; pass the story ids in the order to work on them"
UNKNOWN = "unknown stories: {ids}; open them with open_story first"
DONE = "done stories have no place in the order: {ids}"
BAD_POSITION = "position must be a whole number from 1 to {count}"


class Change(StrEnum):
    """What kind of reorder happened."""

    SET = "set"
    MOVE = "move"
    SPRINT = "sprint"


@dataclass(frozen=True)
class Placement:
    """A story and the position the PO asks for (validated by ``move_refusal``)."""

    story: str
    position: Any


@dataclass(frozen=True)
class Reorder:
    """A change to the order: its kind, the new queue, the moved story and why."""

    change: Change
    order: list[str]
    story: str | None = None
    reason: str = ""


def natural(sid: str) -> tuple[Any, ...]:
    """Sort key for an id: digit runs compare as numbers (s9 < s10)."""
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"(\d+)", sid))


def order_refusal(ids: list[str], stories: dict[str, StoryState]) -> str | None:
    """Why these ids cannot be ordered, or None."""
    if not ids:
        return NO_STORIES
    unknown = [i for i in ids if i not in stories]
    if unknown:
        return UNKNOWN.format(ids=", ".join(unknown))
    done = [i for i in ids if stories[i].status is StoryStatus.DONE]
    return DONE.format(ids=", ".join(done)) if done else None


def moves(before: list[str], after: list[str]) -> list[dict[str, Any]]:
    """Each story in ``after`` whose 1-based position changed."""
    was = {sid: n for n, sid in enumerate(before, 1)}
    return [
        {"story": sid, "from": was.get(sid), "to": n}
        for n, sid in enumerate(after, 1)
        if was.get(sid) != n
    ]


@dataclass(frozen=True)
class Priority:
    """The PO's order over a pipeline whose first step is ``first``."""

    order: list[str]
    first: str

    def in_progress(self, story: StoryState) -> bool:
        """Past the first step, or a step has already run on it."""
        return story.step != self.first or story.previous is not None

    def key(self, story: StoryState) -> tuple[Any, ...]:
        """The one ranking rule (P2)."""
        done = story.status is StoryStatus.DONE
        listed = self.order.index(story.id) if story.id in self.order else len(self.order)
        return (done, listed, not self.in_progress(story), natural(story.id))

    def ranked(self, stories: Iterable[StoryState]) -> list[StoryState]:
        """Every story, best first."""
        return sorted(stories, key=self.key)

    def queue(self, stories: Iterable[StoryState]) -> list[str]:
        """Ids of the unfinished stories in ranking order."""
        return [s.id for s in self.ranked(stories) if s.status is not StoryStatus.DONE]

    def with_first(self, ids: list[str], stories: Iterable[StoryState]) -> list[str]:
        """The queue with ``ids`` first, in the order given."""
        queue = self.queue(stories)
        return [i for i in ids if i in queue] + [i for i in queue if i not in ids]

    def with_move(self, placement: Placement, stories: Iterable[StoryState]) -> list[str]:
        """The queue with one story put back at its position."""
        rest = [i for i in self.queue(stories) if i != placement.story]
        rest.insert(placement.position - 1, placement.story)
        return rest

    def move_refusal(self, placement: Placement, stories: dict[str, StoryState]) -> str | None:
        """Why this move is refused, or None."""
        refusal = order_refusal([placement.story], stories)
        if refusal:
            return refusal
        count = len(self.queue(stories.values()))
        p = placement.position
        ok = type(p) is int and 1 <= p <= count
        return None if ok else BAD_POSITION.format(count=count)

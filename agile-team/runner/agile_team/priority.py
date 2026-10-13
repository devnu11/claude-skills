"""Story priority (s40, s51): the PO's order within the groups started, held and not started."""

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
PULL_NEEDS_REASON = (
    "pulling {ids} ahead of started stories needs a reason; "
    "give one, or place them after the started stories"
)
RANKED_ELSEWHERE = (
    "{story} ranks #{landed}, not #{position}: stories in progress come first, "
    "then held started ones, then the rest; its place in the order is kept"
)
HELD_STATUSES = frozenset({StoryStatus.BLOCKED, StoryStatus.NEEDS_MANAGER})


class Change(StrEnum):
    """What kind of reorder happened."""

    SET = "set"
    MOVE = "move"
    SPRINT = "sprint"


class Tier(StrEnum):
    """The group a story ranks in."""

    IN_PROGRESS = "in progress"
    HELD = "held"
    NOT_STARTED = "not started"


RANK = {tier: n for n, tier in enumerate(Tier)}


@dataclass(frozen=True)
class Pull:
    """The stories a change judges, and those it pulls ahead of started ones."""

    judged: tuple[str, ...] = ()
    ahead: tuple[str, ...] = ()


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
    pull: Pull = Pull()


def started(story: StoryState) -> bool:
    """Has commits in the tree: the runner recorded its first commit (G1)."""
    return story.commit is not None


def held(story: StoryState) -> bool:
    """A hold, a block or a needs-manager status."""
    return story.hold is not None or story.status in HELD_STATUSES


def pulls(listed: list[str], stories: dict[str, StoryState]) -> list[str]:
    """Not-started ids in ``listed`` that come before its last started id (G6)."""
    last = max((n for n, i in enumerate(listed) if started(stories[i])), default=0)
    return [i for i in listed[:last] if not started(stories[i])]


def set_pull(ids: list[str], stories: dict[str, StoryState]) -> Pull:
    """G7: judge ``ids`` only when they name a started story."""
    if not any(started(stories[i]) for i in ids):
        return Pull()
    return Pull(tuple(ids), tuple(pulls(ids, stories)))


def pull_refusal(pull: Pull, reason: str) -> str | None:
    """G9: why a pull without a reason is refused, or None."""
    if pull.ahead and not reason.strip():
        return PULL_NEEDS_REASON.format(ids=", ".join(pull.ahead))
    return None


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
    """The PO's order and pulls over the stories."""

    order: list[str]
    pulled: list[str]

    def tier(self, story: StoryState) -> Tier:
        """The group the story ranks in (G2)."""
        if not started(story) and story.id not in self.pulled:
            return Tier.NOT_STARTED
        return Tier.HELD if held(story) else Tier.IN_PROGRESS

    def key(self, story: StoryState) -> tuple[Any, ...]:
        """The one ranking rule (G3)."""
        done = story.status is StoryStatus.DONE
        listed = self.order.index(story.id) if story.id in self.order else len(self.order)
        return (done, RANK[self.tier(story)], listed, natural(story.id))

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

    def move_pull(self, placement: Placement, stories: dict[str, StoryState]) -> Pull:
        """G8: the moved story is pulled when it lands before a started one."""
        moved = self.with_move(placement, stories.values())
        ahead = (placement.story,) if placement.story in pulls(moved, stories) else ()
        return Pull((placement.story,), ahead)

    def repulled(self, pull: Pull, stories: dict[str, StoryState]) -> list[str]:
        """G13: the pulled ids after a change."""
        kept = [i for i in self.pulled if i not in pull.judged]
        ids = dict.fromkeys(kept + list(pull.ahead))
        return [i for i in ids if i in stories and self._pullable(stories[i])]

    @staticmethod
    def _pullable(story: StoryState) -> bool:
        return story.status is not StoryStatus.DONE and not started(story)

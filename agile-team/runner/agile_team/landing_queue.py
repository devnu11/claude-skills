"""The landing queue (s163 Q1 to Q8): who lands next, in the PO's order, then smallest first."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import sprint_end
from .events import Event, EventKind

if TYPE_CHECKING:
    from .dispatch import Runtime
    from .gates import StoryState

NO_STORIES = "list the ids of the stories waiting to land"
NOW_LANDING = "{id} is landing now; order only the stories waiting behind it"
NOT_WAITING = "{id} is not waiting to land; waiting: {ids}"
ORDER_NEEDS_REASON = "this order departs from smallest first ({smallest}); give a reason"
LINES = re.compile(r"(\d+) (?:insertion|deletion)")


@dataclass(frozen=True)
class Candidate:
    """A story waiting to land and its size."""

    story: str
    size: int


@dataclass(frozen=True)
class Placement:
    """An order_landings call: the ids in the PO's order and its reason."""

    stories: list[str]
    reason: str


def count_lines(shortstat: str) -> int:
    """The lines added plus deleted in a ``git diff --shortstat`` line; 0 for none."""
    return sum(int(n) for n in LINES.findall(shortstat))


def rank_smallest_first(candidates: Sequence[Candidate]) -> list[str]:
    """Q2: fewest lines first; ties by story number (``s9`` before ``s10``)."""
    ranked = sorted(candidates, key=lambda c: (c.size, len(c.story), c.story))
    return [c.story for c in ranked]


def arrange(  # house-rules: allow verb-name -- name fixed by the s163 design
    candidates: Sequence[Candidate], placed: Sequence[str]
) -> list[str]:
    """Q2: the placed ids that still wait, in the PO's order, then the rest smallest first."""
    waiting = {c.story for c in candidates}
    first = [i for i in dict.fromkeys(placed) if i in waiting]
    rest = [c for c in candidates if c.story not in first]
    return [*first, *rank_smallest_first(rest)]


class LandingQueue:
    """Which waiting story or landing revert lands next (Q1)."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self.sizes: dict[tuple[str, ...], int] = {}
        self.reverting = ""

    def waiting(  # house-rules: allow query-property, verb-name -- name fixed by the s163 design
        self,
    ) -> list[Candidate]:
        """Stories waiting to land and landing reverts waiting, each with its size."""
        ids = [*self._ready_ids, *self._queued_ids]
        return [Candidate(i, self.measure(i)) for i in ids if i != self.runtime.state.landing]

    @property
    def _ready_ids(self) -> list[str]:
        state = self.runtime.state
        return [
            s.id
            for s in state.stories.values()
            if s.step == "land" and s.rebase is None and sprint_end.can_move(s, state)
        ]

    @property
    def _queued_ids(self) -> list[str]:
        return list(dict.fromkeys(call.story_id for call in self.runtime.revert_queue))

    def order(  # house-rules: allow query-property, verb-name -- name fixed by the s163 design
        self,
    ) -> list[str]:
        """Q2: the full order of the stories waiting."""
        return arrange(self.waiting(), self.runtime.state.landing_order)

    def next_up(  # house-rules: allow query-property, verb-name -- name fixed by the s163 design
        self,
    ) -> str | None:
        """Q1, Q5: the one now landing, else the first waiting, else ``None``."""
        state = self.runtime.state
        if state.landing and not self._is_live(state.landing):
            state.landing = ""
        if state.landing:
            return state.landing
        found = self.order()
        return found[0] if found else None

    def _is_live(self, story_id: str) -> bool:
        story = self.runtime.state.stories.get(story_id)
        queued = any(call.story_id == story_id for call in self.runtime.revert_queue)
        running = story_id == self.reverting
        return queued or running or (story is not None and story.step == "land")

    def begin(self, story_id: str) -> None:
        """The story is landing now."""
        self.runtime.state.landing = story_id
        self.runtime.save()

    def begin_revert(self, story_id: str) -> None:
        """The story's landing revert is running: it holds the landing slot (Q1, Q5)."""
        self.reverting = story_id
        self.begin(story_id)

    def finish(self, story_id: str) -> None:
        """Q4: the story leaves the queue and loses its place and its cached size."""
        state = self.runtime.state
        if self.reverting == story_id:
            self.reverting = ""
        if state.landing == story_id:
            state.landing = ""
        state.landing_order = [i for i in state.landing_order if i != story_id]
        self.sizes = {k: v for k, v in self.sizes.items() if k[0] != story_id}
        self.runtime.save()

    def place(  # house-rules: allow verb-name -- name fixed by the s163 design
        self, placement: Placement
    ) -> dict[str, Any]:
        """Q3, Q6: set the PO's order; a refusal or the result."""
        stories = list(dict.fromkeys(placement.stories)) if placement.stories else []
        refusal = self._find_refusal(stories)
        if refusal is not None:
            return self._make_refused(refusal)
        waiting = self.waiting()
        order, smallest = arrange(waiting, stories), rank_smallest_first(waiting)
        if order != smallest and not placement.reason.strip():
            return self._make_refused(ORDER_NEEDS_REASON.format(smallest=", ".join(smallest)))
        return self._accept(Placement(stories, placement.reason), order, smallest)

    def _make_refused(self, reason: str) -> dict[str, Any]:
        return {"status": "refused", "reason": reason}

    def _find_refusal(self, stories: list[str]) -> str | None:
        state = self.runtime.state
        if not stories:
            return NO_STORIES
        if state.landing in stories:
            return NOW_LANDING.format(id=state.landing)
        ids = [c.story for c in self.waiting()]
        missing = next((i for i in stories if i not in ids), None)
        return None if missing is None else NOT_WAITING.format(id=missing, ids=", ".join(ids))

    def _accept(
        self, placement: Placement, order: list[str], smallest: list[str]
    ) -> dict[str, Any]:
        rt = self.runtime
        rt.state.landing_order = placement.stories
        sizes = {c.story: c.size for c in self.waiting()}
        data = {"order": order, "placed": placement.stories, "smallest": smallest}
        data |= {"sizes": sizes, "reason": placement.reason}
        rt.events.emit(Event(EventKind.LANDING_ORDER, "po", None, data))
        rt.save()
        return {"status": "ordered", "order": order, "sizes": sizes}

    def measure(self, candidate_id: str) -> int:
        """Q7: the lines a landing changes, cached per branch and base (or per merge)."""
        story = self.runtime.state.stories.get(candidate_id)
        if story is None:
            return 0
        key, span = self._get_span(story)
        if key not in self.sizes:
            out = self.runtime.git.attempt("diff", "--shortstat", *span)
            self.sizes[key] = count_lines(out[1]) if out[0] == 0 else 0
        return self.sizes[key]

    def _get_span(self, story: StoryState) -> tuple[tuple[str, ...], list[str]]:
        queued = any(call.story_id == story.id for call in self.runtime.revert_queue)
        if queued and story.landed is not None:
            merge = story.landed.merge
            return (story.id, merge), [f"{merge}^1", merge]
        return (story.id, story.branch, story.base_sha), [f"{story.base_sha}..{story.branch}"]

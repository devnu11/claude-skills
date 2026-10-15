"""Adding open stories to the running sprint (s122; moved out of ``po_tools`` in s135).

The PO's ``add_to_sprint`` tool and the runner's story intake share these checks and this
change, so both place a story in the sprint the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import dependencies, priority
from .boundary import Boundary, held_text
from .events import Event, EventKind
from .priority import After, Change, Pull, Reorder, Source

if TYPE_CHECKING:
    from .dispatch import Runtime

SPRINT_REFUSAL_BOUNDARY = (
    "sprint {sprint} {edge} boundary is still pending ({stage}{held}); finish it first"
)
NO_OPEN_SPRINT = (
    "no sprint is open to add to (none started, or sprint {sprint} has ended); use start_sprint"
)
ALREADY_IN_SPRINT = "already in sprint {sprint}: {ids}"
ADD_NEEDS_REASON = "add_to_sprint needs a reason: say why these stories join sprint {sprint}"


@dataclass(frozen=True)
class Addition:
    """The stories to add, why, who asks, and (intake only, one id) the story to follow."""

    ids: list[str]
    reason: str
    source: Source = Source.PO
    after: str = ""


def boundary_text(pending: Boundary) -> str:
    """The refusal text for a pending boundary."""
    return SPRINT_REFUSAL_BOUNDARY.format(
        sprint=pending.sprint, edge=pending.edge, stage=pending.stage, held=held_text(pending)
    )


@dataclass
class SprintAdd:
    """Checks and makes an addition to the running sprint."""

    runtime: Runtime

    def boundary_refusal(self) -> str | None:
        """Why a pending boundary stops sprint changes, or None."""
        pending = self.runtime.state.boundary
        return boundary_text(pending) if pending else None

    def refusal(self, add: Addition) -> str | None:
        """Why ``add`` is refused, or None; the first failing check wins."""
        stories = self.runtime.state.stories
        return priority.first_refusal(
            [
                self.boundary_refusal,
                self._open_sprint_refusal,
                lambda: priority.order_refusal(add.ids, stories),
                lambda: self._in_sprint_refusal(add.ids),
                lambda: self._unmet_refusal(add.ids),
                lambda: self._reason_refusal(add.reason),
            ]
        )

    def apply(self, add: Addition) -> list[str]:
        """Add the stories, log ``sprint-add`` and reorder; the new queue."""
        rt = self.runtime
        rt.state.add_to_sprint(add.ids)
        rt.save()
        data: dict[str, Any] = {"sprint": rt.state.sprint, "stories": add.ids, "reason": add.reason}
        rt.events.emit(Event(EventKind.SPRINT_ADD, priority.SOURCE_ROLES[add.source], None, data))
        change = Reorder(Change.SPRINT, self._order(add), None, add.reason, Pull(), add.source)
        return rt.reorder(change)

    def _order(self, add: Addition) -> list[str]:
        stories = self.runtime.state.stories.values()
        plan = self.runtime.priority()
        if add.after:
            return plan.with_after(After(add.ids[0], add.after), stories)
        return plan.with_first(add.ids, stories)

    def _reason_refusal(self, reason: str) -> str | None:
        if reason.strip():
            return None
        return ADD_NEEDS_REASON.format(sprint=self.runtime.state.sprint)

    def _open_sprint_refusal(self) -> str | None:
        state = self.runtime.state
        if state.sprint_open():
            return None
        return NO_OPEN_SPRINT.format(sprint=state.sprint)

    def _in_sprint_refusal(self, ids: list[str]) -> str | None:
        state = self.runtime.state
        inside = set(state.sprint_ids())
        already = [i for i in ids if i in inside]
        if not already:
            return None
        return ALREADY_IN_SPRINT.format(sprint=state.sprint, ids=", ".join(already))

    def _unmet_refusal(self, ids: list[str]) -> str | None:
        state = self.runtime.state
        members = frozenset([*state.sprint_ids(), *ids])
        return dependencies.unmet_refusal(ids, dependencies.Scope(state.stories, members))

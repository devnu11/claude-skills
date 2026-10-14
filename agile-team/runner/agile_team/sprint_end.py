"""When a sprint may end and what to offer while it is stuck (s124 E3, K1, K3). Pure."""

from __future__ import annotations

from . import dependencies
from .gates import StoryState, StoryStatus
from .state import RunState

END_REFUSED = (
    "sprint {sprint} can't end: {stories} unfinished. Finish them, revert_story(story, reason), "
    "or ask the human to cancel them (request_cancel); add_to_sprint ready backlog stories "
    "to keep working meanwhile"
)
READY_HEAD = "Ready in the backlog (dependencies done, not held):"
READY_MORE = "- and {count} more"
READY_ADVICE = (
    "Add the next ready stories with add_to_sprint(stories, reason) so the team keeps working. "
    "Don't end the sprint or wait: it ends only when its stories are done, cancelled or reverted."
)
READY_SHOWN = 5


def end_refusal(state: RunState) -> str | None:
    """E3: END_REFUSED naming each unfinished sprint story and its step, or None."""
    unfinished = state.unfinished_in_sprint()
    if not unfinished:
        return None
    named = ", ".join(f"{i} at {state.stories[i].step}" for i in unfinished)
    return END_REFUSED.format(sprint=state.sprint, stories=named)


def _ready(story: StoryState, stories: dict[str, StoryState]) -> bool:
    free = story.hold is None and story.po_hold is None
    backlog = story.sprint is None and story.status is StoryStatus.ACTIVE
    return backlog and free and not dependencies.waiting_on(story, stories)


def ready_backlog(stories: dict[str, StoryState], queue: list[str]) -> list[str]:
    """K1: ready backlog ids in queue order."""
    return [i for i in queue if _ready(stories[i], stories)]


def ready_lines(stories: dict[str, StoryState], ready: list[str]) -> list[str]:
    """K3: READY_HEAD, up to READY_SHOWN story lines, READY_MORE, READY_ADVICE."""
    shown = [f"- {i}: {stories[i].title}" for i in ready[:READY_SHOWN]]
    more = len(ready) - READY_SHOWN
    tail = [READY_MORE.format(count=more)] if more > 0 else []
    return [READY_HEAD, *shown, *tail, READY_ADVICE]

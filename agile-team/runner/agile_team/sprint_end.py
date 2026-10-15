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
UNTIL_BLOCKER = "until-blocker"
NEXT_SPRINT_LEAD = (
    "Cadence until-blocker: start the next sprint now with start_sprint(goal, stories). "
    "The run ends only when nothing in the backlog can move."
)
NEXT_SPRINT_ADVICE = (
    "Don't end your turn without starting a sprint, and don't notify done or blocked while "
    "stories are ready. A PR waiting for review or merge does not hold the next sprint."
)
KEEP_GOING_REFUSED = (
    "cadence until-blocker: the backlog has ready stories ({ids}); start_sprint them, or "
    "add_to_sprint while a sprint is open. The run ends only when nothing in the backlog can move"
)
KEEP_GOING_CAP = 3
KEEP_GOING_STUCK = (
    "The PO did not start a sprint or add ready stories after {count} hand-overs; ready: {ids}. "
    "Tell the PO what to do with `agile-team tell`, then `start --resume`."
)


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


def _ready_list(stories: dict[str, StoryState], ready: list[str]) -> list[str]:
    """READY_HEAD, up to READY_SHOWN story lines, READY_MORE."""
    shown = [f"- {i}: {stories[i].title}" for i in ready[:READY_SHOWN]]
    more = len(ready) - READY_SHOWN
    tail = [READY_MORE.format(count=more)] if more > 0 else []
    return [READY_HEAD, *shown, *tail]


def ready_lines(stories: dict[str, StoryState], ready: list[str]) -> list[str]:
    """K3: the ready list, then READY_ADVICE."""
    return [*_ready_list(stories, ready), READY_ADVICE]


def next_sprint_lines(stories: dict[str, StoryState], ready: list[str]) -> list[str]:
    """K2: the lead, the ready list and the advice for the next-sprint hand-over."""
    return [NEXT_SPRINT_LEAD, *_ready_list(stories, ready), NEXT_SPRINT_ADVICE]


def ids_text(ready: list[str]) -> str:
    """Up to READY_SHOWN ids joined by ``, ``, then ``, …`` when there are more."""
    text = ", ".join(ready[:READY_SHOWN])
    return text + ", …" if len(ready) > READY_SHOWN else text


def keep_going_refusal(state: RunState) -> str | None:
    """K5: KEEP_GOING_REFUSED under until-blocker while backlog stories are ready."""
    if state.cadence != UNTIL_BLOCKER:
        return None
    ready = ready_backlog(state.stories, list(state.stories))
    return KEEP_GOING_REFUSED.format(ids=ids_text(ready)) if ready else None

"""When a sprint may end, what is ready next, and the stuck Sprint Backlog (s156). Pure."""

from __future__ import annotations

from . import dependencies
from .gates import StoryState, StoryStatus
from .state import RunState

END_REFUSED = (
    "sprint {sprint} can't end: {stories} unfinished. Finish them, revert_story(story, reason), "
    "or ask the human to cancel them (request_cancel)"
)
READY_HEAD = "Ready in the Product Backlog (dependencies done, not held):"
READY_MORE = "- and {count} more"
READY_SHOWN = 5
UNTIL_BLOCKER = "until-blocker"
NEXT_SPRINT_LEAD = (
    "Cadence until-blocker: start the next sprint now with start_sprint(goal, stories). "
    "A sprint end doesn't end the run while the Product Backlog has ready stories."
)
NEXT_SPRINT_ADVICE = (
    "Don't end your turn without being ready to start a sprint while Product Backlog "
    "stories are ready. A PR waiting for review or merge does not hold the "
    "next sprint. A run is ended on "
    "purpose by the liaison resuming it with `--cadence sprint`. If the human's instructions "
    "say to stop after this sprint, notify done quoting them."
)
KEEP_GOING_REFUSED = (
    "cadence until-blocker: Sprint Backlog stories can still move ({ids}); end your turn and "
    "the runner works on them. Notify done or blocked only when nothing in the Sprint Backlog "
    "can move"
)
KEEP_GOING_CAP = 3
KEEP_GOING_STUCK = (
    "The PO did not start a sprint after {count} next-sprint hand-overs; ready in the Product "
    "Backlog: {ids}. Tell the PO what to do with `agile-team tell`, then `start --resume`."
)
SPRINT_STUCK_CAP = 3
SPRINT_STUCK_LEAD = "Nothing in the Sprint Backlog of sprint {sprint} can move. Each story and why:"
SPRINT_STUCK_ADVICE = (
    "Stuck hand-over {count} of {cap}. Act on these stories: continue_story or release_story "
    "once the cause is fixed, run_role with your own brief, pass_tests, revert_story, "
    "request_cancel, or request_story for a bug the team can't fix itself; ask_user when only "
    "the human can unblock one. Don't refill the sprint to keep the team busy. After {cap} "
    "stuck hand-overs with none of these, the runner sets the run blocked and tells the human."
)
SPRINT_STUCK_BLOCKED = (
    "Sprint {sprint}: the Sprint Backlog is stuck after {count} hand-overs with no PO action "
    "on its stories: {reasons}. Tell the PO what to do with `agile-team tell`, then "
    "`start --resume`."
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
    in_product_backlog = story.sprint is None and story.status is StoryStatus.ACTIVE
    return in_product_backlog and free and not dependencies.waiting_on(story, stories)


def select_ready_product_backlog(stories: dict[str, StoryState], queue: list[str]) -> list[str]:
    """K1: ready Product Backlog ids in queue order."""
    return [i for i in queue if _ready(stories[i], stories)]


def _ready_list(stories: dict[str, StoryState], ready: list[str]) -> list[str]:
    """READY_HEAD, up to READY_SHOWN story lines, READY_MORE."""
    shown = [f"- {i}: {stories[i].title}" for i in ready[:READY_SHOWN]]
    more = len(ready) - READY_SHOWN
    tail = [READY_MORE.format(count=more)] if more > 0 else []
    return [READY_HEAD, *shown, *tail]


def next_sprint_lines(stories: dict[str, StoryState], ready: list[str]) -> list[str]:
    """K2: the lead, the ready list and the advice for the next-sprint hand-over."""
    return [NEXT_SPRINT_LEAD, *_ready_list(stories, ready), NEXT_SPRINT_ADVICE]


def ids_text(ready: list[str]) -> str:
    """Up to READY_SHOWN ids joined by ``, ``, then ``, …`` when there are more."""
    text = ", ".join(ready[:READY_SHOWN])
    return text + ", …" if len(ready) > READY_SHOWN else text


def can_move(story: StoryState, state: RunState) -> bool:
    """S8: a Sprint Backlog story the router could step now, open questions aside."""
    in_sprint = story.sprint == state.sprint and story.status is StoryStatus.ACTIVE
    free = story.hold is None and story.po_hold is None and state.boundary is None
    return in_sprint and free and not dependencies.waiting_on(story, state.stories)


def list_movable_sprint_backlog(state: RunState, blocked: set[str]) -> list[str]:
    """S7: ids in the current sprint that can_move and aren't waiting on a question."""
    ids = state.sprint_ids()
    return [i for i in ids if can_move(state.stories[i], state) and i not in blocked]


def keep_going_refusal(state: RunState, blocked: set[str]) -> str | None:
    """S7: KEEP_GOING_REFUSED under until-blocker while a Sprint Backlog story can move."""
    if state.cadence != UNTIL_BLOCKER:
        return None
    movable = list_movable_sprint_backlog(state, blocked)
    return KEEP_GOING_REFUSED.format(ids=ids_text(movable)) if movable else None


def list_stuck(state: RunState, reasons: list[str]) -> list[str]:
    """S3: SPRINT_STUCK_LEAD, the story lines, SPRINT_STUCK_ADVICE with state.stuck_asks."""
    lead = SPRINT_STUCK_LEAD.format(sprint=state.sprint)
    advice = SPRINT_STUCK_ADVICE.format(count=state.stuck_asks, cap=SPRINT_STUCK_CAP)
    return [lead, *reasons, advice]


def format_stuck_blocked_text(state: RunState, reasons: list[str]) -> str:
    """S4: SPRINT_STUCK_BLOCKED for state.sprint and state.stuck_asks."""
    return SPRINT_STUCK_BLOCKED.format(
        sprint=state.sprint, count=state.stuck_asks, reasons="; ".join(reasons)
    )

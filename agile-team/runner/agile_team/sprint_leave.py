"""The PO's ``remove_from_sprint`` (s189): pure rules first, ``SprintLeave`` does the I/O.

A story with no commits and no landing leaves the running sprint for the Product Backlog.
It keeps its step and its place in the order; its holds are cleared and recorded.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from . import priority, revert_log, story_admin, story_spec, system
from .dispatch import Runtime, refused
from .events import Event, EventKind
from .gates import FINISHED, StoryState
from .holds import HoldKind
from .relay import Note
from .revert_log import FileSection
from .reverts import Reverter
from .sprint_add import SprintAdd
from .state import RunState
from .workspaces import Workspaces

NOT_IN_SPRINT = "story {story} is not in the running sprint {sprint}; nothing to remove"
OPEN_LANDING = (
    "story {story} is landing; wait for land to end, then use revert_story(story, reason)"
)
LANDED = "story {story} has landed; use revert_story(story, reason) to take its work out"
HAS_COMMITS = "story {story} has commits; use revert_story(story, reason) to take its work out"
STEP_RUNNING = "story {story}'s {step} step is running; call again when it ends"
DEPENDED_ON_IN_SPRINT = (
    "unfinished sprint stories depend on {story}: {ids}; take them out first, or keep {story}"
)
VERB = "remove from the sprint"
HEADING = "## Left the sprint"
FILE_LINE = "- {date}, sprint {sprint}: {reason} Cleared hold: {cleared}."
NOTICE = (
    'Story {story} ("{title}") left sprint {sprint} for the Product Backlog: {reason} '
    "Cleared hold: {cleared}."
)
RECORD_SUBJECT = "chore({story}): record the move to the Product Backlog"
NO_HOLD = "none"
TOOL = "remove_from_sprint"


@dataclass(frozen=True)
class Leave:
    """One call: the story and the reason."""

    story_id: str
    reason: str


@dataclass(frozen=True)
class Cleared:
    """The holds the move clears (L2)."""

    hold: str | None
    po_hold: str | None

    @property
    def text(self) -> str:
        """The holds in words, or NO_HOLD."""
        parts = []
        if self.hold is not None:
            parts.append(f"runner hold: {self.hold}")
        if self.po_hold is not None:
            parts.append(f"PO hold: {self.po_hold}")
        return "; ".join(parts) or NO_HOLD


def read_cleared(story: StoryState) -> Cleared:
    """The runner hold and the plain PO hold the story has now."""
    asked = story.po_hold
    plain = asked.reason if asked and asked.kind is HoldKind.HOLD else None
    return Cleared(story.hold, plain)


def list_sprint_dependents(state: RunState, story_id: str) -> list[str]:
    """Ids of unfinished sprint stories that depend on ``story_id``, in state order."""
    return [i for i in state.unfinished_in_sprint() if story_id in state.stories[i].depends_on]


def release_worktree(runtime: Runtime, story: StoryState) -> None:
    """E1: a story that leaves the sprint gives up its worktree and keeps its branch."""
    if not story.worktree_head:
        return
    Workspaces(runtime.git, runtime.config).remove(story.id)
    story.worktree_head = ""
    data = {"action": "removed", "branch": story.branch, "base_sha": story.base_sha}
    data["replays"] = story.replays
    runtime.events.emit(Event(EventKind.STORY_BRANCH, story_admin.PO_ROLE, story.id, data))


def _today() -> str:
    return datetime.fromtimestamp(system.now(), UTC).strftime("%Y-%m-%d")


@dataclass
class SprintLeave:
    """Runs remove_from_sprint."""

    runtime: Runtime

    async def run(self, args: dict[str, Any]) -> dict[str, Any]:
        """Settle answered questions, check, then move the story."""
        rt = self.runtime
        story_admin.Clerk(rt).settle()
        Reverter(rt).settle()
        leave = Leave(str(args.get("story", "")), str(args.get("reason") or ""))
        if why := self.find_refusal(leave):
            return refused(why)
        return await self.apply(leave)

    def find_refusal(self, leave: Leave) -> str | None:
        """Why the call is refused, or None; the first failing check wins."""
        stories = self.runtime.state.stories
        if leave.story_id not in stories:
            return story_admin.UNKNOWN.format(story=leave.story_id)
        story = stories[leave.story_id]
        return priority.first_refusal(
            [
                SprintAdd(self.runtime).boundary_refusal,
                lambda: None if leave.reason.strip() else story_admin.NO_REASON,
                lambda: self._finished_refusal(story),
                lambda: self._sprint_refusal(story),
                lambda: story_admin.asked_text(story),
                lambda: self._find_work_refusal(story),
                lambda: self._running_refusal(story),
                lambda: self._dependents_refusal(story),
            ]
        )

    def _finished_refusal(self, story: StoryState) -> str | None:
        if story.status not in FINISHED:
            return None
        return story_admin.FINISHED_TEXT.format(story=story.id, status=story.status, verb=VERB)

    def _sprint_refusal(self, story: StoryState) -> str | None:
        state = self.runtime.state
        if state.sprint_open() and story.sprint == state.sprint:
            return None
        return NOT_IN_SPRINT.format(story=story.id, sprint=state.sprint)

    def _find_work_refusal(self, story: StoryState) -> str | None:
        rt = self.runtime
        queued = any(call.story_id == story.id for call in rt.revert_queue)
        if story.step == "land" or rt.state.landing == story.id or queued:
            return OPEN_LANDING.format(story=story.id)
        if story.landed is not None:
            return LANDED.format(story=story.id)
        if story.commit is not None or story.code_commits:
            return HAS_COMMITS.format(story=story.id)
        return None

    def _running_refusal(self, story: StoryState) -> str | None:
        if story.id not in self.runtime.flags.running:
            return None
        return STEP_RUNNING.format(story=story.id, step=story.step)

    def _dependents_refusal(self, story: StoryState) -> str | None:
        ids = list_sprint_dependents(self.runtime.state, story.id)
        if not ids:
            return None
        return DEPENDED_ON_IN_SPRINT.format(story=story.id, ids=", ".join(ids))

    async def apply(self, leave: Leave) -> dict[str, Any]:
        """L1 to L6: move the story, record it, tell the human."""
        rt = self.runtime
        story, sprint = rt.state.stories[leave.story_id], rt.state.sprint
        before, cleared = story_admin.facts(story), read_cleared(story)
        story.sprint, story.hold, story.overlap_with, story.po_hold = None, None, [], None
        release_worktree(rt, story)
        rt.save()
        line = self._line(leave, sprint, cleared)
        record = await self._record(story, line)
        data = self._data(leave, sprint, cleared) | {"record": record}
        data |= {"before": before, "after": story_admin.facts(story)}
        rt.events.emit(Event(EventKind.STORY_ADMIN, story_admin.PO_ROLE, story.id, data))
        rt.relay.post(Note("update", self._notice(story, leave, sprint, cleared), [story.id]))
        return {
            "status": "removed",
            "story": story.id,
            "step": story.step,
            "sprint": sprint,
            "cleared": asdict(cleared),
            "record": record,
        }

    def _data(self, leave: Leave, sprint: int, cleared: Cleared) -> dict[str, Any]:
        return {
            "tool": TOOL,
            "reason": leave.reason,
            "question": None,
            "sprint": sprint,
            "cleared": asdict(cleared),
        }

    def _notice(self, story: StoryState, leave: Leave, sprint: int, cleared: Cleared) -> str:
        return NOTICE.format(
            story=story.id,
            title=story.title,
            sprint=sprint,
            reason=leave.reason,
            cleared=cleared.text,
        )

    def _line(self, leave: Leave, sprint: int, cleared: Cleared) -> str:
        return FILE_LINE.format(
            date=_today(), sprint=sprint, reason=leave.reason, cleared=cleared.text
        )

    async def _record(self, story: StoryState, line: str) -> str:
        """L4: add the line to the story file and commit it, holding the checkout lock."""
        rt = self.runtime
        file = story_spec.file_of(rt.config, story.id)
        path = rt.config.repo / file
        if not system.exists(path):
            return ""
        async with rt.checkout_lock:
            text = revert_log.append_under(system.read_text(path), FileSection(HEADING, line))
            system.write_text(path, text)
            sha = rt.git.commit([file], RECORD_SUBJECT.format(story=story.id))
            rt.record_checkout()
        return sha

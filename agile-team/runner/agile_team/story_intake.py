"""Queued story requests and the runner side that onboards them between steps (s135).

``agile-team story`` queues a request file; the router's ``Intake`` writes the story file,
commits it in the team's chain, records the commit against the story, places the story and
hands over to the PO. An amend replaces the story's ACs and sends it back to design.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import frontmatter, story_drafts, story_spec, system
from .boundary import BoundaryHold
from .dispatch import FileEdit
from .events import Event, EventKind
from .gates import FINISHED, StoryState
from .git_ops import Authored, GitError
from .numbered_queue import Entry, NumberedQueue
from .priority import After, Change, Pull, Reorder, Source
from .relay import LIAISON_DIR, Note
from .request_files import UNREADABLE_REQUEST, BadRequest, bad_request
from .sprint_add import Addition, SprintAdd
from .story_drafts import (
    Action,
    Draft,
    Known,
    Placing,
    StoryRequest,
    Target,
)

if TYPE_CHECKING:
    from .dispatch import Runtime

STORIES_DIR = "stories"
REQUEST_PREFIX = "q"
REQUEST_SUFFIX = ".json"
ROLE = "liaison"
SHORT = 12
INTAKE_HOLDS = frozenset({BoundaryHold.CI_FAILED, BoundaryHold.CI_INFRA, BoundaryHold.MAIN_BROKEN})

Request = StoryRequest | BadRequest


@dataclass(frozen=True)
class StoryQueue:
    """The story request files under the run directory."""

    run_dir: Path

    @property
    def folder(self) -> Path:
        """Where the request files live."""
        return self.run_dir / LIAISON_DIR / STORIES_DIR

    @property
    def _queue(self) -> NumberedQueue:
        return NumberedQueue(self.folder, REQUEST_PREFIX, REQUEST_SUFFIX)

    def queue(self, request: StoryRequest) -> StoryRequest:
        """Queue ``request`` as the next ``q<N>.json``, written whole, never overwriting."""
        queued = replace(request, at=system.now())
        entry = self._queue.publish(queued.to_json())
        return replace(queued, id=entry.id)

    def all(self) -> list[Request]:
        """Every numbered request, in number order; unreadable ones are bad requests."""
        return [self._read(entry) for entry in self._queue.entries()]

    def pending(self, settled: Mapping[str, str]) -> list[Request]:
        """Requests whose ids are not in ``settled``."""
        return [r for r in self.all() if r.id not in settled]

    @staticmethod
    def _read(entry: Entry) -> Request:
        try:
            return StoryRequest.from_json(entry.id, system.read_text(entry.path))
        except OSError as error:
            return bad_request(entry.id, UNREADABLE_REQUEST.format(error=error.strerror))


@dataclass(frozen=True)
class Refusal:
    """Why a request was refused, for the state text, the event and the liaison."""

    rid: str
    action: str
    story: str | None
    reason: str


@dataclass
class Intake:
    """Onboards pending story requests between steps (O1)."""

    runtime: Runtime

    def apply(self) -> None:
        """Settle every pending request in number order, unless a boundary is open."""
        if not self._due():
            return
        for request in StoryQueue(self.runtime.config.run_dir).pending(self._state.story_requests):
            self._settle(request)

    @property
    def _state(self) -> Any:
        return self.runtime.state

    def _due(self) -> bool:
        boundary = self._state.boundary
        return boundary is None or boundary.hold in INTAKE_HOLDS

    def _settle(self, request: Request) -> None:
        if isinstance(request, BadRequest):
            return self._refuse(Refusal(request.id, "", None, request.reason))
        checked = story_drafts.draft_problems(request, self._known(request))
        if checked.problems or checked.draft is None:
            return self._refuse(self._refusal(request, "; ".join(checked.problems)))
        handler = {Action.NEW: self._open, Action.AMEND: self._amend}[request.action]
        handler(request, checked.draft)

    def _known(self, request: StoryRequest) -> Known:
        envs = tuple(e.name for e in self.runtime.config.environments)
        return Known(envs, self._state.stories, self._text_of(request.story))

    def _text_of(self, story: str) -> str | None:
        if not story:
            return None
        try:
            return system.read_text(self.runtime.config.repo / self._file(story))
        except OSError:
            return None

    def _file(self, story: str) -> str:
        return story_spec.file_of(self.runtime.config, story)

    @staticmethod
    def _refusal(request: StoryRequest, reason: str) -> Refusal:
        return Refusal(request.id, request.action.value, request.story or None, reason)

    def _refuse(self, refusal: Refusal) -> None:
        self._state.story_requests[refusal.rid] = f"refused: {refusal.reason}"
        self.runtime.save()
        data = {"request": refusal.rid, "action": refusal.action, "reason": refusal.reason}
        self.runtime.events.emit(Event(EventKind.STORY_REFUSED, ROLE, refusal.story, data))
        self._post(story_drafts.POSTED_REFUSED.format(id=refusal.rid, reason=refusal.reason), [])

    def _commit(self, edit: FileEdit, message: Authored) -> str:
        """Write ``edit.new`` and commit it; on a git error restore the old text and re-raise."""
        path = self.runtime.config.repo / edit.file
        system.make_dirs(path.parent)
        system.write_text(path, edit.new)
        try:
            return self.runtime.git.commit_by([edit.file], message)
        except GitError:
            system.write_text(path, edit.old) if edit.old else system.remove(path)
            self.runtime.git.attempt("reset", "-q")
            raise

    def _failed(self, request: StoryRequest, error: GitError) -> None:
        reason = story_drafts.COMMIT_FAILED.format(error=error)
        self._refuse(self._refusal(request, reason))

    # ----- a new story (O2) -----

    def _open(self, request: StoryRequest, draft: Draft) -> None:
        sid = story_drafts.next_id(self._names())
        file = self._file(sid)
        text = story_drafts.with_id(request.text, sid)
        if problems := self._filed_problems(sid, file, text):
            reason = story_drafts.CANNOT_WRITE.format(file=file, problems="; ".join(problems))
            return self._refuse(self._refusal(request, reason))
        message = story_drafts.commit_message(request, Target(sid, draft.spec.title))
        try:
            sha = self._commit(FileEdit(file, "", text), message)
        except GitError as error:
            return self._failed(request, error)
        self._record_new(request, draft, (sid, file, sha))

    def _names(self) -> list[str]:
        folder = self.runtime.config.stories_dir
        files = [p.stem for p in system.list_dir(folder)] if system.is_dir(folder) else []
        return [*self._state.stories, *files]

    def _filed_problems(self, sid: str, file: str, text: str) -> tuple[str, ...]:
        envs = [e.name for e in self.runtime.config.environments]
        return story_spec.parse(story_spec.Source(sid, file, text), envs).problems

    def _record_new(self, request: StoryRequest, draft: Draft, made: tuple[str, str, str]) -> None:
        sid, file, sha = made
        rt, title = self.runtime, draft.spec.title
        given = list(draft.depends_on)
        story = StoryState(sid, title, rt.pipeline.first(), depends_on=given)
        story.file_commits, story.files = [sha], [file]
        self._state.stories[sid] = story
        rt.save()
        rt.record_checkout()
        data = {"title": title, "step": story.step, "depends_on": given, "request": request.id}
        data |= {"commit": sha, "approved_by": request.approved_by.value}
        data |= {"sprint": request.sprint, "after": request.after}
        rt.events.emit(Event(EventKind.STORY_OPENED, ROLE, sid, data))
        placed = self._place(request, sid)
        self._state.story_requests[request.id] = f"opened {sid} {sha[:SHORT]}; {placed}"
        rt.save()
        self._hand_over(request, story, (sha, placed))

    def _hand_over(self, request: StoryRequest, story: StoryState, made: tuple[str, str]) -> None:
        sha, placed = made
        fields = {"id": request.id, "story": story.id, "commit": sha[:SHORT], "placed": placed}
        approved = story_drafts.APPROVED[request.approved_by]
        told = story_drafts.TOLD_NEW.format(
            title=story.title, approved=approved, file=story.files[0], **fields
        )
        self.runtime.relay.tell(told)
        self._post(story_drafts.POSTED_NEW.format(**fields), [story.id])

    def _post(self, text: str, stories: list[str]) -> None:
        self.runtime.relay.post(Note("update", text, stories))

    # ----- placement (P1 to P4) -----

    def _place(self, request: StoryRequest, sid: str) -> str:
        after, dropped = self._open_after(request.after)
        placing = Placing(request.sprint)
        if placing is Placing.CURRENT:
            return self._place_current(request, (sid, after)) + dropped
        order = self._order(placing, (sid, after))
        reason = story_drafts.PLACE_REASON.format(id=request.id)
        self.runtime.reorder(Reorder(Change.MOVE, order, sid, reason, Pull(), Source.LIAISON))
        return story_drafts.PLACED[placing] + self._after_text(after) + dropped

    def _open_after(self, after: str) -> tuple[str, str]:
        story = self._state.stories.get(after)
        if story is None or story.status not in FINISHED:
            return after, ""
        return "", story_drafts.AFTER_DROPPED.format(anchor=after, status=story.status.value)

    @staticmethod
    def _after_text(after: str) -> str:
        return story_drafts.AFTER.format(anchor=after) if after else ""

    def _place_current(self, request: StoryRequest, placed: tuple[str, str]) -> str:
        sid, after = placed
        reason = story_drafts.PLACE_REASON.format(id=request.id)
        add, adder = Addition([sid], reason, Source.LIAISON, after), SprintAdd(self.runtime)
        if refusal := adder.refusal(add):
            text = story_drafts.NOT_ADDED.format(sprint=self._state.sprint, refusal=refusal)
            self._reorder_backlog(request, placed)
            return text
        adder.apply(add)
        sprint = story_drafts.PLACED[Placing.CURRENT].format(sprint=self._state.sprint)
        return sprint + self._after_text(after)

    def _reorder_backlog(self, request: StoryRequest, placed: tuple[str, str]) -> None:
        order = self._order(Placing.BACKLOG, placed)
        reason = story_drafts.PLACE_REASON.format(id=request.id)
        change = Reorder(Change.MOVE, order, placed[0], reason, Pull(), Source.LIAISON)
        self.runtime.reorder(change)

    def _order(self, placing: Placing, placed: tuple[str, str]) -> list[str]:
        sid, after = placed
        stories = self._state.stories
        plan = self.runtime.priority()
        if placing is Placing.BACKLOG or after:
            return plan.with_after(After(sid, after), stories.values())
        anchor = self._sprint_anchor(sid)
        if not anchor:
            return plan.with_first([sid], stories.values())
        return plan.with_after(After(sid, anchor), stories.values())

    def _sprint_anchor(self, sid: str) -> str:
        """The last story of the current sprint in the plan (without ``sid``), or ``""``."""
        inside = set(self._state.sprint_ids())
        plan = self.runtime.priority().plan(self._state.stories.values())
        return next((i for i in reversed(plan) if i in inside and i != sid), "")

    # ----- an amend (A1 to A6) -----

    def _amend(self, request: StoryRequest, draft: Draft) -> None:
        story, file = self._state.stories[request.story], self._file(request.story)
        old = self._text_of(request.story) or ""
        made = story_drafts.with_criteria(old, draft.spec.criteria)
        if made is None:
            reason = story_drafts.CANNOT_REWRITE.format(file=file)
            return self._refuse(self._refusal(request, reason))
        message = story_drafts.commit_message(request, Target(story.id, story.title))
        try:
            sha = self._commit(FileEdit(file, old, made), message)
        except GitError as error:
            return self._failed(request, error)
        self._record_amend(request, draft, (sha, old))

    def _record_amend(self, request: StoryRequest, draft: Draft, made: tuple[str, str]) -> None:
        sha, old = made
        rt, story = self.runtime, self._state.stories[request.story]
        from_step = story.step
        story.file_commits.append(sha)
        rt.pipeline.redesign(story)
        story.note = story_drafts.AMENDED_NOTE.format(id=request.id)
        rt.save()
        rt.record_checkout()
        before = _old_criteria(old)
        data = {"request": request.id, "commit": sha, "approved_by": request.approved_by.value}
        data |= {"from_step": from_step, "step": story.step, "old": before}
        data["new"] = story_drafts.criteria_data(draft.spec.criteria)
        rt.events.emit(Event(EventKind.STORY_AMENDED, ROLE, story.id, data))
        self._state.story_requests[request.id] = f"amended {story.id} {sha[:SHORT]}"
        rt.save()
        self._amend_hand_over(request, story, (sha, from_step, data))

    def _amend_hand_over(
        self, request: StoryRequest, story: StoryState, made: tuple[str, str, dict[str, Any]]
    ) -> None:
        sha, from_step, data = made
        fields = {"id": request.id, "story": story.id, "commit": sha[:SHORT], "step": story.step}
        ids = {k: ", ".join(_ids(data[k])) for k in ("old", "new")}
        told = story_drafts.TOLD_AMENDED.format(
            approved=story_drafts.APPROVED[request.approved_by],
            from_step=from_step,
            file=self._file(story.id),
            **ids,
            **fields,
        )
        self.runtime.relay.tell(told)
        self._post(story_drafts.POSTED_AMENDED.format(**fields), [story.id])


def _old_criteria(text: str) -> list[Any]:
    parsed = frontmatter.parse(text)
    old = parsed[0].get("acceptance") if parsed else None
    return old if isinstance(old, list) else []


def _ids(criteria: list[Any]) -> list[str]:
    return [str(c.get("id")) for c in criteria if isinstance(c, dict)]

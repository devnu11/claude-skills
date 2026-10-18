"""A story branch's push, its draft PR and its CI (s159 P4, SC1, SC2).

``StoryPusher`` pushes a story's branch after a committing step. ``StoryCiPoll`` reads the CI of
the story's pushed head now and then. Neither holds the story: only the landing CI decides.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .boundary import SUPERSEDED_BY, Permission, PrMode, StackEntry, find_current_entry
from .ci import Bucket, Check, CiResult, CiVerdict, check_lines, verdict_of
from .events import Event, EventKind
from .gates import FINISHED, StoryState
from .landing import STORY_PR_BODY
from .story_branches import StoryCi
from .upstream import Lease, PrSpec, UpstreamError

if TYPE_CHECKING:
    from .dispatch import Runtime

STORY_CI_POLL_S = 60


def find_sprint_entry(runtime: Runtime) -> StackEntry | None:
    """The current sprint's stack entry, else the newest one."""
    state = runtime.state
    return find_current_entry(state.upstream.stack, state.sprint)


class StoryPusher:
    """P4: pushes a story's branch with its lease and opens its draft PR."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime

    def after_step(  # house-rules: allow verb-name -- name fixed by the tests
        self,
        story: StoryState,
    ) -> str | None:
        """Push the story's worktree head when it moved; the refusal text, or ``None``."""
        entry, head = find_sprint_entry(self.runtime), story.worktree_head
        if not (story.branch and head and head != story.pushed) or not self._confirm_ready(entry):
            return None
        refused = self.runtime.upstream.push(Lease(story.branch, story.pushed, head))  # type: ignore[union-attr]
        if refused is not None:
            return refused
        story.pushed = head
        self._open_draft(story, entry)  # type: ignore[arg-type]
        return None

    def push_replayed(self, story: StoryState, old_pr: int | None) -> str | None:
        """R8, S3: push the replayed branch, open its draft PR, close the old one with a link."""
        refused = self.after_step(story)
        if refused is None and old_pr is not None and story.pr is not None:
            self._close(old_pr, story)
        return refused

    def _confirm_ready(self, entry: StackEntry | None) -> bool:
        """P1, P3: pushing needs permission yes, a PR service and a sprint branch."""
        rt = self.runtime
        if entry is None or rt.prs.missing() or rt.state.upstream.push is Permission.NO:
            return False
        if rt.state.upstream.push is Permission.UNASKED:
            rt.state.permission_asked = True
            return False
        return bool(entry.pushed) or self._open_sprint_branch(entry)

    def _open_sprint_branch(self, entry: StackEntry) -> bool:
        """The sprint branch must exist on the remote before a story PR can target it."""
        if entry.head and self.runtime.upstream.push(Lease(entry.branch, "", entry.head)) is None:  # type: ignore[union-attr]
            entry.pushed = entry.head
        return bool(entry.pushed)

    def _open_draft(self, story: StoryState, entry: StackEntry) -> None:
        if story.pr is not None:
            return
        title = f"{story.id}: {story.title}"
        body = STORY_PR_BODY.format(id=story.id, branch=entry.branch)
        spec = PrSpec(story.branch, entry.branch, title, body, PrMode.DRAFT)
        story.pr = self.runtime.prs.create(spec).number

    def _close(self, old_pr: int, story: StoryState) -> None:
        note = SUPERSEDED_BY.format(target=story.branch, url=f"#{story.pr}")
        self.runtime.prs.close(old_pr, note)


class StoryCiPoll:
    """SC1: reads each open story's PR CI, at most once per ``STORY_CI_POLL_S``."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self._read_at: dict[str, float] = {}

    def poll(self, story: StoryState, now: float) -> StoryCi | None:
        """Record and return a new settled result for the story's pushed head, else ``None``."""
        if not self.claim_due(story, now):
            return None
        sha = story.pushed
        return self.settle(story, self.read_checks(story), sha)

    def claim_due(self, story: StoryState, now: float) -> bool:
        """True, and the read time noted, when the story's head is due a read (loop thread)."""
        last = self._read_at.get(story.id)
        if not self.can_poll(story) or (last is not None and now - last < STORY_CI_POLL_S):
            return False
        self._read_at[story.id] = now
        return True

    def settle(self, story: StoryState, checks: list[Check], sha: str = "") -> StoryCi | None:
        """Record the checks once all are in (loop thread); the new result, else ``None``."""
        if not checks or any(c.bucket is Bucket.PENDING for c in checks):
            return None
        return self._record(story, checks, sha or story.pushed)

    def can_poll(self, story: StoryState) -> bool:
        """An open story with a pushed head, and a PR service to ask (D4)."""
        return (
            bool(story.pushed) and story.status not in FINISHED and not self.runtime.prs.missing()
        )

    def read_checks(self, story: StoryState) -> list[Check]:
        """The head's checks, safe in a worker thread; a failing ``gh`` is "no result" (AC8.3)."""
        try:
            return self.runtime.prs.sha_checks(story.pushed)  # type: ignore[arg-type]
        except UpstreamError:
            return []

    def _record(self, story: StoryState, checks: list[Check], sha: str) -> StoryCi | None:
        found = StoryCi(sha, str(verdict_of(checks)), "pr")
        if found == story.ci:
            return None
        story.ci = found
        data = {**found.__dict__, "checks": check_lines_of(checks)}
        self.runtime.events.emit(Event(EventKind.STORY_CI, None, story.id, data))
        return found


def check_lines_of(checks: list[Check]) -> list[str]:
    """The lines of the checks that did not pass."""
    return check_lines([CiResult(0, "", "", CiVerdict.NONE, checks)]).splitlines()

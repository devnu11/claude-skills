"""Designs that overlap open work wait at design (s163 F3 to F8)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING, Any

from . import design_files
from .events import Event, EventKind
from .gates import FINISHED, Outcome, StoryState, StoryStatus, Verdict, is_overlap_hold
from .loops import Author

if TYPE_CHECKING:
    from .dispatch import Runtime

IGNORED = (".team/**", "{docs}/architecture.md", "{docs}/design/**", "{docs}/requirements/**")
NO_REASON = "a reason is required"
OVERLAP_HOLD = (
    "the design overlaps {ids}: {pairs}; the story waits at design until they have landed, "
    "left the sprint or been cancelled"
)
RUNNER_LIFT = "every overlapping story has landed, left the sprint or been cancelled: {ids}"
LIFTED = "overlap lifted"


def drop_ignored(entries: Sequence[str], docs_dir: str) -> list[str]:
    """F4: the entries that are not in an ignored area (every design writes those)."""
    patterns = [p.format(docs=docs_dir.rstrip("/")) for p in IGNORED]
    return [e for e in entries if not any(fnmatchcase(e, p) for p in patterns)]


def match_pairs(ours: Sequence[str], theirs: Sequence[str]) -> list[str]:
    """F4: the overlapping entries, ``a`` when equal, else ``a ~ b``; sorted, no repeats."""
    found = {
        a if a == b else f"{a} ~ {b}"
        for a in ours
        for b in theirs
        if fnmatchcase(a, b) or fnmatchcase(b, a)
    }
    return sorted(found)


@dataclass(frozen=True)
class Lift:
    """Who lifts an overlap hold and why."""

    by: str
    reason: str


class Overlaps:
    """The overlap check at design, the hold's lift and the PO's early release."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime

    def screen(self, story: StoryState, outcome: Outcome) -> Outcome:
        """F3, F5: hold a design that overlaps another open story; else ``outcome`` unchanged."""
        if not self._is_checked(story, outcome):
            return outcome
        ours = self._read_ours(story)
        found = [m for o in self._find_others(story) if (m := self._match(ours, o))]
        if not found:
            return outcome
        story.overlap_with = [m["story"] for m in found]
        return self._hold(ours, found)

    def _is_checked(self, story: StoryState, outcome: Outcome) -> bool:
        passed = outcome.verdict is Verdict.PASS and story.step == "design"
        return bool(
            self.runtime.state.story_branches and passed and outcome.author is not Author.RUNNER
        )

    def _find_others(self, story: StoryState) -> list[StoryState]:
        rt = self.runtime
        return [
            o
            for o in rt.state.stories.values()
            if o.id != story.id
            and o.sprint == rt.state.sprint
            and o.status not in FINISHED
            and rt.pipeline.is_past_design(o)
        ]

    @property
    def _docs_dir(self) -> str:
        return self.runtime.config.team.docs_dir

    def _read_ours(self, story: StoryState) -> list[str]:
        checks = self.runtime.pipeline.checks
        text = checks.read(checks.design_file(story.id)) or ""
        return drop_ignored(design_files.parse_files(text), self._docs_dir)

    def _read_theirs(self, other: StoryState) -> list[str]:
        git, checks = self.runtime.git, self.runtime.pipeline.checks
        shown = git.attempt("show", f"{other.branch}:{checks.design_file(other.id)}")
        listed = design_files.parse_files(shown[1]) if shown[0] == 0 else []
        span = f"{other.base_sha}..{other.branch}"
        changed = self._read_changed_files(span) if other.branch else []
        return drop_ignored([*listed, *changed], self._docs_dir)

    def _read_changed_files(self, span: str) -> list[str]:
        """Paths changed in `span`; empty when git fails, so its error words are never paths."""
        code, out = self.runtime.git.attempt("diff", "--name-only", span)[:2]
        return out.split() if code == 0 else []

    def _match(self, ours: list[str], other: StoryState) -> dict[str, Any] | None:
        theirs = self._read_theirs(other)
        overlap = match_pairs(ours, theirs)
        return {"story": other.id, "files": theirs, "overlap": overlap} if overlap else None

    def _hold(self, ours: list[str], found: list[dict[str, Any]]) -> Outcome:
        ids = ", ".join(m["story"] for m in found)
        pairs = "; ".join(f"{m['story']}: {', '.join(m['overlap'])}" for m in found)
        reason = OVERLAP_HOLD.format(ids=ids, pairs=pairs)
        return Outcome(Verdict.HOLD, reason, overlap={"files": ours, "with": found})

    def lift_due(  # house-rules: allow verb-name -- name fixed by the s163 design
        self,
    ) -> None:
        """F6: lift every overlap hold whose stories have all landed, left or been cancelled."""
        for story in list(self.runtime.state.stories.values()):
            if is_overlap_hold(story) and self._is_clear(story):
                ids = ", ".join(story.overlap_with)
                self.lift(story, Lift("runner", RUNNER_LIFT.format(ids=ids)))

    def _is_clear(self, story: StoryState) -> bool:
        state = self.runtime.state
        others = [state.stories.get(i) for i in story.overlap_with]
        return all(self._is_gone(o, state.sprint) for o in others)

    def _is_gone(self, other: StoryState | None, sprint: int) -> bool:
        if other is None or other.sprint != sprint:
            return True
        return other.status in (StoryStatus.DONE, StoryStatus.CANCELLED)

    def release(self, story: StoryState, reason: str) -> dict[str, Any]:
        """F7: the PO lifts the hold early; the reason is required."""
        if not reason.strip():
            return {"status": "refused", "reason": NO_REASON}
        self.lift(story, Lift("po", reason))
        return {"status": "released", "story": story.id, "step": story.step}

    def lift(  # house-rules: allow verb-name -- name fixed by the s163 design
        self, story: StoryState, lift: Lift
    ) -> None:
        """F6 steps 1 to 4: clear the hold, drop the worktree, pass past design, log it."""
        rt, waited = self.runtime, list(story.overlap_with)
        story.hold, story.overlap_with = None, []
        rt.drop_worktree(story)
        rt.advance_as_runner(story, Outcome(Verdict.PASS, LIFTED, author=Author.RUNNER))
        data = {"with": waited, "by": lift.by, "reason": lift.reason}
        rt.events.emit(Event(EventKind.OVERLAP_LIFTED, lift.by, story.id, data))
        rt.save()

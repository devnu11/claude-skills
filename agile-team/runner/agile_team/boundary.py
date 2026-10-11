"""Sprint boundaries: pure data and texts, with no I/O.

A boundary is the runner's own work at a sprint's start or end edge: sync with
upstream, run the full checks, rebuild the review branches, push them. It is
saved as ``RunState.boundary`` until it finishes. ``boundary_runner`` does the
work; this module holds the state, the tables and the exact strings.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from .events import Event, EventKind
from .loops import Author, Setback, event_number
from .upstream import DETACHED as DETACHED
from .upstream import FETCH_FAILED as FETCH_FAILED
from .upstream import NO_REMOTE as NO_REMOTE
from .upstream import NO_TARGET as NO_TARGET
from .upstream import SYNC_OFF as SYNC_OFF
from .upstream import PrMode


class Edge(StrEnum):
    """Which edge of a sprint the boundary sits at."""

    START = "start"
    END = "end"


class Stage(StrEnum):
    """The boundary's stages, in order."""

    SYNC = "sync"
    CHECK = "check"
    REVIEW = "review"
    PUSH = "push"


class StepKind(StrEnum):
    """What a router step is: a role, the runner's boundary, or a devops fix."""

    ROLE = "role"
    BOUNDARY = "boundary"
    TEAM_FIX = "team-fix"
    REVIEW_FIX = "review-fix"


class BoundaryHold(StrEnum):
    """Why a boundary waits for a human or the PO."""

    SYNC_CONFLICT = "sync_conflict"
    ESCALATED = "escalated"
    REVIEWED = "reviewed"
    PUSH_PERMISSION = "push_permission"
    PUSH_REJECTED = "push_rejected"
    ERROR = "error"


class BoundaryOutcome(StrEnum):
    """What one boundary event reports."""

    SKIPPED = "skipped"
    CURRENT = "current"
    MERGED = "merged"
    CONFLICT = "conflict"
    PASS = "pass"
    FAIL = "fail"
    ESCALATE = "escalate"
    BUILT = "built"
    HELD = "held"
    PUSHED = "pushed"
    LOCAL = "local"
    ERROR = "error"
    DONE = "done"
    CONTINUED = "continued"
    PERMISSION = "permission"


class FixCase(StrEnum):
    """What a devops fix step repairs."""

    TEAM_CHECK = "team_check"
    REVIEW_CHECK = "review_check"
    REVIEW_CONFLICT = "review_conflict"


class Permission(StrEnum):
    """The human's answer to: may the team push review branches?"""

    UNASKED = "unasked"
    YES = "yes"
    NO = "no"


class CheckState(StrEnum):
    """The full-check result for one review branch."""

    UNCHECKED = "unchecked"
    PASS = "pass"
    FAIL = "fail"


STAGES = (Stage.SYNC, Stage.CHECK, Stage.REVIEW, Stage.PUSH)
RESTACK_ONLY = frozenset({Stage.REVIEW, Stage.PUSH})
FIX_KINDS = {
    FixCase.TEAM_CHECK: StepKind.TEAM_FIX,
    FixCase.REVIEW_CHECK: StepKind.TEAM_FIX,
    FixCase.REVIEW_CONFLICT: StepKind.REVIEW_FIX,
}

BOUNDARY_ROLE = "runner"
FIX_ROLE = "devops"
MERGE_MESSAGE = "chore(team): merge {target} at sprint {sprint} start"
SPRINT_TITLE = "Sprint {sprint}: {goal}"
MERGED_NOTE = "sprint {sprint} is in {target}; dropped from the stack"
BOUNDARY_DUE = (
    "sprint {sprint} {edge} boundary failed {count} times at {stage}; see repeated_boundary"
)
BOUNDARY_STALL = (
    "Sprint {sprint} {edge} is held at {stage} ({hold}); continue_boundary once it is resolved."
)
SKIPPED_REPORT = "sync and pull requests skipped: {why}"
NOTHING_REPORT = "nothing to review: every sprint is in {target}"
PUSHED_REPORT = (
    'Sprint {sprint} is up for review: {prs}. Merge the ready one with "Rebase and merge"; '
    "the next one becomes ready after it."
)
LOCAL_REPORT = (
    "Sprint {sprint}'s review branches are built and checked but not pushed ({why}): {branches}."
)
NOT_PERMITTED = "the human said no to pushing"
CHECK_FAILED = "{name} failed ({why}): {command}\n{tail}"

FIX_HEADING = (
    "Sprint {sprint} {edge} boundary: the runner's {stage} stage failed, and the sprint's "
    "stories wait until it passes. Fix it, then hand off."
)
FIX_LINES = {
    FixCase.TEAM_CHECK: (
        "The full checks failed on the team branch {team} at {sha}.",
        "Fix it on the team branch. In this step you may edit source, tests, e2e tests, CI and "
        "the [toolchain] and [[delivery]] config. The runner commits your changes and runs "
        "the full checks again.",
    ),
    FixCase.REVIEW_CHECK: (
        "The full checks failed on review branch {branch} (sprints {sprints} rebased onto "
        "{target}), checked out in {worktree}. Read that copy to diagnose; do not edit it.",
        "Fix it on the team branch (this repo). In this step you may edit source, tests, e2e "
        "tests, CI and the [toolchain] and [[delivery]] config. The runner rebuilds the review "
        "branches from the team branch and checks them again.",
    ),
    FixCase.REVIEW_CONFLICT: (
        "Rebuilding review branch {branch} onto {target} stopped: commit {commit} ({subject}) "
        "conflicts in {files}. You work in {worktree}, a scratch copy with the cherry-pick in "
        "progress.",
        "Resolve the conflict markers in exactly those files, keeping both sides' intent. "
        "Nothing else you change is kept. The runner records your resolution (git rerere), so "
        "every later rebuild reuses it.",
    ),
}
OUTPUT_BLOCK = "Output:\n```\n{output}\n```"
CLOSED_NOTE = "PR #{pr} for sprint {sprint} is {state}; left alone"
PO_NOTE = "From the PO: {note}"

BOUNDARY_REFUSAL = (
    "sprint {sprint} {edge} boundary is at {stage}{held}; the sprint's stories move once it passes"
)

PR_BODY = (
    "Sprint {sprint} of the agile team.\n\n{stories}\n\n{stacked}"
    'Rebuilt by agile-team from {team} onto {target}. Merge with "Rebase and merge".'
)
STACKED_LINE = "Stacked on {base} (#{base_pr}): review and merge that one first.\n\n"


@dataclass
class Failure:
    """Why a stage failed and what a fix step needs to know."""

    stage: Stage
    case: FixCase
    reason: str
    branch: str = ""
    files: list[str] = field(default_factory=list)
    commit: str = ""
    subject: str = ""

    def __post_init__(self) -> None:
        self.stage, self.case = Stage(self.stage), FixCase(self.case)


@dataclass
class Boundary:
    """One pending boundary: where it is, and what holds it."""

    edge: Edge
    sprint: int
    stage: Stage = Stage.SYNC
    hold: BoundaryHold | None = None
    failure: Failure | None = None
    streak: list[Setback] = field(default_factory=list)
    rounds: int = 0
    escalated: str | None = None
    restack: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        self.edge, self.stage = Edge(self.edge), Stage(self.stage)
        self.hold = BoundaryHold(self.hold) if self.hold else None


@dataclass
class StackEntry:
    """One sprint whose changes are not in the target yet."""

    sprint: int
    branch: str
    start: str
    end: str
    title: str = ""
    stories: list[str] = field(default_factory=list)
    head: str = ""
    checked: str = ""
    check: CheckState = CheckState.UNCHECKED
    pushed: str = ""
    pr: int | None = None
    url: str = ""
    base: str = ""
    mode: PrMode = PrMode.NONE

    def __post_init__(self) -> None:
        self.check, self.mode = CheckState(self.check), PrMode(self.mode)


@dataclass
class UpstreamState:
    """What the runner remembers about the remote between boundaries."""

    team_branch: str = ""
    push: Permission = Permission.UNASKED
    stack: list[StackEntry] = field(default_factory=list)
    last_end: str = ""
    checked: str = ""
    closed: int = 0
    report: str = ""

    def __post_init__(self) -> None:
        self.push = Permission(self.push)


@dataclass(frozen=True)
class Due:
    """One unit of boundary work for the router."""

    kind: StepKind
    role: str
    brief: str


@dataclass(frozen=True)
class FixContext:
    """The placeholders of a fix brief that come from the repo, not the failure."""

    team: str
    target: str
    worktree: str
    sha: str
    sprints: str


def next_stage(b: Boundary) -> Stage | None:
    """The stage after ``b.stage`` that applies to this edge, or ``None`` to finish."""
    skip = RESTACK_ONLY if b.edge is Edge.START and not b.restack else frozenset()
    later = STAGES[STAGES.index(b.stage) + 1 :]
    return next((s for s in later if s not in skip), None)


def setback(b: Boundary, failure: Failure) -> Setback:
    """The failure as an s27 setback, so repeats are found by key."""
    return Setback(b.edge, failure.stage, BOUNDARY_ROLE, "bounce", Author.RUNNER, failure.reason)


def held_text(b: Boundary) -> str:
    """``, held: <hold>`` for a held boundary, else an empty string."""
    return f", held: {b.hold}" if b.hold else ""


def fix_brief(b: Boundary, context: FixContext) -> str:
    """The devops fix brief: heading, case lines, quoted output and the PO's note."""
    f = b.failure
    assert f is not None
    values = {**asdict(context), **asdict(f), "files": ", ".join(f.files)}
    heading = FIX_HEADING.format(sprint=b.sprint, edge=b.edge, stage=f.stage)
    lines = [line.format(**values) for line in FIX_LINES[f.case]]
    parts = [heading, *lines, OUTPUT_BLOCK.format(output=f.reason)]
    return "\n\n".join(parts + ([PO_NOTE.format(note=b.note)] if b.note else []))


def _boundary_events(events: list[Event], first: int) -> list[dict[str, Any]]:
    mine = [e for e in events if _is_boundary_event(e)]
    return [asdict(e) for e in mine if event_number(e.id) >= first]


def _is_boundary_event(event: Event) -> bool:
    if event.kind is EventKind.BOUNDARY:
        return True
    return event.kind is EventKind.STEP_END and event.role == FIX_ROLE and event.story is None


def manager_view(b: Boundary, events: list[Event]) -> dict[str, Any]:
    """The ``repeated_boundary`` entry of the Manager's runner context."""
    last = b.streak[-1]
    first = min((event_number(s.event) for s in b.streak if s.event), default=0)
    return {
        "edge": b.edge,
        "sprint": b.sprint,
        "stage": last.to_step,
        "reason": b.escalated,
        "key": last.key,
        "count": len(b.streak),
        "history": [asdict(s) for s in b.streak],
        "events": _boundary_events(events, first),
    }

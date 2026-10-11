"""Sprint boundary data and texts: stages, failures, the review stack and fix briefs.

No I/O here. ``boundary_runner`` runs the stages; this module only says what
they are called, what state they leave behind and what the runner says.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from . import loops
from .loops import Author, Setback

if TYPE_CHECKING:
    from .events import Event

BOUNDARY_ROLE = "runner"
FIX_ROLE = "devops"
MERGE_MESSAGE = "chore(team): merge {target} at sprint {sprint} start"
SPRINT_TITLE = "Sprint {sprint}: {goal}"
SYNC_OFF = "[upstream] remote is empty"
NO_REMOTE = "no remote {remote!r}"
FETCH_FAILED = "git fetch {remote} failed: {error}"
NO_TARGET = "{target} does not exist"
DETACHED = "the repo is on a detached HEAD; check out the team branch"
MERGED_NOTE = "sprint {sprint} is in {target}; dropped from the stack"
CLOSED_NOTE = "PR #{pr} for sprint {sprint} is {state}; left alone"
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
OUTPUT_BLOCK = "Output:\n```\n{output}\n```"
PR_BODY = (
    "Sprint {sprint} of the agile team.\n\n{stories}\n\n{stacked}"
    'Rebuilt by agile-team from {team} onto {target}. Merge with "Rebase and merge".'
)
STACKED_LINE = "Stacked on {base} (#{base_pr}): review and merge that one first.\n\n"


class Edge(StrEnum):
    """Which end of a sprint the boundary is at."""

    START = "start"
    END = "end"


class Stage(StrEnum):
    """The boundary's stages, in order."""

    SYNC = "sync"
    CHECK = "check"
    REVIEW = "review"
    PUSH = "push"


class StepKind(StrEnum):
    """What a router step is: a role, the runner's boundary, or a boundary fix."""

    ROLE = "role"
    BOUNDARY = "boundary"
    TEAM_FIX = "team-fix"
    REVIEW_FIX = "review-fix"


class BoundaryHold(StrEnum):
    """Why a boundary waits for the PO."""

    SYNC_CONFLICT = "sync_conflict"
    ESCALATED = "escalated"
    REVIEWED = "reviewed"
    PUSH_PERMISSION = "push_permission"
    PUSH_REJECTED = "push_rejected"
    ERROR = "error"


class BoundaryOutcome(StrEnum):
    """The ``outcome`` of a ``boundary`` event."""

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
    """What failed, which decides the fix step's scope."""

    TEAM_CHECK = "team_check"
    REVIEW_CHECK = "review_check"
    REVIEW_CONFLICT = "review_conflict"


class Permission(StrEnum):
    """The human's answer to pushing review branches."""

    UNASKED = "unasked"
    YES = "yes"
    NO = "no"


class CheckState(StrEnum):
    """Whether a review branch's full checks ran and how."""

    UNCHECKED = "unchecked"
    PASS = "pass"
    FAIL = "fail"


class PrMode(StrEnum):
    """How a stack entry's pull request should be."""

    NONE = "none"
    DRAFT = "draft"
    READY = "ready"
    CLOSED = "closed"


STAGES = (Stage.SYNC, Stage.CHECK, Stage.REVIEW, Stage.PUSH)
RESTACK_ONLY = frozenset({Stage.REVIEW, Stage.PUSH})
FIX_KINDS = {
    FixCase.TEAM_CHECK: StepKind.TEAM_FIX,
    FixCase.REVIEW_CHECK: StepKind.TEAM_FIX,
    FixCase.REVIEW_CONFLICT: StepKind.REVIEW_FIX,
}
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


@dataclass
class Failure:
    """What failed at a stage, for the fix step."""

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
    """The runner's pending work at a sprint's start or end edge."""

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
    """What the runner remembers about upstream between boundaries."""

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
    """Work the router should run for the boundary."""

    kind: StepKind
    role: str
    brief: str


@dataclass(frozen=True)
class FixContext:
    """The placeholders of a fix brief that do not come from the failure."""

    team: str
    target: str
    worktree: str
    sha: str
    sprints: str


def next_stage(b: Boundary) -> Stage | None:
    """The stage after ``b.stage`` (skipping restack-only ones at a plain start), or ``None``."""
    skip = RESTACK_ONLY if b.edge is Edge.START and not b.restack else frozenset()
    later = STAGES[STAGES.index(b.stage) + 1 :]
    return next((s for s in later if s not in skip), None)


def setback(b: Boundary, failure: Failure) -> Setback:
    """The failure as a s27 setback, keyed by edge, stage and normalised reason."""
    return Setback(
        step=b.edge.value,
        to_step=failure.stage.value,
        role=BOUNDARY_ROLE,
        verdict="bounce",
        author=Author.RUNNER,
        reason=failure.reason,
    )


def held_text(b: Boundary) -> str:
    """``, held: <hold>`` when the boundary is held, else an empty string."""
    return f", held: {b.hold.value}" if b.hold else ""


def fix_brief(b: Boundary, context: FixContext) -> str:
    """The devops fix step's brief: heading, what failed, what to do, the output, the PO note."""
    failure = b.failure
    assert failure is not None
    heading = FIX_HEADING.format(sprint=b.sprint, edge=b.edge.value, stage=failure.stage.value)
    values = {**asdict(context), **_failure_values(failure)}
    lines = [line.format(**values) for line in FIX_LINES[failure.case]]
    parts = [heading, *lines, OUTPUT_BLOCK.format(output=failure.reason)]
    note = f"\n\nFrom the PO: {b.note}" if b.note else ""
    return "\n\n".join(parts) + note


def _failure_values(failure: Failure) -> dict[str, str]:
    return {
        "branch": failure.branch,
        "commit": failure.commit,
        "subject": failure.subject,
        "files": ", ".join(failure.files),
    }


def _first_event(b: Boundary) -> int:
    return min((loops.event_number(s.event) for s in b.streak if s.event), default=0)


def _in_history(event: Event, first: int) -> bool:
    boundary = event.kind == "boundary"
    fix = event.kind == "step-end" and event.role == FIX_ROLE and event.story is None
    return (boundary or fix) and loops.event_number(event.id) >= first


def manager_view(b: Boundary, events: list[Event]) -> dict[str, Any]:
    """The ``repeated_boundary`` entry of the Manager's runner context."""
    first = _first_event(b)
    return {
        "edge": b.edge.value,
        "sprint": b.sprint,
        "stage": b.failure.stage.value if b.failure else b.stage.value,
        "reason": b.escalated,
        "key": b.streak[-1].key,
        "count": len(b.streak),
        "history": [asdict(s) for s in b.streak],
        "events": [asdict(e) for e in events if _in_history(e, first)],
    }

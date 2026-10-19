"""Sprint boundary data and texts: stages, failures, the sprint PR entry and fix briefs.

No I/O here. ``boundary_runner`` runs the stages; this module only says what
they are called, what state they leave behind and what the runner says.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from . import loops
from .ci import CiResult, CiVerdict
from .loops import Author, Setback

if TYPE_CHECKING:
    from .config import UpstreamSettings
    from .events import Event

BOUNDARY_ROLE = "runner"
FIX_ROLE = "devops"
SPRINT_TITLE = "Sprint {sprint}: {goal}"
SYNC_OFF = "[upstream] remote is empty"
NO_REMOTE = "no remote {remote!r}"
FETCH_FAILED = "git fetch {remote} failed: {error}"
NO_TARGET = "{target} does not exist"
DETACHED = "the repo is on a detached HEAD; check out the team branch"
NOTHING_NEW = "sprint {sprint} added no commit since the last sprint end; nothing to push or rebase"
SPRINT_BRANCH_DIVERGED = (
    "the sprint branch {branch} on {remote} is at {remote_sha}, which does not descend from the "
    "runner's {pushed}; nothing was pushed"
)
SUPERSEDED_BY = "Replayed onto {target} as {url}; this PR is superseded."
FF_COMMAND = "git push {remote} {sha}:{target}"
SUPERSEDED_NOTE = (
    "sprint {old}'s PR #{pr} is superseded: sprint {sprint}'s branch holds its commits"
)
CLOSED_NOTE = "PR #{pr} for sprint {sprint} is {state}; left alone"
BOUNDARY_DUE = (
    "sprint {sprint} {edge} boundary failed {count} times at {stage}; see repeated_boundary"
)
BOUNDARY_STALL = "Sprint {sprint} {edge} is held at {stage} ({hold}); {hint}."
DEFAULT_HINT = "continue_boundary once it is resolved"
CI_BUG_FIRST = "story {story} fixes the failing CI of the last review PR; list it first"
BOUNDARY_REFUSAL = (
    "sprint {sprint} {edge} boundary is at {stage}{held}; the sprint's stories move once it passes"
)
SKIPPED_REPORT = "sync and pull requests skipped: {why}"
PUSHED_REPORT = (
    "Sprint {sprint}'s branch {branch} holds the team branch as built ({sha}): PR #{pr} {url}. "
    "The runner waits for its CI; the team branch is rebased onto {target} only once it is green."
)
CI_RED_HELD = (
    "Sprint {sprint}'s CI failed on the team branch as built ({prs}); the boundary holds and "
    "nothing is rebased:\n{checks}"
)
NO_AS_IS = "no as-built push is recorded for this sprint"
REBASE_WAITS = (
    "the rebase waits for green CI on the team branch as built: {branch} at {sha} has {verdict}"
)
REBASE_UNCHANGED = "the rebase changed nothing; {branch} stays at {sha}"
REBASED_PUSHED_REPORT = (
    "Sprint {sprint}'s PR #{pr} now holds the team branch rebased onto {target} ({sha}); the "
    "as-built push ({as_is}) stays in the PR's history. The runner waits for CI again."
)
REBASED_NOT_GREEN = (
    "Sprint {sprint}'s CI was green on the team branch as built ({as_is}), and is {verdict} on it "
    "rebased onto {target} ({prs}). The PR is NOT ready; do not merge it.\n{checks}"
)
NOT_REBASED = " The team branch is not rebased onto {target}: the rebase waits for green CI."
REBASE_MERGE_LIMIT = 100
BIG_PR_NOTE = (
    "PR #{pr} ({branch}) has {commits} commits, more than the {limit} GitHub merges in one "
    "step. Merge it by fast-forward: git fetch {remote} && " + FF_COMMAND
)
LOCAL_REPORT = (
    "Sprint {sprint}'s branch {branch} is checked but not pushed ({why}). No CI result exists."
)
SUPERSEDES_LINE = (
    "Holds the commits of earlier sprint PRs {prs}, not merged yet; merging this one merges them "
    "too, so close them once it is merged.\n\n"
)
NOT_PERMITTED = "the human said no to pushing"
START_CURRENT = "the team branch is current with {target}"
START_CONFLICT = (
    'Sprint {sprint} start: rebasing {team} onto {target} stopped at {commit} "{subject}" with '
    "conflicts in: {files}. The rebase was aborted, {team} is unchanged and the sprint goes on "
    "from it. The human can rebase {team} by hand; until then the sprint end's PR conflicts "
    "with {target}, so it gets no CI and the end does not rebase."
)
KNOWN_FAILURES_NOTE = (
    "Sprint {sprint} starts with {count} known failures on {team} at {sha}: {ids}. Nothing is "
    "held and the sprint goes on; the PO asks you for a story for them (request_story)."
)
CHECK_FAILED = "{name} failed ({why}): {command}\n{tail}"
FIX_HEADING = (
    "Sprint {sprint} {edge} boundary: the runner's {stage} stage failed, and the sprint's "
    "stories wait until it passes. Fix it, then hand off."
)
FIX_NOT_DONE = "the DevOps step ended {status}"
CHECKS_FAILED = "the full checks failed in {path}: {reason}"
REBASE_FIX_HELD = (
    'Sprint {sprint}\'s rebase onto {target} stopped at {commit} "{subject}" (conflicts in '
    "{files}), and DevOps could not settle it: {reason}. DevOps's notes: {notes}. The team "
    "branch is unchanged; DevOps's work is on the branch {branch}. The boundary holds for "
    "the PO."
)
OUTPUT_BLOCK = "Output:\n```\n{output}\n```"
PR_BODY = (
    "Sprint {sprint} of the agile team.\n\n{stories}\n\n{reverted}{supersedes}"
    "The team branch {team} as built and tested, then, once its CI passed, replayed onto "
    "{target}. Merge it by fast-forward only: " + FF_COMMAND
)
RETIRED_CASES = frozenset({"review_check", "review_conflict"})
RETIRED_ENTRY_KEYS = ("checked", "check")
RETIRED_BOUNDARY_KEYS = ("restack",)


def big_pr_notes(stack: list[StackEntry], upstream: UpstreamSettings) -> list[str]:
    """One fast-forward note per entry with more commits than the PR merge limit."""
    return [
        BIG_PR_NOTE.format(
            pr=e.pr,
            branch=e.branch,
            commits=e.commits,
            limit=REBASE_MERGE_LIMIT,
            remote=upstream.remote,
            sha=f"{upstream.remote}/{e.branch}",
            target=upstream.branch,
        )
        for e in stack
        if e.commits > REBASE_MERGE_LIMIT
    ]


class Edge(StrEnum):
    """Which end of a sprint the boundary is at."""

    START = "start"
    END = "end"


class Stage(StrEnum):
    """The boundary's stages, in order."""

    SYNC = "sync"
    CHECK = "check"
    PUSH = "push"
    CI = "ci"
    OPEN = "open"
    REPLAY = "replay"
    PUSH_REPLAYED = "push-replayed"
    CI_REPLAYED = "ci-replayed"


class StepKind(StrEnum):
    """What a router step is: a role, the runner's boundary, a boundary fix or a gate fix (s92)."""

    ROLE = "role"
    BOUNDARY = "boundary"
    TEAM_FIX = "team-fix"
    GATE_FIX = "gate-fix"
    REBASE_FIX = "rebase-fix"
    LAND = "land"
    STORY_REBASE = "story-rebase"


class BoundaryHold(StrEnum):
    """Why a boundary waits for the PO."""

    SYNC_CONFLICT = "sync_conflict"
    REBASE_CONFLICT = "rebase_conflict"
    ESCALATED = "escalated"
    REVIEWED = "reviewed"
    PUSH_REJECTED = "push_rejected"
    CI_FAILED = "ci_failed"
    CI_INFRA = "ci_infra"
    MAIN_BROKEN = "main_broken"
    CI_PENDING = "ci_pending"
    ERROR = "error"
    FIX_HANDOVER = "fix_handover"


class BoundaryOutcome(StrEnum):
    """The ``outcome`` of a ``boundary`` event."""

    SKIPPED = "skipped"
    CURRENT = "current"
    REBASED = "rebased"
    CONFLICT = "conflict"
    PASS = "pass"
    FAIL = "fail"
    RERUN = "rerun"
    ESCALATE = "escalate"
    HELD = "held"
    PUSHED = "pushed"
    LOCAL = "local"
    ERROR = "error"
    DONE = "done"
    CONTINUED = "continued"
    PERMISSION = "permission"
    SUPERSEDED = "superseded"
    REFUSED = "refused"
    FOLLOWED = "followed"
    OPENED = "opened"


class FixCase(StrEnum):
    """What failed, which decides the fix step's scope."""

    TEAM_CHECK = "team_check"
    REBASE_CONFLICT = "rebase_conflict"


class Permission(StrEnum):
    """The human's answer to pushing review branches."""

    UNASKED = "unasked"
    YES = "yes"
    NO = "no"


class PrMode(StrEnum):
    """How a stack entry's pull request should be."""

    NONE = "none"
    DRAFT = "draft"
    READY = "ready"
    CLOSED = "closed"


PR_KIND = {
    PrMode.NONE: "none",
    PrMode.READY: "open",
    PrMode.DRAFT: "draft",
    PrMode.CLOSED: "closed",
}


EDGE_STAGES = {
    Edge.START: (Stage.SYNC, Stage.CHECK, Stage.PUSH_REPLAYED, Stage.OPEN),
    Edge.END: (
        Stage.SYNC,
        Stage.CHECK,
        Stage.PUSH,
        Stage.CI,
        Stage.REPLAY,
        Stage.PUSH_REPLAYED,
        Stage.CI_REPLAYED,
    ),
}
LEGACY_STAGES = {
    "review": Stage.PUSH,
    "restack": Stage.PUSH,
    "rebase": Stage.REPLAY,
    "push-rebased": Stage.PUSH_REPLAYED,
    "ci-rebased": Stage.CI_REPLAYED,
}
CI_BUG_HOLDS = frozenset({BoundaryHold.CI_FAILED, BoundaryHold.CI_INFRA, BoundaryHold.MAIN_BROKEN})
STALL_HINTS = {
    BoundaryHold.CI_FAILED: "open a bug story and record it with record_ci_bug(story)",
    BoundaryHold.CI_INFRA: (
        "tell the human the job never ran; continue_boundary once it re-ran, "
        "or record_ci_bug(story)"
    ),
    BoundaryHold.MAIN_BROKEN: "open a bug story for main and record it with record_ci_bug(story)",
    BoundaryHold.REBASE_CONFLICT: (
        "relay the conflict; continue_boundary(note) runs the rebase and DevOps again "
        "with your note"
    ),
    BoundaryHold.FIX_HANDOVER: (
        "answer the devops fix's handover, then continue_boundary(note) to rerun the stage"
    ),
}
FIX_KINDS = {
    FixCase.TEAM_CHECK: StepKind.TEAM_FIX,
    FixCase.REBASE_CONFLICT: StepKind.REBASE_FIX,
}
FIX_LINES = {
    FixCase.TEAM_CHECK: (
        "The full checks failed on the team branch {team} at {sha}.",
        "Fix it on the team branch. In this step you may edit source, tests, e2e tests, CI and "
        "the [toolchain] and [[environment]] config. The runner commits your changes and runs "
        "the full checks again.",
    ),
    FixCase.REBASE_CONFLICT: (
        'Rebasing the team branch {team} onto {target} stopped at {commit} "{subject}" with '
        "conflicts in: {files}. The runner aborted that rebase, so {team} is unchanged.",
        "The same rebase is stopped in the scratch worktree {worktree}, on the branch {branch}. "
        "Resolve it there and only there (run git as `git -C {worktree} ...`): edit only the "
        "conflicting files, keep both sides' intent, `git add` them and run `git rebase "
        "--continue` until the rebase is done. Never merge, squash, reorder, reword, skip or "
        "drop a commit; keep a commit that became empty with `git commit --allow-empty -C "
        "REBASE_HEAD`. Run named tests in {worktree}. The runner then checks the result, runs "
        "the full checks in {worktree} and moves {team} to {branch} only if they pass. If you "
        "cannot resolve it, hand off failed with notes the human can act on.",
    ),
}
REPLAY_FIX_LINES = (
    'Replaying the team branch {team} onto the target stopped at {commit} "{subject}" '
    "(story {story}) with conflicts in: {files}. The replay is stopped, not aborted, in the "
    "scratch worktree {worktree}, on the branch {branch}; {team} is unchanged.",
    "Resolve it there and only there (run git as `git -C {worktree} ...`): edit only the "
    "conflicting files, keep both sides' intent, `git add` them and run `git rebase "
    "--continue` (or `git cherry-pick --continue` when a cherry-pick stopped) until it is "
    "done. Never merge, squash, reorder, reword, skip or drop a commit; keep a commit that "
    "became empty with `git commit --allow-empty -C REBASE_HEAD`. Run named tests in "
    "{worktree}. The runner then checks story {story}'s commits, goes on with the replay, runs "
    "the full checks in {worktree} and moves {team} to {branch} only if they pass. If you "
    "cannot resolve it, hand off failed with notes the human can act on.",
)


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
    worktree: str = ""
    story: str = ""

    def __post_init__(self) -> None:
        self.stage, self.case = Stage(self.stage), FixCase(self.case)


@dataclass
class RebaseFix:
    """DevOps's answer to a sprint-end rebase conflict, waiting for the rebase stage."""

    conflict: Failure  # the REBASE_CONFLICT failure the step was given
    status: str  # the DevOps handoff's status
    notes: str  # the DevOps handoff's summary


@dataclass
class ReplayProgress:
    """R1: where a replay stands, so a crash or a conflict resumes at the right commit."""

    old_head: str
    base: str
    target: str
    done: int = 0
    tip: str = ""
    story: str = ""
    moved: dict[str, str] = field(default_factory=dict)
    merges: bool = False


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
    note: str = ""
    sync_from: str = ""
    rebase_fix: RebaseFix | None = None
    replay: ReplayProgress | None = None
    replayed: bool = False

    def __post_init__(self) -> None:
        self.edge, self.stage = Edge(self.edge), Stage(self.stage)
        if isinstance(self.replay, dict):
            self.replay = ReplayProgress(**self.replay)
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
    pushed: str = ""
    pr: int | None = None
    url: str = ""
    base: str = ""
    mode: PrMode = PrMode.NONE
    ci: CiResult | None = None
    commits: int = 0
    reverted: list[str] = field(default_factory=list)
    reran: list[str] = field(default_factory=list)
    as_is: str = ""
    supersedes: list[int] = field(default_factory=list)
    as_is_branch: str = ""
    as_is_pr: int | None = None
    replays: int = 0

    def __post_init__(self) -> None:
        self.mode = PrMode(self.mode)


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
    ci_bug: str = ""

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
    sha: str


def next_stage(b: Boundary) -> Stage | None:
    """The stage after ``b.stage`` on its edge, or ``None``."""
    order = EDGE_STAGES[b.edge]
    later = order[order.index(b.stage) + 1 :] if b.stage in order else ()
    return later[0] if later else None


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
    lines = [line.format(**values) for line in _fix_lines(failure)]
    parts = [heading, *lines, OUTPUT_BLOCK.format(output=failure.reason)]
    note = f"\n\nFrom the PO: {b.note}" if b.note else ""
    return "\n\n".join(parts) + note


def _fix_lines(failure: Failure) -> tuple[str, ...]:
    """R2: a replay stopped inside a story has its own text; else the case's."""
    if failure.case is FixCase.REBASE_CONFLICT and failure.story:
        return REPLAY_FIX_LINES
    return FIX_LINES[failure.case]


def _failure_values(failure: Failure) -> dict[str, str]:
    return {
        "story": failure.story,
        "branch": failure.branch,
        "commit": failure.commit,
        "subject": failure.subject,
        "worktree": failure.worktree,
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


def stall_hint(hold: BoundaryHold | None) -> str:
    """What the PO should do about a boundary held for ``hold``."""
    return STALL_HINTS.get(hold, DEFAULT_HINT) if hold else DEFAULT_HINT


def own_entry(stack: list[StackEntry], sprint: int) -> StackEntry | None:
    """The stack entry of ``sprint``, or ``None``."""
    return next((e for e in stack if e.sprint == sprint), None)


def find_current_entry(stack: list[StackEntry], sprint: int) -> StackEntry | None:
    """The sprint's own stack entry, else the newest one, else ``None``."""
    return own_entry(stack, sprint) or (stack[-1] if stack else None)


def get_rebase_refusal(entry: StackEntry | None) -> str:
    """Why the rebase must wait; empty only when the as-built push has green CI at its head."""
    if entry is None:
        return NO_AS_IS
    ci = entry.ci
    if ci is not None and ci.verdict is CiVerdict.GREEN and ci.head == entry.pushed:
        return ""
    verdict = ci.verdict.value if ci else "no CI read"
    sha = entry.pushed or "nothing pushed"
    return REBASE_WAITS.format(branch=entry.branch, sha=sha, verdict=verdict)

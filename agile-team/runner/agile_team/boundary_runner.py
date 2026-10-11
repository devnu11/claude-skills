"""Runs a sprint boundary one stage at a time: sync, check, review, push.

The router asks ``due`` for the next unit of work, runs a stage with ``step`` or
a devops fix with ``run_role``, and calls ``after_fix`` when the fix is back.
All git access goes through ``runtime.upstream`` and ``runtime.prs``; checks run
through ``runtime.shell``. Nothing here rewrites the team branch.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import halt, handover, loops
from .boundary import (
    BOUNDARY_DUE,
    BOUNDARY_ROLE,
    CLOSED_NOTE,
    FIX_KINDS,
    FIX_ROLE,
    LOCAL_REPORT,
    MERGE_MESSAGE,
    MERGED_NOTE,
    NOT_PERMITTED,
    NOTHING_REPORT,
    PR_BODY,
    PUSHED_REPORT,
    SKIPPED_REPORT,
    SPRINT_TITLE,
    STACKED_LINE,
    Boundary,
    BoundaryHold,
    BoundaryOutcome,
    CheckState,
    Due,
    Edge,
    Failure,
    FixCase,
    FixContext,
    Permission,
    PrMode,
    StackEntry,
    Stage,
    StepKind,
    fix_brief,
    next_stage,
    setback,
)
from .events import Event, EventKind
from .fullcheck import CheckReport, Judging, full_checks, run_checks
from .gates import StoryStatus
from .relay import Note
from .stack import REVIEW_DIR, Build, Conflict, Rebuilder
from .upstream import Lease, MergeOutcome, Pr, PrSpec, PrState, Upstream

if TYPE_CHECKING:
    from .dispatch import Runtime

Out = BoundaryOutcome
FETCH_PREFIX = "git fetch "


def fetch_failed(why: str) -> bool:
    """Whether a skip reason is the fetch failing."""
    return why.startswith(FETCH_PREFIX)


def boundary_data(runtime: Runtime, b: Boundary | None) -> dict[str, Any]:
    """The fields every boundary event and report carries."""
    if b is None:
        return {"edge": Edge.END, "sprint": runtime.state.sprint, "stage": Stage.PUSH}
    return {
        "edge": b.edge,
        "sprint": b.sprint,
        "stage": b.stage,
        "target": runtime.upstream.target,  # type: ignore[union-attr]  # set in __post_init__
        "team_branch": runtime.state.upstream.team_branch,
    }


def boundary_event(
    runtime: Runtime, b: Boundary | None, outcome: BoundaryOutcome, **data: Any
) -> Event:
    """Log one ``boundary`` event for ``b`` (or for a permission answer with no boundary)."""
    fields = {**boundary_data(runtime, b), "outcome": outcome, **data}
    return runtime.events.emit(Event(EventKind.BOUNDARY, BOUNDARY_ROLE, None, fields))


@dataclass
class BoundaryRunner:
    """The runner's own sprint-boundary work, one stage per call."""

    runtime: Runtime
    last: Event | None = field(default=None, init=False)
    rebuilder: Rebuilder = field(init=False)

    def __post_init__(self) -> None:
        rt = self.runtime
        worktree = rt.config.run_dir / REVIEW_DIR
        self.rebuilder = Rebuilder(rt.git, worktree, self.remote.target)

    # ----- shortcuts

    @property
    def remote(self) -> Upstream:
        """The runtime's upstream (always set by ``Runtime.__post_init__``)."""
        return self.runtime.upstream  # type: ignore[return-value]

    @property
    def mine(self):
        """The saved upstream state."""
        return self.runtime.state.upstream

    @property
    def stack(self) -> list[StackEntry]:
        return self.mine.stack

    @property
    def target(self) -> str:
        return self.rebuilder.target

    # ----- what the router asks

    def due(self) -> Due | None:
        """The next boundary work: a stage, a devops fix, or nothing while held."""
        b = self.runtime.state.boundary
        if b is None or b.hold:
            return None
        if b.failure is None:
            return Due(StepKind.BOUNDARY, BOUNDARY_ROLE, "")
        return Due(FIX_KINDS[b.failure.case], FIX_ROLE, fix_brief(b, self._context(b)))

    def open_end(self) -> bool:
        """Open the end boundary when every story of the sprint is done and it has not run."""
        state = self.runtime.state
        mine = [s for s in state.stories.values() if s.sprint == state.sprint]
        done = bool(mine) and all(s.status is StoryStatus.DONE for s in mine)
        if state.boundary or not done or self.mine.closed >= state.sprint:
            return False
        state.boundary = Boundary(Edge.END, state.sprint)
        return True

    def step(self) -> dict[str, Any]:
        """Run the current stage once; any exception holds the boundary as an error."""
        b = self.runtime.state.boundary
        try:
            STAGE_RUNNERS[b.stage](self, b)  # type: ignore[union-attr]
        except Exception as exc:
            self._error(b, exc)  # type: ignore[arg-type]
        self.runtime.save()
        data = self.last.data  # type: ignore[union-attr]
        return {"role": BOUNDARY_ROLE, "status": "boundary", "boundary": data}

    def after_fix(self, report: dict[str, Any]) -> None:
        """A devops fix is back: record a conflict resolution, count the round, rerun the stage."""
        b = self.runtime.state.boundary
        if b is None or report.get("status") == "halted":
            return
        failure = b.failure
        if failure and failure.case is FixCase.REVIEW_CONFLICT:
            self.rebuilder.record(failure.files)
        b.rounds, b.failure, b.note = b.rounds + 1, None, ""
        b.hold = handover.hold_reason(report)
        self.runtime.save()

    # ----- events and holds

    def _emit(self, b: Boundary, outcome: BoundaryOutcome, **data: Any) -> Event:
        self.last = boundary_event(self.runtime, b, outcome, **data)
        return self.last

    def _hold(self, b: Boundary, hold: BoundaryHold, outcome: BoundaryOutcome, **data: Any) -> None:
        b.hold = hold
        self._emit(b, outcome, hold=hold, **data)

    def _error(self, b: Boundary, exc: Exception) -> None:
        halt.log_traceback(self.runtime.config.run_dir, exc)
        reason = f"{type(exc).__name__}: {exc}"
        self._hold(b, BoundaryHold.ERROR, Out.ERROR, reason=reason)

    def _post(self, text: str) -> None:
        self.runtime.relay.post(Note("update", text, []))

    def _context(self, b: Boundary) -> FixContext:
        failure = b.failure
        branches = [e.branch for e in self.stack]
        upto = branches.index(failure.branch) + 1 if failure and failure.branch in branches else 0
        sprints = ", ".join(str(e.sprint) for e in self.stack[:upto])
        worktree = str(self.rebuilder.worktree)
        head = self.runtime.git.head()
        return FixContext(self.mine.team_branch, self.target, worktree, head, sprints)

    # ----- finishing

    def _close(self, b: Boundary, report: str) -> None:
        if b.edge is Edge.END:
            self.mine.closed, self.mine.report = b.sprint, report
        self.runtime.state.boundary = None

    def _finish(self, b: Boundary, report: str = "") -> None:
        self._close(b, report)
        self._emit(b, Out.DONE)

    def _advance(self, b: Boundary) -> None:
        following = next_stage(b)
        if following is None:
            self._finish(b)
        else:
            b.stage = following

    # ----- sync

    def _sync(self, b: Boundary) -> None:
        why = self.remote.missing()
        if why:
            return self._skip(b, why)
        self.mine.team_branch = self.remote.team_branch()
        self._drop_merged(b)
        SYNCS[b.edge](self, b)

    def _skip(self, b: Boundary, why: str) -> None:
        if b.edge is Edge.END and fetch_failed(why):
            self._add_entry(b)
        self._emit(b, Out.SKIPPED, note=why)
        self._close(b, SKIPPED_REPORT.format(why=why))

    def _merge_in(self, b: Boundary) -> None:
        message = MERGE_MESSAGE.format(target=self.target, sprint=b.sprint)
        merge = self.remote.merge_in(message)
        if merge.outcome is MergeOutcome.CONFLICT:
            files = list(merge.files)
            return self._hold(b, BoundaryHold.SYNC_CONFLICT, Out.CONFLICT, files=files)
        self._emit(b, Out(merge.outcome), **({"sha": merge.sha} if merge.sha else {}))
        self._advance(b)

    def _end_sync(self, b: Boundary) -> None:
        self._add_entry(b)
        self._emit(b, Out.PASS, note=f"sprint {b.sprint} is on the review stack")
        self._advance(b)

    def _add_entry(self, b: Boundary) -> None:
        self.mine.team_branch = self.mine.team_branch or self.remote.team_branch()
        start = self.mine.last_end or self.remote.merge_base()
        if self.runtime.git.head() == start or any(e.sprint == b.sprint for e in self.stack):
            return
        self.stack.append(self._entry(b, start))
        self.mine.last_end = self.runtime.git.head()

    def _entry(self, b: Boundary, start: str) -> StackEntry:
        state = self.runtime.state
        branch = f"{self.runtime.config.upstream.prefix}{b.sprint}"
        done = [s.id for s in state.stories.values() if s.sprint == b.sprint]
        title = SPRINT_TITLE.format(sprint=b.sprint, goal=state.goal)
        return StackEntry(b.sprint, branch, start, self.runtime.git.head(), title, done)

    def _drop_merged(self, b: Boundary) -> None:
        if not self.stack:
            return
        unmerged = self.rebuilder.unmerged(self.stack[-1].end)
        gone = [e for e in self.stack if not self.rebuilder.picks(e, unmerged)]
        for entry in gone:
            self._drop(b, entry)
        if gone and self.stack and b.edge is Edge.START:
            b.restack = True

    def _drop(self, b: Boundary, entry: StackEntry) -> None:
        self.stack.remove(entry)
        self._emit(b, Out.MERGED, note=MERGED_NOTE.format(sprint=entry.sprint, target=self.target))

    # ----- check

    def _run_checks(self, path: Path) -> CheckReport:
        required = self.runtime.pipeline.checks.required_coverage()
        judging = Judging(self.runtime.shell(path), required)
        return run_checks(full_checks(self.runtime.config), judging)

    def _check(self, b: Boundary) -> None:
        head = self.runtime.git.head()
        if self.mine.checked == head:
            self._emit(b, Out.PASS, note=f"already checked at {head}")
            return self._advance(b)
        report = self._run_checks(self.runtime.config.repo)
        if not report.passed:
            failure = Failure(Stage.CHECK, FixCase.TEAM_CHECK, report.reason())
            return self._fail(b, failure, checks=report.summary())
        self.mine.checked = head
        self._emit(b, Out.PASS, checks=report.summary())
        self._advance(b)

    def _fail(self, b: Boundary, failure: Failure, **data: Any) -> None:
        found = setback(b, failure)
        count = loops.repeats(b.streak, found) + 1
        history = [asdict(s) for s in b.streak]
        pipeline = self.runtime.pipeline
        escalate = count >= pipeline.repeat or b.rounds >= pipeline.cap
        b.failure = failure
        outcome = Out.ESCALATE if escalate else Out.FAIL
        event = self._emit(
            b, outcome, reason=failure.reason, key=found.key, count=count, history=history, **data
        )
        b.streak = loops.extend(b.streak, replace(found, event=event.id))
        if escalate:
            self._escalate(b, failure)

    def _escalate(self, b: Boundary, failure: Failure) -> None:
        b.hold, b.escalated = BoundaryHold.ESCALATED, failure.reason
        count = len(b.streak)
        due = BOUNDARY_DUE.format(sprint=b.sprint, edge=b.edge, count=count, stage=failure.stage)
        self.runtime.state.manager_due.append(due)
        self.last.data["hold"] = b.hold  # type: ignore[union-attr]

    # ----- review

    def _review(self, b: Boundary) -> None:
        self._include_fixes(b)
        self.rebuilder.prepare()
        conflict = self._build_all(b) if self.stack else None
        failure = self._conflict_failure(conflict) if conflict else self._check_ends()
        if failure:
            return self._fail(b, failure)
        self._emit(b, Out.BUILT, branches=[e.branch for e in self.stack])
        self._advance(b)

    def _include_fixes(self, b: Boundary) -> None:
        top = self.stack[-1] if self.stack else None
        if b.edge is Edge.END and top and top.sprint == b.sprint:
            top.end = self.mine.last_end = self.runtime.git.head()

    def _build_all(self, b: Boundary) -> Conflict | None:
        unmerged = self.rebuilder.unmerged(self.stack[-1].end)
        base = self.target
        for entry in list(self.stack):
            conflict = self._build_one(b, entry, Build(base, self.rebuilder.picks(entry, unmerged)))
            if conflict:
                return conflict
            base = entry.head if entry in self.stack else base
        return None

    def _build_one(self, b: Boundary, entry: StackEntry, source: Build) -> Conflict | None:
        conflict = self.rebuilder.build(entry, source) if source.picks else None
        if conflict is None and (not source.picks or entry.head == source.base):
            self._drop(b, entry)
        return conflict

    def _conflict_failure(self, c: Conflict) -> Failure:
        case, files = FixCase.REVIEW_CONFLICT, list(c.files)
        return Failure(Stage.REVIEW, case, c.output, c.branch, files, c.commit, c.subject)

    def _check_ends(self) -> Failure | None:
        ends = [*self.stack[:1], *self.stack[1:][-1:]]
        failed = [self._check_entry(e) for e in ends]
        return next((f for f in failed if f), None)

    def _check_entry(self, entry: StackEntry) -> Failure | None:
        if entry.checked == entry.head:
            return None
        self.rebuilder.checkout(entry.branch)
        report = self._run_checks(self.rebuilder.worktree)
        entry.check = CheckState.PASS if report.passed else CheckState.FAIL
        if report.passed:
            entry.checked = entry.head
            return None
        return Failure(Stage.REVIEW, FixCase.REVIEW_CHECK, report.reason(), entry.branch)

    # ----- push

    def _push(self, b: Boundary) -> None:
        if not self.stack:
            return self._finish(b, NOTHING_REPORT.format(target=self.target))
        why = self.runtime.prs.missing()
        if why:
            return self._local(b, why)
        if self.mine.push is Permission.UNASKED:
            branches = [e.branch for e in self.stack]
            return self._hold(b, BoundaryHold.PUSH_PERMISSION, Out.HELD, branches=branches)
        if self.mine.push is Permission.NO:
            return self._local(b, NOT_PERMITTED)
        self._push_all(b)

    def _local(self, b: Boundary, why: str) -> None:
        branches = ", ".join(e.branch for e in self.stack)
        text = LOCAL_REPORT.format(sprint=b.sprint, why=why, branches=branches)
        self._emit(b, Out.LOCAL, note=why)
        self._post(text)
        self._finish(b, text)

    def _push_all(self, b: Boundary) -> None:
        for entry, below in zip(self.stack, [None, *self.stack], strict=False):
            rejected = self._push_entry(entry, below)
            if rejected is not None:
                fields = {"branch": entry.branch, "reason": rejected}
                return self._hold(b, BoundaryHold.PUSH_REJECTED, Out.HELD, **fields)
        self._pushed(b)

    def _pushed(self, b: Boundary) -> None:
        prs = "; ".join(f"#{e.pr} ({e.mode}, {e.branch}) {e.url}" for e in self.stack if e.pr)
        text = PUSHED_REPORT.format(sprint=b.sprint, prs=prs)
        self._emit(b, Out.PUSHED, branches=[e.branch for e in self.stack])
        self._post(text)
        self._finish(b, text)

    def _push_entry(self, entry: StackEntry, below: StackEntry | None) -> str | None:
        if entry.pushed != entry.head:
            out = self.remote.push(Lease(entry.branch, entry.pushed))
            if out is not None:
                return out
            entry.pushed = entry.head
        self._pr(entry, below)
        return None

    def _pr(self, entry: StackEntry, below: StackEntry | None) -> None:
        prs, spec = self.runtime.prs, self._spec(entry, below)
        pr = prs.find(entry.branch)
        if pr is None:
            pr = prs.create(spec)
        elif pr.state is PrState.OPEN:
            self._edit(pr, spec)
        else:
            return self._leave(entry, pr.number, pr.state)
        entry.pr, entry.url, entry.base, entry.mode = pr.number, pr.url, spec.base, spec.mode

    def _edit(self, pr: Pr, spec: PrSpec) -> None:
        """Edit only a PR that differs from the spec."""
        wants_draft = spec.mode is PrMode.DRAFT
        if pr.base != spec.base or pr.draft != wants_draft:
            self.runtime.prs.edit(pr, spec)

    def _leave(self, entry: StackEntry, number: int, state: PrState) -> None:
        entry.mode = PrMode.CLOSED
        note = CLOSED_NOTE.format(pr=number, sprint=entry.sprint, state=str(state).lower())
        self._emit(self.runtime.state.boundary, Out.CURRENT, note=note)  # type: ignore[arg-type]

    def _spec(self, entry: StackEntry, below: StackEntry | None) -> PrSpec:
        if below is None:
            base, mode, stacked = self.runtime.config.upstream.branch, PrMode.READY, ""
        else:
            base, mode = below.branch, PrMode.DRAFT
            stacked = STACKED_LINE.format(base=below.branch, base_pr=below.pr)
        return PrSpec(entry.branch, base, entry.title, self._body(entry, stacked), mode)

    def _body(self, entry: StackEntry, stacked: str) -> str:
        titles = self.runtime.state.stories
        lines = [f"- {i}: {titles[i].title if i in titles else i}" for i in entry.stories]
        return PR_BODY.format(
            sprint=entry.sprint,
            stories="\n".join(lines),
            stacked=stacked,
            team=self.mine.team_branch,
            target=self.target,
        )


STAGE_RUNNERS = {
    Stage.SYNC: BoundaryRunner._sync,
    Stage.CHECK: BoundaryRunner._check,
    Stage.REVIEW: BoundaryRunner._review,
    Stage.PUSH: BoundaryRunner._push,
}
SYNCS = {Edge.START: BoundaryRunner._merge_in, Edge.END: BoundaryRunner._end_sync}

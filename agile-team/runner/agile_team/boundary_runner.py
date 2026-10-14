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

from . import halt, handover, loops, pending_tests, revert_log, rewrite, stages
from .boundary import (
    BOUNDARY_DUE,
    BOUNDARY_ROLE,
    CLOSED_NOTE,
    FIX_KINDS,
    FIX_ROLE,
    LOCAL_REPORT,
    MERGED_NOTE,
    NOT_PERMITTED,
    NOTHING_REPORT,
    PR_BODY,
    PR_KIND,
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
    big_pr_notes,
    fix_brief,
    next_stage,
    setback,
)
from .ci import (
    CI_NONE_REPORT,
    CI_RED_REPORT,
    CI_TIMEOUT,
    NO_CHECKS_WHY,
    NO_OPEN_PR_WHY,
    CiResult,
    CiVerdict,
    CiWatch,
    UpstreamError,
    check_lines,
    green_report,
    overall,
    prs_text,
)
from .events import Event, EventKind
from .fullcheck import CheckReport, Judging, full_checks, run_checks
from .relay import Note
from .restack import Plan, Restacker
from .stack import REVIEW_DIR, Build, Conflict, Rebuilder
from .upstream import Lease, Pr, PrSpec, PrState, Rebase, SyncOutcome, Upstream

if TYPE_CHECKING:
    from .dispatch import Runtime

Out = BoundaryOutcome
FETCH_PREFIX = "git fetch "
START_NOTES = {
    False: "the team branch is current with {target}",
    True: (
        "{target} moved {count} commits since the last sprint-end rebase; "
        "nothing changes until the next sprint end"
    ),
}
NOTHING_TO_PUSH = "no review branch to push"
NOTHING_TO_RESTACK = "no review branch to restack"


def fetch_failed(why: str) -> bool:
    """Whether a skip reason is the fetch failing."""
    return why.startswith(FETCH_PREFIX)


def fix_hold(report: dict[str, Any]) -> BoundaryHold | None:
    """``fix_handover`` when the fix's report raises a handover trigger, else ``None``."""
    return BoundaryHold.FIX_HANDOVER if handover.triggers(report) else None


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
    restacker: Restacker = field(init=False)
    watch: CiWatch = field(init=False)

    def __post_init__(self) -> None:
        rt = self.runtime
        self.watch = CiWatch(rt.prs, rt.config.gates.ci_timeout_s)
        worktree = rt.config.run_dir / REVIEW_DIR
        self.rebuilder = Rebuilder(rt.git, worktree, self.remote.target)
        self.restacker = Restacker(rt.prs, self.rebuilder)

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
        """Open the end boundary when the sprint is finished (E1) and it has not run."""
        state = self.runtime.state
        if state.boundary or not state.sprint_complete() or self.mine.closed >= state.sprint:
            return False
        state.boundary = Boundary(Edge.END, state.sprint)
        return True

    def step(self) -> dict[str, Any]:
        """Run the current stage once, as a chore on the heartbeat."""
        stage = self.runtime.state.boundary.stage  # type: ignore[union-attr]
        chore = self.runtime.pulse.doing(f"sprint boundary: {stage}")
        with chore, self.runtime.stage_log.open(stages.BOUNDARY[stage]):
            return self._step()

    def _step(self) -> dict[str, Any]:
        """Run the current stage; any exception holds the boundary as an error."""
        b = self.runtime.state.boundary
        try:
            STAGE_RUNNERS[b.stage](self, b)  # type: ignore[union-attr]
        except Exception as exc:
            self._error(b, exc)  # type: ignore[arg-type]
        self.runtime.save()
        data = self.last.data  # type: ignore[union-attr]
        return {"role": BOUNDARY_ROLE, "status": "boundary", "boundary": data}

    def after_fix(self, report: dict[str, Any]) -> None:
        """A devops fix is back: record any resolution, count the round, hold on handover, rerun."""
        b = self.runtime.state.boundary
        if b is None or report.get("status") == "halted":
            return
        failure = b.failure
        if failure and failure.case is FixCase.REVIEW_CONFLICT:
            self.rebuilder.record(failure.files)
        b.rounds, b.failure, b.note = b.rounds + 1, None, ""
        b.hold = fix_hold(report)
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

    def _finish(self, b: Boundary, report: str = "", **data: Any) -> None:
        self._close(b, report)
        self._emit(b, Out.DONE, **data)

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
        SYNCS[b.edge](self, b)

    def _skip(self, b: Boundary, why: str) -> None:
        if b.edge is Edge.END and fetch_failed(why):
            self._add_entry(b)
        self._emit(b, Out.SKIPPED, note=why)
        self._close(b, SKIPPED_REPORT.format(why=why))

    def _start_sync(self, b: Boundary) -> None:
        """Report how far the target moved; change nothing (the next sprint end rebases)."""
        behind = self.remote.behind()
        note = START_NOTES[behind > 0].format(target=self.remote.target, count=behind)
        self._emit(b, Out.PASS, note=note, behind=behind)
        self._advance(b)

    def _rebase(self, b: Boundary) -> None:
        self._fetch()
        self._pin_sync_from(b)
        result = self.remote.rebase_onto(b.sync_from)
        AFTER_REBASE[result.outcome](self, b, result)

    def _pin_sync_from(self, b: Boundary) -> None:
        """R2: pin the pre-rebase HEAD once and save it, so a crash cannot lose the old hashes."""
        if b.sync_from:
            return
        b.sync_from = self.runtime.git.head()
        self.runtime.save()

    def _rebase_conflict(self, b: Boundary, result: Rebase) -> None:
        data = {"files": list(result.files), "commit": result.commit[:12]}
        self._hold(b, BoundaryHold.SYNC_CONFLICT, Out.CONFLICT, subject=result.subject, **data)

    def _rebase_current(self, b: Boundary, result: Rebase) -> None:
        self._emit(b, Out.CURRENT)
        self._unpin(b)
        self._advance(b)

    def _unpin(self, b: Boundary) -> None:
        b.sync_from = ""
        self.runtime.save()

    def _settle_rebase(self, b: Boundary, result: Rebase) -> None:
        count = rewrite.remap_state(self.runtime.state, result.moved)
        self.runtime.record_checkout()
        self.runtime.save()
        self._emit(b, Out.REBASED, sha=result.sha, rewritten=count)
        self._unpin(b)
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
        head = self.runtime.git.head()
        return StackEntry(b.sprint, branch, start, head, title, done, reverted=self._reverted(b))

    def _reverted(self, b: Boundary) -> list[str]:
        """R12: ids of stories with a revert in sprint ``b``."""
        stories = self.runtime.state.stories
        return [i for i, s in stories.items() if any(e.sprint == b.sprint for e in s.reverted)]

    def _drop(self, b: Boundary, entry: StackEntry) -> None:
        self.stack.remove(entry)
        self._emit(b, Out.MERGED, note=MERGED_NOTE.format(sprint=entry.sprint, target=self.target))

    # ----- check

    def _run_checks(self, path: Path) -> CheckReport:
        required = self.runtime.pipeline.checks.required_coverage()
        judging = Judging(self.runtime.shell(path), required)
        return run_checks(full_checks(self.runtime.config, pending_tests.read(path)), judging)

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
        conflict = self._build_from(b, self._first_build(b))
        failure = self._conflict_failure(conflict) if conflict else self._check_ends()
        if failure:
            return self._fail(b, failure)
        self._emit(b, Out.BUILT, branches=[e.branch for e in self.stack])
        self._advance(b)

    def _include_fixes(self, b: Boundary) -> None:
        top = self.stack[-1] if self.stack else None
        if b.edge is Edge.END and top and top.sprint == b.sprint:
            top.end = self.mine.last_end = self.runtime.git.head()

    def _first_build(self, b: Boundary) -> int:
        """Index of the first entry to build: all after a refused restack, else the sprint's own."""
        top = self.stack[-1] if self.stack else None
        if b.restack:
            return 0
        return len(self.stack) - 1 if top and top.sprint == b.sprint else len(self.stack)

    def _build_from(self, b: Boundary, first: int) -> Conflict | None:
        if first >= len(self.stack):
            return None
        unmerged = self.rebuilder.unmerged(self.stack[-1].end)
        base = self.stack[first - 1].head if first else self.target
        for entry in list(self.stack[first:]):
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
            return self._pass(b, NOTHING_TO_PUSH)
        why = self.runtime.prs.missing()
        if why:
            return self._local_event(b, why)
        if self.mine.push is Permission.UNASKED:
            branches = [e.branch for e in self.stack]
            return self._hold(b, BoundaryHold.PUSH_PERMISSION, Out.HELD, branches=branches)
        if self.mine.push is Permission.NO:
            return self._local_event(b, NOT_PERMITTED)
        self._push_own(b)

    def _pass(self, b: Boundary, note: str) -> None:
        self._emit(b, Out.PASS, note=note)
        self._advance(b)

    def _local_event(self, b: Boundary, why: str) -> None:
        self._emit(b, Out.LOCAL, note=why, ci=CiVerdict.NONE)
        self._advance(b)

    def _push_own(self, b: Boundary) -> None:
        """Push the sprint's own review branch (step 1 of the sprint end); no PR call."""
        top = self.stack[-1]
        if top.sprint != b.sprint:
            return self._pass(b, NOTHING_TO_PUSH)
        rejected = self._push_branch(top)
        if rejected is not None:
            return self._reject(b, top, rejected)
        self._pass(b, f"pushed {top.branch}")

    def _push_branch(self, entry: StackEntry) -> str | None:
        """Push the entry's branch when it moved; the refusal text, or ``None``."""
        if entry.pushed == entry.head:
            return None
        out = self.remote.push(Lease(entry.branch, entry.pushed))
        if out is None:
            entry.pushed = entry.head
        return out

    def _reject(self, b: Boundary, entry: StackEntry, reason: str) -> None:
        fields = {"branch": entry.branch, "reason": reason}
        self._hold(b, BoundaryHold.PUSH_REJECTED, Out.HELD, **fields)

    def _push_stack(self, b: Boundary) -> bool:
        """Push and retarget every entry; hold ``push_rejected`` and return False on a refusal."""
        for entry, below in zip(self.stack, [None, *self.stack], strict=False):
            rejected = self._push_entry(entry, below)
            if rejected is not None:
                self._reject(b, entry, rejected)
                return False
        return True

    def _with_big(self, text: str) -> str:
        """``text`` followed by one fast-forward note per PR too big for "Rebase and merge"."""
        return "\n".join([text, *big_pr_notes(self.stack, self.runtime.config.upstream)])

    # ----- restack

    def _fetch(self) -> None:
        why = self.remote.missing()
        if why:
            raise UpstreamError(why)

    def _local_why(self) -> str:
        """Why the boundary delivers nothing: no gh, or no permission; empty when it delivers."""
        if why := self.runtime.prs.missing():
            return why
        return "" if self.mine.push is Permission.YES else NOT_PERMITTED

    def _restack(self, b: Boundary) -> None:
        """Steps 3-4: drop merged parents, rebase the rest onto the target, push, retarget."""
        if not self.stack:
            return self._pass(b, NOTHING_TO_RESTACK)
        gone = [] if self._local_why() else self.restacker.merged(self.stack)
        if gone:
            self._fetch()
        below = gone[-1].head if gone else self.rebuilder.merge_base(self.stack[0].head)
        rest = self.stack[len(gone) :]
        for entry in gone:
            self._drop(b, entry)
        plan = self.restacker.plan(rest, below)
        self._settle_plan(b, plan)

    def _settle_plan(self, b: Boundary, plan: Plan) -> None:
        if plan.refused:
            return self._rebuild(b, plan.refused)
        self._apply(b, plan)
        self._deliver(b)

    def _rebuild(self, b: Boundary, why: str) -> None:
        self._emit(b, Out.REBUILD, note=why)
        b.restack, b.stage = True, Stage.REVIEW

    def _apply(self, b: Boundary, plan: Plan) -> None:
        moved = [e.branch for e, h in zip(self.stack, plan.heads, strict=True) if e.head != h]
        for entry, head in zip(list(self.stack), plan.heads, strict=True):
            if entry.branch in plan.emptied:
                self._drop(b, entry)
            else:
                self._move(entry, head)
        self._emit(b, Out.RESTACKED, branches=moved)

    def _move(self, entry: StackEntry, head: str) -> None:
        if entry.checked == entry.head:
            entry.checked = head
        self.rebuilder.point(entry, head)

    def _deliver(self, b: Boundary) -> None:
        if not self.stack:
            return self._advance(b)
        why = self._local_why()
        if why:
            return self._finish_local(b, why)
        if self._push_stack(b):
            self._pushed(b)

    def _finish_local(self, b: Boundary, why: str) -> None:
        branches = ", ".join(e.branch for e in self.stack)
        text = LOCAL_REPORT.format(sprint=b.sprint, why=why, branches=branches)
        self._post(text)
        self._finish(b, text)

    def _pushed(self, b: Boundary) -> None:
        kinds = ((e, PR_KIND[e.mode]) for e in self.stack if e.pr)
        prs = "; ".join(f"#{e.pr} ({kind}, {e.branch}) {e.url}" for e, kind in kinds)
        self._post(self._with_big(PUSHED_REPORT.format(sprint=b.sprint, prs=prs)))
        self._advance(b)

    # ----- ci

    def _watched(self) -> list[StackEntry]:
        return [e for e in self.stack if e.mode is PrMode.READY and e.pr]

    def _ci(self, b: Boundary) -> None:
        if not self.stack:
            return self._finish(b, NOTHING_REPORT.format(target=self.target))
        watched = self._watched()
        results = self.watch.results(watched)
        for entry, result in zip(watched, results, strict=True):
            entry.ci = result
        CI_OUTCOMES[overall(results)](self, b, results)

    def _ci_green(self, b: Boundary, results: list[CiResult]) -> None:
        text = self._with_big(green_report(b.sprint, results))
        self._finish(b, text, ci=CiVerdict.GREEN, **_ci_fields(results))

    def _ci_red(self, b: Boundary, results: list[CiResult]) -> None:
        self._hold(b, BoundaryHold.CI_FAILED, Out.HELD, ci=CiVerdict.RED, **_ci_fields(results))

    def _ci_pending(self, b: Boundary, results: list[CiResult]) -> None:
        reason = CI_TIMEOUT.format(limit=self.watch.limit_s)
        fields = {"ci": CiVerdict.PENDING, "reason": reason, **_ci_fields(results)}
        self._hold(b, BoundaryHold.CI_PENDING, Out.HELD, **fields)

    def _ci_none(self, b: Boundary, results: list[CiResult]) -> None:
        why = NO_CHECKS_WHY if results else NO_OPEN_PR_WHY
        prs = prs_text(results) or ", ".join(e.branch for e in self.stack)
        text = self._with_big(CI_NONE_REPORT.format(sprint=b.sprint, prs=prs, why=why))
        self._post(text)
        self._finish(b, text, ci=CiVerdict.NONE, note=why, **_ci_fields(results))

    def settle_bug(self, story: str) -> None:
        """Close a boundary held on failed CI with its bug story recorded."""
        b = self.runtime.state.boundary
        self.mine.ci_bug = story
        red = [e.ci for e in self.stack if e.ci and e.ci.verdict is CiVerdict.RED]
        text = CI_RED_REPORT.format(sprint=b.sprint, story=story, prs=prs_text(red))  # type: ignore[union-attr,arg-type]
        self._finish(b, text, ci=CiVerdict.RED, story=story, note=text)  # type: ignore[arg-type]
        self.runtime.save()

    def _push_entry(self, entry: StackEntry, below: StackEntry | None) -> str | None:
        out = self._push_branch(entry)
        if out is not None:
            return out
        base = below.head if below else self.target
        entry.commits = self.rebuilder.count(base, entry.head)
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
            base, mode = below.branch, PrMode.READY
            stacked = STACKED_LINE.format(base=below.branch, base_pr=below.pr)
        return PrSpec(entry.branch, base, entry.title, self._body(entry, stacked), mode)

    def _reverted_lines(self, entry: StackEntry) -> list[str]:
        stories = self.runtime.state.stories
        return [
            revert_log.pr_line(f"{i}: {stories[i].title}", e)
            for i in entry.reverted
            for e in stories[i].reverted
            if e.sprint == entry.sprint
        ]

    def _body(self, entry: StackEntry, stacked: str) -> str:
        titles = self.runtime.state.stories
        lines = [f"- {i}: {titles[i].title if i in titles else i}" for i in entry.stories]
        return PR_BODY.format(
            sprint=entry.sprint,
            stories="\n".join(lines),
            reverted=revert_log.pr_section(self._reverted_lines(entry)),
            stacked=stacked,
            team=self.mine.team_branch,
            target=self.target,
        )


def _ci_fields(results: list[CiResult]) -> dict[str, Any]:
    return {
        "prs": prs_text(results),
        "checks": check_lines(results),
        "results": [asdict(r) for r in results],
    }


CI_OUTCOMES = {
    CiVerdict.GREEN: BoundaryRunner._ci_green,
    CiVerdict.RED: BoundaryRunner._ci_red,
    CiVerdict.PENDING: BoundaryRunner._ci_pending,
    CiVerdict.NONE: BoundaryRunner._ci_none,
}
STAGE_RUNNERS = {
    Stage.SYNC: BoundaryRunner._sync,
    Stage.CHECK: BoundaryRunner._check,
    Stage.REVIEW: BoundaryRunner._review,
    Stage.PUSH: BoundaryRunner._push,
    Stage.REBASE: BoundaryRunner._rebase,
    Stage.RESTACK: BoundaryRunner._restack,
    Stage.CI: BoundaryRunner._ci,
}
AFTER_REBASE = {
    SyncOutcome.CONFLICT: BoundaryRunner._rebase_conflict,
    SyncOutcome.CURRENT: BoundaryRunner._rebase_current,
    SyncOutcome.REBASED: BoundaryRunner._settle_rebase,
}
SYNCS = {Edge.START: BoundaryRunner._start_sync, Edge.END: BoundaryRunner._end_sync}

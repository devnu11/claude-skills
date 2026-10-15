"""Runs a sprint boundary one stage at a time.

The stages: sync, check, push as built, ci, rebase, push rebased, ci rebased.

The router asks ``due`` for the next unit of work, runs a stage with ``step`` or
a devops fix with ``run_role``, and calls ``after_fix`` when the fix is back.
All git access goes through ``runtime.upstream`` and ``runtime.prs``; checks run
through ``runtime.shell``. Only the rebase stage rewrites the team branch, through ``Upstream``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import halt, handover, loops, pending_tests, repin, revert_log, rewrite, stages
from .boundary import (
    BOUNDARY_DUE,
    BOUNDARY_ROLE,
    CI_RED_HELD,
    CLOSED_NOTE,
    FIX_KINDS,
    FIX_ROLE,
    LOCAL_REPORT,
    NOT_PERMITTED,
    NOT_REBASED,
    NOTHING_NEW,
    PR_BODY,
    PUSHED_REPORT,
    REBASE_UNCHANGED,
    REBASED_NOT_GREEN,
    REBASED_PUSHED_REPORT,
    SKIPPED_REPORT,
    SPRINT_TITLE,
    SUPERSEDED_NOTE,
    SUPERSEDES_LINE,
    Boundary,
    BoundaryHold,
    BoundaryOutcome,
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
    own_entry,
    rebase_refusal,
    setback,
)
from .ci import (
    CI_MAIN_REPORT,
    CI_NONE_REPORT,
    CI_RED_REPORT,
    CI_STALE,
    CI_TIMEOUT,
    NO_CHECKS_WHY,
    NO_OPEN_PR_WHY,
    Check,
    CheckKind,
    CiResult,
    CiVerdict,
    CiWatch,
    UpstreamError,
    check_lines,
    green_report,
    kind_or_bucket,
    label,
    overall,
    prs_text,
    rerun_due,
)
from .ci_triage import rerun_key
from .events import Event, EventKind
from .fullcheck import CheckReport, Judging, full_checks, run_checks
from .relay import Note
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
    watch: CiWatch = field(init=False)

    def __post_init__(self) -> None:
        rt = self.runtime
        self.watch = CiWatch(rt.prs, rt.config.gates.ci_timeout_s, rt.config.upstream.branch)

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
        return self.remote.target

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
        return FixContext(self.mine.team_branch, self.target, self.runtime.git.head())

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

    def _own(self, b: Boundary) -> StackEntry | None:
        return own_entry(self.stack, b.sprint)

    def _end_sync(self, b: Boundary) -> None:
        self._add_entry(b)
        own = self._own(b)
        if own is None:
            text = NOTHING_NEW.format(sprint=b.sprint)
            return self._finish(b, text, note=text)
        self._supersede(b, own)
        self._emit(b, Out.PASS, note=f"sprint {b.sprint} is the sprint PR")
        self._advance(b)

    def _supersede(self, b: Boundary, own: StackEntry) -> None:
        """R2: older entries leave the stack; their open PRs are named in the own entry."""
        for old in [e for e in self.stack if e is not own]:
            self.stack.remove(old)
            if old.pr and old.mode is not PrMode.CLOSED:
                own.supersedes.append(old.pr)
            note = SUPERSEDED_NOTE.format(old=old.sprint, pr=old.pr, sprint=b.sprint)
            self._emit(b, Out.SUPERSEDED, note=note)

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

    # ----- check

    def _run_checks(self, path: Path) -> CheckReport:
        required = self.runtime.pipeline.checks.required_coverage()
        judging = Judging(self.runtime.shell(path), required)
        return run_checks(full_checks(self.runtime.config, pending_tests.read(path)), judging)

    def _check(self, b: Boundary) -> None:
        head = self.runtime.git.head()
        if self.mine.checked == head:
            self._emit(b, Out.PASS, note=f"already checked at {head}")
            self._advance(b)
            return self._repin_due(b, head)
        report = self._run_checks(self.runtime.config.repo)
        if not report.passed:
            failure = Failure(Stage.CHECK, FixCase.TEAM_CHECK, report.reason())
            return self._fail(b, failure, checks=report.summary())
        self.mine.checked = head
        self._emit(b, Out.PASS, checks=report.summary())
        self._advance(b)
        self._repin_due(b, head)

    def _repin_due(self, b: Boundary, head: str) -> None:
        """P2: a passing end check on a pinned runner asks to re-pin to the checked head."""
        if b.edge is Edge.END and repin.due(self.runtime.config.run_dir, head):
            self.runtime.state.repin = head

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

    # ----- push (as built)

    def _push(self, b: Boundary) -> None:
        why = self.runtime.prs.missing()
        if why:
            return self._finish_local(b, why)
        own = self._own(b)
        if self.mine.push is Permission.UNASKED:
            return self._hold(b, BoundaryHold.PUSH_PERMISSION, Out.HELD, branches=[own.branch])  # type: ignore[union-attr]
        if self.mine.push is Permission.NO:
            return self._finish_local(b, NOT_PERMITTED)
        self._push_as_is(b, own)  # type: ignore[arg-type]

    def _push_as_is(self, b: Boundary, own: StackEntry) -> None:
        """R3: push the team branch as it is, then open or reuse the sprint PR."""
        own.head = own.end = self.mine.last_end = self.runtime.git.head()
        rejected = self._push_branch(own)
        if rejected is not None:
            return self._reject(b, own, rejected)
        own.as_is = own.pushed
        self._open_pr(own)
        self._report_pushed(b, own)
        self._advance(b)

    def _report_pushed(self, b: Boundary, own: StackEntry) -> None:
        if own.mode is PrMode.READY:
            fields = {"sprint": b.sprint, "branch": own.branch, "sha": own.pushed}
            fields |= {"pr": own.pr, "url": own.url, "target": self.target}
            self._post(self._with_big(PUSHED_REPORT.format(**fields)))
        self._emit(b, Out.PUSHED, branch=own.branch, sha=own.pushed, as_is=own.as_is)

    def _push_branch(self, entry: StackEntry) -> str | None:
        """Push the entry's head when it moved; the refusal text, or ``None``."""
        if entry.pushed == entry.head:
            return None
        out = self.remote.push(Lease(entry.branch, entry.pushed, entry.head))
        if out is None:
            entry.pushed = entry.head
            entry.commits = self.remote.count(entry.head)
        return out

    def _reject(self, b: Boundary, entry: StackEntry, reason: str) -> None:
        fields = {"branch": entry.branch, "reason": reason}
        self._hold(b, BoundaryHold.PUSH_REJECTED, Out.HELD, **fields)

    def _with_big(self, text: str) -> str:
        """``text`` followed by one fast-forward note per PR too big for "Rebase and merge"."""
        return "\n".join([text, *big_pr_notes(self.stack, self.runtime.config.upstream)])

    def _finish_local(self, b: Boundary, why: str) -> None:
        """R4: no gh or no permission; the branch is checked, nothing is pushed or rebased."""
        branch = self._own(b).branch  # type: ignore[union-attr]
        text = LOCAL_REPORT.format(sprint=b.sprint, branch=branch, why=why) + self._not_rebased()
        self._post(text)
        self._finish(b, text, ci=CiVerdict.NONE, note=why)

    def _not_rebased(self) -> str:
        return NOT_REBASED.format(target=self.target)

    # ----- rebase

    def _fetch(self) -> None:
        why = self.remote.missing()
        if why:
            raise UpstreamError(why)

    def _rebase(self, b: Boundary) -> None:
        """R6, R7: refuse unless the as-built push has green CI, else rebase onto the target."""
        refusal = rebase_refusal(self._own(b))
        if refusal:
            return self._refuse_rebase(b, refusal)
        self._fetch()
        self._pin_sync_from(b)
        result = self.remote.rebase_onto(b.sync_from)
        AFTER_REBASE[result.outcome](self, b, result)

    def _refuse_rebase(self, b: Boundary, reason: str) -> None:
        b.stage = Stage.CI
        self._hold(b, BoundaryHold.ERROR, Out.REFUSED, reason=reason)

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

    # ----- push rebased

    def _push_rebased(self, b: Boundary) -> None:
        """R8: push the rebased head with the lease on the as-built sha; nothing if unchanged."""
        own, head = self._own(b), self.runtime.git.head()
        if head == own.pushed:  # type: ignore[union-attr]
            return self._unchanged(b, own)  # type: ignore[arg-type]
        own.head = head  # type: ignore[union-attr]
        rejected = self._push_branch(own)  # type: ignore[arg-type]
        if rejected is not None:
            return self._reject(b, own, rejected)  # type: ignore[arg-type]
        self._report_rebased(b, own)  # type: ignore[arg-type]
        self._advance(b)

    def _unchanged(self, b: Boundary, own: StackEntry) -> None:
        note = REBASE_UNCHANGED.format(branch=own.branch, sha=own.pushed)
        self._emit(b, Out.PASS, note=note)
        self._ready(b, [own.ci] if own.ci else [])

    def _report_rebased(self, b: Boundary, own: StackEntry) -> None:
        fields = {"sprint": b.sprint, "pr": own.pr, "target": self.target}
        fields |= {"sha": own.pushed, "as_is": own.as_is}
        self._post(REBASED_PUSHED_REPORT.format(**fields))
        self._emit(b, Out.PUSHED, branch=own.branch, sha=own.pushed, as_is=own.as_is)

    # ----- ci

    def _watched(self, b: Boundary) -> list[StackEntry]:
        own = self._own(b)
        return [own] if own and own.mode is PrMode.READY and own.pr else []

    def _read_ci(self, b: Boundary) -> list[CiResult]:
        watched = self._watched(b)
        results = self.watch.results(watched)
        for entry, result in zip(watched, results, strict=True):
            entry.ci = result
        return results

    def _ci(self, b: Boundary) -> None:
        results = self._read_ci(b)
        CI_OUTCOMES[overall(results)](self, b, results)

    def _ci_green(self, b: Boundary, results: list[CiResult]) -> None:
        self._emit(b, Out.PASS, ci=CiVerdict.GREEN, **_ci_fields(results))
        self._advance(b)

    def _ready(self, b: Boundary, results: list[CiResult]) -> None:
        text = self._with_big(green_report(b.sprint, results))
        self._finish(b, text, ci=CiVerdict.GREEN, **_ci_fields(results))

    def _ci_red(self, b: Boundary, results: list[CiResult]) -> None:
        self._hold(b, BoundaryHold.CI_FAILED, Out.HELD, ci=CiVerdict.RED, **_ci_fields(results))
        fields = {"sprint": b.sprint, "prs": prs_text(results), "checks": check_lines(results)}
        self._post(CI_RED_HELD.format(**fields))

    def _ci_infra(self, b: Boundary, results: list[CiResult]) -> None:
        due = rerun_due(self._watched(b))
        if not due:
            return self._hold(
                b, BoundaryHold.CI_INFRA, Out.HELD, ci=CiVerdict.INFRA, **_ci_fields(results)
            )
        self._rerun(b, due)

    def _rerun(self, b: Boundary, due: list[tuple[StackEntry, Check]]) -> None:
        """Use each job's one re-run at this head, then look for the new attempt."""
        for entry, check in due:
            entry.reran.append(rerun_key(entry.head, label(check)))
            check.kind = CheckKind.RERUN
        self.runtime.save()
        self._emit(b, Out.RERUN, jobs=[label(c) for _, c in due])
        for entry, check in due:
            self.watch.rerun(entry.pr or 0, check)

    def _ci_main(self, b: Boundary, results: list[CiResult]) -> None:
        fields = {"ci": CiVerdict.MAIN, "target": self.watch.target, **_ci_fields(results)}
        self._hold(b, BoundaryHold.MAIN_BROKEN, Out.HELD, **fields)

    def _ci_pending(self, b: Boundary, results: list[CiResult]) -> None:
        stale = any(kind_or_bucket(c) is CheckKind.STALE for r in results for c in r.checks)
        reason = CI_STALE if stale else CI_TIMEOUT.format(limit=self.watch.limit_s)
        fields = {"ci": CiVerdict.PENDING, "reason": reason, **_ci_fields(results)}
        self._hold(b, BoundaryHold.CI_PENDING, Out.HELD, **fields)

    def _ci_none(self, b: Boundary, results: list[CiResult]) -> None:
        why = NO_CHECKS_WHY if results else NO_OPEN_PR_WHY
        prs = prs_text(results) or self._own(b).branch  # type: ignore[union-attr]
        text = CI_NONE_REPORT.format(sprint=b.sprint, prs=prs, why=why) + self._not_rebased()
        text = self._with_big(text)
        self._post(text)
        self._finish(b, text, ci=CiVerdict.NONE, note=why, **_ci_fields(results))

    # ----- ci rebased

    def _ci_rebased(self, b: Boundary) -> None:
        """R9: only green is ready; every other verdict is reported, never held."""
        results = self._read_ci(b)
        REBASED_OUTCOMES[overall(results)](self, b, results)

    def _rebased_infra(self, b: Boundary, results: list[CiResult]) -> None:
        due = rerun_due(self._watched(b))
        if not due:
            return self._rebased_not_green(b, results)
        self._rerun(b, due)

    def _rebased_not_green(self, b: Boundary, results: list[CiResult]) -> None:
        verdict, own = overall(results), self._own(b)
        fields = {"sprint": b.sprint, "as_is": own.as_is, "verdict": verdict}  # type: ignore[union-attr]
        fields |= {"target": self.target, **_ci_fields(results)}
        text = REBASED_NOT_GREEN.format(**fields)
        self._post(text)
        self._finish(b, text, ci=verdict, **_ci_fields(results))

    def settle_bug(self, story: str) -> None:
        """Close a boundary held on failed CI with its bug story recorded."""
        b = self.runtime.state.boundary
        self.mine.ci_bug = story
        verdict, report = SETTLED[b.hold]  # type: ignore[index,union-attr]
        own = self._own(b)  # type: ignore[arg-type]
        hit = [own.ci] if own and own.ci and own.ci.verdict is verdict else []
        fields = {
            "sprint": b.sprint,  # type: ignore[union-attr]
            "story": story,
            "target": self.watch.target,
            "prs": prs_text(hit),
        }
        text = report.format(**fields) + self._not_rebased()
        self._finish(b, text, ci=verdict, story=story, note=text)  # type: ignore[arg-type]
        self.runtime.save()

    def _open_pr(self, entry: StackEntry) -> None:
        """Find the sprint PR; create it, edit it when it differs, or leave a closed one."""
        prs, spec = self.runtime.prs, self._spec(entry)
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

    def _spec(self, entry: StackEntry) -> PrSpec:
        base = self.runtime.config.upstream.branch
        return PrSpec(entry.branch, base, entry.title, self._body(entry), PrMode.READY)

    def _reverted_lines(self, entry: StackEntry) -> list[str]:
        stories = self.runtime.state.stories
        return [
            revert_log.pr_line(f"{i}: {stories[i].title}", e)
            for i in entry.reverted
            for e in stories[i].reverted
            if e.sprint == entry.sprint
        ]

    def _body(self, entry: StackEntry) -> str:
        prs = ", ".join(f"#{n}" for n in entry.supersedes)
        supersedes = SUPERSEDES_LINE.format(prs=prs) if entry.supersedes else ""
        titles = self.runtime.state.stories
        lines = [f"- {i}: {titles[i].title if i in titles else i}" for i in entry.stories]
        return PR_BODY.format(
            sprint=entry.sprint,
            stories="\n".join(lines),
            reverted=revert_log.pr_section(self._reverted_lines(entry)),
            supersedes=supersedes,
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
    CiVerdict.INFRA: BoundaryRunner._ci_infra,
    CiVerdict.MAIN: BoundaryRunner._ci_main,
    CiVerdict.PENDING: BoundaryRunner._ci_pending,
    CiVerdict.NONE: BoundaryRunner._ci_none,
}
SETTLED = {
    BoundaryHold.CI_FAILED: (CiVerdict.RED, CI_RED_REPORT),
    BoundaryHold.CI_INFRA: (CiVerdict.INFRA, CI_RED_REPORT),
    BoundaryHold.MAIN_BROKEN: (CiVerdict.MAIN, CI_MAIN_REPORT),
}
REBASED_OUTCOMES = {
    CiVerdict.GREEN: BoundaryRunner._ready,
    CiVerdict.INFRA: BoundaryRunner._rebased_infra,
    CiVerdict.RED: BoundaryRunner._rebased_not_green,
    CiVerdict.MAIN: BoundaryRunner._rebased_not_green,
    CiVerdict.PENDING: BoundaryRunner._rebased_not_green,
    CiVerdict.NONE: BoundaryRunner._rebased_not_green,
}
STAGE_RUNNERS = {
    Stage.SYNC: BoundaryRunner._sync,
    Stage.CHECK: BoundaryRunner._check,
    Stage.PUSH: BoundaryRunner._push,
    Stage.CI: BoundaryRunner._ci,
    Stage.REBASE: BoundaryRunner._rebase,
    Stage.PUSH_REBASED: BoundaryRunner._push_rebased,
    Stage.CI_REBASED: BoundaryRunner._ci_rebased,
}
AFTER_REBASE = {
    SyncOutcome.CONFLICT: BoundaryRunner._rebase_conflict,
    SyncOutcome.CURRENT: BoundaryRunner._rebase_current,
    SyncOutcome.REBASED: BoundaryRunner._settle_rebase,
}
SYNCS = {Edge.START: BoundaryRunner._start_sync, Edge.END: BoundaryRunner._end_sync}

"""Runs a sprint boundary one stage at a time.

The stages: sync, check, push as built, ci, rebase, push rebased, ci rebased.

The router asks ``due`` for the next unit of work, runs a stage with ``step`` or
a devops fix with ``run_role``, and calls ``after_fix`` when the fix is back.
All git access goes through ``runtime.upstream`` and ``runtime.prs``; checks run
through ``runtime.shell``. Only the start sync and the end's rebase stage rewrite the
team branch, through ``Upstream``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import halt, handover, loops, repin, revert_log, rewrite, stages
from .boundary import (
    BOUNDARY_DUE,
    BOUNDARY_ROLE,
    CHECKS_FAILED,
    CI_RED_HELD,
    CLOSED_NOTE,
    FF_COMMAND,
    FIX_KINDS,
    FIX_NOT_DONE,
    FIX_ROLE,
    KNOWN_FAILURES_NOTE,
    LOCAL_REPORT,
    NOT_PERMITTED,
    NOT_REBASED,
    NOTHING_NEW,
    PR_BODY,
    PUSHED_REPORT,
    REBASE_FIX_HELD,
    REBASE_UNCHANGED,
    REBASED_NOT_GREEN,
    REBASED_PUSHED_REPORT,
    SKIPPED_REPORT,
    SPRINT_BRANCH_DIVERGED,
    SPRINT_TITLE,
    START_CONFLICT,
    START_CURRENT,
    SUPERSEDED_BY,
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
    RebaseFix,
    ReplayProgress,
    StackEntry,
    Stage,
    StepKind,
    big_pr_notes,
    fix_brief,
    get_rebase_refusal,
    next_stage,
    own_entry,
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
from .gates import FINISHED, StoryState
from .halt import Halt, HaltKind
from .relay import Note
from .replay import Replayer, ReplayResult, ReplaySpec
from .scratch_rebase import REBASE_BRANCH, REBASE_DIR, ScratchRebase
from .scratch_replay import REPLAY_BRANCH, REPLAY_DIR, ScratchReplay
from .upstream import Lease, Pr, PrSpec, PrState, Rebase, Spans, SyncOutcome, Upstream

if TYPE_CHECKING:
    from .dispatch import Runtime

Out = BoundaryOutcome
FETCH_PREFIX = "git fetch "
REPLAY_STOPPED = (
    "replaying {commit} stopped (story {story}); the conflict is in the replay worktree"
)
PUSH_NOT_OPENED = "pushing {branch} was not done: {why}; it is pushed with the first landing"
FOLLOW_HOLDS = frozenset({BoundaryHold.CI_FAILED, BoundaryHold.CI_INFRA, BoundaryHold.CI_PENDING})
OPEN_MODES = frozenset({PrMode.DRAFT, PrMode.READY})


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
        if b is None or b.hold or self._is_awaiting_permission(b):
            return None
        if b.failure is None:
            return Due(StepKind.BOUNDARY, BOUNDARY_ROLE, "")
        return Due(FIX_KINDS[b.failure.case], FIX_ROLE, fix_brief(b, self._context(b)))

    def _is_awaiting_permission(self, b: Boundary) -> bool:
        asked = self.runtime.state.permission_asked
        return asked and b.stage is Stage.PUSH and self.mine.push is Permission.UNASKED

    def open_end(self) -> bool:
        """Open the end boundary when the sprint is finished (E1) and it has not run."""
        state = self.runtime.state
        if state.boundary or not state.sprint_complete() or self.mine.closed >= state.sprint:
            return False
        state.boundary = Boundary(Edge.END, state.sprint)
        return True

    def follow_remote(self) -> None:
        """R9: a CI hold follows a sprint branch someone else moved on the remote."""
        b = self.runtime.state.boundary
        own = self._own(b) if b is not None else None
        if own is None or b.hold not in FOLLOW_HOLDS:  # type: ignore[union-attr]
            return
        remote = self.remote.remote_head(own.branch)
        if remote and remote != own.pushed:
            self._follow(b, own, remote)  # type: ignore[arg-type]

    def _follow(self, b: Boundary, own: StackEntry, remote: str) -> None:
        """Fetch and fast-forward to ``remote``, back into CI; a divergence halts as drift."""
        self.remote.git.attempt("fetch", self.remote.settings.remote, own.branch)
        if not self.remote.fast_forward(remote):
            fields = {"branch": own.branch, "remote": self.remote.settings.remote}
            text = SPRINT_BRANCH_DIVERGED.format(**fields, remote_sha=remote, pushed=own.pushed)
            self.runtime.halt_run(Halt(HaltKind.CHECKOUT, text))
            return
        self.runtime.record_checkout()
        own.head = own.pushed = remote
        b.stage, b.hold = Stage.CI, None
        self._emit(b, Out.FOLLOWED, sha=remote)
        self.runtime.save()

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
        kept = self._keep_rebase_fix(b, report)
        b.rounds, b.failure, b.note = b.rounds + 1, None, ""
        b.hold = None if kept else fix_hold(report)
        self.runtime.save()

    def _keep_rebase_fix(self, b: Boundary, report: dict[str, Any]) -> bool:
        """R15: keep DevOps's answer to a rebase conflict for the rebase stage; say if it did."""
        if b.failure is None or b.failure.case is not FixCase.REBASE_CONFLICT:
            return False
        b.rebase_fix = RebaseFix(b.failure, report.get("status", ""), report.get("summary", ""))
        return True

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
        """AC1.1: rebase the team branch onto the target; a branch already on it is left alone."""
        if not b.sync_from and self.remote.behind() == 0:
            return self._start_current(b)
        self._pin_sync_from(b)
        result = self._make_replay(b)
        START_REBASES[result.outcome](self, b, result)

    def _start_current(self, b: Boundary) -> None:
        self._emit(b, Out.CURRENT, note=START_CURRENT.format(target=self.target), behind=0)
        self._advance(b)

    def _start_conflict(self, b: Boundary, result: Rebase) -> None:
        """S2: the rebase was aborted; tell the liaison and go on, holding nothing."""
        text = self._start_conflict_text(b, result)
        self._post(text)
        data = _describe_conflict(result)
        self._emit(b, Out.CONFLICT, note=text, subject=result.subject, **data)
        self._drop_replay_tree(b)
        self._unpin(b)
        self._advance(b)

    def _start_conflict_text(self, b: Boundary, result: Rebase) -> str:
        return START_CONFLICT.format(
            sprint=b.sprint,
            team=self.mine.team_branch,
            target=self.target,
            commit=result.commit[:12],
            subject=result.subject,
            files=", ".join(result.files),
        )

    def _own(self, b: Boundary) -> StackEntry | None:
        return own_entry(self.stack, b.sprint)

    def _end_sync(self, b: Boundary) -> None:
        """AC2.17: the sprint's own entry was made at its start; make it only when it is missing."""
        if self._own(b) is None:
            self._add_entry(b)
        own = self._own(b)
        if own is None or own.head == own.start:
            text = NOTHING_NEW.format(sprint=b.sprint)
            return self._finish(b, text, note=text)
        self._drop_superseded(b, own)
        self._emit(b, Out.PASS, note=f"sprint {b.sprint} is the sprint PR")
        self._advance(b)

    def _drop_superseded(self, b: Boundary, own: StackEntry) -> None:
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
        return run_checks(full_checks(self.runtime.config), judging)

    def _check(self, b: Boundary) -> None:
        head = self.runtime.git.head()
        if self.mine.checked == head:
            self._emit(b, Out.PASS, note=f"already checked at {head}")
            self._advance(b)
            return self._repin_due(b, head)
        report = self._run_checks(self.runtime.config.repo)
        if not report.passed:
            return CHECK_FAILURES[b.edge](self, b, report)
        self.mine.checked = head
        self._emit(b, Out.PASS, checks=report.summary())
        self._advance(b)
        self._repin_due(b, head)

    def _fail_team_check(self, b: Boundary, report: CheckReport) -> None:
        failure = Failure(Stage.CHECK, FixCase.TEAM_CHECK, report.reason())
        self._fail(b, failure, checks=report.summary())

    def _record_known_failures(self, b: Boundary, report: CheckReport) -> None:
        """AC2.1, AC2.2: a failing start check holds nothing; its failing ids are recorded."""
        ids, head = report.failing_ids, self.runtime.git.head()
        text = self._format_known_failures(b, report)
        self._post(text)
        self._finish(
            b,
            note=text,
            known_failures=ids,
            sha=head,
            reason=report.reason(),
            checks=report.summary(),
        )

    def _format_known_failures(self, b: Boundary, report: CheckReport) -> str:
        """The liaison's note: the failing ids and the 12-character start sha."""
        ids = report.failing_ids
        return KNOWN_FAILURES_NOTE.format(
            sprint=b.sprint,
            count=len(ids),
            team=self.mine.team_branch or self.remote.team_branch(),
            sha=self.runtime.git.head()[:12],
            ids=", ".join(ids),
        )

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
            return self._await_permission(b, own)  # type: ignore[arg-type]
        if self.mine.push is Permission.NO:
            return self._finish_local(b, NOT_PERMITTED)
        self._push_as_is(b, own)  # type: ignore[arg-type]

    def _await_permission(self, b: Boundary, own: StackEntry) -> None:
        """P1: ask once; the push waits (nothing is held) until the answer."""
        self._emit(b, Out.HELD, **self._ask_push(own))

    def _ask_push(self, entry: StackEntry) -> dict[str, Any]:
        """P1: the data that raises the push_permission hand-over, the first time only."""
        state = self.runtime.state
        asked, state.permission_asked = state.permission_asked, True
        return {} if asked else {"waiting": "push_permission", "branches": [entry.branch]}

    def _push_as_is(self, b: Boundary, own: StackEntry) -> None:
        """R3: push the team branch as it is, then open or reuse the sprint PR."""
        own.head = own.end = self.mine.last_end = self.runtime.git.head()
        rejected = self._push_branch(own)
        if rejected is not None:
            return self._reject(b, own, rejected)
        own.as_is, own.as_is_branch = own.pushed, own.branch
        self._open_pr(own)
        own.as_is_pr = own.pr
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
        text = LOCAL_REPORT.format(sprint=b.sprint, branch=branch, why=why) + self._not_rebased_note
        self._post(text)
        self._finish(b, text, ci=CiVerdict.NONE, note=why)

    @property
    def _not_rebased_note(self) -> str:
        return NOT_REBASED.format(target=self.target)

    # ----- rebase

    def _fetch(self) -> None:
        why = self.remote.missing()
        if why:
            raise UpstreamError(why)

    def _replay(self, b: Boundary) -> None:
        """R6, R7: refuse unless the as-built push has green CI, else rebase onto the target."""
        refusal = get_rebase_refusal(self._own(b))
        if refusal:
            return self._refuse_rebase(b, refusal)
        if b.rebase_fix:
            return self._apply_rebase_fix(b)
        self._fetch()
        self._pin_sync_from(b)
        result = self._make_replay(b)
        AFTER_REBASE[result.outcome](self, b, result)

    _rebase = _replay

    def _refuse_rebase(self, b: Boundary, reason: str) -> None:
        b.stage = Stage.CI
        self._hold(b, BoundaryHold.ERROR, Out.REFUSED, reason=reason)

    def _pin_sync_from(self, b: Boundary) -> None:
        """R2: pin the pre-rebase HEAD once and save it, so a crash cannot lose the old hashes."""
        if b.sync_from:
            return
        b.sync_from = self.runtime.git.head()
        b.replay = ReplayProgress(b.sync_from, "", "")
        self.runtime.save()

    def _make_replay(self, b: Boundary) -> Rebase:
        """R1: replay a line with story merges in the replay worktree, else rebase it plainly."""
        resumed = b.replay is not None and b.replay.merges
        if not resumed and not self.remote.has_story_merges(b.sync_from):
            return self.remote.rebase_onto(b.sync_from)
        progress = self._set_progress(b)
        if progress.base == progress.target:
            return Rebase(SyncOutcome.CURRENT)  # the target is already under the line
        spec, replayer = self._build_replayer(b, progress)
        return self._finish_replay(b, (spec, replayer), replayer.run(spec, progress))

    def _set_progress(self, b: Boundary) -> ReplayProgress:
        """The pinned progress, with the line's base and target filled in once."""
        progress = b.replay or ReplayProgress(b.sync_from, "", "")
        if not progress.merges:
            main = self.remote.git
            progress.target = main.run("rev-parse", self.target).strip()
            progress.base = main.run("merge-base", progress.old_head, self.target).strip()
            progress.merges, b.replay = True, progress
            self.runtime.save()
        return progress

    def _build_replayer(self, b: Boundary, progress: ReplayProgress) -> tuple[ReplaySpec, Replayer]:
        branch = REPLAY_BRANCH.format(sprint=b.sprint)
        spec = ReplaySpec(progress.base, progress.old_head, progress.target, branch)
        path = self.runtime.config.run_dir / REPLAY_DIR
        return spec, Replayer(self.remote.git, path, self.runtime.save)

    def _finish_replay(
        self, b: Boundary, tools: tuple[ReplaySpec, Replayer], result: ReplayResult
    ) -> Rebase:
        """A stopped replay is a conflict; a finished one keeps every path and moves the team."""
        spec, replayer = tools
        if result.outcome is SyncOutcome.CONFLICT:
            return Rebase(
                SyncOutcome.CONFLICT,
                "",
                result.files,
                result.commit,
                result.subject,
                output=REPLAY_STOPPED.format(story=result.story or "none", commit=result.commit),
            )
        self.remote.confirm_kept(Spans(b.sync_from, b.sync_from, spec.target, head=result.tip))
        self.remote.reset_team_branch(b.sync_from, result.tip)
        replayer.remove()
        return Rebase(SyncOutcome.REBASED, result.tip, moved=result.moved)

    def _drop_replay_tree(self, b: Boundary) -> None:
        """Remove a stopped replay's worktree: a start conflict is aborted, not handed on."""
        if b.replay is not None and b.replay.merges:
            self._build_replayer(b, b.replay)[1].remove()

    def _get_scratch(self, b: Boundary) -> ScratchRebase:
        path = self.runtime.config.run_dir / REBASE_DIR
        return ScratchRebase(self.remote, path, REBASE_BRANCH.format(sprint=b.sprint))

    def _find_replay_scratch(self, b: Boundary) -> ScratchReplay:
        path = self.runtime.config.run_dir / REPLAY_DIR
        return ScratchReplay(self.remote.git, path, REPLAY_BRANCH.format(sprint=b.sprint))

    @property
    def _is_replaying(self) -> bool:
        b = self.runtime.state.boundary
        return b is not None and b.replay is not None and b.replay.merges

    def _stop_replay(self, b: Boundary, result: Rebase) -> None:
        """R2: the replay stopped in its worktree on the scratch branch; wake DevOps."""
        scratch, story = self._find_replay_scratch(b), b.replay.story  # type: ignore[union-attr]
        b.failure = Failure(
            Stage.REPLAY,
            FixCase.REBASE_CONFLICT,
            result.output,
            branch=scratch.branch,
            files=list(result.files),
            commit=result.commit,
            subject=result.subject,
            worktree=str(scratch.path),
            story=story,
        )
        data = _describe_conflict(result)
        self._emit(b, Out.CONFLICT, subject=result.subject, branch=scratch.branch, **data)

    def _continue_replay(self, b: Boundary) -> None:
        """R2: DevOps resolved the stopped commit; replay the rest, check it, then move the team."""
        progress = b.replay
        tools = self._build_replayer(b, progress)  # type: ignore[arg-type]
        spec, replayer = tools
        if replayer.is_stopped(spec, progress):  # type: ignore[arg-type]
            replayer.settle_stopped(spec, progress)  # type: ignore[arg-type]
        found = replayer.run(spec, progress)  # type: ignore[arg-type]
        why = self._check_replayed(replayer, found)
        if why:
            return self._hold_conflict(b, why)
        b.rebase_fix = None
        result = self._finish_replay(b, tools, found)
        AFTER_REBASE[result.outcome](self, b, result)

    def _check_replayed(self, replayer: Replayer, found: ReplayResult) -> str:
        """The full checks on a finished replay's tip, in its worktree; why they failed, or ''."""
        if found.outcome is not SyncOutcome.REBASED:
            return ""
        return self._checks_refusal(replayer)

    def _rebase_conflict(self, b: Boundary, result: Rebase) -> None:
        """R13: stop the same rebase in a scratch worktree and wake DevOps; hold nothing."""
        if self._is_replaying:
            return self._stop_replay(b, result)
        scratch = self._get_scratch(b)
        scratch.prepare(b.sync_from)
        b.failure = Failure(
            Stage.REPLAY,
            FixCase.REBASE_CONFLICT,
            result.output,
            branch=scratch.branch,
            files=list(result.files),
            commit=result.commit,
            subject=result.subject,
            worktree=str(scratch.path),
            plain_rebase=True,
        )
        data = _describe_conflict(result)
        self._emit(b, Out.CONFLICT, subject=result.subject, branch=scratch.branch, **data)

    def _apply_rebase_fix(self, b: Boundary) -> None:
        """R16: move the team branch to DevOps's result, or hold with the first reason."""
        why = self._get_rebase_fix_refusal(b)
        if why:
            return self._hold_conflict(b, why)
        self._move_to_fix(b)

    def _get_rebase_fix_refusal(self, b: Boundary) -> str:
        fix = b.rebase_fix
        if fix.status != "done":  # type: ignore[union-attr]
            return FIX_NOT_DONE.format(status=fix.status)  # type: ignore[union-attr]
        if self._is_replaying:
            return self._find_replay_scratch(b).find_refusal(b.replay)  # type: ignore[arg-type]
        scratch = self._get_scratch(b)
        return scratch.find_refusal(b.sync_from) or self._checks_refusal(scratch)

    def _checks_refusal(self, scratch: ScratchRebase | Replayer) -> str:
        report = self._run_checks(scratch.path)
        if report.passed:
            return ""
        return CHECKS_FAILED.format(path=scratch.path, reason=report.reason())

    def _move_to_fix(self, b: Boundary) -> None:
        if self._is_replaying:
            return self._continue_replay(b)
        scratch = self._get_scratch(b)
        try:
            result = self.remote.move_team_branch(b.sync_from, scratch.head)
        except UpstreamError:
            self._drop_rebase_fix(b, scratch)
            raise
        self._drop_rebase_fix(b, scratch)
        self._settle_rebase(b, result)

    def _drop_rebase_fix(self, b: Boundary, scratch: ScratchRebase) -> None:
        """Drop the scratch and the fix; a moved team branch must rebase afresh (R16, R17)."""
        scratch.drop()
        b.rebase_fix = None
        b.sync_from, b.replay = "", None
        self.runtime.save()

    def _hold_conflict(self, b: Boundary, why: str) -> None:
        """R17: keep the worktree and branch; the liaison and the PO get the notes."""
        fix = b.rebase_fix
        c = fix.conflict  # type: ignore[union-attr]
        data = {
            "reason": why,
            "branch": c.branch,
            "notes": fix.notes or "none",  # type: ignore[union-attr]
            "commit": c.commit[:12],
            "subject": c.subject,
            "files": list(c.files),
        }
        self._post(
            REBASE_FIX_HELD.format(
                sprint=b.sprint, target=self.target, **{**data, "files": ", ".join(c.files)}
            )
        )
        self._hold(b, BoundaryHold.REBASE_CONFLICT, Out.CONFLICT, **data)

    def _rebase_current(self, b: Boundary, result: Rebase) -> None:
        self._emit(b, Out.CURRENT)
        self._unpin(b)
        self._advance(b)

    def _unpin(self, b: Boundary) -> None:
        b.sync_from, b.replay = "", None
        self.runtime.save()

    def _settle_rebase(self, b: Boundary, result: Rebase) -> None:
        count = rewrite.remap_state(self.runtime.state, result.moved)
        self.runtime.record_checkout()
        self.runtime.save()
        self._emit(b, Out.REBASED, sha=result.sha, rewritten=count)
        b.replayed = True
        self._unpin(b)
        self._advance(b)

    def _open(self, b: Boundary) -> None:
        """R7 (AC2.17): the sprint's own entry and remote branch, then the carried stories."""
        head = self.runtime.git.head()
        entry = self._own(b) or self._begin_entry(b, head)
        asked = self._push_opened(entry)
        carried = self._run_carried(head)
        self._finish(b, branch=entry.branch, sha=entry.pushed, replayed=carried, **asked)

    def _begin_entry(self, b: Boundary, head: str) -> StackEntry:
        state = self.runtime.state
        branch = f"{self.runtime.config.upstream.prefix}{b.sprint}"
        title = SPRINT_TITLE.format(sprint=b.sprint, goal=state.goal)
        ids = [s.id for s in state.stories.values() if s.sprint == b.sprint]
        entry = StackEntry(b.sprint, branch, head, head, title, ids, head=head)
        self.stack.append(entry)
        return entry

    def _push_opened(self, entry: StackEntry) -> dict[str, Any]:
        """Create the remote branch at the start head (P1: deferred while permission is unasked)."""
        if self.runtime.prs.missing() or self.mine.push is Permission.NO:
            return {}
        if self.mine.push is Permission.UNASKED:
            return self._ask_push(entry)
        refused = self.remote.push(Lease(entry.branch, "", entry.head))
        entry.pushed = entry.head if refused is None else entry.pushed
        if refused is not None:
            self._post(PUSH_NOT_OPENED.format(branch=entry.branch, why=refused))
        return {}

    def _run_carried(self, head: str) -> list[str]:
        """R8: rebase each carried story's branch onto the new sprint head."""
        from .replay import StoryReplay
        from .story_ci import StoryPusher

        rt = self.runtime
        carried = [s for s in rt.state.stories.values() if self._is_carried(s, head)]
        for story in carried:
            old_pr = story.pr
            if StoryReplay(rt).run(story, head).outcome is SyncOutcome.REBASED:
                StoryPusher(rt).push_replayed(story, old_pr)
        return [s.id for s in carried]

    def _is_carried(self, story: StoryState, head: str) -> bool:
        """A story of this sprint, not yet landed, whose branch was forked from an older head."""
        mine = story.sprint == self.runtime.state.sprint and story.landed is None
        return (
            mine and bool(story.branch) and story.base_sha != head and story.status not in FINISHED
        )

    # ----- push replayed

    def _push_replayed(self, b: Boundary) -> None:
        """R5: push the replayed head to the next ``-r<k>`` branch; nothing if it did not change."""
        if b.edge is Edge.START:
            return self._push_start_replay(b)
        own, head = self._own(b), self.runtime.git.head()
        if head == own.pushed:  # type: ignore[union-attr]
            return self._report_unchanged(b, own)  # type: ignore[arg-type]
        rejected = self._push_replay_branch(own, head)  # type: ignore[arg-type]
        if rejected is not None:
            return self._reject(b, own, rejected)  # type: ignore[arg-type]
        self._report_rebased(b, own)  # type: ignore[arg-type]
        self._advance(b)

    def _push_start_replay(self, b: Boundary) -> None:
        """R7: after a start replay, push the newest open PR's next ``-r<k>`` branch (under P1)."""
        newest = self.stack[-1] if self.stack else None
        due = b.replayed and newest is not None and newest.mode in OPEN_MODES and newest.pr
        if not due or self.mine.push is not Permission.YES or self.runtime.prs.missing():
            return self._advance(b)
        rejected = self._push_replay_branch(newest, self.runtime.git.head())  # type: ignore[arg-type]
        if rejected is not None:
            self._post(PUSH_NOT_OPENED.format(branch=newest.branch, why=rejected))  # type: ignore[union-attr]
        self._advance(b)

    def _push_replay_branch(self, own: StackEntry, head: str) -> str | None:
        """R5: push ``head`` as a new branch with a ready PR; the old PR is closed with a link."""
        k = own.replays + 1
        branch = f"{self.runtime.config.upstream.prefix}{own.sprint}-r{k}"
        refused = self.remote.push(Lease(branch, "", head))
        if refused is not None:
            return refused
        old_pr = own.pr
        own.branch, own.replays, own.head, own.pushed = branch, k, head, head
        own.commits = self.remote.count(head)
        self._open_replay_pr(own)
        if old_pr:
            note = SUPERSEDED_BY.format(target=self.target, url=own.url)
            self.runtime.prs.close(old_pr, note)
        return None

    def _make_ready(self, own: StackEntry) -> None:
        """The replay changed nothing, so the draft sprint PR itself becomes the ready one."""
        if own.mode is not PrMode.DRAFT or own.pr is None:
            return
        pr = Pr(own.pr, own.url, PrState.OPEN, True, own.base)
        self.runtime.prs.edit(pr, self.make_spec(own, PrMode.READY))
        own.mode = PrMode.READY

    def _open_replay_pr(self, own: StackEntry) -> None:
        """A ready PR from the replay branch; always a new one (no look-up)."""
        spec = self.make_spec(own, PrMode.READY)
        pr = self.runtime.prs.create(spec)
        own.pr, own.url, own.base, own.mode = pr.number, pr.url, spec.base, spec.mode

    _push_rebased = _push_replayed

    def _report_unchanged(self, b: Boundary, own: StackEntry) -> None:
        note = REBASE_UNCHANGED.format(branch=own.branch, sha=own.pushed)
        self._emit(b, Out.PASS, note=note)
        self._make_ready(own)
        self._finish_green(b, [own.ci] if own.ci else [])

    def _report_rebased(self, b: Boundary, own: StackEntry) -> None:
        fields = {"sprint": b.sprint, "pr": own.pr, "target": self.target}
        fields |= {"sha": own.pushed, "as_is": own.as_is}
        self._post(REBASED_PUSHED_REPORT.format(**fields))
        self._emit(b, Out.PUSHED, branch=own.branch, sha=own.pushed, as_is=own.as_is)

    # ----- ci

    def _watched(self, b: Boundary) -> list[StackEntry]:
        own = self._own(b)
        return [own] if own and own.mode in OPEN_MODES and own.pr else []

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

    def _finish_green(self, b: Boundary, results: list[CiResult]) -> None:
        text = self._with_big(green_report(b.sprint, results))
        self._finish(b, self._add_ff(text), ci=CiVerdict.GREEN, **_ci_fields(results))

    def _add_ff(self, text: str) -> str:
        """R6: ``text`` and the fast-forward command that lands the sprint's PR (never a rebase)."""
        own = self._own(self.runtime.state.boundary)  # type: ignore[arg-type]
        if own is None:
            return text
        settings = self.runtime.config.upstream
        ff = FF_COMMAND.format(remote=settings.remote, sha=own.pushed, target=settings.branch)
        return f"{text}\n{ff}"

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
        text = CI_NONE_REPORT.format(sprint=b.sprint, prs=prs, why=why) + self._not_rebased_note
        text = self._with_big(text)
        self._post(text)
        self._finish(b, text, ci=CiVerdict.NONE, note=why, **_ci_fields(results))

    # ----- ci rebased

    def _check_replayed_ci(self, b: Boundary) -> None:
        """R9: only green is ready; every other verdict is reported, never held."""
        results = self._read_ci(b)
        REBASED_OUTCOMES[overall(results)](self, b, results)

    _check_rebased_ci = _check_replayed_ci

    def _handle_rebased_infra(self, b: Boundary, results: list[CiResult]) -> None:
        due = rerun_due(self._watched(b))
        if not due:
            return self._report_rebased_not_green(b, results)
        self._rerun(b, due)

    def _report_rebased_not_green(self, b: Boundary, results: list[CiResult]) -> None:
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
        text = report.format(**fields) + self._not_rebased_note
        self._finish(b, text, ci=verdict, story=story, note=text)  # type: ignore[arg-type]
        self.runtime.save()

    def _open_pr(self, entry: StackEntry) -> None:
        """Keep the sprint PR the landings opened; else find it, create it, edit it or leave it."""
        if entry.pr is not None:
            return
        prs, spec = self.runtime.prs, self.make_spec(entry)
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

    def make_spec(self, entry: StackEntry, mode: PrMode = PrMode.READY) -> PrSpec:
        """The pull request the entry should have, ready or draft."""
        base = self.runtime.config.upstream.branch
        return PrSpec(entry.branch, base, entry.title, self._body(entry), mode)

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
            target=self.runtime.config.upstream.branch,
            remote=self.runtime.config.upstream.remote,
            sha=f"{self.runtime.config.upstream.remote}/{entry.branch}",
        )


def _describe_conflict(result: Rebase) -> dict[str, Any]:
    """The conflicting files and the short commit of a stopped rebase."""
    return {"files": list(result.files), "commit": result.commit[:12]}


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
    CiVerdict.GREEN: BoundaryRunner._finish_green,
    CiVerdict.INFRA: BoundaryRunner._handle_rebased_infra,
    CiVerdict.RED: BoundaryRunner._report_rebased_not_green,
    CiVerdict.MAIN: BoundaryRunner._report_rebased_not_green,
    CiVerdict.PENDING: BoundaryRunner._report_rebased_not_green,
    CiVerdict.NONE: BoundaryRunner._report_rebased_not_green,
}
STAGE_RUNNERS = {
    Stage.SYNC: BoundaryRunner._sync,
    Stage.CHECK: BoundaryRunner._check,
    Stage.PUSH: BoundaryRunner._push,
    Stage.CI: BoundaryRunner._ci,
    Stage.OPEN: BoundaryRunner._open,
    Stage.REPLAY: BoundaryRunner._replay,
    Stage.PUSH_REPLAYED: BoundaryRunner._push_replayed,
    Stage.CI_REPLAYED: BoundaryRunner._check_replayed_ci,
}
AFTER_REBASE = {
    SyncOutcome.CONFLICT: BoundaryRunner._rebase_conflict,
    SyncOutcome.CURRENT: BoundaryRunner._rebase_current,
    SyncOutcome.REBASED: BoundaryRunner._settle_rebase,
}
START_REBASES = {
    SyncOutcome.CONFLICT: BoundaryRunner._start_conflict,
    SyncOutcome.CURRENT: BoundaryRunner._rebase_current,
    SyncOutcome.REBASED: BoundaryRunner._settle_rebase,
}
CHECK_FAILURES = {
    Edge.START: BoundaryRunner._record_known_failures,
    Edge.END: BoundaryRunner._fail_team_check,
}
SYNCS = {Edge.START: BoundaryRunner._start_sync, Edge.END: BoundaryRunner._end_sync}

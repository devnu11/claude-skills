"""Watch a run while it runs: each slice, re-read the job and decide whether it must stop.

A runner waits on its run in ``SLICE`` steps and calls ``RunWatch.check`` after
each. The check re-reads ``state.json``, so a live ``extend`` takes effect
within one slice. It then:

1. **Samples the progress probes** (``probes.PROBES``). The last time any
   reading changed is the run's last progress.
2. **Raises notices** (``CONDITIONS``) as they become true: ``idle`` once no
   probe has moved for ``--idle``, ``hung`` once a heartbeat's ``at`` is older
   than ``--idle``. Each re-arms when it stops being true.
3. **Starts the idle stop** once the run has been idle or hung for ``--idle-stop``: a
   stop sequence from now, going hard after ``--hardstop`` (at once without).
4. **Walks each stop sequence** (deadline, idle stop; see ``limits.PHASES``),
   acting once per phase per run:

   - graceful: logs the stop and asks the runner to run the job's
     ``--stop-command`` (``Verdict.GRACEFUL``). A soft deadline (no stop
     command, no hard phase) does nothing mid-run;
   - hard: logs the stop and asks the runner to end the run (``Verdict.END``).

Once a stop was sent, ``settle`` turns the run's outcome into ``HALTED`` with
the stop's reason, whatever the run itself returned.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from . import probes
from .limits import Outcome, OutcomeKind, Phase, Stop, StopCause, span
from .notify import Notice, Trigger, post
from .probes import Context, Probe, Reading, Stamp
from .store import HEARTBEAT_ENV, HEARTBEAT_FILE, Job, JobState

SLICE = 30.0
ORDER = tuple(Phase)
STOP_EVENTS = {StopCause.DEADLINE: "deadline", StopCause.IDLE: "idle-stop"}
STOP_NOTICES = {StopCause.DEADLINE: Trigger.DEADLINE, StopCause.IDLE: Trigger.IDLE_STOP}


class Verdict(StrEnum):
    """What a runner must do after a check."""

    GRACEFUL = "graceful"
    END = "end"


Verdicts = tuple[Verdict, ...]


@dataclass(frozen=True)
class View:
    """The run as one check sees it: the job's state, the time, the last progress and the
    stalest heartbeat (None when no heartbeat has been written)."""

    state: JobState
    now: float
    moved_at: float
    alive_at: float | None = None
    waiting: str | None = None

    @property
    def idle_for(self) -> float:
        return self.now - self.moved_at

    @property
    def stale_for(self) -> float:
        """How long the stalest heartbeat has gone unwritten; 0 without one."""
        return 0.0 if self.alive_at is None else self.now - self.alive_at

    @property
    def quiet_for(self) -> float:
        """How long the run has been idle or hung, whichever is longer."""
        return max(self.idle_for, self.stale_for)


@dataclass(frozen=True)
class Step:
    """One phase of one stop sequence."""

    stop: Stop
    phase: Phase

    @property
    def key(self) -> tuple[StopCause, Phase]:
        return self.stop.cause, self.phase


def due(stop: Stop, now: float) -> list[Step]:
    """Every phase ``stop`` has reached by ``now``, in order (graceful before hard)."""
    reached = ORDER[1 : ORDER.index(stop.phase(now)) + 1]
    return [Step(stop, phase) for phase in reached]


def enforced(step: Step, state: JobState) -> bool:
    """True when the stop does something: a stop command to send, or a hard phase to come."""
    return bool(state.spec.stop_command) or step.stop.hard_after is not None


def idle(view: View) -> str | None:
    """Why the run counts as idle (no probe moved for ``--idle``), or None."""
    limit = view.state.spec.idle
    if limit is None or view.idle_for < limit:
        return None
    return f"no progress for {span(view.idle_for)}"


def hung(view: View) -> str | None:
    """Why the run counts as hung (a heartbeat older than ``--idle``), or None."""
    limit = view.state.spec.idle
    if limit is None or view.alive_at is None or view.stale_for < limit:
        return None
    return f"heartbeat stale for {span(view.stale_for)}"


CONDITIONS: dict[Trigger, Callable[[View], str | None]] = {Trigger.IDLE: idle, Trigger.HUNG: hung}


@dataclass
class Liveness:
    """The probes' last readings and when any of them last changed."""

    probes: list[Probe]
    moved_at: float
    last: list[object] = field(default_factory=list)
    alive_at: float | None = None
    waiting: str | None = None

    def sample(self, now: float) -> None:
        """Read every probe; a changed value moves ``moved_at`` to ``now``."""
        readings = [probe() for probe in self.probes]
        values = [reading.value for reading in readings]
        if values != self.last:
            self.last, self.moved_at = values, now
        self.alive_at = stalest(readings)
        self.waiting = next((r.waiting for r in readings if r.waiting), None)

    def rebase(self) -> None:
        """Take the current readings as the starting point, without counting them as progress."""
        self.last = [probe().value for probe in self.probes]


def stalest(readings: list[Reading]) -> float | None:
    """The oldest liveness stamp among ``readings``, or None when none has one."""
    return min((r.alive_at for r in readings if r.alive_at is not None), default=None)


class StopRequested(BaseException):
    """The user asked the job to stop; a BaseException so job code cannot swallow it."""


@dataclass
class RunWatch:
    """The per-slice checks of one run; ``clock`` and ``slice`` are injectable for tests."""

    job: Job
    clock: Callable[[], float] = time.time
    slice: float = field(default_factory=lambda: SLICE)
    halt: str | None = None
    acted: set[tuple[StopCause, Phase]] = field(default_factory=set)
    raised: set[Trigger] = field(default_factory=set)
    idle_stop: Stop | None = None
    waited_at: float | None = None
    context: Context = field(init=False)
    liveness: Liveness = field(init=False)

    def __post_init__(self) -> None:
        spec = self.job.load().spec
        self.context = Context(self.job, Path(spec.cwd), Stamp())
        chosen = [*probes.chosen(spec.progress, spec.kind), f"heartbeat:{self.heartbeat}"]
        self.liveness = Liveness([probes.build(text, self.context) for text in chosen], 0.0)
        self.liveness.sample(self.clock())

    @property
    def spend(self) -> Stamp:
        return self.context.spend

    @property
    def heartbeat(self) -> Path:
        """The job's own heartbeat file, which the run finds in ``$UNATTENDED_HEARTBEAT``."""
        return self.job.path(HEARTBEAT_FILE)

    def env(self) -> dict[str, str]:
        """What the run's environment gains: where to write its heartbeat."""
        return {HEARTBEAT_ENV: str(self.heartbeat)}

    def track(self, pgid: int) -> None:
        """Point the ``cpu`` and ``children`` probes at the run's process group, which has
        just started; what the start wrote (the log header) is not progress."""
        self.context.pgid = pgid
        self.liveness.rebase()

    def check_stop(self) -> None:
        """Raise ``StopRequested`` once ``stop`` wrote the stop file (how Windows stops a run)."""
        if self.job.stop_requested():
            raise StopRequested

    def check(self) -> Verdicts:
        """What the runner must do now; empty to keep waiting."""
        now = self.clock()
        self.liveness.sample(now)
        live = self.liveness
        view = View(self.job.load(), now, live.moved_at, live.alive_at, live.waiting)
        self._raise_notices(view)
        self._raise_waiting(view)
        self._start_idle_stop(view)
        return self._walk(view)

    def stops(self, view: View) -> list[Stop]:
        """The stop sequences that apply now."""
        return [s for s in (view.state.bounds.deadline_stop(), self.idle_stop) if s]

    def settle(self, outcome: Outcome) -> Outcome:
        """``outcome``, or ``HALTED`` with the stop's reason once a stop was sent."""
        if self.halt is None:
            return outcome
        return Outcome(OutcomeKind.HALTED, self.halt, outcome.metrics)

    def _raise_notices(self, view: View) -> None:
        """Post each condition that has just become true; forget those no longer true."""
        found = {t: reason for t, check in CONDITIONS.items() if (reason := check(view))}
        for trigger in found.keys() - self.raised:
            self._notice(trigger, found[trigger])
        self.raised = set(found)

    def _raise_waiting(self, view: View) -> None:
        """I7: one ``waiting`` notice per wait; again only after the run's progress moved."""
        if view.waiting is None:
            return
        if self.waited_at != view.moved_at:
            self.waited_at = view.moved_at
            self._notice(Trigger.WAITING, view.waiting)

    def _start_idle_stop(self, view: View) -> None:
        bounds = view.state.bounds
        if view.waiting is not None:
            return
        if self.idle_stop or bounds.idle_stop is None or view.quiet_for < bounds.idle_stop:
            return
        self.idle_stop = Stop(StopCause.IDLE, view.now, bounds.hardstop or 0.0, bounds.idle_stop)

    def _walk(self, view: View) -> Verdicts:
        steps = [step for stop in self.stops(view) for step in due(stop, view.now)]
        fresh = [step for step in steps if step.key not in self.acted]
        return tuple(verdict for step in fresh for verdict in self._act(step, view))

    def _act(self, step: Step, view: View) -> Verdicts:
        self.acted.add(step.key)
        if not enforced(step, view.state):
            return ()
        reason = step.stop.reason(step.phase)
        self.job.event(STOP_EVENTS[step.stop.cause], {"phase": step.phase, "reason": reason})
        self._notice(STOP_NOTICES[step.stop.cause], reason)
        verdicts = ACTIONS[step.phase](view.state)
        self.halt = reason if verdicts else self.halt
        return verdicts

    def _notice(self, trigger: Trigger, reason: str) -> None:
        post(self.job, Notice(trigger, self.job.load().status, reason))


ACTIONS: dict[Phase, Callable[[JobState], Verdicts]] = {
    Phase.GRACEFUL: lambda state: (Verdict.GRACEFUL,) if state.spec.stop_command else (),
    Phase.HARD: lambda state: (Verdict.END,),
}

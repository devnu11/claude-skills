"""Watch a run while it runs: each slice, re-read the job and decide whether it must stop.

A runner waits on its run in ``SLICE`` steps and calls ``RunWatch.check`` after
each. The check re-reads ``state.json``, so a live ``extend`` takes effect
within one slice. Each stop sequence (see ``limits.PHASES``) acts once per
phase per run:

- **graceful:** logs the stop and asks the runner to run the job's
  ``--stop-command`` (``Verdict.GRACEFUL``). A soft stop (no stop command, no
  hard phase) does nothing mid-run.
- **hard:** logs the stop and asks the runner to end the run (``Verdict.END``).

Once a stop was sent, ``settle`` turns the run's outcome into ``HALTED`` with
the stop's reason, whatever the run itself returned.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from .limits import Outcome, OutcomeKind, Phase, Stop, StopCause
from .store import Job, JobState

SLICE = 30.0
ORDER = tuple(Phase)
STOP_EVENTS = {StopCause.DEADLINE: "deadline", StopCause.IDLE: "idle-stop"}


class Verdict(StrEnum):
    """What a runner must do after a check."""

    GRACEFUL = "graceful"
    END = "end"


Verdicts = tuple[Verdict, ...]


@dataclass(frozen=True)
class View:
    """The job as one check sees it: its state and the time."""

    state: JobState
    now: float


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


@dataclass
class RunWatch:
    """The per-slice checks of one run; ``clock`` and ``slice`` are injectable for tests."""

    job: Job
    clock: Callable[[], float] = time.time
    slice: float = field(default_factory=lambda: SLICE)
    halt: str | None = None
    acted: set[tuple[StopCause, Phase]] = field(default_factory=set)

    def check(self) -> Verdicts:
        """What the runner must do now; empty to keep waiting."""
        view = View(self.job.load(), self.clock())
        steps = [step for stop in self.stops(view) for step in due(stop, view.now)]
        fresh = [step for step in steps if step.key not in self.acted]
        return tuple(verdict for step in fresh for verdict in self._act(step, view))

    def stops(self, view: View) -> list[Stop]:
        """The stop sequences that apply now."""
        deadline = view.state.bounds.deadline_stop()
        return [deadline] if deadline else []

    def settle(self, outcome: Outcome) -> Outcome:
        """``outcome``, or ``HALTED`` with the stop's reason once a stop was sent."""
        if self.halt is None:
            return outcome
        return Outcome(OutcomeKind.HALTED, self.halt, outcome.metrics)

    def _act(self, step: Step, view: View) -> Verdicts:
        self.acted.add(step.key)
        if not enforced(step, view.state):
            return ()
        reason = step.stop.reason(step.phase)
        self.job.event(STOP_EVENTS[step.stop.cause], {"phase": step.phase, "reason": reason})
        verdicts = ACTIONS[step.phase](view.state)
        self.halt = reason if verdicts else self.halt
        return verdicts


ACTIONS: dict[Phase, Callable[[JobState], Verdicts]] = {
    Phase.GRACEFUL: lambda state: (Verdict.GRACEFUL,) if state.spec.stop_command else (),
    Phase.HARD: lambda state: (Verdict.END,),
}

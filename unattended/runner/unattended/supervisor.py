"""The supervisor loop: run the job, then finish, or wait for the reset and resume.

A usage limit waits until the stated reset plus three minutes (or the fallback
wait); a rate limit backs off 1, 2, 4… minutes up to 30. Before waiting, the
job's bounds (deadline, resumes, cost) may end it as ``limit-reached``. A stop
(the stop file, SIGTERM or Ctrl-C) raises ``StopRequested`` and ends it as
``stopped``.
"""

from __future__ import annotations

import signal
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from types import FrameType
from typing import Protocol

from .limits import Outcome, OutcomeKind, Waits, backoff, local
from .store import Job, JobState, JobStatus

SLICE = 30.0
STOP_REASON = "stopped by the user"
FINAL: dict[OutcomeKind, JobStatus] = {
    OutcomeKind.DONE: JobStatus.DONE,
    OutcomeKind.FAILED: JobStatus.FAILED,
}


class Runner(Protocol):
    """Runs a job once: the first time, or as a resume once it has run."""

    def run_once(self) -> Outcome: ...


class StopRequested(BaseException):
    """The user asked the job to stop; a BaseException so job code cannot swallow it."""


def raise_stop(signum: int, frame: FrameType | None) -> None:
    raise StopRequested


def install_sigterm() -> None:
    """Make SIGTERM unwind the current run and mark the job stopped."""
    signal.signal(signal.SIGTERM, raise_stop)


def wake_after(state: JobState, outcome: Outcome) -> Callable[[float], float]:
    """When to wake after a limit or rate limit, as a function of now."""
    if outcome.kind is OutcomeKind.RATE_LIMITED:
        return lambda now: now + backoff(state.retries - 1)
    return lambda now: Waits(state.spec.fallback_wait).after_limit(outcome.reason, now)


@dataclass
class Supervisor:
    """Supervises one job; ``clock`` and ``sleep`` are injectable for tests."""

    job: Job
    runner: Runner
    clock: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep

    def run(self) -> JobStatus:
        """Run and resume until the job ends; returns its final status."""
        try:
            status = None
            while status is None:
                status = self._cycle()
        except (StopRequested, KeyboardInterrupt):
            status = self._finish(JobStatus.STOPPED, STOP_REASON)
        return status

    def _cycle(self) -> JobStatus | None:
        """One run and what follows; the final status, or None to run again."""
        self._check_stop()
        self.job.update(lambda st: st.mark(JobStatus.RUNNING))
        outcome = self.runner.run_once()
        state = self._record(outcome)
        if outcome.kind in FINAL:
            return self._finish(FINAL[outcome.kind], outcome.reason)
        return self._wait(state, outcome)

    def _record(self, outcome: Outcome) -> JobState:
        def apply(st: JobState) -> None:
            st.runs += 1
            st.cost += outcome.metrics.cost
            st.retries = st.retries + 1 if outcome.kind is OutcomeKind.RATE_LIMITED else 0

        state = self.job.update(apply)
        detail = {"run": state.runs, "outcome": outcome.kind, "reason": outcome.reason}
        self.job.event("run", detail | asdict(outcome.metrics))
        return state

    def _wait(self, state: JobState, outcome: Outcome) -> JobStatus | None:
        """Wait for the reset and count a resume, unless the bounds end the job first."""
        wake = wake_after(state, outcome)(self.clock())
        stop = state.bounds.stop_reason(state.progress(wake))
        if stop:
            return self._finish(JobStatus.LIMIT_REACHED, f"{outcome.reason}; {stop}")
        self._mark_waiting(wake, outcome.reason)
        self._sleep_until(wake)
        state = self.job.update(lambda st: setattr(st, "resumes", st.resumes + 1))
        self.job.event("resume", {"resumes": state.resumes})
        return None

    def _mark_waiting(self, wake: float, reason: str) -> None:
        def apply(st: JobState) -> None:
            st.mark(JobStatus.WAITING, reason)
            st.next_wake = wake

        self.job.update(apply)
        self.job.event("wait", {"until": local(wake).isoformat(timespec="seconds")})

    def _sleep_until(self, wake: float) -> None:
        """Sleep in ``SLICE`` steps, checking the stop file before each."""
        while (left := wake - self.clock()) > 0:
            self._check_stop()
            self.sleep(min(SLICE, left))
        self._check_stop()

    def _check_stop(self) -> None:
        if self.job.stop_requested():
            raise StopRequested

    def _finish(self, status: JobStatus, reason: str) -> JobStatus:
        def apply(st: JobState) -> None:
            st.mark(status, reason)
            st.next_wake = None

        self.job.update(apply)
        self.job.event("end", {"status": status, "reason": reason})
        return status

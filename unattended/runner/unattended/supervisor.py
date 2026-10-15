"""The supervisor loop: run the job, then finish, or wait for the reset and resume.

A run that spends what is left of the cost cap ends the job as
``limit-reached`` at once. A usage limit waits until the stated reset plus
three minutes (or the fallback wait); a rate limit backs off 1, 2, 4… minutes
up to 30. Before waiting, the job's bounds (deadline, resumes, cost) may end
it as ``limit-reached``. A network failure (``OFFLINE``) runs nothing until a
plain TCP probe reaches the API again, so waiting costs no tokens; it does not
count as a resume, but ``MAX_RECONNECTS`` in a row fail the job. A stop (the
stop file, SIGTERM or Ctrl-C) raises ``StopRequested`` and ends it as
``stopped``. An offline wait has no wake time (``wake_on`` is ``network``).

Each run is watched (``watch.RunWatch``): from the deadline the job's stop
command is sent, and from the deadline plus ``--hardstop`` the run is ended.
A run that ends after a stop was sent ends the job as ``limit-reached`` with
the stop's reason. Once the deadline has passed, no new run, resume or wait
starts (``Halted``).
"""

from __future__ import annotations

import signal
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from types import FrameType
from typing import Protocol

from . import network
from .limits import Outcome, OutcomeKind, Phase, Waits, Wake, WakeOn, backoff, local
from .store import Job, JobState, JobStatus
from .watch import SLICE, RunWatch

STOP_REASON = "stopped by the user"
FINAL: dict[OutcomeKind, JobStatus] = {
    OutcomeKind.DONE: JobStatus.DONE,
    OutcomeKind.FAILED: JobStatus.FAILED,
    OutcomeKind.BUDGET: JobStatus.LIMIT_REACHED,
    OutcomeKind.HALTED: JobStatus.LIMIT_REACHED,
}
RETRIED = frozenset({OutcomeKind.RATE_LIMITED, OutcomeKind.OFFLINE})
MAX_RECONNECTS = 10


class Runner(Protocol):
    """Runs a job once: the first time, or as a resume once it has run."""

    def run_once(self, watch: RunWatch) -> Outcome: ...


class StopRequested(BaseException):
    """The user asked the job to stop; a BaseException so job code cannot swallow it."""


class Halted(Exception):
    """The deadline has passed between runs; the message is the job's end reason."""


def raise_stop(signum: int, frame: FrameType | None) -> None:
    raise StopRequested


def install_sigterm() -> None:
    """Make SIGTERM unwind the current run and mark the job stopped."""
    signal.signal(signal.SIGTERM, raise_stop)


def wake_after(state: JobState, outcome: Outcome) -> Callable[[float], Wake]:
    """When and why to wake after a limit or rate limit, as a function of now."""
    if outcome.kind is OutcomeKind.RATE_LIMITED:
        return lambda now: Wake(now + backoff(state.retries - 1), WakeOn.BACKOFF)
    return lambda now: Waits(state.spec.fallback_wait).after_limit(outcome.reason, now)


@dataclass
class Supervisor:
    """Supervises one job; ``clock``, ``sleep`` and ``online`` are injectable for tests."""

    job: Job
    runner: Runner
    clock: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep
    online: Callable[[], bool] = network.online

    def run(self) -> JobStatus:
        """Run and resume until the job ends; returns its final status."""
        try:
            status = None
            while status is None:
                status = self._cycle()
        except (StopRequested, KeyboardInterrupt):
            status = self._finish(JobStatus.STOPPED, STOP_REASON)
        except Halted as halted:
            status = self._finish(JobStatus.LIMIT_REACHED, str(halted))
        return status

    def _cycle(self) -> JobStatus | None:
        """One run and what follows; the final status, or None to run again."""
        self._check_stop()
        self._check_deadline()
        self.job.update(lambda st: st.mark(JobStatus.RUNNING))
        watch = RunWatch(self.job, self.clock)
        outcome = watch.settle(self.runner.run_once(watch))
        state = self._record(outcome)
        if outcome.kind in FINAL:
            return self._finish(FINAL[outcome.kind], outcome.reason)
        if outcome.kind is OutcomeKind.OFFLINE:
            return self._reconnect(state, outcome.reason)
        return self._wait(state, outcome)

    def _record(self, outcome: Outcome) -> JobState:
        def apply(st: JobState) -> None:
            st.runs += 1
            st.cost += outcome.metrics.cost
            st.retries = st.retries + 1 if outcome.kind in RETRIED else 0

        state = self.job.update(apply)
        detail = {"run": state.runs, "outcome": outcome.kind, "reason": outcome.reason}
        self.job.event("run", detail | asdict(outcome.metrics))
        return state

    def _wait(self, state: JobState, outcome: Outcome) -> JobStatus | None:
        """Wait for the reset and count a resume, unless the bounds end the job first."""
        wake = wake_after(state, outcome)(self.clock())
        stop = state.bounds.stop_reason(state.progress(wake.at))
        if stop:
            return self._finish(JobStatus.LIMIT_REACHED, f"{outcome.reason}; {stop}")
        self._mark_waiting(wake, outcome.reason)
        self._sleep_until(wake.at)
        state = self.job.update(lambda st: setattr(st, "resumes", st.resumes + 1))
        self.job.event("resume", {"resumes": state.resumes})
        return None

    def _reconnect(self, state: JobState, reason: str) -> JobStatus | None:
        """Wait until the API is reachable, then run again; None to run, else the end."""
        if state.retries > MAX_RECONNECTS:
            return self._finish(JobStatus.FAILED, f"{reason}; {MAX_RECONNECTS} reconnects in a row")
        self._mark_offline(reason)
        self.job.event("offline", {"reason": reason})
        if not self._await_network(state.bounds.deadline):
            return self._finish(JobStatus.LIMIT_REACHED, f"{reason}; deadline passed offline")
        self.job.event("online", {})
        return None

    def _await_network(self, deadline: float | None) -> bool:
        """Probe every ``SLICE`` until the API answers; False once the deadline passes."""
        while deadline is None or self.clock() < deadline:
            self._check_stop()
            self.sleep(SLICE)
            if self.online():
                return True
        return False

    def _mark_offline(self, reason: str) -> None:
        """Wait for the network: no wake time, only what is awaited."""

        def apply(st: JobState) -> None:
            st.mark(JobStatus.WAITING, reason)
            st.wake_on = WakeOn.NETWORK

        self.job.update(apply)

    def _mark_waiting(self, wake: Wake, reason: str) -> None:
        def apply(st: JobState) -> None:
            st.mark(JobStatus.WAITING, reason)
            st.next_wake, st.wake_on = wake.at, wake.on

        self.job.update(apply)
        until = local(wake.at).isoformat(timespec="seconds")
        self.job.event("wait", {"until": until, "on": wake.on})

    def _sleep_until(self, wake: float) -> None:
        """Sleep in ``SLICE`` steps, checking the stop and wake files before each."""
        while (left := wake - self.clock()) > 0 and not self._woken():
            self._check_stop()
            self._check_deadline()
            self.sleep(min(SLICE, left))
        self._check_stop()

    def _woken(self) -> bool:
        """True once ``resume --now`` asked to cut the wait short; logs it once."""
        if not self.job.wake_requested():
            return False
        self.job.clear_wake()
        self.job.event("wake", {"by": "user"})
        return True

    def _check_stop(self) -> None:
        if self.job.stop_requested():
            raise StopRequested

    def _check_deadline(self) -> None:
        """Raise ``Halted`` once the deadline has passed: no new run, resume or wait."""
        stop = self.job.load().bounds.deadline_stop()
        if stop and stop.phase(self.clock()) is not Phase.OPEN:
            raise Halted(stop.reason(Phase.GRACEFUL))

    def _finish(self, status: JobStatus, reason: str) -> JobStatus:
        self.job.update(lambda st: st.mark(status, reason))
        self.job.event("end", {"status": status, "reason": reason})
        return status

"""Run a command job once: exit 0 is done, 75 a usage limit, anything else a failure.

A failure whose output names a network error (``ENOTFOUND``, "Can't reach the
API server") is ``OFFLINE`` instead, so the supervisor waits for the network.

75 is ``EX_TEMPFAIL``, which agile-team already exits with on a usage limit.
The reset time comes from the last ``TAIL_LINES`` lines of output. Output is
appended to ``output.log``. The command runs in its own process group, so
stopping the job also stops whatever the command started.
"""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .limits import (
    LIMIT_PATTERNS,
    NETWORK_PATTERNS,
    RESET_NOTE,
    Outcome,
    OutcomeKind,
    find_reason,
)
from .store import LOG_FILE, Job, JobState

LIMIT_EXIT = 75
TAIL_LINES = 50
TAIL_BYTES = 64 * 1024
TERM_GRACE = 30.0
DEFAULT_LIMIT_REASON = f"usage limit (exit {LIMIT_EXIT})"
# A stated reset beats a bare "hit your limit", wherever the reset line is.
COMMAND_LIMIT_PATTERNS = LIMIT_PATTERNS[:1] + RESET_NOTE + LIMIT_PATTERNS[1:]


@dataclass(frozen=True)
class CommandJob:
    """Runs the job's command, or its resume command after the first run."""

    job: Job
    env: Mapping[str, str]

    def run_once(self) -> Outcome:
        state = self.job.load()
        log = self.job.path(LOG_FILE)
        with log.open("a") as out:
            out.write(f"--- run {state.runs + 1}: {command_for(state)}\n")
            out.flush()
            code = self._run(state, out.fileno())
        return outcome_for(code, tail(log))

    def _run(self, state: JobState, out: int) -> int:
        proc = subprocess.Popen(
            command_for(state),
            shell=True,
            cwd=state.spec.cwd,
            env=dict(self.env),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return proc.wait()
        finally:
            end(proc)


def command_for(state: JobState) -> str:
    """The command for the next run: the resume command once the job has run."""
    spec = state.spec
    return (spec.resume_command or spec.command) if state.runs else spec.command


def end(proc: subprocess.Popen[bytes]) -> None:
    """SIGTERM the command's process group if it still runs; SIGKILL it after a grace."""
    if proc.poll() is not None:
        return
    os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(TERM_GRACE)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


def tail(path: Path) -> str:
    """The last ``TAIL_LINES`` lines of ``path``."""
    with path.open("rb") as log:
        log.seek(max(0, path.stat().st_size - TAIL_BYTES))
        text = log.read().decode(errors="replace")
    return "\n".join(text.splitlines()[-TAIL_LINES:])


def _limit(text: str) -> Outcome:
    reason = find_reason(COMMAND_LIMIT_PATTERNS, text) or DEFAULT_LIMIT_REASON
    return Outcome(OutcomeKind.LIMIT, reason)


EXIT_OUTCOMES: dict[int, Callable[[str], Outcome]] = {
    0: lambda text: Outcome(OutcomeKind.DONE),
    LIMIT_EXIT: _limit,
}


def outcome_for(code: int, text: str) -> Outcome:
    """The outcome for an exit code and the output's tail."""
    handler = EXIT_OUTCOMES.get(code)
    return handler(text) if handler else _failed(code, text)


def _failed(code: int, text: str) -> Outcome:
    offline = find_reason(NETWORK_PATTERNS, text)
    if offline:
        return Outcome(OutcomeKind.OFFLINE, f"{offline}, exit code {code}")
    return Outcome(OutcomeKind.FAILED, f"exit code {code}")

"""Run a command job once: exit 0 is done, 75 a usage limit, anything else a failure.

A failure whose output names a network error (``ENOTFOUND``, "Can't reach the
API server") is ``OFFLINE`` instead, so the supervisor waits for the network.

75 is ``EX_TEMPFAIL``, which agile-team already exits with on a usage limit.
The limit reason comes from the first source that gives one: agile-team's halt
line in the last ``TAIL_LINES`` lines of output, its ``state.json`` status
reason, then free text (``resets`` only with a readable time). Output is
appended to ``output.log``. The command runs in its own process group, so
stopping the job also stops whatever the command started.
"""

from __future__ import annotations

import json
import os
import re
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

HALT_LINE = re.compile(
    r"^agile-team start: (?P<reason>[^\n]+?); run `agile-team start --resume`", re.MULTILINE
)
STATUS_FILE = Path(".team/run/state.json")
BLOCKED = "blocked"


@dataclass(frozen=True)
class RunOutput:
    """What a finished command left: its output's tail and its working directory."""

    text: str
    cwd: Path


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
        return outcome_for(code, RunOutput(tail(log), Path(state.spec.cwd)))

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


def halt_reason(output: RunOutput) -> str | None:
    """The reason on agile-team's last halt line in the tail, or None."""
    found = list(HALT_LINE.finditer(output.text))
    return found[-1]["reason"] if found else None


def status_reason(output: RunOutput) -> str | None:
    """agile-team's ``status_reason`` when its state.json in cwd says ``blocked``, or None."""
    try:
        data = json.loads((output.cwd / STATUS_FILE).read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("status") != BLOCKED:
        return None
    reason = data.get("status_reason")
    return reason if isinstance(reason, str) and reason else None


def text_reason(output: RunOutput) -> str | None:
    """A limit named in free text; ``resets`` counts only with a readable time."""
    return find_reason(COMMAND_LIMIT_PATTERNS, output.text)


REASON_SOURCES: tuple[Callable[[RunOutput], str | None], ...] = (
    halt_reason,
    status_reason,
    text_reason,
)


def limit_reason(output: RunOutput) -> str:
    """The first reason a source gives, in ``REASON_SOURCES`` order, else the default."""
    return next((r for source in REASON_SOURCES if (r := source(output))), DEFAULT_LIMIT_REASON)


def _limit(output: RunOutput) -> Outcome:
    return Outcome(OutcomeKind.LIMIT, limit_reason(output))


EXIT_OUTCOMES: dict[int, Callable[[RunOutput], Outcome]] = {
    0: lambda output: Outcome(OutcomeKind.DONE),
    LIMIT_EXIT: _limit,
}


def outcome_for(code: int, output: RunOutput) -> Outcome:
    """The outcome for an exit code and what the command left."""
    handler = EXIT_OUTCOMES.get(code)
    return handler(output) if handler else _failed(code, output)


def _failed(code: int, output: RunOutput) -> Outcome:
    offline = find_reason(NETWORK_PATTERNS, output.text)
    if offline:
        return Outcome(OutcomeKind.OFFLINE, f"{offline}, exit code {code}")
    return Outcome(OutcomeKind.FAILED, f"exit code {code}")

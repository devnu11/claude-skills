"""Parking: a run hands a wait on an external job to the supervisor (``$UNATTENDED_PARK``).

A run that started something slow outside the session (a CI build, a hardware
test, a long export) writes ``park.json`` at the path in ``$UNATTENDED_PARK``::

    {"check": "gh run view 123 --exit-status", "every": "5m", "reason": "CI run 123"}

``check`` is a shell command, run in the job's ``--cwd``, that exits 0 once the
external job is done. ``every`` is how often to run it (default ``5m``), and
``reason`` says what the job waits for. A prompt run ends at its next tool step
once the file appears (``stop_when_parked``); a command job just exits 0. The
run's outcome becomes ``PARKED`` (``settle_park``), and the supervisor waits,
spending nothing, running the check until it passes. The file outlives the
supervisor, so ``resume`` after a crash or reboot goes back to waiting on it.

A file that does not parse is removed and logged as ``park-invalid``; a prompt
run is also told why at its next step, so it can write a valid one.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

from .limits import Outcome, OutcomeKind, parse_duration
from .steps import Advice
from .store import Job

PARK_FILE = "park.json"
PARK_ENV = "UNATTENDED_PARK"
DEFAULT_EVERY = "5m"
CHECK_TIMEOUT = 120  # seconds one check may take; a slower check counts as not done
FIELDS = {"check", "every", "reason"}


class ParkError(Exception):
    """``park.json`` cannot be used; the message lists why."""


@dataclass(frozen=True)
class Park:
    """A parked run's wait: the check command, its interval in seconds, and why."""

    check: str
    every: float
    reason: str


def read_park(job: Job) -> Park | None:
    """The job's park request, None when there is none; ``ParkError`` when unusable."""
    path = job.path(PARK_FILE)
    if not path.is_file():
        return None
    try:
        return parse_park(json.loads(path.read_text()))
    except (ValueError, TypeError) as error:
        raise ParkError(str(error)) from error


def parse_park(data: Any) -> Park:
    """``data`` as a ``Park``; ``ValueError`` naming each problem."""
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    problems = find_park_problems(data)
    if problems:
        raise ValueError("; ".join(problems))
    every = parse_duration(data.get("every", DEFAULT_EVERY))
    return Park(data["check"], every, data.get("reason") or data["check"])


def find_park_problems(data: dict[str, Any]) -> list[str]:
    """Unknown keys, a missing or empty ``check``, and text fields that are not text."""
    unknown = [f"{key}: not a park field" for key in sorted(data.keys() - FIELDS)]
    check = data.get("check")
    missing = [] if isinstance(check, str) and check.strip() else ["check: a command is required"]
    texts = [f"{key}: expected text" for key in ("every", "reason") if not is_text(data, key)]
    return unknown + missing + texts


def is_text(data: dict[str, Any], key: str) -> bool:
    """True when ``key`` is absent or holds text."""
    return isinstance(data.get(key, ""), str)


def find_park(job: Job) -> Park | None:
    """The job's park request; an unusable one is refused and counts as none."""
    try:
        return read_park(job)
    except ParkError as error:
        deny_park(job, error)
        return None


def deny_park(job: Job, error: ParkError) -> None:
    """Remove an unusable ``park.json`` and log why."""
    remove_park(job)
    job.event("park-invalid", {"problems": str(error)})


def remove_park(job: Job) -> None:
    """Remove ``park.json``: the wait is over or the request was refused."""
    job.path(PARK_FILE).unlink(missing_ok=True)


def stop_when_parked(job: Job) -> Advice:
    """A step check: end the run once it has parked; say why a bad request was refused."""
    try:
        park = read_park(job)
    except ParkError as error:
        deny_park(job, error)
        return Advice(f"{PARK_FILE} was refused and removed, so nothing is parked: {error}")
    return Advice(stop=f"parked: {park.reason}") if park else Advice()


def settle_park(job: Job, outcome: Outcome) -> Outcome:
    """``PARKED`` for a run that ended by itself with a usable park request, else ``outcome``."""
    park = find_park(job) if outcome.kind is OutcomeKind.DONE else None
    if park is None:
        return outcome
    return Outcome(OutcomeKind.PARKED, f"parked: {park.reason}", outcome.metrics)


def run_check(command: str, cwd: str) -> bool:
    """True once ``command`` exits 0 in ``cwd``; a check that times out is not done."""
    try:
        done = subprocess.run(
            command, shell=True, cwd=cwd, capture_output=True, timeout=CHECK_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return False
    return done.returncode == 0

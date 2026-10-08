"""Why the runner stopped: classify an exception as a ``Halt``; tracebacks go to ``crash.log``."""

from __future__ import annotations

import asyncio
import re
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .state import RunStatus

CRASH_LOG = "crash.log"
SIGTERM_REASON = "stopped by stop --now"
REASON_LIMIT = 200
RESUME = "run `agile-team start --resume`"


class HaltKind(StrEnum):
    """The ways a run can stop on its own."""

    LIMIT = "limit"
    CRASH = "crash"
    SIGTERM = "sigterm"


@dataclass(frozen=True)
class HaltRule:
    """What a kind of halt does: run status, liaison note kind, exit code, advice."""

    status: RunStatus
    note_kind: str
    exit_code: int
    advice: str


HALTS: dict[HaltKind, HaltRule] = {
    HaltKind.LIMIT: HaltRule(RunStatus.BLOCKED, "blocked", 75, f"{RESUME} after the reset"),
    HaltKind.CRASH: HaltRule(
        RunStatus.FAILED, "failed", 70, f"details in .team/run/{CRASH_LOG}; {RESUME} to continue"
    ),
    HaltKind.SIGTERM: HaltRule(RunStatus.STOPPED, "stopped", 143, f"{RESUME} to continue"),
}


@dataclass(frozen=True)
class Halt:
    """A classified stop: its kind and the stored reason."""

    kind: HaltKind
    reason: str

    @property
    def rule(self) -> HaltRule:
        return HALTS[self.kind]

    def message(self) -> str:
        """The reason plus what to do next; the liaison note and the printed line."""
        return f"{self.reason}; {self.rule.advice}"


def _pattern(regex: str) -> re.Pattern[str]:
    return re.compile(regex, re.IGNORECASE)


LIMIT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_pattern(r"hit your (?P<kind>[\w ]+?) limit\W+resets (?P<reset>[^\n]*\S)"),
     "{kind} limit, resets {reset}"),
    (_pattern(r"hit your (?P<kind>[\w ]+?) limit"), "{kind} limit"),
    (_pattern(r"(?P<kind>usage) limit reached"), "{kind} limit reached"),
)  # fmt: skip


def leaves(exc: BaseException) -> list[BaseException]:
    """``exc``, or the flattened leaf exceptions of an exception group."""
    if not isinstance(exc, BaseExceptionGroup):
        return [exc]
    return [leaf for inner in exc.exceptions for leaf in leaves(inner)]


def _limit_reason(text: str) -> str | None:
    for pattern, template in LIMIT_PATTERNS:
        match = pattern.search(text)
        if match:
            return template.format(**match.groupdict()).strip()
    return None


def limit_halt(exc: BaseException) -> Halt | None:
    """A ``limit`` halt when any leaf's message matches a limit pattern."""
    reasons = (_limit_reason(str(leaf)) for leaf in leaves(exc))
    reason = next((r for r in reasons if r), None)
    return Halt(HaltKind.LIMIT, reason) if reason else None


def sigterm_halt(exc: BaseException) -> Halt | None:
    """A ``sigterm`` halt when any leaf is a cancellation."""
    if any(isinstance(leaf, asyncio.CancelledError) for leaf in leaves(exc)):
        return Halt(HaltKind.SIGTERM, SIGTERM_REASON)
    return None


def crash_halt(exc: BaseException) -> Halt:
    """A ``crash`` halt naming the first leaf's type and first message line."""
    leaf = leaves(exc)[0]
    lines = str(leaf).splitlines()
    detail = f": {lines[0][:REASON_LIMIT]}" if lines else ""
    return Halt(HaltKind.CRASH, f"crashed: {type(leaf).__name__}{detail}")


DETECTORS: tuple[Callable[[BaseException], Halt | None], ...] = (
    limit_halt,
    sigterm_halt,
    crash_halt,
)


def classify(exc: BaseException) -> Halt:
    """The halt for ``exc``: limit first, then sigterm, else crash."""
    return next(h for h in (d(exc) for d in DETECTORS) if h)


def log_traceback(run_dir: Path, exc: BaseException) -> None:
    """Append ``exc``'s traceback to ``crash.log`` under a timestamped header."""
    run_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    entry = f"--- {stamp} {type(exc).__name__}\n" + "".join(traceback.format_exception(exc))
    with (run_dir / CRASH_LOG).open("a") as log:
        log.write(entry + "\n")

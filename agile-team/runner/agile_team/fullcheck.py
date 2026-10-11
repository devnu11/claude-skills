"""The full checks a sprint boundary runs: lint, static, test, coverage, each e2e.

``full_checks`` lists them from the config; ``run_checks`` runs every one (none
is skipped after a failure) with a command runner bound to the tree being
checked, and judges each by its table entry in ``JUDGES``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from . import boundary
from .config import Config
from .gates import CommandRunner, parse_coverage, tail


class Judge(StrEnum):
    """How a check's result is read."""

    EXIT = "exit"
    COVERAGE = "coverage"


TOOLCHAIN_CHECKS = (
    ("lint", Judge.EXIT),
    ("static", Judge.EXIT),
    ("test", Judge.EXIT),
    ("coverage", Judge.COVERAGE),
)
UNREADABLE = "could not read a coverage total"
BELOW = "coverage {pct}% is below {required}%"


@dataclass(frozen=True)
class FullCheck:
    """One command and how to judge it."""

    name: str
    command: str
    judge: Judge = Judge.EXIT


@dataclass(frozen=True)
class Judging:
    """The runner for the tree being checked, and the coverage it must reach."""

    run: CommandRunner
    required: float


@dataclass(frozen=True)
class CheckResult:
    """One check's outcome; ``why`` is empty when it passed."""

    check: FullCheck
    code: int
    why: str
    tail: str

    @property
    def passed(self) -> bool:
        return self.why == ""


@dataclass(frozen=True)
class CheckReport:
    """Every check's result."""

    results: tuple[CheckResult, ...]

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    def reason(self) -> str:
        """The failed checks, each in ``CHECK_FAILED`` format, blank-line separated."""
        failed = [r for r in self.results if not r.passed]
        return "\n\n".join(_failed_text(r) for r in failed)

    def summary(self) -> list[dict]:
        """Name, outcome and why for every check."""
        return [{"name": r.check.name, "passed": r.passed, "why": r.why} for r in self.results]


def _failed_text(result: CheckResult) -> str:
    check = result.check
    return boundary.CHECK_FAILED.format(
        name=check.name, why=result.why, command=check.command, tail=result.tail
    )


def full_checks(config: Config) -> list[FullCheck]:
    """The toolchain checks that are set, then each delivery's ``e2e``."""
    commands = config.toolchain.commands
    toolchain = [FullCheck(n, commands[n], j) for n, j in TOOLCHAIN_CHECKS if commands.get(n)]
    e2e = [FullCheck(f"e2e:{d.name}", d.e2e) for d in config.deliveries if d.e2e]
    return toolchain + e2e


def _exit_why(code: int, output: str, required: float) -> str:
    return "" if code == 0 else f"exit {code}"


def _coverage_why(code: int, output: str, required: float) -> str:
    pct = parse_coverage(output)
    if code != 0:
        return f"exit {code}"
    if pct is None:
        return UNREADABLE
    return "" if pct >= required else BELOW.format(pct=pct, required=required)


JUDGES: dict[Judge, Callable[[int, str, float], str]] = {
    Judge.EXIT: _exit_why,
    Judge.COVERAGE: _coverage_why,
}


def _run_one(check: FullCheck, judging: Judging) -> CheckResult:
    code, output = judging.run(check.command)
    why = JUDGES[check.judge](code, output, judging.required)
    return CheckResult(check, code, why, tail(output))


def run_checks(checks: list[FullCheck], judging: Judging) -> CheckReport:
    """Run every check and collect the results."""
    return CheckReport(tuple(_run_one(c, judging) for c in checks))

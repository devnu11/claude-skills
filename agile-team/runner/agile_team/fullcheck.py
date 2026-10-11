"""The full checks a sprint boundary runs: lint, static, test, coverage, each delivery's e2e."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from . import gates
from .boundary import CHECK_FAILED
from .config import Config
from .gates import CommandRunner


class Judge(StrEnum):
    """How a check's result is judged."""

    EXIT = "exit"
    COVERAGE = "coverage"


TOOLCHAIN_CHECKS = (
    ("lint", Judge.EXIT),
    ("static", Judge.EXIT),
    ("test", Judge.EXIT),
    ("coverage", Judge.COVERAGE),
)


@dataclass(frozen=True)
class FullCheck:
    """One command to run and how to judge it."""

    name: str
    command: str
    judge: Judge = Judge.EXIT


@dataclass(frozen=True)
class Judging:
    """The runner bound to the tree being checked, and the coverage required."""

    run: CommandRunner
    required: float


@dataclass(frozen=True)
class CheckResult:
    """A check's outcome; ``why`` is empty when it passed."""

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
        """The failed checks, one block each, blank-line separated."""
        return "\n\n".join(_failed_text(r) for r in self.results if not r.passed)

    def summary(self) -> list[dict[str, object]]:
        """``name``, ``passed`` and ``why`` for each check."""
        return [{"name": r.check.name, "passed": r.passed, "why": r.why} for r in self.results]


def _failed_text(result: CheckResult) -> str:
    return CHECK_FAILED.format(
        name=result.check.name, why=result.why, command=result.check.command, tail=result.tail
    )


def _exit_why(code: int, output: str, judging: Judging) -> str:
    return "" if code == 0 else f"exit {code}"


def _coverage_why(code: int, output: str, judging: Judging) -> str:
    if code != 0:
        return f"exit {code}"
    total = gates.parse_coverage(output)
    if total is None:
        return "could not read a coverage total"
    below = total < judging.required
    return f"coverage {total}% is below {judging.required}%" if below else ""


JUDGES: dict[Judge, Callable[[int, str, Judging], str]] = {
    Judge.EXIT: _exit_why,
    Judge.COVERAGE: _coverage_why,
}


def full_checks(config: Config) -> list[FullCheck]:
    """Toolchain checks that are set, then each delivery's e2e command."""
    commands = config.toolchain.commands
    chosen = [FullCheck(n, commands[n], j) for n, j in TOOLCHAIN_CHECKS if commands.get(n)]
    e2e = [FullCheck(f"e2e:{d.name}", d.e2e) for d in config.deliveries if d.e2e]
    return [*chosen, *e2e]


def _run_one(check: FullCheck, judging: Judging) -> CheckResult:
    code, output = judging.run(check.command)
    return CheckResult(check, code, JUDGES[check.judge](code, output, judging), gates.tail(output))


def run_checks(checks: list[FullCheck], judging: Judging) -> CheckReport:
    """Run every check, none skipped after a failure."""
    return CheckReport(tuple(_run_one(c, judging) for c in checks))

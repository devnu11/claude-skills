"""The full checks a sprint boundary runs: lint, static, test, coverage, each environment's e2e.

``test`` runs only when no ``coverage`` command is set: the coverage run proves green too (s73).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from . import gates, test_reports
from .boundary import CHECK_FAILED
from .commands import TIMED_OUT, CommandRunner
from .config import TEST_COMMANDS, Config

TIMED_OUT_WHY = "timed out"


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
SUPERSEDED_BY: dict[str, str] = {"test": "coverage"}  # one coverage run proves green (s73 F1)


def _wanted(name: str, commands: Mapping[str, str]) -> bool:
    """Whether check ``name`` runs: its command is set and no set command supersedes it."""
    return bool(commands.get(name)) and not commands.get(SUPERSEDED_BY.get(name, ""))


@dataclass(frozen=True)
class FullCheck:
    """One command to run and how to judge it."""

    name: str
    command: str
    judge: Judge = Judge.EXIT
    built: test_reports.Built | None = None


@dataclass(frozen=True)
class Judging:
    """The runner bound to the tree being checked, and the coverage required."""

    run: CommandRunner
    required: float

    def result(self, check: FullCheck, run: test_reports.TestRun) -> CheckResult:
        """The check's outcome from its run: why it failed and its tail."""
        timed_out = run.code == TIMED_OUT
        why = TIMED_OUT_WHY if timed_out else JUDGES[check.judge](run, self)
        failed = _collect_failed_ids(run)
        return CheckResult(check, run.code, why, gates.tail(run.out), failed)


@dataclass(frozen=True)
class CheckResult:
    """A check's outcome; ``why`` is empty when it passed."""

    check: FullCheck
    code: int
    why: str
    tail: str
    failed: tuple[str, ...] = ()  # the JUnit ids of the failed cases

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

    @property
    def failing_ids(self) -> list[str]:
        """The known failures: each failed check's failed test ids, or its name when it has none."""
        ids = (i for r in self.results if not r.passed for i in (r.failed or (r.check.name,)))
        return list(dict.fromkeys(ids))

    def summary(self) -> list[dict[str, object]]:
        """``name``, ``passed`` and ``why`` for each check."""
        return [{"name": r.check.name, "passed": r.passed, "why": r.why} for r in self.results]


def _collect_failed_ids(run: test_reports.TestRun) -> tuple[str, ...]:
    if run.report is None:
        return ()
    return tuple(c.id for c in run.report.failed())


def _failed_text(result: CheckResult) -> str:
    return CHECK_FAILED.format(
        name=result.check.name, why=result.why, command=result.check.command, tail=result.tail
    )


def _exit_why(run: test_reports.TestRun, judging: Judging) -> str:
    return "" if run.code == 0 else f"exit {run.code}"


def _coverage_why(run: test_reports.TestRun, judging: Judging) -> str:
    if run.code != 0:
        return _failed_why(run, judging)
    return _total_why(gates.parse_coverage(run.out), judging.required)


def _failed_why(run: test_reports.TestRun, judging: Judging) -> str:
    """A run stopped only by coverage reads as a shortfall (s68 C4); any other is ``exit N``."""
    total = gates.coverage_shortfall(run.out, judging.required)
    return f"exit {run.code}" if total is None else _total_why(total, judging.required)


def _total_why(total: float | None, required: float) -> str:
    """Why a coverage total fails, or empty when it meets ``required``."""
    if total is None:
        return "could not read a coverage total"
    return f"coverage {total}% is below {required}%" if total < required else ""


JUDGES: dict[Judge, Callable[[test_reports.TestRun, Judging], str]] = {
    Judge.EXIT: _exit_why,
    Judge.COVERAGE: _coverage_why,
}


def _toolchain_check(
    config: Config, reporting: test_reports.Reporting
) -> Callable[[str, Judge], FullCheck]:
    commands = config.toolchain.commands

    def make(name: str, judge: Judge) -> FullCheck:
        reported = reporting.options.on and name in TEST_COMMANDS
        built = test_reports.build(commands[name], reporting) if reported else None
        return FullCheck(name, commands[name], judge, built)

    return make


def full_checks(config: Config) -> list[FullCheck]:
    """Toolchain checks that are set (``test`` only without ``coverage``), then each e2e command."""
    commands = config.toolchain.commands
    reporting = test_reports.Reporting(
        config.toolchain.report, config.run_dir / test_reports.FOLDER
    )
    make = _toolchain_check(config, reporting)
    chosen = [make(n, j) for n, j in TOOLCHAIN_CHECKS if _wanted(n, commands)]
    e2e = [FullCheck(f"e2e:{d.name}", d.e2e) for d in config.environments if d.e2e]
    return [*chosen, *e2e]


def _plain_run(command: str, runner: CommandRunner) -> test_reports.TestRun:
    code, out = runner(command)
    return test_reports.TestRun(code, out, None)


def _test_run(check: FullCheck, judging: Judging) -> test_reports.TestRun:
    if check.built is None:
        return _plain_run(check.command, judging.run)
    return test_reports.run(check.built, judging.run)


def _run_one(check: FullCheck, judging: Judging) -> CheckResult:
    return judging.result(check, _test_run(check, judging))


def run_checks(checks: list[FullCheck], judging: Judging) -> CheckReport:
    """Run every check, none skipped after a failure."""
    return CheckReport(tuple(_run_one(c, judging) for c in checks))

"""s73: the sprint-boundary full check runs the suite once, as the coverage command."""

from pathlib import Path

import pytest
from agile_team import boundary, cli, fullcheck, gates, stages, system
from agile_team.fullcheck import FullCheck, Judge, Judging, full_checks, run_checks
from agile_team.gates import Verdict
from agile_team.pending_tests import Registry

from .conftest import FakeRunner
from .test_fullcheck import config_with

DESCRIPTION = (
    "Lint, static analysis, the full suite with coverage, once, "
    "and each environment's e2e, on the team branch"
)
SHORT = "TOTAL 1000 200 80%\nFAIL Required test coverage of 95% not reached\n200 passed"
PROTOCOL = Path(cli.__file__).parents[2] / "reference" / "protocol.md"


def names(scratch: Path, commands: dict) -> list[str]:
    return [f.name for f in full_checks(config_with(scratch, commands), Registry())]


def cov(output: str, code: int = 0, required: float = 95.0) -> fullcheck.CheckReport:
    runner = FakeRunner({"cov": (code, output)})
    return run_checks([FullCheck("coverage", "cov", Judge.COVERAGE)], Judging(runner, required))


# ----- F1 / AC1, AC3: one run -----------------------------------------------------------


def test_coverage_set_drops_the_test_check_and_runs_the_command_once(scratch: Path) -> None:
    c = config_with(scratch, {"lint": "l", "test": "t", "coverage": "cov"})
    checks = full_checks(c, Registry())
    assert [f.name for f in checks] == ["lint", "coverage"]
    runner = FakeRunner({"cov": (0, "TOTAL 96%")})
    report = run_checks(checks, Judging(runner, 95.0))
    assert report.passed
    assert runner.calls == ["l", "cov"]


def test_test_runs_when_no_coverage_command_is_set(scratch: Path) -> None:
    assert names(scratch, {"test": "t"}) == ["test"]
    assert names(scratch, {"test": "t", "coverage": ""}) == ["test"]


def test_static_still_precedes_coverage(scratch: Path) -> None:
    got = names(scratch, {"coverage": "c", "static": "s", "lint": "l", "test": "t"})
    assert got == ["lint", "static", "coverage"]


# ----- F2: data, not a branch -----------------------------------------------------------


def test_superseded_by_is_data_and_the_toolchain_rows_are_kept() -> None:
    assert fullcheck.SUPERSEDED_BY == {"test": "coverage"}
    assert fullcheck.TOOLCHAIN_CHECKS == (
        ("lint", Judge.EXIT),
        ("static", Judge.EXIT),
        ("test", Judge.EXIT),
        ("coverage", Judge.COVERAGE),
    )


# ----- F3-F6 / AC2: bounce texts --------------------------------------------------------


def test_exit_zero_below_required_is_a_shortfall() -> None:
    [r] = cov("TOTAL 100 20 80%").results
    assert r.why == "coverage 80.0% is below 95.0%"


def test_exit_zero_without_a_total_is_unreadable() -> None:
    [r] = cov("nothing").results
    assert r.why == "could not read a coverage total"


def test_exit_zero_at_required_passes() -> None:
    assert cov("TOTAL 100 5 95%").passed


def test_fail_under_stop_with_no_failing_test_reads_as_a_shortfall() -> None:
    [r] = cov(SHORT, code=1).results
    assert r.why == "coverage 80.0% is below 95.0%"


def test_a_failing_test_gives_exit_n_and_the_check_failed_block() -> None:
    out = "1 failed, 10 passed\nTOTAL 80%"
    report = cov(out, code=1)
    assert report.results[0].why == "exit 1"
    assert report.reason() == boundary.CHECK_FAILED.format(
        name="coverage", why="exit 1", command="cov", tail=gates.tail(out)
    )


def test_non_zero_exit_with_a_good_total_never_passes() -> None:
    report = cov("TOTAL 99%", code=1)
    assert not report.passed
    assert report.results[0].why == "exit 1"


def test_non_zero_exit_without_a_total_is_exit_n() -> None:
    assert cov("boom", code=2).results[0].why == "exit 2"


def test_a_timeout_is_timed_out() -> None:
    assert cov("TOTAL 99%", code=124).results[0].why == "timed out"


# ----- F7 / AC5: one shared helper ------------------------------------------------------


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("TOTAL 80%", 80.0),
        ("1 failed\nTOTAL 80%", None),
        ("TOTAL 96%", None),
        ("no total", None),
        ("", None),
    ],
)
def test_coverage_shortfall(output: str, expected: float | None) -> None:
    assert gates.coverage_shortfall(output, 95.0) == expected


def test_both_callers_use_the_one_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, float]] = []

    def stub(output: str, required: float) -> None:
        seen.append((output, required))

    monkeypatch.setattr(gates, "coverage_shortfall", stub)
    assert cov(SHORT, code=1).results[0].why == "exit 1"
    assert len(seen) == 1
    runner = FakeRunner({"C": (1, SHORT)})
    out = gates.Checks({"test": "T", "coverage": "C"}, 95.0, runner).tests_green_and_covered()
    assert out.verdict is Verdict.BOUNCE
    assert out.reason.startswith("tests fail")
    assert len(seen) == 2


# ----- F10 / AC3: description -----------------------------------------------------------


def test_the_stage_description_says_the_suite_runs_once() -> None:
    assert stages.STAGES[stages.Name.BOUNDARY_CHECK].description == DESCRIPTION


# ----- AC4: protocol.md -----------------------------------------------------------------


def flat_protocol() -> str:
    return " ".join(system.read_text(PROTOCOL).split())


@pytest.mark.parametrize(
    "token",
    [
        "runs the suite **once** (s73)",
        "as the `coverage` command",
        "`test` runs only when no `coverage` command is set",
        "`exit N`",
        "`coverage X% is below Y%`",
        "`gates.coverage_shortfall`",
    ],
)
def test_protocol_states_the_boundary_runs_the_suite_once(token: str) -> None:
    assert token in flat_protocol()

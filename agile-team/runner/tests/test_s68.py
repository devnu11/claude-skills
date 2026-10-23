"""s68: the implement gate runs the suite once, through the coverage command."""

import pytest
from agile_team import gates
from agile_team.gates import Verdict

from .conftest import FakeRunner

SHORT = "TOTAL 1000 200 80%\nFAIL Required test coverage of 95% not reached\n200 passed"


def made(results=None, baseline=None) -> tuple[gates.Checks, FakeRunner]:
    runner = FakeRunner(results)
    return gates.Checks({"test": "T", "coverage": "C"}, 95.0, runner, baseline), runner


def test_green_covered_run_runs_only_coverage() -> None:
    checks, runner = made({"C": (0, "TOTAL 96%")})
    out = checks.tests_green_and_covered()
    assert out.verdict is Verdict.PASS and out.reason == "coverage 96.0%"
    assert runner.calls == ["C"]


def test_failing_run_also_runs_only_coverage() -> None:
    checks, runner = made({"C": (1, "boom")})
    checks.tests_green_and_covered()
    assert runner.calls == ["C"]


def test_exit_zero_low_total_bounces() -> None:
    out = made({"C": (0, "TOTAL 80%")})[0].tests_green_and_covered()
    assert out.verdict is Verdict.BOUNCE
    assert out.reason.split("\n")[0] == "coverage 80.0% is below 95.0%"


def test_exit_zero_without_total_bounces() -> None:
    out = made({"C": (0, "nothing")})[0].tests_green_and_covered()
    assert "could not read a coverage total" in out.reason


def test_shortfall_that_stopped_the_run_is_a_coverage_bounce() -> None:
    out = made({"C": (1, SHORT)})[0].tests_green_and_covered()
    assert out.verdict is Verdict.BOUNCE
    assert out.reason.split("\n")[0] == "coverage 80.0% is below 95.0%"


LOW_SCOPE = "the total of `C` over everything it measures, not only this story's files; "


def test_a_shortfall_names_the_command_its_scope_and_no_baseline() -> None:
    out = made({"C": (0, "TOTAL 80%")})[0].tests_green_and_covered()
    assert out.reason.split("\n")[1] == LOW_SCOPE + (
        'the bar is [gates] coverage = 95.0%, and no .team/baseline.json "coverage" baseline '
        "lowers it for old debt"
    )


def test_a_shortfall_names_the_baseline_that_set_the_bar() -> None:
    out = made({"C": (0, "TOTAL 40%")}, baseline=51.0)[0].tests_green_and_covered()
    assert out.reason == (
        "coverage 40.0% is below 51.0%\n"
        + LOW_SCOPE
        + "the bar is the lower of [gates] coverage = 95.0% and the 51.0% in .team/baseline.json"
    )


@pytest.mark.parametrize("marker", ["1 failed, 10 passed", "1 error", "--- FAIL: TestX (0.0s)"])
def test_failing_test_is_tests_fail_even_with_low_total(marker: str) -> None:
    out = made({"C": (1, f"{marker}\nTOTAL 80%")})[0].tests_green_and_covered()
    assert out.verdict is Verdict.BOUNCE
    assert out.reason.startswith("tests fail:\n") and marker in out.reason


def test_nonzero_exit_with_high_total_never_passes() -> None:
    out = made({"C": (1, "TOTAL 99%")})[0].tests_green_and_covered()
    assert out.verdict is Verdict.BOUNCE and out.reason.startswith("tests fail:\n")


def test_nonzero_exit_without_total_is_tests_fail() -> None:
    out = made({"C": (2, "garbage")})[0].tests_green_and_covered()
    assert out.reason.startswith("tests fail:\n") and "garbage" in out.reason


def test_baseline_does_not_let_a_nonzero_exit_pass() -> None:
    out = made({"C": (1, "TOTAL 93%")}, baseline=90.0)[0].tests_green_and_covered()
    assert out.verdict is Verdict.BOUNCE and out.reason.startswith("tests fail:\n")


def test_coverage_timeout_is_the_timeout_bounce() -> None:
    checks, runner = made({"C": (124, "slow")})
    out = checks.tests_green_and_covered()
    assert "did not finish in time" in out.reason and runner.calls == ["C"]


@pytest.mark.parametrize("text", ["0 failed", "0 errors", "Coverage failure", "", "10 passed"])
def test_tests_failed_false(text: str) -> None:
    assert gates.tests_failed(text) is False


@pytest.mark.parametrize("text", ["2 failed", "1 error", "3 errors", "--- FAIL: TestY"])
def test_tests_failed_true(text: str) -> None:
    assert gates.tests_failed(text) is True


def test_green_failure_uses_shared_text() -> None:
    out = made({"T": (1, "boom")})[0].green()
    assert out.reason == gates.TESTS_FAIL.format(tail=gates.tail("boom"))
    assert out.reason.startswith("tests fail:\n")

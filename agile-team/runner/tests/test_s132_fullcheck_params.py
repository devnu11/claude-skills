"""s132: Judging.result takes the check and the test run; no function has over two parameters."""

import inspect

from agile_team import fullcheck
from agile_team.commands import TIMED_OUT
from agile_team.fullcheck import TIMED_OUT_WHY, FullCheck, Judge, Judging
from agile_team.test_reports import TestRun


def _runner(command: str) -> tuple[int, str]:
    return 0, ""


def _judging() -> Judging:
    return Judging(_runner, 95.0)


def test_every_function_has_at_most_two_parameters():
    funcs = inspect.getmembers(fullcheck, inspect.isfunction)
    own = [f for _, f in funcs if f.__module__ == "agile_team.fullcheck"]
    assert own
    for func in own:
        count = len(inspect.signature(func).parameters)
        assert count <= 2, f"{func.__name__} has {count} parameters"


def test_result_takes_check_and_run():
    params = list(inspect.signature(Judging.result).parameters)
    assert params == ["self", "check", "run"]
    assert len(params) == 3


def test_module_result_is_gone():
    assert not hasattr(fullcheck, "_result")
    assert hasattr(Judging, "result")


def test_plain_passing_run():
    result = _judging().result(FullCheck("a", "a"), TestRun(0, "ok", None))
    assert (result.why, result.code) == ("", 0)
    assert result.tail == "ok"


def test_timed_out_for_both_judges():
    run = TestRun(TIMED_OUT, "", None)
    for judge in Judge:
        result = _judging().result(FullCheck("a", "a", judge), run)
        assert result.why == TIMED_OUT_WHY, judge
        assert result.code == TIMED_OUT


def test_coverage_below_required():
    run = TestRun(0, "TOTAL 10 5 50%", None)
    result = _judging().result(FullCheck("a", "a", Judge.COVERAGE), run)
    assert result.why == "coverage 50.0% is below 95.0%"
    assert result.code == 0


def test_exit_failure_text():
    result = _judging().result(FullCheck("a", "a"), TestRun(2, "bad", None))
    assert (result.why, result.code, result.tail) == ("exit 2", 2, "bad")

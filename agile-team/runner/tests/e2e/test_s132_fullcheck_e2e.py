"""s132 e2e: run_checks judges plain checks through Judging.result (library API)."""

import inspect

from agile_team import fullcheck
from agile_team.fullcheck import FullCheck, Judging, run_checks


def _runner(command: str) -> tuple[int, str]:
    return (1, "boom") if command == "bad" else (0, "fine")


def test_run_checks_reports_pass_and_fail():
    report = run_checks([FullCheck("ok", "good"), FullCheck("no", "bad")], Judging(_runner, 95.0))
    ok, no = report.results
    assert (ok.code, ok.why) == (0, "")
    assert no.code == 1 and no.why


def test_result_signature_is_two_parameters():
    assert list(inspect.signature(Judging.result).parameters) == ["self", "check", "run"]
    assert not hasattr(fullcheck, "_result")

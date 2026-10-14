"""s29 U7: the full checks (lint, static, test, coverage, each environment's e2e)."""

from pathlib import Path

from agile_team import boundary, fullcheck, gates
from agile_team import config as cfg
from agile_team.fullcheck import CheckReport, FullCheck, Judge, Judging, full_checks, run_checks
from agile_team.pending_tests import Registry

from .conftest import FakeRunner


def config_with(scratch: Path, commands: dict, environments: list | None = None) -> cfg.Config:
    c = cfg.from_raw(scratch, {"environment": environments or []})
    c.toolchain.commands = commands
    return c


def test_order_is_toolchain_then_e2e_and_unset_are_left_out(scratch: Path) -> None:
    c = config_with(
        scratch,
        {"coverage": "cov", "test": "t", "lint": "l"},
        [
            {"name": "cli", "kind": "package", "e2e": "run-e2e"},
            {"name": "gui", "kind": "package"},
            {"name": "web", "kind": "package", "e2e": "run-web"},
        ],
    )
    assert full_checks(c, Registry()) == [
        FullCheck("lint", "l", Judge.EXIT),
        FullCheck("test", "t", Judge.EXIT),
        FullCheck("coverage", "cov", Judge.COVERAGE),
        FullCheck("e2e:cli", "run-e2e", Judge.EXIT),
        FullCheck("e2e:web", "run-web", Judge.EXIT),
    ]


def test_static_sits_between_lint_and_test(scratch: Path) -> None:
    c = config_with(scratch, {"test": "t", "static": "s", "lint": "l"})
    assert [f.name for f in full_checks(c, Registry())] == ["lint", "static", "test"]


def test_toolchain_table_order() -> None:
    assert fullcheck.TOOLCHAIN_CHECKS == (
        ("lint", Judge.EXIT),
        ("static", Judge.EXIT),
        ("test", Judge.EXIT),
        ("coverage", Judge.COVERAGE),
    )


def test_every_check_runs_even_after_a_failure() -> None:
    runner = FakeRunner({"a": (1, "boom"), "b": (0, "")})
    report = run_checks([FullCheck("a", "a"), FullCheck("b", "b")], Judging(runner, 95.0))
    assert runner.calls == ["a", "b"]
    assert not report.passed
    assert report.summary() == [
        {"name": "a", "passed": False, "why": "exit 1", "pending": ""},
        {"name": "b", "passed": True, "why": "", "pending": ""},
    ]


def test_all_pass() -> None:
    report = run_checks([FullCheck("a", "a")], Judging(FakeRunner(), 95.0))
    assert report.passed and report.reason() == ""


def test_empty_checks_pass() -> None:
    assert run_checks([], Judging(FakeRunner(), 95.0)).passed


def cov(output: str, required: float = 95.0, code: int = 0) -> CheckReport:
    runner = FakeRunner({"c": (code, output)})
    return run_checks([FullCheck("coverage", "c", Judge.COVERAGE)], Judging(runner, required))


def test_coverage_passes_at_the_threshold() -> None:
    assert cov("TOTAL 100 5 95%").passed


def test_coverage_below_required() -> None:
    [r] = cov("TOTAL 100 20 80%").results
    assert r.why == "coverage 80.0% is below 95.0%"


def test_coverage_baseline_lowers_the_required_value() -> None:
    assert cov("TOTAL 100 20 80%", required=80.0).passed


def test_coverage_unreadable() -> None:
    [r] = cov("no numbers here").results
    assert r.why == "could not read a coverage total"


def test_coverage_nonzero_exit_fails_with_exit_reason() -> None:
    [r] = cov("TOTAL 100 0 100%", code=2).results
    assert not r.passed and r.why == "exit 2"


def test_reason_holds_only_failed_checks_in_check_failed_format() -> None:
    runner = FakeRunner({"bad1": (1, "l1\nl2"), "bad2": (3, "x")})
    checks = [FullCheck("one", "bad1"), FullCheck("ok", "ok"), FullCheck("two", "bad2")]
    reason = run_checks(checks, Judging(runner, 1.0)).reason()
    expect = [
        boundary.CHECK_FAILED.format(
            name="one", why="exit 1", command="bad1", tail=gates.tail("l1\nl2")
        ),
        boundary.CHECK_FAILED.format(
            name="two", why="exit 3", command="bad2", tail=gates.tail("x")
        ),
    ]
    assert reason == "\n\n".join(expect)
    assert "ok failed" not in reason


def test_tail_is_the_last_thirty_lines() -> None:
    text = "\n".join(f"line{i}" for i in range(100))
    out = gates.tail(text)
    assert "line99" in out and "line70" in out and "line69" not in out


def test_check_failed_text() -> None:
    assert boundary.CHECK_FAILED == "{name} failed ({why}): {command}\n{tail}"

"""s68 end to end: the implement gate runs the coverage command once, with real shells."""

from __future__ import annotations

from pathlib import Path

from agile_team import gates
from agile_team.commands import CommandShell


def gate(tmp_path: Path, body: str, code: int) -> tuple[gates.Outcome, list[str]]:
    """Run the gate with a real coverage command; return the outcome and the runs logged."""
    log = tmp_path / "runs.log"
    cov = f"echo run >> {log}; printf '%b\\n' '{body}'; exit {code}"
    test = f"echo test >> {log}; exit 0"
    checks = gates.Checks({"test": test, "coverage": cov}, 95.0, CommandShell(tmp_path, 20.0).run)
    outcome = checks.tests_green_and_covered()
    return outcome, log.read_text().split() if log.exists() else []


def test_green_and_covered_passes_after_one_run(tmp_path: Path) -> None:
    outcome, runs = gate(tmp_path, "200 passed\\nTOTAL 100 0 96%", 0)
    assert outcome.verdict == gates.Verdict.PASS
    assert runs == ["run"]


def test_failing_suite_bounces_with_tests_fail_after_one_run(tmp_path: Path) -> None:
    outcome, runs = gate(tmp_path, "1 failed, 10 passed\\nTOTAL 100 0 80%", 1)
    assert outcome.verdict == gates.Verdict.BOUNCE
    assert outcome.reason.startswith("tests fail:\n")
    assert runs == ["run"]


def test_coverage_shortfall_bounces_with_the_shortfall_text(tmp_path: Path) -> None:
    body = "200 passed\\nTOTAL 100 20 80%\\nFAIL Required test coverage of 95% not reached"
    outcome, runs = gate(tmp_path, body, 1)
    assert outcome.reason.split("\n")[0] == "coverage 80.0% is below 95.0%"
    assert runs == ["run"]

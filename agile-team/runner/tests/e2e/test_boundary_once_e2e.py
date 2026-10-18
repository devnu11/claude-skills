"""s73 end to end: the boundary full check runs the suite once, with real shells."""

from __future__ import annotations

from pathlib import Path

from agile_team import config as cfg
from agile_team.commands import CommandShell
from agile_team.fullcheck import Judging, full_checks, run_checks


def boundary(tmp_path: Path, body: str, code: int) -> tuple[list[dict], list[str]]:
    """Run the full check with real test and coverage commands; return summary and runs."""
    log = tmp_path / "runs.log"
    c = cfg.from_raw(tmp_path, {"environment": []})
    c.toolchain.commands = {
        "test": f"echo test >> {log}; exit 0",
        "coverage": f"echo cov >> {log}; printf '%b\\n' '{body}'; exit {code}",
    }
    report = run_checks(full_checks(c), Judging(CommandShell(tmp_path, 20.0).run, 95.0))
    return report.summary(), (log.read_text().split() if log.exists() else [])


def test_green_and_covered_passes_with_one_run(tmp_path: Path) -> None:
    summary, runs = boundary(tmp_path, "200 passed\\nTOTAL 100 0 96%", 0)
    assert [s["name"] for s in summary] == ["coverage"]
    assert summary[0]["passed"] is True
    assert runs == ["cov"]


def test_coverage_shortfall_bounces_with_the_same_text(tmp_path: Path) -> None:
    summary, runs = boundary(tmp_path, "200 passed\\nTOTAL 100 20 80%", 0)
    assert summary[0]["why"] == "coverage 80.0% is below 95.0%"
    assert runs == ["cov"]


def test_failing_suite_bounces_with_exit_text(tmp_path: Path) -> None:
    summary, runs = boundary(tmp_path, "1 failed\\nTOTAL 100 0 99%", 1)
    assert summary[0]["why"] == "exit 1"
    assert runs == ["cov"]

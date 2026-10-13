"""s69 end to end: the real PreToolUse hook denies full pytest runs; briefs carry results."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from agile_team import guard
from agile_team.results import Ran, Results, section
from agile_team.suite_check import COVERAGE_DENIED, FULL_DENIED


def ask(role: str, command: str, tmp_path: Path) -> dict:
    """Run ``command`` as ``role`` through the real hook."""
    hook = guard.pre_tool_hook(guard.Scope(role, tmp_path, ["**"]))
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    return asyncio.run(hook(payload, None, None))


def reason(out: dict) -> str | None:
    """The deny reason, or None when the call is allowed."""
    return out.get("hookSpecificOutput", {}).get("permissionDecisionReason")


@pytest.mark.parametrize("role", ["developer-cli", "unit-tester", "integration-tester"])
def test_full_and_coverage_runs_are_denied_with_the_how_to(role: str, tmp_path: Path) -> None:
    assert reason(ask(role, "uv run pytest -q 2>&1 | tail -5", tmp_path)) == FULL_DENIED
    assert reason(ask(role, "pytest --cov=agile_team", tmp_path)) == COVERAGE_DENIED
    assert "run_new_tests" in FULL_DENIED and "run_tests" in FULL_DENIED


def test_named_tests_are_allowed(tmp_path: Path) -> None:
    assert ask("developer-cli", "pytest -q tests/test_x.py::test_y", tmp_path) == {}


def test_code_reviewer_may_not_run_tests_at_all(tmp_path: Path) -> None:
    out = ask("code-reviewer", "pytest -q tests/test_x.py", tmp_path)
    assert "code-reviewer reads tests and does not run them" in reason(out)


def test_brief_section_carries_kept_runner_results(tmp_path: Path) -> None:
    results = Results(tmp_path)
    results.keep("s1", Ran("coverage", 0, "TOTAL 100%", "abc1234", "implement gate"))
    results.keep("s1", Ran("lint", 0, "All checks passed", "abc1234", "quality"))
    text = section(results.shown("s1", "quality"))
    assert "## Runner results" in text and "TOTAL 100%" in text and "All checks passed" in text

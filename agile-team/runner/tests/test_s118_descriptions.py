"""s118 round 3 (AC12, AC13): stage descriptions in the snapshot (R11) and their texts (R12)."""

from __future__ import annotations

from pathlib import Path

import pytest
from agile_team import stages
from agile_team.stages import Name

from .test_snapshot import build, make_config

R12 = {
    "quality.lint": "Lint the whole repo before the quality step",
    "quality.static": "Static analysis of the whole repo before the quality step",
    "quality.coverage": "The full suite with coverage, for the quality step's report",
    "gate.tests-red": "Tests gate: the full suite must fail, so the story's new tests are red before any code",  # noqa: E501
    "gate.tests-rework": "Tests gate on a reworked story: the full suite may be red, or green with a tests claim",  # noqa: E501
    "gate.tests+coverage": "Implement gate: the full suite with coverage, once; every test must pass and coverage must meet the threshold",  # noqa: E501
    "gate.suite-runs": "The full suite again, the story's suite_runs times in a row, after its suite step's gate passes",  # noqa: E501
    "gate.dispute-output": "The full suite, to show a disputed test's output",
    "gate.route-lint": "Lint and static analysis of the whole repo, to route a failed gate's items to their owners",  # noqa: E501
    "gate.green": "The full suite must pass before the PO passes a story stuck at tests",
    "boundary.check": "Lint, static analysis, the full suite with coverage, once, and each environment's e2e, on the team branch; at a sprint start a failure is recorded as known failures and holds nothing",  # noqa: E501
    "runner-tool.run_tests": "Only the tests a developer named, run for that developer",
    "runner-tool.run_new_tests": "Only the story's new test files, run for a developer",
}


@pytest.mark.parametrize(("name", "text"), list(R12.items()))
def test_a_rewritten_stage_description(name: str, text: str) -> None:
    description = stages.STAGES[Name(name)].description
    assert description == text
    assert "\n" not in description


def test_the_stages_that_run_the_suite_say_full_suite() -> None:
    names = [n for n in R12 if n.startswith("gate.") and n != "gate.route-lint"]
    for name in [*names, "quality.coverage", "boundary.check"]:
        assert "full suite" in stages.STAGES[Name(name)].description


def test_the_snapshot_has_every_built_in_description(scratch: Path) -> None:
    got = build(make_config(scratch / "repo"), scratch)["stage_descriptions"]
    assert got == {str(n): s.description for n, s in stages.STAGES.items()}
    assert list(got) == [str(n) for n in stages.STAGES]


def test_a_repo_tool_adds_its_own_description(scratch: Path) -> None:
    tool = {"name": "deploy.preview", "description": "Deploy the branch to the preview site",
            "command": "make preview"}  # fmt: skip
    config = make_config(scratch / "repo", tool=[tool])
    got = build(config, scratch)["stage_descriptions"]
    assert got["deploy.preview"] == "Deploy the branch to the preview site"
    assert list(got)[-1] == "deploy.preview"
    assert got["gate.green"] == R12["gate.green"]

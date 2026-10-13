"""s92 AC6 end to end: real router, real git, a gate that reads the real files."""

from __future__ import annotations

from typing import Any

from agile_team.dispatch import shell_runner
from agile_team.events import EventKind
from agile_team.gates import StoryStatus

from ..conftest import git
from ..pipeline_helpers import Script, add_story, drive, step_roles

SRC = "src/a.py"
UNIT = "tests/test_limits.py"
E2E = "tests/e2e/test_git.py"
BAD = "BROKEN\n"
GOOD = "fine\n"


class FileRunner:
    """Gate commands: git is real; tests and lint fail while a file says BROKEN."""

    def __init__(self, repo):
        self.repo, self.real = repo, shell_runner(repo)

    def broken(self, rel: str) -> bool:
        return (self.repo / rel).read_text().startswith("BROKEN")

    def __call__(self, command: str) -> tuple[int, str]:
        if command.startswith("git "):
            return self.real(command)
        if command == "pytest --cov":
            return self.tests()
        return self.lint()

    def tests(self) -> tuple[int, str]:
        if self.broken(E2E):
            return 1, f"FAILED {E2E}::test_keep - AssertionError\n1 failed"
        if self.broken(SRC):
            return 1, "FAILED tests/test_x.py::test_a - AssertionError\n1 failed"
        return 0, "TOTAL   10   0   100%"

    def lint(self) -> tuple[int, str]:
        if self.broken(UNIT):
            return 1, f"{UNIT}:8:1: I001 unsorted imports"
        return 0, ""


def writer(rel: str, text: str):
    """A role action that rewrites one file."""

    async def action(rt) -> None:
        (rt.config.repo / rel).write_text(text)

    return action


def world(make_runtime, configured, replies, **files: str):
    """A repo with every file committed, a story at implement and a scripted team."""
    for rel, text in ({SRC: GOOD, UNIT: GOOD, E2E: GOOD} | files).items():
        (configured / rel).parent.mkdir(parents=True, exist_ok=True)
        (configured / rel).write_text(text)
    git(configured, "add", "-A")
    git(configured, "commit", "-q", "-m", "files")
    script = Script(replies)
    rt = make_runtime(script, runner=FileRunner(configured))
    script.rt = rt
    rt.pipeline.steps = ["tests", "implement", "e2e"]
    return script, rt


def gates(rt) -> list[Any]:
    return [e.data for e in rt.events.events() if e.kind == EventKind.GATE]


def test_e2e_failure_at_implement_goes_to_the_integration_tester_and_back(
    make_runtime, configured
) -> None:
    """AC1, AC2, AC4: the s65 case; no round, no dispute, no Manager step."""
    replies = {
        "developer": [writer(SRC, GOOD)],
        "integration-tester": [writer(E2E, GOOD)],
    }
    script, rt = world(make_runtime, configured, replies, **{E2E: BAD})
    add_story(rt, step="implement")
    drive(rt)
    story = rt.state.stories["s1"]
    assert step_roles(rt)[:3] == ["developer", "integration-tester", "developer"]
    assert "manager" not in step_roles(rt)
    assert (story.status, story.rounds, story.disputes) == (StoryStatus.DONE, 0, 0)
    assert gates(rt)[0]["verdict"] == "route"
    brief = script.prompts["integration-tester"][0]
    assert E2E in brief and "Gate fix on story s1" in brief
    assert [r.role for r in story.fixed] == ["integration-tester"]
    assert git(configured, "log", "-1", "--format=%s", "--", E2E).strip()


def test_lint_in_a_touched_test_file_goes_to_the_unit_tester(make_runtime, configured) -> None:
    """AC1, AC2: the s48 case; the unit-tester fixes its own lint, no round."""
    replies = {"unit-tester": [writer(UNIT, GOOD)]}
    script, rt = world(make_runtime, configured, replies, **{UNIT: BAD})
    add_story(rt, step="implement", files=[UNIT])
    drive(rt)
    story = rt.state.stories["s1"]
    assert step_roles(rt)[:3] == ["developer", "unit-tester", "developer"]
    assert (story.status, story.rounds, story.disputes) == (StoryStatus.DONE, 0, 0)
    assert UNIT in script.prompts["unit-tester"][0]


def test_a_failure_in_the_developers_own_files_stays_with_the_developer(
    make_runtime, configured
) -> None:
    """AC6: a red unit test is the developer's; a round is counted, nothing is routed."""
    replies = {"developer": [writer(SRC, BAD), writer(SRC, GOOD)]}
    _, rt = world(make_runtime, configured, replies)
    add_story(rt, step="implement")
    drive(rt)
    story = rt.state.stories["s1"]
    assert step_roles(rt)[:2] == ["developer", "developer"]
    assert gates(rt)[0]["verdict"] == "bounce" and story.fixes == []
    assert (story.status, story.rounds) == (StoryStatus.DONE, 1)

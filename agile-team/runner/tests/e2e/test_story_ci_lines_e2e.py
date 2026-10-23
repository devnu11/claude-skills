"""s172 e2e: a red story CI, read through GhPrs and a scripted gh, reaches PO and developer."""

from __future__ import annotations

import json
import os
from pathlib import Path

from agile_team.dispatch import StepRequest
from agile_team.gates import StoryState
from agile_team.po_tools import Start
from agile_team.upstream import GhPrs

from ..late import Late
from ..pipeline_helpers import add_story

story_ci = Late("story_ci")
sched = Late("scheduler")
HEAD = "b" * 40
RUFF_JOB = "https://github.com/o/r/actions/runs/1/job/77"
RULES_JOB = "https://github.com/o/r/actions/runs/1/job/78"
TEST_JOB = "https://github.com/o/r/actions/runs/1/job/79"
STAMP = "2026-10-23T10:00:00.0000000Z"
EVIDENCE = os.environ.get("S172_EVIDENCE")

LOGS = {
    "77": ("Run ruff", ["src/a.py:3:1: F401 `os` imported but unused", "Found 1 error."]),
    "78": (
        "Run house-rules",
        ["src/c.py:12: verb-name: compile_pattern is not a verb in function compile_pattern"],
    ),
    "79": ("Run tests", ["collected 3 items", "FAILED tests/test_x.py::test_y - assert 1 == 2"]),
}


class ScriptedGh:
    """A ``gh`` that answers the three calls a story-CI read makes; counts the calls."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], limit_s: float | None = None) -> tuple[int, str]:
        self.calls.append(argv)
        if argv[:2] == ["gh", "--version"] or argv[:3] == ["gh", "auth", "status"]:
            return 0, "ok"
        if "check-runs?per_page=100" in argv[-1]:
            return 0, json.dumps({"check_runs": [self.run_of(j) for j in LOGS]})
        if argv[2].startswith("repos/{owner}/{repo}/actions/jobs/"):
            return 0, json.dumps(self.job_of(argv[2].rsplit("/", 1)[1]))
        return 0, self.log_of(argv[argv.index("--job") + 1])

    @staticmethod
    def run_of(job: str) -> dict:
        url = f"https://github.com/o/r/actions/runs/1/job/{job}"
        name = {"77": "lint", "78": "house-rules", "79": "unit"}[job]
        return {
            "name": name,
            "status": "completed",
            "conclusion": "failure",
            "details_url": url,
        }

    @staticmethod
    def job_of(job: str) -> dict:
        step = LOGS[job][0]
        steps = [
            {"name": "Set up job", "conclusion": "success"},
            {"name": step, "conclusion": "failure"},
        ]
        return {"id": int(job), "head_sha": HEAD, "name": "x", "steps": steps}

    @staticmethod
    def log_of(job: str) -> str:
        step, lines = LOGS[job]
        noise = [f"later line {i}" for i in range(12)]
        return "\n".join(f"x\t{step}\t{STAMP} {t}" for t in [*lines, *noise])


def red_story(make_runtime):
    rt = make_runtime(prs=GhPrs(ScriptedGh()))
    story = add_story(rt, step="implement")
    story.pushed = HEAD
    poll = story_ci.StoryCiPoll(rt)
    assert poll.poll(story, 1000.0) is not None
    return rt, story, poll


def event_checks(rt) -> list[str]:
    [event] = [e for e in rt.events.events() if e.kind == "story-ci"]
    return event.data["checks"]


def test_the_event_names_each_failing_job_step_lines_and_link_ac1(make_runtime) -> None:
    rt, _, _ = red_story(make_runtime)
    checks = event_checks(rt)
    assert f"- lint: fail at step Run ruff {RUFF_JOB}" in checks
    assert f"- house-rules: fail at step Run house-rules {RULES_JOB}" in checks
    assert f"- unit: fail at step Run tests {TEST_JOB}" in checks
    assert "    src/a.py:3:1: F401 `os` imported but unused" in checks


def test_finding_lines_not_the_log_tail_are_shown_ac2(make_runtime) -> None:
    rt, _, _ = red_story(make_runtime)
    checks = event_checks(rt)
    assert any("compile_pattern is not a verb in function" in c for c in checks)
    assert "    FAILED tests/test_x.py::test_y - assert 1 == 2" in checks
    assert not any("later line" in c for c in checks)


def test_the_po_hand_over_lists_the_same_checks_ac1(make_runtime) -> None:
    rt = make_runtime()
    s = sched.Scheduler(rt, Start("task"))
    seen: list = []
    s.queue_pass = seen.append  # type: ignore[method-assign]
    checks = ["- lint: fail at step Run ruff " + RUFF_JOB, "    src/a.py:3:1: F401 x"]
    story = StoryState(id="s1", title="t", step="implement", sprint=1)
    s.queue_story_ci(story, story_ci.StoryCi(HEAD, "red", "pr", checks))
    text = "\n".join(seen[0].lines)
    assert "lint: fail at step Run ruff" in text and "    src/a.py:3:1: F401 x" in text


def test_the_developer_brief_holds_the_story_ci_section_ac3(make_runtime) -> None:
    rt, _, _ = red_story(make_runtime)
    prompt = rt.user_prompt(rt.plan(StepRequest("developer-cli", "go", "s1")))
    assert "## Story CI" in prompt
    assert f"lint: fail at step Run ruff {RUFF_JOB}" in prompt
    assert "    src/a.py:3:1: F401 `os` imported but unused" in prompt
    save_evidence(event_checks(rt), prompt)


def test_a_second_poll_fetches_nothing_new_ac1(make_runtime) -> None:
    rt, story, poll = red_story(make_runtime)
    before = len(rt.prs.run.calls)
    poll.poll(story, 1000.0 + story_ci.STORY_CI_POLL_S)
    logs = [c for c in rt.prs.run.calls[before:] if "--log-failed" in c]
    assert logs == []


def save_evidence(checks: list[str], prompt: str) -> None:
    if EVIDENCE:
        Path(EVIDENCE, "event-checks.txt").write_text("\n".join(checks) + "\n")
        Path(EVIDENCE, "developer-brief-excerpt.txt").write_text(
            prompt[prompt.index("## Story CI") :]
        )

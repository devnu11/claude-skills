"""s187 end to end: a gate fix names the gated commit and worktree; an empty done isn't a fix.

Real git; the gate's test command fails on one integration-tester file.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from agile_team.dispatch import StepRequest, shell_runner
from agile_team.events import EventKind
from agile_team.gates import StoryStatus

from ..conftest import git
from ..pipeline_helpers import Script, add_story

E2E_FILE = "tests/e2e/test_git.py"
FAIL = f"FAILED {E2E_FILE}::test_keep - AssertionError\n1 failed in 0.4s"


class Runner:
    """Gate commands: git is real; the test run fails on the e2e file; the rest is green."""

    def __init__(self, repo):
        self.real = shell_runner(repo)

    def __call__(self, command: str) -> tuple[int, str]:
        if command.startswith("git "):
            return self.real(command)
        return (1, FAIL) if command == "pytest --cov" else (0, "")


def build(make_runtime, configured):
    (configured / "tests" / "e2e").mkdir(parents=True)
    (configured / E2E_FILE).write_text("def test_keep():\n    assert 1 == 2\n")
    git(configured, "add", "-A")
    git(configured, "commit", "-q", "-m", "e2e")
    script = Script()
    rt = make_runtime(script, runner=Runner(configured))
    script.rt = rt
    add_story(rt, step="implement")
    return rt


def step(rt, role: str, kind: Any = None) -> dict[str, Any]:
    from agile_team.boundary import StepKind

    request = StepRequest(role, "go", "s1", kind or StepKind.ROLE)
    return asyncio.run(rt.run_role(request))


def start_brief(rt) -> str:
    starts = [e for e in rt.events.events() if e.kind == EventKind.STEP_START]
    return starts[-1].data["brief"]


def routed(make_runtime, configured):
    rt = build(make_runtime, configured)
    gated = git(configured, "rev-parse", "HEAD").strip()
    step(rt, "developer")
    return rt, gated


def test_the_fix_brief_names_the_gated_commit_and_the_worktree(make_runtime, configured) -> None:
    """AC1: the step-start brief has the gated short sha, the path and the head state."""
    from agile_team.boundary import StepKind

    rt, gated = routed(make_runtime, configured)
    step(rt, "integration-tester", StepKind.GATE_FIX)
    brief = start_brief(rt)
    assert f"The gate ran on commit {gated[:12]} in {configured}" in brief
    assert f"Its head is still {gated[:12]}." in brief


def test_an_empty_done_is_not_a_fix_and_the_second_escalates(make_runtime, configured) -> None:
    """AC2: done with no commit keeps the fix queued, then escalates; no round is spent."""
    from agile_team.boundary import StepKind

    rt, _ = routed(make_runtime, configured)
    report = step(rt, "integration-tester", StepKind.GATE_FIX)
    first = report["gate"]
    story = rt.state.stories["s1"]
    assert first["verdict"] == "route" and story.rounds == 0
    assert "handed off done with no commit" in first["reason"]
    second = step(rt, "integration-tester", StepKind.GATE_FIX)["gate"]
    assert "handed off done with no commit" in start_brief(rt)
    assert second["verdict"] == "escalate" and story.status is StoryStatus.NEEDS_MANAGER


def test_the_manager_context_shows_each_fix_with_commit_none(make_runtime, configured) -> None:
    """AC3: after the escalation the Manager's context carries fix_rounds with "none"."""
    from agile_team.boundary import StepKind

    rt, gated = routed(make_runtime, configured)
    step(rt, "integration-tester", StepKind.GATE_FIX)
    step(rt, "integration-tester", StepKind.GATE_FIX)
    story = rt.state.stories["s1"]
    story.repeated = "the same gate failure again"
    text = rt._manager_context(story)
    context = json.loads(text.split("Runner context:\n", 1)[1])
    [round_] = context["repeated_setback"]["fix_rounds"]
    assert round_["gated"] == gated[:12]
    assert [f["commit"] for f in round_["fixes"]] == ["none", "none"]
    assert {f["head"] for f in round_["fixes"]} == {gated[:12]}

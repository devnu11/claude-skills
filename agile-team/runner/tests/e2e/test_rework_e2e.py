"""s24 end to end: a ruled-back story passes tests on a green suite; a done story's hold clears."""

from __future__ import annotations

import asyncio
import json

from agile_team.dispatch import StepRequest, shell_runner
from agile_team.gates import StoryStatus
from agile_team.po_tools import Tools

from ..conftest import git, handoff
from ..pipeline_helpers import Script, add_story, drive, step_roles


class GreenGit:
    """Gate commands: git runs for real; the suite is always green."""

    def __init__(self, repo):
        self.real = shell_runner(repo)

    def __call__(self, command: str) -> tuple[int, str]:
        if command.startswith("git "):
            return self.real(command)
        return 0, "TOTAL   10   0   100%" if "cov" in command else "ok"


def build_rt(make_runtime, configured, replies):
    script = Script(replies)
    rt = make_runtime(script, runner=GreenGit(configured))
    script.rt = rt
    rt.pipeline.steps = ["design", "tests", "implement", "review"]
    return script, rt


def ruled_back(rt):
    """A reviewed story (code in) that the Manager sends back to design."""
    story = add_story(rt, step="review", implemented=1)
    rt.query_fn.replies["manager"] = [handoff("done", ruling="revise_design")]
    asyncio.run(rt.run_role(StepRequest("manager", "rule", "s1")))
    assert story.step == "design"
    return story


def test_ruled_back_story_finishes_with_a_plain_done_tests_step(make_runtime, configured) -> None:
    """AC4.2: revise_design -> design -> tests (plain done, no claim) -> implement -> review -> done."""
    _, rt = build_rt(make_runtime, configured, {"unit-tester": [handoff("done")]})
    story = ruled_back(rt)
    drive(rt)
    assert step_roles(rt)[1:5] == ["architect", "unit-tester", "developer", "code-reviewer"]
    assert story.status is StoryStatus.DONE and story.rounds == 0
    assert story.implemented == 2


def test_hold_on_a_done_story_is_cleared_and_the_story_stays_put(make_runtime, configured) -> None:
    """AC2: continue_story clears the hold on a done story; it never moves."""
    _, rt = build_rt(make_runtime, configured, {})
    story = add_story(rt, step="review", status=StoryStatus.DONE, hold="ruling_not_applied")
    out = asyncio.run(Tools(rt).continue_story({"story": "s1", "note": "ack"}))
    body = json.loads(out["content"][0]["text"])
    assert body == {"status": "continued", "story": "s1", "step": "review"}
    assert story.hold is None and story.step == "review" and story.status is StoryStatus.DONE
    saved = json.loads((rt.config.run_dir / "state.json").read_text())
    assert saved["stories"]["s1"]["hold"] is None
    report = asyncio.run(rt.run_role(StepRequest("developer", "go", "s1")))
    assert "story s1 is done" in str(report)
    assert git(configured, "status", "--porcelain").strip() == ""

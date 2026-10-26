"""s175 end to end: a real landing on real git whose CI read hits GitHub's rate-limit reply.

The scene is the s159 one; only the check-run read goes through ``GhPrs`` with a scripted ``gh``
that answers ``{`` (exit 1, HTTP 403). The scheduler runs the landing as it does in a sprint.
One test per AC id.
"""

from __future__ import annotations

import asyncio

from agile_team import halt, handover, scheduler, stages, system
from agile_team.boundary import StepKind
from agile_team.events import EventKind
from agile_team.gates import StoryState
from agile_team.po_tools import Start
from agile_team.router import Work
from agile_team.upstream import GhPrs

from ..test_s99_stages import runs
from .test_s151_as_built_end_e2e import Scene
from .test_s151_as_built_end_e2e import scene as scene_fixture
from .test_s159_landing_e2e import LandPrs, open_story, start_sprint

scene = scene_fixture
BODY = "{\ngh: rate limit (HTTP 403)"


class RateLimitedGh:
    """A gh runner that notes each call as the shell does and always answers the rate limit."""

    def __call__(self, argv: list[str]) -> tuple[int, str]:
        stages.note(" ".join(argv), 1)
        return 1, BODY


class RateLimitedPrs(LandPrs):
    """LandPrs whose check-run read goes through the real GhPrs and the scripted gh."""

    def list_checks(self, sha: str) -> list:
        return GhPrs(RateLimitedGh()).list_checks(sha)


def run_rate_limited_land(scene: Scene) -> tuple[list[dict], StoryState]:
    start_sprint(scene)
    scene.rt.prs = RateLimitedPrs()
    story = open_story(scene, "s1", "src/a.py", "a = 1\n")
    work = Work("developer-cli", story, "b", StepKind.LAND)
    s = scheduler.Scheduler(scene.rt, Start("task"))
    reports: list[dict] = []
    s.report_back = lambda _, report: reports.append(report)
    asyncio.run(s.run_work(work))
    return reports, story


def land_stage(scene: Scene) -> dict:
    [stage] = [r for r in runs(scene.rt.stage_log) if r.data["stage"] == "story.land"]
    return stage.data


def test_ac1_the_stage_event_carries_the_error_and_the_call_that_raised(scene: Scene) -> None:
    run_rate_limited_land(scene)
    data = land_stage(scene)
    assert data["raised"] == "UpstreamError"
    assert "HTTP 403" in data["error"] and "\n" not in data["error"] and len(data["error"]) <= 500
    assert data["detail"].startswith("gh api") and "/commits/" in data["detail"]
    assert data["code"] == 1


def test_ac2_the_traceback_goes_to_crash_log(scene: Scene) -> None:
    run_rate_limited_land(scene)
    log = system.read_text(scene.rt.config.run_dir / halt.CRASH_LOG)
    assert log.startswith("--- ") and "UpstreamError" in log and "Traceback" in log


def test_ac3_the_hand_over_and_hold_reason_name_the_command_and_status(scene: Scene) -> None:
    reports, _ = run_rate_limited_land(scene)
    assert reports[0]["status"] == "error"
    for text in (reports[0]["reason"], handover.hold_reason(reports[0])):
        assert "UpstreamError" in text and "HTTP 403" in text and "exit 1" in text
    assert EventKind  # events module is the real one

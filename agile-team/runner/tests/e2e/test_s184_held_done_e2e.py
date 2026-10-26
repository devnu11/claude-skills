"""s184 end to end on real git: a PO done sent during the sprint end boundary ends the run.

Uses the s151 scene (real git, a bare origin, fake PRs and CI). One group per AC id.
"""

from __future__ import annotations

import asyncio
import json

from agile_team import cli, repin, sprint_end
from agile_team.boundary import Stage
from agile_team.po_tools import Start, Tools
from agile_team.scheduler import Scheduler
from agile_team.state import RunState, RunStatus

from .test_s151_as_built_end_e2e import Scene, team_work
from .test_s151_as_built_end_e2e import scene as scene_fixture

scene = scene_fixture
REASON = "No further sprint, as instructed"


class FakePin:
    """Records the re-pin instead of exec'ing a new runner."""

    def __init__(self) -> None:
        self.markers: list[repin.Marker] = []

    def repin(self, marker: repin.Marker) -> None:
        self.markers.append(marker)


def po_says_done(scene: Scene) -> dict:
    """The PO's notify_user(kind=done) while the end boundary runs."""
    scene.rt.state.cadence = "until-blocker"
    team_work(scene)
    scene.open_end()
    scene.run_to(Stage.CI)
    return asyncio.run(_done(scene))


async def _done(scene: Scene) -> dict:
    out = await Tools(scene.rt).notify_user({"kind": "done", "text": f"{REASON}\ndetails"})
    return json.loads(out["content"][0]["text"])


def test_ac1_the_done_is_held_then_ends_the_run_after_a_repin(scene: Scene, monkeypatch) -> None:
    out = po_says_done(scene)
    state = scene.rt.state
    assert "held" in out and state.held_done == REASON and state.status is not RunStatus.DONE
    monkeypatch.setattr(repin, "pin_commit", lambda run_dir: "a" * 40)
    state.repin = "b" * 40
    pin = FakePin()
    cli._repin_or(0, scene.rt, pin)  # the passing end check re-pins the runner
    assert len(pin.markers) == 1 and state.status is RunStatus.IDLE
    scene.rt.save()
    scene.rt.state = RunState.from_json(scene.rt.state.to_json())  # the re-pinned process
    sched = Scheduler(scene.rt, Start(""))
    sched.begin()
    assert scene.rt.state.held_done == REASON  # begin marked running, the done survives
    scene.drive()
    assert scene.boundary is None
    sched.tick()
    assert sched.ended and scene.rt.state.keep_going_asks == 0  # no next-sprint hand-over
    assert scene.rt.state.status is RunStatus.DONE


def test_ac3_status_shows_done_and_the_reason(scene: Scene, capsys) -> None:
    po_says_done(scene)
    scene.rt.save()
    cli.main(["--repo", str(scene.repo), "status"])
    assert json.loads(capsys.readouterr().out)["held_done"] == REASON
    scene.drive()
    scene.rt.save()
    cli.main(["--repo", str(scene.repo), "status"])
    report = json.loads(capsys.readouterr().out)
    assert (report["status"], report["status_reason"]) == ("done", REASON)
    assert report["held_done"] is None


def test_ac2_the_next_sprint_hand_over_says_how_a_run_ends() -> None:
    advice = sprint_end.NEXT_SPRINT_ADVICE
    assert "--cadence sprint" in advice and "notify done quoting them" in advice

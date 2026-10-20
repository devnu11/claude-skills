"""s165 end to end: ``agile-team start --resume`` after a story step was cut off mid-run."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from agile_team import config as config_mod
from agile_team import state as state_mod
from agile_team.dispatch import Runtime, StepRequest
from agile_team.events import Event, EventKind
from agile_team.salvage import Cause, InFlight

from ..conftest import result_message, write_story
from .test_halt_e2e import (
    PoRunsRole,
    RoleWritesThenLimit,
    Router,
    saved,
    sdk_limit_error,
)
from .test_halt_e2e import (
    harness as harness_fixture,
)

harness = harness_fixture


class ResumedPo:
    """A PO turn after the resume: run the architect on s1 and keep what the role saw."""

    def __init__(self, holder: list[Runtime]):
        self.holder, self.seen = holder, {}

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        rt = self.holder[0]
        self.seen["interrupted"] = rt.state.stories["s1"].interrupted
        self.seen["step"] = rt.state.stories["s1"].step
        self.seen["report"] = await rt.run_role(StepRequest("architect", "design it", "s1"))
        yield result_message("back", session="po-sess")


class RoleRecorder:
    """A role query that records its prompt, worktree, resumed session and the edit it sees."""

    def __init__(self, seen: dict):
        self.seen = seen

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        cwd = Path(options.cwd)
        if cwd.name == "s1" and "prompt" not in self.seen:  # the first step in the worktree
            self.seen.update(prompt=prompt, cwd=cwd, resume=options.resume)
            self.seen["edit"] = (cwd / "src" / "oops.py").read_text()
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        yield result_message("working", session="role-sess")
        raise sdk_limit_error()  # stop the scheduler after the first resumed step


def test_ac1_ac2_a_cut_off_story_step_resumes(harness, configured: Path) -> None:
    start, holder = harness
    write_story(config_mod.load(configured), "s1", "cli")
    po = PoRunsRole(holder)
    assert start(Router(po, RoleWritesThenLimit(configured)), "--task", "t") == 75
    # The machine goes down with the step still in flight: put the run back to that moment.
    st = saved(configured)
    story = st.stories["s1"]
    story.in_flight = InFlight("architect", "s1", "design it", session="role-sess")
    story.interrupted = None
    state_mod.save(configured / ".team" / "run", st)
    events = holder[0].events
    events.emit(Event(EventKind.STEP_START, "architect", "s1", {"brief": "design it"}))
    seen_role: dict = {}
    resumed = ResumedPo(holder)
    start(Router(resumed, RoleRecorder(seen_role)), "--resume")
    cause = Cause.LIMIT
    ends = [
        e.data
        for e in holder[0].events.events()
        if e.kind == EventKind.STEP_END and e.story == "s1" and e.data.get("status") == "stopped"
    ]
    assert ends and "interrupted" in ends[0]
    assert "cut off" in seen_role["prompt"] and "uncommitted edits" in seen_role["prompt"]
    assert str(cause) in seen_role["prompt"]
    assert seen_role["cwd"].name == "s1" and seen_role["edit"] == "y = 2\n"
    assert seen_role["resume"] == "role-sess"

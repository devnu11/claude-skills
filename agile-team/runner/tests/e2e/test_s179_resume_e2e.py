"""s179 end to end: ``agile-team start --resume`` keeps an idle open story's worktree."""

from __future__ import annotations

import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from agile_team import config as config_mod
from agile_team import state as state_mod
from agile_team.events import EventKind

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
from .test_s165_resume_e2e import ResumedPo

harness = harness_fixture
IGNORED = ".venv/marker"


class IgnoredFileRecorder:
    """A role query that records whether the ignored file is in its worktree, then stops."""

    def __init__(self, seen: dict):
        self.seen = seen

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        cwd = Path(options.cwd)
        if cwd.name == "s1" and "cwd" not in self.seen:
            self.seen.update(cwd=cwd, ignored=(cwd / IGNORED).exists())
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        yield result_message("working", session="role-sess")
        raise sdk_limit_error()


def plant_ignored_file(worktree: Path) -> None:
    """Create a git-ignored file in the worktree, as a venv would be."""
    exclude = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "--git-path", "info/exclude"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    exclude_path = Path(exclude) if Path(exclude).is_absolute() else worktree / exclude
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    with exclude_path.open("a") as out:
        out.write(".venv/\n")
    (worktree / IGNORED).parent.mkdir(parents=True, exist_ok=True)
    (worktree / IGNORED).write_text("venv\n")


def test_ac1_ac2_ac3_a_resume_keeps_an_idle_stories_worktree(harness, configured: Path) -> None:
    start, holder = harness
    write_story(config_mod.load(configured), "s1", "cli")
    assert start(Router(PoRunsRole(holder), RoleWritesThenLimit(configured)), "--task", "t") == 75
    # Stop with no step in flight: the story is open, in the sprint, and its worktree stands.
    st = saved(configured)
    st.stories["s1"].in_flight = None
    st.stories["s1"].interrupted = None
    state_mod.save(configured / ".team" / "run", st)
    worktree = configured / ".team" / "run" / "worktrees" / "s1"
    assert worktree.is_dir()
    plant_ignored_file(worktree)
    head = saved(configured).stories["s1"].worktree_head
    seen: dict = {}
    start(Router(ResumedPo(holder), IgnoredFileRecorder(seen)), "--resume")
    assert (worktree / IGNORED).read_text() == "venv\n"  # AC1: not removed by the resume
    assert seen["ignored"] is True  # AC1: still there when the next step starts
    kinds = [e.kind for e in holder[0].events.events()]
    assert EventKind.WORKTREE_PRUNED not in kinds  # AC2: nothing to remove for an open story
    assert saved(configured).stories["s1"].worktree_head == head  # AC3: record left to the step

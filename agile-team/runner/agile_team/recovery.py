"""Save an interrupted step's edits and record it, for a halt or a run killed outright."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import checkout, halt, salvage
from . import state as state_mod
from .events import EVENTS, Event, EventKind, EventLog
from .git_ops import Git, GitError
from .salvage import Cause, Cut, Interruption
from .state import RunState


@dataclass
class Salvager:
    """Saves the tree for a cut-off step and records it on the state."""

    git: Git
    run_dir: Path

    def save(self, state: RunState, cause: Cause) -> Interruption | None:
        """Capture, record and log; the caller saves ``state.json``."""
        found = self._capture(Cut(cause, state.in_flight))
        if found is None:
            return None
        state.interrupt(found)
        self._log(found)
        return found

    def _capture(self, cut: Cut) -> Interruption | None:
        try:
            return salvage.capture(self.git, cut)
        except GitError as exc:
            halt.log_traceback(self.run_dir, exc)
            return None

    def _log(self, found: Interruption) -> None:
        data = {"cause": str(found.cause), "commit": found.sha, "brief": found.brief}
        event = Event(EventKind.STEP_INTERRUPTED, found.role, found.story, data)
        EventLog(self.run_dir / EVENTS).emit(event)


def recover_killed(run_dir: Path, git: Git) -> Interruption | None:
    """Save the edits of a run that was killed outright; ``None`` if it was not."""
    state = state_mod.load(run_dir)
    if state_mod.shown_status(run_dir, state) is not state_mod.RunStatus.INTERRUPTED:
        return None
    found = Salvager(git, run_dir).save(state, Cause.KILLED)
    state.checkout = checkout.recorded(git)
    state_mod.save(run_dir, state)
    return found

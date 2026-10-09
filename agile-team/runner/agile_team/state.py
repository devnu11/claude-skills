"""Run state in ``.team/run/state.json`` so ``start --resume`` can continue."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from .gates import StoryState, StoryStatus
from .providers import DEFAULT as DEFAULT_PROVIDER

STATE_FILE = "state.json"
STOP_FILE = "stop"
PID_FILE = "runner.pid"


class RunStatus(StrEnum):
    """The run as a whole.

    ``sprint-end``, ``blocked`` and ``done`` are set by the PO's ``notify_user``.
    ``blocked``, ``failed`` and ``stopped`` are set by the runner when it halts
    (see ``halt.HALTS``).
    """

    IDLE = "idle"
    RUNNING = "running"
    SPRINT_END = "sprint-end"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class ModelOverride:
    """A PO-set model change for one role, with the logged reason."""

    model: str
    effort: str
    reason: str
    provider: str = DEFAULT_PROVIDER


@dataclass
class RunState:
    """Everything the runner needs to resume."""

    cadence: str = "sprint"
    sprint: int = 0
    po_session: str | None = None
    status: RunStatus = RunStatus.IDLE
    stories: dict[str, StoryState] = field(default_factory=dict)
    overrides: dict[str, ModelOverride] = field(default_factory=dict)
    unreviewed: list[str] = field(default_factory=list)
    manager_due: list[str] = field(default_factory=list)
    status_reason: str | None = None
    task: str = ""

    def mark(self, status: RunStatus, reason: str | None = None) -> None:
        """Set the run status and why; no reason clears the old one."""
        self.status, self.status_reason = status, reason

    def runtime_overrides(self, role: str) -> dict[str, Any]:
        """Fields from a PO model override for ``role``, if any."""
        o = self.overrides.get(role)
        return {"model": o.model, "effort": o.effort, "provider": o.provider} if o else {}

    def halted(self) -> bool:
        """``done``/``blocked`` always halt; ``sprint-end`` halts only the sprint cadence."""
        if self.status in (RunStatus.DONE, RunStatus.BLOCKED):
            return True
        return self.status is RunStatus.SPRINT_END and self.cadence == "sprint"

    def unknown_stories(self, ids: list[str]) -> list[str]:
        """The ids that are not opened stories, in the order given."""
        return [i for i in ids if i not in self.stories]

    def begin_sprint(self, ids: list[str]) -> None:
        """Open the next sprint holding exactly ``ids``; other unfinished stories go back."""
        self.sprint += 1
        for sid, story in self.stories.items():
            if story.status != StoryStatus.DONE:
                story.sprint = self.sprint if sid in ids else None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> RunState:
        data = json.loads(text)
        data["status"] = RunStatus(data.get("status", RunStatus.IDLE))
        data["stories"] = {k: _story(v) for k, v in data.get("stories", {}).items()}
        data["overrides"] = {k: ModelOverride(**v) for k, v in data.get("overrides", {}).items()}
        return cls(**data)


def _story(data: dict[str, Any]) -> StoryState:
    return StoryState(**{**data, "status": StoryStatus(data.get("status", StoryStatus.ACTIVE))})


def load(run_dir: Path) -> RunState:
    path = run_dir / STATE_FILE
    return RunState.from_json(path.read_text()) if path.is_file() else RunState()


def save(run_dir: Path, state: RunState) -> None:
    """Write atomically so a crash mid-write never leaves a torn state file."""
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp = run_dir / f"{STATE_FILE}.tmp"
    tmp.write_text(state.to_json())
    tmp.replace(run_dir / STATE_FILE)

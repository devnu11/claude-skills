"""Run state in ``.team/run/state.json`` so ``start --resume`` can continue."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .gates import StoryState

STATE_FILE = "state.json"
STOP_FILE = "stop"
PID_FILE = "runner.pid"


@dataclass
class ModelOverride:
    """A PO-set model change, kept until the Manager has reviewed it."""

    model: str
    effort: str
    reason: str
    reviewed: bool = False


@dataclass
class RunState:
    """Everything the runner needs to resume."""

    cadence: str = "sprint"
    sprint: int = 0
    po_session: str | None = None
    status: str = "idle"
    stories: dict[str, StoryState] = field(default_factory=dict)
    overrides: dict[str, ModelOverride] = field(default_factory=dict)
    manager_due: list[str] = field(default_factory=list)

    def runtime_overrides(self, role: str) -> dict[str, Any]:
        """Fields from a PO model override for ``role``, if any."""
        o = self.overrides.get(role)
        return {"model": o.model, "effort": o.effort} if o else {}

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> RunState:
        data = json.loads(text)
        data["stories"] = {k: StoryState(**v) for k, v in data.get("stories", {}).items()}
        data["overrides"] = {k: ModelOverride(**v) for k, v in data.get("overrides", {}).items()}
        return cls(**data)


def load(run_dir: Path) -> RunState:
    path = run_dir / STATE_FILE
    return RunState.from_json(path.read_text()) if path.is_file() else RunState()


def save(run_dir: Path, state: RunState) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp = run_dir / f"{STATE_FILE}.tmp"
    tmp.write_text(state.to_json())
    tmp.replace(run_dir / STATE_FILE)

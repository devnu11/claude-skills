"""The chat's state on disk: transcript, summary, last addressee and decision log.

One ``state.json`` per chat directory, written atomically so a crash mid-write
leaves the previous state intact.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .decision_log import DecisionLog

STATE_FILE = "state.json"
HUMAN = "human"
ORCHESTRATOR = "orchestrator"


@dataclass(frozen=True)
class Turn:
    """One message in the shared thread."""

    speaker: str
    text: str

    def render(self) -> str:
        return f"@{self.speaker}: {self.text}"


@dataclass
class ChatState:
    """Everything a chat remembers between messages."""

    turns: list[Turn] = field(default_factory=list)
    summary: str = ""
    last_addressed: tuple[str, ...] = ()
    log: DecisionLog = field(default_factory=DecisionLog)

    def add(self, turn: Turn) -> None:
        self.turns.append(turn)
        self.log.apply(turn.speaker, turn.text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turns": [vars(turn) for turn in self.turns],
            "summary": self.summary,
            "last_addressed": list(self.last_addressed),
            "log": self.log.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatState:
        return cls(
            [Turn(**turn) for turn in data.get("turns", [])],
            data.get("summary", ""),
            tuple(data.get("last_addressed", ())),
            DecisionLog.from_dict(data.get("log", {})),
        )


@dataclass(frozen=True)
class Store:
    """A chat directory holding ``state.json``."""

    directory: Path

    @property
    def path(self) -> Path:
        return self.directory / STATE_FILE

    def load(self) -> ChatState:
        """The saved state, or a fresh one for a new chat."""
        if not self.path.exists():
            return ChatState()
        return ChatState.from_dict(json.loads(self.path.read_text()))

    def save(self, state: ChatState) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state.to_dict(), indent=2) + "\n")
        os.replace(tmp, self.path)

"""The chat's state on disk: transcript, summary, last addressee and decision log.

One ``state.json`` per chat directory. Writes go to a unique temp file that is
fsynced and then renamed over ``state.json``, so a crash mid-write leaves the
previous state intact. ``Store.locked`` holds ``<dir>/lock`` (created with
``O_EXCL``, which works the same on Windows) for a whole message, so two
``say`` calls cannot interleave; the second is refused, not queued.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .decision_log import DecisionLog

STATE_FILE = "state.json"
LOCK_FILE = "lock"
HUMAN = "human"
ORCHESTRATOR = "orchestrator"
# An opening or closing turn tag, any case, as a reply might forge it.
TAG_RE = re.compile(r"<(/?turn)", re.IGNORECASE)


class StateError(RuntimeError):
    """``state.json`` is unreadable or malformed, or the chat is locked."""


@dataclass(frozen=True)
class Turn:
    """One message in the shared thread."""

    speaker: str
    text: str

    def render(self) -> str:
        """One line for people: ``@speaker: text``."""
        return f"@{self.speaker}: {self.text}"

    def block(self) -> str:
        """A delimited block for models; a turn cannot fake another turn's tags."""
        text = TAG_RE.sub(r"&lt;\1", self.text)
        return f'<turn speaker="{self.speaker}">\n{text}\n</turn>'


@dataclass
class ChatState:
    """Everything a chat remembers between messages."""

    turns: list[Turn] = field(default_factory=list)
    summary: str = ""
    last_addressed: tuple[str, ...] = ()
    log: DecisionLog = field(default_factory=DecisionLog)

    def add(self, turn: Turn) -> None:
        """Append ``turn`` and apply its marker lines to the log."""
        self.turns.append(turn)
        self.log.apply(turn.speaker, turn.text)

    def note(self, text: str) -> Turn:
        """Append an orchestrator note. Notes bypass the log on purpose: the
        runner reports, it never decides."""
        turn = Turn(ORCHESTRATOR, text)
        self.turns.append(turn)
        return turn

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form, read back by ``from_dict``."""
        return {
            "turns": [vars(turn) for turn in self.turns],
            "summary": self.summary,
            "last_addressed": list(self.last_addressed),
            "log": self.log.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatState:
        """The state saved by ``to_dict``; missing keys take their defaults."""
        return cls(
            [Turn(**turn) for turn in data.get("turns", [])],
            data.get("summary", ""),
            tuple(data.get("last_addressed", ())),
            DecisionLog.from_dict(data.get("log", {})),
        )


@dataclass(frozen=True)
class Store:
    """A chat directory holding ``state.json`` and, while busy, ``lock``."""

    directory: Path

    @property
    def path(self) -> Path:
        return self.directory / STATE_FILE

    @property
    def lock_path(self) -> Path:
        return self.directory / LOCK_FILE

    def load(self) -> ChatState:
        """The saved state, or a fresh one for a new chat."""
        if not self.path.exists():
            return ChatState()
        try:
            return ChatState.from_dict(json.loads(self.path.read_text()))
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise StateError(f"{self.path} is unreadable or malformed: {exc}") from exc

    def save(self, state: ChatState) -> None:
        """Write ``state`` atomically and durably."""
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(json.dumps(state.to_dict(), indent=2) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            Path(tmp).replace(self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Hold the chat's lock; ``StateError`` if another process holds it."""
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            os.close(os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError as exc:
            raise StateError(
                f"{self.lock_path} exists: another group-chat is using this chat "
                "(delete the file if none is running)"
            ) from exc
        try:
            yield
        finally:
            self.lock_path.unlink(missing_ok=True)

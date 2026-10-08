"""Product Owner <-> liaison message files.

The PO's ``ask_user`` / ``notify_user`` append to ``outbox.jsonl``; the liaison
watches it and relays to the human. Answers come back through
``agile-team answer`` into ``inbox.jsonl``. Only the stories a question names
are blocked while it is open.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

KINDS = ("question", "update", "sprint-end", "blocked", "done", "failed", "stopped")
OUTBOX = "outbox.jsonl"
INBOX = "inbox.jsonl"


class RelayError(Exception):
    """Bad kind or unknown question id."""


@dataclass
class Note:
    """What the PO wants to send; ``post`` turns it into a numbered ``Message``."""

    kind: str
    text: str
    stories: list[str] = field(default_factory=list)


@dataclass
class Message:
    """One outbox entry."""

    id: str
    kind: str
    text: str
    stories: list[str] = field(default_factory=list)
    at: float = 0.0


@dataclass
class Answer:
    """One inbox entry."""

    id: str
    text: str
    at: float = 0.0


@dataclass
class Relay:
    """Outbox/inbox pair in the run directory."""

    run_dir: Path

    @property
    def outbox(self) -> Path:
        return self.run_dir / OUTBOX

    @property
    def inbox(self) -> Path:
        return self.run_dir / INBOX

    def post(self, note: Note) -> Message:
        """Append a message for the liaison and return it."""
        if note.kind not in KINDS:
            raise RelayError(f"kind must be one of {KINDS}")
        msg_id = f"m{len(self.messages()) + 1}"
        msg = Message(msg_id, note.kind, note.text, list(note.stories), time.time())
        _append(self.outbox, asdict(msg))
        return msg

    def answer(self, msg_id: str, text: str) -> Answer:
        """Record the human's answer to question ``msg_id``."""
        question = next((m for m in self.messages() if m.id == msg_id), None)
        if question is None or question.kind != "question":
            raise RelayError(f"no question with id {msg_id!r}")
        ans = Answer(msg_id, text, time.time())
        _append(self.inbox, asdict(ans))
        return ans

    def messages(self) -> list[Message]:
        return [Message(**d) for d in _read(self.outbox)]

    def answers(self) -> dict[str, Answer]:
        return {a.id: a for a in (Answer(**d) for d in _read(self.inbox))}

    def open_questions(self) -> list[Message]:
        answered = self.answers()
        return [m for m in self.messages() if m.kind == "question" and m.id not in answered]

    def blocked_stories(self) -> set[str]:
        return {s for m in self.open_questions() for s in m.stories}


def _append(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(data) + "\n")


def _read(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

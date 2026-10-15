"""Product Owner <-> liaison message files.

The PO's ``ask_user`` / ``notify_user`` append to ``outbox.jsonl``; the liaison
watches it and relays to the human. Answers come back through
``agile-team answer`` into ``inbox.jsonl``. ``agile-team tell`` queues the
human's own messages for the PO as ``liaison/messages/t<N>.md`` files. Only the
stories a question names are blocked while it is open. Story-thread posts to the
PO are ``tell`` files with a thread head (s84, ``threads.py``).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import system
from .numbered_queue import NumberedQueue

WAIT_LINE = "{story} waits on {ids}"
RUN_WAIT_LINE = "the run waits on {ids}"
WAITING_HEAD = "waiting on answers: "
KINDS = ("question", "update", "sprint-end", "blocked", "done", "failed", "stopped", "reply")
REPLY = "reply"
OUTBOX = "outbox.jsonl"
INBOX = "inbox.jsonl"
LIAISON_DIR = "liaison"
MESSAGES_DIR = "messages"
TOLD_PREFIX = "t"
TOLD_SUFFIX = ".md"
TOLD_LINE = "The human sent you a message ({id}): read {path}."


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


@dataclass(frozen=True)
class Told:
    """A message the human queued for the PO with ``agile-team tell`` (s62)."""

    id: str
    path: Path


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

    @property
    def messages_dir(self) -> Path:
        return self.run_dir / LIAISON_DIR / MESSAGES_DIR

    @property
    def _messages(self) -> NumberedQueue:
        return NumberedQueue(self.messages_dir, TOLD_PREFIX, TOLD_SUFFIX)

    def tell(self, text: str) -> Told:
        """Queue ``text`` as the next ``t<N>.md``: written whole, never overwriting (T2)."""
        entry = self._messages.publish(text)
        return Told(entry.id, entry.path)

    def told(self) -> list[Told]:
        """Every queued message, in number order; other files are ignored (T2)."""
        return [Told(e.id, e.path) for e in self._messages.entries()]

    def unread(self, told: list[str]) -> list[Told]:
        """Queued messages whose ids are not in ``told`` (T4)."""
        return [t for t in self.told() if t.id not in told]

    def post(self, note: Note) -> Message:
        """Append a message for the liaison and return it."""
        if note.kind not in KINDS:
            raise RelayError(f"kind must be one of {KINDS}")
        msg_id = f"m{len(self.messages()) + 1}"
        msg = Message(msg_id, note.kind, note.text, list(note.stories), system.now())
        _append(self.outbox, asdict(msg))
        return msg

    def answer(self, msg_id: str, text: str) -> Answer:
        """Record the human's answer to question ``msg_id``."""
        question = next((m for m in self.messages() if m.id == msg_id), None)
        if question is None or question.kind != "question":
            raise RelayError(f"no question with id {msg_id!r}")
        ans = Answer(msg_id, text, system.now())
        _append(self.inbox, asdict(ans))
        return ans

    def messages(self) -> list[Message]:
        return [Message(**d) for d in _read(self.outbox)]

    def answers(self) -> dict[str, Answer]:
        return {a.id: a for a in (Answer(**d) for d in _read(self.inbox))}

    def open_questions(self) -> list[Message]:
        answered = self.answers()
        return [m for m in self.messages() if m.kind == "question" and m.id not in answered]

    def waits(self) -> list[str]:
        """One line per story an open question names, then one for questions naming none (W2)."""
        by_story: dict[str, list[str]] = {}
        for m in self.open_questions():
            for sid in dict.fromkeys(m.stories):
                by_story.setdefault(sid, []).append(m.id)
        lines = [WAIT_LINE.format(story=s, ids=", ".join(i)) for s, i in by_story.items()]
        return lines + self._unnamed_wait()

    def _unnamed_wait(self) -> list[str]:
        ids = [m.id for m in self.open_questions() if not m.stories]
        return [RUN_WAIT_LINE.format(ids=", ".join(ids))] if ids else []

    def waiting(self) -> str:
        """WAITING_HEAD + the waits joined by "; ", or "" when no question is open (W3, W5)."""
        lines = self.waits()
        return WAITING_HEAD + "; ".join(lines) if lines else ""

    def blocked_stories(self) -> set[str]:
        return {s for m in self.open_questions() for s in m.stories}


def _append(path: Path, data: dict) -> None:
    system.make_dirs(path.parent)
    system.append_text(path, json.dumps(data) + "\n")


def _read(path: Path) -> list[dict]:
    if not system.is_file(path):
        return []
    return [json.loads(line) for line in system.read_text(path).splitlines() if line.strip()]

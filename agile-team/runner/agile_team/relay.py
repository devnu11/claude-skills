"""Product Owner <-> liaison message files.

The PO's ``ask_user`` / ``notify_user`` append to ``outbox.jsonl``; the liaison
watches it and relays to the human. Answers come back through
``agile-team answer`` into ``inbox.jsonl``. ``agile-team tell`` queues the
human's own messages for the PO as ``liaison/messages/t<N>.md`` files. Only the
stories a question names are blocked while it is open.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import system

WAIT_LINE = "{story} waits on {ids}"
RUN_WAIT_LINE = "the run waits on {ids}"
WAITING_HEAD = "waiting on answers: "
KINDS = ("question", "update", "sprint-end", "blocked", "done", "failed", "stopped")
OUTBOX = "outbox.jsonl"
INBOX = "inbox.jsonl"
LIAISON_DIR = "liaison"
MESSAGES_DIR = "messages"
TOLD_NAME = re.compile(r"^t(\d+)\.md$")
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

    def tell(self, text: str) -> Told:
        """Queue ``text`` as the next ``t<N>.md``: written whole, never overwriting (T2)."""
        system.make_dirs(self.messages_dir)
        draft = self.messages_dir / f".draft-{system.pid()}"
        try:
            system.write_text(draft, text)
            return self._publish(draft)
        finally:
            system.remove(draft)

    def told(self) -> list[Told]:
        """Every queued message, in number order; other files are ignored (T2)."""
        if not system.is_dir(self.messages_dir):
            return []
        found = [
            (int(m[1]), p)
            for p in system.list_dir(self.messages_dir)
            if (m := TOLD_NAME.match(p.name))
        ]
        return [Told(f"t{n}", p) for n, p in sorted(found)]

    def unread(self, told: list[str]) -> list[Told]:
        """Queued messages whose ids are not in ``told`` (T4)."""
        return [t for t in self.told() if t.id not in told]

    def _publish(self, draft: Path) -> Told:
        n = self._next_number()
        while True:
            try:
                system.hard_link(self._told_at(n).path, draft)
                return self._told_at(n)
            except FileExistsError:
                n += 1

    def _next_number(self) -> int:
        return max((int(t.id[1:]) for t in self.told()), default=0) + 1

    def _told_at(self, n: int) -> Told:
        return Told(f"t{n}", self.messages_dir / f"t{n}.md")

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

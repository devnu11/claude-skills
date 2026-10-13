"""Story threads (s84): the human's posts to the PO or the liaison and their replies,
read from the files each path writes."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import state as state_mod
from . import system
from .backlog import STORY_ID
from .relay import LIAISON_DIR, MESSAGES_DIR, OUTBOX, REPLY, TOLD_LINE, Relay, Told

MAX_TEXT = 4000
LIAISON_INBOX = "inbox.jsonl"
LIAISON_REPLIES = "replies.jsonl"
HEAD = "<!-- thread story={story} at={at} -->"
HEAD_RE = re.compile(
    r"\A<!-- thread story=([A-Za-z][A-Za-z0-9_-]{0,63}) at=([0-9]+(?:\.[0-9]+)?) -->\n\n"
)
EMPTY = "the message is empty"
TOO_LONG = "the message is longer than {max} characters"
UNKNOWN_STORY = "no story {story!r}"
THREAD_TOLD_LINE = (
    "The human wrote to you on {story}'s thread ({id}): read {path}. "
    "Answer there with reply_story; the reply shows under the story on the dashboard."
)
REPLIED = "replied {id} on {story}"


class Party(StrEnum):
    """Who writes or reads on a thread."""

    HUMAN = "human"
    PO = "product-owner"
    LIAISON = "liaison"


RECIPIENTS = frozenset({Party.PO, Party.LIAISON})
EVENT_ROLES: dict[Party, str] = {Party.PO: "product-owner"}


@dataclass(frozen=True)
class Post:
    """A validated post from the human."""

    story: str
    to: Party
    text: str


@dataclass(frozen=True)
class Tag:
    """The thread head of a told file and the text after it."""

    story: str
    at: float
    text: str


@dataclass(frozen=True)
class Entry:
    """One message on a story's thread."""

    id: str
    story: str
    author: Party
    to: Party
    text: str
    at: float

    def as_dict(self) -> dict[str, Any]:
        """Plain JSON form: enum values as strings, ``to`` for the recipient."""
        data = asdict(self)
        return {**data, "author": str(self.author), "to": str(self.to)}


def text_refusal(text: str) -> str | None:
    """Why a text may not be posted, or ``None``."""
    stripped = text.strip()
    if not stripped:
        return EMPTY
    return TOO_LONG.format(max=MAX_TEXT) if len(stripped) > MAX_TEXT else None


def story_refusal(story: str, stories: Mapping[str, Any]) -> str | None:
    """Why a story id may not be used, or ``None`` (done stories are fine)."""
    return None if story in stories else UNKNOWN_STORY.format(story=story)


def parse_post(body: bytes) -> Post | None:
    """A ``Post`` from a request body, or ``None`` when its shape is wrong."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    return _post_of(data) if isinstance(data, dict) else None


def _post_of(data: dict[str, Any]) -> Post | None:
    story, to, text = data.get("story"), data.get("to"), data.get("text")
    if not (isinstance(story, str) and isinstance(to, str) and isinstance(text, str)):
        return None
    if not STORY_ID.match(story) or to not in RECIPIENTS or text_refusal(text):
        return None
    return Post(story, Party(to), text)


def tagged(story: str, text: str) -> str:
    """``text`` under the thread head for ``story``."""
    return HEAD.format(story=story, at=system.now()) + "\n\n" + text


def tag_of(told: Told) -> Tag | None:
    """The thread tag of a told file, or ``None`` for a plain tell."""
    try:
        content = system.read_text(told.path)
    except OSError:
        return None
    head = HEAD_RE.match(content)
    return Tag(head[1], float(head[2]), content[head.end() :]) if head else None


def told_line(told: Told, repo: Path) -> str:
    """The PO's hand-over line for a told file."""
    tag = tag_of(told)
    path = told.path.relative_to(repo)
    if tag is None:
        return TOLD_LINE.format(id=told.id, path=path)
    return THREAD_TOLD_LINE.format(story=tag.story, id=told.id, path=path)


def told_stories(told: list[Told]) -> list[str]:
    """The stories the tagged told files name, deduplicated in order."""
    tags = (tag_of(t) for t in told)
    return list(dict.fromkeys(tag.story for tag in tags if tag))


def watched(run_dir: Path) -> list[Path]:
    """The files a thread changes."""
    liaison = run_dir / LIAISON_DIR
    told = (
        system.glob(liaison / MESSAGES_DIR, "t*.md")
        if system.is_dir(liaison / MESSAGES_DIR)
        else []
    )
    return [liaison / LIAISON_INBOX, liaison / LIAISON_REPLIES, *told]


def post_known(run_dir: Path, post: Post) -> Entry | None:
    """Post it, or ``None`` when the story is unknown."""
    if story_refusal(post.story, state_mod.load(run_dir).stories):
        return None
    return Threads(run_dir).post(post)


def _lines(path: Path) -> list[dict]:
    """The JSON objects of a JSONL file; blank, torn and non-object lines are skipped."""
    if not system.is_file(path):
        return []
    return [d for line in system.read_text(path).splitlines() if (d := _object(line)) is not None]


def _object(line: str) -> dict | None:
    try:
        data = json.loads(line)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _well_formed(record: dict) -> bool:
    at = record.get("at")
    numeric = isinstance(at, int | float) and not isinstance(at, bool)
    return isinstance(record.get("story"), str) and isinstance(record.get("text"), str) and numeric


def _entries(path: Path, prefix: str, authors: tuple[Party, Party]) -> list[Entry]:
    records = [r for r in _lines(path) if _well_formed(r)]
    return [
        Entry(f"{prefix}{n}", r["story"], authors[0], authors[1], r["text"], r["at"])
        for n, r in enumerate(records, 1)
    ]


@dataclass(frozen=True)
class Threads:
    """All thread files of one run directory."""

    run_dir: Path

    @property
    def inbox(self) -> Path:
        return self.run_dir / LIAISON_DIR / LIAISON_INBOX

    @property
    def replies(self) -> Path:
        return self.run_dir / LIAISON_DIR / LIAISON_REPLIES

    def post(self, post: Post) -> Entry:
        """Send a post to its recipient."""
        return SENDERS[post.to](self, post)

    def _to_po(self, post: Post) -> Entry:
        text = post.text.strip()
        told = Relay(self.run_dir).tell(tagged(post.story, text))
        tag = tag_of(told)
        at = tag.at if tag else system.now()
        return Entry(told.id, post.story, Party.HUMAN, Party.PO, text, at)

    def _to_liaison(self, post: Post) -> Entry:
        text, at = post.text.strip(), system.now()
        _append(self.inbox, {"story": post.story, "text": text, "at": at})
        return Entry(
            f"lp{len(self.liaison_posts())}", post.story, Party.HUMAN, Party.LIAISON, text, at
        )

    def reply(self, story: str, text: str) -> Entry:
        """Record the liaison's reply."""
        text, at = text.strip(), system.now()
        _append(self.replies, {"story": story, "text": text, "at": at})
        return Entry(
            f"lr{len(self.liaison_replies())}", story, Party.LIAISON, Party.HUMAN, text, at
        )

    def to_po(self) -> list[Entry]:
        """The tagged told files."""
        pairs = ((t, tag_of(t)) for t in Relay(self.run_dir).told())
        return [Entry(t.id, g.story, Party.HUMAN, Party.PO, g.text, g.at) for t, g in pairs if g]

    def po_replies(self) -> list[Entry]:
        """The outbox ``reply`` messages."""
        return [
            Entry(f"m{n}", r["stories"][0], Party.PO, Party.HUMAN, r["text"], r["at"])
            for n, r in enumerate(_lines(self.run_dir / OUTBOX), 1)
            if _is_reply(r)
        ]

    def liaison_posts(self) -> list[Entry]:
        """Posts to the liaison."""
        return _entries(self.inbox, "lp", (Party.HUMAN, Party.LIAISON))

    def liaison_replies(self) -> list[Entry]:
        """The liaison's replies."""
        return _entries(self.replies, "lr", (Party.LIAISON, Party.HUMAN))

    def all(self) -> list[Entry]:
        """Every entry, in time order."""
        found = [*self.to_po(), *self.po_replies(), *self.liaison_posts(), *self.liaison_replies()]
        return sorted(found, key=lambda e: (e.at, e.id))


def _is_reply(record: dict) -> bool:
    stories, at = record.get("stories"), record.get("at")
    return (
        record.get("kind") == REPLY
        and isinstance(record.get("text"), str)
        and isinstance(at, int | float)
        and isinstance(stories, list)
        and bool(stories)
        and isinstance(stories[0], str)
    )


def _append(path: Path, data: dict) -> None:
    system.make_dirs(path.parent)
    system.append_text(path, json.dumps(data) + "\n")


SENDERS = {Party.PO: Threads._to_po, Party.LIAISON: Threads._to_liaison}

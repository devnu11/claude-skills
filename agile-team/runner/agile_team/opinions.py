"""The liaison's opinions on stories (s85): recorded by the CLI, reviewed and acted on
from the dashboard; read from the files each writer appends to."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import state as state_mod
from . import system
from .backlog import Ask, View
from .priority import first_refusal
from .relay import LIAISON_DIR
from .reorders import MAX_VERSION, Requests
from .threads import BACKLOG, Entry, Party, Post, Threads, append_line, has_time, read_lines


class Kind(StrEnum):
    """What the liaison suggests for a story."""

    KEEP = "keep"
    MOVE_UP = "move-up"
    MOVE_DOWN = "move-down"
    FOLD = "fold"
    CLOSE = "close"
    SCOPE = "scope"
    ASK = "ask"


class Act(StrEnum):
    """What the human does with an opinion."""

    DISMISS = "dismiss"
    APPLY = "apply"


class Route(StrEnum):
    """Where an applied opinion goes."""

    NONE = ""
    REORDER = "reorder"
    PO = "product-owner"


OPINIONS = "opinions.jsonl"
REVIEWS = "reviews.jsonl"
ACTS = "opinion-acts.jsonl"
OPINION_ID = re.compile(r"^o[1-9][0-9]{0,8}\Z")
MOVES: dict[Kind, Callable[[View], int]] = {
    Kind.MOVE_UP: lambda view: 1,
    Kind.MOVE_DOWN: lambda view: len(view.backlog),
}
ACT_STATUS = {Act.DISMISS: "dismissed", Act.APPLY: "applied"}
UNKNOWN_KIND = "no opinion kind {kind!r}; use one of: {kinds}"
UNKNOWN_OPINION = "no opinion {id!r}"
SUPERSEDED = "{id} is no longer the latest opinion on {story}; reload"
NOTHING_TO_ACT = "{id} is keep: there is nothing to dismiss or apply"
SETTLED = "{id} was already {status}"
RECORDED = "recorded {id}: {kind} on {story}"
REVIEWED = "recorded backlog review {id}"
REVIEW_TEXT = (
    "Please review the backlog. Record an opinion on each story you would change with "
    "`agile-team opinion <story> <kind> -` (kinds: keep, move-up, move-down, fold, close, "
    "scope, ask), then a short summary with `agile-team reviewed -`."
)
APPLY_TEXT = (
    "The human applied the liaison's opinion {id} on {story} from the dashboard: {kind}.\n\n{text}"
)


@dataclass(frozen=True)
class Opinion:
    """One recorded opinion."""

    id: str
    story: str
    kind: Kind
    text: str
    at: float

    def as_dict(self) -> dict[str, Any]:
        """Plain JSON form."""
        return {
            "id": self.id,
            "story": self.story,
            "kind": str(self.kind),
            "text": self.text,
            "at": self.at,
        }


@dataclass(frozen=True)
class Review:
    """The summary that closed a backlog review."""

    id: str
    text: str
    at: float

    def as_dict(self) -> dict[str, Any]:
        """Plain JSON form."""
        return {"id": self.id, "text": self.text, "at": self.at}


@dataclass(frozen=True)
class Settled:
    """An act the human took on an opinion."""

    id: str
    opinion: str
    story: str
    act: Act
    route: Route
    ref: str
    at: float

    def as_dict(self) -> dict[str, Any]:
        """Plain JSON form."""
        return {
            "id": self.id,
            "opinion": self.opinion,
            "story": self.story,
            "act": str(self.act),
            "route": str(self.route),
            "ref": self.ref,
            "at": self.at,
        }


@dataclass(frozen=True)
class ActAsk:
    """A validated request to dismiss or apply an opinion."""

    opinion: str
    act: Act
    version: str


def kind_refusal(kind: str) -> str | None:
    """Why a kind is not allowed, or ``None``."""
    if kind in set(Kind):
        return None
    return UNKNOWN_KIND.format(kind=kind, kinds=", ".join(Kind))


def _object_of(body: bytes) -> dict | None:
    try:
        data = json.loads(body)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def is_object(body: bytes) -> bool:
    """Whether the body parses as a JSON object."""
    return _object_of(body) is not None


def parse_act(body: bytes) -> ActAsk | None:
    """An ``ActAsk`` from a request body, or ``None`` when its shape is wrong (O7)."""
    data = _object_of(body)
    if data is None:
        return None
    oid, act, version = data.get("opinion"), data.get("act"), data.get("version")
    if not (isinstance(oid, str) and isinstance(act, str) and isinstance(version, str)):
        return None
    if not OPINION_ID.match(oid) or act not in set(Act) or len(version) > MAX_VERSION:
        return None
    return ActAsk(oid, Act(act), version)


def route_of(opinion: Opinion, view: View) -> Route:
    """Where applying ``opinion`` would go (O9)."""
    if opinion.kind == Kind.KEEP:
        return Route.NONE
    if opinion.kind in MOVES and opinion.story in view.backlog:
        return Route.REORDER
    return Route.PO


def watched(run_dir: Path) -> list[Path]:
    """The files opinions change."""
    files = Opinions(run_dir)
    return [files.opinions_file, files.reviews_file, files.acts_file]


def _strings(record: dict, *keys: str) -> bool:
    return all(isinstance(record.get(k), str) for k in keys)


def _opinion_ok(record: dict) -> bool:
    return (
        _strings(record, "story", "text") and record.get("kind") in set(Kind) and has_time(record)
    )


def _act_ok(record: dict) -> bool:
    known = record.get("act") in set(Act) and record.get("route") in set(Route)
    return _strings(record, "opinion", "story", "route", "ref") and known and has_time(record)


@dataclass(frozen=True)
class Board:
    """Opinions and the acts taken on them; pure."""

    opinions: list[Opinion]
    acts: list[Settled]

    def latest(self) -> dict[str, Opinion]:
        """Each story's last opinion; line order decides (O3)."""
        return {o.story: o for o in self.opinions}

    def find(self, oid: str) -> Opinion | None:
        """The opinion with this id."""
        return next((o for o in self.opinions if o.id == oid), None)

    def act_of(self, oid: str) -> Settled | None:
        """The first act on an opinion."""
        return next((a for a in self.acts if a.opinion == oid), None)

    def refusal(self, ask: ActAsk) -> str | None:
        """Why the act may not be taken, or ``None`` (O8)."""
        opinion = self.find(ask.opinion)
        if opinion is None:
            return UNKNOWN_OPINION.format(id=ask.opinion)
        return first_refusal(
            [
                lambda: self._superseded(opinion),
                lambda: self._keep(opinion),
                lambda: self._settled(opinion),
            ]
        )

    def _superseded(self, opinion: Opinion) -> str | None:
        if self.latest()[opinion.story].id == opinion.id:
            return None
        return SUPERSEDED.format(id=opinion.id, story=opinion.story)

    @staticmethod
    def _keep(opinion: Opinion) -> str | None:
        return NOTHING_TO_ACT.format(id=opinion.id) if opinion.kind == Kind.KEEP else None

    def _settled(self, opinion: Opinion) -> str | None:
        done = self.act_of(opinion.id)
        if done is None:
            return None
        return SETTLED.format(id=opinion.id, status=ACT_STATUS[done.act])


@dataclass(frozen=True)
class Opinions:
    """All opinion files of one run directory."""

    run_dir: Path

    @property
    def opinions_file(self) -> Path:
        """The file the liaison's opinions are appended to."""
        return self.run_dir / LIAISON_DIR / OPINIONS

    @property
    def reviews_file(self) -> Path:
        """The file the human's review requests are appended to."""
        return self.run_dir / LIAISON_DIR / REVIEWS

    @property
    def acts_file(self) -> Path:
        """The file the acts taken on opinions are appended to."""
        return self.run_dir / LIAISON_DIR / ACTS

    def record(self, story: str, kind: Kind, text: str) -> Opinion:
        """Append an opinion."""
        text, at = text.strip(), system.now()
        append_line(self.opinions_file, {"story": story, "kind": str(kind), "text": text, "at": at})
        return Opinion(f"o{len(self.all())}", story, kind, text, at)

    def review(self, text: str) -> Review:
        """Append a review summary."""
        text, at = text.strip(), system.now()
        append_line(self.reviews_file, {"text": text, "at": at})
        return Review(f"v{len(self.reviews())}", text, at)

    def all(self) -> list[Opinion]:
        """Every well-formed opinion, in line order."""
        records = [r for r in read_lines(self.opinions_file) if _opinion_ok(r)]
        return [
            Opinion(f"o{n}", r["story"], Kind(r["kind"]), r["text"], r["at"])
            for n, r in enumerate(records, 1)
        ]

    def reviews(self) -> list[Review]:
        """Every well-formed review, in line order."""
        records = [r for r in read_lines(self.reviews_file) if _strings(r, "text") and has_time(r)]
        return [Review(f"v{n}", r["text"], r["at"]) for n, r in enumerate(records, 1)]

    def acts(self) -> list[Settled]:
        """Every well-formed act, in line order."""
        records = [r for r in read_lines(self.acts_file) if _act_ok(r)]
        return [
            Settled(
                f"a{n}",
                r["opinion"],
                r["story"],
                Act(r["act"]),
                Route(r["route"]),
                r["ref"],
                r["at"],
            )
            for n, r in enumerate(records, 1)
        ]

    def board(self) -> Board:
        """Opinions and acts together."""
        return Board(self.all(), self.acts())

    def ask_review(self) -> Entry:
        """Post a review request to the liaison inbox (O5)."""
        return Threads(self.run_dir).post(Post(BACKLOG, Party.LIAISON, REVIEW_TEXT))

    def asked_at(self) -> float | None:
        """When the latest review was asked for, or ``None``."""
        posts = Threads(self.run_dir).liaison_posts()
        return max((p.at for p in posts if p.story == BACKLOG), default=None)

    def refusal(self, ask: ActAsk) -> str | None:
        """Why the act may not be taken, or ``None``."""
        return self.board().refusal(ask)

    def act(self, ask: ActAsk) -> Settled:
        """Take the act; call only after ``refusal`` gave ``None``."""
        opinion = self.board().find(ask.opinion)
        assert opinion is not None
        route, ref = DOERS[ask.act](self, opinion, ask)
        return self._settle(opinion, ask, route, ref)

    def _dismiss(self, opinion: Opinion, ask: ActAsk) -> tuple[Route, str]:
        return Route.NONE, ""

    def _apply(self, opinion: Opinion, ask: ActAsk) -> tuple[Route, str]:
        view = View.of(state_mod.load(self.run_dir))
        route = route_of(opinion, view)
        return route, APPLIERS[route](self, opinion, ask)

    def _reorder(self, opinion: Opinion, ask: ActAsk) -> str:
        view = View.of(state_mod.load(self.run_dir))
        position = MOVES[opinion.kind](view)
        return Requests(self.run_dir).queue(Ask(opinion.story, position, ask.version)).id

    def _tell_po(self, opinion: Opinion, ask: ActAsk) -> str:
        text = APPLY_TEXT.format(
            id=opinion.id, story=opinion.story, kind=opinion.kind, text=opinion.text
        )
        return Threads(self.run_dir).post(Post(opinion.story, Party.PO, text)).id

    def _settle(self, opinion: Opinion, ask: ActAsk, route: Route, ref: str) -> Settled:
        at = system.now()
        append_line(
            self.acts_file,
            {
                "opinion": opinion.id,
                "story": opinion.story,
                "act": str(ask.act),
                "route": str(route),
                "ref": ref,
                "at": at,
            },
        )
        return Settled(f"a{len(self.acts())}", opinion.id, opinion.story, ask.act, route, ref, at)


DOERS = {Act.DISMISS: Opinions._dismiss, Act.APPLY: Opinions._apply}
APPLIERS = {Route.REORDER: Opinions._reorder, Route.PO: Opinions._tell_po}

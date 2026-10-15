"""Queued shares and the runner side that applies them between steps (s120).

``agile-team share`` queues a request file; the router's ``Sharer`` copies the file,
records its hash in the story file and commits both, never while a boundary is open.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from . import shares, story_spec, system
from .events import Event, EventKind
from .numbered_queue import Entry, NumberedQueue
from .relay import LIAISON_DIR
from .shares import BadRequest, Refused, Request, Share, SharedFile

if TYPE_CHECKING:
    from .dispatch import Runtime

SHARES_DIR = "shares"
REQUEST_PREFIX = "f"
REQUEST_SUFFIX = ".json"
ROLE = "liaison"


@dataclass(frozen=True)
class Shares:
    """The share request files under the run directory."""

    run_dir: Path

    @property
    def folder(self) -> Path:
        """Where the request files live."""
        return self.run_dir / LIAISON_DIR / SHARES_DIR

    @property
    def _queue(self) -> NumberedQueue:
        return NumberedQueue(self.folder, REQUEST_PREFIX, REQUEST_SUFFIX)

    def queue(self, share: Share) -> Share:
        """Queue ``share`` as the next ``f<N>.json``, written whole, never overwriting."""
        queued = replace(share, at=system.now())
        entry = self._queue.publish(queued.to_json())
        return replace(queued, id=entry.id)

    def all(self) -> list[Request]:
        """Every numbered request, in number order; unreadable ones are bad requests."""
        return [self._read(entry) for entry in self._queue.entries()]

    def pending(self, settled: Mapping[str, str]) -> list[Request]:
        """Requests whose ids are not in ``settled``."""
        return [s for s in self.all() if s.id not in settled]

    @staticmethod
    def _read(entry: Entry) -> Request:
        try:
            return Share.from_json(entry.id, system.read_text(entry.path))
        except OSError as error:
            problem = shares.UNREADABLE_REQUEST.format(error=error.strerror)
            return shares.bad_request(entry.id, problem)


class Outcome(StrEnum):
    """How a share was settled."""

    APPLIED = "applied"
    UNCHANGED = "unchanged"
    REFUSED = "refused"


@dataclass(frozen=True)
class Settled:
    """The result of settling one share."""

    outcome: Outcome
    commit: str | None = None
    reason: str | None = None

    def state_text(self) -> str:
        """What ``state.shares`` records."""
        if self.outcome is Outcome.APPLIED:
            return f"applied {(self.commit or '')[: shares.SHORT]}"
        if self.outcome is Outcome.REFUSED:
            return f"refused: {self.reason}"
        return self.outcome.value


@dataclass(frozen=True)
class Note:
    """A request id and the state text recorded for it."""

    rid: str
    text: str


@dataclass
class Sharer:
    """Applies pending shares between steps (S4)."""

    runtime: Runtime

    def apply(self) -> None:
        """Settle every pending share in number order; wait while a boundary is open."""
        if self.runtime.state.boundary is not None:
            return
        for request in Shares(self.runtime.config.run_dir).pending(self.runtime.state.shares):
            if isinstance(request, BadRequest):
                self._refuse_bad(request)
            else:
                self._settle(request)

    def _refuse_bad(self, bad: BadRequest) -> None:
        data: dict[str, object] = {
            "request": bad.id,
            "path": None,
            "sha256": None,
            "commit": None,
            "outcome": Outcome.REFUSED.value,
            "reason": bad.reason,
        }
        self._note(Note(bad.id, f"refused: {bad.reason}"), Event(EventKind.SHARE, ROLE, None, data))

    def _settle(self, share: Share) -> None:
        config = self.runtime.config
        refusal = shares.story_refusal(config, share)
        file = story_spec.file_of(config, share.story)
        text = None if refusal else self._with_entry(share, file)
        if refusal or text is None:
            reason = refusal or self._unwritable(file)
            return self._record(share, Settled(Outcome.REFUSED, reason=reason))
        self._record(share, self._write(share, file, text))

    def _with_entry(self, share: Share, file: str) -> str | None:
        config = self.runtime.config
        entry = SharedFile(shares.target_of(config.team.docs_dir, share), share.sha256())
        return shares.with_entry(system.read_text(config.repo / file), entry)

    @staticmethod
    def _unwritable(file: str) -> str:
        fields = {"file": file, "problem": shares.UNPARSED}
        return shares.REFUSALS[Refused.STORY_FILE].format(**fields)

    def _write(self, share: Share, file: str, text: str) -> Settled:
        repo = self.runtime.config.repo
        target = shares.target_of(self.runtime.config.team.docs_dir, share)
        if self._same(repo / target, share.data) and system.read_text(repo / file) == text:
            return Settled(Outcome.UNCHANGED)
        system.make_dirs((repo / target).parent)
        system.write_bytes(repo / target, share.data)
        system.write_text(repo / file, text)
        subject = shares.SUBJECT.format(story=share.story, name=share.name, id=share.id)
        sha = self.runtime.git.commit([target, file], subject)
        self.runtime.record_checkout()
        return Settled(Outcome.APPLIED, commit=sha)

    @staticmethod
    def _same(path: Path, data: bytes) -> bool:
        try:
            return system.read_bytes(path) == data
        except OSError:
            return False

    def _record(self, share: Share, settled: Settled) -> None:
        event = Event(EventKind.SHARE, ROLE, share.story, self._data(share, settled))
        self._note(Note(share.id, settled.state_text()), event)
        if settled.outcome is Outcome.APPLIED:
            self._tell(share, settled.commit or "")

    def _note(self, note: Note, event: Event) -> None:
        self.runtime.state.shares[note.rid] = note.text
        self.runtime.save()
        self.runtime.events.emit(event)

    def _data(self, share: Share, settled: Settled) -> dict[str, object]:
        path = shares.target_of(self.runtime.config.team.docs_dir, share)
        data: dict[str, object] = {
            "request": share.id,
            "path": path,
            "sha256": share.sha256(),
            "commit": settled.commit,
            "outcome": settled.outcome.value,
        }
        return data | ({"reason": settled.reason} if settled.reason else {})

    def _tell(self, share: Share, commit: str) -> None:
        path = shares.target_of(self.runtime.config.team.docs_dir, share)
        short = share.sha256()[: shares.SHORT]
        text = shares.TOLD.format(
            path=path, story=share.story, short=short, commit=commit[: shares.SHORT]
        )
        self.runtime.relay.tell(text)

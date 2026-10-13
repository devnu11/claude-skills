"""``agile-team watch``: block until the run needs the liaison; one JSON line says why (s62)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import config as config_mod
from . import health, relay, system
from . import state as state_mod
from .relay import Message, Relay
from .threads import Entry, Threads

WATCH_FILE = "watch.json"
POLL_S = 2.0
HEARTBEAT = "heartbeat"


@dataclass
class Seen:
    """Where the last watch left off: outbox entries reported and the run's status (V3)."""

    messages: int = 0
    status: str | None = None
    status_reason: str | None = None
    health: str = ""
    posts: int = 0

    @classmethod
    def load(cls, path: Path) -> Seen | None:
        """Read the memory: ``None`` when there is none yet (a first watch, F1).

        Fresh memory when the file is unreadable.
        """
        try:
            return cls(**json.loads(system.read_text(path)))
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: Path) -> None:
        """Write atomically (tmp + replace)."""
        system.make_dirs(path.parent)
        tmp = path.with_name(path.name + ".tmp")
        system.write_text(tmp, json.dumps(asdict(self)))
        system.replace(tmp, path)


@dataclass(frozen=True)
class Look:
    """The run as one poll found it (V2)."""

    messages: list[Message]
    status: str
    status_reason: str | None
    health: str = ""
    health_reason: str = ""
    posts: list[Entry] = field(default_factory=list)

    def quiet(self) -> bool:
        """Running with no reason."""
        return self.status == "running" and self.status_reason is None

    def new_since(self, seen: Seen) -> list[Message]:
        """Outbox entries not yet reported; a shorter outbox is a new run, all count."""
        start = seen.messages if seen.messages <= len(self.messages) else 0
        return self.messages[start:]

    def new_posts(self, seen: Seen) -> list[Entry]:
        """Liaison-inbox entries not yet reported; a shorter inbox reports all."""
        start = seen.posts if seen.posts <= len(self.posts) else 0
        return self.posts[start:]

    def seen(self) -> Seen:
        """This look as watch memory."""
        return Seen(
            len(self.messages), self.status, self.status_reason, self.health, len(self.posts)
        )


def look(run_dir: Path) -> Look | None:
    """Read the outbox and the shown status; ``None`` when an outbox line is torn (V2)."""
    try:
        messages = Relay(run_dir).messages()
    except json.JSONDecodeError:
        return None
    state = state_mod.load(run_dir)
    status = str(state_mod.shown_status(run_dir, state))
    verdict = health.current(_config_of(run_dir))
    posts = Threads(run_dir).liaison_posts()
    return Look(messages, status, state.status_reason, str(verdict.level), verdict.reason, posts)


def _config_of(run_dir: Path) -> config_mod.Config:
    """The run's config (the repo is two levels above ``.team/run``); defaults if unreadable."""
    repo = run_dir.parents[1]
    try:
        return config_mod.load(repo)
    except config_mod.ConfigError:
        return config_mod.Config(repo)


def _status_changed(seen: Seen, now: Look) -> bool:
    return not now.quiet() and (now.status, now.status_reason) != (seen.status, seen.status_reason)


TRIGGERS: tuple[tuple[str, Callable[[Seen, Look], bool]], ...] = (
    ("message", lambda seen, now: bool(now.new_since(seen))),
    ("liaison_message", lambda seen, now: bool(now.new_posts(seen))),
    ("status", _status_changed),
    ("health", lambda seen, now: now.health == "red" and seen.health != "red"),
)


def fired(seen: Seen, now: Look) -> list[str]:
    """The trigger names that fire for ``now`` against ``seen``, in table order."""
    return [name for name, test in TRIGGERS if test(seen, now)]


@dataclass(frozen=True)
class Basis:
    """What a line compares: the memory and the look."""

    seen: Seen
    now: Look


def line(triggers: list[str], basis: Basis) -> dict[str, Any]:
    """The JSON line for a watch that ended (V6, V7)."""
    seen, now = basis.seen, basis.now
    return {
        "triggers": triggers,
        "messages": [asdict(m) for m in now.new_since(seen)] if triggers != [HEARTBEAT] else [],
        "posts": [e.as_dict() for e in now.new_posts(seen)] if triggers != [HEARTBEAT] else [],
        "status": now.status,
        "status_reason": now.status_reason,
        "was": {"status": seen.status, "status_reason": seen.status_reason},
        "health": {"level": now.health, "reason": now.health_reason},
    }


@dataclass
class Watcher:
    """Polls one run directory until something needs the liaison."""

    run_dir: Path

    @property
    def memory(self) -> Path:
        return self.run_dir / relay.LIAISON_DIR / WATCH_FILE

    def until(self, timeout_s: float | None) -> dict[str, Any]:
        """Poll until a trigger fires or ``timeout_s`` passes; save memory; return the line."""
        deadline = self._deadline(timeout_s)
        seen = self._baseline()
        while True:
            now = look(self.run_dir)
            ended = self._ended(seen, now, deadline)
            if now is not None and ended:
                now.seen().save(self.memory)
                return line(ended, Basis(seen, now))
            seen = self._next(seen, now)
            self._sleep(POLL_S)

    def _baseline(self) -> Seen:
        """The remembered look; a first watch (no memory file) records the current one (F2)."""
        remembered = Seen.load(self.memory)
        return remembered if remembered is not None else self._record(self._whole_look())

    def _record(self, now: Look) -> Seen:
        """Save ``now`` as watch memory and return it (F2)."""
        seen = now.seen()
        seen.save(self.memory)
        return seen

    def _whole_look(self) -> Look:
        """The first look with no torn outbox line, sleeping ``POLL_S`` between tries (F3)."""
        while (now := look(self.run_dir)) is None:
            self._sleep(POLL_S)
        return now

    def _sleep(self, seconds: float) -> None:
        system.sleep(seconds)

    def _clock(self) -> float:
        return system.monotonic()

    def _deadline(self, timeout_s: float | None) -> float | None:
        return None if timeout_s is None else self._clock() + timeout_s

    def _ended(self, seen: Seen, now: Look | None, deadline: float | None) -> list[str]:
        if now is None:
            return []
        names = fired(seen, now)
        late = deadline is not None and self._clock() >= deadline
        return names or ([HEARTBEAT] if late else [])

    def _next(self, seen: Seen, now: Look | None) -> Seen:
        """After a quiet look the status baseline moves to it; the message count stays (V5)."""
        if now is None:
            return seen
        return Seen(seen.messages, now.status, now.status_reason, now.health, seen.posts)

"""``agile-team watch``: block until the run needs the liaison; one JSON line says why (s62)."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import relay
from . import state as state_mod
from .relay import Message, Relay

WATCH_FILE = "watch.json"
POLL_S = 2.0
HEARTBEAT = "heartbeat"


@dataclass
class Seen:
    """Where the last watch left off: outbox entries reported and the run's status (V3)."""

    messages: int = 0
    status: str | None = None
    status_reason: str | None = None

    @classmethod
    def load(cls, path: Path) -> Seen:
        """Read the memory; a missing or unreadable file means fresh memory."""
        try:
            return cls(**json.loads(path.read_text()))
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: Path) -> None:
        """Write atomically (tmp + replace)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(asdict(self)))
        os.replace(tmp, path)


@dataclass(frozen=True)
class Look:
    """The run as one poll found it (V2)."""

    messages: list[Message]
    status: str
    status_reason: str | None

    def quiet(self) -> bool:
        """Running with no reason."""
        return self.status == "running" and self.status_reason is None

    def new_since(self, seen: Seen) -> list[Message]:
        """Outbox entries not yet reported; a shorter outbox is a new run, all count."""
        start = seen.messages if seen.messages <= len(self.messages) else 0
        return self.messages[start:]

    def seen(self) -> Seen:
        """This look as watch memory."""
        return Seen(len(self.messages), self.status, self.status_reason)


def look(run_dir: Path) -> Look | None:
    """Read the outbox and the shown status; ``None`` when an outbox line is torn (V2)."""
    try:
        messages = Relay(run_dir).messages()
    except json.JSONDecodeError:
        return None
    state = state_mod.load(run_dir)
    return Look(messages, str(state_mod.shown_status(run_dir, state)), state.status_reason)


def _status_changed(seen: Seen, now: Look) -> bool:
    return not now.quiet() and (now.status, now.status_reason) != (seen.status, seen.status_reason)


TRIGGERS: tuple[tuple[str, Callable[[Seen, Look], bool]], ...] = (
    ("message", lambda seen, now: bool(now.new_since(seen))),
    ("status", _status_changed),
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
        "status": now.status,
        "status_reason": now.status_reason,
        "was": {"status": seen.status, "status_reason": seen.status_reason},
    }


@dataclass(frozen=True)
class Pace:
    """How the watch waits; tests pass fakes (V8)."""

    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic


DEFAULT_PACE = Pace()


@dataclass
class Watcher:
    """Polls one run directory until something needs the liaison."""

    run_dir: Path
    pace: Pace = DEFAULT_PACE

    @property
    def memory(self) -> Path:
        return self.run_dir / relay.LIAISON_DIR / WATCH_FILE

    def until(self, timeout_s: float | None) -> dict[str, Any]:
        """Poll until a trigger fires or ``timeout_s`` passes; save memory; return the line."""
        seen, deadline = Seen.load(self.memory), self._deadline(timeout_s)
        while True:
            now = look(self.run_dir)
            ended = self._ended(seen, now, deadline)
            if now is not None and ended:
                now.seen().save(self.memory)
                return line(ended, Basis(seen, now))
            seen = self._next(seen, now)
            self.pace.sleep(POLL_S)

    def _deadline(self, timeout_s: float | None) -> float | None:
        return None if timeout_s is None else self.pace.clock() + timeout_s

    def _ended(self, seen: Seen, now: Look | None, deadline: float | None) -> list[str]:
        if now is None:
            return []
        names = fired(seen, now)
        late = deadline is not None and self.pace.clock() >= deadline
        return names or ([HEARTBEAT] if late else [])

    def _next(self, seen: Seen, now: Look | None) -> Seen:
        """After a quiet look the status baseline moves to it; the message count stays (V5)."""
        if now is None:
            return seen
        return Seen(seen.messages, now.status, now.status_reason)

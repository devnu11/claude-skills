"""Turn the run's files into the one JSON snapshot the dashboard renders.

Read-only; the contract is ``fixtures/snapshot.json``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from .. import roles as roles_mod
from .. import state as state_mod
from ..config import Config
from ..events import EVENTS
from ..ledger import LEDGER, Entry
from ..relay import INBOX, OUTBOX
from ..roles import RoleBook, RoleError
from ..state import STATE_FILE, RunState

RUN_FILES = (STATE_FILE, EVENTS, LEDGER, OUTBOX, INBOX)
HISTORY_KEYS = ("at", "change", "reason", "role", "story")


@dataclass(frozen=True)
class RunFiles:
    """The inputs one snapshot reads, loaded once."""

    config: Config
    book: RoleBook
    state: RunState
    events: list[dict]

    @classmethod
    def load(cls, config: Config, book: RoleBook) -> RunFiles:
        """Read the state and the event log."""
        state = state_mod.load(config.run_dir)
        return cls(config, book, state, read_jsonl(config.run_dir / EVENTS))

    def lines(self, name: str) -> list[dict]:
        """The objects of one JSONL file in the run directory."""
        return read_jsonl(self.config.run_dir / name)


def _parse_line(line: str) -> dict | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def read_jsonl(path: Path) -> list[dict]:
    """JSON objects of a JSONL file; blank, torn or non-object lines are skipped."""
    # The runner appends while we read, so the last line may be torn.
    if not path.is_file():
        return []
    parsed = (_parse_line(line) for line in path.read_text().splitlines() if line.strip())
    return [item for item in parsed if item is not None]


def watched_files(config: Config) -> list[Path]:
    """Every file a snapshot reads (missing ones included)."""
    run = [config.run_dir / name for name in RUN_FILES]
    stories = sorted(config.stories_dir.glob("*.md"))
    return run + stories + sorted(config.requirements_dir.glob("REQ-*.md"))


def _generated_at(files: RunFiles) -> float:
    return time.time()


def _pipeline(files: RunFiles) -> list[str]:
    return list(files.config.gates.steps)


def _run(files: RunFiles) -> dict[str, Any]:
    state, config = files.state, files.config
    return {
        "status": str(state.status),
        "sprint": state.sprint,
        "cadence": state.cadence,
        "task": state.task,
        "budget_usd": config.team.budget_usd,
        "manager_every_pct": config.team.manager_every_pct,
        "round_cap": config.gates.round_cap,
        "manager_due": list(state.manager_due),
    }


def _role(files: RunFiles, name: str) -> dict | None:
    try:
        role = files.book.resolve(name, files.state.runtime_overrides(name))
    except RoleError:
        return None
    if not role.enabled:
        return None
    return {"name": name, "model": role.model, "provider": role.provider}


def _roles(files: RunFiles) -> list[dict]:
    found = (_role(files, name) for name in sorted(files.book.names()))
    return [role for role in found if role is not None]


def _frontmatter(path: Path) -> tuple[dict, str]:
    if not path.is_file():
        return {}, ""
    try:
        meta, body = roles_mod.split_frontmatter(path.name, path.read_text())
    except (yaml.YAMLError, RoleError):
        return {}, ""
    return meta or {}, body


def _opened_at(events: list[dict], story_id: str) -> float | None:
    opened = (e for e in events if e.get("kind") == "story-opened" and e.get("story") == story_id)
    return next((e["at"] for e in opened), None)


def _acceptance(config: Config, story_id: str) -> list[dict]:
    meta, _ = _frontmatter(config.stories_dir / f"{story_id}.md")
    items = meta.get("acceptance")
    items = items if isinstance(items, list) else []
    return [
        {"id": str(a.get("id", "")), "text": str(a.get("text", ""))}
        for a in items
        if isinstance(a, dict)
    ]


def _story(files: RunFiles, story: Any) -> dict:
    return {
        "id": story.id,
        "title": story.title,
        "sprint": story.sprint,
        "delivery": story.delivery or "",
        "step": story.step,
        "status": str(story.status),
        "rounds": story.rounds,
        "opened_at": _opened_at(files.events, story.id),
        "acceptance": _acceptance(files.config, story.id),
    }


def _stories(files: RunFiles) -> list[dict]:
    return [_story(files, story) for story in files.state.stories.values()]


def _history(events: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for event in (e for e in events if e.get("kind") == "requirement-changed"):
        data = event.get("data") or {}
        row = {key: event.get(key) for key in HISTORY_KEYS if key != "change"}
        row = {**row, "change": data.get("change"), "reason": data.get("reason"),
               "sha": data.get("sha", "")}  # fmt: skip
        grouped.setdefault(data.get("id"), []).append(row)
    return grouped


def _requirement(path: Path, history: dict[str, list[dict]]) -> dict:
    meta, body = _frontmatter(path)
    req_id = str(meta.get("id", path.stem))
    return {
        "id": req_id,
        "title": str(meta.get("title", "")),
        "status": str(meta.get("status", "active")),
        "covers": [str(c) for c in meta.get("covers") or []],
        "text": body.strip(),
        "history": history.get(req_id, []),
    }


def _requirements(files: RunFiles) -> list[dict]:
    history = _history(files.events)
    paths = sorted(files.config.requirements_dir.glob("REQ-*.md"))
    return [_requirement(path, history) for path in paths]


def _message_event(message: dict) -> dict:
    mid = message.get("id")
    return {"id": f"out-{mid}", "at": message.get("at", 0.0), "kind": "message",
            "role": "product-owner", "story": None, "data": {"message": mid}}  # fmt: skip


def _answer_event(answer: dict) -> dict:
    mid = answer.get("id")
    return {"id": f"in-{mid}", "at": answer.get("at", 0.0), "kind": "answer",
            "role": None, "story": None, "data": {"message": mid}}  # fmt: skip


def _events(files: RunFiles) -> list[dict]:
    sent = map(_message_event, files.lines(OUTBOX))
    received = map(_answer_event, files.lines(INBOX))
    return sorted([*files.events, *sent, *received], key=lambda e: e.get("at", 0.0))


def _ledger(files: RunFiles) -> list[dict]:
    return [asdict(Entry.from_dict(line)) for line in files.lines(LEDGER)]


def _messages(files: RunFiles) -> list[dict]:
    return files.lines(OUTBOX)


def _answers(files: RunFiles) -> list[dict]:
    return files.lines(INBOX)


SECTIONS: dict[str, Callable[[RunFiles], Any]] = {
    "generated_at": _generated_at,
    "run": _run,
    "pipeline": _pipeline,
    "roles": _roles,
    "stories": _stories,
    "requirements": _requirements,
    "events": _events,
    "ledger": _ledger,
    "messages": _messages,
    "answers": _answers,
}


def build(config: Config, book: RoleBook) -> dict[str, Any]:
    """The snapshot dict; ``fixtures/snapshot.json`` is its contract."""
    files = RunFiles.load(config, book)
    return {key: section(files) for key, section in SECTIONS.items()}

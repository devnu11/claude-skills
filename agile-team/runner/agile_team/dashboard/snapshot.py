"""Turn the run's files into the one JSON snapshot the dashboard renders.

Read-only; the contract is ``fixtures/snapshot.json``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from .. import config as config_mod
from .. import health, live, system, waits
from .. import roles as roles_mod
from .. import state as state_mod
from ..config import Config, ConfigError, config_path
from ..events import EVENTS
from ..gates import StoryStatus
from ..ledger import LEDGER, Entry, corrected
from ..priority import Priority
from ..relay import INBOX, OUTBOX
from ..roles import RoleBook, RoleError
from ..state import STATE_FILE, RunState

RUN_FILES = (STATE_FILE, EVENTS, LEDGER, OUTBOX, INBOX, live.HEARTBEAT, live.TURNS)
TURN_TAIL_BYTES = 262_144
TURN_WINDOW_S = 600
TURNS_SHOWN = 500
HISTORY_KEYS = ("at", "change", "reason", "role", "story")


@dataclass(frozen=True)
class RunFiles:
    """The inputs one snapshot reads, loaded once."""

    config: Config
    book: RoleBook
    state: RunState
    events: list[dict]
    now: float = 0.0
    mono: float | None = None

    @classmethod
    def load(cls, config: Config, book: RoleBook) -> RunFiles:
        """Read the state and the event log."""
        state = state_mod.load(config.run_dir)
        events = read_jsonl(config.run_dir / EVENTS)
        return cls(config, book, state, events, system.now(), system.monotonic())

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
    if not system.is_file(path):
        return []
    parsed = (_parse_line(line) for line in system.read_text(path).splitlines() if line.strip())
    return [item for item in parsed if item is not None]


def read_tail(path: Path, size: int) -> list[dict]:
    """JSON objects in the last ``size`` bytes of a JSONL file; a cut first line is dropped."""
    try:
        data, end = system.read_end(path, size)
        lines = data.decode(errors="replace").splitlines()
        cut = end > size
    except OSError:
        return []
    parsed = (_parse_line(line) for line in lines[1 if cut else 0 :] if line.strip())
    return [item for item in parsed if item is not None]


def watched_files(config: Config) -> list[Path]:
    """Every file a snapshot reads (missing ones included)."""
    run = [config.run_dir / name for name in RUN_FILES]
    stories = system.glob(config.stories_dir, "*.md")
    reqs = system.glob(config.requirements_dir, "REQ-*.md")
    return [*run, config_path(config.repo), *stories, *reqs]


def _generated_at(files: RunFiles) -> float:
    return files.now


def _pipeline(files: RunFiles) -> list[str]:
    return list(files.config.gates.steps)


def _priority(files: RunFiles) -> Priority:
    return Priority(files.state.order, files.state.pulled)


def _run(files: RunFiles) -> dict[str, Any]:
    state, config = files.state, files.config
    return {
        "status": str(state_mod.shown_status(config.run_dir, state)),
        "sprint": state.sprint,
        "cadence": state.cadence,
        "task": state.task,
        "budget_usd": config.team.budget_usd,
        "manager_every_pct": config.team.manager_every_pct,
        "round_cap": config.gates.round_cap,
        "manager_due": list(state.manager_due),
        "order": _priority(files).queue(state.stories.values()),
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
    if not system.is_file(path):
        return {}, ""
    try:
        meta, body = roles_mod.split_frontmatter(path.name, system.read_text(path))
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


def _position(files: RunFiles, story: Any) -> int | None:
    queue = _priority(files).queue(files.state.stories.values())
    return queue.index(story.id) + 1 if story.id in queue else None


def _tier(files: RunFiles, story: Any) -> str | None:
    if story.status is StoryStatus.DONE:
        return None
    return str(_priority(files).tier(story))


def _asking(files: RunFiles, story_id: str) -> list[str]:
    answered = {a.get("id") for a in files.lines(INBOX)}
    asked = (m for m in files.lines(OUTBOX) if m.get("kind") == "question")
    open_ = (m for m in asked if m.get("id") not in answered)
    return [f"{m['id']}: {m.get('text', '')}" for m in open_ if story_id in m.get("stories", [])]


def _wait(files: RunFiles, story: Any) -> dict[str, Any] | None:
    found = waits.wait(story, _asking(files, story.id))
    return None if found is None else {"reason": str(found.reason), "on": found.on}


def _story(files: RunFiles, story: Any) -> dict:
    return {
        "id": story.id,
        "title": story.title,
        "sprint": story.sprint,
        "delivery": story.delivery or "",
        "step": story.step,
        "status": str(story.status),
        "rounds": story.rounds,
        "repeated": story.repeated,
        "position": _position(files, story),
        "tier": _tier(files, story),
        "hold": story.hold,
        "wait": _wait(files, story),
        "opened_at": _opened_at(files.events, story.id),
        "acceptance": _acceptance(files.config, story.id),
    }


def _stories(files: RunFiles) -> list[dict]:
    ranked = _priority(files).ranked(files.state.stories.values())
    return [_story(files, story) for story in ranked]


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
    paths = system.glob(files.config.requirements_dir, "REQ-*.md")
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
    return [asdict(e) for e in corrected([Entry.from_dict(x) for x in files.lines(LEDGER)])]


def _messages(files: RunFiles) -> list[dict]:
    return files.lines(OUTBOX)


def _answers(files: RunFiles) -> list[dict]:
    return files.lines(INBOX)


def _stack_entry(entry: Any) -> dict[str, Any]:
    return {
        "sprint": entry.sprint,
        "branch": entry.branch,
        "base": entry.base,
        "pr": entry.pr,
        "url": entry.url,
        "mode": str(entry.mode),
        "check": str(entry.check),
        "head": entry.head,
    }


def _boundary(b: Any) -> dict[str, Any] | None:
    if b is None:
        return None
    failure = b.failure.reason.splitlines()[0] if b.failure and b.failure.reason else None
    return {
        "edge": str(b.edge),
        "sprint": b.sprint,
        "stage": str(b.stage),
        "hold": str(b.hold) if b.hold else None,
        "failure": failure,
        "rounds": b.rounds,
    }


def _upstream(files: RunFiles) -> dict[str, Any]:
    state, settings = files.state, files.config.upstream
    return {
        "remote": settings.remote,
        "branch": settings.branch,
        "team_branch": state.upstream.team_branch,
        "push": str(state.upstream.push),
        "report": state.upstream.report,
        "boundary": _boundary(state.boundary),
        "stack": [_stack_entry(e) for e in state.upstream.stack],
    }


def _turns(files: RunFiles) -> list[dict]:
    rows = read_tail(files.config.run_dir / live.TURNS, TURN_TAIL_BYTES)
    recent = [r for r in rows if r.get("at", 0) >= files.now - TURN_WINDOW_S]
    return recent[-TURNS_SHOWN:]


def _heartbeat(files: RunFiles) -> dict[str, Any] | None:
    return live.read_heartbeat(files.config.run_dir)


def _health(files: RunFiles) -> dict[str, Any]:
    verdict = health.judge(health.Vitals.read(files.config, health.Clock(files.now, files.mono)))
    return {"level": str(verdict.level), "reason": verdict.reason, "model_note": verdict.model_note}


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
    "upstream": _upstream,
    "turns": _turns,
    "heartbeat": _heartbeat,
    "health": _health,
}


def fresh_config(config: Config) -> Config:
    """The config as the file says now; the given one if the file is missing or bad."""
    try:
        return config_mod.load(config.repo)
    except ConfigError:
        return config


def build(config: Config, book: RoleBook) -> dict[str, Any]:
    """The snapshot dict; ``fixtures/snapshot.json`` is its contract.

    Re-reads ``.agile-team.toml`` each time.
    """
    files = RunFiles.load(fresh_config(config), book)
    return {key: section(files) for key, section in SECTIONS.items()}


def vital_sign(config: Config) -> str:
    """``level|reason`` of the run's health now; the server pushes when it changes (S6)."""
    return health.current(fresh_config(config)).key()

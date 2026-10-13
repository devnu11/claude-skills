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

from .. import backlog, dependencies, health, live, opinions, system, threads, tool_calls, waits
from .. import config as config_mod
from .. import roles as roles_mod
from .. import state as state_mod
from ..config import Config, ConfigError, config_path
from ..events import EVENTS
from ..gates import FINISHED, STEP_ROLES
from ..ledger import LEDGER, Entry, corrected
from ..priority import Priority
from ..relay import INBOX, OUTBOX, REPLY
from ..reorders import APPLIED, REORDERS_DIR, Request, Requests
from ..roles import RoleBook, RoleError
from ..state import STATE_FILE, RunState
from . import step_times, story_files, tool_groups

RUN_FILES = (
    STATE_FILE,
    EVENTS,
    LEDGER,
    OUTBOX,
    INBOX,
    live.HEARTBEAT,
    live.TURNS,
    tool_calls.TOOLS,
    live.SLEEPS,
)
TURN_TAIL_BYTES = 262_144
SLEEPS_TAIL_BYTES = 262_144
TOOLS_TAIL_BYTES = 4_194_304
TURN_WINDOW_S = 600
TURNS_SHOWN = 500
REORDERS_SHOWN = 20
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
    asks = system.glob(config.run_dir / REORDERS_DIR, "r*.json")
    return [
        *run,
        config_path(config.repo),
        *stories,
        *reqs,
        *asks,
        *threads.watched(config.run_dir),
        *opinions.watched(config.run_dir),
    ]


def _generated_at(files: RunFiles) -> float:
    return files.now


def _pipeline(files: RunFiles) -> list[str]:
    return list(files.config.gates.steps)


def _priority(files: RunFiles) -> Priority:
    return Priority(files.state.order, files.state.pulled)


def _run(files: RunFiles) -> dict[str, Any]:
    state, config = files.state, files.config
    view = backlog.View.of(state)
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
        "order_version": view.version,
        "backlog": view.backlog,
    }


def _role(files: RunFiles, name: str) -> dict | None:
    try:
        role = files.book.resolve(name, files.state.runtime_overrides(name))
    except RoleError:
        return None
    if not role.enabled:
        return None
    return {"name": name, "model": role.model, "provider": role.provider}


UNKNOWN_MODEL = "unknown"


def _configured_model(files: RunFiles, role: str) -> str:
    """The role's model as configured now (ST7), or ``UNKNOWN_MODEL``."""
    found = _role(files, role)
    return found["model"] if found else UNKNOWN_MODEL


def _step(files: RunFiles, span: step_times.Span) -> dict:
    """One ``steps`` object; ``model`` falls back to the configured one (ST7).

    ``recorded_model`` is the end's own (MF6).
    """
    step = span.as_dict()
    step["model"] = span.model or _configured_model(files, span.role)
    step["recorded_model"] = span.model
    return step


def _watch(files: RunFiles) -> step_times.Stopwatch:
    """The reader's clocks now (AW4, AW9): platform, wall, monotonic, the heartbeat's ``slept``."""
    beat = _heartbeat(files) or {}
    now = step_times.Mark(files.now, files.mono, step_times.number(beat.get("slept")))
    return step_times.Stopwatch(step_times.platform_of(system.platform()), now)


def _steps(files: RunFiles) -> list[dict]:
    """Every agent step with its awake time (s96, s97)."""
    return [_step(files, span) for span in step_times.spans(files.events, _watch(files))]


GENERIC_DEVELOPER = STEP_ROLES["implement"]  # stands for the repo's developer roles


def _assigned_developers(state: RunState) -> frozenset[str]:
    """Every story's developer and PO-chosen developer that is set (FL7a)."""
    names = (n for s in state.stories.values() for n in (s.developer, s.po_developer))
    return frozenset(n for n in names if n)


def _step_role(files: RunFiles, step: str) -> frozenset[str]:
    role = STEP_ROLES.get(step)
    if role != GENERIC_DEVELOPER:
        return frozenset({role} if role else ())
    return _assigned_developers(files.state) or frozenset({role})


def _routed_roles(files: RunFiles) -> frozenset[str]:
    """Roles the repo's pipeline steps route to (FL7a)."""
    return frozenset().union(*(_step_role(files, step) for step in _pipeline(files)))


def _stepped_roles(events: list[dict]) -> frozenset[str]:
    """Roles with at least one ``step-start`` event (FL7b)."""
    return frozenset(e["role"] for e in events if e.get("kind") == "step-start" and e.get("role"))


def _used_roles(files: RunFiles) -> frozenset[str]:
    """Roles routed to by the pipeline or already stepped (FL7)."""
    return _routed_roles(files) | _stepped_roles(files.events)


def _roles(files: RunFiles) -> list[dict]:
    """Enabled roles, each with ``used`` (FL7)."""
    used = _used_roles(files)
    found = (_role(files, name) for name in sorted(files.book.names()))
    return [{**role, "used": role["name"] in used} for role in found if role is not None]


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
    if story.status in FINISHED:
        return None
    return str(_priority(files).tier(story))


def _asking(files: RunFiles, story_id: str) -> list[str]:
    answered = {a.get("id") for a in files.lines(INBOX)}
    asked = (m for m in files.lines(OUTBOX) if m.get("kind") == "question")
    open_ = (m for m in asked if m.get("id") not in answered)
    return [f"{m['id']}: {m.get('text', '')}" for m in open_ if story_id in m.get("stories", [])]


def _wait(files: RunFiles, story: Any) -> dict[str, Any] | None:
    found = waits.wait(story, _asking(files, story.id))
    if found is None:
        return None
    return {"reason": str(found.reason), "on": found.on, "title": found.title}


def _story(files: RunFiles, story: Any) -> dict:
    return {
        "id": story.id,
        "title": story.title,
        "sprint": story.sprint,
        "environment": story.environment or "",
        "step": story.step,
        "status": str(story.status),
        "rounds": story.rounds,
        "repeated": story.repeated,
        "position": _position(files, story),
        "tier": _tier(files, story),
        "hold": story.hold,
        "po_hold": asdict(story.po_hold) if story.po_hold else None,
        "wait": _wait(files, story),
        "opened_at": _opened_at(files.events, story.id),
        "acceptance": _acceptance(files.config, story.id),
        "disputes": story.disputes,
        "developer": story.developer,
        "commits": [c for c in dict.fromkeys([story.commit, *story.code_commits]) if c],
        "files": story_files.existing(files.config, story.id),
        "label": backlog.label(story),
        **_dependency_keys(files, story),
    }


def _dependency_keys(files: RunFiles, story: Any) -> dict[str, list[str]]:
    stories = files.state.stories
    queue = _priority(files).queue(stories.values())
    done = story.status in FINISHED
    return {
        "depends_on": list(story.depends_on),
        "waiting_on": [] if done else dependencies.waiting_on(story, stories),
        "dependency_warnings": dependencies.warning_texts(story, queue),
    }


def _reorder(files: RunFiles, request: Request) -> dict[str, Any]:
    done = files.state.reorders.get(request.id)
    status = "pending" if done is None else "applied" if done == APPLIED else "refused"
    reason = done if status == "refused" else ""
    ask = request.ask
    return {"id": request.id, "story": ask.story, "position": ask.position,
            "at": request.at, "status": status, "reason": reason}  # fmt: skip


def _reorders(files: RunFiles) -> list[dict]:
    asked = Requests(files.config.run_dir).all()[-REORDERS_SHOWN:]
    return [_reorder(files, request) for request in asked]


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


def _thread_event(entry: threads.Entry) -> dict:
    return {"id": f"thread-{entry.id}", "at": entry.at, "kind": "thread",
            "role": threads.EVENT_ROLES.get(entry.author), "story": entry.story or None,
            "data": {"entry": entry.id, "author": str(entry.author),
                     "to": str(entry.to)}}  # fmt: skip


def _opinion_event(opinion: opinions.Opinion) -> dict:
    return {"id": f"opinion-{opinion.id}", "at": opinion.at, "kind": "opinion",
            "role": None, "story": opinion.story,
            "data": {"opinion": opinion.id, "kind": str(opinion.kind)}}  # fmt: skip


def _act_event(act: opinions.Settled) -> dict:
    return {"id": f"opinion-act-{act.id}", "at": act.at, "kind": "opinion-act",
            "role": None, "story": act.story,
            "data": {"opinion": act.opinion, "act": str(act.act), "route": str(act.route),
                     "ref": act.ref}}  # fmt: skip


def _events(files: RunFiles) -> list[dict]:
    outbox = [m for m in files.lines(OUTBOX) if m.get("kind") != REPLY]
    sent = map(_message_event, outbox)
    received = map(_answer_event, files.lines(INBOX))
    posts = map(_thread_event, threads.Threads(files.config.run_dir).all())
    box = opinions.Opinions(files.config.run_dir)
    marks = map(_opinion_event, box.all())
    acts = map(_act_event, box.acts())
    merged = [*files.events, *sent, *received, *posts, *marks, *acts]
    return sorted(merged, key=lambda e: e.get("at", 0.0))


def _ledger(files: RunFiles) -> list[dict]:
    return [asdict(e) for e in corrected([Entry.from_dict(x) for x in files.lines(LEDGER)])]


def _messages(files: RunFiles) -> list[dict]:
    return files.lines(OUTBOX)


def _answers(files: RunFiles) -> list[dict]:
    return files.lines(INBOX)


def _thread(files: RunFiles) -> list[dict]:
    return [entry.as_dict() for entry in threads.Threads(files.config.run_dir).all()]


def _item_act(act: opinions.Settled | None) -> dict | None:
    """The act on an opinion as the snapshot shows it (the item names the opinion)."""
    if act is None:
        return None
    return {k: v for k, v in act.as_dict().items() if k not in ("opinion", "story")}


def _opinion_item(opinion: opinions.Opinion, board: opinions.Board, view: backlog.View) -> dict:
    latest = board.latest()[opinion.story] == opinion
    act = board.act_of(opinion.id)
    route = opinions.route_of(opinion, view) if latest and act is None else opinions.Route.NONE
    return {**opinion.as_dict(), "latest": latest, "route": str(route),
            "act": _item_act(act)}  # fmt: skip


def _opinions(files: RunFiles) -> dict:
    box = opinions.Opinions(files.config.run_dir)
    board, view = box.board(), backlog.View.of(files.state)
    reviews = box.reviews()
    return {
        "items": [_opinion_item(o, board, view) for o in board.opinions],
        "asked_at": box.asked_at(),
        "review": reviews[-1].as_dict() if reviews else None,
    }


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


def _tools(files: RunFiles) -> list[dict]:
    rows = read_tail(files.config.run_dir / tool_calls.TOOLS, TOOLS_TAIL_BYTES)
    return tool_groups.groups(rows, files.config.dashboard.collapse_under_s)


def misc_calls(config: Config, ask: tool_groups.MiscAsk) -> list[dict] | None:
    """A step's misc calls, re-gathered from the ``tools.jsonl`` tail (N12); ``None`` if bad."""
    key = tool_groups.ask_key(ask)
    if key is None:
        return None
    rows = read_tail(config.run_dir / tool_calls.TOOLS, TOOLS_TAIL_BYTES)
    return tool_groups.gathered_calls(rows, key, config.dashboard.collapse_under_s)


def _sleep_row(row: dict) -> dict | None:
    start, end, slept = (step_times.number(row.get(k)) for k in ("from", "to", "slept"))
    if start is None or end is None or slept is None:
        return None
    if start > end or not 0 <= slept <= end - start:
        return None
    return {"from": start, "to": end, "slept": slept}


def _sleeps(files: RunFiles) -> list[dict]:
    rows = read_tail(files.config.run_dir / live.SLEEPS, SLEEPS_TAIL_BYTES)
    valid = [r for r in map(_sleep_row, rows) if r is not None]
    return sorted(valid, key=lambda r: r["from"])


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
    "reorders": _reorders,
    "events": _events,
    "ledger": _ledger,
    "steps": _steps,
    "tools": _tools,
    "sleeps": _sleeps,
    "messages": _messages,
    "answers": _answers,
    "thread": _thread,
    "opinions": _opinions,
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

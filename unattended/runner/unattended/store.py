"""Where jobs live: ``<repo>/.claude/jobs/<name>/`` when that directory exists, else ``~``.

A job directory holds ``state.json`` (written atomically), ``events.jsonl``,
the output (``output.md`` for prompts, ``output.log`` for commands), the stop
file and the supervisor's pid file.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from .auth import Auth
from .limits import DEFAULT_FALLBACK, Bounds, Progress

JOBS = Path(".claude/jobs")
STATE_FILE = "state.json"
EVENTS_FILE = "events.jsonl"
OUTPUT_FILE = "output.md"
LOG_FILE = "output.log"
STOP_FILE = "stop"
PID_FILE = "supervisor.pid"
SUPERVISOR_LOG = "supervisor.log"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
DEFAULT_RESUME_PROMPT = "Continue where you left off. If you are done, say so."


class JobError(Exception):
    """A user-facing job problem: bad name, unknown job, or one that already exists."""


class JobStatus(StrEnum):
    """Where a job stands; the last four are final."""

    RUNNING = "running"
    WAITING = "waiting"
    DONE = "done"
    FAILED = "failed"
    STOPPED = "stopped"
    LIMIT_REACHED = "limit-reached"


ENDED = frozenset({JobStatus.DONE, JobStatus.FAILED, JobStatus.STOPPED, JobStatus.LIMIT_REACHED})


class JobKind(StrEnum):
    """What a job runs."""

    PROMPT = "prompt"
    COMMAND = "command"


@dataclass
class Spec:
    """What the job runs and how; fixed when it starts."""

    kind: JobKind
    cwd: str
    prompt: str = ""
    command: str = ""
    resume_prompt: str = DEFAULT_RESUME_PROMPT
    resume_command: str = ""
    auth: Auth = Auth.LOGIN
    key_file: str | None = None
    model: str | None = None
    permission_mode: str | None = None
    fallback_wait: float = DEFAULT_FALLBACK


@dataclass
class JobState:
    """Everything ``state.json`` holds."""

    name: str
    spec: Spec
    bounds: Bounds = field(default_factory=Bounds)
    status: JobStatus = JobStatus.RUNNING
    reason: str = ""
    runs: int = 0
    resumes: int = 0
    retries: int = 0
    cost: float = 0.0
    session_id: str | None = None
    next_wake: float | None = None
    created: float = field(default_factory=time.time)

    def mark(self, status: JobStatus, reason: str = "") -> None:
        """Set the status and why; a status without a reason clears the old one."""
        self.status, self.reason = status, reason

    def progress(self, next_wake: float) -> Progress:
        return Progress(self.resumes, self.cost, next_wake)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> JobState:
        data = json.loads(text)
        spec = data["spec"]
        data["spec"] = Spec(**{**spec, "kind": JobKind(spec["kind"]), "auth": Auth(spec["auth"])})
        data["bounds"] = Bounds(**data["bounds"])
        data["status"] = JobStatus(data["status"])
        return cls(**data)


def alive(pid: int) -> bool:
    """True when a process with ``pid`` exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass(frozen=True)
class Job:
    """One job directory."""

    dir: Path

    @property
    def name(self) -> str:
        return self.dir.name

    def path(self, filename: str) -> Path:
        return self.dir / filename

    def load(self) -> JobState:
        return JobState.from_json(self.path(STATE_FILE).read_text())

    def save(self, state: JobState) -> None:
        """Write atomically so a crash mid-write never leaves a torn state file."""
        tmp = self.path(f"{STATE_FILE}.{os.getpid()}.tmp")
        tmp.write_text(state.to_json())
        tmp.replace(self.path(STATE_FILE))

    def update(self, change: Callable[[JobState], object]) -> JobState:
        """Load, apply ``change``, save and return the new state."""
        state = self.load()
        change(state)
        self.save(state)
        return state

    def event(self, kind: str, data: dict[str, Any] | None = None) -> None:
        """Append one timestamped line to ``events.jsonl``."""
        line = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": kind, **(data or {})}
        with self.path(EVENTS_FILE).open("a") as events:
            events.write(json.dumps(line) + "\n")

    def request_stop(self) -> None:
        self.path(STOP_FILE).touch()

    def stop_requested(self) -> bool:
        return self.path(STOP_FILE).exists()

    def clear_stop(self) -> None:
        self.path(STOP_FILE).unlink(missing_ok=True)

    def pid(self) -> int | None:
        """The live supervisor's pid, or None when none is running."""
        path = self.path(PID_FILE)
        pid = int(path.read_text()) if path.is_file() else None
        return pid if pid is not None and alive(pid) else None

    @contextmanager
    def pid_file(self) -> Iterator[None]:
        """Record this process as the job's supervisor while the block runs."""
        path = self.path(PID_FILE)
        path.write_text(str(os.getpid()))
        try:
            yield
        finally:
            path.unlink(missing_ok=True)


def git_root(start: Path) -> Path | None:
    """The nearest directory at or above ``start`` that holds ``.git``."""
    start = start.resolve()
    return next((d for d in (start, *start.parents) if (d / ".git").exists()), None)


@dataclass(frozen=True)
class JobHome:
    """The directory holding job directories."""

    root: Path

    @classmethod
    def find(cls, cwd: Path, home: Path) -> JobHome:
        """The repo's ``.claude/jobs`` when it exists, else ``~/.claude/jobs``."""
        repo = git_root(cwd)
        if repo is not None and (repo / JOBS).is_dir():
            return cls(repo / JOBS)
        return cls(home / JOBS)

    def job(self, name: str) -> Job:
        """An existing job, or ``JobError``."""
        job = Job(self.root / check_name(name))
        if not job.path(STATE_FILE).is_file():
            raise JobError(f"no job named {name!r} in {self.root}")
        return job

    def create(self, state: JobState) -> Job:
        """A new job directory holding ``state``; names are unique within a home."""
        job = Job(self.root / check_name(state.name))
        try:
            job.dir.mkdir(parents=True)
        except FileExistsError:
            raise JobError(f"job {state.name!r} already exists in {self.root}") from None
        job.save(state)
        return job

    def jobs(self) -> list[Job]:
        """Every job here, by name."""
        found = sorted(self.root.glob(f"*/{STATE_FILE}")) if self.root.is_dir() else []
        return [Job(path.parent) for path in found]


def check_name(name: str) -> str:
    """``name`` when it is a safe directory name, else ``JobError``."""
    if not NAME.fullmatch(name):
        raise JobError(f"bad job name {name!r}: use letters, digits, '.', '_' or '-'")
    return name

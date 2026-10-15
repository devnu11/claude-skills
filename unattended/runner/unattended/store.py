"""Where jobs live: ``<repo>/.claude/jobs/<name>/`` when that directory exists, else ``~``.

A job directory holds ``state.json`` (written atomically), ``events.jsonl``,
the output (``output.md`` for prompts, ``output.log`` for commands), the stop
file, the supervisor's pid file and the run's heartbeat file.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from .auth import Auth
from .awake import SleepPolicy
from .limits import DEFAULT_FALLBACK, Bounds, Progress, WakeOn

JOBS = Path(".claude/jobs")
STATE_FILE = "state.json"
EVENTS_FILE = "events.jsonl"
OUTPUT_FILE = "output.md"
LOG_FILE = "output.log"
STOP_FILE = "stop"
WAKE_FILE = "wake"
PID_FILE = "supervisor.pid"
HEARTBEAT_FILE = "heartbeat.json"
HEARTBEAT_ENV = "UNATTENDED_HEARTBEAT"
SUPERVISOR_LOG = "supervisor.log"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
DEFAULT_IDLE = 20 * 60.0
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
    stop_command: str = ""
    auth: Auth = Auth.LOGIN
    key_file: str | None = None
    model: str | None = None
    permission_mode: str | None = None
    fallback_wait: float = DEFAULT_FALLBACK
    sleep: SleepPolicy = SleepPolicy.PREVENT
    idle: float | None = DEFAULT_IDLE
    progress: list[str] = field(default_factory=list)
    notify: str = ""


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
    wake_on: WakeOn | None = None
    created: float = field(default_factory=time.time)

    def mark(self, status: JobStatus, reason: str = "") -> None:
        """Set the status and why, and clear the wake time.

        A status without a reason clears the old one; a timed wait sets its wake after this.
        """
        self.status, self.reason = status, reason
        self.next_wake = self.wake_on = None

    def progress(self, next_wake: float) -> Progress:
        return Progress(self.resumes, self.cost, next_wake)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> JobState:
        data = json.loads(text)
        spec = data["spec"]
        enums = {"kind": JobKind(spec["kind"]), "auth": Auth(spec["auth"])}
        data["spec"] = Spec(
            **{**spec, **enums, "sleep": SleepPolicy(spec.get("sleep", SleepPolicy.PREVENT))}
        )
        data["bounds"] = Bounds(**data["bounds"])
        data["status"] = JobStatus(data["status"])
        data["wake_on"] = _wake_on(data)
        return cls(**data)


def _wake_on(data: dict[str, Any]) -> WakeOn | None:
    stored = data.get("wake_on")
    return WakeOn(stored) if stored else None


# Win32 values for the Windows probe
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
NO_INHERIT = 0
STILL_ACTIVE = 259  # GetExitCodeProcess's code for a process that has not exited
ERROR_ACCESS_DENIED = 5


def alive(pid: int) -> bool:
    """True when a process with ``pid`` exists."""
    return ALIVE_PROBES.get(sys.platform, _alive_on_posix)(pid)


def _alive_on_posix(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass(frozen=True)
class Win32:
    """The kernel32 calls the Windows probe makes."""

    dll: Any

    def open(self, pid: int) -> int:  # pragma: no cover -- runs only on Windows
        """A query handle for ``pid``, or 0."""
        return self.dll.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, NO_INHERIT, pid)

    def last_error(self) -> int:  # pragma: no cover -- runs only on Windows
        """The calling thread's last Win32 error."""
        import ctypes

        return ctypes.get_last_error()  # type: ignore[attr-defined]

    def exit_code(self, handle: int) -> int:  # pragma: no cover -- runs only on Windows
        """The process's exit code; ``STILL_ACTIVE`` while it runs."""
        import ctypes

        code = ctypes.c_ulong()
        self.dll.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value

    def close(self, handle: int) -> None:  # pragma: no cover -- runs only on Windows
        """Release ``handle``."""
        self.dll.CloseHandle(handle)


def kernel32() -> Win32:  # pragma: no cover -- runs only on Windows
    """The real kernel32, with Win32 errors kept per thread."""
    import ctypes

    return Win32(ctypes.WinDLL("kernel32", use_last_error=True))  # type: ignore[attr-defined]


def _alive_on_windows(pid: int, win32: Any = None) -> bool:
    # os.kill(pid, 0) on Windows terminates the process instead of probing it
    api = win32 or kernel32()
    handle = api.open(pid)
    if not handle:
        return api.last_error() == ERROR_ACCESS_DENIED
    try:
        return api.exit_code(handle) == STILL_ACTIVE
    finally:
        api.close(handle)


ALIVE_PROBES: dict[str, Callable[[int], bool]] = {"win32": _alive_on_windows}


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

    def request_wake(self) -> None:
        """Ask a waiting supervisor to resume now instead of at the reset."""
        self.path(WAKE_FILE).touch()

    def wake_requested(self) -> bool:
        return self.path(WAKE_FILE).exists()

    def clear_wake(self) -> None:
        self.path(WAKE_FILE).unlink(missing_ok=True)

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

"""Progress probes: what tells the supervisor that a running job is making progress.

A probe is data, ``KIND`` or ``KIND:ARG`` (``--progress``, repeatable), read
through the ``PROBES`` table. Each probe returns a ``Reading`` whose ``value``
changes only when the job makes progress; the watch compares readings slice
by slice. A reading may also carry ``alive_at``, a liveness stamp (the
heartbeat's ``at``), which makes a stale one *hung*. Paths are relative to
the job's cwd. ``cpu`` and
``children`` read the run's process group with ``ps``, so they are POSIX only.
"""

from __future__ import annotations

import itertools
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .store import LOG_FILE, Job, JobKind

COMMAND_TIMEOUT = 10.0
DAY = 86400
PS = ["ps", "-A", "-o", "pgid=", "-o", "pid=", "-o", "time="]
DEFAULT_PROBES: dict[JobKind, tuple[str, ...]] = {
    JobKind.COMMAND: ("output", "cpu"),
    JobKind.PROMPT: ("spend",),
}


@dataclass
class Stamp:
    """A counter a runner bumps each time it sees progress; the ``spend`` probe reads it."""

    count: int = 0

    def tick(self) -> None:
        self.count += 1


@dataclass(frozen=True)
class Reading:
    """One sample: a value that changes with progress, and when the job last said it is alive."""

    value: object
    alive_at: float | None = None
    waiting: str | None = None


Probe = Callable[[], Reading]


@dataclass
class Context:
    """What probes read: the job, its cwd, the spend stamp and the run's process group."""

    job: Job
    cwd: Path
    spend: Stamp
    pgid: int | None = None


# ----- readers -----------------------------------------------------------------------


def file_reading(path: Path) -> Reading:
    """The file's size and mtime; None while it is missing."""
    try:
        found = path.stat()
    except OSError:
        return Reading(None)
    return Reading((found.st_size, found.st_mtime_ns))


def load_json(path: Path) -> Any:
    """The parsed file, or None when it is missing or not JSON."""
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def dotted(data: Any, key: str) -> Any:
    """``data[a][b]`` for the key ``a.b``; None where a step is missing."""
    for part in key.split("."):
        data = data.get(part) if isinstance(data, dict) else None
    return data


def json_probe(arg: str, ctx: Context) -> Probe:
    """The values at the dotted keys of ``PATH:KEY[,KEY…]``; a missing step reads None."""
    path, keys = json_args(arg)

    def read() -> Reading:
        data = load_json(ctx.cwd / path)
        return Reading(tuple(dotted(data, key) for key in keys))

    return read


def heartbeat_reading(path: Path) -> Reading:
    """``{"at": <epoch>, "progress": <any>, "waiting": <text>}``: progress is the value, ``at``
    the liveness stamp, and ``waiting`` (optional) why the run is idle on purpose."""
    data = load_json(path)
    if not isinstance(data, dict):
        return Reading(None)
    at, waiting = data.get("at"), data.get("waiting")
    stamp = float(at) if isinstance(at, int | float) else None
    return Reading(data.get("progress"), stamp, waiting if isinstance(waiting, str) else None)


def cpu_seconds(text: str) -> float:
    """``ps`` CPU time in seconds: ``[[dd-]hh:]mm:ss`` (Linux) or ``m:ss.cc`` (macOS)."""
    days, _, clock = text.rpartition("-")
    parts = enumerate(reversed(clock.split(":")))
    return sum(float(part) * 60**place for place, part in parts) + DAY * int(days or 0)


def ps_output() -> str:
    """Every process as ``pgid pid time`` lines."""
    return subprocess.run(PS, capture_output=True, text=True, check=False).stdout


list_processes: Callable[[], str] = ps_output


def group(pgid: int | None) -> list[tuple[int, str]]:
    """The (pid, CPU time) of each live process in process group ``pgid``."""
    if pgid is None:
        return []
    rows = (line.split() for line in list_processes().splitlines())
    return [(int(row[1]), row[2]) for row in rows if len(row) == 3 and int(row[0]) == pgid]


def cpu_reading(ctx: Context) -> Reading:
    members = group(ctx.pgid)
    return Reading(sum(cpu_seconds(time) for _, time in members) if members else None)


def children_reading(ctx: Context) -> Reading:
    members = group(ctx.pgid)
    return Reading(frozenset(pid for pid, _ in members) if members else None)


def command_probe(command: str, ctx: Context) -> Probe:
    """Progress when ``command`` exits 0 printing nothing, or its stdout differs."""
    fresh = itertools.count()

    def read() -> Reading:
        try:
            done = subprocess.run(command, shell=True, cwd=ctx.cwd, capture_output=True,
                                  text=True, timeout=COMMAND_TIMEOUT, check=False)  # fmt: skip
        except subprocess.TimeoutExpired:
            return Reading(None)
        return Reading(_command_value(done, fresh))

    return read


def _command_value(done: subprocess.CompletedProcess[str], fresh: itertools.count[int]) -> object:
    if done.returncode:
        return None
    return done.stdout or ("exit 0", next(fresh))


# ----- the table ---------------------------------------------------------------------


class Takes(StrEnum):
    """What argument a probe kind takes."""

    NOTHING = "nothing"
    TEXT = "text"
    JSON = "json"


def json_args(arg: str) -> tuple[str, list[str]]:
    """``PATH:KEY[,KEY…]`` split into the path and the keys."""
    path, _, keys = arg.rpartition(":")
    return path, [key for key in keys.split(",") if key]


ARG_PROBLEMS: dict[Takes, Callable[[str], str | None]] = {
    Takes.NOTHING: lambda arg: "takes no argument" if arg else None,
    Takes.TEXT: lambda arg: None if arg else "needs an argument",
    Takes.JSON: lambda arg: None if all(json_args(arg)) else "needs PATH:KEY[,KEY…]",
}


@dataclass(frozen=True)
class ProbeKind:
    """How to build one kind of probe, what argument it takes and which jobs it suits."""

    make: Callable[[str, Context], Probe]
    takes: Takes
    jobs: frozenset[JobKind]


ANY_JOB = frozenset(JobKind)
COMMAND_JOB = frozenset({JobKind.COMMAND})
PROMPT_JOB = frozenset({JobKind.PROMPT})

PROBES: dict[str, ProbeKind] = {
    "output": ProbeKind(lambda arg, ctx: lambda: file_reading(ctx.job.path(LOG_FILE)),
                        Takes.NOTHING, COMMAND_JOB),
    "spend": ProbeKind(lambda arg, ctx: lambda: Reading(ctx.spend.count),
                       Takes.NOTHING, PROMPT_JOB),
    "file": ProbeKind(lambda arg, ctx: lambda: file_reading(ctx.cwd / arg), Takes.TEXT, ANY_JOB),
    "json": ProbeKind(json_probe, Takes.JSON, ANY_JOB),
    "heartbeat": ProbeKind(lambda arg, ctx: lambda: heartbeat_reading(ctx.cwd / arg),
                           Takes.TEXT, ANY_JOB),
    "cpu": ProbeKind(lambda arg, ctx: lambda: cpu_reading(ctx), Takes.NOTHING, COMMAND_JOB),
    "children": ProbeKind(lambda arg, ctx: lambda: children_reading(ctx),
                          Takes.NOTHING, COMMAND_JOB),
    "command": ProbeKind(command_probe, Takes.TEXT, ANY_JOB),
}  # fmt: skip


# ----- parsing -----------------------------------------------------------------------


def split(text: str) -> tuple[str, str]:
    """``KIND:ARG`` as (kind, arg); the arg may itself hold colons."""
    kind, _, arg = text.partition(":")
    return kind, arg


def problem(text: str, job: JobKind) -> str | None:
    """Why ``--progress text`` is unusable for a ``job`` job, or None when it is fine."""
    kind, arg = split(text)
    found = PROBES.get(kind)
    if found is None:
        return f"unknown probe {kind!r} (known: {', '.join(PROBES)})"
    if job not in found.jobs:
        return f"probe {kind!r} does not apply to {job} jobs"
    issue = ARG_PROBLEMS[found.takes](arg)
    return f"probe {kind!r} {issue}" if issue else None


def problems(texts: list[str], job: JobKind) -> list[str]:
    """Why any of the ``--progress`` values is unusable; empty when all are fine."""
    return [issue for text in texts if (issue := problem(text, job))]


def chosen(texts: list[str], job: JobKind) -> list[str]:
    """The probes given, else the defaults for the job's kind."""
    return texts or list(DEFAULT_PROBES[job])


def build(text: str, ctx: Context) -> Probe:
    kind, arg = split(text)
    return PROBES[kind].make(arg, ctx)

"""``unattended``: run a prompt or command unattended, resuming after usage limits.

start | status | list | wait | log | stop | resume. Jobs live in the repo's
``.claude/jobs/`` when it exists, else ``~/.claude/jobs/``. Errors print
``unattended <cmd>: <message>`` and return 1.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, get_args

from claude_agent_sdk.types import PermissionMode

from .auth import Auth, AuthSetup
from .command_job import CommandJob
from .limits import Bounds, local, parse_duration, parse_until
from .prompt_job import PromptJob
from .store import (
    DEFAULT_RESUME_PROMPT,
    ENDED,
    EVENTS_FILE,
    LOG_FILE,
    OUTPUT_FILE,
    PID_FILE,
    SUPERVISOR_LOG,
    Job,
    JobError,
    JobHome,
    JobKind,
    JobState,
    JobStatus,
    Spec,
)
from .supervisor import STOP_REASON, Runner, Supervisor, install_sigterm

POLL = 5.0
FOLLOW_POLL = 1.0
EXIT_CODES: dict[JobStatus, int] = {
    JobStatus.DONE: 0,
    JobStatus.FAILED: 1,
    JobStatus.LIMIT_REACHED: 75,
    JobStatus.STOPPED: 143,
}
RESUMABLE = frozenset({JobStatus.STOPPED, JobStatus.LIMIT_REACHED})
OUTPUTS = {JobKind.PROMPT: OUTPUT_FILE, JobKind.COMMAND: LOG_FILE}
LIVE_FILES = (EVENTS_FILE, LOG_FILE)
Kill = Callable[[int, int], None]
Sleep = Callable[[float], None]


class CliError(Exception):
    """A user-facing failure; the message is printed as is."""


class Launch(StrEnum):
    """Where the supervisor runs."""

    DETACH = "detach"
    FOREGROUND = "foreground"


class Follow(StrEnum):
    """Whether ``log`` keeps printing as the job writes."""

    ONCE = "once"
    FOLLOW = "follow"


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2))


def job_home(args: argparse.Namespace) -> JobHome:
    return JobHome.find(Path.cwd(), Path(args.home))


def iso(epoch: float | None) -> str | None:
    return local(epoch).isoformat(timespec="seconds") if epoch is not None else None


# ----- building a job ------------------------------------------------------------


def spec_from(args: argparse.Namespace) -> Spec:
    """The job's spec from ``start``'s flags."""
    kind = JobKind.COMMAND if args.command is not None else JobKind.PROMPT
    _require_kind_flags(args, kind)
    return Spec(
        kind=kind,
        cwd=str(_directory(args.cwd)),
        prompt=_prompt_text(args),
        command=args.command or "",
        resume_prompt=args.resume_prompt or DEFAULT_RESUME_PROMPT,
        resume_command=args.resume_command or "",
        auth=args.auth,
        key_file=str(Path(args.key_file).resolve()) if args.key_file else None,
        model=args.model,
        permission_mode=args.permission_mode,
        fallback_wait=_duration(args.fallback_wait),
    )


KIND_ONLY: dict[JobKind, tuple[str, ...]] = {
    JobKind.PROMPT: ("resume_prompt", "model", "permission_mode"),
    JobKind.COMMAND: ("resume_command",),
}


def _require_kind_flags(args: argparse.Namespace, kind: JobKind) -> None:
    """Refuse flags that only the other kind of job uses."""
    other = next(k for k in KIND_ONLY if k is not kind)
    wrong = [f"--{name.replace('_', '-')}" for name in KIND_ONLY[other] if getattr(args, name)]
    if wrong:
        raise CliError(f"{', '.join(wrong)} only apply to {other} jobs")


def _directory(path: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_dir():
        raise CliError(f"--cwd {path} is not a directory")
    return resolved


def _prompt_text(args: argparse.Namespace) -> str:
    if args.prompt_file is None:
        return args.prompt or ""
    try:
        return Path(args.prompt_file).read_text()
    except OSError as exc:
        raise CliError(f"cannot read --prompt-file: {exc.strerror}") from exc


def _duration(text: str) -> float:
    try:
        return parse_duration(text)
    except ValueError as exc:
        raise CliError(str(exc)) from exc


def deadline_from(args: argparse.Namespace, now: float) -> float | None:
    """Epoch seconds from ``--until`` or ``--for``; None when neither is given."""
    try:
        if args.until is not None:
            deadline = parse_until(args.until, local(now)).timestamp()
        elif args.for_ is not None:
            deadline = now + parse_duration(args.for_)
        else:
            return None
    except ValueError as exc:
        raise CliError(str(exc)) from exc
    return _future(deadline, now)


def _future(deadline: float, now: float) -> float:
    if deadline <= now:
        raise CliError(f"the deadline {iso(deadline)} has already passed")
    return deadline


def updated_bounds(bounds: Bounds, args: argparse.Namespace) -> Bounds:
    """``bounds`` with whichever limits the flags give replaced."""
    deadline = deadline_from(args, time.time())
    return Bounds(
        deadline=bounds.deadline if deadline is None else deadline,
        max_resumes=bounds.max_resumes if args.max_resumes is None else args.max_resumes,
        max_cost=bounds.max_cost if args.max_cost is None else args.max_cost,
    )


def auth_setup(spec: Spec, home: Path) -> AuthSetup:
    return AuthSetup(spec.auth, Path(spec.key_file) if spec.key_file else None, home)


def require_auth(spec: Spec, home: Path) -> None:
    problems = auth_setup(spec, home).problems(os.environ)
    if problems:
        raise CliError("; ".join(problems))


# ----- running -------------------------------------------------------------------

RUNNERS: dict[JobKind, Callable[[Job, dict[str, str]], Runner]] = {
    JobKind.PROMPT: lambda job, env: PromptJob(job, env),
    JobKind.COMMAND: lambda job, env: CommandJob(job, {**os.environ, **env}),
}


def runner_for(job: Job, home: Path) -> Runner:
    spec = job.load().spec
    return RUNNERS[spec.kind](job, auth_setup(spec, home).env())


def run_supervisor(job: Job, home: Path) -> JobStatus:
    """Supervise ``job`` in this process; an unexpected error marks it failed."""
    install_sigterm()
    with job.pid_file():
        try:
            return Supervisor(job, runner_for(job, home)).run()
        except Exception as exc:
            return _crashed(job, exc)


def _crashed(job: Job, exc: Exception) -> JobStatus:
    traceback.print_exception(exc)
    reason = f"supervisor crashed: {type(exc).__name__}: {exc}"
    job.update(lambda st: st.mark(JobStatus.FAILED, reason))
    job.event("end", {"status": JobStatus.FAILED, "reason": reason})
    return JobStatus.FAILED


def detach(job: Job, args: argparse.Namespace) -> int:
    """Start the supervisor in a new session that outlives this process."""
    command = [sys.executable, "-m", "unattended", "--home", args.home, "supervise", str(job.dir)]
    with job.path(SUPERVISOR_LOG).open("a") as log:
        proc = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True
        )
    # Written here too so a `wait` right after `start` sees a live supervisor.
    job.path(PID_FILE).write_text(str(proc.pid))
    print_json(report(job))
    return 0


def foreground(job: Job, args: argparse.Namespace) -> int:
    status = run_supervisor(job, Path(args.home))
    print_json(report(job))
    return EXIT_CODES[status]


LAUNCHERS: dict[Launch, Callable[[Job, argparse.Namespace], int]] = {
    Launch.DETACH: detach,
    Launch.FOREGROUND: foreground,
}


# ----- commands ------------------------------------------------------------------


def cmd_start(args: argparse.Namespace) -> int:
    """Create the job, then supervise it detached or in the foreground."""
    spec = spec_from(args)
    bounds = Bounds(deadline_from(args, time.time()), args.max_resumes, args.max_cost)
    require_auth(spec, Path(args.home))
    job = job_home(args).create(JobState(args.name, spec, bounds))
    job.event("start", {"kind": spec.kind, "cwd": spec.cwd})
    return LAUNCHERS[args.launch](job, args)


def cmd_supervise(args: argparse.Namespace) -> int:
    return EXIT_CODES[run_supervisor(Job(Path(args.dir)), Path(args.home))]


def running(job: Job) -> bool:
    """True while the job has not ended and its supervisor is alive."""
    return job.load().status not in ENDED and job.pid() is not None


def report(job: Job) -> dict[str, Any]:
    """The job's state for ``status``, ``list`` and ``wait``."""
    st, pid = job.load(), job.pid()
    found = {
        "name": st.name, "kind": st.spec.kind, "status": st.status, "reason": st.reason,
        "runs": st.runs, "resumes": st.resumes, "max_resumes": st.bounds.max_resumes,
        "cost": round(st.cost, 4), "max_cost": st.bounds.max_cost,
        "next_wake": iso(st.next_wake), "deadline": iso(st.bounds.deadline),
        "session_id": st.session_id, "supervisor_pid": pid, "dir": str(job.dir),
    }  # fmt: skip
    if st.status not in ENDED and pid is None:
        found["warning"] = f"no supervisor is running; `unattended resume {st.name}` restarts it"
    return found


def cmd_status(args: argparse.Namespace) -> int:
    if args.name is None:
        return cmd_list(args)
    print_json(report(job_home(args).job(args.name)))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    print_json([report(job) for job in job_home(args).jobs()])
    return 0


def cmd_wait(args: argparse.Namespace, sleep: Sleep = time.sleep) -> int:
    """Block until the job ends (or its supervisor is gone); exit with its status code."""
    job = job_home(args).job(args.name)
    while running(job):
        sleep(POLL)
    print_json(report(job))
    return EXIT_CODES.get(job.load().status, 1)


@dataclass
class Tail:
    """Prints what was appended to a job's files since the last call."""

    job: Job
    offsets: dict[str, int] = field(default_factory=dict)

    def print_all(self, filenames: tuple[str, ...]) -> None:
        for filename in filenames:
            self.print_new(filename)

    def print_new(self, filename: str) -> None:
        path = self.job.path(filename)
        if not path.is_file():
            return
        with path.open() as source:
            source.seek(self.offsets.get(filename, 0))
            sys.stdout.write(source.read())
            self.offsets[filename] = source.tell()
        sys.stdout.flush()


def cmd_log(args: argparse.Namespace, sleep: Sleep = time.sleep) -> int:
    """Print the events and output; ``-f`` keeps printing until the job ends."""
    job = job_home(args).job(args.name)
    tail = Tail(job)
    tail.print_all(LIVE_FILES)
    while args.follow is Follow.FOLLOW and running(job):
        sleep(FOLLOW_POLL)
        tail.print_all(LIVE_FILES)
    tail.print_new(OUTPUTS[job.load().spec.kind])
    return 0


def cmd_stop(args: argparse.Namespace, kill: Kill = os.kill) -> int:
    """Ask the job to stop: the stop file for a wait, SIGTERM for a run."""
    job = job_home(args).job(args.name)
    status = job.load().status
    if status in ENDED:
        print(f"job {args.name} already ended: {status}")
        return 0
    job.request_stop()
    print(_signal_or_mark(job, kill))
    return 0


def _signal_or_mark(job: Job, kill: Kill) -> str:
    """SIGTERM a live supervisor; with none, mark the job stopped here."""
    pid = job.pid()
    if pid is not None:
        kill(pid, signal.SIGTERM)
        return f"stop requested; supervisor {pid} signalled"
    job.update(lambda st: st.mark(JobStatus.STOPPED, STOP_REASON))
    job.event("end", {"status": JobStatus.STOPPED, "reason": STOP_REASON})
    return f"job {job.name} stopped (no supervisor was running)"


def cmd_resume(args: argparse.Namespace) -> int:
    """Restart a stopped, limit-reached or orphaned job, optionally with new limits."""
    job = job_home(args).job(args.name)
    state = job.load()
    _require_resumable(job, state)
    bounds = updated_bounds(state.bounds, args)
    _require_open_deadline(bounds)
    require_auth(state.spec, Path(args.home))
    job.update(lambda st: _restart(st, bounds))
    job.clear_stop()
    job.event("resume", {"by": "user"})
    return LAUNCHERS[args.launch](job, args)


def _restart(state: JobState, bounds: Bounds) -> None:
    state.bounds = bounds
    state.mark(JobStatus.RUNNING)


def _require_resumable(job: Job, state: JobState) -> None:
    orphaned = state.status not in ENDED and job.pid() is None
    if state.status not in RESUMABLE and not orphaned:
        raise CliError(
            f"job is {state.status}; only stopped, limit-reached or orphaned jobs resume"
        )


def _require_open_deadline(bounds: Bounds) -> None:
    if bounds.deadline is not None:
        _future(bounds.deadline, time.time())


# ----- parser ----------------------------------------------------------------------

Arg = tuple[tuple[str, ...], dict[str, Any]]


class Need(StrEnum):
    """How many flags of a mutually exclusive group must be given."""

    ONE = "one"
    AT_MOST_ONE = "at-most-one"


@dataclass(frozen=True)
class Exclusive:
    """Flags of which at most one (or exactly one) may be given."""

    need: Need
    args: tuple[Arg, ...]


@dataclass(frozen=True)
class Command:
    """One subcommand: its name, help, handler, arguments and exclusive groups."""

    name: str
    help: str
    func: Callable[[argparse.Namespace], int]
    args: tuple[Arg, ...] = ()
    groups: tuple[Exclusive, ...] = ()


NAME_ARG: Arg = (("name",), {"help": "job name: letters, digits, '.', '_' or '-'"})
GLOBAL_ARGS: tuple[Arg, ...] = (
    (("--home",), {"default": str(Path.home()), "help": argparse.SUPPRESS}),
)
LAUNCH_ARG: Arg = (
    ("--foreground",),
    {"action": "store_const", "dest": "launch", "const": Launch.FOREGROUND,
     "default": Launch.DETACH, "help": "supervise in this process (for run_in_background)"},
)  # fmt: skip
DEADLINE = Exclusive(Need.AT_MOST_ONE, (
    (("--until",), {"help": "deadline: 21:00, 9pm, 'tomorrow 9am' or ISO"}),
    (("--for",), {"dest": "for_", "metavar": "DURATION",
                  "help": "deadline as a duration from now: 24h, 90m"}),
))  # fmt: skip
SOURCE = Exclusive(Need.ONE, (
    (("--prompt",), {"help": "the prompt to run"}),
    (("--prompt-file",), {"help": "read the prompt from this file"}),
    (("--command",), {"help": "a shell command; exit 75 means a usage limit"}),
))  # fmt: skip


def limit_args(max_resumes: int | None) -> tuple[Arg, ...]:
    return (
        (("--max-resumes",), {"type": int, "default": max_resumes,
                              "help": f"most automatic resumes (default {max_resumes})"}),
        (("--max-cost",), {"type": float, "help": "stop resuming once this many USD are spent"}),
    )  # fmt: skip


START_ARGS: tuple[Arg, ...] = (
    NAME_ARG,
    (("--resume-command",), {"help": "command for resumes (default: the command)"}),
    (("--resume-prompt",), {"help": f"prompt for resumes (default: {DEFAULT_RESUME_PROMPT!r})"}),
    (("--cwd",), {"default": ".", "help": "directory the job runs in (default: cwd)"}),
    (("--auth",), {"type": Auth, "choices": list(Auth), "default": Auth.LOGIN}),
    (("--key-file",), {"help": "API key file, mode 600 (default ~/secrets/anthropic-api-key)"}),
    (("--model",), {}),
    (("--permission-mode",), {"choices": get_args(PermissionMode),
                              "help": "default: your settings decide"}),
    (("--fallback-wait",), {"default": "5h", "help": "wait when no reset time is given"}),
    *limit_args(10),
    LAUNCH_ARG,
)  # fmt: skip
RESUME_ARGS: tuple[Arg, ...] = (NAME_ARG, *limit_args(None), LAUNCH_ARG)
COMMANDS = (
    Command("start", "create a job and supervise it", cmd_start, START_ARGS, (SOURCE, DEADLINE)),
    Command("status", "print a job's state as JSON (all jobs without NAME)", cmd_status,
            ((("name",), {"nargs": "?"}),)),
    Command("list", "print every job's state as JSON", cmd_list),
    Command("wait", "block until the job ends; run with run_in_background", cmd_wait, (NAME_ARG,)),
    Command("log", "print the job's events and output", cmd_log, (NAME_ARG,
            (("-f", "--follow"), {"action": "store_const", "const": Follow.FOLLOW,
                                  "default": Follow.ONCE, "help": "keep printing until it ends"}))),
    Command("stop", "stop the job", cmd_stop, (NAME_ARG,)),
    Command("resume", "restart a stopped or limit-reached job", cmd_resume, RESUME_ARGS,
            (DEADLINE,)),
    Command("supervise", "internal: supervise a job directory in this process", cmd_supervise,
            ((("dir",), {}),)),
)  # fmt: skip


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="unattended", description=__doc__)
    _add_args(parser, GLOBAL_ARGS)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for command in COMMANDS:
        _add_command(sub, command)
    return parser


def _add_command(sub: Any, command: Command) -> None:
    parser = sub.add_parser(command.name, help=command.help)
    _add_args(parser, command.args)
    for group in command.groups:
        exclusive = parser.add_mutually_exclusive_group(required=group.need is Need.ONE)
        _add_args(exclusive, group.args)
    parser.set_defaults(func=command.func)


def _add_args(parser: Any, args: tuple[Arg, ...]) -> None:
    for flags, options in args:
        parser.add_argument(*flags, **options)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (CliError, JobError) as exc:
        print(f"unattended {args.cmd}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130

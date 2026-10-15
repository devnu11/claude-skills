"""The one door to other programs, so tests can stand in for all of them."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finished:
    """A finished program: its exit code and what it printed."""

    code: int
    out: str
    err: str


MISSING = Finished(127, "", "not found")
TIMEOUT_SECONDS = 300
TIMED_OUT = Finished(124, "", f"timed out after {TIMEOUT_SECONDS} s")
# A new session makes the child lead a process group that a timeout can kill whole.
STARTUP = {"stderr": subprocess.PIPE, "text": True, "start_new_session": True}


def run(argv: Sequence[str], env: Mapping[str, str] | None = None) -> Finished:
    """Run ``argv`` to the end; a missing program exits 127, one past the time limit 124."""
    try:
        process = subprocess.Popen(list(argv), env=env, stdout=subprocess.PIPE, **STARTUP)
    except FileNotFoundError:
        return MISSING
    return finish(process)


def run_into(argv: Sequence[str], target: Path) -> Finished:
    """Run ``argv`` with its standard output written, as bytes, to ``target``."""
    with target.open("wb") as out:
        try:
            process = subprocess.Popen(list(argv), stdout=out, **STARTUP)
        except FileNotFoundError:
            return MISSING
        return finish(process)


def finish(process: subprocess.Popen[str]) -> Finished:
    """Wait for ``process`` within the time limit; past it, stop it and all it started."""
    try:
        out, err = process.communicate(timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        STOPPERS.get(sys.platform, stop_group)(process)
        process.communicate()
        return TIMED_OUT
    return Finished(process.returncode, out or "", err or "")


def stop_group(process: subprocess.Popen[str]) -> None:
    """Kill the process group ``process`` leads (Chrome's renderers and GPU process too)."""
    os.killpg(process.pid, signal.SIGKILL)


def stop_process(process: subprocess.Popen[str]) -> None:
    """Kill ``process`` alone; Windows has no process groups to kill."""
    process.kill()


def capture(argv: Sequence[str]) -> str | None:
    """What ``argv`` prints, or None when it fails or isn't installed."""
    done = run(argv)
    return done.out if done.code == 0 else None


def get_environment() -> dict[str, str]:
    """A copy of this process's environment."""
    return dict(os.environ)


STOPPERS: dict[str, Callable[[subprocess.Popen[str]], None]] = {"win32": stop_process}

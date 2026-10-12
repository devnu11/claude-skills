"""Shell commands the runner runs, each in its own process group under a time limit.

A hung test is named from the command's output.
"""

from __future__ import annotations

import contextlib
import os
import re
import signal
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CommandRunner = Callable[[str], tuple[int, str]]
TIMED_OUT = 124
DEFAULT_TIMEOUT_S = 300.0
DRAIN_S = 5.0
TIMEOUT_LINE = "timed out after {limit:g}s, so the runner killed its process group: {command}"
HUNG_LINE = "the hanging test: {test}"
NO_HUNG_LINE = (
    "no test is named in its output; a per-test timeout (pytest-timeout) "
    "or pytest's faulthandler_timeout would name it"
)
POPEN_OPTS: dict[str, Any] = {
    "shell": True,
    "stdin": subprocess.DEVNULL,
    "stdout": subprocess.PIPE,
    "stderr": subprocess.STDOUT,
    "text": True,
    "errors": "replace",
    "start_new_session": True,
}


@dataclass(frozen=True)
class HungPattern:
    """A regex for a stack frame of the hung test and how to print its name."""

    regex: re.Pattern[str]
    template: str

    def last(self, output: str) -> str | None:
        """Return the template filled from the last match, or None."""
        found = list(self.regex.finditer(output))
        return self.template.format(**found[-1].groupdict()) if found else None


HUNG_PATTERNS: tuple[HungPattern, ...] = (
    HungPattern(
        re.compile(r'File "(?P<file>[^"]+)", line (?P<line>\d+),? in (?P<func>test\w*)'),
        "{file}::{func} (line {line})",
    ),
)


def hung_test(output: str) -> str | None:
    """Name the hung test from the first pattern that matches, or None."""
    names = (pattern.last(output) for pattern in HUNG_PATTERNS)
    return next((name for name in names if name), None)


def hung_line(output: str) -> str:
    """Return the line that names the hung test, or says none could be named."""
    test = hung_test(output)
    return HUNG_LINE.format(test=test) if test else NO_HUNG_LINE


def kill_group(proc: subprocess.Popen[str]) -> None:
    """SIGKILL the process group the command started (its pid is its pgid)."""
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)


def drain(proc: subprocess.Popen[str]) -> str:
    """Collect what a killed group wrote, with a deadline."""
    try:
        return proc.communicate(timeout=DRAIN_S)[0] or ""
    except subprocess.TimeoutExpired:
        return ""


@dataclass(frozen=True)
class CommandShell:
    """Runs shell commands in ``repo``, each in its own process group, under ``limit_s``."""

    repo: Path
    limit_s: float = DEFAULT_TIMEOUT_S

    def run(self, command: str) -> tuple[int, str]:
        """Run ``command``; on timeout kill its group and return ``TIMED_OUT``."""
        with subprocess.Popen(command, cwd=self.repo, **POPEN_OPTS) as proc:
            try:
                out, _ = proc.communicate(timeout=self.limit_s)
            except subprocess.TimeoutExpired:
                kill_group(proc)
                return TIMED_OUT, self.report_timeout(command, drain(proc))
            except BaseException:
                kill_group(proc)
                raise
            return proc.returncode, out

    def report_timeout(self, command: str, output: str) -> str:
        """Lay out the output, the timeout line, then the hung test line."""
        line = TIMEOUT_LINE.format(limit=self.limit_s, command=command)
        return "\n".join([*output.splitlines(), line, hung_line(output)])


def shell_runner(repo: Path, limit_s: float = DEFAULT_TIMEOUT_S) -> CommandRunner:
    """Run commands in ``repo`` under a time limit; return exit code and combined output."""
    return CommandShell(repo, limit_s).run

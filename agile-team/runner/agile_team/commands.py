"""Shell commands the runner runs, each in its own process group under a time limit.

A hung test is named from the command's output.
"""

from __future__ import annotations

import re
import signal
import threading
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from . import runner_venv, stages, system, tally_watch
from .process_groups import signal_child_group

CommandRunner = Callable[[str], tuple[int, str]]
TIMED_OUT = 124
DEFAULT_TIMEOUT_S = 300.0
DRAIN_S = 5.0
# The gate's own coverage data goes under the never-audited run dir, so the next step's
# audit does not quarantine it as an out-of-scope change (#60).
COVERAGE_DATA = ("COVERAGE_FILE", ".team/run/.coverage")
TIMEOUT_LINE = "timed out after {limit:g}s, so the runner killed its process group: {command}"
HUNG_LINE = "the hanging test: {test}"
NO_HUNG_LINE = (
    "no test is named in its output; a per-test timeout (pytest-timeout) "
    "or pytest's faulthandler_timeout would name it"
)


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


def kill_group(proc: system.Process) -> None:
    """SIGKILL the command's own process group, only if it is one (s41)."""
    signal_child_group(proc.pid, signal.SIGKILL)


@dataclass(eq=False)
class Pump:
    """Reads a command's output line by line on a thread (s118 R8)."""

    lines: Iterable[str]
    seen: list[str] = field(default_factory=list)
    thread: threading.Thread = field(init=False)

    def start(self) -> None:
        """Begin reading on a daemon thread."""
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def join(self, limit_s: float) -> bool:
        """Wait up to ``limit_s``; True when the output ended in time."""
        self.thread.join(limit_s)
        return not self.thread.is_alive()

    def text(self) -> str:
        """Everything read so far."""
        return "".join(self.seen)

    def _read(self) -> None:
        # A pipe closed under the thread must never break a gate.
        with suppress(ValueError, OSError):
            for line in self.lines:
                self.seen.append(line)


@dataclass(frozen=True)
class CommandShell:
    """Runs shell commands in ``repo``, each in its own process group, under ``limit_s``."""

    repo: Path
    limit_s: float = DEFAULT_TIMEOUT_S

    def run(self, command: str) -> tuple[int, str]:
        """Run ``command``; on timeout kill its group and return ``TIMED_OUT``."""
        code, out = self._watched(command)
        stages.note(command, code)
        return code, out

    def _watched(self, command: str) -> tuple[int, str]:
        """Run with the tally plugin when a stage is open."""
        run = stages.current()  # on the caller's thread: contextvars skip threads
        plain = self._build_shell(command, runner_venv.get_command_environ())
        if run is None:
            return self._run(plain)
        with tally_watch.watching(run) as env:
            code, out = self._run(self._build_shell(command, env))
        if code != 0 and tally_watch.plugin_failed(out):
            return self._run(plain)
        return code, out

    def _build_shell(self, command: str, env: Mapping[str, str]) -> system.ShellCommand:
        """``command`` in the repo, under ``env`` with the coverage data redirected."""
        name, path = COVERAGE_DATA
        return system.ShellCommand(command, self.repo, {**env, name: str(self.repo / path)})

    def _run(self, shell: system.ShellCommand) -> tuple[int, str]:
        with system.spawn_piped(shell) as proc:
            pump = Pump(proc.stdout)
            pump.start()
            try:
                ended = self._finish(proc, pump)
            except BaseException:
                kill_group(proc)
                raise
            if ended:
                return proc.returncode, pump.text()
            kill_group(proc)
            pump.join(DRAIN_S)
            return TIMED_OUT, self.report_timeout(shell.text, pump.text())

    def _finish(self, proc: system.Process, pump: Pump) -> bool:
        """Wait for the exit and the end of output within one ``limit_s``."""
        deadline = system.monotonic() + self.limit_s
        try:
            proc.wait(timeout=self.limit_s)
        except system.TimeoutExpired:
            return False
        return pump.join(max(0.0, deadline - system.monotonic()))

    def report_timeout(self, command: str, output: str) -> str:
        """Lay out the output, the timeout line, then the hung test line."""
        line = TIMEOUT_LINE.format(limit=self.limit_s, command=command)
        return "\n".join([*output.splitlines(), line, hung_line(output)])


def shell_runner(repo: Path, limit_s: float = DEFAULT_TIMEOUT_S) -> CommandRunner:
    """Run commands in ``repo`` under a time limit; return exit code and combined output."""
    return CommandShell(repo, limit_s).run

"""Which kill commands a role's Bash may run (s41).

Never the runner's group, never by name, never targets picked at run time.
"""

from __future__ import annotations

import os
import re

from .process_groups import in_runner_group

BY_NAME = frozenset({"pkill", "killall"})
KILL = "kill"
FEEDERS = frozenset({"xargs"})
RUN_TIME_MARKS = ("$(", "`")
VALUE_OPTIONS = frozenset({"-s", "-n"})
END_OF_OPTIONS = "--"
NUMBER = re.compile(r"-?\d+")
ALWAYS_PROTECTED = frozenset({0, -1})
KILL_FIX = "kill only a process you started, by the pid you saved: `cmd & PID=$!` … `kill $PID`"
BY_NAME_DENIED = (
    "`{word}` picks processes by name, and the agent running you has your whole prompt "
    "on its command line, so it can match itself; " + KILL_FIX
)
RUNNER_DENIED = (
    "`kill {target}` would signal the runner or the agent running you "
    "(the runner's process group); " + KILL_FIX
)
AT_RUN_TIME_DENIED = (
    "`kill` with targets chosen at run time (`$(…)`, backticks or `xargs`) "
    "cannot be checked; " + KILL_FIX
)


def _names(words: list[str]) -> list[str]:
    return [os.path.basename(word) for word in words]


def _fed(names_before_kill: list[str]) -> bool:
    return any(name in FEEDERS for name in names_before_kill)


def _option_width(args: list[str]) -> int:
    """Words taken by a leading signal option: 0, 1, or 2 for ``-s X`` / ``-n X``."""
    if not args or not args[0].startswith("-") or args[0] == END_OF_OPTIONS:
        return 0
    return 2 if args[0] in VALUE_OPTIONS else 1


def kill_targets(args: list[str]) -> list[str]:
    """The targets of a ``kill``: arguments after one signal option and one ``--``."""
    rest = args[_option_width(args) :]
    return rest[1:] if rest[:1] == [END_OF_OPTIONS] else rest


def _protected(number: int) -> bool:
    if number in ALWAYS_PROTECTED:
        return True
    return in_runner_group(number) if number > 0 else -number == os.getpgrp()


def target_denial(target: str) -> str | None:
    """Why one kill target is denied, or ``None``."""
    if any(mark in target for mark in RUN_TIME_MARKS):
        return AT_RUN_TIME_DENIED
    if NUMBER.fullmatch(target) and _protected(int(target)):
        return RUNNER_DENIED.format(target=target)
    return None


def kill_denial(words: list[str]) -> str | None:
    """Why one segment's kill command is denied (K1, K2, K4), or ``None``."""
    names = _names(words)
    by_name = next((n for n in names if n in BY_NAME), None)
    if by_name:
        return BY_NAME_DENIED.format(word=by_name)
    if KILL not in names:
        return None
    at = names.index(KILL)
    if _fed(names[:at]):
        return AT_RUN_TIME_DENIED
    return next((r for r in map(target_denial, kill_targets(words[at + 1 :])) if r), None)

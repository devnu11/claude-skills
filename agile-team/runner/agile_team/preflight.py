"""Checks that must pass before a run starts.

Each check returns a list of failure strings so the CLI can report all of them
at once instead of stopping at the first.
"""

from __future__ import annotations

import shlex
import shutil
from collections.abc import Callable
from pathlib import Path

from . import keys
from .config import Config
from .git_ops import Git

Which = Callable[[str], str | None]


def check_clean_tree(git: Git) -> list[str]:
    changed = git.changed_paths()
    if not changed:
        return []
    shown = ", ".join(changed[:5]) + (" …" if len(changed) > 5 else "")
    return [f"working tree is dirty ({shown}); commit or stash first"]


def check_key(config: Config, git: Git, home: Path) -> list[str]:
    """The key file exists, is mode 600, and is gitignored when inside the repo."""
    try:
        source = keys.resolve(config.repo, config.team.key_file, home)
    except keys.KeyNotFound as exc:
        return [str(exc)]
    failures = []
    if source.in_repo and not git.is_ignored(config.team.key_file):
        failures.append(f"{config.team.key_file} is not gitignored")
    if not keys.mode_ok(source.path):
        failures.append(f"{source.path} must be mode 600")
    return failures


def executable_of(command: str) -> str:
    """First word of a shell command, ignoring leading ``VAR=value`` pairs."""
    words = [w for w in shlex.split(command) if "=" not in w.split("/")[0]]
    return words[0] if words else ""


def check_toolchain(config: Config, which: Which = shutil.which) -> list[str]:
    """Every configured toolchain command's executable is on PATH."""
    failures = []
    for name, command in sorted(config.toolchain.commands.items()):
        exe = executable_of(command)
        if exe and which(exe) is None:
            failures.append(f"toolchain.{name}: `{exe}` not found on PATH")
    return failures


def run_all(config: Config, git: Git, home: Path, which: Which = shutil.which) -> list[str]:
    """All preflight failures; empty means the run may start."""
    return check_clean_tree(git) + check_key(config, git, home) + check_toolchain(config, which)

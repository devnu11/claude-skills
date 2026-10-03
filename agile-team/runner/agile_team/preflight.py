"""Checks that must pass before a run starts.

Each check returns a list of failure strings so the CLI can report all of them
at once instead of stopping at the first.
"""

from __future__ import annotations

import shlex
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import keys
from .config import Config
from .git_ops import Git

Which = Callable[[str], str | None]


def executable_of(command: str) -> str:
    """First word of a shell command, ignoring leading ``VAR=value`` pairs."""
    words = [w for w in shlex.split(command) if "=" not in w.split("/")[0]]
    return words[0] if words else ""


@dataclass
class Preflight:
    """The pre-run checks for one repo; ``which`` is injectable for tests."""

    config: Config
    git: Git
    home: Path
    which: Which = field(default=shutil.which)

    def run_all(self) -> list[str]:
        """All preflight failures; empty means the run may start."""
        return self.clean_tree() + self.key() + self.toolchain()

    def clean_tree(self) -> list[str]:
        changed = self.git.changed_paths()
        if not changed:
            return []
        shown = ", ".join(changed[:5]) + (" …" if len(changed) > 5 else "")
        return [f"working tree is dirty ({shown}); commit or stash first"]

    def key(self) -> list[str]:
        """The key file exists, is mode 600, and is gitignored when inside the repo."""
        try:
            source = self.locations().resolve()
        except keys.KeyNotFound as exc:
            return [str(exc)]
        unignored = source.origin is keys.KeyOrigin.REPO and not self.git.is_ignored(
            self.config.team.key_file
        )
        failures = [f"{self.config.team.key_file} is not gitignored"] if unignored else []
        return failures + ([] if keys.mode_ok(source.path) else [f"{source.path} must be mode 600"])

    def locations(self) -> keys.KeyLocations:
        return keys.KeyLocations(self.config.repo, self.config.team.key_file, self.home)

    def toolchain(self) -> list[str]:
        """Every configured toolchain command's executable is on PATH."""
        exes = {name: executable_of(cmd) for name, cmd in self.config.toolchain.commands.items()}
        return [
            f"toolchain.{name}: `{exe}` not found on PATH"
            for name, exe in sorted(exes.items())
            if exe and self.which(exe) is None
        ]

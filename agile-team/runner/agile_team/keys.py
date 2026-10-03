"""Resolve the Anthropic API key that bills a run.

Order: the repo key file named in config (default ``.team/run/api-key``), then
``~/secrets/anthropic-api-key``. The key is only ever placed in the runner's
child environment, so the interactive session's OAuth login is untouched.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

ENV_VAR = "ANTHROPIC_API_KEY"
# Blanked in the child so an inherited subscription token cannot win over the key.
COMPETING_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN")
HOME_KEY = Path("secrets/anthropic-api-key")
REQUIRED_MODE = 0o600


class KeyNotFound(Exception):
    """No usable key file was found."""


class KeyOrigin(StrEnum):
    """Where a key file lives; only a repo key must be gitignored."""

    REPO = "repo"
    HOME = "home"


@dataclass(frozen=True)
class KeySource:
    """One candidate key file."""

    path: Path
    origin: KeyOrigin


@dataclass(frozen=True)
class KeyLocations:
    """The repo's configured key file and the home fallback."""

    repo: Path
    key_file: str
    home: Path

    def candidates(self) -> list[KeySource]:
        """Key files in resolution order."""
        return [
            KeySource(self.repo / self.key_file, KeyOrigin.REPO),
            KeySource(self.home / HOME_KEY, KeyOrigin.HOME),
        ]

    def resolve(self) -> KeySource:
        """First existing key file, or ``KeyNotFound``."""
        found = next((c for c in self.candidates() if c.path.is_file()), None)
        if found is None:
            tried = ", ".join(str(c.path) for c in self.candidates())
            raise KeyNotFound(f"no API key file found (tried {tried})")
        return found

    def secret_paths(self) -> list[Path]:
        """Paths no role may read: both key file candidates and ``~/secrets``."""
        return [c.path for c in self.candidates()] + [self.home / HOME_KEY.parent]


def mode_ok(path: Path) -> bool:
    """True when the file is readable by its owner only (mode 600)."""
    return stat.S_IMODE(path.stat().st_mode) == REQUIRED_MODE


def read_key(path: Path) -> str:
    """The key with surrounding whitespace removed."""
    return path.read_text().strip()


def child_env(key: str) -> dict[str, str]:
    """Environment additions for SDK child processes."""
    return {ENV_VAR: key, **dict.fromkeys(COMPETING_VARS, "")}


def deny_rules(paths: list[Path]) -> list[str]:
    """Claude Code permission rules denying Read of each path (and anything under it)."""
    absolute = [p.resolve() for p in paths]
    return [rule for p in absolute for rule in (f"Read(/{p})", f"Read(/{p}/**)")]

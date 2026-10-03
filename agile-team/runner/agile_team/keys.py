"""Resolve the Anthropic API key that bills a run.

Order: the repo key file named in config (default ``.team/run/api-key``), then
``~/secrets/anthropic-api-key``. The key is only ever placed in the runner's
child environment, so the interactive session's OAuth login is untouched.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass
from pathlib import Path

ENV_VAR = "ANTHROPIC_API_KEY"
# Blanked in the child so an inherited subscription token cannot win over the key.
COMPETING_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN")
HOME_KEY = Path("secrets/anthropic-api-key")
REQUIRED_MODE = 0o600


class KeyNotFound(Exception):
    """No usable key file was found."""


@dataclass(frozen=True)
class KeySource:
    """Where the key came from; ``in_repo`` decides whether gitignore matters."""

    path: Path
    in_repo: bool


def candidates(repo: Path, key_file: str, home: Path) -> list[KeySource]:
    """Key files in resolution order."""
    return [KeySource(repo / key_file, True), KeySource(home / HOME_KEY, False)]


def resolve(repo: Path, key_file: str, home: Path) -> KeySource:
    """First existing key file, or ``KeyNotFound``."""
    for source in candidates(repo, key_file, home):
        if source.path.is_file():
            return source
    tried = ", ".join(str(c.path) for c in candidates(repo, key_file, home))
    raise KeyNotFound(f"no API key file found (tried {tried})")


def mode_ok(path: Path) -> bool:
    """True when the file is readable by its owner only (mode 600)."""
    return stat.S_IMODE(path.stat().st_mode) == REQUIRED_MODE


def read_key(path: Path) -> str:
    """The key with surrounding whitespace removed."""
    return path.read_text().strip()


def child_env(key: str) -> dict[str, str]:
    """Environment additions for SDK child processes."""
    return {ENV_VAR: key, **dict.fromkeys(COMPETING_VARS, "")}

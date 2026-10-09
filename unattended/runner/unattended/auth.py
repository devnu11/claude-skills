"""Login or API-key auth for a job's child processes.

``login`` passes nothing, so Claude Code uses the user's login; an inherited
``ANTHROPIC_API_KEY`` would win over it and bill a Console workspace, so it is
refused. ``api-key`` reads a mode-600 key file and puts the key only in the
child environment; the key is never stored or printed. Copied from agile-team's
``keys.py`` and ``preflight.py``.
"""

from __future__ import annotations

import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

ENV_VAR = "ANTHROPIC_API_KEY"
# Blanked in the child so an inherited subscription token cannot win over the key.
COMPETING_VARS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN")
HOME_KEY = Path("secrets/anthropic-api-key")
REQUIRED_MODE = 0o600


class Auth(StrEnum):
    """What bills a job: the Claude Code login or an API key."""

    LOGIN = "login"
    API_KEY = "api-key"


@dataclass(frozen=True)
class AuthSetup:
    """A job's auth choice, its key file (if any) and the home holding ``~/secrets``."""

    auth: Auth
    key_file: Path | None
    home: Path

    @property
    def key_path(self) -> Path:
        """``--key-file``, else ``~/secrets/anthropic-api-key``."""
        return self.key_file or self.home / HOME_KEY

    def problems(self, environ: Mapping[str, str]) -> list[str]:
        """Why the job may not start; empty when it may."""
        return PROBLEMS[self.auth](self, environ)

    def env(self) -> dict[str, str]:
        """Environment additions for the job's child processes."""
        return ENVS[self.auth](self)


def _login_problems(setup: AuthSetup, environ: Mapping[str, str]) -> list[str]:
    if environ.get(ENV_VAR):
        return [f"auth is login but ${ENV_VAR} is set; unset it or use --auth api-key"]
    return []


def _key_problems(setup: AuthSetup, environ: Mapping[str, str]) -> list[str]:
    path = setup.key_path
    if not path.is_file():
        return [f"no API key file at {path}"]
    return [] if mode_ok(path) else [f"{path} must be mode 600"]


def mode_ok(path: Path) -> bool:
    """True when the file is readable by its owner only (mode 600)."""
    return stat.S_IMODE(path.stat().st_mode) == REQUIRED_MODE


def _key_env(setup: AuthSetup) -> dict[str, str]:
    key = setup.key_path.read_text().strip()
    return {ENV_VAR: key, **dict.fromkeys(COMPETING_VARS, "")}


PROBLEMS: dict[Auth, Callable[[AuthSetup, Mapping[str, str]], list[str]]] = {
    Auth.LOGIN: _login_problems,
    Auth.API_KEY: _key_problems,
}
ENVS: dict[Auth, Callable[[AuthSetup], dict[str, str]]] = {
    Auth.LOGIN: lambda setup: {},
    Auth.API_KEY: _key_env,
}

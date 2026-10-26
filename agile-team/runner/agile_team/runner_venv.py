"""Hiding the runner's own venv from the roles and commands it starts (#55, s174)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from . import system

VENV_VAR = "VIRTUAL_ENV"


def strip_venv_bin(path: str, venv: str) -> str:
    """``path`` without the directories directly inside ``venv`` (its bin or Scripts)."""
    kept = [d for d in path.split(os.pathsep) if Path(d).parent != Path(venv)]
    return os.pathsep.join(kept)


def hide_runner_venv(env: Mapping[str, str], inherited: Mapping[str, str]) -> dict[str, str]:
    """``env`` with the runner's own venv blanked and dropped from PATH.

    The SDK only adds to the inherited environment, so the venv is overridden, not removed.
    """
    venv = inherited.get(VENV_VAR)
    if not venv:
        return dict(env)
    path = env.get("PATH", inherited.get("PATH", ""))
    return {**env, VENV_VAR: "", "PATH": strip_venv_bin(path, venv)}


def get_command_environ() -> dict[str, str]:
    """The process environment for a command: no venv variable, no venv directory in PATH."""
    inherited = system.environ()
    env = {k: v for k, v in inherited.items() if k != VENV_VAR}
    venv = inherited.get(VENV_VAR)
    if venv:
        env["PATH"] = strip_venv_bin(env.get("PATH", ""), venv)
    return env

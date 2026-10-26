"""s174 end to end: a real shell command sees no runner venv, and the rest of the env intact."""

from __future__ import annotations

from pathlib import Path

import pytest
from agile_team.commands import CommandShell


def run_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Run ``env`` through CommandShell with a runner venv set; return what the child saw."""
    venv = tmp_path / "runner-venv"
    monkeypatch.setenv("VIRTUAL_ENV", str(venv))
    monkeypatch.setenv("PATH", f"{venv / 'bin'}:/usr/bin:/bin")
    monkeypatch.setenv("S174_KEEP", "kept")
    _, output = CommandShell(tmp_path, 20.0).run("env")
    lines = (line.partition("=") for line in output.splitlines())
    return {k: v for k, _, v in lines}


def test_command_sees_no_runner_venv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = run_env(tmp_path, monkeypatch)
    assert "VIRTUAL_ENV" not in seen
    assert "runner-venv" not in seen["PATH"]


def test_command_keeps_the_rest_of_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = run_env(tmp_path, monkeypatch)
    assert seen["PATH"] == "/usr/bin:/bin"
    assert seen["S174_KEEP"] == "kept"
    assert seen["HOME"]

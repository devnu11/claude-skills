"""Shared helpers: checking text with settings rooted in a scratch directory."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from house_rules.checker import check_source
from house_rules.config import Settings
from house_rules.model import Finding
from house_rules.source import Source

SAMPLES = Path(__file__).parent / "samples"

type CheckText = Callable[..., list[Finding]]


@pytest.fixture
def check_text(tmp_path: Path) -> CheckText:
    """Check ``text`` as ``sample.py`` with settings built from keyword overrides."""

    def check(text: str, **overrides: object) -> list[Finding]:
        return check_source(Source("sample.py", text), Settings(tmp_path, **overrides))

    return check


@pytest.fixture
def git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty git repo in a scratch directory, made the working directory."""
    repo = tmp_path / "repo"
    repo.mkdir()
    for command in (
        ["init", "-q"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "Test"],
        ["config", "commit.gpgsign", "false"],
    ):
        subprocess.run(["git", "-C", str(repo), *command], check=True)
    monkeypatch.chdir(repo)
    return repo


def git(repo: Path, *arguments: str) -> None:
    """Run git in ``repo``."""
    subprocess.run(["git", "-C", str(repo), *arguments], check=True, capture_output=True)

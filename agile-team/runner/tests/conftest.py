"""Shared fixtures: throwaway git repos and a configured runtime with a fake query()."""

from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
import tomli_w
from agile_team import config as config_mod
from agile_team import gates
from agile_team.dispatch import Runtime
from agile_team.git_ops import Git
from agile_team.ledger import Ledger
from agile_team.relay import Relay
from agile_team.roles import RoleBook
from agile_team.state import RunState
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

PY_CONFIG: dict[str, Any] = {
    "team": {"docs_dir": "docs", "budget_usd": 10.0, "manager_every_pct": 50},
    "toolchain": {
        "preset": "python",
        "test": "pytest",
        "coverage": "pytest --cov",
        "lint": "ruff check .",
        "globs": {
            "source": ["src/**"],
            "tests": ["tests/**", "!tests/e2e/**"],
            "e2e": ["tests/e2e/**"],
            "ci": [".github/**"],
        },
    },
    "delivery": [{"name": "cli", "kind": "package", "prepare": "", "bin": ["bin"]}],
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with one commit and ``.team/run/`` ignored."""
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "Test")
    git(path, "config", "commit.gpgsign", "false")
    (path / ".gitignore").write_text(".team/run/\n")
    (path / "src").mkdir()
    (path / "src" / "app.py").write_text("x = 1\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "init")
    return path


@pytest.fixture
def configured(repo: Path) -> Path:
    """``repo`` with a committed Python ``.agile-team.toml``."""
    (repo / config_mod.CONFIG_NAME).write_text(tomli_w.dumps(PY_CONFIG))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "config")
    return repo


def result_message(text: str, cost: float = 0.1, session: str = "sess") -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=session,
        total_cost_usd=cost,
        result=text,
    )


def handoff(status: str = "done", **extra: Any) -> str:
    import json

    return "work\n```handoff\n" + json.dumps({"status": status, **extra}) + "\n```"


class FakeQuery:
    """Stands in for ``claude_agent_sdk.query``; runs ``action`` then yields messages."""

    def __init__(self, text: str = "", cost: float = 0.1, action: Callable[[], None] | None = None):
        self.text = text or handoff()
        self.cost = cost
        self.action = action
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *, prompt: str, options: Any) -> AsyncIterator[Any]:
        self.calls.append({"prompt": prompt, "options": options})
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        if self.action:
            self.action()
        yield AssistantMessage(content=[TextBlock(text="thinking")], model="m")
        yield result_message(self.text, self.cost)


class FakeRunner:
    """Command runner returning canned (code, output) per command."""

    def __init__(self, results: dict[str, tuple[int, str]] | None = None):
        self.results = results or {}
        self.calls: list[str] = []

    def __call__(self, command: str) -> tuple[int, str]:
        self.calls.append(command)
        return self.results.get(command, (0, ""))


@pytest.fixture
def make_runtime(configured: Path) -> Callable[..., Runtime]:
    """Build a Runtime on ``configured`` with injectable query and command runner."""

    def build(query: Any = None, runner: FakeRunner | None = None, **kw: Any) -> Runtime:
        config = config_mod.load(configured)
        checks = gates.Checks(
            config.toolchain.commands, config.gates.coverage, runner or FakeRunner()
        )
        return Runtime(
            config=config,
            book=RoleBook.for_repo(configured, config.roles),
            git=Git(configured),
            ledger=Ledger(config.run_dir / "ledger.jsonl"),
            relay=Relay(config.run_dir),
            state=RunState(),
            env={"ANTHROPIC_API_KEY": "k"},
            query_fn=query or FakeQuery(),
            checks=checks,
            **kw,
        )

    return build


@pytest.fixture
def key_home(tmp_path: Path) -> Path:
    """A home dir holding a mode-600 fallback key."""
    home = tmp_path / "home"
    (home / "secrets").mkdir(parents=True)
    key = home / "secrets" / "anthropic-api-key"
    key.write_text("sk-test\n")
    os.chmod(key, 0o600)
    return home

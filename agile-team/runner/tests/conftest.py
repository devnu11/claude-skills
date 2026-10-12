"""Shared fixtures: an in-memory ``system`` for unit tests, real git repos for e2e.

Unit tests run in the FAKE world (s71): an autouse fixture swaps ``agile_team.system``
for ``FakeSystem`` and ``os_guard`` fails any test that reaches the real OS. Tests in
``tests/e2e/`` (and the ``os_guard.LEGACY`` files, until P3) run in the REAL world.
Unit tests have a 1 s limit, the real world ``e2e_timeout`` (s72).
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
import tomli_w
from agile_team import config as config_mod
from agile_team import gates, system
from agile_team.dispatch import Runtime
from agile_team.git_ops import Git
from agile_team.ledger import Ledger
from agile_team.relay import Relay
from agile_team.roles import RoleBook
from agile_team.state import RunState
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from . import os_guard, time_limit
from .fake_system import FAKE_HOME, FAKE_REPO, FakeSystem

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

# The audit hook is installed once per process; it acts only inside a unit test's phases.
sys.addaudithook(os_guard.hook)


def git(repo: Path, *args: str) -> str:
    """Run real git (REAL world only)."""
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the e2e time limit's ini key (s72 L2)."""
    parser.addini(time_limit.E2E_LIMIT_INI, "per-test time limit (s) for tests/e2e/ and LEGACY")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Mark each test with its world's time limit (s72 L4)."""
    time_limit.mark(items)


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtest_setup(item: pytest.Item) -> Any:
    """Run fixture setup with the guard on for unit tests."""
    with os_guard.watching(os_guard.world_of(item)):
        return (yield)


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtest_call(item: pytest.Item) -> Any:
    """Run the test body with the guard on for unit tests."""
    with os_guard.watching(os_guard.world_of(item)):
        return (yield)


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_runtest_teardown(item: pytest.Item) -> Any:
    """Run fixture teardown with the guard on for unit tests."""
    with os_guard.watching(os_guard.world_of(item)):
        return (yield)


@pytest.fixture
def world(request: pytest.FixtureRequest) -> os_guard.World:
    """Which world this test runs in: the fake (unit) or the real OS (e2e, LEGACY)."""
    return os_guard.world_of(request.node)


@pytest.fixture(autouse=True)
def fake(world: os_guard.World, monkeypatch: pytest.MonkeyPatch) -> FakeSystem | None:
    """A fresh in-memory ``system`` for every unit test; ``None`` in the real world."""

    def install() -> FakeSystem:
        fresh = FakeSystem()
        fresh.install(monkeypatch)
        return fresh

    makers: dict[os_guard.World, Callable[[], FakeSystem | None]] = {
        os_guard.World.FAKE: install,
        os_guard.World.REAL: lambda: None,
    }
    return makers[world]()


def _real_home(request: pytest.FixtureRequest) -> Path:
    tmp_path: Path = request.getfixturevalue("tmp_path")
    return tmp_path / "agile-team-home"


@pytest.fixture(autouse=True)
def isolated_global_roles(
    world: os_guard.World, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point the global role layer at a scratch dir so no test reads the real home."""
    homes: dict[os_guard.World, Callable[[], Path]] = {
        os_guard.World.FAKE: lambda: FAKE_HOME / "agile-team",
        os_guard.World.REAL: lambda: _real_home(request),
    }
    home = homes[world]()
    monkeypatch.setenv("AGILE_TEAM_HOME", str(home))
    return home / "roles"


def _seed_fake_repo() -> Path:
    system.make_dirs(FAKE_REPO / "src")
    system.make_dirs(FAKE_REPO / ".git")
    system.write_text(FAKE_REPO / ".gitignore", ".team/run/\n")
    system.write_text(FAKE_REPO / "src" / "app.py", "x = 1\n")
    return FAKE_REPO


def _real_repo(request: pytest.FixtureRequest) -> Path:
    tmp_path: Path = request.getfixturevalue("tmp_path")
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
def repo(world: os_guard.World, request: pytest.FixtureRequest) -> Path:
    """A repo with one commit and ``.team/run/`` ignored (in memory for unit tests)."""
    seeds: dict[os_guard.World, Callable[[], Path]] = {
        os_guard.World.FAKE: _seed_fake_repo,
        os_guard.World.REAL: lambda: _real_repo(request),
    }
    return seeds[world]()


def _commit_config(repo: Path) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "config")


@pytest.fixture
def configured(repo: Path, world: os_guard.World) -> Path:
    """``repo`` with a Python ``.agile-team.toml`` (committed in the real world)."""
    system.write_text(repo / config_mod.CONFIG_NAME, tomli_w.dumps(PY_CONFIG))
    commits: dict[os_guard.World, Callable[[Path], None]] = {
        os_guard.World.FAKE: lambda path: None,
        os_guard.World.REAL: _commit_config,
    }
    commits[world](repo)
    return repo


USAGE = {
    "input_tokens": 100,
    "output_tokens": 20,
    "cache_read_input_tokens": 300,
    "cache_creation_input_tokens": 40,
}


def result_message(text: str, cost: float = 0.1, session: str = "sess") -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=session,
        total_cost_usd=cost,
        usage=USAGE,
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
        from functools import partial

        from agile_team import presentation

        checks = gates.Checks(
            config.toolchain.commands,
            config.gates.coverage,
            runner or FakeRunner(),
            presentation=partial(presentation.missing, config),
            read=partial(gates.read_repo_file, configured),
        )
        pipeline = gates.Pipeline(list(config.gates.steps), config.gates.round_cap, checks)
        return Runtime(
            config=config,
            book=RoleBook.for_repo(configured, config.roles),
            git=Git(configured),
            ledger=Ledger(config.run_dir / "ledger.jsonl"),
            relay=Relay(config.run_dir),
            state=RunState(),
            env={"ANTHROPIC_API_KEY": "k"},
            query_fn=query or FakeQuery(),
            pipeline=pipeline,
            **kw,
        )

    return build


GUIDE_TEXT = "Run `todo add milk`, then `todo list`: milk is listed.\n"


def present(config: config_mod.Config, story_id: str = "s1", workspace: bool = True) -> Path:
    """Write a complete presentation for ``story_id`` through ``system`` (E1, E5, O15)."""
    source = config.run_dir / "presentation" / story_id
    system.make_dirs(source)
    system.write_text(source / "PRESENTATION.md", GUIDE_TEXT)
    if workspace:
        system.make_dirs(source / "workspace")
        system.write_text(source / "workspace" / "todo.txt", "milk\n")
    return source


def _fake_key_home(fake: FakeSystem) -> Path:
    fake.put(FAKE_HOME / "secrets" / "anthropic-api-key", "sk-test\n", mode=0o600)
    return FAKE_HOME


def _real_key_home(request: pytest.FixtureRequest) -> Path:
    tmp_path: Path = request.getfixturevalue("tmp_path")
    home = tmp_path / "home"
    (home / "secrets").mkdir(parents=True)
    key = home / "secrets" / "anthropic-api-key"
    key.write_text("sk-test\n")
    os.chmod(key, 0o600)
    return home


@pytest.fixture
def key_home(
    world: os_guard.World, fake: FakeSystem | None, request: pytest.FixtureRequest
) -> Path:
    """A home dir holding a mode-600 fallback key."""
    makers: dict[os_guard.World, Callable[[], Path]] = {
        os_guard.World.FAKE: lambda: _fake_key_home(fake),  # type: ignore[arg-type]
        os_guard.World.REAL: lambda: _real_key_home(request),
    }
    return makers[world]()

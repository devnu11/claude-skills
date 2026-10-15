"""Shared fixtures: a stand-in for every program the runner calls, and Chrome detection."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from render_markdown import chrome, printer, system
from render_markdown.system import Finished

FIXTURES = Path(__file__).parent / "fixtures"
OK = Finished(0, "", "")


@dataclass
class FakeSystem:
    """Scripted answers per program name; a list answers in turn and repeats its last."""

    answers: dict[str, Finished | list[Finished]] = field(default_factory=dict)
    environment: dict[str, str] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)
    environments: list[Mapping[str, str] | None] = field(default_factory=list)
    written: bytes = b"raster"

    def answer(self, program: str, out: str = "", code: int = 0) -> None:
        """Script one answer for ``program``."""
        self.answers[program] = Finished(code, out, "" if code == 0 else "it broke")

    def run(self, argv: Sequence[str], env: Mapping[str, str] | None = None) -> Finished:
        """Record the call and give the scripted answer."""
        self.calls.append(list(argv))
        self.environments.append(env)
        answer = self.answers.get(Path(argv[0]).name, OK)
        if isinstance(answer, list):
            return answer.pop(0) if len(answer) > 1 else answer[0]
        return answer

    def run_into(self, argv: Sequence[str], target: Path) -> Finished:
        """Record the call and write ``written`` to ``target``."""
        done = self.run(argv)
        target.write_bytes(self.written if done.code == 0 else b"")
        return done

    def get_environment(self) -> dict[str, str]:
        """The scripted environment."""
        return dict(self.environment)

    def find_calls(self, program: str) -> list[list[str]]:
        """Every call to ``program``."""
        return [call for call in self.calls if Path(call[0]).name == program]


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never reach a real CUPS web server; one that needs it scripts ``open_url``."""

    def refuse(url: str) -> None:
        raise OSError(f"no network in tests: {url}")

    monkeypatch.setattr(printer, "open_url", refuse)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeSystem:
    """Every external program replaced by scripted answers."""
    stand_in = FakeSystem()
    monkeypatch.setattr(system, "run", stand_in.run)
    monkeypatch.setattr(system, "run_into", stand_in.run_into)
    monkeypatch.setattr(system, "get_environment", stand_in.get_environment)
    return stand_in


@pytest.fixture
def real_chrome() -> Path:
    """A real Chrome, or a skip (a failure when ``RENDER_MARKDOWN_SMOKE=1``)."""
    try:
        return chrome.find_chrome()
    except chrome.ChromeError as error:
        if os.environ.get("RENDER_MARKDOWN_SMOKE") == "1":
            pytest.fail(f"RENDER_MARKDOWN_SMOKE=1 but {error}")
        pytest.skip(str(error))


@pytest.fixture
def output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The system temp dir, moved into the test's own scratch dir."""
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    return tmp_path / "render-markdown"

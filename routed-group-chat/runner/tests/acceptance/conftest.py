"""Acceptance fixtures: the shipped example roster and a CLI harness over it."""

from __future__ import annotations

from pathlib import Path

import pytest

from ..conftest import Cli, FakeBackend

SKILL_DIR = Path(__file__).parents[3]
EXAMPLE_ROSTER = SKILL_DIR / "examples" / "leadership.toml"
RUNNER_DIR = SKILL_DIR / "runner"


@pytest.fixture
def leadership(tmp_path: Path, backend: FakeBackend) -> Cli:
    """The examples/leadership.toml roster with a chat dir under tmp_path."""
    return Cli(EXAMPLE_ROSTER, tmp_path / ".group-chat" / "leadership", backend)

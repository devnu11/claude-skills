"""Acceptance: the real console entry point, run as a subprocess (no model needed).

Covers error paths of ``python -m group_chat`` that exit before any model call.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ..conftest import ROSTER_TOML
from .conftest import RUNNER_DIR

pytestmark = pytest.mark.acceptance


def group_chat(tmp_path: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HOME": str(tmp_path / "home")}
    return subprocess.run(
        [sys.executable, "-m", "group_chat", *argv],
        cwd=RUNNER_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def write_roster(tmp_path: Path) -> Path:
    (tmp_path / "po.md").write_text("You own the backlog.\n")
    path = tmp_path / "roster.toml"
    path.write_text(ROSTER_TOML)
    return path


def test_unaddressed_first_message_exits_2(tmp_path: Path) -> None:
    """First message has no mention -> refused, exit 2; errors show the valid names."""
    roster = write_roster(tmp_path)
    done = group_chat(tmp_path, "--roster", str(roster), "--dir", str(tmp_path / "c"), "say", "hi")
    assert done.returncode == 2
    assert "@manager @po @liaison @all" in done.stderr
    assert done.stdout == ""
    assert not (tmp_path / "c").exists()


def test_bad_roster_exits_2(tmp_path: Path) -> None:
    """A roster that breaks a rule is rejected on load."""
    roster = tmp_path / "roster.toml"
    roster.write_text("[[role]]\nname = 'all'\nprompt = 'p'\n")
    done = group_chat(
        tmp_path, "--roster", str(roster), "--dir", str(tmp_path / "c"), "say", "@all hi"
    )
    assert done.returncode == 2
    assert "group-chat: role name 'all' is reserved" in done.stderr
    assert not (tmp_path / "c").exists()


def test_missing_roster_exits_2(tmp_path: Path) -> None:
    """Rejected on load: an unreadable roster."""
    missing = str(tmp_path / "nope.toml")
    done = group_chat(tmp_path, "--roster", missing, "--dir", str(tmp_path / "c"), "say", "@a x")
    assert done.returncode == 2
    assert "nope.toml" in done.stderr

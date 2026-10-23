"""s162 end to end: ``unattended status|list|wait`` give each job a ``time_left``."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from .readiness import wait_until

PROJECT = Path(__file__).resolve().parents[4] / "unattended" / "runner"


class Unattended:
    """The real ``unattended`` CLI with a scratch home."""

    def __init__(self, home: Path) -> None:
        self.home = home

    def run(self, *args: str) -> str:
        """Run one subcommand and return its stdout."""
        cmd = ["uv", "run", "--quiet", "--project", str(PROJECT), "unattended"]
        done = subprocess.run(
            [*cmd, "--home", str(self.home), *args],
            capture_output=True, text=True, timeout=120, cwd=self.home,
        )  # fmt: skip
        return done.stdout

    def status(self, name: str) -> dict:
        """The job's ``status`` report."""
        return json.loads(self.run("status", name))


@pytest.fixture
def cli(tmp_path: Path) -> Iterator[Unattended]:
    """A CLI on a scratch home; stops every job afterwards."""
    tool = Unattended(tmp_path)
    yield tool
    for job in json.loads(tool.run("list")):
        tool.run("stop", job["name"])


def start(cli: Unattended, name: str, *limit: str) -> None:
    cli.run("start", "--command", "sleep 300", *limit, name)


def test_time_left_shapes_and_unchanged_state(cli: Unattended) -> None:
    start(cli, "long", "--for", "23h41m30s")
    start(cli, "tiny", "--for", "30s")
    start(cli, "plain")
    assert cli.status("long")["time_left"] == "23h41m"
    assert cli.status("tiny")["time_left"] == "0m"
    assert cli.status("plain")["time_left"] is None
    assert cli.status("plain")["deadline"] is None
    state = cli.home / ".claude" / "jobs" / "long" / "state.json"
    before = state.read_bytes()
    reports = json.loads(cli.run("list"))
    assert {r["name"]: r["time_left"] for r in reports}["long"] == "23h41m"
    assert "time_left" not in json.loads(before)
    assert state.read_bytes() == before


def test_overdue_after_deadline(cli: Unattended) -> None:
    start(cli, "late", "--for", "1s")
    wait_until(lambda: cli.status("late")["time_left"] == "overdue", "deadline passed")
    cli.run("stop", "late")
    assert json.loads(cli.run("wait", "late"))["time_left"] == "overdue"

"""s62 end to end: ``tell``, ``watch`` and ``pin-runner.sh`` through their real entry points."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agile_team.relay import Note, Relay

from ..conftest import git

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "pin-runner.sh"


ENTRY = "import sys; from agile_team.cli import main; sys.exit(main())"


def run_cli(repo: Path, *argv: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    """Run ``the CLI entry`` as a separate process, the way a human would."""
    return subprocess.run(
        [sys.executable, "-c", ENTRY, "--repo", str(repo), *argv],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_tell_from_stdin_then_watch_reports_the_outbox_message(configured: Path) -> None:
    told = run_cli(configured, "tell", "-", stdin="please hurry\n")
    assert told.returncode == 0 and "queued t1 for the PO" in told.stdout
    stored = configured / ".team" / "run" / "liaison" / "messages" / "t1.md"
    assert stored.read_text() == "please hurry\n"
    relay = Relay(configured / ".team" / "run")
    relay.post(Note("update", "history"))
    first = run_cli(configured, "watch", "--timeout", "1")
    line = json.loads(first.stdout)
    assert first.returncode == 0 and line["triggers"] == ["heartbeat"]
    assert line["messages"] == []
    seen = configured / ".team" / "run" / "liaison" / "watch.json"
    assert json.loads(seen.read_text())["messages"] == 1
    relay.post(Note("update", "hello"))
    fresh = json.loads(run_cli(configured, "watch", "--timeout", "5").stdout)
    assert "message" in fresh["triggers"]
    assert [m["id"] for m in fresh["messages"]] == ["m2"]
    second = run_cli(configured, "watch", "--timeout", "1")
    assert json.loads(second.stdout)["triggers"] == ["heartbeat"]


def test_status_lists_the_queued_message(configured: Path) -> None:
    run_cli(configured, "tell", "-", stdin="x")
    status = run_cli(configured, "status")
    assert json.loads(status.stdout)["queued_messages"] == ["t1"]


def test_tell_refuses_an_empty_message(configured: Path) -> None:
    result = run_cli(configured, "tell", "-", stdin="  \n")
    assert result.returncode == 1 and "the message is empty" in result.stderr


def pin(repo: Path, commit: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sh", str(SCRIPT), commit], cwd=repo, capture_output=True, text=True, check=False
    )


def test_pin_runner_builds_the_copy_and_records_the_commit(repo: Path) -> None:
    runner = repo / "agile-team" / "runner"
    runner.mkdir(parents=True)
    (runner / "pyproject.toml").write_text("[project]\nname='x'\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "runner")
    sha = git(repo, "rev-parse", "HEAD").strip()
    result = pin(repo, "HEAD")
    assert result.returncode == 0 and result.stdout.startswith(f"pinned {sha[:7]} at ")
    run = repo / ".team" / "run"
    assert (run / "runner-pin" / "pyproject.toml").is_file()
    assert (run / "runner-pin.commit").read_text() == sha + "\n"
    assert pin(repo, "nope").returncode == 1

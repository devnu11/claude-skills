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


def _commit_runner(repo: Path, marker: str) -> str:
    """Commit a runner tree whose pyproject carries `marker`; return the commit sha."""
    runner = repo / "agile-team" / "runner"
    runner.mkdir(parents=True, exist_ok=True)
    (runner / "pyproject.toml").write_text(f"[project]\nname='{marker}'\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", marker)
    return git(repo, "rev-parse", "HEAD").strip()


def _script(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sh", str(SCRIPT), *args], cwd=repo, capture_output=True, text=True, check=False
    )


def test_a_second_pin_keeps_the_first_as_prev(repo: Path) -> None:
    """s128 AC2 (P6): the old pin and its commit move to `runner-pin.prev[.commit]`."""
    first = _commit_runner(repo, "one")
    assert _script(repo, first).returncode == 0
    second = _commit_runner(repo, "two")
    assert _script(repo, second).returncode == 0
    run = repo / ".team" / "run"
    assert (run / "runner-pin.commit").read_text() == second + "\n"
    assert (run / "runner-pin.prev.commit").read_text() == first + "\n"
    assert "one" in (run / "runner-pin.prev" / "pyproject.toml").read_text()
    assert "two" in (run / "runner-pin" / "pyproject.toml").read_text()


def test_rollback_restores_the_prev_pin_and_keeps_the_failed_one(repo: Path) -> None:
    """s128 AC2 (P7): `--rollback` swaps prev back in and parks the current pin as `.failed`."""
    first = _commit_runner(repo, "one")
    _script(repo, first)
    second = _commit_runner(repo, "two")
    _script(repo, second)
    result = _script(repo, "--rollback")
    run = repo / ".team" / "run"
    assert result.returncode == 0 and f"rolled back to {first[:7]}" in result.stdout
    assert (run / "runner-pin.commit").read_text() == first + "\n"
    assert (run / "runner-pin.failed.commit").read_text() == second + "\n"
    assert not (run / "runner-pin.prev").exists()


def test_rollback_without_a_prev_pin_fails(repo: Path) -> None:
    """s128 AC2 (P7): nothing to go back to is exit 1."""
    _script(repo, _commit_runner(repo, "one"))
    result = _script(repo, "--rollback")
    assert result.returncode == 1 and "no previous pin to roll back to" in result.stderr


def test_the_usage_line_names_rollback_and_exits_2(repo: Path) -> None:
    """s128 AC2 (P7): wrong arguments print the new usage and exit 2."""
    result = _script(repo, "a", "b")
    assert result.returncode == 2 and "usage: pin-runner.sh <commit> | --rollback" in result.stderr

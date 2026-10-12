"""s62: ``pin-runner.sh`` builds a frozen copy of the runner from an accepted commit (P1-P3)."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pin-runner.sh"


def run_git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=git_env()
    ).stdout.strip()


def git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="T",
        GIT_AUTHOR_EMAIL="t@example.com",
        GIT_COMMITTER_NAME="T",
        GIT_COMMITTER_EMAIL="t@example.com",
    )
    env.pop("GIT_DIR", None)
    return env


def commit(repo: Path, message: str) -> str:
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", message)
    return run_git(repo, "rev-parse", "HEAD")


@pytest.fixture
def scratch(tmp_path: Path) -> Path:
    repo = tmp_path / "scratch"
    pkg = repo / "agile-team" / "runner" / "agile_team"
    pkg.mkdir(parents=True)
    (repo / "agile-team" / "runner" / "pyproject.toml").write_text("[project]\nname='x'\n")
    (pkg / "old.py").write_text("old = 1\n")
    (pkg / "keep.py").write_text("keep = 1\n")
    run_git(repo, "init", "-q", "-b", "main")
    commit(repo, "first")
    return repo


def pin(repo: Path, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sh", str(SCRIPT), *args],
        cwd=cwd or repo,
        capture_output=True,
        text=True,
        env=git_env(),
    )


def pinned(repo: Path) -> Path:
    return repo / ".team" / "run" / "runner-pin"


def head(repo: Path) -> str:
    return run_git(repo, "rev-parse", "HEAD")


def test_pin_builds_the_tree_without_the_prefix(scratch: Path) -> None:
    sha = head(scratch)
    done = pin(scratch, sha)
    assert done.returncode == 0, done.stderr
    assert (pinned(scratch) / "pyproject.toml").is_file()
    assert (pinned(scratch) / "agile_team" / "keep.py").is_file()
    assert (scratch / ".team" / "run" / "runner-pin.commit").read_text() == sha + "\n"
    assert done.stdout.startswith(f"pinned {sha[:7]} at .team/run/runner-pin")
    assert "uv run --frozen --quiet --project .team/run/runner-pin agile-team" in done.stdout


def test_repin_replaces_the_tree(scratch: Path) -> None:
    pin(scratch, head(scratch))
    (scratch / "agile-team" / "runner" / "agile_team" / "old.py").unlink()
    (scratch / "agile-team" / "runner" / "agile_team" / "new.py").write_text("n = 1\n")
    later = commit(scratch, "second")
    assert pin(scratch, later).returncode == 0
    assert not (pinned(scratch) / "agile_team" / "old.py").exists()
    assert (pinned(scratch) / "agile_team" / "new.py").is_file()
    assert not (scratch / ".team" / "run" / "runner-pin.new").exists()
    assert (scratch / ".team" / "run" / "runner-pin.commit").read_text() == later + "\n"


def test_pinning_from_a_subdirectory_pins_at_the_root(scratch: Path) -> None:
    sub = scratch / "agile-team"
    assert pin(scratch, head(scratch), cwd=sub).returncode == 0
    assert (pinned(scratch) / "pyproject.toml").is_file()
    assert not (sub / ".team").exists()


def existing_pin(repo: Path) -> tuple[str, str]:
    pin(repo, head(repo))
    return (
        (pinned(repo) / "pyproject.toml").read_text(),
        (repo / ".team" / "run" / "runner-pin.commit").read_text(),
    )


def assert_refused(repo: Path, done, reason: str, code: int = 1) -> None:
    assert done.returncode == code
    assert done.stderr.strip() == f"pin-runner: {reason}"
    assert done.stdout == ""


@pytest.mark.parametrize("args", [[], ["a", "b"]])
def test_wrong_argument_count_is_a_usage_error(scratch: Path, args) -> None:
    assert_refused(scratch, pin(scratch, *args), "usage: pin-runner.sh <commit>", 2)


def test_refuses_outside_a_git_repository(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    env = git_env()
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path)
    done = subprocess.run(
        ["sh", str(SCRIPT), "abc"], cwd=plain, capture_output=True, text=True, env=env
    )
    assert_refused(plain, done, "not a git repository")


def test_refuses_an_unknown_commit(scratch: Path) -> None:
    before = existing_pin(scratch)
    assert_refused(scratch, pin(scratch, "deadbeef"), "unknown commit: deadbeef")
    assert existing_pin(scratch) == before


def test_refuses_a_commit_off_the_branch(scratch: Path) -> None:
    before = existing_pin(scratch)
    run_git(scratch, "checkout", "-q", "-b", "side")
    (scratch / "x.txt").write_text("x\n")
    side = commit(scratch, "side")
    run_git(scratch, "checkout", "-q", "main")
    reason = f"{side} is not on the checked-out branch; pin only accepted code"
    assert_refused(scratch, pin(scratch, side), reason)
    assert existing_pin(scratch) == before


def test_refuses_a_commit_without_a_runner(scratch: Path) -> None:
    run_git(scratch, "checkout", "-q", "--orphan", "bare")
    run_git(scratch, "rm", "-rfq", ".")
    (scratch / "readme").write_text("r\n")
    bare = commit(scratch, "bare")
    run_git(scratch, "checkout", "-q", "main")
    run_git(scratch, "merge", "-q", "--allow-unrelated-histories", "-m", "m", "bare")
    done = pin(scratch, bare)
    assert_refused(scratch, done, f"{bare} has no agile-team/runner")


def test_refuses_while_the_team_runs(scratch: Path) -> None:
    before = existing_pin(scratch)
    (scratch / ".team" / "run" / "runner.pid").write_text(str(os.getpid()))
    assert_refused(scratch, pin(scratch, head(scratch)), "the team is running; stop it first")
    assert existing_pin(scratch) == before


def test_a_dead_pid_does_not_block(scratch: Path) -> None:
    proc = subprocess.Popen(["true"])
    proc.wait()
    run = scratch / ".team" / "run"
    run.mkdir(parents=True)
    (run / "runner.pid").write_text(str(proc.pid))
    assert pin(scratch, head(scratch)).returncode == 0

"""The command line."""

import io
import subprocess
import sys
from pathlib import Path

import pytest
from house_rules.baseline import Baseline
from house_rules.cli import describe_limits, main
from house_rules.model import Limits

from .conftest import git

LONG = "def add(a, b, c, d):\n    return a\n"


def write(repo: Path, name: str, text: str) -> None:
    (repo / name).write_text(text)


def test_check_reports_and_fails(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(git_repo, "a.py", LONG)
    assert main(["check"]) == 1
    assert "a.py:1: fail parameters" in capsys.readouterr().out


def test_check_formats(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(git_repo, "a.py", LONG)
    main(["check", "--format", "github"])
    assert capsys.readouterr().out.startswith("::error file=a.py,line=1,")


def test_baseline_ratchet(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(git_repo, "a.py", LONG)
    assert main(["baseline"]) == 1
    assert "a.py::add::parameters: new -> 4" in capsys.readouterr().err
    assert main(["baseline", "--accept-new"]) == 0
    assert main(["check"]) == 0
    write(git_repo, "a.py", "def add(a, b, c, d, e):\n    return a\n")
    assert main(["check"]) == 1
    write(git_repo, "a.py", "def add_up(a, b, c, d):\n    return a\n")
    assert main(["check"]) == 1, "a renamed function is a new violation"
    write(git_repo, "a.py", "def add(a):\n    return a\n")
    assert main(["check"]) == 0
    assert main(["baseline"]) == 0
    assert Baseline.from_file(git_repo / ".house-rules-baseline.json").entries == {}


def test_staged_checks_the_index(git_repo: Path) -> None:
    write(git_repo, "a.py", LONG)
    git(git_repo, "add", "a.py")
    write(git_repo, "a.py", "def add(a):\n    return a\n")
    assert main(["check", "--staged"]) == 1
    assert main(["check"]) == 0


def test_config_error_exits_2(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(git_repo, ".house-rules.toml", "colour = 1\n")
    assert main(["check"]) == 2
    assert "unknown keys: colour" in capsys.readouterr().err


def test_rules_lists_repo_limits(git_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(
        git_repo,
        ".house-rules.toml",
        'disable = ["verb-synonym"]\n[limits.parameters]\nwarn = 3\nfail = 5\n',
    )
    assert main(["rules"]) == 0
    out = capsys.readouterr().out
    assert "warn > 3, fail > 5" in out and "verb-synonym        off" in out


def test_describe_limits() -> None:
    assert describe_limits(Limits(0, 0)) == "fail > 0"
    assert describe_limits(Limits(0, 2**31)) == "warn > 0"


def test_hook_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert main(["hook"]) == 0


def test_runs_as_a_module(tmp_path: Path) -> None:
    result = subprocess.run([sys.executable, "-m", "house_rules", "rules"], cwd=tmp_path,
                            capture_output=True, text=True, check=False)  # fmt: skip
    assert result.returncode == 0 and "global-scope" in result.stdout

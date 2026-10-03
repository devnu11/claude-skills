"""Preflight refusals."""

import os
from pathlib import Path

from agile_team import config as cfg
from agile_team import preflight
from agile_team.git_ops import Git


def test_clean_tree_passes(configured: Path) -> None:
    assert preflight.check_clean_tree(Git(configured)) == []


def test_dirty_tree_refused(configured: Path) -> None:
    for i in range(7):
        (configured / f"f{i}").write_text("x")
    [msg] = preflight.check_clean_tree(Git(configured))
    assert "dirty" in msg and "…" in msg


def test_key_falls_back_to_home(configured: Path, key_home: Path) -> None:
    c = cfg.load(configured)
    assert preflight.check_key(c, Git(configured), key_home) == []


def test_key_missing(configured: Path, tmp_path: Path) -> None:
    c = cfg.load(configured)
    [msg] = preflight.check_key(c, Git(configured), tmp_path / "none")
    assert "no API key" in msg


def test_repo_key_not_ignored_and_bad_mode(configured: Path, key_home: Path) -> None:
    c = cfg.load(configured)
    c.team.key_file = "secret.key"
    key = configured / "secret.key"
    key.write_text("k")
    os.chmod(key, 0o644)
    problems = preflight.check_key(c, Git(configured), key_home)
    assert any("not gitignored" in p for p in problems)
    assert any("mode 600" in p for p in problems)


def test_executable_of() -> None:
    assert preflight.executable_of("FOO=1 uv run pytest") == "uv"
    assert preflight.executable_of("") == ""


def test_toolchain_missing(configured: Path) -> None:
    c = cfg.load(configured)
    found = {"pytest"}
    problems = preflight.check_toolchain(c, lambda exe: exe if exe in found else None)
    assert problems == ["toolchain.lint: `ruff` not found on PATH"]


def test_run_all(configured: Path, key_home: Path) -> None:
    c = cfg.load(configured)
    assert preflight.run_all(c, Git(configured), key_home, lambda e: e) == []

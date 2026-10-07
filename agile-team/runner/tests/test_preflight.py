"""Preflight refusals."""

import os
from pathlib import Path

from agile_team import config as cfg
from agile_team import preflight
from agile_team.git_ops import Git


def check(repo: Path, home: Path, which=lambda e: e) -> preflight.Preflight:
    return preflight.Preflight(cfg.load(repo), Git(repo), home, which)


def test_clean_tree_passes(configured: Path, key_home: Path) -> None:
    assert check(configured, key_home).clean_tree() == []


def test_dirty_tree_refused(configured: Path, key_home: Path) -> None:
    for i in range(7):
        (configured / f"f{i}").write_text("x")
    [msg] = check(configured, key_home).clean_tree()
    assert "dirty" in msg and "…" in msg


def test_key_falls_back_to_home(configured: Path, key_home: Path) -> None:
    assert check(configured, key_home).key() == []


def test_key_missing(configured: Path, tmp_path: Path) -> None:
    [msg] = check(configured, tmp_path / "none").key()
    assert "no API key" in msg


def test_repo_key_not_ignored_and_bad_mode(configured: Path, key_home: Path) -> None:
    pre = check(configured, key_home)
    pre.config.team.key_file = "secret.key"
    key = configured / "secret.key"
    key.write_text("k")
    os.chmod(key, 0o644)
    problems = pre.key()
    assert any("not gitignored" in p for p in problems)
    assert any("mode 600" in p for p in problems)


def test_executable_of() -> None:
    assert preflight.executable_of("FOO=1 uv run pytest") == "uv"
    assert preflight.executable_of("") == ""


def test_toolchain_missing(configured: Path, key_home: Path) -> None:
    found = {"pytest"}
    problems = check(configured, key_home, lambda exe: exe if exe in found else None).toolchain()
    assert problems == ["toolchain.lint: `ruff` not found on PATH"]


def test_run_all(configured: Path, key_home: Path) -> None:
    assert check(configured, key_home).run_all() == []

"""API key resolution."""

import os
from pathlib import Path

import pytest
from agile_team import keys


def test_repo_key_wins(tmp_path: Path, key_home: Path) -> None:
    (tmp_path / ".team/run").mkdir(parents=True)
    (tmp_path / ".team/run/api-key").write_text(" sk-repo \n")
    src = keys.KeyLocations(tmp_path, ".team/run/api-key", key_home).resolve()
    assert src.origin is keys.KeyOrigin.REPO
    assert keys.read_key(src.path) == "sk-repo"


def test_falls_back_to_home(tmp_path: Path, key_home: Path) -> None:
    src = keys.KeyLocations(tmp_path, ".team/run/api-key", key_home).resolve()
    assert src.origin is keys.KeyOrigin.HOME
    assert keys.mode_ok(src.path)


def test_none_found(tmp_path: Path) -> None:
    with pytest.raises(keys.KeyNotFound, match="tried"):
        keys.KeyLocations(tmp_path, "k", tmp_path / "nohome").resolve()


def test_mode(tmp_path: Path) -> None:
    f = tmp_path / "k"
    f.write_text("x")
    os.chmod(f, 0o644)
    assert not keys.mode_ok(f)


def test_child_env() -> None:
    env = keys.child_env("abc")
    assert env["ANTHROPIC_API_KEY"] == "abc"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == ""


def test_secret_paths_and_rules(tmp_path: Path) -> None:
    paths = keys.KeyLocations(tmp_path, "k", tmp_path / "home").secret_paths()
    assert paths == [
        tmp_path / "k",
        tmp_path / "home/secrets/anthropic-api-key",
        tmp_path / "home/secrets",
    ]
    rules = keys.deny_rules([tmp_path / "k"])
    assert rules == [f"Read(/{tmp_path.resolve()}/k)", f"Read(/{tmp_path.resolve()}/k/**)"]

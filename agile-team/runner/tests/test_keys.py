"""API key resolution."""

from pathlib import Path

import pytest
from agile_team import keys, system

from .fake_system import FAKE_HOME, FAKE_REPO, FakeSystem


def test_repo_key_wins(fake: FakeSystem, key_home: Path) -> None:
    fake.put(FAKE_REPO / ".team/run/api-key", " sk-repo \n", mode=0o600)
    src = keys.KeyLocations(FAKE_REPO, ".team/run/api-key", key_home).resolve()
    assert src.origin is keys.KeyOrigin.REPO
    assert keys.read_key(src.path) == "sk-repo"


def test_falls_back_to_home(key_home: Path) -> None:
    src = keys.KeyLocations(FAKE_REPO, ".team/run/api-key", key_home).resolve()
    assert src.origin is keys.KeyOrigin.HOME
    assert keys.mode_ok(src.path)


@pytest.mark.parametrize(
    ("key_file", "where"),
    [
        (str(FAKE_HOME / "anthropic_key"), FAKE_HOME / "anthropic_key"),
        ("~/anthropic_key", FAKE_HOME / "anthropic_key"),
        ("../elsewhere/key", FAKE_REPO / "../elsewhere/key"),
    ],
)
def test_a_configured_key_outside_the_repo_is_external(key_file: str, where: Path) -> None:
    source = keys.KeyLocations(FAKE_REPO, key_file, FAKE_HOME).configured()
    assert source == keys.KeySource(where, keys.KeyOrigin.EXTERNAL)


def test_an_absolute_key_inside_the_repo_is_a_repo_key() -> None:
    source = keys.KeyLocations(FAKE_REPO, str(FAKE_REPO / "k"), FAKE_HOME).configured()
    assert source.origin is keys.KeyOrigin.REPO


def test_none_found() -> None:
    with pytest.raises(keys.KeyNotFound, match="tried"):
        keys.KeyLocations(FAKE_REPO, "k", FAKE_REPO / "nohome").resolve()


def test_mode(fake: FakeSystem) -> None:
    f = FAKE_REPO / "k"
    fake.put(f, "x", mode=0o644)
    assert not keys.mode_ok(f)
    fake.put(f, "x", mode=0o600)
    assert keys.mode_ok(f)


def test_child_env() -> None:
    env = keys.child_env("abc")
    assert env["ANTHROPIC_API_KEY"] == "abc"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == ""


def test_secret_paths_and_rules() -> None:
    paths = keys.KeyLocations(FAKE_REPO, "k", FAKE_HOME).secret_paths()
    assert paths == [
        FAKE_REPO / "k",
        FAKE_HOME / "secrets/anthropic-api-key",
        FAKE_HOME / "secrets",
    ]
    resolved = system.resolve(FAKE_REPO)
    rules = keys.deny_rules([FAKE_REPO / "k"])
    assert rules == [f"Read(/{resolved}/k)", f"Read(/{resolved}/k/**)"]

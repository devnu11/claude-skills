from __future__ import annotations

from pathlib import Path

from unattended.auth import COMPETING_VARS, ENV_VAR, HOME_KEY, Auth, AuthSetup


def key_file(path: Path, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("sk-test\n")
    path.chmod(mode)
    return path


def test_login_refuses_an_inherited_key(tmp_path: Path) -> None:
    problems = AuthSetup(Auth.LOGIN, None, tmp_path).problems({ENV_VAR: "sk-x"})
    assert problems == [f"auth is login but ${ENV_VAR} is set; unset it or use --auth api-key"]


def test_login_passes_nothing(tmp_path: Path) -> None:
    setup = AuthSetup(Auth.LOGIN, None, tmp_path)
    assert setup.problems({ENV_VAR: ""}) == []
    assert setup.env() == {}


def test_api_key_defaults_to_home_secrets(tmp_path: Path) -> None:
    key_file(tmp_path / HOME_KEY)
    setup = AuthSetup(Auth.API_KEY, None, tmp_path)
    assert setup.key_path == tmp_path / HOME_KEY
    assert setup.problems({}) == []


def test_api_key_env_blanks_competing_tokens(tmp_path: Path) -> None:
    setup = AuthSetup(Auth.API_KEY, key_file(tmp_path / "k"), tmp_path)
    assert setup.env() == {ENV_VAR: "sk-test", **dict.fromkeys(COMPETING_VARS, "")}


def test_api_key_missing(tmp_path: Path) -> None:
    problems = AuthSetup(Auth.API_KEY, tmp_path / "nope", tmp_path).problems({})
    assert problems == [f"no API key file at {tmp_path / 'nope'}"]


def test_api_key_mode_is_checked(tmp_path: Path) -> None:
    path = key_file(tmp_path / "k", 0o644)
    assert AuthSetup(Auth.API_KEY, path, tmp_path).problems({}) == [f"{path} must be mode 600"]

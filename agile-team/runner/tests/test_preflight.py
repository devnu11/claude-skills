"""Preflight refusals."""

from pathlib import Path

import pytest
from agile_team import config as cfg
from agile_team import keys, preflight, system
from agile_team.git_ops import Git
from agile_team.providers import Provider

from .fake_system import Done, FakeSystem

TOOLS = {"pytest": "/bin/pytest", "ruff": "/bin/ruff"}


@pytest.fixture(autouse=True)
def on_path(fake: FakeSystem) -> None:
    """The python preset's executables are installed."""
    fake.programs.update(TOOLS)


def check(repo: Path, home: Path) -> preflight.Preflight:
    return preflight.Preflight(cfg.load(repo), Git(repo), home)


def test_clean_tree_passes(configured: Path, key_home: Path) -> None:
    assert check(configured, key_home).clean_tree() == []


def test_dirty_tree_refused(configured: Path, key_home: Path, fake: FakeSystem) -> None:
    fake.track()
    for i in range(7):
        system.write_text(configured / f"f{i}", "x")
    [msg] = check(configured, key_home).clean_tree()
    assert "dirty" in msg and "…" in msg


def test_key_falls_back_to_home(configured: Path, key_home: Path) -> None:
    assert check(configured, key_home).key() == []


def test_key_missing(configured: Path, scratch: Path) -> None:
    [msg] = check(configured, scratch / "none").key()
    assert "no API key" in msg


def test_repo_key_not_ignored_and_bad_mode(
    configured: Path, key_home: Path, fake: FakeSystem
) -> None:
    pre = check(configured, key_home)
    pre.config.team.key_file = "secret.key"
    fake.put(configured / "secret.key", "k", mode=0o644)
    fake.reply(("git", "check-ignore"), Done(1))
    problems = pre.key()
    assert any("not gitignored" in p for p in problems)
    assert any("mode 600" in p for p in problems)


def test_executable_of() -> None:
    assert preflight.executable_of("FOO=1 uv run pytest") == "uv"
    assert preflight.executable_of("") == ""


def test_toolchain_missing(configured: Path, key_home: Path, fake: FakeSystem) -> None:
    del fake.programs["ruff"]
    problems = check(configured, key_home).toolchain()
    assert problems == ["toolchain.lint: `ruff` not found on PATH"]


def test_run_all(configured: Path, key_home: Path) -> None:
    assert check(configured, key_home).run_all() == []


def with_providers(repo: Path, home: Path, roles: dict) -> preflight.Preflight:
    pf = check(repo, home)
    pf.config.providers = {
        "local": Provider("local", "http://localhost:11434"),
        "proxy": Provider("proxy", "https://proxy.example", token_env="PROXY_TOKEN"),
        "unused": Provider("unused", "http://down.example"),
    }
    pf.config.roles = roles
    pf.probe = lambda url: url != "http://localhost:11434"
    return pf


def test_providers_checked_only_when_a_role_uses_them(configured: Path, key_home: Path) -> None:
    roles = {"scribe": {"provider": "local"}, "devops": {"provider": "proxy"}}
    assert with_providers(configured, key_home, roles).providers() == [
        "providers.local: nothing answers at http://localhost:11434",
        "providers.proxy: $PROXY_TOKEN is not set",
    ]
    assert with_providers(configured, key_home, {}).providers() == []


def test_providers_skip_a_broken_role(configured: Path, key_home: Path) -> None:
    roles = {"ghost": {}}
    assert with_providers(configured, key_home, roles).providers() == []


def test_login_auth_needs_no_key_but_refuses_an_inherited_one(
    configured: Path, scratch: Path, fake: FakeSystem
) -> None:
    pre = check(configured, scratch / "no-home")
    pre.config.team.auth = cfg.LOGIN_AUTH
    assert pre.key() == []
    fake.env[keys.ENV_VAR] = "sk-x"
    [msg] = pre.key()
    assert "team.auth is login" in msg


def test_toolchain_checks_each_delivery_e2e_executable(configured: Path, key_home: Path) -> None:
    pre = check(configured, key_home)
    pre.config.deliveries[0].e2e = "e2erunner --all"
    assert pre.toolchain() == ["delivery.cli.e2e: `e2erunner` not found on PATH"]


def test_toolchain_ignores_an_empty_e2e(configured: Path, key_home: Path) -> None:
    assert check(configured, key_home).toolchain() == []


def test_provider_token_is_read_from_the_environment(
    configured: Path, key_home: Path, fake: FakeSystem
) -> None:
    roles = {"devops": {"provider": "proxy"}}
    fake.env["PROXY_TOKEN"] = "t"
    assert with_providers(configured, key_home, roles).providers() == []

"""Config loading and validation."""

from pathlib import Path

import pytest
from agile_team import config as cfg
from agile_team import system

KNOWN = cfg.Known({"developer"}, {"package", "web", "harness"})


def test_load_missing(repo: Path) -> None:
    with pytest.raises(cfg.ConfigError, match="not found"):
        cfg.load(repo)


def test_load_bad_toml(repo: Path) -> None:
    system.write_text(repo / cfg.CONFIG_NAME, "[team\n")
    with pytest.raises(cfg.ConfigError):
        cfg.load(repo)


def test_load_full(configured: Path) -> None:
    c = cfg.load(configured)
    assert c.team.budget_usd == 10.0
    assert c.toolchain.commands["test"] == "pytest"
    assert c.deliveries[0].kind == "package"
    assert c.run_dir == configured / ".team/run"
    assert c.placeholders()["docs"] == ["docs/**"]
    assert c.placeholders()["config"] == [cfg.CONFIG_NAME]
    assert cfg.validate(c, KNOWN) == []


def test_delivery_lookup(configured: Path) -> None:
    c = cfg.load(configured)
    assert c.delivery(None).name == "cli"
    assert c.delivery("cli").name == "cli"
    assert c.delivery("nope") is None
    c.deliveries = []
    assert c.delivery(None) is None


def test_unknown_keys_are_ignored(repo: Path) -> None:
    c = cfg.from_raw(
        repo,
        {
            "team": {"bogus": 1},
            "gates": {"x": 2},
            "delivery": [{"name": "a", "kind": "package", "extra": True}],
        },
    )
    assert c.team.cadence == "sprint"
    assert c.deliveries[0].name == "a"


def test_validate_reports_every_problem(repo: Path) -> None:
    raw = {
        "team": {"cadence": "x", "artifacts": "x", "budget_usd": 0, "manager_every_pct": 0},
        "gates": {"coverage": 101, "round_cap": 0, "steps": ["nope"]},
        "delivery": [
            {"name": "w", "kind": "web"},
            {"name": "w", "kind": "harness"},
            {"name": "z", "kind": "bogus"},
            {"name": "../up", "kind": "package"},
        ],
        "roles": {
            "ghost": {},
            "dev-x": {"extends": "missing"},
            "dev-y": {"extends": "developer"},
            "developer": {"model": "haiku"},
        },
    }
    problems = cfg.validate(cfg.from_raw(repo, raw), KNOWN)
    text = "\n".join(problems)
    for needle in [
        "cadence",
        "artifacts",
        "budget_usd",
        "manager_every_pct",
        "toolchain.test",
        "toolchain.coverage",
        "globs.source",
        "globs.tests",
        "gates.steps",
        "gates.coverage",
        "round_cap",
        "unknown kind",
        "repeated",
        "needs a url",
        "needs commands",
        "roles.ghost",
        "unknown role 'missing'",
    ]:
        assert needle in text, needle
    assert "dev-y" not in text


def test_providers_load_and_validate(repo: Path) -> None:
    raw = {
        "providers": {
            "local": {"base_url": "http://localhost:11434", "extra": 1},
            "anthropic": {"base_url": "https://x"},
            "odd": {"base_url": "ftp://x", "kind": "codex", "billing": "maybe"},
        },
    }
    c = cfg.from_raw(repo, raw)
    assert c.providers["local"].name == "local"
    assert c.providers["local"].billing == "free"
    problems = [p for p in cfg.validate(c, KNOWN) if p.startswith("providers.")]
    assert problems == [
        "providers.anthropic is built in; pick another name",
        "providers.odd kind must be one of ('anthropic',)",
        "providers.odd billing must be one of ('reported', 'free')",
        "providers.odd base_url must be an http(s) URL",
    ]


# ----- s29: [upstream] and Delivery.e2e -------------------------------------


def test_upstream_defaults(repo: Path) -> None:
    c = cfg.from_raw(repo, {})
    assert (c.upstream.remote, c.upstream.branch, c.upstream.prefix) == (
        "origin",
        "main",
        "team/sprint-",
    )


def test_upstream_loads_and_ignores_unknown_keys(repo: Path) -> None:
    raw = {"upstream": {"remote": "up", "branch": "dev", "prefix": "rev/s", "bogus": 1}}
    u = cfg.from_raw(repo, raw).upstream
    assert (u.remote, u.branch, u.prefix) == ("up", "dev", "rev/s")


def test_delivery_e2e_loads(repo: Path) -> None:
    c = cfg.from_raw(repo, {"delivery": [{"name": "a", "kind": "package", "e2e": "pytest e2e"}]})
    assert c.deliveries[0].e2e == "pytest e2e"
    assert (
        cfg.from_raw(repo, {"delivery": [{"name": "b", "kind": "package"}]}).deliveries[0].e2e == ""
    )


def _upstream_problems(repo: Path, upstream: dict) -> list[str]:
    c = cfg.from_raw(repo, {"upstream": upstream})
    return [p for p in cfg.validate(c, KNOWN) if p.startswith("upstream")]


def test_upstream_rules_messages(repo: Path) -> None:
    assert _upstream_problems(repo, {"branch": ""}) == ["upstream.branch must be set"]
    assert _upstream_problems(repo, {"prefix": "-bad"}) == [
        "upstream.prefix must be a branch name prefix"
    ]
    assert _upstream_problems(repo, {"prefix": "a b"}) == [
        "upstream.prefix must be a branch name prefix"
    ]


def test_upstream_valid_and_sync_off_allow_empty_branch(repo: Path) -> None:
    assert _upstream_problems(repo, {}) == []
    assert _upstream_problems(repo, {"remote": "", "branch": ""}) == []

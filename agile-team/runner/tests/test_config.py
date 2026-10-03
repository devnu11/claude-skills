"""Config loading and validation."""

from pathlib import Path

import pytest
from agile_team import config as cfg

KINDS = {"package", "web", "harness"}


def test_load_missing(tmp_path: Path) -> None:
    with pytest.raises(cfg.ConfigError, match="not found"):
        cfg.load(tmp_path)


def test_load_bad_toml(tmp_path: Path) -> None:
    (tmp_path / cfg.CONFIG_NAME).write_text("[team\n")
    with pytest.raises(cfg.ConfigError):
        cfg.load(tmp_path)


def test_load_full(configured: Path) -> None:
    c = cfg.load(configured)
    assert c.team.budget_usd == 10.0
    assert c.toolchain.commands["test"] == "pytest"
    assert c.deliveries[0].kind == "package"
    assert c.run_dir == configured / ".team/run"
    assert c.placeholders()["docs"] == ["docs/**"]
    assert c.placeholders()["config"] == [cfg.CONFIG_NAME]
    assert cfg.validate(c, {"developer"}, KINDS) == []


def test_delivery_lookup(configured: Path) -> None:
    c = cfg.load(configured)
    assert c.delivery(None).name == "cli"
    assert c.delivery("cli").name == "cli"
    assert c.delivery("nope") is None
    c.deliveries = []
    assert c.delivery(None) is None


def test_unknown_keys_are_ignored(tmp_path: Path) -> None:
    c = cfg.from_raw(
        tmp_path,
        {
            "team": {"bogus": 1},
            "gates": {"x": 2},
            "delivery": [{"name": "a", "kind": "package", "extra": True}],
        },
    )
    assert c.team.cadence == "sprint"
    assert c.deliveries[0].name == "a"


def test_validate_reports_every_problem(tmp_path: Path) -> None:
    raw = {
        "team": {"cadence": "x", "artifacts": "x", "budget_usd": 0, "manager_every_pct": 0},
        "gates": {"coverage": 101, "round_cap": 0, "steps": ["nope"]},
        "delivery": [
            {"name": "w", "kind": "web"},
            {"name": "w", "kind": "harness"},
            {"name": "z", "kind": "bogus"},
        ],
        "roles": {
            "ghost": {},
            "dev-x": {"extends": "missing"},
            "dev-y": {"extends": "developer"},
            "developer": {"model": "haiku"},
        },
    }
    problems = cfg.validate(cfg.from_raw(tmp_path, raw), {"developer"}, KINDS)
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
        "unknown step",
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

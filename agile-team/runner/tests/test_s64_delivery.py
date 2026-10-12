"""s64: a story's delivery must name a configured [[delivery]]."""

import asyncio
import json

import pytest
from agile_team import config as config_mod
from agile_team.config import Config, Delivery
from agile_team.po_tools import SCHEMAS, Tools

CLI = Delivery("cli", "cli")
WEB = Delivery("web", "web")


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


@pytest.fixture
def cfg(make_runtime):
    """A factory for a loaded Config holding exactly the given deliveries."""

    def build(deliveries: list[Delivery]) -> Config:
        config = make_runtime().config
        config.deliveries = deliveries
        return config

    return build


def unknown(name: str, names: str) -> str:
    return config_mod.UNKNOWN_DELIVERY.format(name=name, names=names)


def test_message_constants_are_exact() -> None:
    assert config_mod.UNKNOWN_DELIVERY == (
        "delivery {name!r} is not a configured [[delivery]]; use one of: {names}"
    )
    assert config_mod.NO_DELIVERY == (
        "delivery {name!r} is not a configured [[delivery]]; .agile-team.toml configures none, "
        "so leave delivery empty or ask the human to add a [[delivery]]"
    )


def test_configured_name_is_accepted(cfg) -> None:
    assert cfg([CLI]).delivery_refusal("cli") is None


@pytest.mark.parametrize("deliveries", [[], [CLI]], ids=["none", "one"])
@pytest.mark.parametrize("name", [None, ""], ids=["none", "empty"])
def test_empty_name_is_accepted(cfg, deliveries, name) -> None:
    assert cfg(deliveries).delivery_refusal(name) is None


def test_unknown_name_lists_names_in_config_order(cfg) -> None:
    reason = cfg([CLI, WEB]).delivery_refusal("nope")
    assert reason == unknown("nope", "cli, web")
    assert reason.endswith("use one of: cli, web")


@pytest.mark.parametrize("name", ["CLI", "cli "], ids=["case", "space"])
def test_match_is_exact(cfg, name) -> None:
    assert cfg([CLI]).delivery_refusal(name) == unknown(name, "cli")


def test_no_deliveries_configured(cfg) -> None:
    reason = cfg([]).delivery_refusal("cli")
    assert reason == config_mod.NO_DELIVERY.format(name="cli")
    assert "use one of" not in reason


def watch_save(rt) -> list[int]:
    saves: list[int] = []
    real = rt.save
    rt.save = lambda: (saves.append(1), real())[1]
    return saves


def test_open_story_valid_delivery(make_runtime) -> None:
    t = Tools(make_runtime())
    result = call(t.open_story({"id": "s1", "title": "Add", "delivery": "cli"}))
    assert result == {"status": "opened", "step": "design"}
    assert t.runtime.state.stories["s1"].delivery == "cli"
    assert len(t.runtime.events.events()) == 1


def test_open_story_without_delivery(make_runtime) -> None:
    t = Tools(make_runtime())
    assert call(t.open_story({"id": "s1", "title": "Add"}))["status"] == "opened"
    assert t.runtime.state.stories["s1"].delivery is None


def test_open_story_prose_delivery_refused_and_changes_nothing(make_runtime) -> None:
    rt = make_runtime()
    saves = watch_save(rt)
    prose = "agile-team runner (checkout guard)"
    result = call(Tools(rt).open_story({"id": "s1", "title": "Add", "delivery": prose}))
    assert result == {"status": "refused", "reason": unknown(prose, "cli")}
    assert "s1" not in rt.state.stories
    assert rt.events.events() == []
    assert saves == []


def test_open_story_refused_when_no_deliveries(make_runtime) -> None:
    rt = make_runtime()
    rt.config.deliveries = []
    result = call(Tools(rt).open_story({"id": "s1", "title": "A", "delivery": "cli"}))
    assert result == {"status": "refused", "reason": config_mod.NO_DELIVERY.format(name="cli")}
    assert "s1" not in rt.state.stories


def test_duplicate_id_wins_over_bad_delivery(make_runtime) -> None:
    t = Tools(make_runtime())
    call(t.open_story({"id": "s1", "title": "A"}))
    result = call(t.open_story({"id": "s1", "title": "A", "delivery": "prose"}))
    assert result == {"status": "refused", "reason": "story s1 already exists"}


def test_schema_description_mentions_delivery_rule() -> None:
    assert "[[delivery]]" in str(SCHEMAS["open_story"])

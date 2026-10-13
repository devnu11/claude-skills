"""s64: a story's environment must name a configured [[environment]]."""

import asyncio
import json

import pytest
from agile_team import config as config_mod
from agile_team.config import Config, Environment
from agile_team.po_tools import SCHEMAS, Tools

CLI = Environment("cli", "cli")
WEB = Environment("web", "web")


def call(coro) -> dict:
    return json.loads(asyncio.run(coro)["content"][0]["text"])


@pytest.fixture
def cfg(make_runtime):
    """A factory for a loaded Config holding exactly the given environments."""

    def build(environments: list[Environment]) -> Config:
        config = make_runtime().config
        config.environments = environments
        return config

    return build


def unknown(name: str, names: str) -> str:
    return config_mod.UNKNOWN_ENVIRONMENT.format(name=name, names=names)


def test_message_constants_are_exact() -> None:
    assert config_mod.UNKNOWN_ENVIRONMENT == (
        "acceptance environment {name!r} is not a configured [[environment]]; use one of: {names}"
    )
    assert config_mod.NO_ENVIRONMENT == (
        "acceptance environment {name!r} is not a configured [[environment]]; "
        ".agile-team.toml configures none, so leave environment empty or ask the human to add an [[environment]]"
    )


def test_configured_name_is_accepted(cfg) -> None:
    assert cfg([CLI]).environment_refusal("cli") is None


@pytest.mark.parametrize("environments", [[], [CLI]], ids=["none", "one"])
@pytest.mark.parametrize("name", [None, ""], ids=["none", "empty"])
def test_empty_name_is_accepted(cfg, environments, name) -> None:
    assert cfg(environments).environment_refusal(name) is None


def test_unknown_name_lists_names_in_config_order(cfg) -> None:
    reason = cfg([CLI, WEB]).environment_refusal("nope")
    assert reason == unknown("nope", "cli, web")
    assert reason.endswith("use one of: cli, web")


@pytest.mark.parametrize("name", ["CLI", "cli "], ids=["case", "space"])
def test_match_is_exact(cfg, name) -> None:
    assert cfg([CLI]).environment_refusal(name) == unknown(name, "cli")


def test_no_environments_configured(cfg) -> None:
    reason = cfg([]).environment_refusal("cli")
    assert reason == config_mod.NO_ENVIRONMENT.format(name="cli")
    assert "use one of" not in reason


def watch_save(rt) -> list[int]:
    saves: list[int] = []
    real = rt.save
    rt.save = lambda: (saves.append(1), real())[1]
    return saves


def test_open_story_valid_environment(make_runtime) -> None:
    t = Tools(make_runtime())
    result = call(t.open_story({"id": "s1", "title": "Add", "environment": "cli"}))
    assert result == {"status": "opened", "step": "design"}
    assert t.runtime.state.stories["s1"].environment == "cli"
    assert len(t.runtime.events.events()) == 1


def test_open_story_without_environment(make_runtime) -> None:
    t = Tools(make_runtime())
    assert call(t.open_story({"id": "s1", "title": "Add"}))["status"] == "opened"
    assert t.runtime.state.stories["s1"].environment is None


def test_open_story_prose_environment_refused_and_changes_nothing(make_runtime) -> None:
    rt = make_runtime()
    saves = watch_save(rt)
    prose = "agile-team runner (checkout guard)"
    result = call(Tools(rt).open_story({"id": "s1", "title": "Add", "environment": prose}))
    assert result == {"status": "refused", "reason": unknown(prose, "cli")}
    assert "s1" not in rt.state.stories
    assert rt.events.events() == []
    assert saves == []


def test_open_story_refused_when_no_environments(make_runtime) -> None:
    rt = make_runtime()
    rt.config.environments = []
    result = call(Tools(rt).open_story({"id": "s1", "title": "A", "environment": "cli"}))
    assert result == {"status": "refused", "reason": config_mod.NO_ENVIRONMENT.format(name="cli")}
    assert "s1" not in rt.state.stories


def test_duplicate_id_wins_over_bad_environment(make_runtime) -> None:
    t = Tools(make_runtime())
    call(t.open_story({"id": "s1", "title": "A"}))
    result = call(t.open_story({"id": "s1", "title": "A", "environment": "prose"}))
    assert result == {"status": "refused", "reason": "story s1 already exists"}


def test_schema_description_mentions_environment_rule() -> None:
    assert "[[environment]]" in str(SCHEMAS["open_story"])

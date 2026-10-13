"""The snapshot's ``recorded_model`` step key (s109, MF6, MF8)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agile_team import config as cfg

from .test_s96_snapshot import row, steps_for
from .test_snapshot import FIXTURE_TEXT, build, make_config


@pytest.fixture
def config(scratch: Path) -> cfg.Config:
    return make_config(scratch / "repo")


def ended(model: Any = None) -> list[dict]:
    data: dict[str, Any] = {"status": "done"}
    if model is not None:
        data["model"] = model
    return [row("step-start", 1.0, "architect"), row("step-end", 3.0, "architect", **data)]


def test_an_end_model_is_recorded_and_is_the_model(config: cfg.Config, scratch: Path) -> None:
    [step] = steps_for(config, scratch, ended("claude-opus-5-5"))
    assert step["recorded_model"] == "claude-opus-5-5"
    assert step["model"] == "claude-opus-5-5"


def test_an_end_without_a_model_records_none_but_falls_back(
    config: cfg.Config, scratch: Path
) -> None:
    [step] = steps_for(config, scratch, ended())
    roles = {r["name"]: r["model"] for r in build(config, scratch)["roles"]}
    assert step["recorded_model"] is None
    assert step["model"] == roles["architect"]


def test_a_running_step_records_no_model(config: cfg.Config, scratch: Path) -> None:
    [step] = steps_for(config, scratch, [row("step-start", 1.0, "architect")])
    assert step["recorded_model"] is None


def test_recorded_model_is_the_last_key(config: cfg.Config, scratch: Path) -> None:
    steps = steps_for(config, scratch, ended("claude-opus-5-5"))
    assert list(steps[0])[-2:] == ["slept", "recorded_model"]


def test_every_fixture_step_carries_recorded_model_last() -> None:
    steps = json.loads(FIXTURE_TEXT)["steps"]
    assert steps and all(list(s)[-1] == "recorded_model" for s in steps)


def test_the_fixture_holds_an_alias_step_and_an_exact_step_of_one_family() -> None:
    steps = json.loads(FIXTURE_TEXT)["steps"]
    models = {s["model"] for s in steps}
    assert "sonnet" in models and any(m.startswith("claude-sonnet") for m in models)

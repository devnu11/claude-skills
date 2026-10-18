"""s94: the pre-acceptance read, state and the view follow the story file (SF4-SF9)."""

import contextlib
import json
from functools import partial
from pathlib import Path

from agile_team import config as cfg
from agile_team import presentation, state, story_spec, system
from agile_team.config import Environment
from agile_team.gates import StoryState, StoryStatus
from agile_team.po_tools import Tools
from agile_team.presentation import Need
from agile_team.state import RunState

from .conftest import FakeQuery, present, write_story
from .test_dispatch import open_story, run
from .test_po_tools import call
from .test_snapshot import book_for, build, make_config, put_story

WEB = Environment("dashboard", "web", url="http://127.0.0.1:8765/")
CLI = Environment("cli", "package")


def wire(rt) -> None:
    """Give the runtime's checks the real story-file reader."""
    rt.pipeline.checks.story_spec = partial(story_spec.read, rt.config)


# ----- SF4: the file checks moved to the story CLI (s135) ---------------------


def test_config_no_longer_has_environment_refusal() -> None:
    assert not hasattr(cfg.Config, "environment_refusal")
    assert not hasattr(cfg, "UNKNOWN_ENVIRONMENT") and not hasattr(cfg, "NO_ENVIRONMENT")


# ----- SF5, SF7: the read before acceptance ------------------------------------


def test_bad_file_at_acceptance_holds_the_story_and_runs_nothing(make_runtime) -> None:
    q, prepared = FakeQuery(), []
    rt = make_runtime(q, prepare_fn=lambda *a: prepared.append(a))
    wire(rt)
    story = open_story(rt, "acceptance")
    present(rt.config)
    write_story(rt.config, "s1", "mars")
    report = run(rt, "customer-proxy", story="s1")
    assert report["gate"]["verdict"] == "hold"
    assert "the story file must be fixed before acceptance:" in report["reason"]
    assert ".team/stories/s1.md: AC AC1:" in report["reason"]
    assert story.hold == "gate_hold"
    assert q.calls == [] and prepared == [] and rt.ledger.total() == 0
    assert story.step == "acceptance" and story.status is StoryStatus.ACTIVE


def test_a_missing_file_at_acceptance_is_a_hold_not_a_fault(make_runtime) -> None:
    rt = make_runtime()
    wire(rt)
    story = StoryState("s1", "Add todo", "acceptance", sprint=1)
    rt.state.stories["s1"] = story
    report = run(rt, "customer-proxy", story="s1")
    assert report["gate"]["verdict"] == "hold" and story.hold
    assert "no story file" in report["reason"]


def test_bad_file_hold_comes_before_the_unpresented_return(make_runtime) -> None:
    rt = make_runtime()
    wire(rt)
    open_story(rt, "acceptance")  # nothing presented
    write_story(rt.config, "s1", "mars")
    assert run(rt, "customer-proxy", story="s1")["gate"]["verdict"] == "hold"
    write_story(rt.config, "s1", "cli")
    rt.state.stories["s1"].hold = None
    report = run(rt, "customer-proxy", story="s1")
    assert report["gate"]["verdict"] == "return" and "no presentation" in report["reason"]


def test_unwired_checks_read_every_file_as_clean(make_runtime) -> None:
    rt = make_runtime()
    open_story(rt, "acceptance")
    assert rt.pipeline.checks.story_spec("s1").refusal() is None


def test_unready_is_none_for_a_clean_file_and_a_hold_otherwise(make_runtime) -> None:
    rt = make_runtime()
    wire(rt)
    story = open_story(rt, "acceptance")
    write_story(rt.config, "s1", "cli")
    assert rt.pipeline.unready(story) is None
    write_story(rt.config, "s1", "mars")
    outcome = rt.pipeline.unready(story)
    assert outcome is not None and outcome.verdict.value == "hold"
    assert outcome.reason == story_spec.STORY_FILE_HOLD.format(
        refusal=story_spec.read(rt.config, "s1").refusal()
    )


def test_continue_story_then_a_fixed_file_runs_the_proxy(make_runtime) -> None:
    q = FakeQuery()
    rt = make_runtime(q)
    wire(rt)
    story = open_story(rt, "acceptance")
    present(rt.config)
    write_story(rt.config, "s1", "mars")
    assert run(rt, "customer-proxy", story="s1")["gate"]["verdict"] == "hold"
    write_story(rt.config, "s1", "cli")
    call(Tools(rt).continue_story({"story": "s1"}))
    assert story.hold is None
    report = run(rt, "customer-proxy", story="s1")
    assert len(q.calls) == 1 and report["gate"]["now_at"] == "land"


def test_an_edited_environment_between_e2e_and_acceptance_is_used(make_runtime) -> None:
    orders = []

    def fake_prepare(config, order):
        orders.append(order.environment.name)
        raise RuntimeError("stop here")

    rt = make_runtime(FakeQuery(), prepare_fn=fake_prepare)
    wire(rt)
    rt.config.environments = [CLI, WEB]
    open_story(rt, "acceptance")
    present(rt.config, environment="dashboard")
    write_story(rt.config, "s1", "cli")
    write_story(rt.config, "s1", "dashboard")  # the PO edited the file
    with contextlib.suppress(RuntimeError):
        run(rt, "customer-proxy", story="s1")
    assert orders == ["dashboard"]


def test_a_storyless_proxy_keeps_the_first_configured_environment(make_runtime) -> None:
    rt = make_runtime()
    wire(rt)
    rt.config.environments = [WEB, CLI]
    assert rt.config.environment(None) is WEB


# ----- SF6: no environment in state --------------------------------------------


def test_story_has_no_environment_field() -> None:
    assert "environment" not in StoryState.__dataclass_fields__
    assert cfg.OLD_ENVIRONMENT_NAME not in StoryState.__dataclass_fields__


def test_state_drops_environment_and_old_name_keys(scratch: Path) -> None:
    state.save(scratch, RunState(stories={"s1": StoryState("s1", "One", "design")}))
    path = scratch / "state.json"
    data = json.loads(system.read_text(path))
    data["stories"]["s1"]["environment"] = "cli"
    data["stories"]["s1"][cfg.OLD_ENVIRONMENT_NAME] = "web"
    system.write_text(path, json.dumps(data))
    loaded = state.load(scratch)
    assert loaded.stories["s1"].title == "One"
    state.save(scratch, loaded)
    kept = json.loads(system.read_text(path))["stories"]["s1"]
    assert "environment" not in kept and cfg.OLD_ENVIRONMENT_NAME not in kept


def test_state_dropped_keys_are_the_two_names() -> None:
    assert frozenset({"environment", cfg.OLD_ENVIRONMENT_NAME}) == state.STORY_DROPPED
    raw = {"id": "s1", "environment": "x", cfg.OLD_ENVIRONMENT_NAME: "y"}
    assert state._kept(raw) == {"id": "s1"}


# ----- SF8: the view -------------------------------------------------------------


def two_env_config(scratch: Path) -> cfg.Config:
    return make_config(
        scratch / "repo",
        environment=[
            {"name": "cli", "kind": "package"},
            {"name": "dashboard", "kind": "web", "url": "http://127.0.0.1:8765/"},
        ],
    )


def test_snapshot_environment_joins_the_files_environments(scratch: Path) -> None:
    config = two_env_config(scratch)
    write_story(config, "s1", "dashboard", "cli")
    put_story(config, StoryState("s1", "One", "design", sprint=1))
    (story,) = build(config, scratch)["stories"]
    assert story["environment"] == "cli, dashboard"
    assert book_for(config, scratch)  # the book still builds


def test_snapshot_environment_is_empty_for_a_bad_file(scratch: Path) -> None:
    config = two_env_config(scratch)
    write_story(config, "s1", "mars")
    put_story(config, StoryState("s1", "One", "design", sprint=1))
    (story,) = build(config, scratch)["stories"]
    assert story["environment"] == ""


def test_snapshot_environment_is_empty_without_a_file(scratch: Path) -> None:
    config = two_env_config(scratch)
    put_story(config, StoryState("s1", "One", "design", sprint=1))
    assert build(config, scratch)["stories"][0]["environment"] == ""


# ----- SF9 superseded by AE1: one showing per environment the file names ----------


def story_s1() -> StoryState:
    return StoryState("s1", "A story", "e2e", sprint=1)


def test_showings_follow_the_files_environments_in_config_order(configured: Path) -> None:
    config = cfg.load(configured)
    config.environments = [Environment("hw", "manual"), CLI]
    write_story(config, "s1", "cli", "hw")
    got = presentation.showings(config, "s1")
    assert [s.environment.name for s in got] == ["hw", "cli"]
    assert [presentation.recipe_of(s.environment).need for s in got] == [
        Need.GUIDE_ONLY,
        Need.WORKSPACE,
    ]


def test_a_story_without_a_usable_file_has_no_showings(configured: Path) -> None:
    config = cfg.load(configured)
    assert presentation.showings(config, "s1") == []
    write_story(config, "s1", "mars")
    assert presentation.showings(config, "s1") == []


def test_liveness_passes_when_the_file_has_problems(configured: Path) -> None:
    config = cfg.load(configured)
    trial = presentation.Trial(config, lambda *a: (_ for _ in ()).throw(AssertionError("no")))
    write_story(config, "s1", "mars")
    assert trial.liveness(story_s1()).verdict.value == "pass"


def test_each_showing_has_its_own_environments_seeds(configured: Path) -> None:
    config = cfg.load(configured)
    config.environments = [Environment("a", "web", url="http://x", seed="seedA"), CLI]
    write_story(config, "s1", "cli", "a")
    a, cli = presentation.showings(config, "s1")
    assert presentation.story_seeds(config, a).source == config.repo / "seedA"
    assert presentation.story_seeds(config, cli).source is None

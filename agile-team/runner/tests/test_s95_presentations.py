"""s95: one presentation per acceptance environment (AE1-AE4, AE10)."""

from pathlib import Path

import pytest
from agile_team import config as cfg
from agile_team import presentation, sandbox, system
from agile_team.config import Environment
from agile_team.gates import StoryState, Verdict

from .conftest import GUIDE_TEXT, write_story
from .fake_system import FakeSystem

ENVS = [
    Environment("cli", "package", seed=""),
    Environment("dashboard", "web", url="http://localhost:1", seed=""),
    Environment("review", "manual"),
]


@pytest.fixture
def config(configured: Path) -> cfg.Config:
    loaded = cfg.load(configured)
    loaded.environments = list(ENVS)
    write_story(loaded, "s4", "dashboard", "cli", "review", "cli")
    return loaded


def story() -> StoryState:
    return StoryState("s4", "A story", "e2e", sprint=1)


def root(config: cfg.Config) -> Path:
    return config.run_dir / "presentation" / "s4"


def build(
    config: cfg.Config, name: str, files: tuple[str, ...] = ("DEMO.md",), guide: bool = True
) -> Path:
    base = root(config) / name
    system.make_dirs(base / "workspace")
    if guide:
        system.write_text(base / "PRESENTATION.md", GUIDE_TEXT)
    for f in files:
        system.write_text(base / "workspace" / f, "x")
    return base


def build_all(config: cfg.Config) -> None:
    build(config, "cli")
    build(config, "dashboard")
    system.make_dirs(root(config) / "review")
    system.write_text(root(config) / "review" / "PRESENTATION.md", GUIDE_TEXT)


def test_showings_in_config_order(config: cfg.Config) -> None:
    got = presentation.showings(config, "s4")
    assert [(s.story, s.environment.name) for s in got] == [
        ("s4", "cli"),
        ("s4", "dashboard"),
        ("s4", "review"),
    ]


def test_no_showings_for_a_bad_file(config: cfg.Config) -> None:
    assert presentation.showings(config, "s99") == []


def test_dirs(config: cfg.Config) -> None:
    showing = presentation.Showing("s4", ENVS[0])
    assert presentation.source_dir(config, showing) == root(config) / "cli"
    assert presentation.workspace_of(config, showing) == root(config) / "cli" / "workspace"
    assert presentation.story_root(config, "s4") == root(config)


def test_lay_out_creates_every_showing(config: cfg.Config, fake: FakeSystem) -> None:
    assert presentation.lay_out(config, story()) == root(config)
    assert system.is_dir(root(config) / "cli" / "workspace")
    assert system.is_dir(root(config) / "dashboard" / "workspace")
    assert system.is_dir(root(config) / "review")
    assert not system.exists(root(config) / "review" / "workspace")
    inits = [c.cwd for c in fake.commands if "init" in c.argv]
    assert inits == [root(config) / "cli" / "workspace", root(config) / "dashboard" / "workspace"]


def test_lay_out_keeps_what_is_there(config: cfg.Config) -> None:
    base = build(config, "cli")
    presentation.lay_out(config, story())
    assert system.exists(base / "workspace" / "DEMO.md")


# ----- AE3 -------------------------------------------------------------------


def line(env: str, gap: str) -> str:
    return f"story s4 has no presentation for acceptance environment '{env}': {gap}"


def test_missing_is_none_when_all_complete(config: cfg.Config) -> None:
    build_all(config)
    assert presentation.missing(config, story()) is None


def test_missing_is_none_without_showings(config: cfg.Config) -> None:
    assert presentation.missing(config, StoryState("s99", "x", "e2e")) is None


def test_missing_lists_every_gap_one_line_each(config: cfg.Config) -> None:
    build(config, "cli", guide=False)
    system.make_dirs(root(config) / "review")
    got = presentation.missing(config, story())
    p = ".team/run/presentation/s4"
    assert got.split("\n") == [
        line(
            "cli", f"{p}/cli/PRESENTATION.md is missing or empty; write the customer's guide there"
        ),
        line(
            "dashboard",
            f"{p}/dashboard/PRESENTATION.md is missing or empty; write the customer's guide there",
        ),
        line(
            "review",
            f"{p}/review/PRESENTATION.md is missing or empty; write the customer's guide there",
        ),
    ]


def test_no_workspace(config: cfg.Config) -> None:
    build_all(config)
    system.remove_tree(root(config) / "dashboard" / "workspace")
    got = presentation.missing(config, story())
    assert got == line(
        "dashboard",
        ".team/run/presentation/s4/dashboard/workspace is missing; "
        "put the demo or evidence files the customer tries there",
    )


def test_empty_workspace(config: cfg.Config) -> None:
    build_all(config)
    system.remove(root(config) / "cli" / "workspace" / "DEMO.md")
    got = presentation.missing(config, story())
    assert got == line(
        "cli",
        ".team/run/presentation/s4/cli/workspace is empty; "
        "put the demo or evidence files the customer tries there",
    )


def test_hollow_workspace_names_git_and_a_file_to_add(config: cfg.Config) -> None:
    build_all(config)
    system.remove(root(config) / "cli" / "workspace" / "DEMO.md")
    system.make_dirs(root(config) / "cli" / "workspace" / ".git")
    got = presentation.missing(config, story())
    assert got == line(
        "cli",
        ".team/run/presentation/s4/cli/workspace holds only .git; add the demo or evidence "
        "files themselves, for example .team/run/presentation/s4/cli/workspace/DEMO.md",
    )


def test_hollow_workspace_lists_seeds_after_git(config: cfg.Config) -> None:
    config.environments[0] = Environment("cli", "package", seed="seeds")
    system.make_dirs(config.repo / "seeds")
    system.write_text(config.repo / "seeds" / "b.txt", "b")
    system.write_text(config.repo / "seeds" / "a.txt", "a")
    build_all(config)
    ws = root(config) / "cli" / "workspace"
    system.remove(ws / "DEMO.md")
    system.make_dirs(ws / ".git")
    system.write_text(ws / "a.txt", "a")
    system.write_text(ws / "b.txt", "b")
    assert "holds only .git, a.txt, b.txt;" in presentation.missing(config, story())


def test_manual_needs_only_the_guide(config: cfg.Config) -> None:
    build_all(config)
    assert presentation.missing(config, story()) is None


# ----- AE4 -------------------------------------------------------------------


class Prep:
    def __init__(self, fail_on: str | None = None) -> None:
        self.orders: list[sandbox.Order] = []
        self.fail_on = fail_on

    def __call__(self, config: cfg.Config, order: sandbox.Order) -> sandbox.Prepared:
        self.orders.append(order)
        if order.environment.name == self.fail_on:
            raise sandbox.NotUp("down")
        return FakePrepared()


class FakePrepared:
    def stop(self) -> str:
        return ""

    def probe_url(self) -> str:
        return "http://localhost:1/"


def test_liveness_never_prepares_files_showings(config: cfg.Config) -> None:
    config.environments = [ENVS[0], ENVS[2]]
    write_story(config, "s4", "cli", "review")
    prep = Prep()
    outcome = presentation.Trial(config, prep).liveness(story())
    assert prep.orders == [] and outcome.verdict is Verdict.PASS


def test_liveness_tries_each_service_in_order(config: cfg.Config) -> None:
    config.environments = [
        Environment("a", "web", url="http://x", seed=""),
        Environment("b", "web", url="http://y", seed=""),
    ]
    write_story(config, "s4", "b", "a")
    prep = Prep()
    outcome = presentation.Trial(config, prep).liveness(story())
    assert [o.environment.name for o in prep.orders] == ["a", "b"]
    assert outcome.verdict is Verdict.PASS and outcome.reason.count("answered") == 2


def test_liveness_first_failure_is_the_outcome(config: cfg.Config) -> None:
    config.environments = [
        Environment("a", "web", url="http://x", seed=""),
        Environment("b", "web", url="http://y", seed=""),
    ]
    write_story(config, "s4", "a", "b")
    prep = Prep(fail_on="a")
    outcome = presentation.Trial(config, prep).liveness(story())
    assert outcome.verdict is Verdict.BOUNCE and "not up" in outcome.reason
    assert [o.environment.name for o in prep.orders] == ["a"]


# ----- AE10 ------------------------------------------------------------------


def test_layout_section(config: cfg.Config) -> None:
    text = presentation.layout_section(config, "s4")
    assert text.startswith("## Presentations to build\n")
    assert "- cli (package): .team/run/presentation/s4/cli/ (AC2, AC4)" in text
    assert "- dashboard (web): .team/run/presentation/s4/dashboard/ (AC1)" in text
    assert "- review (manual): .team/run/presentation/s4/review/ (AC3)" in text


def test_layout_section_empty_without_showings(config: cfg.Config) -> None:
    assert presentation.layout_section(config, "s99") == ""

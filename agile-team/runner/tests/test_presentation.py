"""The team's presentation of a story to the Customer Proxy (rules E1, E2, E5, E7, E8)."""

from pathlib import Path

import pytest
from agile_team import config as cfg
from agile_team import presentation, sandbox, system
from agile_team.config import Environment
from agile_team.gates import StoryState
from agile_team.presentation import Need

from .conftest import GUIDE_TEXT, present, write_story
from .fake_system import FAKE_ROOT, FakeSystem


def _state(story_id: str) -> StoryState:
    return StoryState(story_id, "A story", "e2e", sprint=1)


def story_of(config: cfg.Config, story_id: str = "s4") -> StoryState:
    """A story whose file names the first configured environment (if any)."""
    names = [e.name for e in config.environments[:1]]
    if names and "/" not in story_id:
        write_story(config, story_id, *names)
    return _state(story_id)


def story_on(config: cfg.Config, environment: str) -> StoryState:
    """Story s4 whose file names ``environment``."""
    write_story(config, "s4", environment)
    return _state("s4")


@pytest.fixture
def config(configured: Path) -> cfg.Config:
    return cfg.load(configured)


# ----- E1 / the table -------------------------------------------------------


def test_names_and_source_dir(config: cfg.Config) -> None:
    assert (presentation.PRESENTATION_DIR, presentation.GUIDE, presentation.WORKSPACE) == (
        "presentation",
        "PRESENTATION.md",
        "workspace",
    )
    showing = presentation.Showing("s4", Environment("cli", "package"))
    assert presentation.story_root(config, "s4") == config.run_dir / "presentation" / "s4"
    assert presentation.source_dir(config, showing) == config.run_dir / "presentation/s4/cli"


def test_need_values() -> None:
    assert (Need.WORKSPACE.value, Need.GUIDE_ONLY.value) == ("workspace", "guide-only")


@pytest.mark.parametrize(
    ("kind", "need"),
    [
        ("package", Need.WORKSPACE),
        ("script", Need.WORKSPACE),
        ("web", Need.WORKSPACE),
        ("library", Need.WORKSPACE),
        ("harness", Need.WORKSPACE),
        ("manual", Need.GUIDE_ONLY),
    ],
)
def test_presentation_table(kind: str, need: Need) -> None:
    assert presentation.PRESENTATIONS[kind].need is need


def test_table_covers_every_environment_kind() -> None:
    assert set(presentation.PRESENTATIONS) == set(sandbox.ENVIRONMENT_KINDS)


def test_need_of_an_environment_follows_its_kind() -> None:
    assert presentation.recipe_of(Environment("cli", "package")).need is Need.WORKSPACE
    assert presentation.recipe_of(Environment("hw", "manual")).need is Need.GUIDE_ONLY


def test_a_story_that_names_no_environment_has_no_showings(config: cfg.Config) -> None:
    config.environments = []
    assert presentation.showings(config, "s4") == []


# ----- E5 -------------------------------------------------------------------

HEAD = "story s4 has no presentation for acceptance environment '{env}': "
BASE = ".team/run/presentation/s4/{env}"
GUIDE_REASON = HEAD.format(env="cli") + (
    BASE.format(env="cli")
    + "/PRESENTATION.md is missing or empty; write the customer's guide there"
)
TRIES = "put the demo or evidence files the customer tries there"
NO_WORKSPACE_REASON = (
    HEAD.format(env="cli") + BASE.format(env="cli") + f"/workspace is missing; {TRIES}"
)
EMPTY_REASON = HEAD.format(env="cli") + BASE.format(env="cli") + f"/workspace is empty; {TRIES}"
HOLLOW_REASON = (
    HEAD.format(env="cli")
    + BASE.format(env="cli")
    + "/workspace holds only {held}; add the demo or evidence files themselves, for example "
    + BASE.format(env="cli")
    + "/workspace/DEMO.md"
)


def cli_dir(config: cfg.Config) -> Path:
    return presentation.source_dir(config, presentation.showings(config, "s4")[0])


def test_missing_when_there_is_no_dir(config: cfg.Config) -> None:
    assert presentation.missing(config, story_of(config)) == GUIDE_REASON


@pytest.mark.parametrize("text", ["", "   \n\t\n"])
def test_missing_when_the_guide_is_blank(config: cfg.Config, text: str) -> None:
    source = present(config, "s4")
    system.write_text(source / "PRESENTATION.md", text)
    assert presentation.missing(config, story_of(config)) == GUIDE_REASON


def test_guide_is_checked_before_the_workspace(config: cfg.Config) -> None:
    story_of(config)
    system.make_dirs(cli_dir(config) / "workspace")
    assert presentation.missing(config, story_of(config)) == GUIDE_REASON


def test_missing_when_there_is_a_guide_but_no_workspace(config: cfg.Config) -> None:
    present(config, "s4", workspace=False)
    assert presentation.missing(config, story_of(config)) == NO_WORKSPACE_REASON


def test_missing_when_the_workspace_is_empty(config: cfg.Config) -> None:
    system.make_dirs(present(config, "s4", workspace=False) / "workspace")
    assert presentation.missing(config, story_of(config)) == EMPTY_REASON


def test_workspace_holding_only_git_is_incomplete(config: cfg.Config) -> None:
    source = present(config, "s4", workspace=False)
    system.make_dirs(source / "workspace" / ".git")
    assert presentation.missing(config, story_of(config)) == HOLLOW_REASON.format(held=".git")


def test_workspace_with_a_file_beside_git_is_complete(config: cfg.Config) -> None:
    source = present(config, "s4")
    system.make_dirs(source / "workspace" / ".git")
    assert presentation.missing(config, story_of(config)) is None


def test_complete_presentation(config: cfg.Config) -> None:
    present(config, "s4")
    assert presentation.missing(config, story_of(config)) is None


def test_manual_needs_only_the_guide(config: cfg.Config) -> None:
    config.environments = [Environment("hw", "manual")]
    present(config, "s4", workspace=False)
    assert presentation.missing(config, story_on(config, "hw")) is None


def test_a_story_without_showings_has_nothing_missing(config: cfg.Config) -> None:
    assert presentation.missing(config, StoryState("s4", "A story", "e2e", sprint=1)) is None


def test_each_story_has_its_own_presentation(config: cfg.Config) -> None:
    present(config, "s5")
    assert presentation.missing(config, story_of(config, "s4")) == GUIDE_REASON
    assert presentation.missing(config, story_of(config, "s5")) is None


# ----- E2 -------------------------------------------------------------------


def test_lay_out_keeps_the_old_presentation(config: cfg.Config) -> None:
    source = present(config, "s4")
    system.write_text(source / "stale.txt", "old")
    assert presentation.lay_out(config, story_of(config)) == presentation.story_root(config, "s4")
    assert system.exists(source / "stale.txt")
    assert system.exists(source / "workspace" / "todo.txt")
    assert system.exists(source / "PRESENTATION.md")


def test_lay_out_gives_a_package_its_own_git_workspace(
    config: cfg.Config, fake: FakeSystem
) -> None:
    presentation.lay_out(config, story_of(config))
    workspace = cli_dir(config) / "workspace"
    assert system.is_dir(workspace)
    (init,) = [c for c in fake.commands if "init" in c.argv]
    assert (init.argv[-2:], init.cwd) == (("init", "-q"), workspace)


def test_lay_out_leaves_the_empty_workspace_incomplete(config: cfg.Config) -> None:
    presentation.lay_out(config, story_of(config))
    system.write_text(cli_dir(config) / "PRESENTATION.md", GUIDE_TEXT)
    assert presentation.missing(config, story_of(config)) == EMPTY_REASON


def test_lay_out_manual_has_no_workspace(config: cfg.Config) -> None:
    config.environments = [Environment("hw", "manual")]
    root = presentation.lay_out(config, story_on(config, "hw"))
    assert system.list_dir(root / "hw") == []


@pytest.mark.parametrize("bad", ["../x", "..", "S1", "a/b", ""])
def test_lay_out_refuses_an_unsafe_id_before_wiping(config: cfg.Config, bad: str) -> None:
    outside = config.run_dir / "x"
    system.make_dirs(outside)
    system.write_text(outside / "keep.txt", "keep")
    survivor = present(config, "s4")
    with pytest.raises(sandbox.SandboxError, match="must match"):
        presentation.lay_out(config, story_of(config, bad))
    assert system.read_text(outside / "keep.txt") == "keep"
    assert system.exists(survivor / "PRESENTATION.md")


# ----- E7 -------------------------------------------------------------------


def test_copy_into_copies_the_tree(config: cfg.Config) -> None:
    source = present(config, "s4")
    root = FAKE_ROOT / "box"
    system.make_dirs(root)
    copied = presentation.copy_into(source, root)
    assert copied == root / "presentation"
    assert system.read_text(copied / "PRESENTATION.md") == GUIDE_TEXT
    assert system.read_text(copied / "workspace" / "todo.txt") == "milk\n"


# ----- E8 -------------------------------------------------------------------


def test_prompt_section_is_empty_without_a_presentation() -> None:
    assert presentation.prompt_section(None) == ""


def test_prompt_section_names_the_path_the_rule_and_quotes_the_guide() -> None:
    copied = FAKE_ROOT / "box" / "presentation"
    system.make_dirs(copied)
    system.write_text(copied / "PRESENTATION.md", GUIDE_TEXT)
    text = presentation.prompt_section(copied)
    assert "## What the team presents" in text
    assert str(copied) in text
    assert "workspace" in text
    assert "changes_requested" in text and "integration-tester" in text
    assert GUIDE_TEXT.strip() in text


# ----- s105: seeds ----------------------------------------------------------


def seeded_config(config: cfg.Config, *, seed: str = "seedsrc") -> None:
    system.make_dirs(config.repo / "seedsrc")
    system.write_text(config.repo / "seedsrc" / ".agile-team.toml", "[dashboard]\n")
    config.environments = [Environment("cli", "package", seed=seed)]


def test_lay_out_plants_the_seed_in_the_source_workspace(config: cfg.Config) -> None:
    seeded_config(config)
    presentation.lay_out(config, story_of(config))
    seeded = cli_dir(config) / "workspace" / ".agile-team.toml"
    assert system.read_text(seeded) == "[dashboard]\n"


def test_lay_out_keeps_the_testers_own_config(config: cfg.Config) -> None:
    seeded_config(config)
    story_of(config)
    source = cli_dir(config)
    system.make_dirs(source / "workspace" / ".git")
    system.write_text(source / "workspace" / ".agile-team.toml", "mine\n")
    presentation.lay_out(config, story_of(config))
    assert system.read_text(source / "workspace" / ".agile-team.toml") == "mine\n"


def test_lay_out_plants_nothing_without_a_seed(config: cfg.Config) -> None:
    seeded_config(config, seed="")
    presentation.lay_out(config, story_of(config))
    assert not system.exists(cli_dir(config) / "workspace" / ".agile-team.toml")


def test_lay_out_manual_plants_no_seed(config: cfg.Config) -> None:
    config.environments = [Environment("hw", "manual", seed="seedsrc")]
    root = presentation.lay_out(config, story_on(config, "hw"))
    assert system.list_dir(root / "hw") == []


def test_workspace_holding_only_git_and_the_seed_is_incomplete(config: cfg.Config) -> None:
    seeded_config(config)
    source = present(config, "s4", workspace=False)
    presentation.lay_out(config, story_of(config))
    assert system.exists(source / "workspace" / ".agile-team.toml")
    held = ".agile-team.toml"  # the fake git init leaves no .git
    assert presentation.missing(config, story_of(config)) == HOLLOW_REASON.format(held=held)


def test_workspace_with_another_file_beside_the_seed_is_complete(config: cfg.Config) -> None:
    seeded_config(config)
    source = present(config, "s4", workspace=False)
    presentation.lay_out(config, story_of(config))
    system.write_text(source / "workspace" / "state.json", "{}")
    assert presentation.missing(config, story_of(config)) is None


def test_story_seeds_point_at_the_environment_seed_and_the_workspace(config: cfg.Config) -> None:
    seeded_config(config)
    story_of(config)
    showing = presentation.showings(config, "s4")[0]
    s = presentation.story_seeds(config, showing)
    assert s.source == config.repo / "seedsrc"
    assert s.workspace == presentation.workspace_of(config, showing)

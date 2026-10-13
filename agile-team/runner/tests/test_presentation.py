"""The team's presentation of a story to the Customer Proxy (rules E1, E2, E5, E7, E8)."""

from pathlib import Path

import pytest
from agile_team import config as cfg
from agile_team import presentation, sandbox, system
from agile_team.config import Delivery
from agile_team.gates import StoryState
from agile_team.presentation import Need

from .conftest import GUIDE_TEXT, present
from .fake_system import FAKE_ROOT, FakeSystem


def story_of(story_id: str = "s4", delivery: str | None = None) -> StoryState:
    return StoryState(story_id, "A story", "e2e", sprint=1, delivery=delivery)


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
    assert presentation.source_dir(config, "s4") == config.run_dir / "presentation" / "s4"


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


def test_table_covers_every_delivery_kind() -> None:
    assert set(presentation.PRESENTATIONS) == set(sandbox.DELIVERY_KINDS)


def test_need_of_named_default_and_missing_delivery(config: cfg.Config) -> None:
    config.deliveries = [Delivery("cli", "package"), Delivery("hw", "manual")]
    assert presentation.recipe_of(config, story_of()).need is Need.WORKSPACE
    assert presentation.recipe_of(config, story_of(delivery="hw")).need is Need.GUIDE_ONLY
    config.deliveries = []
    assert presentation.recipe_of(config, story_of()).need is Need.GUIDE_ONLY


# ----- E5 -------------------------------------------------------------------

GUIDE_REASON = (
    "story s4 has no presentation: .team/run/presentation/s4/PRESENTATION.md is missing or empty"
)
WORKSPACE_REASON = (
    "story s4 has no presentation: .team/run/presentation/s4/workspace is missing or empty"
)


def test_missing_when_there_is_no_dir(config: cfg.Config) -> None:
    assert presentation.missing(config, story_of()) == GUIDE_REASON


@pytest.mark.parametrize("text", ["", "   \n\t\n"])
def test_missing_when_the_guide_is_blank(config: cfg.Config, text: str) -> None:
    source = present(config, "s4")
    system.write_text(source / "PRESENTATION.md", text)
    assert presentation.missing(config, story_of()) == GUIDE_REASON


def test_guide_is_checked_before_the_workspace(config: cfg.Config) -> None:
    system.make_dirs(presentation.source_dir(config, "s4") / "workspace")
    assert presentation.missing(config, story_of()) == GUIDE_REASON


def test_missing_when_there_is_a_guide_but_no_workspace(config: cfg.Config) -> None:
    present(config, "s4", workspace=False)
    assert presentation.missing(config, story_of()) == WORKSPACE_REASON


def test_missing_when_the_workspace_is_empty(config: cfg.Config) -> None:
    system.make_dirs(present(config, "s4", workspace=False) / "workspace")
    assert presentation.missing(config, story_of()) == WORKSPACE_REASON


def test_workspace_holding_only_git_is_incomplete(config: cfg.Config) -> None:
    source = present(config, "s4", workspace=False)
    system.make_dirs(source / "workspace" / ".git")
    assert presentation.missing(config, story_of()) == WORKSPACE_REASON


def test_workspace_with_a_file_beside_git_is_complete(config: cfg.Config) -> None:
    source = present(config, "s4")
    system.make_dirs(source / "workspace" / ".git")
    assert presentation.missing(config, story_of()) is None


def test_complete_presentation(config: cfg.Config) -> None:
    present(config, "s4")
    assert presentation.missing(config, story_of()) is None


def test_manual_needs_only_the_guide(config: cfg.Config) -> None:
    config.deliveries = [Delivery("hw", "manual")]
    present(config, "s4", workspace=False)
    assert presentation.missing(config, story_of(delivery="hw")) is None


def test_no_delivery_needs_only_the_guide(config: cfg.Config) -> None:
    config.deliveries = []
    present(config, "s4", workspace=False)
    assert presentation.missing(config, story_of()) is None


def test_each_story_has_its_own_presentation(config: cfg.Config) -> None:
    present(config, "s5")
    assert presentation.missing(config, story_of("s4")) == GUIDE_REASON
    assert presentation.missing(config, story_of("s5")) is None


# ----- E2 -------------------------------------------------------------------


def test_lay_out_keeps_the_old_presentation(config: cfg.Config) -> None:
    source = present(config, "s4")
    system.write_text(source / "stale.txt", "old")
    assert presentation.lay_out(config, story_of()) == source
    assert system.exists(source / "stale.txt")
    assert system.exists(source / "workspace" / "todo.txt")
    assert system.exists(source / "PRESENTATION.md")


def test_lay_out_gives_a_package_its_own_git_workspace(
    config: cfg.Config, fake: FakeSystem
) -> None:
    source = presentation.lay_out(config, story_of())
    workspace = source / "workspace"
    assert system.is_dir(workspace)
    (init,) = [c for c in fake.commands if "init" in c.argv]
    assert (init.argv[-2:], init.cwd) == (("init", "-q"), workspace)


def test_lay_out_leaves_the_empty_workspace_incomplete(config: cfg.Config) -> None:
    source = presentation.lay_out(config, story_of())
    system.write_text(source / "PRESENTATION.md", GUIDE_TEXT)
    assert presentation.missing(config, story_of()) == WORKSPACE_REASON


def test_lay_out_manual_has_no_workspace(config: cfg.Config) -> None:
    config.deliveries = [Delivery("hw", "manual")]
    source = presentation.lay_out(config, story_of(delivery="hw"))
    assert system.is_dir(source) and system.list_dir(source) == []


@pytest.mark.parametrize("bad", ["../x", "..", "S1", "a/b", ""])
def test_lay_out_refuses_an_unsafe_id_before_wiping(config: cfg.Config, bad: str) -> None:
    outside = config.run_dir / "x"
    system.make_dirs(outside)
    system.write_text(outside / "keep.txt", "keep")
    survivor = present(config, "s4")
    with pytest.raises(sandbox.SandboxError, match="must match"):
        presentation.lay_out(config, story_of(bad))
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

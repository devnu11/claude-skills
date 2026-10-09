"""The team's presentation of a story to the Customer Proxy (rules E1, E2, E5, E7, E8)."""

import os
import subprocess
from pathlib import Path

import pytest
from agile_team import config as cfg
from agile_team import presentation, sandbox
from agile_team.config import Delivery
from agile_team.gates import StoryState
from agile_team.presentation import Need

from .conftest import GUIDE_TEXT, present


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
    assert presentation.PRESENTATIONS[kind] is need


def test_table_covers_every_delivery_kind() -> None:
    assert set(presentation.PRESENTATIONS) == set(sandbox.DELIVERY_KINDS)


def test_need_of_named_default_and_missing_delivery(config: cfg.Config) -> None:
    config.deliveries = [Delivery("cli", "package"), Delivery("hw", "manual")]
    assert presentation.need_of(config, story_of()) is Need.WORKSPACE
    assert presentation.need_of(config, story_of(delivery="hw")) is Need.GUIDE_ONLY
    config.deliveries = []
    assert presentation.need_of(config, story_of()) is Need.GUIDE_ONLY


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
    (source / "PRESENTATION.md").write_text(text)
    assert presentation.missing(config, story_of()) == GUIDE_REASON


def test_guide_is_checked_before_the_workspace(config: cfg.Config) -> None:
    (presentation.source_dir(config, "s4") / "workspace").mkdir(parents=True)
    assert presentation.missing(config, story_of()) == GUIDE_REASON


def test_missing_when_there_is_a_guide_but_no_workspace(config: cfg.Config) -> None:
    present(config, "s4", workspace=False)
    assert presentation.missing(config, story_of()) == WORKSPACE_REASON


def test_missing_when_the_workspace_is_empty(config: cfg.Config) -> None:
    (present(config, "s4", workspace=False) / "workspace").mkdir()
    assert presentation.missing(config, story_of()) == WORKSPACE_REASON


def test_workspace_holding_only_git_is_incomplete(config: cfg.Config) -> None:
    source = present(config, "s4", workspace=False)
    (source / "workspace" / ".git").mkdir(parents=True)
    assert presentation.missing(config, story_of()) == WORKSPACE_REASON


def test_workspace_with_a_file_beside_git_is_complete(config: cfg.Config) -> None:
    source = present(config, "s4")
    (source / "workspace" / ".git").mkdir()
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


def test_lay_out_wipes_the_old_presentation(config: cfg.Config) -> None:
    source = present(config, "s4")
    (source / "stale.txt").write_text("old")
    assert presentation.lay_out(config, story_of()) == source
    assert sorted(p.name for p in source.iterdir()) == ["workspace"]
    assert not (source / "workspace" / "todo.txt").exists()


def test_lay_out_gives_a_package_its_own_git_workspace(config: cfg.Config) -> None:
    source = presentation.lay_out(config, story_of())
    workspace = source / "workspace"
    assert (workspace / ".git").exists()
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], cwd=workspace, capture_output=True, text=True
    ).stdout.strip()
    assert Path(top).resolve() == workspace.resolve()


def test_lay_out_leaves_the_empty_workspace_incomplete(config: cfg.Config) -> None:
    source = presentation.lay_out(config, story_of())
    (source / "PRESENTATION.md").write_text(GUIDE_TEXT)
    assert presentation.missing(config, story_of()) == WORKSPACE_REASON


def test_lay_out_manual_has_no_workspace(config: cfg.Config) -> None:
    config.deliveries = [Delivery("hw", "manual")]
    source = presentation.lay_out(config, story_of(delivery="hw"))
    assert source.is_dir() and list(source.iterdir()) == []


@pytest.mark.parametrize("bad", ["../x", "..", "S1", "a/b", ""])
def test_lay_out_refuses_an_unsafe_id_before_wiping(config: cfg.Config, bad: str) -> None:
    outside = config.run_dir / "x"
    outside.mkdir(parents=True)
    (outside / "keep.txt").write_text("keep")
    survivor = present(config, "s4")
    with pytest.raises(sandbox.SandboxError, match="must match"):
        presentation.lay_out(config, story_of(bad))
    assert (outside / "keep.txt").read_text() == "keep"
    assert (survivor / "PRESENTATION.md").exists()


# ----- E7 -------------------------------------------------------------------


def test_copy_into_copies_the_tree(config: cfg.Config, tmp_path: Path) -> None:
    source = present(config, "s4")
    root = tmp_path / "box"
    root.mkdir()
    copied = presentation.copy_into(source, root)
    assert copied == root / "presentation"
    assert (copied / "PRESENTATION.md").read_text() == GUIDE_TEXT
    assert (copied / "workspace" / "todo.txt").read_text() == "milk\n"


def test_copy_into_keeps_symlinks_as_links(config: cfg.Config, tmp_path: Path) -> None:
    source = present(config, "s4")
    target = tmp_path / "secret.py"
    target.write_text("secret")
    os.symlink(target, source / "link.py")
    copied = presentation.copy_into(source, tmp_path)
    assert (copied / "link.py").is_symlink()
    assert os.readlink(copied / "link.py") == str(target)


# ----- E8 -------------------------------------------------------------------


def test_prompt_section_is_empty_without_a_presentation() -> None:
    assert presentation.prompt_section(None) == ""


def test_prompt_section_names_the_path_the_rule_and_quotes_the_guide(tmp_path: Path) -> None:
    copied = tmp_path / "presentation"
    copied.mkdir()
    (copied / "PRESENTATION.md").write_text(GUIDE_TEXT)
    text = presentation.prompt_section(copied)
    assert "## What the team presents" in text
    assert str(copied) in text
    assert "workspace" in text
    assert "changes_requested" in text and "integration-tester" in text
    assert GUIDE_TEXT.strip() in text

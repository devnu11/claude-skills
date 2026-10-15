"""s135 F4: ``story amend`` refusals for unreadable drafts, finished and unknown targets."""

from __future__ import annotations

from pathlib import Path

from agile_team.gates import StoryStatus

from .test_s135_story_cli import (
    DRAFT,
    amending,
    put,
    queued,
    refusal,
    run,
)

MISSING = "missing.md"


def test_amend_of_an_unknown_story_with_a_missing_file_gives_both_lines(
    configured: Path, capsys
) -> None:
    assert run(configured, "amend", "s999", MISSING, "--approved-by", "none") == 1
    lines = refusal(capsys)
    assert any(line.startswith("cannot read") and MISSING in line for line in lines)
    assert "no story 's999'" in lines
    assert queued(configured) == []


def test_amend_of_a_finished_story_with_a_missing_file_gives_both_lines(
    configured: Path, capsys
) -> None:
    amending(configured, StoryStatus.DONE)
    assert run(configured, "amend", "s1", MISSING, "--approved-by", "none") == 1
    lines = refusal(capsys)
    assert any(line.startswith("cannot read") for line in lines)
    assert "s1 is done; story amend changes open stories only" in lines
    assert queued(configured) == []


def test_the_unknown_target_line_appears_once_for_a_readable_draft(
    configured: Path, capsys
) -> None:
    assert run(configured, "amend", "s999", put(configured, DRAFT), "--approved-by", "none") == 1
    assert refusal(capsys).count("no story 's999'") == 1
    assert queued(configured) == []

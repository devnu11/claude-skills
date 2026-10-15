"""s138: hold and refusal texts do not tell a role to edit a story file."""

import re

import pytest
from agile_team import cli, story_spec, suite_runs

ROLE_TEXTS = [story_spec.STORY_FILE_HOLD, suite_runs.BAD_SUITE_RUNS]
FIX_FILE = r"(?i)fix (the |its )?(story )?(file|frontmatter)|fix depends_on"


def test_exact_texts() -> None:
    assert story_spec.STORY_FILE_HOLD == (
        "the story file must be fixed before acceptance:\n{refusal}\n"
        "Only the runner writes story files. If the config lost the environment, route the "
        "fix to devops and continue_story once it is in; if the ACs are wrong, ask the human "
        "with ask_user, and the liaison sends new ACs with story amend"
    )
    assert cli.START_REFUSED == (
        "story files: {refusal}; story amend cannot change depends_on, so the human fixes it: "
        "edit depends_on in the story's file in {folder}, git commit it, then agile-team start "
        "again (agile-team accept-checkout first if start halts on the moved checkout)"
    )
    assert suite_runs.BAD_SUITE_RUNS == (
        "story {story}'s suite_runs must be a whole number from 1 to {most}, not {value!r}; "
        "only the runner writes story files: ask the human with ask_user for a valid suite_runs"
    )


@pytest.mark.parametrize("text", ROLE_TEXTS)
def test_role_texts_do_not_say_edit(text: str) -> None:
    assert re.search(r"(?i)\bedit\b", text) is None
    assert re.search(FIX_FILE, text) is None
    assert re.search(r"(?i)only the runner writes story files", text)
    assert "ask_user" in text


def test_hold_names_who_acts() -> None:
    assert "continue_story" in story_spec.STORY_FILE_HOLD
    assert "story amend" in story_spec.STORY_FILE_HOLD


def test_start_refusal_gives_only_the_humans_edit() -> None:
    text = cli.START_REFUSED
    assert "fix depends_on in" not in text
    assert "the human fixes it: edit depends_on" in text
    for name in ("story amend", "git commit", "agile-team start", "agile-team accept-checkout"):
        assert name in text


def test_placeholders_format_away() -> None:
    texts = [
        story_spec.STORY_FILE_HOLD.format(refusal="r"),
        cli.START_REFUSED.format(refusal="r", folder="f"),
        suite_runs.BAD_SUITE_RUNS.format(story="s1", most=3, value=0),
    ]
    assert all("{" not in t for t in texts)

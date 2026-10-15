"""s136: the docs and role files say the liaison writes stories (AC1-AC3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from agile_team import cli, roles, story_drafts, system
from agile_team.roles import RoleBook

SKILL_DIR = Path(cli.__file__).parents[2]
PATHS = {
    "role": roles.BUILTIN_DIR / "product-owner.md",
    "devops": roles.BUILTIN_DIR / "devops.md",
    "skill": SKILL_DIR / "SKILL.md",
    "protocol": SKILL_DIR / "reference" / "protocol.md",
    "liaison": SKILL_DIR / "reference" / "liaison-template.md",
    "readme": SKILL_DIR.parent / "README.md",
}
DOCS = ["skill", "protocol"]
DOC_TOKENS = [
    "story new",
    "story amend",
    "--approved-by",
    "created story to",
    "Human-involvement:",
    "story-opened",
    "story-amended",
    "story-refused",
    "story-request",
]


def flat(name: str) -> str:
    """A file's text with every run of whitespace collapsed to one space."""
    return " ".join(system.read_text(PATHS[name]).split())


def between(text: str, start: str, end: str) -> str:
    """The text from ``start`` up to ``end``."""
    head = text.index(start)
    return text[head : text.index(end, head)]


# ----- AC1: the PO role file ---------------------------------------------------------


def test_the_po_file_has_no_open_story() -> None:
    assert "open_story" not in flat("role")


@pytest.mark.parametrize(
    "phrase",
    [
        "request_story(summary, evidence)",
        "You never write a story",
        "You never write or edit a story file",
    ],
)
def test_the_po_file_says_it_schedules_and_requests(phrase: str) -> None:
    assert phrase in flat("role")


def test_the_po_description_says_it_schedules(repo: Path) -> None:
    description = RoleBook.for_repo(repo, {}).resolve("product-owner").description
    assert description.startswith("Schedules the stories")
    assert "Writes the stories" not in description
    assert "Writes the stories" not in flat("role")


@pytest.mark.parametrize(
    ("start", "end"),
    [("**ci_failed**", "**ci_infra**"), ("**main_broken**", "**ci_pending**")],
)
def test_the_ci_bullets_request_a_story(start: str, end: str) -> None:
    bullet = between(flat("role"), start, end)
    assert "request_story" in bullet
    assert "open_story" not in bullet


def test_devops_no_longer_says_the_po_opens_one() -> None:
    assert "the PO opens one" not in flat("devops")


# ----- AC2: the liaison template ----------------------------------------------------


@pytest.mark.parametrize(
    "phrase",
    [
        "agile-team story new",
        "agile-team story amend",
        "--approved-by",
        "story-request",
        "## Writing stories",
    ],
)
def test_the_liaison_template_describes_writing_stories(phrase: str) -> None:
    assert phrase in flat("liaison")


# ----- AC3: SKILL.md and protocol.md ------------------------------------------------


@pytest.mark.parametrize("name", DOCS)
@pytest.mark.parametrize("token", DOC_TOKENS)
def test_each_doc_names_the_story_commands_and_events(name: str, token: str) -> None:
    assert token in flat(name)


@pytest.mark.parametrize("name", DOCS)
def test_each_doc_says_the_runner_commits_between_steps(name: str) -> None:
    assert "between steps" in flat(name).lower()


@pytest.mark.parametrize("name", [*DOCS, "role", "liaison", "readme"])
def test_no_doc_mentions_open_story(name: str) -> None:
    assert "open_story" not in flat(name)


def test_protocol_has_the_stories_from_the_liaison_section() -> None:
    assert "### Stories from the liaison" in flat("protocol")


@pytest.mark.parametrize("row", ["| `story new ", "| `story amend "])
def test_the_cli_table_has_the_story_rows(row: str) -> None:
    lines = system.read_text(PATHS["protocol"]).splitlines()
    assert any(line.startswith(row) for line in lines)


def test_protocol_author_follows_the_code() -> None:
    assert story_drafts.LIAISON_AUTHOR in flat("protocol")
    assert story_drafts.LIAISON_AUTHOR == "Claude (agile-team liaison) <noreply@anthropic.com>"


def test_the_readme_row_mentions_the_story_commands() -> None:
    text = flat("readme")
    assert "story new" in text and "request_story" in text

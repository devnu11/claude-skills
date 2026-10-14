"""s120: the docs describe ``agile-team share`` (AC5)."""

from __future__ import annotations

from pathlib import Path

import pytest
from agile_team import cli, system

SKILL_DIR = Path(cli.__file__).parents[2]
PATHS = {
    "skill": SKILL_DIR / "SKILL.md",
    "template": SKILL_DIR / "reference" / "liaison-template.md",
    "protocol": SKILL_DIR / "reference" / "protocol.md",
    "readme": SKILL_DIR.parent / "README.md",
}


def flat(name: str) -> str:
    """A file's text with every run of whitespace collapsed to one space."""
    return " ".join(system.read_text(PATHS[name]).split())


@pytest.mark.parametrize("name", ["skill", "template", "protocol"])
def test_the_file_describes_the_share_command(name: str) -> None:
    assert "agile-team share" in flat(name)


@pytest.mark.parametrize("name", ["skill", "template"])
def test_the_liaison_docs_say_a_changed_file_fails_acceptance(name: str) -> None:
    text = flat(name).lower()
    assert "--story" in text and "acceptance" in text
    assert "hash" in text or "sha-256" in text


def test_skill_says_where_the_file_lands() -> None:
    assert "design/<id>-" in flat("skill")


def test_protocol_has_a_shared_files_section() -> None:
    assert "Shared files" in flat("protocol")
    assert "queued_shares" in flat("protocol")


def test_readme_mentions_sharing() -> None:
    assert "share" in flat("readme").lower()

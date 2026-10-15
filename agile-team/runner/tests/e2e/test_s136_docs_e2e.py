"""s136 e2e: the shipped docs and role files say the liaison writes stories."""

from __future__ import annotations

from pathlib import Path

import pytest
from agile_team import cli, roles

SKILL_DIR = Path(cli.__file__).parents[2]
FILES = {
    "role": roles.BUILTIN_DIR / "product-owner.md",
    "devops": roles.BUILTIN_DIR / "devops.md",
    "skill": SKILL_DIR / "SKILL.md",
    "protocol": SKILL_DIR / "reference" / "protocol.md",
    "liaison": SKILL_DIR / "reference" / "liaison-template.md",
}


def flat(name: str) -> str:
    """A file's text with whitespace collapsed."""
    return " ".join(FILES[name].read_text().split())


@pytest.mark.parametrize("phrase", ["request_story", "You never write a story"])
def test_ac1_po_schedules_and_requests(phrase: str) -> None:
    assert phrase in flat("role")
    assert "open_story" not in flat("role")


@pytest.mark.parametrize("phrase", ["story new", "story amend", "story-request"])
def test_ac2_liaison_template(phrase: str) -> None:
    assert phrase in flat("liaison")


@pytest.mark.parametrize("name", ["skill", "protocol"])
@pytest.mark.parametrize(
    "phrase",
    [
        "story new",
        "story amend",
        "--approved-by",
        "story-opened",
        "story-amended",
        "story-refused",
        "story-request",
    ],
)
def test_ac3_skill_and_protocol(name: str, phrase: str) -> None:
    assert phrase in flat(name)


def test_ac3_protocol_has_the_section() -> None:
    assert "Stories from the liaison" in flat("protocol")

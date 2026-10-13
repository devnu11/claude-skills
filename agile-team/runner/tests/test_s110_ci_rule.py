"""s110: the CI rule is stated in the PO role file, SKILL.md and protocol.md."""

from __future__ import annotations

from pathlib import Path

import pytest
from agile_team import cli, roles, system

RULE = (
    "**CI rule.** A sprint is done only when a green CI run is actually "
    "present on GitHub. A re-run counts only when it is green, and only when "
    "the failed job never ran our code (it was cancelled with no steps run, "
    "or no runner was available). If a failure could be flakiness in our "
    "code, it is a bug story, and the sprint is not done."
)

SKILL_DIR = Path(cli.__file__).parents[2]
PATHS = {
    "role": roles.BUILTIN_DIR / "product-owner.md",
    "skill": SKILL_DIR / "SKILL.md",
    "protocol": SKILL_DIR / "reference" / "protocol.md",
}


def flat(name: str) -> str:
    """A file's text with every run of whitespace collapsed to one space."""
    return " ".join(system.read_text(PATHS[name]).split())


@pytest.mark.parametrize("name", sorted(PATHS))
def test_the_ci_rule_text_is_in_each_file(name: str) -> None:
    assert RULE in flat(name)


def test_in_the_role_file_the_rule_sits_between_ready_and_refused() -> None:
    text = flat("role")
    assert text.index("Never call a PR ready") < text.index(RULE) < text.index("**refused**")


def test_the_ci_failed_bullet_reads_the_lines_and_never_hopes_for_a_rerun() -> None:
    text = flat("role")
    start = text.index("**ci_failed**")
    bullet = text[start : start + 900]
    assert "read the failing lines first" in bullet
    assert "no runner was assigned" in bullet
    assert "Never `continue_boundary` hoping a re-run turns green" in bullet


def test_the_role_file_forbids_calling_an_unrun_ci_done() -> None:
    assert "never tell the human the sprint is done" in flat("role")


@pytest.mark.parametrize("row", ["ci_green", "ci_failed", "ci_pending"])
def test_protocol_rows_point_to_the_rule(row: str) -> None:
    lines = system.read_text(PATHS["protocol"]).splitlines()
    rows = [line for line in lines if f"`{row}`" in line and line.lstrip().startswith("|")]
    assert rows
    assert any("see the CI rule under **Ready.**" in " ".join(r.split()) for r in rows)

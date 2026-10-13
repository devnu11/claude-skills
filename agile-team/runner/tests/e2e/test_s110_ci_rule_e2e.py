"""s110 e2e: the shipped docs and the PO role file carry the same CI rule."""

from pathlib import Path

import pytest
from agile_team import cli

RULE = (
    "**CI rule.** A sprint is done only when a green CI run is actually present on "
    "GitHub. A re-run counts only when it is green, and only when the failed job "
    "never ran our code (it was cancelled with no steps run, or no runner was "
    "available). If a failure could be flakiness in our code, it is a bug story, "
    "and the sprint is not done."
)
SKILL = Path(cli.__file__).parents[2]
FILES = {
    "role": Path(cli.__file__).parent / "roles" / "product-owner.md",
    "skill": SKILL / "SKILL.md",
    "protocol": SKILL / "reference" / "protocol.md",
}


def _text(name: str) -> str:
    return " ".join(FILES[name].read_text().split())


@pytest.mark.parametrize("name", sorted(FILES))
def test_ci_rule_present(name: str) -> None:
    """AC1/AC2: the exact rule is in the role file, SKILL.md and protocol.md."""
    assert RULE in _text(name)


def test_role_file_order_and_ci_failed() -> None:
    """AC1: the rule sits between 'Never call a PR ready' and 'refused'; ci_failed never hopes."""
    role = _text("role")
    start = role.index("Never call a PR ready")
    assert start < role.index(RULE) < role.index("**refused**", start)
    assert "read the failing lines first" in role
    assert "no runner was assigned" in role
    assert "Never `continue_boundary` hoping a re-run turns green" in role
    assert "never tell the human the sprint is done" in role


def test_protocol_rows_point_to_rule() -> None:
    """AC2: protocol.md's ci_* rows point at the rule."""
    assert _text("protocol").count("see the CI rule under **Ready.**") >= 3

"""s150: static checks of the Board card pills (W1, W3); behaviour checks live in the e2e suite."""

import re
from importlib import resources

from agile_team import system

PAGE = system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))


def rule(selector: str) -> str:
    """Body of the first CSS rule whose selector is exactly ``selector``."""
    found = re.search(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", PAGE)
    assert found, selector
    return found.group(1)


def test_card_pill_rule_keeps_one_line_and_cuts_with_an_ellipsis() -> None:
    body = rule(".story .pill")
    for decl in (
        "display: inline-block",
        "white-space: nowrap",
        "overflow: hidden",
        "text-overflow: ellipsis",
        "max-width: 100%",
    ):
        assert decl in body


def test_no_rule_lets_a_card_pill_wrap() -> None:
    assert not re.search(r"\.story \.pill[^{]*\{[^}]*white-space:\s*normal", PAGE)


def test_card_pill_dot_has_its_own_display_and_gap() -> None:
    assert "display: inline-block" in rule(".story .pill .dot")


def test_card_pill_helper_puts_the_tooltip_on_the_pill() -> None:
    assert "const cardPill = " in PAGE
    helper = PAGE.split("const cardPill = ")[1].split("\n\n")[0]
    assert 'title="${esc(title)}"' in helper


def test_wait_pill_shows_the_reason_and_titles_the_full_title() -> None:
    assert "cardPill(`⏸ ${s.wait.reason}`" in PAGE
    assert "title: s.wait.title" in PAGE
    assert "⏸ ${s.wait.title}" not in PAGE


def test_role_and_revert_pills_are_card_pills() -> None:
    assert "cardPill(`▶ ${act.role}`" in PAGE
    assert re.search(r"cardPill\(`reverted \(\$\{s\.reverts\}.\)`", PAGE)

"""s104 (as reshaped by s118): static checks of the Flow chart's page source.

The Mermaid checks became the HTML chart's rules (FC4, FC12, FC28; see
``test_s118_page.py``). The behaviour checks need node (a process), so they
live in the e2e suite.
"""

import re
from importlib import resources

from agile_team import system


def page() -> str:
    """Text of the dashboard page."""
    return system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))


# Anchored at a brace or the start: an unanchored [^{}]* rescans each stretch (s167).
FLOW_RULE = r"(?<![^{}])[^{}]*(?:#flow|\.fc)[^{}]*\{[^}]*\}"


def flow_css(text: str) -> list[str]:
    """Every CSS rule in ``text`` whose selector names ``#flow`` or a ``.fc`` class."""
    return re.findall(FLOW_RULE, text)


def test_the_flow_is_not_shrunk_to_the_container() -> None:
    rules = flow_css(page())
    assert rules
    assert not any("max-width: 100%" in rule for rule in rules)


def test_a_flow_rule_that_sets_full_max_width_is_found() -> None:
    for selector in ("#flow .fc-box", ".fc-cell"):
        rules = flow_css("<p>text</p>\n" + selector + " { max-width: 100%; }")
        assert len(rules) == 1
        assert "max-width: 100%" in rules[0]


def test_full_max_width_on_another_selector_is_not_a_flow_rule() -> None:
    rules = flow_css(".live-panel { max-width: 100%; }\n.fc { color: red; }")
    assert len(rules) == 1
    assert ".fc" in rules[0]
    assert not any("max-width: 100%" in rule for rule in rules)


def test_a_long_brace_free_stretch_is_scanned_once() -> None:
    assert flow_css("x" * 50_000 + "{}") == []


def test_the_page_draws_no_mermaid() -> None:
    assert "mermaid" not in page().lower()


def test_a_dimmed_box_is_recoloured_and_never_faded() -> None:
    dim = re.search(r"\.fc-box\.dim\s*\{([^}]*)\}", page())
    assert dim
    assert "--surface-2" in dim.group(1) and "--ink-2" in dim.group(1)
    assert not re.search(r"opacity|filter|transform|mix-blend-mode", dim.group(1))


def test_the_flow_draws_only_roles_not_marked_unused() -> None:
    assert "r.used !== false" in page()


def test_an_idle_role_reads_idle_instead_of_zero_stats() -> None:
    body = page().split("function roleBox(")[1].split("\n}")[0]
    assert "idle" in body

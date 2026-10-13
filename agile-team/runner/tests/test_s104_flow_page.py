"""s104: static checks of the Flow chart's page source (FL1, FL2, FL5, FL8).

The behaviour checks need node (a process), so they live in the e2e suite.
"""

import re
from importlib import resources

from agile_team import system


def page() -> str:
    """Text of the dashboard page."""
    return system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))


def test_the_flow_svg_is_not_shrunk_to_the_container() -> None:
    rule = re.search(r"\.flow svg\s*\{([^}]*)\}", page())
    assert rule
    assert "max-width: none" in rule.group(1)
    assert "max-width: 100%" not in rule.group(1)


def test_mermaid_draws_at_natural_size_in_16_px() -> None:
    text = page()
    assert "useMaxWidth: false" in text
    assert "const FLOW_FONT_PX = 16;" in text
    assert "mermaid.initialize(mermaidConfig(vars))" in text


def test_the_idle_class_recolours_and_never_uses_opacity() -> None:
    text = page()
    assert "idle opacity" not in text
    body = text.split("function idleClassDef()")[1].split("`;")[0]
    assert "classDef idle fill:" in body and "stroke:" in body and "color:" in body
    assert not re.search(r"opacity|filter|transform|mix-blend-mode", body)


def test_the_flow_draws_only_roles_not_marked_unused() -> None:
    assert "r.used !== false" in page()


def test_an_idle_role_reads_idle_instead_of_zero_stats() -> None:
    body = page().split("function statsText(")[1].split("\n}")[0]
    assert 'return "idle"' in body

"""s125: ``gates.Serving`` defaults (the pending registry is gone, s159 G1)."""

from __future__ import annotations

from agile_team import gates


def test_serving_defaults_to_no_story_and_no_base() -> None:
    assert gates.Serving() == gates.Serving("", "")

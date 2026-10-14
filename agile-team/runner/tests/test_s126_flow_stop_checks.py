"""s126 AC9: static checks of the Flow page's stop-check boxes.

The rendering behaviour (fixture events to boxes, refused counts, the running
attempt caption) needs node and moves to e2e.
"""

from __future__ import annotations

import json
from importlib import resources

from agile_team import system

PKG = resources.files("agile_team.dashboard")
PAGE = system.read_text(PKG.joinpath("index.html"))
FIXTURE = system.read_text(PKG.joinpath("fixtures/snapshot.json"))


def test_page_counts_refusals_per_role_and_stage() -> None:
    assert "stopRefusals" in PAGE
    assert "stop-check" in PAGE
    assert "refused" in PAGE


def test_page_captions_the_running_attempt() -> None:
    assert "attempt" in PAGE


def test_fixture_has_stop_check_events_and_attempts() -> None:
    assert '"stop-check"' in FIXTURE
    assert '"stage": "stop.suite"' in FIXTURE
    attempts = [r["attempt"] for r in _runs(json.loads(FIXTURE)) if "attempt" in r]
    assert {"n": 1, "of": 3} in attempts
    assert {"n": 2, "of": 3} in attempts
    assert None in attempts


def _runs(node: object) -> list[dict]:
    """Every dict in the fixture that carries an ``attempt`` key."""
    if isinstance(node, dict):
        own = [node] if "attempt" in node else []
        return own + [r for v in node.values() for r in _runs(v)]
    if isinstance(node, list):
        return [r for v in node for r in _runs(v)]
    return []

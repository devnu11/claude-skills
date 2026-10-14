"""s126 AC9: static checks of the Flow page's stop-check boxes.

The rendering behaviour (fixture events to boxes, refused counts, the running
attempt caption) needs node and lives in the e2e suite.
"""

from __future__ import annotations

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
    assert '"attempt": {"n": 1, "of": 3}' in FIXTURE or '"attempt": {' in FIXTURE
    assert '"attempt": null' in FIXTURE

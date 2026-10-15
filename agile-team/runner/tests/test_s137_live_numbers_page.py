"""s137: static checks of the dashboard page source for the live Flow totals.

The behaviour (numbers, growth, no double count) needs node, so it lives in
the e2e suite (``e2e/test_s137_live_numbers_e2e.py``).
"""

import re
from importlib import resources

from agile_team import system


def page() -> str:
    """Text of the dashboard page."""
    return system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))


def body(name: str) -> str:
    """Source of function ``name`` from its declaration to the next top-level declaration."""
    match = re.search(
        rf"(?:function {name}\b|const {name} =)(.*?)(?=\n(?:function|const|async function) )",
        page(),
        re.S,
    )
    assert match, name
    return match.group(1)


def test_the_live_helpers_exist() -> None:
    text = page()
    for name in ("inLedger", "liveSeconds", "liveTotals", "flowTotals"):
        assert re.search(rf"(?:function {name}\b|const {name} =)", text), name


def test_the_flow_model_reads_flow_totals() -> None:
    model = body("flowModel")
    assert "flowTotals(view)" in model
    assert "scopeTotals(view)" not in model


def test_flow_totals_builds_on_the_ledger_totals() -> None:
    assert "scopeTotals(view)" in body("flowTotals")
    assert "liveTotals(view)" in body("flowTotals")


def test_the_live_step_must_be_in_scope() -> None:
    live = body("liveTotals")
    assert "liveStep(view)" in live
    assert "inScope(view)" in live


def test_live_seconds_use_the_open_step_row() -> None:
    seconds = body("liveSeconds")
    assert "openStep(view" in seconds
    assert "awakeSoFar(view" in seconds


def test_live_tokens_come_from_the_heartbeat_not_the_turn_window() -> None:
    live = (
        body("liveTotals") + body("liveSpend")
        if "function liveSpend" in page()
        else body("liveTotals")
    )
    assert "step.tokens" in live and "cost_usd" in live
    assert "view.turns" not in live


def test_the_ledger_check_compares_role_story_and_start() -> None:
    check = body("inLedger")
    assert "l.role === step.role" in check
    assert "l.at >= step.started_at" in check


def test_the_unused_flow_context_copy_is_gone() -> None:
    assert "flowContext" not in page()


def test_the_ledger_only_totals_stay() -> None:
    assert re.search(r"function scopeTotals\b", page())

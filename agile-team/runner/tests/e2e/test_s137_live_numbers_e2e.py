"""s137 end to end on the page: a running role's Flow box counts its open step (AC1, AC2, AC3)."""
# ruff: noqa: E501

from __future__ import annotations

import json
import shutil

import pytest

from .. import dashboard_node
from ..clock import about

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

ROLE = "developer-cli"
STARTED = 1791472960.0
LIVE_TOKENS = 2130103
LIVE_COST = 1.0767
LEDGER_TOKENS = 5000
LEDGER_COST = 0.5

FIRST_STEP = f"""
view.ledger = view.ledger.filter((l) => !(l.role === "{ROLE}" && l.story === "s3"));
view.steps = view.steps.filter((s) => !(s.role === "{ROLE}" && s.story === "s3" && s.ended_at));
"""
LEDGER_ROW = f"""
view.ledger.push({{ at: {STARTED} + 100, role: "{ROLE}", model: "sonnet", story: "s3", cost_usd: {LEDGER_COST},
  tokens: {{ input: {LEDGER_TOKENS}, output: 0, cache_read: 0, cache_creation: 0 }}, turns: 3 }});
"""
CLOSED = """
const open = view.steps.find((s) => s.role === "developer-cli" && !s.ended_at);
open.ended_at = open.at + 200; open.seconds = 200;
view.heartbeat.step = null;
"""


def _numbers(
    setup: str = "", scope: str = "story", focus: str = "s3", now: float | None = None
) -> dict:
    """Role -> `roleNumbers`, plus the developer box HTML, after `setup` mutates the view."""
    driver = f"""const view = {json.dumps(dashboard_node.fixture())};
ui.scope = {json.dumps(scope)}; ui.focus = {json.dumps(focus)};
{setup}
const ctx = flowModel(view).ctx;
const out = {{}};
view.roles.forEach((r) => {{ out[r.name] = roleNumbers(view, ctx, r.name); }});
const base = scopeTotals(view)["{ROLE}"] || {{ tokens: 0, cost: 0, seconds: 0 }};
const html = flowHtml(flowModel(view));
const box = html.split('<div class="fc-box').slice(1).find((b) => b.includes('data-role="{ROLE}"')) || "";
console.log(JSON.stringify({{ roles: out, base, box }}));"""
    return dashboard_node.run_page(driver, now)


def _live_seconds(now: float, slept: float = 0.0) -> float:
    return now - STARTED - slept


NOW = dashboard_node.fixture()["generated_at"]


def test_story_scope_first_step_shows_live_numbers() -> None:
    """AC1/AC3: a running first step shows non-zero tokens, cost and time."""
    dev = _numbers(FIRST_STEP)["roles"][ROLE]
    assert dev["tokens"] == LIVE_TOKENS
    assert dev["cost"] == pytest.approx(LIVE_COST)
    assert dev["seconds"] > 0
    assert dev["seconds"] == about(_live_seconds(NOW))
    assert dev["idle"] is False


def test_box_html_does_not_read_zero_tokens() -> None:
    """AC1: the box no longer reads `0 · $0.00 · 0s`."""
    out = _numbers(FIRST_STEP)
    assert 'f-tokens">0<' not in out["box"]


@pytest.mark.parametrize("scope", ["sprint", "run"])
def test_sprint_and_run_scope_add_the_live_step(scope: str) -> None:
    """AC1: every scope equals the scope's totals plus the live numbers."""
    out = _numbers(FIRST_STEP, scope=scope)
    dev, base = out["roles"][ROLE], out["base"]
    assert dev["tokens"] == base["tokens"] + LIVE_TOKENS
    assert dev["cost"] == pytest.approx(base["cost"] + LIVE_COST)
    assert dev["seconds"] == about(base["seconds"] + _live_seconds(NOW))


def test_numbers_grow_between_two_snapshots() -> None:
    """AC1/AC3: a later snapshot with more tokens and cost shows larger numbers."""
    first = _numbers(FIRST_STEP)["roles"][ROLE]
    grow = (
        FIRST_STEP
        + "view.heartbeat.step.tokens.output += 50000; view.heartbeat.step.cost_usd += 0.25;"
        + "view.generated_at += 60; view.heartbeat.at += 60;"
    )
    later = _numbers(grow, now=NOW + 60)["roles"][ROLE]
    assert later["tokens"] > first["tokens"]
    assert later["cost"] > first["cost"]
    assert later["seconds"] > first["seconds"]


def test_settling_window_counts_the_ledger_row_not_the_live_step() -> None:
    """AC2/AC3: ledger row written, step still open: tokens and cost are the row's, seconds still live."""
    dev = _numbers(FIRST_STEP + LEDGER_ROW)["roles"][ROLE]
    assert dev["tokens"] == LEDGER_TOKENS
    assert dev["cost"] == pytest.approx(LEDGER_COST)
    assert dev["seconds"] == about(_live_seconds(NOW))


def test_after_the_step_totals_are_the_ledger_and_the_step_seconds() -> None:
    """AC2/AC3: step closed: ledger numbers, the step's own seconds, nothing twice."""
    dev = _numbers(FIRST_STEP + LEDGER_ROW + CLOSED)["roles"][ROLE]
    assert dev["tokens"] == LEDGER_TOKENS
    assert dev["cost"] == pytest.approx(LEDGER_COST)
    assert dev["seconds"] == 200


def test_an_earlier_ledger_row_does_not_stop_the_live_tokens() -> None:
    """AC2: a row from before the live step is a different step."""
    early = LEDGER_ROW.replace(f"at: {STARTED} + 100", f"at: {STARTED} - 100")
    dev = _numbers(FIRST_STEP + early)["roles"][ROLE]
    assert dev["tokens"] == LEDGER_TOKENS + LIVE_TOKENS
    assert dev["cost"] == pytest.approx(LEDGER_COST + LIVE_COST)


@pytest.mark.parametrize(("scope", "focus"), [("story", "s3"), ("sprint", "s3"), ("run", "s3")])
def test_idle_roles_are_unchanged(scope: str, focus: str) -> None:
    """AC3: every role but the running one reads as it does with no live step."""
    with_step = _numbers(FIRST_STEP, scope, focus)["roles"]
    without = _numbers(FIRST_STEP + "view.heartbeat.step = null;", scope, focus)["roles"]
    for role, numbers in with_step.items():
        if role != ROLE:
            assert numbers == without[role]


def test_a_live_step_outside_the_scope_adds_nothing() -> None:
    """LT1: Story scope on another story ignores the live step."""
    with_step = _numbers(FIRST_STEP, focus="s1")["roles"]
    without = _numbers(FIRST_STEP + "view.heartbeat.step = null;", focus="s1")["roles"]
    assert with_step == without


def test_po_in_story_scope_keeps_blank_tokens_and_cost() -> None:
    """LT6: a running PO turn leaves its Story-scope tokens and cost blank."""
    po = _numbers(FIRST_STEP + 'view.heartbeat.step.role = "product-owner";')["roles"][
        "product-owner"
    ]
    assert po["tokens"] is None
    assert po["cost"] is None

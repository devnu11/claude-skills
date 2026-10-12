"""The live meter's page functions, run under node (s44, AC10, U1-U3)."""
# ruff: noqa: E501  (embedded JavaScript lines)

from __future__ import annotations

import json
import re
import shutil
from typing import Any

import pytest

from tests.dashboard_node import fixture, run_page

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

SNAP = fixture()
NOW = SNAP["generated_at"]
HEAD = f"const SNAP = {json.dumps(SNAP)}; const NOW = {NOW};\n"


def drive(body: str) -> Any:
    """Run `body` (which sets `result`) after the page script, with SNAP and NOW defined."""
    return run_page(HEAD + body + "\nconsole.log(JSON.stringify(result));")


def with_health(level: str, reason: str = "x") -> str:
    return f"const view = normalize(SNAP); view.health = {{level: {json.dumps(level)}, reason: {json.dumps(reason)}, model_note: null}};\n"


def test_page_loads_without_booting() -> None:
    assert drive("const result = {boot: typeof boot, fetched: globalThis.fetched};") == {
        "boot": "function",
        "fetched": [],
    }


def test_tokens_per_min_and_sparkline() -> None:
    turns = [t for t in SNAP["turns"] if t["at"] > NOW - 300]
    tokens = sum(sum(t["tokens"].values()) for t in turns)
    out = drive(
        "const result = {r: tokensPerMin(SNAP.turns, NOW), s: sparkline(SNAP.turns, NOW), e: sparkline([], NOW)};"
    )
    assert out["r"] == pytest.approx(tokens / 5)
    assert len(out["s"]) == 10 and set(out["s"]) <= set("▁▂▃▄▅▆▇█")
    assert "█" in out["s"]
    assert out["e"] == "▁" * 10


def test_age_formats() -> None:
    out = drive("const result = [8, 89, 90, 660, 5400].map(fmt.age);")
    assert out == ["8 s", "89 s", "1 min", "11 min", "1 h 30 min"]


def test_restarted_after_interrupted_end() -> None:
    out = drive(
        """
const ev = (kind, status) => ({kind, role: "a", story: "s1", data: {status}});
const start = ev("step-start");
const result = {
  yes: restarted([ev("step-end", "interrupted"), start], start),
  no: restarted([ev("step-end", "done"), start], start),
  none: restarted([start], start),
};"""
    )
    assert out == {"yes": True, "no": False, "none": False}


def test_pill_text_and_class_over_fixture() -> None:
    out = drive(
        "const v = normalize(SNAP); const result = {t: pillText(v, NOW), h: smartPill(v, NOW)};"
    )
    age = int(NOW - SNAP["heartbeat"]["step"]["last_turn_at"])
    assert re.fullmatch(
        rf"● developer-cli on s3 · \S+/min [▁-█]{{10}} · {age} s( · ↻ restarted)?", out["t"]
    )
    assert "h-green" in out["h"]


def test_pill_with_red_health_and_no_live_step() -> None:
    out = drive(
        with_health("red", "the runner is not running")
        + "view.heartbeat = null; view.events = [];\nconst result = {t: pillText(view, NOW), h: smartPill(view, NOW)};"
    )
    assert out["t"] == "● the runner is not running"
    assert "h-red" in out["h"]


def test_pill_details_include_model_note() -> None:
    out = drive(
        "const v = normalize(SNAP); v.health.model_note = 'configured sonnet, answering opus';"
        "const result = pillDetails(v, NOW);"
    )
    assert any("configured sonnet, answering opus" in line for line in out)


def totals(entries: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for e in entries:
        t = out.setdefault(e["role"], {"tokens": 0, "cost": 0.0})
        t["tokens"] += sum(e["tokens"].values())
        t["cost"] += e["cost_usd"]
    return out


@pytest.mark.parametrize("scope", ["story", "sprint", "run"])
def test_scope_totals_equal_ledger_sums(scope: str) -> None:
    got = drive(
        f"""
ui.scope = {json.dumps(scope)};
const v = normalize(SNAP);
const result = {{totals: scopeTotals(v), focus: focusStory(v), entries: scopeEntries(v)}};"""
    )
    assert got["totals"].keys() == totals(got["entries"]).keys()
    for role, want in totals(got["entries"]).items():
        assert got["totals"][role]["tokens"] == want["tokens"]
        assert got["totals"][role]["cost"] == pytest.approx(want["cost"])
    if scope == "run":
        assert len(got["entries"]) == len(SNAP["ledger"])
    if scope == "story":
        assert got["entries"] and {e["story"] for e in got["entries"]} == {got["focus"]}


def test_story_scope_dims_idle_roles_never_the_po() -> None:
    src = drive("ui.scope = 'story'; const result = flowSource(normalize(SNAP)); ").splitlines()
    idle = [ln for ln in src if re.fullmatch(r"class \w+ idle", ln)]
    assert idle
    assert not any(ln == "class po idle" for ln in idle)


def test_alert_title_and_notification() -> None:
    out = drive(
        """
const mk = (level) => ({health: {level, reason: "boom"}});
Notification.permission = "granted";
applyAlert(mk("green")); const t1 = document.title;
applyAlert(mk("red")); const t2 = document.title, n2 = made.length;
applyAlert(mk("red")); const n3 = made.length;
applyAlert(mk("amber")); const t4 = document.title;
const result = {t1, t2, n2, n3, t4};"""
    )
    assert out == {
        "t1": "agile-team dashboard",
        "t2": "⚠ agile-team dashboard",
        "n2": 1,
        "n3": 1,
        "t4": "agile-team dashboard",
    }


@pytest.mark.parametrize(
    "setup",
    [
        "Notification.permission = 'denied';",
        "Notification.permission = 'granted'; globalThis.isSecureContext = false;",
    ],
)
def test_no_notification_without_permission_or_secure_context(setup: str) -> None:
    out = drive(
        setup
        + "applyAlert({health:{level:'green',reason:''}}); applyAlert({health:{level:'red',reason:'b'}});"
        "const result = {n: made.length, t: document.title};"
    )
    assert out == {"n": 0, "t": "⚠ agile-team dashboard"}


def test_graceful_stop_is_idle_and_silent() -> None:
    out = drive(
        with_health("idle", "stopped")
        + """
Notification.permission = "granted";
applyAlert(view);
const result = {t: pillText(view, NOW), h: smartPill(view, NOW), title: document.title, n: made.length};"""
    )
    assert "h-idle" in out["h"]
    assert out["t"] == "● stopped"
    assert out["title"] == "agile-team dashboard" and out["n"] == 0


def test_health_level_whitelist_blocks_html() -> None:
    out = drive(
        with_health("<b>x")
        + "const result = {l: healthLevel(view), h: smartPill(view, NOW), l2: healthLevel({health:{level:'red'}})};"
    )
    assert out["l"] == "idle" and out["l2"] == "red"
    assert "<b>" not in out["h"]


def test_fallback_pill_text_has_a_space_after_the_arrow() -> None:
    out = drive(
        'const view = normalize(SNAP); view.heartbeat = null; view.health = {level: "idle", reason: "idle", model_note: null};\n'
        'view.events = [{kind: "step-start", role: "developer-cli", story: "s29", at: NOW - 120, data: {}}];\n'
        "const result = pillText(view, NOW);"
    )
    assert out == "▶ developer-cli on s29 · 2 min"


def test_resting_stopped_pill_is_plain() -> None:
    out = drive(
        'const view = normalize(SNAP); view.run.status = "stopped"; view.health = {level: "idle", reason: "stopped", model_note: null};\n'
        "view.events = []; view.heartbeat = null; view.messages = []; view.run.manager_due = [];\n"
        "const result = statusPills(view, NOW);"
    )
    assert out[1] == '<span class="pill tone-"><span class="dot"></span>stopped</span>'
    assert "tone-warning" not in out[1]
    assert not any(x in p for p in out[1:] for x in ("h-amber", "h-red", "⚠"))


@pytest.mark.parametrize(
    ("status", "reason"),
    [
        ("stopped", "halted: stopped by stop --now"),
        ("blocked", "halted: session limit, resets 9pm"),
        ("failed", "halted: boom"),
        ("interrupted", "the runner is not running"),
    ],
)
def test_forced_halts_stay_red_on_the_smart_pill(status: str, reason: str) -> None:
    out = drive(
        f"const view = normalize(SNAP); view.run.status = {json.dumps(status)};\n"
        f'view.health = {{level: "red", reason: {json.dumps(reason)}, model_note: null}}; view.heartbeat = null; view.events = [];\n'
        "const result = statusPills(view, NOW);"
    )
    assert any("pill smart h-red" in p and f"● {reason}" in p for p in out)

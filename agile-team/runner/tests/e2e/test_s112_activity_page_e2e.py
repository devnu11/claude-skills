"""s112 end to end: Markdown in every message, the live panel, the notice and readability, under node."""
# ruff: noqa: E501

from __future__ import annotations

import json
import re
import shutil

import pytest

from .. import dashboard_node
from .test_s102_stages_page_e2e import CSS, _contrast, _theme_vars

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

BODY = "see **b**"
PLAIN = ["gate-fix", "opinion-act"]
FAKE_MD = (
    '(() => ({ disable() {}, renderer: { rules: {} }, render: (s) => "<p>MD:" + s + "</p>" }))'
)

# One sample event per TIMELINE kind, each with a body holding **b**.
SAMPLES = {
    "story-admin": {
        "tool": "hold_story",
        "reason": BODY,
        "question": None,
        "after": {"status": "active"},
    },
    "step-start": {"brief": BODY},
    "step-end": {"status": "done", "summary": BODY},
    "po-session": {"path": "p", "reasons": [BODY]},
    "gate": {"verdict": "pass", "step": "x", "now_at": "y", "reason": BODY},
    "gate-fix": {"status": "done", "files": [BODY]},
    "escalation": {"rule": "backstop", "reason": BODY, "step": "x", "count": 2, "author": "a"},
    "tests-passed": {"now_at": "implement", "reason": BODY},
    "priority": {"change": "set", "reason": BODY, "moves": [], "order": []},
    "fault": {"kind": "runner", "reason": BODY, "now_at": "x"},
    "test-dispute": {"reason": BODY, "disputes": 1, "rounds": 1},
    "message": {"message": "m1"},
    "answer": {"message": "m1"},
    "requirement-changed": {"id": "REQ-1", "change": "added", "reason": BODY},
    "story-opened": {"title": BODY},
    "boundary": {"outcome": "pass", "sprint": 1, "edge": "end", "stage": "s", "reason": BODY},
    "sprint-start": {"goal": BODY, "sprint": 1},
    "opinion": {"opinion": "o1", "kind": "note"},
    "opinion-act": {"act": "done", "route": "", "opinion": BODY},
    "thread": {"author": "human", "to": "product-owner", "entry": "t1"},
}
CTX = {
    "events": [],
    "messages": {"m1": {"id": "m1", "kind": "question", "text": BODY}},
    "answers": {"m1": {"text": BODY}},
    "thread": {"t1": {"text": BODY}},
    "opinions": {"o1": {"text": BODY}},
}


def _run(body: str, view: dict | None = None) -> dict:
    """Run `body` in the page with `view` (default: the fixture) bound; it fills `out`."""
    snap = json.dumps(view or dashboard_node.fixture())
    driver = f"const view = {snap};\nconst out = {{}};\n(async () => {{\n{body}\nconsole.log(JSON.stringify(out));\n}})();"
    return dashboard_node.run_page(driver)


# ---------------------------------------------------------------- AC2 Markdown


def test_every_timeline_kind_with_a_body_renders_through_md() -> None:
    """AC2, MD1: a kind added to TIMELINE without a sample fails; Markdown except the two plain kinds."""
    out = _run(f"""
    useMarkdown({FAKE_MD});
    const samples = {json.dumps(SAMPLES)}, ctx = {json.dumps(CTX)};
    out.kinds = Object.keys(TIMELINE); out.plain = [...PLAIN_BODIES]; out.html = {{}};
    out.errors = [];
    for (const [kind, data] of Object.entries(samples)) {{
      try {{ out.html[kind] = timelineRowHtml({{id: "x", at: 1791473000, kind, role: "developer-cli", story: "s3", data}}, ctx, false); }}
      catch (err) {{ out.errors.push(kind + ": " + err.message); }}
    }}
    """)
    assert out["errors"] == []
    assert sorted(out["kinds"]) == sorted(SAMPLES), "add a sample for the new TIMELINE kind"
    assert out["plain"] == PLAIN
    for kind, html in out["html"].items():
        if kind in PLAIN:
            assert "MD:" not in html and "see **b**" in html, kind
        else:
            assert "MD:" in html and "<p>MD:" in html and "**b**" in html, kind


def test_meta_stays_plain_and_story_admin_puts_the_question_in_the_body() -> None:
    """MD1, MD2: meta is escaped, not Markdown; the reason and question both go through md()."""
    out = _run(f"""
    useMarkdown({FAKE_MD});
    const ctx = {json.dumps(CTX)};
    out.meta = timelineRowHtml({{id: "x", at: 1791473000, kind: "fault", story: "s3", data: {{kind: "runner", reason: "r", now_at: "**x**"}}}}, ctx, false);
    out.admin = timelineRowHtml({{id: "y", at: 1791473000, kind: "story-admin", story: "s3", data: {{tool: "cancel_story", reason: "why **now**", question: "really `ok`?", after: {{status: "cancelled"}}}}}}, ctx, false);
    """)
    meta = re.search(r'<div class="tl-meta">(.*?)</div>', out["meta"]).group(1)  # type: ignore[union-attr]
    assert meta == "now at **x**" and "MD:" not in meta
    assert "MD:why **now**\n\nreally `ok`?" in out["admin"]
    assert "tl-meta" not in out["admin"]


def test_questions_tab_sources_render_through_md() -> None:
    """AC2, MD3: the Questions tab renders q.text and the answer text through md()."""
    src = dashboard_node.dashboard_file("index.html")
    assert "md(q.text)" in src and re.search(r"md\([^)]*answer[^)]*text", src)


# ---------------------------------------------------------------- AC3 notice


def test_failed_markdown_load_shows_the_notice_and_ready_does_not() -> None:
    """AC3, MD4, MD5: after a failed import the status row holds the notice; with the library ready it doesn't."""
    out = _run(
        """
    globalThis.render = () => {};
    const view2 = structuredClone(view);
    out.before = statusPills(view2, 0).join("");
    await loadMarkdown();
    out.state = markdownState; out.failed = statusPills(view2, 0).join("");
    useMarkdown("""
        + FAKE_MD
        + """);
    out.ready = statusPills(view2, 0).join(""); out.readyState = markdownState; out.MD = MD;
    """
    )
    notice = "Markdown unavailable: showing plain text"
    assert out["state"] == out["MD"]["FAILED"] and out["readyState"] == out["MD"]["READY"]
    assert 'class="md-notice"' in out["failed"] and notice in out["failed"]
    for key in ("before", "ready"):
        assert 'class="md-notice"' not in out[key] and notice not in out[key], key


# ---------------------------------------------------------------- AC4 live panel


def test_panel_state_step_stage_and_idle() -> None:
    """LP2: a beating step, an open stage alone, and nothing running."""
    out = _run("""
    out.step = panelState(view);
    const staged = structuredClone(view);
    staged.heartbeat.step = null;
    staged.heartbeat.stages = [{stage: "gate.tests", started_at: clockNow(staged) - 5, started_slept: 0}];
    out.stage = panelState(staged);
    const idle = structuredClone(view); idle.heartbeat.beat = "stopped";
    out.idle = panelState(idle);
    """)
    step = out["step"]
    assert step["kind"] == "step" and step["story"] == "s3"
    assert step["who"] == "developer-cli · s3 · implement", step["who"]
    assert re.search(r" · (first run|round \d+|↻ restarted)$", step["when"]), step["when"]
    stage = out["stage"]
    assert stage["kind"] == "stage" and stage["who"].startswith("⚙ runner · ")
    assert stage["when"].startswith("gate.tests") and stage["story"] == ""
    assert out["idle"]["kind"] == "idle" and out["idle"]["story"] == ""
    assert out["idle"]["who"] == "● Nothing running"


def test_idle_says_why() -> None:
    """LP5: open question ids, else the health reason, else the run status."""
    out = _run("""
    const idle = structuredClone(view); idle.heartbeat.beat = "stopped";
    out.open = openQuestions(idle).map((q) => q.id);
    out.waiting = idlePanel(idle).line;
    idle.messages = idle.messages.filter((m) => m.kind !== "question");
    idle.health.reason = "runner stopped"; out.reason = idlePanel(idle).line;
    idle.health.reason = ""; out.status = idlePanel(idle).line; out.runStatus = idle.run.status;
    """)
    assert out["open"], "fixture has open questions"
    assert out["waiting"] == f"waiting on {', '.join(out['open'])}"
    assert out["reason"] == "runner stopped"
    assert out["status"] == out["runStatus"]


def _events(extra: str) -> str:
    return f"""
    const ev = (id, story, at, kind, data) => ({{id, at, kind, role: "developer-cli", story, data}});
    const v = structuredClone(view);
    {extra}
    """


def test_latest_message_prefers_the_story_then_the_newest_and_skips_blanks() -> None:
    """LP4: story filter, newest of all, blank bodies skipped, a throwing builder skipped."""
    out = _run(
        _events("""
    v.events = [
      ev("a", "s3", 1, "story-opened", {title: "old on s3"}),
      ev("b", "s5", 2, "story-opened", {title: "newer on s5"}),
      ev("c", "s5", 3, "story-opened", {title: "   "}),
      ev("d", "s5", 4, "gate", {}),
      ev("f", "s5", 5, "step-end", null),
    ];
    out.s3 = latestMessage(v, "s3").e.id;
    out.all = latestMessage(v, "").e.id;
    out.none = latestMessage(v, "s9");
    v.events = [];
    out.empty = latestMessage(v, "");
    """)
    )
    assert out["s3"] == "a" and out["all"] == "b"
    assert out["none"] is None and out["empty"] is None


def test_clip_keeps_four_non_blank_lines_and_four_hundred_characters() -> None:
    """LP6: 8 lines keep 4; 3 lines are whole; blank lines don't count; 400 characters cut."""
    out = _run("""
    const lines = (n) => Array.from({length: n}, (_, i) => "l" + (i + 1)).join("\\n");
    out.eight = clip(lines(8)); out.three = clip(lines(3));
    out.blanks = clip("l1\\n\\nl2\\n\\n\\nl3\\nl4\\nl5");
    out.long = clip("x".repeat(500)); out.empty = clip(null);
    out.none = panelMessageHtml(null);
    """)
    assert out["eight"] == "l1\nl2\nl3\nl4"
    assert out["three"] == "l1\nl2\nl3"
    assert out["blanks"] == "l1\n\nl2\n\n\nl3\nl4"
    assert len(out["long"]) == 400 and out["empty"] == ""
    assert out["none"] == ""


def test_panel_message_renders_through_md_except_plain_kinds() -> None:
    """AC4: the panel message is Markdown (and escaped plain text for a PLAIN_BODIES kind)."""
    out = _run(f"""
    useMarkdown({FAKE_MD});
    out.md = panelMessageHtml({{e: {{kind: "step-start"}}, t: {{body: "- **a**"}}}});
    out.plain = panelMessageHtml({{e: {{kind: "gate-fix"}}, t: {{body: "<f>"}}}});
    """)
    assert out["md"] == '<div class="md"><p>MD:- **a**</p></div>'
    assert "MD:" not in out["plain"] and "&lt;f&gt;" in out["plain"]


def test_open_activity_filters_to_a_known_story_only() -> None:
    """LP8: a known story sets the filter, an unknown one means All stories; both open Activity."""
    out = _run("""
    globalThis.render = () => {};
    globalThis.history = {replaceState() {}};
    data.view = view;
    openActivity("s3"); out.known = [ui.story, ui.tab];
    openActivity("nope"); out.unknown = [ui.story, ui.tab];
    openActivity(""); out.blank = [ui.story, ui.tab];
    """)
    assert out["known"] == ["s3", "activity"]
    assert out["unknown"] == ["", "activity"] and out["blank"] == ["", "activity"]


def test_live_panel_fills_its_parts() -> None:
    """LP7: who, when, line, message, story, label and the health class; ticks keep the message."""
    out = _run("""
    const els = {};
    const el = () => ({textContent: "", innerHTML: "", hidden: false, className: "", dataset: {}, attrs: {},
      setAttribute(k, v) { this.attrs[k] = v; }, classList: {toggle: (c, on) => { els.cls = [c, on]; }}});
    for (const q of ["#live-panel", "#lp-who", "#lp-when", "#lp-line", "#lp-msg"]) els[q] = el();
    globalThis.document.querySelector = (q) => els[q];
    renderLivePanel(view);
    out.who = els["#lp-who"].textContent; out.story = els["#live-panel"].dataset.story;
    out.label = els["#live-panel"].attrs["aria-label"]; out.className = els["#live-panel"].className;
    out.cls = els.cls; out.msg = els["#lp-msg"].innerHTML; out.hidden = els["#lp-msg"].hidden;
    els["#lp-msg"].innerHTML = "kept"; els["#lp-when"].textContent = "";
    renderPanelText(view);
    out.keptMsg = els["#lp-msg"].innerHTML; out.when = els["#lp-when"].textContent;
    const idle = structuredClone(view); idle.heartbeat.beat = "stopped"; idle.events = [];
    renderLivePanel(idle);
    out.idleCls = els.cls; out.idleMsg = els["#lp-msg"].innerHTML; out.idleHidden = els["#lp-msg"].hidden;
    out.idleLabel = els["#live-panel"].attrs["aria-label"];
    """)
    assert out["who"].startswith("developer-cli · s3") and out["story"] == "s3"
    assert out["label"] == "Open the Activity tab for s3"
    assert re.fullmatch(r"live-panel h-\w+", out["className"])
    assert out["cls"] == ["tool", True] and out["msg"] and out["hidden"] is False
    assert out["keptMsg"] == "kept" and out["when"]
    assert out["idleCls"] == ["tool", False] and out["idleMsg"] == "" and out["idleHidden"] is True
    assert out["idleLabel"] == "Open the Activity tab"


# ---------------------------------------------------------------- layout and AC4b


def test_activity_is_its_own_tab_and_meter_sits_in_the_status_bar() -> None:
    """AC1, AC4b, AT1-AT3, BM1, LP1: tab order, the markup homes, no grid-flow."""
    out = _run("""
    out.tabs = TABS.map(([t]) => t); out.render = RENDER.activity === renderTimeline;
    out.flowSrc = renderFlowTab.toString();
    """)
    assert out["tabs"] == [
        "flow",
        "activity",
        "board",
        "backlog",
        "tokens",
        "questions",
        "requirements",
    ]
    assert out["render"] and "renderTimeline" not in out["flowSrc"]
    assert "grid-flow" not in CSS
    flow = CSS[CSS.index('id="tab-flow"') : CSS.index('id="tab-activity"')]
    activity = CSS[CSS.index('id="tab-activity"') :]
    assert 'id="timeline"' not in flow and 'id="tl-filter"' not in flow
    assert 'id="timeline"' in activity[:600] and 'id="tl-filter"' in activity[:600]
    head = CSS[CSS.index('class="head"') : CSS.index('id="tabs"')]
    assert head.index('id="status-row"') < head.index('id="live-panel"') < head.index('id="theme"')
    for gone in ('id="meter"', "head-right", "status-bar", "live-details"):
        assert gone not in CSS, gone


# ---------------------------------------------------------------- AC5 readable

RD1 = {
    ".lp-who": "--ink",
    ".lp-when": "--ink-2",
    ".lp-line": "--ink-2",
    ".lp-msg": "--ink",
    ".md-notice": "--ink-2",
}


def _rule(selector: str) -> str:
    return re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS).group(1)  # type: ignore[union-attr]


@pytest.mark.parametrize("selector", sorted(RD1))
def test_new_text_is_twelve_px_and_has_contrast_in_every_theme(selector: str) -> None:
    """AC5, RD1: font-size >= 12 px, --ink/--ink-2 only, contrast >= 4.5 on --surface in light and dark."""
    rule = _rule(selector)
    size = float(re.search(r"font-size:\s*([\d.]+)px", rule).group(1))  # type: ignore[union-attr]
    colour = re.search(r"color:\s*var\((--[\w-]+)\)", rule).group(1)  # type: ignore[union-attr]
    assert 12 <= size <= 15 and colour == RD1[selector] and "--muted" not in rule
    for name, v in _theme_vars().items():
        assert _contrast(v[colour], v["--surface"]) >= 4.5, (selector, name)


def test_code_in_markdown_stays_twelve_px() -> None:
    """RD2: `.md code` is max(12px, .92em) on --surface-2 with passing contrast."""
    assert "font-size: max(12px, .92em)" in re.search(r"\.md code\s*\{([^}]*)\}", CSS).group(1)  # type: ignore[union-attr]
    for name, v in _theme_vars().items():
        assert _contrast(v["--ink-2"], v["--surface-2"]) >= 4.5, name

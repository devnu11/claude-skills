"""s100 end to end: the story timeline on the Backlog tab, under the node harness and a real dashboard."""
# ruff: noqa: E501

from __future__ import annotations

import json
import shutil

import pytest

from .. import dashboard_node
from .test_s83_backlog_e2e import _snapshot
from .test_s104_flow_e2e import served  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _run(body: str, snap: dict | None = None) -> dict:
    """Run `body` with `view` (the snapshot as of now) bound; it fills `out`."""
    snap = snap or dashboard_node.fixture()
    driver = f"const snap = {json.dumps(snap)};\ndata.cursor = Infinity;\nconst view = asOf(snap, Infinity);\nconst out = {{}};\n(async () => {{\n{body}\nconsole.log(JSON.stringify(out));\n}})();"
    return dashboard_node.run_page(driver)


def test_expanded_story_shows_rows_totals_and_bars() -> None:
    """AC1-AC3: a timeline with role rows, bars, wait strips and the five totals."""
    out = _run("""
    const story = view.stories.find((s) => s.id === "s3");
    out.html = timelineHtml(view, story);
    out.model = timelineModel({ view, now: tlNow(view) }, story, "story");
    out.rows = out.model.groups[0].rows.map((r) => r.name ?? r.label ?? r.row);
    """)
    html = out["html"]
    assert 'data-tl-story="s3"' in html and "<svg" in html
    assert 'data-bar="step"' in html and 'data-outcome="running"' in html
    assert 'data-arrow="bounce"' in html
    assert 'data-wait="question"' in html and 'data-bar="po"' in html
    keys = [k for k in ("work", "runner", "po", "waiting", "asleep") if f'data-total="{k}"' in html]
    assert keys == ["work", "runner", "po", "waiting", "asleep"]


def test_sprint_scope_groups_every_story() -> None:
    """AC1: Sprint scope draws sprint-1 and each story as a group."""
    out = _run("""
    const story = view.stories.find((s) => s.id === "s3");
    data.skew = view.generated_at - Date.now() / 1000;  // pin "now": the fixture's running step must not stretch with the real clock
    ui.tl.s3 = { scope: "sprint", span: null, end: null };
    out.html = timelineHtml(view, story);
    """)
    assert 'data-arrow="bounce"' in out["html"] and 'data-outcome="passed"' in out["html"]
    for g in ("sprint-1", "s1", "s2", "s3", "s4"):
        assert f'data-group="{g}"' in out["html"], g


def test_zoom_pan_and_follow_now() -> None:
    """AC4: zoom narrows the window, pan moves it, fit returns; a running story has a now line."""
    out = _run("""
    const s3 = view.stories.find((s) => s.id === "s3");
    const range = timelineModel({ view, now: tlNow(view) }, s3, "story").range;
    const st = { scope: "story", span: null, end: null };
    const full = tlWindow(range, st), zin = tlWindow(range, zoomed(st, range, "in"));
    out.narrower = (zin.to - zin.from) < (full.to - full.from);
    const back = tlWindow(range, zoomed(zoomed(st, range, "in"), range, "fit"));
    out.fit = back.from === full.from && back.to === full.to;
    const z = zoomed(st, range, "in"), p = pannedBy(z, range, -60);
    out.pan = tlWindow(range, p).to < zin.to;
    out.running = range.running;
    out.now = timelineHtml(view, s3).includes("data-now");
    out.doneNow = timelineHtml(view, view.stories.find((s) => s.id === "s1")).includes("data-now");
    """)
    assert out["narrower"] and out["fit"] and out["pan"]
    assert out["running"] and out["now"] and not out["doneNow"]


def test_board_card_opens_the_timeline() -> None:
    """AC1: a done story's Board card carries a timeline link; opening it expands the row."""
    out = _run("""
    data.snap = snap; data.view = view;
    const card = storyCard(view, view.stories.find((s) => s.id === "s1"), null);
    out.link = card.includes('data-timeline="s1"');
    """)
    assert out["link"]


def test_text_in_timeline_is_readable() -> None:
    """AC-R: every drawn text is sized by an inline font-size of at least 12 at scale one."""
    out = _run("""
    const html = timelineHtml(view, view.stories.find((s) => s.id === "s3"));
    out.sizes = [...html.matchAll(/data-text="[^"]*"[^>]*?font-size[:=]"?(\\d+(?:\\.\\d+)?)/g)].map((m) => Number(m[1]));
    out.width = /<svg[^>]*width="(\\d+)"[^>]*viewBox="0 0 (\\d+)/.exec(html)?.slice(1).map(Number);
    """)
    assert out["sizes"] and min(out["sizes"]) >= 12
    assert out["width"][0] == out["width"][1]


def test_served_snapshot_feeds_the_timeline(served) -> None:  # noqa: F811
    """AC4: the live snapshot of a real dashboard renders, as a timeline or its empty note."""
    _rt, url = served
    snap = _snapshot(url)
    out = _run(
        """
    const s = view.stories[0];
    out.html = timelineHtml(view, s);
    """,
        snap,
    )
    assert 'data-tl-story="s1"' in out["html"]

"""s95 end to end: the dashboard marks each acceptance environment pass or fail, under node."""

from __future__ import annotations

import json
import shutil

import pytest

from .. import dashboard_node

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _run(body: str) -> dict:
    """Run `body` in the page; it fills `out`."""
    driver = f"const out = {{}};\n{body}\nconsole.log(JSON.stringify(out));"
    return dashboard_node.run_page(driver)


def test_envpills_render_each_mark() -> None:
    """AC4: pass is good with a tick, fail is critical with a cross, untried is plain."""
    out = _run("""
    out.html = envPills({environments: [
      {name: "cli", verdict: "pass"}, {name: "api", verdict: "fail"},
      {name: "web", verdict: ""}, {name: "odd", verdict: "weird"}]});
    """)
    html = out["html"]
    assert 'tone-good" title="acceptance environment cli: passed">cli ✓<' in html
    assert 'tone-critical" title="acceptance environment api: failed">api ✗<' in html
    assert 'tone-" title="acceptance environment web: not tried yet">web<' in html
    assert 'title="acceptance environment odd: not tried yet">odd<' in html


def test_envpills_fall_back_for_an_older_snapshot() -> None:
    """An older snapshot shows the single environment name, or nothing."""
    out = _run("""
    out.named = envPills({environment: "cli"});
    out.none = envPills({});
    """)
    assert out == {"named": " · cli", "none": ""}


def test_a_next_gate_event_reads_tried_next_environment() -> None:
    """AC4: the timeline row and the outcome legend for a `next` verdict."""
    data = {"verdict": "next", "step": "acceptance", "environment": "cli", "mark": "pass"}
    out = _run(f"""
    const row = TIMELINE.gate({{data: {json.dumps(data)}}});
    out.what = row.what; out.outcome = OUTCOMES.next.outcome;
    """)
    assert out["what"] == "acceptance · cli pass → next environment"
    assert out["outcome"] == "tried; next environment"

"""s122 end to end: a sprint-add event shows on the Activity page as a row, under node."""

from __future__ import annotations

import json
import shutil

import pytest

from .test_s112_activity_page_e2e import _run

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

EVENT = {
    "id": "e1",
    "at": 1791473000,
    "kind": "sprint-add",
    "role": "product-owner",
    "story": "s3",
    "data": {"reason": "urgent fix", "sprint": 2, "stories": ["s3", "s4"]},
}


def test_sprint_add_row_names_the_sprint_the_reason_and_the_story_ids() -> None:
    """AC4: the row reads "stories added" to "sprint 2" with the reason and `Stories: s3, s4`."""
    ctx = {"events": [], "messages": {}, "answers": {}, "thread": {}, "opinions": {}}
    out = _run(f"""
    const ev = {json.dumps(EVENT)};
    out.row = TIMELINE["sprint-add"](ev, {{}});
    out.html = timelineRowHtml(ev, {json.dumps(ctx)}, false);
    """)
    row = out["row"]
    assert row["what"] == "stories added"
    assert row["to"] == "sprint 2"
    assert row["body"] == "urgent fix\nStories: s3, s4"
    assert "stories added" in out["html"] and "sprint 2" in out["html"]
    assert "Stories: s3, s4" in out["html"] and "urgent fix" in out["html"]

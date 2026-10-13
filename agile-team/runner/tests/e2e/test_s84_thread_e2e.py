"""s84 end to end: a story thread through a real dashboard, ``watch`` and ``reply``; the page under node."""
# ruff: noqa: E501

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from agile_team import state as state_mod

from .. import dashboard_node
from ..pipeline_helpers import Script, add_story, build
from .test_dashboard_e2e import BOOT, RUNNER
from .test_liaison_e2e import ENTRY, run_cli
from .test_s83_backlog_e2e import TOKEN, _call, _snapshot, _url


@pytest.fixture
def served(make_runtime, configured: Path, tmp_path: Path) -> Iterator[tuple]:
    """A seeded runtime with story s5, and a real dashboard process on the same repo."""
    rt = build(make_runtime, Script(), steps=["design", "review"])
    add_story(rt, "s5")
    state_mod.save(rt.config.run_dir, rt.state)
    env = {**os.environ, "AGILE_TEAM_HOME": str(tmp_path / "home")}
    cmd = [sys.executable, "-c", BOOT, "--repo", str(configured), "dashboard"]
    cmd += ["--host", "127.0.0.1", "--port", "0", "--no-open", "--token", TOKEN]
    proc = subprocess.Popen(
        cmd, cwd=RUNNER, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    try:
        yield configured, _url(proc), rt
    finally:
        proc.kill()
        proc.wait(timeout=10)


def _post(url: str, story: str, to: str, text: str, token: str | None = TOKEN) -> tuple:
    body = json.dumps({"story": story, "to": to, "text": text}).encode()
    return _call(url, "POST", "/api/thread", body, token)


def test_post_to_the_po_writes_a_tagged_told_file(served) -> None:
    """AC1/AC2: 202, a ``t1.md`` with the head, and the post in the snapshot's thread."""
    _, url, rt = served
    status, data = _post(url, "s5", "product-owner", "Is CSV enough?")
    assert status == 202 and json.loads(data) == {"id": "t1", "status": "posted"}
    stored = (rt.config.run_dir / "liaison" / "messages" / "t1.md").read_text()
    assert "s5" in stored.splitlines()[0] and "Is CSV enough?" in stored
    entry = _snapshot(url)["thread"][-1]
    assert (entry["story"], entry["author"], entry["to"]) == ("s5", "human", "product-owner")
    assert TOKEN not in stored


def test_write_gate_refuses_without_the_token(served) -> None:
    """AC5: no, empty or wrong token is 403; a bad body or unknown story is 400; nothing written."""
    _, url, rt = served
    for token in (None, "", "wrong"):
        assert _post(url, "s5", "liaison", "hi", token)[0] == 403
    assert _post(url, "s5", "manager", "hi")[0] == 400
    assert _post(url, "nope", "liaison", "hi")[0] == 400
    assert _post(url, "s5", "liaison", "  ")[0] == 400
    assert not (rt.config.run_dir / "liaison" / "inbox.jsonl").exists()
    assert not (rt.config.run_dir / "liaison" / "messages").exists() or not list(
        (rt.config.run_dir / "liaison" / "messages").glob("t*.md")
    )


def test_post_to_the_liaison_wakes_watch_and_the_reply_shows(served) -> None:
    """AC3/AC4: ``watch`` prints ``liaison_message``; ``reply`` lands in the snapshot thread."""
    repo, url, _ = served
    run_cli(repo, "watch", "--timeout", "1")  # saves the memory: existing posts count as seen
    watch = subprocess.Popen(
        [sys.executable, "-c", ENTRY, "--repo", str(repo), "watch", "--timeout", "30"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )  # fmt: skip
    try:
        time.sleep(1)
        assert _post(url, "s5", "liaison", "Ask the PO about scope")[0] == 202
        out, _ = watch.communicate(timeout=15)
    finally:
        if watch.poll() is None:
            watch.kill()
            watch.wait(timeout=10)
    line = json.loads(out)
    assert "liaison_message" in line["triggers"]
    assert [p["story"] for p in line["posts"]] == ["s5"]
    replied = run_cli(repo, "reply", "s5", "-", stdin="Asked; CSV only.\n")
    assert replied.returncode == 0 and "replied lr1 on s5" in replied.stdout
    thread = _snapshot(url)["thread"]
    assert [(t["author"], t["to"]) for t in thread] == [("human", "liaison"), ("liaison", "human")]
    assert thread[-1]["text"].strip() == "Asked; CSV only."
    kinds = [e["kind"] for e in _snapshot(url)["events"] if e["kind"] == "thread"]
    assert len(kinds) == 2


def test_reply_to_an_unknown_story_is_refused(configured: Path) -> None:
    """AC3: the CLI refuses an unknown story and writes nothing."""
    done = run_cli(configured, "reply", "s999", "-", stdin="x\n")
    assert done.returncode != 0
    assert not (configured / ".team" / "run" / "liaison" / "replies.jsonl").exists()


# ----- the page under node (checklist 14-16) -------------------------------------------------

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _page(driver: str, search: str = "") -> object:
    """Run `driver` after the page's script, with `search` as the page's query string."""
    prelude = dashboard_node.PRELUDE.replace('search: ""', f'search: "{search}"')
    source = "\n".join([prelude, dashboard_node.page_script(), driver])
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "page.js"
        path.write_text(source, encoding="utf-8")
        done = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


SETUP = f"""
const snap = {json.dumps(dashboard_node.fixture())};
data.snap = normalize(snap);
const view = asOf(data.snap, Infinity);
data.view = view;
const story = (id) => view.stories.find((s) => s.id === id);
"""


@needs_node
def test_thread_renders_in_order_with_a_form_only_with_the_token() -> None:
    """AC1/AC4: entries in order with who → whom; the form needs TOKEN; none shows the empty text."""
    driver = (
        SETUP
        + """
    const empty = view.stories.find((s) => !view.thread.some((t) => t.story === s.id));
    console.log(JSON.stringify({
      html: storyDetails(story("s5"), view), expected: view.thread.filter((t) => t.story === "s5").length,
      none: empty ? storyDetails(empty, view) : "",
    }));
    """
    )
    with_token = _page(driver, "?token=t")
    assert with_token["html"].count('class="tmsg"') == with_token["expected"] >= 4
    assert "you → PO" in with_token["html"] and "PO → you" in with_token["html"]
    assert "data-thread-text" in with_token["html"] and "data-thread-send" in with_token["html"]
    assert '<option value="product-owner" selected>' in with_token["html"].replace("  ", " ")
    assert "No messages yet." in with_token["none"]
    read_only = _page(driver)
    assert (
        "data-thread-text" not in read_only["html"] and "data-thread-send" not in read_only["html"]
    )


@needs_node
def test_post_thread_validates_posts_and_reports() -> None:
    """AC1: blank sets a note and no fetch; a stubbed fetch gets the token header and body."""
    driver = (
        SETUP
        + """
    const out = {};
    const calls = [];
    let reply = { status: 202, ok: true };
    globalThis.fetch = (url, opts) => { calls.push([String(url), opts]); return Promise.resolve(reply); };
    (async () => {
      ui.drafts.s5 = "   ";
      await postThread("s5");
      out.blank = [ui.threadNote.s5, calls.length];
      ui.drafts.s5 = " hello "; ui.to.s5 = "liaison";
      await postThread("s5");
      out.ok = [calls[0][0], calls[0][1].headers["X-Agile-Team-Token"], JSON.parse(calls[0][1].body),
                ui.drafts.s5, ui.threadNote.s5];
      reply = { status: 403, ok: false };
      ui.drafts.s5 = "x"; await postThread("s5"); out.forbidden = ui.threadNote.s5;
      reply = { status: 500, ok: false };
      await postThread("s5"); out.failed = ui.threadNote.s5;
      console.log(JSON.stringify(out));
    })();
    """
    )
    out = _page(driver, "?token=t")
    assert out["blank"] == ["write a message first", 0]
    assert out["ok"] == [
        "api/thread",
        "t",
        {"story": "s5", "to": "liaison", "text": "hello"},
        "",
        "",
    ]
    assert out["forbidden"].startswith("read-only")
    assert out["failed"] == "post failed: HTTP 500"


@needs_node
def test_timeline_row_for_a_thread_event_shows_from_to_and_body() -> None:
    """AC4: the timeline row names author and recipient and carries the text."""
    driver = (
        SETUP
        + """
    const e = view.events.find((x) => x.kind === "thread");
    const ctx = { thread: Object.fromEntries(view.thread.map((t) => [t.id, t])), events: view.events };
    console.log(JSON.stringify({ row: timelineRowHtml(e, ctx, false), text: ctx.thread[e.data.entry].text }));
    """
    )
    out = _page(driver)
    assert "you" in out["row"] and "PO" in out["row"] and "→" in out["row"]
    assert "Should s5 cover Excel quoting?" in out["row"]

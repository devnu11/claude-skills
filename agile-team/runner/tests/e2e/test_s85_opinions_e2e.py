"""s85 end to end: a review request wakes ``watch``; opinions show in the snapshot; apply queues a reorder."""
# ruff: noqa: E501, F811, F401

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agile_team import reorders

from .readiness import STARTUP_S
from .test_liaison_e2e import ENTRY, run_cli
from .test_s83_backlog_e2e import TOKEN, _call, _snapshot, served


def _post(url: str, path: str, payload: dict, token: str | None = TOKEN) -> tuple:
    return _call(url, "POST", path, json.dumps(payload).encode(), token)


def _watch_after_review(url: str, repo: Path) -> dict:
    run_cli(repo, "watch", "--timeout", "1")  # saves the memory
    watch = subprocess.Popen(
        [sys.executable, "-c", ENTRY, "--repo", str(repo), "watch", "--timeout", "120"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )  # fmt: skip
    try:
        assert _post(url, "/api/review", {})[0] == 202
        out, _ = watch.communicate(timeout=2 * STARTUP_S)
    finally:
        if watch.poll() is None:
            watch.kill()
            watch.wait(timeout=10)
    return json.loads(out)


def test_review_request_wakes_watch_and_opinions_reach_the_snapshot(
    served, configured: Path
) -> None:
    """AC1-AC3: ``liaison_message`` with a story-less post; opinion and summary in ``opinions``."""
    _, url, _ = served
    line = _watch_after_review(url, configured)
    assert "liaison_message" in line["triggers"]
    assert [p["story"] for p in line["posts"]] == [""]
    done = run_cli(configured, "opinion", "b3", "move-up", "-", stdin="Do this first.\n")
    assert done.returncode == 0 and "recorded o1: move-up on b3" in done.stdout
    assert run_cli(configured, "reviewed", "-", stdin="One change.\n").returncode == 0
    ops = _snapshot(url)["opinions"]
    assert [(i["story"], i["kind"], i["latest"], i["route"]) for i in ops["items"]] == [
        ("b3", "move-up", True, "reorder")
    ]
    assert ops["asked_at"] is not None and ops["review"]["text"].strip() == "One change."
    assert ops["review"]["at"] >= ops["asked_at"]


def test_cli_refuses_bad_kind_and_unknown_story(served, configured: Path) -> None:
    """AC1: a refusal writes nothing."""
    rt, _, _ = served
    assert run_cli(configured, "opinion", "b3", "later", "-", stdin="x\n").returncode != 0
    assert run_cli(configured, "opinion", "nope", "keep", "-", stdin="x\n").returncode != 0
    assert not (rt.config.run_dir / "liaison" / "opinions.jsonl").exists()


def test_apply_queues_a_reorder_the_desk_applies(served, configured: Path) -> None:
    """AC4: apply 202 with route reorder, ``r1.json`` written, desk reorders, a second act is 409."""
    rt, url, _ = served
    run_cli(configured, "opinion", "b3", "move-up", "-", stdin="Do this first.\n")
    version = _snapshot(url)["run"]["order_version"]
    ask = {"opinion": "o1", "act": "apply", "version": version}
    assert _post(url, "/api/opinion", ask, None)[0] == 403
    status, data = _post(url, "/api/opinion", ask)
    answer = json.loads(data)
    assert status == 202 and answer["route"] == "reorder" and answer["ref"] == "r1"
    assert (rt.config.run_dir / "reorders" / "r1.json").is_file()
    assert _post(url, "/api/opinion", ask)[0] == 409
    reorders.Desk(rt).apply()
    assert rt.state.order.index("b3") < rt.state.order.index("b1")
    snap = _snapshot(url)
    assert snap["opinions"]["items"][0]["act"]["ref"] == "r1"
    assert {"opinion", "opinion-act"} <= {e["kind"] for e in snap["events"]}


def test_dismiss_and_apply_to_the_po(served, configured: Path) -> None:
    """AC4: dismiss writes no request; a ``fold`` apply is a tagged tell to the PO."""
    rt, url, _ = served
    run_cli(configured, "opinion", "b1", "scope", "-", stdin="Too big.\n")
    run_cli(configured, "opinion", "b2", "fold", "-", stdin="Merge with b1.\n")
    version = _snapshot(url)["run"]["order_version"]
    dismiss = _post(url, "/api/opinion", {"opinion": "o1", "act": "dismiss", "version": version})
    assert dismiss[0] == 202 and json.loads(dismiss[1])["route"] == ""
    status, data = _post(url, "/api/opinion", {"opinion": "o2", "act": "apply", "version": version})
    assert status == 202 and json.loads(data)["route"] == "product-owner"
    told = rt.config.run_dir / "liaison" / "messages" / f"{json.loads(data)['ref']}.md"
    assert "applied the liaison's opinion o2" in told.read_text()
    assert not (rt.config.run_dir / "reorders").exists() or not list(
        (rt.config.run_dir / "reorders").glob("r*.json")
    )

"""s128: the stop reason (S1), the snapshot's runner_pin and the page's pin pill (P12)."""

from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path

import pytest
from agile_team import system
from agile_team.gates import StoryStatus
from agile_team.holds import HoldKind, PoHold
from agile_team.po_tools import Tools
from agile_team.state import RunStatus

from .fake_system import Done, FakeSystem
from .pipeline_helpers import Script, add_story, build, drive
from .test_po_tools import call
from .test_snapshot import FIXTURE_TEXT, make_config
from .test_snapshot import build as build_snapshot

PAGE = system.read_text(resources.files("agile_team.dashboard").joinpath("index.html"))


# ----- S1: the runner says why it stopped -----------------------------------------------------


@pytest.mark.parametrize("kind", ["sprint-end", "done", "blocked"])
def test_a_status_note_stores_its_first_line(make_runtime, kind: str) -> None:
    rt = make_runtime()
    rt.state.sprint = 1
    rt.state.stories["s1"] = __import__("agile_team.gates").gates.StoryState(
        "s1", "t", "done", sprint=1, status=StoryStatus.DONE
    )
    rt.state.upstream.closed = 1  # s184 D1: the end boundary has closed, so a done lands at once
    out = call(Tools(rt).notify_user({"kind": kind, "text": "Need the API key.\nmore"}))
    assert "id" in out
    assert rt.state.status is (RunStatus.RUNNING if kind == "blocked" else RunStatus(kind))  # I4
    assert rt.state.status_reason == "Need the API key."


def test_the_stored_reason_is_cut_to_200_characters(make_runtime) -> None:
    rt = make_runtime()
    call(Tools(rt).notify_user({"kind": "blocked", "text": "x" * 500}))
    assert rt.state.status_reason == "x" * 200


def test_a_plain_update_leaves_the_status_alone(make_runtime) -> None:
    rt = make_runtime()
    call(Tools(rt).notify_user({"kind": "update", "text": "hello"}))
    assert rt.state.status_reason is None and rt.state.status is RunStatus.IDLE


def test_a_stuck_sprint_blocks_after_the_cap_with_the_blocked_text(
    make_runtime, fake: FakeSystem
) -> None:
    fake.track()
    fake.reply(("git", "remote", "get-url"), Done(2))
    rt = build(make_runtime, Script())
    add_story(rt).po_hold = PoHold(HoldKind.HOLD, "r")
    rt.state.cadence = "sprint"
    drive(rt)
    notes = [m for m in rt.relay.messages() if m.kind == "blocked"]  # I4: it waits, not BLOCKED
    assert [n.text for n in notes] == [notes[0].text], [n.text for n in notes]
    assert notes[0].text.startswith("Sprint 1: the Sprint Backlog is stuck after 3")
    assert len(notes) == 1


# ----- P12: the snapshot and the page ---------------------------------------------------------


def test_the_snapshot_carries_the_pinned_commit(scratch: Path) -> None:
    snapshot_config = make_config(scratch / "repo")
    assert build_snapshot(snapshot_config, scratch)["run"]["runner_pin"] == ""
    system.make_dirs(snapshot_config.run_dir)
    system.write_text(snapshot_config.run_dir / "runner-pin.commit", "abc1234" + "0" * 33 + "\n")
    assert build_snapshot(snapshot_config, scratch)["run"]["runner_pin"] == "abc1234" + "0" * 33


def test_the_fixture_has_the_pin_and_a_repin_event() -> None:
    fixture = json.loads(FIXTURE_TEXT)
    assert isinstance(fixture["run"]["runner_pin"], str)
    kinds = [e["kind"] for e in fixture["events"]]
    assert "runner-repin" in kinds
    [event] = [e for e in fixture["events"] if e["kind"] == "runner-repin"]
    assert set(event["data"]) == {"old", "new", "sprint", "outcome", "reason"}


def test_the_header_has_a_pin_pill_after_the_state_pill() -> None:
    assert "function pinPill(view)" in PAGE
    assert "pinPill(view)" in PAGE.split("statePill(view), ", 1)[1].split("]", 1)[0].split(",")[0]
    body = PAGE.split("function pinPill(view)", 1)[1].split("\n}\n", 1)[0]
    assert "view.run.runner_pin" in body
    assert "runner pinned at" in body and "pin " in body and ".slice(0, 7)" in body


def test_the_timeline_renders_both_repin_outcomes() -> None:
    assert re.search(r'TIMELINE\["runner-repin"\]', PAGE)
    body = PAGE.split('TIMELINE["runner-repin"]', 1)[1].split("\n};", 1)[0].split("\n\n", 1)[0]
    for text in ("runner re-pinned", "re-pin rolled back", "warning", "→", "sprint"):
        assert text in body, text

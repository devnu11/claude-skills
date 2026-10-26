"""s181 AC1/AC2 end to end: overlapping chores from two story threads, read from heartbeat.json."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from agile_team import live


def _chores(run: Path) -> list[dict]:
    return json.loads((run / "heartbeat.json").read_text())["chores"]


def _step(go: threading.Event, done: threading.Event, block) -> None:
    with block:
        done.set()
        go.wait(10)


def test_overlapping_chores_of_two_story_threads_never_outlive_their_block(tmp_path: Path) -> None:
    """AC1+AC2: A starts, B starts, A ends, B ends: each file read shows only open chores."""
    pulse = live.Pulse(tmp_path, 60.0)
    release_a, release_b = threading.Event(), threading.Event()
    in_a, in_b = threading.Event(), threading.Event()
    ta = threading.Thread(target=_step, args=(release_a, in_a, pulse.doing("stop checks", "s162")))
    tb = threading.Thread(target=_step, args=(release_b, in_b, pulse.doing("named tests", "s164")))
    ta.start()
    assert in_a.wait(10)
    tb.start()
    assert in_b.wait(10)
    rows = _chores(tmp_path)
    assert [(c["what"], c["story"]) for c in rows] == [
        ("stop checks", "s162"),
        ("named tests", "s164"),
    ]
    assert all(isinstance(c["since"], int | float) for c in rows)
    release_a.set()
    ta.join(10)
    assert [c["story"] for c in _chores(tmp_path)] == ["s164"]
    release_b.set()
    tb.join(10)
    assert _chores(tmp_path) == []

"""s100: the heartbeat records where each sleep happened; the snapshot ships it (TL19, TL20)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agile_team import config as cfg
from agile_team import live
from agile_team.dashboard import snapshot

from .clock import about
from .fake_system import FakeSystem
from .test_s78_health import RUN_DIR, make_pulse
from .test_snapshot import FIXTURE_TEXT, build, make_config, write_jsonl, write_run

BEAT = 20.0
SLEEPS_PATH = RUN_DIR / "sleeps.jsonl"


def lines(fake: FakeSystem) -> list[dict[str, Any]]:
    text = fake.files.get(str(SLEEPS_PATH), b"").decode()
    return [json.loads(line) for line in text.splitlines()]


def test_the_file_name_is_sleeps_jsonl() -> None:
    assert live.SLEEPS == "sleeps.jsonl"


def test_a_counted_sleep_is_returned_as_a_sleep(fake: FakeSystem) -> None:
    pulse, _ = make_pulse(fake)
    start = fake.clock
    fake.clock += 10 * BEAT
    sleep = pulse._count_sleep(fake.clock)
    assert sleep == live.Sleep(start, start + 10 * BEAT, 9 * BEAT)


def test_a_normal_beat_returns_none(fake: FakeSystem) -> None:
    pulse, _ = make_pulse(fake)
    for gap in (BEAT, 2 * BEAT):
        fake.clock += gap
        assert pulse._count_sleep(fake.clock) is None


def test_the_sleep_line_has_three_keys_rounded_to_a_tenth() -> None:
    line = live.Sleep(100.04, 220.06, 99.96).line()
    assert json.loads(line) == {"from": 100.0, "to": 220.1, "slept": about(100.0)}
    assert list(json.loads(line)) == ["from", "to", "slept"]
    assert "\n" not in line


def test_a_sleeping_beat_appends_exactly_one_line(fake: FakeSystem) -> None:
    pulse, _ = make_pulse(fake)
    fake.dirs.add(str(RUN_DIR))
    start = fake.clock
    fake.clock += 6 * BEAT
    pulse._beat()
    assert lines(fake) == [{"from": start, "to": start + 6 * BEAT, "slept": about(5 * BEAT)}]


def test_two_sleeps_append_two_lines_in_order(fake: FakeSystem) -> None:
    pulse, _ = make_pulse(fake)
    fake.dirs.add(str(RUN_DIR))
    fake.clock += 6 * BEAT
    pulse._beat()
    fake.clock += 4 * BEAT
    pulse._beat()
    first, second = lines(fake)
    assert first["to"] == second["from"] and second["slept"] == about(3 * BEAT)


def test_a_normal_beat_appends_nothing(fake: FakeSystem) -> None:
    pulse, _ = make_pulse(fake)
    fake.clock += BEAT
    pulse._beat()
    assert str(SLEEPS_PATH) not in fake.files


def test_log_sleep_with_none_does_nothing(fake: FakeSystem) -> None:
    pulse, _ = make_pulse(fake)
    pulse._log_sleep(None)
    assert str(SLEEPS_PATH) not in fake.files


def test_a_failed_append_is_swallowed_and_the_sleep_still_counts(fake: FakeSystem) -> None:
    pulse, writes = make_pulse(fake)
    fake.full = True
    fake.clock += 6 * BEAT
    pulse._beat()
    assert pulse.slept_s == about(5 * BEAT) and writes == [1]
    assert pulse._reported is False


# -- snapshot (TL20) ---------------------------------------------------------


@pytest.fixture
def config(scratch: Path) -> cfg.Config:
    return make_config(scratch / "repo")


def sleeps_for(config: cfg.Config, scratch: Path, rows: list[Any]) -> list[dict]:
    write_jsonl(config.run_dir / "sleeps.jsonl", rows)
    return build(config, scratch)["sleeps"]


def test_the_file_is_watched() -> None:
    assert live.SLEEPS in snapshot.RUN_FILES
    assert snapshot.SLEEPS_TAIL_BYTES == 262_144


def test_the_section_follows_tools() -> None:
    keys = list(snapshot.SECTIONS)
    assert keys[keys.index("tools") + 1] == "sleeps"


def test_no_file_no_rows(config: cfg.Config, scratch: Path) -> None:
    assert build(config, scratch)["sleeps"] == []


def test_valid_rows_are_sorted_by_from(config: cfg.Config, scratch: Path) -> None:
    late = {"from": 500, "to": 700, "slept": 150.5}
    early = {"from": 100, "to": 300, "slept": 100}
    assert sleeps_for(config, scratch, [late, early]) == [early, late]


def test_rows_ship_only_the_three_keys(config: cfg.Config, scratch: Path) -> None:
    row = {"from": 1, "to": 9, "slept": 4, "extra": "x"}
    assert sleeps_for(config, scratch, [row]) == [{"from": 1, "to": 9, "slept": about(4)}]


def test_boundary_rows_are_kept(config: cfg.Config, scratch: Path) -> None:
    rows = [{"from": 5, "to": 5, "slept": 0}, {"from": 10, "to": 20, "slept": 10}]
    assert sleeps_for(config, scratch, rows) == rows


@pytest.mark.parametrize(
    "bad",
    [
        {"from": True, "to": 10, "slept": 1},
        {"from": 0, "to": True, "slept": 0},
        {"from": 0, "to": 10, "slept": True},
        {"from": "0", "to": 10, "slept": 1},
        {"from": 0, "to": "10", "slept": 1},
        {"from": 0, "to": 10, "slept": "1"},
        {"from": 0, "to": 10, "slept": -1},
        {"from": 0, "to": 10, "slept": 11},
        {"from": 10, "to": 0, "slept": 0},
        {"from": 0, "to": 10},
        {"to": 10, "slept": 1},
        {"from": None, "to": 10, "slept": 1},
    ],
)
def test_invalid_rows_are_dropped(config: cfg.Config, scratch: Path, bad: dict) -> None:
    good = {"from": 1, "to": 5, "slept": 2}
    assert sleeps_for(config, scratch, [bad, good]) == [good]


def test_only_the_tail_is_read(config: cfg.Config, scratch: Path) -> None:
    rows = [{"from": i, "to": i + 10, "slept": 5} for i in range(8000)]
    shipped = sleeps_for(config, scratch, rows)
    assert 0 < len(shipped) < len(rows)
    assert shipped[-1] == rows[-1] and shipped[0] != rows[0]


def test_the_fixture_has_two_sleep_rows_and_three_stages() -> None:
    fixture = json.loads(FIXTURE_TEXT)
    assert len(fixture["sleeps"]) == 2
    assert list(fixture).index("sleeps") == list(fixture).index("tools") + 1
    stages = [e for e in fixture["events"] if e["kind"] == "runner-stage"]
    assert {"rs1", "rs2", "rs3"} <= {e["id"] for e in stages}
    ats = [e["at"] for e in fixture["events"]]
    assert ats == sorted(ats)


def test_the_fixture_sleeps_are_what_the_builder_gives(scratch: Path) -> None:
    fixture = json.loads(FIXTURE_TEXT)
    config = write_run(scratch / "repo", fixture)
    write_jsonl(config.run_dir / "sleeps.jsonl", fixture["sleeps"])
    assert build(config, scratch)["sleeps"] == fixture["sleeps"]

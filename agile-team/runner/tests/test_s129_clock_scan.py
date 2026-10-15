"""s129: no unit test reads the real clock or compares a duration exactly (AC2, AC3).

The files are read at import (collection), before the OS guard is on.
"""

from __future__ import annotations

import pytest

from . import clock, clock_scan

SOURCES = clock_scan.read_tree(clock_scan.Tree.UNIT)
HELPER_TEXT = (clock_scan.TESTS / "clock.py").read_text()


def test_no_test_reads_the_real_clock() -> None:
    hits = clock_scan.clock_read_hits(SOURCES)
    assert hits == [], f"real-clock reads outside tests/clock.py: {hits}"


def test_no_test_compares_a_duration_exactly() -> None:
    hits = clock_scan.duration_hits(SOURCES)
    assert hits == [], f"exact duration compares (use clock.about), file:line: {hits}"


def test_the_unit_tree_is_scanned() -> None:
    assert "dashboard_node.py" in SOURCES
    assert "conftest.py" in SOURCES
    assert not [k for k in SOURCES if k.startswith("e2e/")]


def test_the_clock_helper_is_the_one_reader() -> None:
    assert clock_scan.clock_reads(HELPER_TEXT)
    assert {"clock.py", "clock_scan.py", "test_s129_clock_scan.py"} == clock_scan.EXEMPT
    assert clock.real_now  # the helper this scan points at


@pytest.mark.parametrize(
    "text",
    [
        "Date.now()",
        "performance.now()",
        "new Date()",
        "time.time()",
        "time.monotonic()",
        "time.monotonic_ns()",
        "time.perf_counter()",
        "datetime.now(tz)",
        "datetime.utcnow()",
        "date.today()",
        "from time import monotonic",
    ],
)
def test_clock_reads_catches_each_form(text: str) -> None:
    assert len(clock_scan.clock_reads(text)) == 1


@pytest.mark.parametrize(
    "text",
    [
        "time.sleep(1)",
        'time.strftime("%H", time.gmtime(0))',
        "new Date(0)",
        "Date.now = () => 1;",
        "import time",
        "from time import sleep",
    ],
)
def test_clock_reads_passes_other_time_use(text: str) -> None:
    assert clock_scan.clock_reads(text) == []


@pytest.mark.parametrize(
    "line",
    [
        'assert row["seconds"] == 3.0',
        'assert 480 == out["awake"]',
        'assert p.heartbeat()["slept"] == 9 * BEAT',
        "assert v.beat_age != 12",
        "assert span.slept == 200.0",
        'assert (b["steps"], b["seconds"]) == (3, 180)',
        'assert out["s"] == {"tokens": 2, "seconds": 0}',
        "assert ok and x.slept_s == 5",
    ],
)
def test_exact_compares_are_caught(line: str) -> None:
    assert clock_scan.exact_duration_compares(line) == [1]


@pytest.mark.parametrize(
    "line",
    [
        'assert row["seconds"] == about(3.0)',
        "assert x.awake == pytest.approx(480, abs=1)",
        "assert span.seconds is None",
        'assert row["seconds"] == None',
        "assert len(fake.slept) == 3",
        "assert fake.slept == [5.0, 5.0]",
        "assert fake.slept == []",
        'assert row["status"] == "ok"',
        'assert row["seconds"] < 25',
        'ok = row["seconds"] == 3',
        'assert out["s"] == {"tokens": 2, "seconds": about(0)}',
    ],
)
def test_tolerant_or_other_compares_pass(line: str) -> None:
    assert clock_scan.exact_duration_compares(line) == []


def test_duration_hits_name_file_and_line_for_py_only() -> None:
    sources = {"a.py": "x = 1\nassert x.slept == 2\n", "b.js": "assert x.slept == 2"}
    assert clock_scan.duration_hits(sources) == ["a.py:2"]


def test_clock_read_hits_name_file_line_and_match() -> None:
    hits = clock_scan.clock_read_hits({"a.py": "x = 1\ny = time.time()\n"})
    assert hits == ["a.py:2: time.time("]

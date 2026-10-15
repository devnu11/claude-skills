"""s129 (AC2, AC3): no e2e test reads the real clock or compares a duration exactly (ADR-0066)."""

from __future__ import annotations

from .. import clock_scan

SOURCES = clock_scan.Tree.E2E


def test_no_test_reads_the_real_clock() -> None:
    """AC2: the e2e tree reads the clock only through `clock.py`."""
    hits = clock_scan.clock_read_hits(clock_scan.read_tree(SOURCES))
    assert hits == [], "real-clock reads outside tests/clock.py:\n" + "\n".join(hits)


def test_no_test_compares_a_duration_exactly() -> None:
    """AC3: durations are compared with `about(...)`, never `==`."""
    hits = clock_scan.duration_hits(clock_scan.read_tree(SOURCES))
    assert hits == [], "exact duration compares (use about):\n" + "\n".join(hits)


def test_the_e2e_tree_is_scanned() -> None:
    """AC2: the scan is not vacuous and covers only the e2e half."""
    files = clock_scan.read_tree(SOURCES)
    assert "e2e/readiness.py" in files and "e2e/test_s129_clock_scan_e2e.py" in files
    assert all(name.startswith("e2e/") for name in files)

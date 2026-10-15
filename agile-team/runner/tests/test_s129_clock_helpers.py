"""s129: the pure parts of the test clock helper (`tests/clock.py`).

`Deadline`, `real_now` and the node behaviour read the real clock or a process,
so their tests are e2e (`tests/e2e/test_s129_clock_e2e.py`).
"""

from __future__ import annotations

import pytest

from . import clock


def test_tolerance_is_ten_milliseconds() -> None:
    assert clock.DURATION_TOLERANCE_S == 0.01


@pytest.mark.parametrize(
    ("expected", "actual"),
    [(480, 480.005), (480, 479.995), (0, 0.0), (0, 0.009), (3.0, 3)],
)
def test_about_matches_within_tolerance(expected: float, actual: float) -> None:
    assert actual == clock.about(expected)


@pytest.mark.parametrize(
    ("expected", "actual"),
    [(480, 480.02), (480, 479.98), (0, 0.05), (3, 4)],
)
def test_about_rejects_outside_tolerance(expected: float, actual: float) -> None:
    assert actual != clock.about(expected)


def test_page_clock_freezes_date_now_in_milliseconds() -> None:
    js = clock.page_clock(100)
    assert js == "Date.now = () => 100000;\n"


def test_page_clock_keeps_fractions() -> None:
    assert clock.page_clock(1.5) == "Date.now = () => 1500.0;\n"


def test_page_clock_is_an_assignment_not_a_read() -> None:
    assert "Date.now()" not in clock.page_clock(7)

"""s129: the pure parts of the test clock helper (`tests/clock.py`).

`Deadline` is tested here on a replaced clock. The node behaviour and the real
`Deadline` are in `tests/e2e/test_s129_clock_e2e.py`.
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
    assert "Date.now" + "()" not in clock.page_clock(7)


@pytest.fixture
def now(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    t = [100.0]
    monkeypatch.setattr(clock, "real_monotonic", lambda: t[0])
    return t


def test_deadline_counts_down(now: list[float]) -> None:
    d = clock.Deadline(5)
    assert d.left() == 5.0
    assert not d.passed()
    now[0] = 103.0
    assert d.left() == 2.0
    assert not d.passed()


@pytest.mark.parametrize("at", [105.0, 110.0])
def test_deadline_passes_at_and_after_the_end(now: list[float], at: float) -> None:
    d = clock.Deadline(5)
    now[0] = at
    assert d.left() == 0.0
    assert d.passed()


def test_deadline_of_zero_has_passed_at_once(now: list[float]) -> None:
    assert clock.Deadline(0).passed()

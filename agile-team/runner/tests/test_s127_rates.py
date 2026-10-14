"""s127 (AC7, AC9, RT1): the rate series buckets tokens by 10 seconds, in tokens per minute."""

from __future__ import annotations

from agile_team import rates


def test_the_window_is_ten_seconds() -> None:
    assert rates.WINDOW_S == 10
    assert rates.RATE_POINTS == 24


def test_a_40_second_step_has_at_least_two_points() -> None:
    rate = rates.Rate(0.0)
    rate.add(5, 100)
    rate.add(35, 200)
    assert rate.series() == [600.0, 0.0, 0.0, 1200.0]


def test_a_steady_stream_reads_in_tokens_per_minute() -> None:
    rate = rates.Rate(0.0)
    for at in range(0, 60, 10):
        rate.add(at, 100)
    assert rate.series() == [600.0] * 6


def test_tokens_in_one_window_add_up() -> None:
    rate = rates.Rate(100.0)
    rate.add(100, 10)
    rate.add(109.9, 5)
    assert rate.series() == [90.0]


def test_a_turn_before_start_lands_in_window_zero() -> None:
    rate = rates.Rate(100.0)
    rate.add(90, 7)
    assert rate.series() == [42.0]


def test_quiet_windows_are_zero() -> None:
    rate = rates.Rate(0.0)
    rate.add(10, 4)
    rate.add(190, 9)
    assert rate.series() == [0.0, 24.0] + [0.0] * 17 + [54.0]


def test_nothing_added_is_an_empty_series() -> None:
    assert rates.Rate(0.0).series() == []


def test_the_series_is_rounded_to_one_decimal() -> None:
    rate = rates.Rate(0.0)
    for at in (0, 10, 20):
        rate.add(at, 1)
    assert rate.series() == [6.0, 6.0, 6.0]


def test_an_hour_is_squeezed_to_the_point_limit() -> None:
    rate = rates.Rate(0.0)
    for at in range(0, 3600, 10):
        rate.add(at, 10)
    got = rate.series()
    assert len(got) == rates.RATE_POINTS
    assert set(got) == {60.0}

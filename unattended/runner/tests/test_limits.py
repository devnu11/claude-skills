from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from unattended import limits
from unattended.limits import Bounds, OutcomeKind, Progress, Waits

EDMONTON = ZoneInfo("America/Edmonton")
NOW = datetime(2026, 10, 9, 14, 0, tzinfo=EDMONTON)
SDK_LIMIT = (
    "Claude Code returned an error result: You've hit your session limit · "
    "resets 7:20pm (America/Edmonton) (exit code: 1)"
)


def at(hour: int, minute: int = 0, day: int = 9) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=EDMONTON)


# ----- classify ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "kind", "reason"),
    [
        (
            SDK_LIMIT,
            OutcomeKind.LIMIT,
            "session limit, resets 7:20pm (America/Edmonton) (exit code: 1)",
        ),
        ("You've hit your weekly limit", OutcomeKind.LIMIT, "weekly limit"),
        ("Usage limit reached for today", OutcomeKind.LIMIT, "Usage limit reached"),
        ("API Error: 429 Too Many Requests", OutcomeKind.RATE_LIMITED, "rate limited (HTTP 429)"),
        ("rate_limit_error", OutcomeKind.RATE_LIMITED, "rate limited"),
        ("Overloaded", OutcomeKind.RATE_LIMITED, "API overloaded"),
        ("boom\nsecond line", OutcomeKind.FAILED, "boom"),
        ("cannot open src/foo-429.ts", OutcomeKind.FAILED, "cannot open src/foo-429.ts"),
        ("HTTP 529 from the API", OutcomeKind.RATE_LIMITED, "rate limited (HTTP 529)"),
        ("", OutcomeKind.FAILED, "failed"),
    ],
)
def test_classify(text: str, kind: OutcomeKind, reason: str) -> None:
    assert limits.classify(text) == limits.Outcome(kind, reason)


def test_strip_exit_suffix_before_classifying() -> None:
    reason = limits.classify(limits.strip_exit_suffix(SDK_LIMIT)).reason
    assert reason == "session limit, resets 7:20pm (America/Edmonton)"


def test_strip_exit_suffix_on_each_line() -> None:
    text = "Command failed (exit code: 1)\nError output: x"
    assert limits.strip_exit_suffix(text) == "Command failed\nError output: x"


def test_find_reason_uses_the_last_match() -> None:
    text = "resets 1pm\nlater\nresets 7pm"
    assert limits.find_reason(limits.RESET_NOTE, text) == "usage limit, resets 7pm"


# ----- reset times -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("resets 7:20pm (America/Edmonton)", at(19, 20)),
        ("resets 2am", at(2, day=10)),
        ("resets 2pm", at(14, day=10)),
        ("resets 12am", at(0, day=10)),
        ("resets 12pm", at(12, day=10)),
        ("resets Oct 10, 5pm", at(17, day=10)),
        ("resets October 10 at 5pm", at(17, day=10)),
        ("resets Oct 1, 5pm", datetime(2027, 10, 1, 17, tzinfo=EDMONTON)),
        ("first resets 1am, then resets 3pm", at(15)),
    ],
)
def test_reset_at(text: str, expected: datetime) -> None:
    assert limits.reset_at(text, NOW) == expected


def test_reset_at_honours_a_named_zone() -> None:
    found = limits.reset_at("resets 11pm (Europe/London)", NOW)
    assert found == datetime(2026, 10, 9, 23, tzinfo=ZoneInfo("Europe/London"))
    assert found > NOW


@pytest.mark.parametrize(
    "text", ["no reset here", "resets soon", "resets Foo 3, 5pm", "resets Feb 30, 5pm"]
)
def test_reset_at_unreadable(text: str) -> None:
    assert limits.reset_at(text, NOW) is None


def test_reset_at_unknown_zone_uses_now_zone() -> None:
    assert limits.reset_at("resets 7pm (Mars/Olympus)", NOW) == at(19)


def test_waits_adds_grace_to_the_reset() -> None:
    wake = Waits().after_limit("resets 7:20pm (America/Edmonton)", NOW.timestamp())
    assert wake == (at(19, 20) + timedelta(minutes=3)).timestamp()


def test_waits_falls_back_when_unreadable() -> None:
    assert Waits(60.0).after_limit("session limit", 1000.0) == 1060.0
    assert Waits().after_limit("x", 0.0) == 5 * 3600


@pytest.mark.parametrize(
    ("retries", "seconds"), [(0, 60), (1, 120), (2, 240), (5, 1800), (9, 1800)]
)
def test_backoff(retries: int, seconds: float) -> None:
    assert limits.backoff(retries) == seconds


# ----- deadlines ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "seconds"), [("24h", 86400), ("90m", 5400), ("1h30m", 5400), ("2d", 172800),
                          ("45s", 45), ("1.5h", 5400), (" 1h 5m ", 3900)],
)  # fmt: skip
def test_parse_duration(text: str, seconds: float) -> None:
    assert limits.parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "24", "h", "1x", "1h then"])
def test_parse_duration_rejects(text: str) -> None:
    with pytest.raises(ValueError, match="cannot read duration"):
        limits.parse_duration(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("21:00", at(21)),
        ("9pm", at(21)),
        ("13:30", at(13, 30, day=10)),
        ("tomorrow 9am", at(9, day=10)),
        ("today 18:15", at(18, 15)),
        ("TODAY 1am", at(1)),
        ("2026-10-12T09:00", datetime(2026, 10, 12, 9, tzinfo=EDMONTON)),
        ("2026-10-12T09:00+00:00", datetime(2026, 10, 12, 9, tzinfo=ZoneInfo("UTC"))),
    ],
)
def test_parse_until(text: str, expected: datetime) -> None:
    assert limits.parse_until(text, NOW) == expected


@pytest.mark.parametrize("text", ["noon", "25:00", "9:75", "next week"])
def test_parse_until_rejects(text: str) -> None:
    with pytest.raises(ValueError, match="cannot read time"):
        limits.parse_until(text, NOW)


# ----- bounds -------------------------------------------------------------------------


def test_bounds_allow_within_limits() -> None:
    assert (
        Bounds(deadline=200.0, max_resumes=2, max_cost=1.0).stop_reason(
            Progress(resumes=1, cost=0.5, next_wake=100.0)
        )
        is None
    )


def test_bounds_without_deadline_or_cost() -> None:
    assert Bounds().stop_reason(Progress(resumes=9, cost=1e6, next_wake=1e12)) is None


def test_bounds_deadline_before_next_wake() -> None:
    reason = Bounds(deadline=NOW.timestamp()).stop_reason(
        Progress(0, 0.0, (NOW + timedelta(hours=1)).timestamp())
    )
    assert reason is not None and reason.startswith("deadline ")
    assert "comes before the next wake" in reason


def test_bounds_resumes_used_up() -> None:
    reason = Bounds(max_resumes=3).stop_reason(Progress(3, 0.0, 0.0))
    assert reason == "used all 3 resumes"


def test_bounds_cost_reached() -> None:
    reason = Bounds(max_cost=2.0).stop_reason(Progress(0, 2.5, 0.0))
    assert reason == "cost $2.50 reached the $2.00 cap"


def test_local_is_aware() -> None:
    assert limits.local(0.0).tzinfo is not None

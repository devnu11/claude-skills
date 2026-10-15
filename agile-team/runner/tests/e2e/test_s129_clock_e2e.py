"""s129 (AC1): the real `Deadline`, and the page's clock frozen under node (ADR-0066)."""

from __future__ import annotations

import shutil

import pytest

from .. import clock, dashboard_node

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
NOW_DRIVER = "console.log(JSON.stringify({n: nowS()}))"
BUSY = "let x = 0; for (let i = 0; i < 5e6; i++) x += i;"


def test_a_zero_deadline_has_passed() -> None:
    """A Deadline(0) is over at once and has nothing left."""
    deadline = clock.Deadline(0)
    assert deadline.passed() and deadline.left() == 0.0


def test_a_long_deadline_has_not_passed() -> None:
    """A Deadline(60) is still running with at most 60 s left."""
    deadline = clock.Deadline(60)
    assert not deadline.passed() and 0 < deadline.left() <= 60


@needs_node
def test_run_page_pins_now_to_the_given_value() -> None:
    """AC1: `run_page(driver, 100)` makes `nowS()` 100."""
    assert dashboard_node.run_page(NOW_DRIVER, 100) == {"n": 100}


@needs_node
def test_run_page_defaults_to_the_fixture_generated_at() -> None:
    """AC1: with no `now`, `nowS()` is the fixture's `generated_at`."""
    out = dashboard_node.run_page(NOW_DRIVER)
    assert out == {"n": dashboard_node.fixture()["generated_at"]}


@needs_node
def test_the_page_clock_does_not_move_while_the_driver_runs() -> None:
    """AC1: work between two reads of `nowS()` leaves them equal."""
    driver = f"const a = nowS(); {BUSY} console.log(JSON.stringify({{same: a === nowS()}}));"
    assert dashboard_node.run_page(driver) == {"same": True}

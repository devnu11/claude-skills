"""s82: the stop waits for the whole service group and its port (FAKE world, fake clock)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from agile_team import config as cfg
from agile_team import presentation, sandbox
from agile_team.config import Delivery
from agile_team.gates import READY, StoryState, Verdict
from agile_team.presentation import Trial

from .fake_system import FakeSystem

PORT = 8799
URL = f"http://127.0.0.1:{PORT}/"
UI = Delivery("ui", "web", prepare="serve", url=URL, probe="api/snapshot")


def prepared(delivery: Delivery = UI) -> sandbox.Prepared:
    root = Path("/fake/customer/ui")
    return sandbox.Prepared(delivery, sandbox.DELIVERY_KINDS["web"], Path("/fake"), root, root)


# ----- constants --------------------------------------------------------------


def test_wait_constants() -> None:
    assert sandbox.KILL_WAIT_S == 5
    assert sandbox.PORT_WAIT_S == 5
    assert sandbox.POLL_EVERY_S == 0.05
    assert sandbox.STOP_WAIT_S == 10


# ----- wait_until -------------------------------------------------------------


def test_wait_until_true_at_once_does_not_sleep(fake: FakeSystem) -> None:
    assert sandbox.wait_until(lambda: True, 5) is True
    assert fake.slept == []


def test_wait_until_true_on_the_third_check_sleeps_twice(fake: FakeSystem) -> None:
    checks: list[int] = []

    def done() -> bool:
        checks.append(1)
        return len(checks) == 3

    assert sandbox.wait_until(done, 5) is True
    assert fake.slept == [sandbox.POLL_EVERY_S, sandbox.POLL_EVERY_S]


def test_wait_until_never_true_gives_up_at_the_deadline(fake: FakeSystem) -> None:
    start = fake.clock
    assert sandbox.wait_until(lambda: False, 2) is False
    moved = fake.clock - start
    assert 2 <= moved < 2 + sandbox.POLL_EVERY_S + 1e-9


def test_wait_until_checks_once_more_at_the_deadline(fake: FakeSystem) -> None:
    target = fake.clock + 1
    assert sandbox.wait_until(lambda: fake.clock >= target, 1) is True


# ----- port_released ----------------------------------------------------------


def test_port_released_when_it_frees_on_the_third_poll() -> None:
    calls: list[tuple[str, int]] = []

    def listening(host: str, port: int) -> bool:
        calls.append((host, port))
        return len(calls) < 3

    assert sandbox.port_released(prepared(), listening) is None
    assert calls == [("127.0.0.1", PORT)] * 3


def test_port_released_reports_a_port_that_never_frees(fake: FakeSystem) -> None:
    start = fake.clock
    note = sandbox.port_released(prepared(), lambda _h, _p: True)
    assert note == (
        f"delivery 'ui' did not let go of 127.0.0.1:{PORT}: it was still in use "
        "5s after the service was stopped; keep the service in its start "
        "command's process group"
    )
    assert fake.clock - start >= sandbox.PORT_WAIT_S


def test_port_released_without_a_url_never_looks() -> None:
    def listening(_h: str, _p: int) -> bool:
        raise AssertionError("must not be called")

    assert sandbox.port_released(prepared(Delivery("ui", "web")), listening) is None


# ----- Trial ------------------------------------------------------------------


@pytest.fixture
def config(configured: Path) -> cfg.Config:
    c = cfg.load(configured)
    c.deliveries = [UI]
    return c


def trial_with(config: cfg.Config, note: str | None, monkeypatch: pytest.MonkeyPatch) -> Trial:
    # presented_source asks the real disk (Path.is_dir); the answer is irrelevant here.
    monkeypatch.setattr(presentation, "presented_source", lambda _c, _s: None)

    def prepare(_config: cfg.Config, _order: Any) -> sandbox.Prepared:
        p = prepared()
        p.stop = lambda: note  # type: ignore[method-assign]
        return p

    return Trial(config, prepare=prepare)


def story() -> StoryState:
    return StoryState("s7", "A story", "e2e", sprint=1)


def test_trial_holds_when_the_stop_reports_a_held_port(
    config: cfg.Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = trial_with(config, "port 1 held", monkeypatch).liveness(story())
    assert out.verdict is Verdict.HOLD
    assert out.reason == presentation.STOP_HELD.format(story="s7", held="port 1 held")
    assert out.reason == "story s7 presentation did not stop: port 1 held"


def test_trial_passes_when_the_stop_is_clean(
    config: cfg.Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = trial_with(config, None, monkeypatch).liveness(story())
    assert out.verdict is Verdict.PASS
    assert out.reason == f"{READY}; {URL}api/snapshot answered"


# ----- _joined ----------------------------------------------------------------


def test_joined_adds_the_note_on_its_own_line() -> None:
    assert sandbox._joined("r", None) == "r"
    assert sandbox._joined("r", "n") == "r\nn"

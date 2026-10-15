"""s82: the stop waits for the whole service group and its port (FAKE world, fake clock)."""

from __future__ import annotations

import signal
from pathlib import Path
from typing import Any

import pytest
from agile_team import config as cfg
from agile_team import presentation, sandbox, system
from agile_team.config import Environment
from agile_team.gates import READY, StoryState, Verdict
from agile_team.presentation import Trial

from .clock import about
from .conftest import write_story
from .fake_system import FAKE_REPO, Done, FakeSystem, Hang

PORT = 8799
URL = f"http://127.0.0.1:{PORT}/"
UI = Environment("ui", "web", prepare="serve", url=URL, probe="api/snapshot")


def prepared(environment: Environment = UI) -> sandbox.Prepared:
    root = Path("/fake/customer/ui")
    return sandbox.Prepared(
        environment, sandbox.ENVIRONMENT_KINDS["web"], Path("/fake"), root, root
    )


# ----- constants --------------------------------------------------------------


def test_wait_constants() -> None:
    assert sandbox.KILL_WAIT_S == 5
    assert sandbox.PORT_WAIT_S == 5
    assert sandbox.POLL_EVERY_S == 0.05
    assert sandbox.STOP_WAIT_S == 10


# ----- wait_until -------------------------------------------------------------


def test_wait_until_true_at_once_does_not_sleep(fake: FakeSystem) -> None:
    assert sandbox.wait_until(lambda: True, 5) is True
    assert fake.slept == about([])


def test_wait_until_true_on_the_third_check_sleeps_twice(fake: FakeSystem) -> None:
    checks: list[int] = []

    def done() -> bool:
        checks.append(1)
        return len(checks) == 3

    assert sandbox.wait_until(done, 5) is True
    assert fake.slept == about([sandbox.POLL_EVERY_S, sandbox.POLL_EVERY_S])


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
        f"acceptance environment 'ui' did not let go of 127.0.0.1:{PORT}: it was still in use "
        "5s after the service was stopped; keep the service in its start "
        "command's process group"
    )
    assert fake.clock - start >= sandbox.PORT_WAIT_S


def test_port_released_without_a_url_never_looks() -> None:
    def listening(_h: str, _p: int) -> bool:
        raise AssertionError("must not be called")

    assert sandbox.port_released(prepared(Environment("ui", "web")), listening) is None


# ----- Trial ------------------------------------------------------------------


@pytest.fixture
def config(configured: Path) -> cfg.Config:
    c = cfg.load(configured)
    c.environments = [UI]
    return c


def trial_with(config: cfg.Config, note: str | None) -> Trial:
    def prepare(_config: cfg.Config, _order: Any) -> sandbox.Prepared:
        p = prepared()
        p.stop = lambda: note  # type: ignore[method-assign]
        return p

    return Trial(config, prepare=prepare)


def story() -> StoryState:
    return StoryState("s7", "A story", "e2e", sprint=1)


def test_trial_holds_when_the_stop_reports_a_held_port(config: cfg.Config) -> None:
    write_story(config, "s7", "ui")
    out = trial_with(config, "port 1 held").liveness(story())
    assert out.verdict is Verdict.HOLD
    assert out.reason == presentation.STOP_HELD.format(story="s7", held="port 1 held")
    assert out.reason == "story s7 presentation did not stop: port 1 held"


def test_trial_passes_when_the_stop_is_clean(config: cfg.Config) -> None:
    write_story(config, "s7", "ui")
    out = trial_with(config, None).liveness(story())
    assert out.verdict is Verdict.PASS
    assert out.reason == f"{READY}; {URL}api/snapshot answered"


# ----- _joined ----------------------------------------------------------------


def test_joined_adds_the_note_on_its_own_line() -> None:
    assert sandbox._joined("r", None) == "r"
    assert sandbox._joined("r", "n") == "r\nn"


# ----- the group, on the fake process model (s76 J5) ---------------------------

ADDRESS = ("127.0.0.1", PORT)


def started(fake: FakeSystem) -> system.Process:
    """A running service that leads its own group."""
    fake.reply(("serve",), Hang("up\n"))
    return system.spawn_piped(system.ShellCommand("serve", FAKE_REPO))


def sent(fake: FakeSystem) -> list[int]:
    return [sig for name, _group, sig in fake.signals if name == "killpg"]


def test_end_group_on_a_hung_child_sends_only_sigterm(fake: FakeSystem) -> None:
    child = started(fake)
    sandbox.end_group(child)
    assert sent(fake) == [signal.SIGTERM]
    assert child.poll() == -signal.SIGTERM


def test_end_group_on_an_exited_child_sends_nothing(fake: FakeSystem) -> None:
    fake.reply(("serve",), Done(0))
    sandbox.end_group(system.spawn_piped(system.ShellCommand("serve", FAKE_REPO)))
    assert fake.signals == []


def test_end_group_escalates_to_sigkill_after_the_stop_wait(fake: FakeSystem) -> None:
    child = started(fake)
    fake.survivors.add(child.pid)
    start = fake.clock
    sandbox.end_group(child)
    assert sent(fake) == [signal.SIGTERM, signal.SIGKILL]
    assert fake.clock - start >= sandbox.STOP_WAIT_S
    assert child.poll() == -signal.SIGKILL


def test_a_lingering_group_member_keeps_the_group_from_being_ended(fake: FakeSystem) -> None:
    child = started(fake)
    member = child.pid + 100
    fake.groups[member] = child.pid  # the dash case: the leader goes, the group stays
    fake.survivors.add(member)
    system.kill(child.pid, signal.SIGKILL)
    assert child.poll() is not None
    assert sandbox._ended(child) is False
    system.killpg(child.pid, signal.SIGKILL)
    assert sandbox._ended(child) is True


def test_end_group_waits_for_a_member_that_outlives_its_leader(fake: FakeSystem) -> None:
    child = started(fake)
    member = child.pid + 100
    fake.groups[member] = child.pid
    fake.survivors.add(member)
    sandbox.end_group(child)
    assert sent(fake) == [signal.SIGTERM, signal.SIGKILL]
    assert member not in fake.groups


def stoppable(fake: FakeSystem) -> sandbox.Prepared:
    root = FAKE_REPO / "customer" / "ui"
    return sandbox.Prepared(
        UI, sandbox.ENVIRONMENT_KINDS["web"], FAKE_REPO, root, root, process=started(fake)
    )


def test_stop_returns_port_held_while_a_survivor_outside_the_group_holds_the_port(
    fake: FakeSystem,
) -> None:
    box = stoppable(fake)
    straggler = 7000  # escaped the group and still listens
    fake.groups[straggler] = straggler
    fake.holds[straggler] = ADDRESS
    fake.listening.add(ADDRESS)
    note = box.stop()
    assert note == sandbox.PORT_HELD.format(
        name="ui", host="127.0.0.1", port=PORT, seconds=sandbox.PORT_WAIT_S
    )
    assert straggler in fake.groups


def test_stop_returns_none_once_the_group_that_held_the_port_is_ended(fake: FakeSystem) -> None:
    box = stoppable(fake)
    fake.holds[box.process.pid] = ADDRESS
    fake.listening.add(ADDRESS)
    assert box.stop() is None
    assert ADDRESS not in fake.listening

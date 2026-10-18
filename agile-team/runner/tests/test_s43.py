"""s43: gate commands run under a time limit; a hung test is named."""

import signal
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from agile_team import boundary, cli, commands, fullcheck, gates, guard, system
from agile_team import config as cfg
from agile_team.commands import (
    HUNG_LINE,
    NO_HUNG_LINE,
    TIMED_OUT,
    TIMEOUT_LINE,
    CommandShell,
    hung_test,
    shell_runner,
)
from agile_team.gates import Verdict
from agile_team.guard import WAIT_DENIED, Scope
from agile_team.roles import Handoff

from .conftest import FakeRunner
from .fake_system import FAKE_REPO, FIRST_CHILD_PID, START_CLOCK, Done, FakeSystem, Hang
from .test_gates import checks, pipeline, story

FAULT = '  File "/x/tests/test_a.py", line 12 in test_hangs\n'
TRACE = '  File "/x/tests/test_b.py", line 7, in test_other\n'


REPO = FAKE_REPO


class Stuck:
    """A child that never finishes: ``wait`` times out and its output never ends (s118 R8)."""

    pid = FIRST_CHILD_PID
    returncode = None

    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.timeouts: list[float] = []
        self.release = threading.Event()

    @property
    def stdout(self) -> Iterator[str]:
        yield "started\n"
        self.release.wait(5)  # a hard bound so a mistake cannot hang the suite

    def wait(self, timeout: float) -> int:
        self.timeouts.append(timeout)
        raise self.error or system.TimeoutExpired("stuck", timeout)

    def __enter__(self) -> "Stuck":
        return self

    def __exit__(self, *exc: object) -> None:
        self.release.set()


def killpgs(fake: FakeSystem) -> list[tuple[int, int]]:
    return [(group, sig) for name, group, sig in fake.signals if name == "killpg"]


# ---- commands.py


def test_shell_runner_merges_streams_and_keeps_the_code(fake: FakeSystem) -> None:
    fake.reply(("echo",), Done(4, "out\nerr\n"))
    code, out = shell_runner(REPO)("echo out; echo err >&2; exit 4")
    assert code == 4 and "out" in out and "err" in out
    assert fake.commands == [system.ShellCommand("echo out; echo err >&2; exit 4", REPO)]


def test_the_child_is_spawned_with_its_output_piped(fake: FakeSystem) -> None:
    fake.reply(("cat",), Done(0, ""))
    assert shell_runner(REPO, 2.0)("cat") == (0, "")


def test_timeout_kills_and_reports(fake: FakeSystem) -> None:
    fake.reply(("sleep",), Hang("partial\n"))
    code, out = CommandShell(REPO, 0.3).run("sleep 30")
    assert code == TIMED_OUT == 124
    assert fake.clock == START_CLOCK + 0.3
    lines = out.splitlines()
    assert lines[0] == "partial"
    assert lines[-2] == TIMEOUT_LINE.format(limit=0.3, command="sleep 30")
    assert lines[-2].startswith("timed out after 0.3s")
    assert lines[-1] == NO_HUNG_LINE
    assert killpgs(fake) == [(FIRST_CHILD_PID, signal.SIGKILL)]


def test_hung_test_is_named_from_stderr(fake: FakeSystem) -> None:
    fake.reply(("sleep",), Hang(FAULT))
    code, out = CommandShell(REPO, 0.5).run("printf %s faulthandler >&2; sleep 30")
    assert code == TIMED_OUT
    assert out.splitlines()[-1] == HUNG_LINE.format(test="/x/tests/test_a.py::test_hangs (line 12)")


def test_only_the_group_is_killed(fake: FakeSystem) -> None:
    other = FIRST_CHILD_PID + 500
    grandchild = FIRST_CHILD_PID + 100
    fake.groups[other] = other
    fake.reply(("sleep",), Hang())
    fake.groups[grandchild] = FIRST_CHILD_PID  # `sleep 30 &` in the command's own group
    assert CommandShell(REPO, 0.3).run("sleep 30 & wait")[0] == TIMED_OUT
    assert grandchild not in fake.groups and FIRST_CHILD_PID not in fake.groups
    assert other in fake.groups


def test_drain_has_a_deadline(fake: FakeSystem, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(commands, "DRAIN_S", 0.2)
    stuck = Stuck()
    fake.groups[stuck.pid] = stuck.pid
    monkeypatch.setattr(system, "spawn_piped", lambda _command: stuck)
    command = "python3 -c setsid-child & sleep 30"
    code, out = CommandShell(REPO, 0.5).run(command)
    assert code == TIMED_OUT
    assert stuck.timeouts == [0.5]
    assert out.splitlines() == [
        "started",
        TIMEOUT_LINE.format(limit=0.5, command=command),
        NO_HUNG_LINE,
    ]


def test_other_exceptions_kill_the_group_and_propagate(
    fake: FakeSystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed: list[object] = []
    stuck = Stuck(KeyboardInterrupt())
    monkeypatch.setattr(system, "spawn_piped", lambda _command: stuck)
    monkeypatch.setattr(commands, "kill_group", killed.append)
    with pytest.raises(KeyboardInterrupt):
        CommandShell(REPO, 5.0).run("sleep 30")
    assert killed == [stuck]


def test_hung_test_formats_and_last_dump_wins() -> None:
    assert hung_test(FAULT) == "/x/tests/test_a.py::test_hangs (line 12)"
    assert hung_test(TRACE) == "/x/tests/test_b.py::test_other (line 7)"
    assert hung_test(FAULT + TRACE) == "/x/tests/test_b.py::test_other (line 7)"


def test_hung_test_ignores_non_test_frames() -> None:
    noise = '  File "/p/x.py", line 3 in pytest_pyfunc_call\n  File "/p/y.py", line 4 in select\n'
    assert hung_test(noise) is None
    assert hung_test(FAULT + noise) == "/x/tests/test_a.py::test_hangs (line 12)"
    assert hung_test("") is None


def test_report_timeout_with_empty_output() -> None:
    got = CommandShell(REPO, 2.0).report_timeout("cmd", "")
    assert got.splitlines() == [TIMEOUT_LINE.format(limit=2.0, command="cmd"), NO_HUNG_LINE]


# ---- gates.py

TIMEOUT_OUT = "partial\nthe reason"
TIMEOUT = {"T": (124, TIMEOUT_OUT)}


def test_timed_out_helper() -> None:
    assert gates.timed_out(1, "x") is None
    assert gates.timed_out(0, "x") is None
    assert gates.timed_out(124, "x").verdict is Verdict.BOUNCE


def test_green_timeout_is_not_tests_fail() -> None:
    out = checks(TIMEOUT).green()
    assert out.verdict is Verdict.BOUNCE
    assert "tests fail" not in out.reason and "did not finish in time" in out.reason


def test_coverage_timeout_is_not_unreadable_total() -> None:
    out = checks({"T": (0, ""), "C": (124, "slow")}).tests_green_and_covered()
    assert out.verdict is Verdict.BOUNCE
    assert "did not finish in time" in out.reason and "could not read" not in out.reason


def test_pipeline_bounces_a_timeout_at_implement() -> None:
    out = pipeline({"C": TIMEOUT["T"]}).evaluate(story("implement"), Handoff("done"))
    assert out.verdict is Verdict.BOUNCE and out.bounce_to == "implement"
    assert "did not finish in time" in out.reason


# ---- config / cli


def test_command_timeout_default_and_read(repo: Path) -> None:
    assert cfg.from_raw(repo, {}).gates.command_timeout_s == 300.0
    assert cfg.from_raw(repo, {"gates": {"command_timeout_s": 90}}).gates.command_timeout_s == 90


@pytest.mark.parametrize("bad", [0, -1])
def test_command_timeout_must_be_positive(repo: Path, bad: int) -> None:
    c = cfg.from_raw(repo, {"gates": {"command_timeout_s": bad}})
    known = cfg.Known({"developer"}, {"package"})
    assert "gates.command_timeout_s must be positive" in cfg.validate(c, known)


def test_cli_passes_the_limit(configured: Path, key_home: Path, repo: Path) -> None:
    config = cfg.load(configured)
    config.gates.command_timeout_s = 90
    assert cli.make_pipeline(config).checks.run.__self__.limit_s == 90
    rt = cli.make_runtime(cli.Place(configured, key_home), lambda *a, **k: None)
    assert rt.shell(repo).__self__.limit_s == rt.config.gates.command_timeout_s
    assert rt.shell(repo).__self__.limit_s == 300.0


def test_cli_runtime_uses_the_configured_limit(
    configured: Path, key_home: Path, repo: Path
) -> None:
    text = system.read_text(configured / cfg.CONFIG_NAME)
    system.write_text(configured / cfg.CONFIG_NAME, text + "\n[gates]\ncommand_timeout_s = 90\n")
    rt = cli.make_runtime(cli.Place(configured, key_home), lambda *a, **k: None)
    assert rt.shell(repo).__self__.limit_s == 90


# ---- fullcheck.py


def test_fullcheck_timeout_why_and_tail() -> None:
    runner = FakeRunner({"slow": (124, "a\nTIMEOUT REASON")})
    report = fullcheck.run_checks(
        [fullcheck.FullCheck("test", "slow")], fullcheck.Judging(runner, 1.0)
    )
    assert fullcheck.TIMED_OUT_WHY == "timed out"
    assert report.reason() == boundary.CHECK_FAILED.format(
        name="test", why="timed out", command="slow", tail=gates.tail("a\nTIMEOUT REASON")
    )


# ---- guard.py


@pytest.mark.parametrize(
    "command",
    [
        "until grep -q passed /tmp/run.log; do sleep 5; done",
        "while true; do sleep 1; done",
        "while ! grep -q x f; do sleep 1; done",
    ],
)
def test_open_wait_loops_are_denied(repo: Path, command: str) -> None:
    scope = Scope("developer", repo, [])
    assert guard.check_bash(scope, command) == WAIT_DENIED


@pytest.mark.parametrize(
    "command",
    [
        "timeout 300 bash -c 'until grep -q x f; do sleep 1; done'",
        "for i in $(seq 60); do sleep 1; done",
        'cat f | while read l; do echo "$l"; done',
        "while IFS= read -r l; do :; done < f",
    ],
)
def test_bounded_loops_are_allowed(repo: Path, command: str) -> None:
    assert guard.check_bash(Scope("developer", repo, []), command) is None


# ---- pytest config


def test_per_test_timeout_is_configured(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.getini("timeout") == "1"
    assert pytestconfig.getini("e2e_timeout") == "30"

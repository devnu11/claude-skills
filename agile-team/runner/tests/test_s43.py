"""s43: gate commands run under a time limit; a hung test is named."""

import contextlib
import os
import signal
import subprocess
import time
from pathlib import Path

import pytest
from agile_team import boundary, cli, commands, fullcheck, gates, guard
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
from agile_team.gates import TIMED_OUT_BOUNCE, TestClaim, Verdict
from agile_team.guard import WAIT_DENIED, Scope
from agile_team.roles import Handoff

from .conftest import FakeRunner
from .test_gates import checks, pipeline, story

FAULT = '  File "/x/tests/test_a.py", line 12 in test_hangs\n'
TRACE = '  File "/x/tests/test_b.py", line 7, in test_other\n'


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_gone(pid: int) -> bool:
    for _ in range(40):
        if not alive(pid):
            return True
        time.sleep(0.05)
    return False


# ---- commands.py


def test_shell_runner_merges_streams_and_keeps_the_code(tmp_path: Path) -> None:
    code, out = shell_runner(tmp_path)("echo out; echo err >&2; exit 4")
    assert code == 4 and "out" in out and "err" in out


def test_stdin_is_dev_null(tmp_path: Path) -> None:
    assert shell_runner(tmp_path, 2.0)("cat") == (0, "")


def test_timeout_kills_and_reports(tmp_path: Path) -> None:
    start = time.monotonic()
    code, out = CommandShell(tmp_path, 0.3).run("sleep 30")
    assert code == TIMED_OUT == 124
    assert time.monotonic() - start < 5
    lines = out.splitlines()
    assert lines[-2] == TIMEOUT_LINE.format(limit=0.3, command="sleep 30")
    assert lines[-2].startswith("timed out after 0.3s")
    assert lines[-1] == NO_HUNG_LINE


def test_hung_test_is_named_from_stderr(tmp_path: Path) -> None:
    command = f"printf %s '{FAULT}' >&2; sleep 30"
    code, out = CommandShell(tmp_path, 0.5).run(command)
    assert code == TIMED_OUT
    assert out.splitlines()[-1] == HUNG_LINE.format(test="/x/tests/test_a.py::test_hangs (line 12)")


def test_only_the_group_is_killed(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"
    other = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        command = f"sleep 30 & echo $! > {pidfile}; wait"
        assert CommandShell(tmp_path, 0.3).run(command)[0] == TIMED_OUT
        assert wait_gone(int(pidfile.read_text()))
        assert alive(other.pid)
    finally:
        other.kill()
        other.wait()


def test_drain_has_a_deadline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(commands, "DRAIN_S", 0.2)
    pidfile = tmp_path / "pid"
    py = (
        "import os,time;os.setsid();"
        f"open({str(pidfile)!r},'w').write(str(os.getpid()));time.sleep(30)"
    )
    command = f'python3 -c "{py}" & sleep 30'
    try:
        start = time.monotonic()
        code, out = CommandShell(tmp_path, 0.5).run(command)
        assert code == TIMED_OUT and time.monotonic() - start < 5
        assert out.splitlines() == [
            TIMEOUT_LINE.format(limit=0.5, command=command),
            NO_HUNG_LINE,
        ]
    finally:
        if pidfile.exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(pidfile.read_text()), signal.SIGKILL)


def test_other_exceptions_kill_the_group_and_propagate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed: list[object] = []

    def boom(self, *a, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr(subprocess.Popen, "communicate", boom)
    monkeypatch.setattr(commands, "kill_group", killed.append)
    with pytest.raises(KeyboardInterrupt):
        CommandShell(tmp_path, 5.0).run("sleep 30")
    assert len(killed) == 1 and isinstance(killed[0], subprocess.Popen)
    os.killpg(killed[0].pid, signal.SIGKILL)


def test_hung_test_formats_and_last_dump_wins() -> None:
    assert hung_test(FAULT) == "/x/tests/test_a.py::test_hangs (line 12)"
    assert hung_test(TRACE) == "/x/tests/test_b.py::test_other (line 7)"
    assert hung_test(FAULT + TRACE) == "/x/tests/test_b.py::test_other (line 7)"


def test_hung_test_ignores_non_test_frames() -> None:
    noise = '  File "/p/x.py", line 3 in pytest_pyfunc_call\n  File "/p/y.py", line 4 in select\n'
    assert hung_test(noise) is None
    assert hung_test(FAULT + noise) == "/x/tests/test_a.py::test_hangs (line 12)"
    assert hung_test("") is None


def test_report_timeout_with_empty_output(tmp_path: Path) -> None:
    got = CommandShell(tmp_path, 2.0).report_timeout("cmd", "")
    assert got.splitlines() == [TIMEOUT_LINE.format(limit=2.0, command="cmd"), NO_HUNG_LINE]


# ---- gates.py

TIMEOUT_OUT = "partial\nthe reason"
TIMEOUT = {"T": (124, TIMEOUT_OUT)}


def test_tests_red_bounces_on_a_timeout() -> None:
    out = checks(TIMEOUT).tests_red()
    assert out.verdict is Verdict.BOUNCE
    assert out.reason == TIMED_OUT_BOUNCE.format(tail=gates.tail(TIMEOUT_OUT))
    assert out.reason.startswith("the command did not finish in time:")


def test_timed_out_helper() -> None:
    assert gates.timed_out(1, "x") is None
    assert gates.timed_out(0, "x") is None
    assert gates.timed_out(124, "x").verdict is Verdict.BOUNCE


def test_tests_reworked_timeout_is_not_rescued_by_a_claim() -> None:
    for claim in (None, TestClaim.CHANGED, TestClaim.CONFIRMED):
        out = checks(TIMEOUT).tests_reworked(claim)
        assert out.verdict is Verdict.BOUNCE
        assert out.reason.startswith("the command did not finish in time:")


def test_tests_reworked_green_and_red_unchanged() -> None:
    assert checks({"T": (0, "")}).tests_reworked(TestClaim.CHANGED).verdict is Verdict.PASS
    assert checks({"T": (1, "")}).tests_reworked(None).verdict is Verdict.PASS
    assert checks({"T": (0, "")}).tests_reworked(None).verdict is Verdict.BOUNCE


def test_green_timeout_is_not_tests_fail() -> None:
    out = checks(TIMEOUT).green()
    assert out.verdict is Verdict.BOUNCE
    assert "tests fail" not in out.reason and "did not finish in time" in out.reason


def test_coverage_timeout_is_not_unreadable_total() -> None:
    out = checks({"T": (0, ""), "C": (124, "slow")}).tests_green_and_covered()
    assert out.verdict is Verdict.BOUNCE
    assert "did not finish in time" in out.reason and "could not read" not in out.reason


@pytest.mark.parametrize("step", ["implement", "tests"])
def test_pipeline_bounces_a_timeout_at_the_step(step: str) -> None:
    script = {"C": TIMEOUT["T"]} if step == "implement" else TIMEOUT
    out = pipeline(script).evaluate(story(step), Handoff("done"))
    assert out.verdict is Verdict.BOUNCE and out.bounce_to == step
    assert "did not finish in time" in out.reason


# ---- config / cli


def test_command_timeout_default_and_read(tmp_path: Path) -> None:
    assert cfg.from_raw(tmp_path, {}).gates.command_timeout_s == 300.0
    assert (
        cfg.from_raw(tmp_path, {"gates": {"command_timeout_s": 90}}).gates.command_timeout_s == 90
    )


@pytest.mark.parametrize("bad", [0, -1])
def test_command_timeout_must_be_positive(tmp_path: Path, bad: int) -> None:
    c = cfg.from_raw(tmp_path, {"gates": {"command_timeout_s": bad}})
    known = cfg.Known({"developer"}, {"package"})
    assert "gates.command_timeout_s must be positive" in cfg.validate(c, known)


def test_cli_passes_the_limit(configured: Path, key_home: Path, tmp_path: Path) -> None:
    config = cfg.load(configured)
    config.gates.command_timeout_s = 90
    assert cli.make_pipeline(config).checks.run.__self__.limit_s == 90
    rt = cli.make_runtime(cli.Place(configured, key_home), lambda *a, **k: None)
    assert rt.shell(tmp_path).__self__.limit_s == rt.config.gates.command_timeout_s
    assert rt.shell(tmp_path).__self__.limit_s == 300.0


def test_cli_runtime_uses_the_configured_limit(
    configured: Path, key_home: Path, tmp_path: Path
) -> None:
    text = (configured / cfg.CONFIG_NAME).read_text()
    (configured / cfg.CONFIG_NAME).write_text(text + "\n[gates]\ncommand_timeout_s = 90\n")
    rt = cli.make_runtime(cli.Place(configured, key_home), lambda *a, **k: None)
    assert rt.shell(tmp_path).__self__.limit_s == 90


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
def test_open_wait_loops_are_denied(tmp_path: Path, command: str) -> None:
    scope = Scope("developer", tmp_path, [])
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
def test_bounded_loops_are_allowed(tmp_path: Path, command: str) -> None:
    assert guard.check_bash(Scope("developer", tmp_path, []), command) is None


# ---- pytest config


def test_per_test_timeout_is_configured(pytestconfig: pytest.Config) -> None:
    assert pytestconfig.getini("timeout") == "30"

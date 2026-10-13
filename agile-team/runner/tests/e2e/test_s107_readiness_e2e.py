"""s107 end to end: readiness helpers show the child's output; no blind sleeps."""

from __future__ import annotations

import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

from . import readiness
from .readiness import Output, serving

HERE = Path(__file__).parent
ALLOWED_SLEEPERS = {
    "readiness.py",  # the poll interval
    "test_command_timeout_e2e.py",  # the hanging child under test
    "test_dashboard_e2e.py",  # the fake step's idle tail
    "test_health_false_red_e2e.py",  # children kept alive
    "test_s98_tool_spans_e2e.py",  # minimum duration
    "test_service_stop_e2e.py",  # slow shutdown under test
    "test_signal_own_groups_e2e.py",  # nothing-happened check and minimum age
    "test_system_e2e.py",  # system.sleep itself
    "test_unit_limit_e2e.py",  # inside the child under test
    "test_s107_readiness_e2e.py",  # this file names the pattern
}


def _child(code: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def test_wait_for_returns_a_match_from_a_line_printed_before_the_call() -> None:
    proc = _child("print('ready', flush=True)")
    proc.wait(timeout=30)
    match = Output(proc).wait_for(re.compile(r"^(r)eady$"))
    assert match.group(1) == "r"


def test_wait_for_fails_at_once_with_the_output_and_exit_code() -> None:
    proc = _child("print('boom')")
    with pytest.raises(AssertionError) as err:
        Output(proc).wait_for(re.compile(r"^never$"))
    text = str(err.value)
    assert "boom" in text and "(exit 0)" in text and "never" in text


def test_serving_waits_until_the_server_accepts() -> None:
    server = serving(BaseHTTPRequestHandler)
    try:
        assert readiness._accepts(server.server_address[:2])
    finally:
        server.shutdown()
        server.server_close()


def test_wait_until_names_what_it_waited_for(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness, "STARTUP_S", 0.2)
    with pytest.raises(AssertionError, match="the moon not within"):
        readiness.wait_until(lambda: False, "the moon")


def test_every_dashboard_start_goes_through_readiness() -> None:
    starters = [
        p.name
        for p in HERE.glob("*.py")
        if p.name not in ("readiness.py", Path(__file__).name)
        and 'dashboard"' in p.read_text()
        and "Popen(" in p.read_text()
        and "BOOT" in p.read_text()
    ]
    assert starters == []


def test_no_blind_sleeps_outside_the_reviewed_files() -> None:
    sleepers = {p.name for p in HERE.glob("*.py") if "time.sleep(" in p.read_text()}
    assert sleepers <= ALLOWED_SLEEPERS, sleepers - ALLOWED_SLEEPERS

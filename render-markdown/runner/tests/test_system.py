"""The door to other programs."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from render_markdown import system


def test_run_returns_code_and_output() -> None:
    done = system.run([sys.executable, "-c", "print('hi'); raise SystemExit(3)"])
    assert (done.code, done.out.strip()) == (3, "hi")


def test_a_missing_program_exits_127() -> None:
    assert system.run(["no-such-program-render-markdown"]).code == 127


def test_run_passes_the_environment() -> None:
    code = "import os; print(os.environ['ONLY'])"
    assert system.run([sys.executable, "-c", code], {"ONLY": "this"}).out.strip() == "this"


def test_capture_gives_output_only_on_success() -> None:
    assert system.capture([sys.executable, "-c", "print('ok')"]) == "ok\n"
    assert system.capture([sys.executable, "-c", "raise SystemExit(1)"]) is None


def test_run_into_writes_bytes(tmp_path: Path) -> None:
    target = tmp_path / "out.bin"
    code = "import sys; sys.stdout.buffer.write(bytes([0, 255, 10]))"
    assert system.run_into([sys.executable, "-c", code], target).code == 0
    assert target.read_bytes() == bytes([0, 255, 10])


def test_run_into_a_missing_program_exits_127(tmp_path: Path) -> None:
    assert system.run_into(["no-such-program-render-markdown"], tmp_path / "x").code == 127


def test_get_environment_is_a_copy() -> None:
    environment = system.get_environment()
    environment["RENDER_MARKDOWN_TEST"] = "1"
    assert "RENDER_MARKDOWN_TEST" not in system.get_environment()


def test_a_program_past_the_time_limit_exits_124(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(system, "TIMEOUT_SECONDS", 0.2)
    slow = [sys.executable, "-c", "import time; time.sleep(5)"]
    assert system.run(slow).code == 124
    assert system.run_into(slow, tmp_path / "out").code == 124

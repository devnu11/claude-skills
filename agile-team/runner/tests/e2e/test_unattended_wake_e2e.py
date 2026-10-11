"""s37 end to end: the real `unattended` CLI reads the halt line's reset time, not the PO's text."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
RUNNER = ROOT / "unattended" / "runner"
HALT = (
    "agile-team start: session limit, resets 9pm (America/Chicago); "
    "run `agile-team start --resume` after the reset"
)
SCRIPT = f"#!/bin/sh\necho '{HALT}' >&2\necho 'PO: AC4 resets the count) and add AC4b'\nexit 75\n"


def unattended(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the real unattended CLI against a scratch home."""
    cmd = ["uv", "run", "--directory", str(RUNNER), "unattended", "--home", str(home), *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def status_when_waiting(home: Path) -> dict:
    """Poll `status` until the job leaves `running` (or time out)."""
    for _ in range(40):
        state = json.loads(unattended(home, "status", "live").stdout)
        if state["status"] != "running":
            return state
        time.sleep(0.5)
    return state


@pytest.mark.skipif(not RUNNER.is_dir(), reason="unattended runner not in this checkout")
def test_halt_line_reset_wins_over_po_text(tmp_path):
    script = tmp_path / "fake.sh"
    script.write_text(SCRIPT)
    script.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    unattended(
        home, "start", "live", "--command", str(script), "--cwd", str(tmp_path), "--allow-sleep"
    )
    try:
        state = status_when_waiting(home)
    finally:
        unattended(home, "stop", "live")
    assert state["status"] == "waiting"
    assert state["reason"] == "session limit, resets 9pm (America/Chicago)"
    assert state["wake_on"] == "reset"
    assert state["next_wake"].endswith("T21:03:00-05:00") or "T21:03:00" in state["next_wake"]

"""s37 end to end: the real `unattended` CLI reads the halt line's reset time, not the PO's text."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from datetime import time as clock
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from .readiness import wait_until

RESET_ZONE = ZoneInfo("America/Chicago")  # the zone the halt line names
RESET_AT = clock(21, 3)  # 9pm plus unattended's margin, in RESET_ZONE
MACHINE_ZONES = ["UTC", "Asia/Kolkata"]  # static labels (s70)
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
    """Poll `status` until the job leaves `running`; keep the last status JSON."""
    seen: dict = {}

    def left_running() -> bool:
        seen.update(json.loads(unattended(home, "status", "live").stdout))
        return seen["status"] != "running"

    wait_until(left_running, "the job to leave running")
    return seen


@pytest.mark.skipif(not RUNNER.is_dir(), reason="unattended runner not in this checkout")
@pytest.mark.parametrize("zone", MACHINE_ZONES)
def test_halt_line_reset_wins_over_po_text(tmp_path, monkeypatch, zone):
    monkeypatch.setenv("TZ", zone)
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
    wake = datetime.fromisoformat(state["next_wake"])
    assert wake.tzinfo is not None
    assert wake.astimezone(RESET_ZONE).time() == RESET_AT

"""s70 e2e: the real pytest command runs under xdist with stable test IDs."""

import subprocess
import sys
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[2]


def _pytest(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", *args],
        cwd=RUNNER,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_process_groups_file_passes_under_xdist():
    done = _pytest("-n", "2", "tests/test_process_groups.py")
    assert done.returncode == 0, done.stdout[-1500:] + done.stderr[-500:]
    assert "Different tests were collected" not in done.stdout + done.stderr


def test_stop_stale_ids_are_fixed_labels():
    done = _pytest(
        "--collect-only", "-o", "console_output_style=classic", "-v", "tests/test_process_groups.py"
    )
    ids = [x for x in done.stdout.splitlines() if "stop_stale_never_signals_the_runner[" in x]
    assert ids
    assert {x.split("[")[-1] for x in ids} >= {"pid]", "pgrp]"}

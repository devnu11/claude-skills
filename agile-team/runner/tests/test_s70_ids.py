"""s70 X5: test node ids are the same in every process (xdist needs that)."""

import os
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).parent
RUNNER_DIR = TESTS_DIR.parent


def node_ids(output: str) -> list[str]:
    """The test node ids in ``pytest --collect-only -q`` output."""
    return [line for line in output.splitlines() if "::" in line]


def _start_collect(home: Path) -> subprocess.Popen:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "--no-cov",
        "-p",
        "no:cacheprovider",
        str(TESTS_DIR),
    ]
    env = {**os.environ, "AGILE_TEAM_HOME": str(home)}
    return subprocess.Popen(
        command,
        cwd=RUNNER_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def test_test_ids_are_the_same_in_another_process(tmp_path: Path) -> None:
    procs = [_start_collect(tmp_path / "home") for _ in range(2)]
    results = [p.communicate(timeout=25) for p in procs]
    assert [p.returncode for p in procs] == [0, 0]
    first, second = (node_ids(out) for out, _ in results)
    assert first
    assert first == second

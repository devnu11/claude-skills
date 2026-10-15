"""s130 (AC1, AC3): the presentation modules pass in random order (ADR-0067)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[2]
FILES = ["tests/test_presentation.py", "tests/test_service_presentation.py"]


def pytest_run(*args: str) -> subprocess.CompletedProcess[str]:
    """Run pytest in a subprocess from the runner directory."""
    cmd = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *args, *FILES]
    return subprocess.run(cmd, cwd=RUNNER, capture_output=True, text=True, timeout=240)


def listing(*args: str) -> list[str]:
    """The collected test ids, in order."""
    out = pytest_run("--co", *args).stdout
    return [line for line in out.splitlines() if "::" in line]


def test_random_order_is_on_by_default() -> None:
    """Same ids as file order, in a different order."""
    shuffled = listing("--randomly-seed=1")
    ordered = listing("-p", "no:randomly")
    assert shuffled and sorted(shuffled) == sorted(ordered)
    assert shuffled != ordered


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_presentation_modules_pass_in_three_random_orders(seed: int) -> None:
    """AC1/AC3: each seeded random order passes; `-p randomly` is accepted."""
    result = pytest_run("-q", "-p", "randomly", f"--randomly-seed={seed}")
    assert result.returncode == 0, result.stdout[-1500:]

"""s72 end to end: the per-test time limit, through a real pytest run."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent.parent
FORBIDDEN = ("mark." + "timeout", "timeout_func_" + "only")
ALLOWED = {"time_limit.py", Path(__file__).name}


def test_e2e_marker_is_the_e2e_limit(request):
    """An e2e test carries the 30 s e2e limit."""
    assert request.node.get_closest_marker("timeout").args == (30.0,)


def test_slow_test_fails_naming_test_and_limit(tmp_path):
    """A test over the limit fails with its node id and the limit (L5)."""
    (tmp_path / "test_slow.py").write_text("import time\n\ndef test_sleeps():\n    time.sleep(5)\n")
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    cmd += ["-o", "timeout=0.2", "test_slow.py"]
    done = subprocess.run(
        cmd, cwd=tmp_path, capture_output=True, text=True, timeout=20, check=False
    )
    lines = [ln for ln in done.stdout.splitlines() if "test_slow.py::test_sleeps" in ln]
    assert done.returncode == 1
    assert any("Timeout (>0.2s)" in ln for ln in lines), done.stdout


def test_no_test_sets_its_own_limit():
    """L6: no test file sets a per-test limit marker."""
    bad = [
        str(p.relative_to(TESTS))
        for p in TESTS.rglob("*.py")
        if p.name not in ALLOWED and any(f in p.read_text() for f in FORBIDDEN)
    ]
    assert bad == []

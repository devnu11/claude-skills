"""s154 end to end: a guard hit in a fixture fails alone; OS fixtures are refused in unit tests."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from agile_team import junit

from .. import os_guard

TESTS = Path(__file__).resolve().parent.parent
FILES = {
    "tests/test_a_reaches.py": """
        import pytest

        @pytest.fixture
        def reach(request):
            return request.getfixturevalue("tmp_path")

        def test_x(reach):
            pass
    """,
    "tests/test_b_requests.py": """
        def test_x(tmp_path):
            pass
    """,
    "tests/test_c_clean.py": """
        def test_x():
            assert True
    """,
    "tests/e2e/test_d_real.py": """
        def test_x(tmp_path):
            (tmp_path / "f").write_text("hi")
            assert (tmp_path / "f").read_text() == "hi"
    """,
}


def build_scratch(root: Path) -> list[str]:
    """Copy the guard's helper modules and write the four test files; return their paths."""
    (root / "tests" / "e2e").mkdir(parents=True)
    for helper in TESTS.glob("*.py"):
        if not helper.name.startswith("test_"):
            shutil.copy(helper, root / "tests" / helper.name)
    shutil.copy(TESTS / "e2e" / "__init__.py", root / "tests" / "e2e" / "__init__.py")
    (root / "pytest.ini").write_text("[pytest]\ntimeout = 1\ne2e_timeout = 30\n")
    for rel, body in FILES.items():
        (root / rel).write_text(textwrap.dedent(body))
    return list(FILES)


def run_worker(root: Path) -> dict[str, junit.Case]:
    """Run the four files in one xdist worker; return the cases by test file."""
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    report = root / "report.xml"
    args = [sys.executable, "-m", "pytest", "-p", "no:randomly", "-p", "no:cacheprovider"]
    args += ["-n", "1", f"--junitxml={report}", "-o", "junit_family=xunit1", *build_scratch(root)]
    subprocess.run(args, cwd=root, env=env, capture_output=True, timeout=120)
    cases = junit.parse(report.read_text(), "")
    return {Path(c.id.split("::")[0]).name: c for c in cases}


@pytest.fixture(scope="module")
def cases(tmp_path_factory: pytest.TempPathFactory) -> dict[str, junit.Case]:
    """The four cases of one scratch run."""
    return run_worker(tmp_path_factory.mktemp("s154"))


def test_ac1_guard_hit_in_fixture_fails_alone(cases):
    """AC1: the fixture's OS reach fails with the guard's message."""
    case = cases["test_a_reaches.py"]
    assert case.result is junit.Result.FAILED
    assert "unit test reached the real OS" in case.detail


def test_ac1_later_tests_in_the_worker_pass(cases):
    """AC1: the clean unit test and the e2e test after it are unaffected."""
    assert cases["test_c_clean.py"].result is junit.Result.PASSED
    assert cases["test_d_real.py"].result is junit.Result.PASSED


def test_ac2_tmp_path_request_refused_before_fixtures(cases):
    """AC2: refused with the advice, not RealOsCall (no fixture ran)."""
    case = cases["test_b_requests.py"]
    assert case.result is junit.Result.FAILED
    assert os_guard.OS_FIXTURE_REFUSED.format(names="tmp_path, tmp_path_factory") in case.detail
    assert "reached the real OS" not in case.detail


def test_ac1_pytest_fixture_state_not_broken(cases):
    """AC1: no case shows pytest's broken-finalizer assertion."""
    assert all("_finalizers" not in c.detail for c in cases.values())

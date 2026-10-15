"""s154 AC1 + AC2 e2e: a guard hit in fixture setup fails alone; a temp-dir request is refused.

Runs a real pytest process (``-n 1``, one worker) over four files in a scratch project.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from agile_team import junit

from .. import os_guard

TESTS = Path(__file__).resolve().parents[1]

FILES = {
    "tests/test_a_reaches.py": (
        "import pytest\n\n\n@pytest.fixture\ndef reach(request):\n"
        '    return request.getfixturevalue("tmp_path")\n\n\n'
        "def test_a(reach):\n    pass\n"
    ),
    "tests/test_b_requests.py": "def test_x(tmp_path):\n    pass\n",
    "tests/test_c_clean.py": "def test_c():\n    assert True\n",
    "tests/e2e/test_d_real.py": (
        "def test_d(tmp_path):\n    f = tmp_path / 'x'\n    f.write_text('1')\n"
        "    assert f.read_text() == '1'\n"
    ),
}


def build_project(root: Path) -> None:
    """Copy the guard's helper modules and write the ini and the four test files."""
    (root / "tests" / "e2e").mkdir(parents=True)
    for src in TESTS.glob("*.py"):
        if src.name == "__init__.py" or not src.name.startswith("test_"):
            shutil.copy(src, root / "tests" / src.name)
    shutil.copy(TESTS / "e2e" / "__init__.py", root / "tests" / "e2e" / "__init__.py")
    (root / "pytest.ini").write_text("[pytest]\ntimeout = 1\ne2e_timeout = 30\n")
    for name, body in FILES.items():
        (root / name).write_text(body)


@pytest.fixture(scope="module")
def cases(tmp_path_factory) -> dict[str, junit.Case]:
    root = tmp_path_factory.mktemp("s154")
    build_project(root)
    report = root / "report.xml"
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    argv = [sys.executable, "-m", "pytest", "-p", "no:randomly", "-p", "no:cacheprovider"]
    argv += ["-n", "1", f"--junitxml={report}", "-o", "junit_family=xunit1", *FILES]
    subprocess.run(argv, cwd=root, env=env, check=False, timeout=120, capture_output=True)
    return {c.id.rsplit("::", 1)[-1]: c for c in junit.parse(report.read_text(), "")}


def test_a_guard_hit_in_fixture_setup_fails_with_the_guards_message(cases):
    assert cases["test_a"].result is junit.Result.FAILED
    assert "unit test reached the real OS" in cases["test_a"].detail


def test_a_unit_test_requesting_tmp_path_is_refused_before_any_fixture_runs(cases):
    detail = cases["test_x"].detail
    assert cases["test_x"].result is junit.Result.FAILED
    assert "tmp_path" in detail
    assert os_guard.OS_FIXTURE_REFUSED.split("{")[0] in detail
    assert "unit test reached the real OS" not in detail


def test_the_tests_after_it_in_the_worker_are_unaffected(cases):
    assert cases["test_c"].result is junit.Result.PASSED
    assert cases["test_d"].result is junit.Result.PASSED


def test_no_case_is_broken_pytest_fixture_state(cases):
    assert all("_finalizers" not in c.detail for c in cases.values())

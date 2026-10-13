"""s103 end to end: the real hook allows named test output to a file; roles never say timeout."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.test_suite_denial_e2e import ask, reason

ROLES = Path(__file__).resolve().parents[2] / "agile_team"


@pytest.mark.parametrize(
    "cmd",
    [
        "pytest -q tests/test_x.py > out.txt",
        "pytest -q tests/test_x.py 2>&1 | tee out.txt",
    ],
)
def test_named_run_output_to_a_file_is_allowed(cmd: str, tmp_path: Path) -> None:
    assert ask("integration-tester", cmd, tmp_path) == {}


def test_whole_suite_to_a_file_is_still_refused_and_names_the_rule(tmp_path: Path) -> None:
    text = reason(ask("integration-tester", "pytest -q > out.txt", tmp_path))
    assert text and "run_tests" in text


def test_no_built_in_role_file_says_timeout() -> None:
    files = [p for p in ROLES.rglob("*.md") if "roles" in p.parts]
    assert files and not [p for p in files if "timeout " in p.read_text()]

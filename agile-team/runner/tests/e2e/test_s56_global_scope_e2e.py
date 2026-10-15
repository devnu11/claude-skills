"""s56 e2e: the fixture script runs as a process and the rule is in the prompts."""

import ast
import subprocess
import sys
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[2]
SCRIPT = RUNNER / "scripts" / "make_dashboard_fixture.py"
FIXTURE = RUNNER / "agile_team" / "dashboard" / "fixtures" / "snapshot.json"
REVIEWER = RUNNER / "agile_team" / "roles" / "code-reviewer.md"
GUIDE = RUNNER.parent / "docs" / "guidelines.md"


def test_ac1_script_regenerates_identical_fixture(tmp_path):
    out = tmp_path / "snapshot.json"
    subprocess.run([sys.executable, str(SCRIPT), str(out)], check=True)
    assert out.read_bytes() == FIXTURE.read_bytes()


def test_ac1_script_top_level_is_definitions_only():
    body = ast.parse(SCRIPT.read_text()).body
    allowed = (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.FunctionDef, ast.ClassDef)
    stray = [n for i, n in enumerate(body[:-1]) if not isinstance(n, allowed) and i > 0]
    assert stray == []
    assert isinstance(body[-1], ast.If) and "__main__" in ast.unparse(body[-1].test)


def test_ac4_rule_in_reviewer_checklist_and_guidelines():
    text = REVIEWER.read_text()
    assert "## Checklist" in text and "just_do_it" in text and "top level" in text
    assert "global scope" in GUIDE.read_text()

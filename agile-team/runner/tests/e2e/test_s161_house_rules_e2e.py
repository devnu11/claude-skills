"""s161 end to end: the real ``house-rules check`` CLI on the repo and on excuse samples."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PROJECT = ROOT / "house-rules" / "runner"
EXCUSE = (
    "def fetch(rows):  # house-rules: allow verb-name -- name fixed by the {who}\n    return rows\n"
)


def run_check(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    cmd = ["uv", "run", "--frozen", "--quiet", "--project", str(PROJECT), "house-rules", "check"]
    return subprocess.run([*cmd, *args], cwd=cwd, capture_output=True, text=True, timeout=300)


def test_ac1_repo_has_no_name_excuses() -> None:
    result = run_check(ROOT)
    assert "suppression-excuse" not in result.stdout + result.stderr
    assert result.returncode == 0, result.stdout + result.stderr


def test_ac1_no_suppression_blames_tests_or_design() -> None:
    pkg = ROOT / "agile-team" / "runner" / "agile_team"
    for path in pkg.rglob("*.py"):
        for line in path.read_text().splitlines():
            assert not ("house-rules: allow" in line and "fixed by the" in line), path


def test_ac2_excuse_refused_with_file_line_rule(tmp_path: Path) -> None:
    for who in ("tests", "design", "s159 tests"):
        (tmp_path / "m.py").write_text(EXCUSE.format(who=who))
        result = run_check(tmp_path, "m.py")
        out = result.stdout + result.stderr
        assert result.returncode != 0, out
        assert "m.py:1" in out and "suppression-excuse" in out, out
        assert f"name fixed by the {who}" in out, out


def test_ac2_other_reason_not_an_excuse(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(EXCUSE.replace("name fixed by the {who}", "mirrors git's verb"))
    out = run_check(tmp_path, "m.py")
    assert "suppression-excuse" not in out.stdout + out.stderr


def test_ac2_repo_extends_patterns(tmp_path: Path) -> None:
    (tmp_path / ".house-rules.toml").write_text('excuses = ["legacy callers"]\n')
    (tmp_path / "m.py").write_text(EXCUSE.replace("name fixed by the {who}", "legacy callers"))
    out = run_check(tmp_path, "m.py")
    assert "suppression-excuse" in out.stdout + out.stderr


def test_ac2_other_phrasings_refused(tmp_path: Path) -> None:
    for reason in ("test file fixed the name", "tests fix the name", "a test fixes the name"):
        (tmp_path / "m.py").write_text(EXCUSE.replace("name fixed by the {who}", reason))
        out = run_check(tmp_path, "m.py")
        assert out.returncode != 0 and "suppression-excuse" in out.stdout, reason

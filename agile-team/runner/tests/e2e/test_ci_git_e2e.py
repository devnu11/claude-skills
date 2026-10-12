"""s79: e2e git runs as on a CI runner; a repo with no identity cannot commit."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..conftest import AMBIENT_IDENTITY, git, set_git_identity


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git in ``repo`` without raising on failure."""
    cmd = ["git", "-C", str(repo), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def test_a_repo_with_no_identity_cannot_commit(tmp_path):
    run_git(tmp_path, "init", "-q")
    (tmp_path / "f.txt").write_text("x")
    run_git(tmp_path, "add", "-A")
    result = run_git(tmp_path, "commit", "-m", "x")
    assert result.returncode != 0
    assert "auto-detection is disabled" in result.stderr


def test_no_global_identity_is_read(tmp_path):
    run_git(tmp_path, "init", "-q")
    result = run_git(tmp_path, "config", "--get", "user.email")
    assert result.returncode == 1
    assert result.stdout == ""


def test_ambient_identity_variables_are_cleared():
    assert not [name for name in AMBIENT_IDENTITY if name in os.environ]


def test_set_git_identity_lets_a_new_repo_commit(tmp_path):
    run_git(tmp_path, "init", "-q")
    set_git_identity(tmp_path)
    git(tmp_path, "commit", "--allow-empty", "-m", "x")
    out = run_git(tmp_path, "log", "-1", "--format=%an <%ae>")
    assert out.stdout.strip() == "Test <t@example.com>"


def test_the_repo_fixture_has_its_own_identity(repo):
    out = run_git(repo, "config", "--local", "user.email")
    assert out.stdout.strip() == "t@example.com"

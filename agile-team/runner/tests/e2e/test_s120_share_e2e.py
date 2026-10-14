"""s120 end to end on real git: ``agile-team share``, then one ``Sharer.apply`` (AC1, AC4)."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from agile_team import cli, shares, system
from agile_team.sharing import Sharer

from ..conftest import git, write_story

MOCK = b"<html>mock \xff\x00 bytes</html>\n"
TARGET = "docs/design/s1-mock.html"
STORY = ".team/stories/s1.md"


def test_share_commits_exactly_the_copy_and_the_story_file(
    configured: Path, make_runtime, tmp_path: Path, capsys
) -> None:
    rt = make_runtime()
    write_story(rt.config, "s1", "cli")
    git(configured, "add", "-A")
    git(configured, "commit", "-q", "-m", "story")
    source = tmp_path / "mock.html"
    source.write_bytes(MOCK)
    before = int(git(configured, "rev-list", "--count", "HEAD").strip())

    assert cli.main(["--repo", str(configured), "share", str(source), "--story", "s1"]) == 0
    assert f"queued f1: {TARGET}" in capsys.readouterr().out
    assert int(git(configured, "rev-list", "--count", "HEAD").strip()) == before
    Sharer(rt).apply()

    assert int(git(configured, "rev-list", "--count", "HEAD").strip()) == before + 1
    names = git(configured, "log", "-1", "--name-only", "--format=%s").split("\n")
    assert names[0] == "chore(s1): share mock.html (f1)"
    assert {n for n in names[1:] if n} == {TARGET, STORY}
    committed = subprocess.run(
        ["git", "show", f"HEAD:{TARGET}"], cwd=configured, check=True, capture_output=True
    ).stdout
    digest = hashlib.sha256(committed).hexdigest()
    assert committed == MOCK
    entry = shares.listed_of(rt.config, "s1").files
    assert entry == (shares.SharedFile(TARGET, digest),)
    assert system.read_bytes(configured / TARGET) == MOCK
    assert git(configured, "status", "--porcelain").strip() == ""

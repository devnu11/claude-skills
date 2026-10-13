"""e2e: PR CI read through a stub ``gh`` on PATH (s81, AC7)."""

from __future__ import annotations

import stat

from agile_team.boundary import StackEntry
from agile_team.ci import CiVerdict, CiWatch
from agile_team.upstream import GhPrs, command_runner

STUB = """#!/bin/sh
echo "$@" >> "$GH_ARGV"
case "$*" in
  "pr checks 7 --watch") exit 1 ;;
  "pr checks 7 --json "*)
    echo '[{"name":"tests","bucket":"fail","state":"FAILURE","workflow":"CI","link":"https://github.com/o/r/actions/runs/5/job/99"}]'
    exit 1 ;;
  "run view --job 99 --log-failed")
    printf 'tests\\trun\\t2026-01-01T00:00:00.0Z FAILED tests/x.py::test_y\\n'
    exit 0 ;;
esac
exit 2
"""


def test_stub_gh_red_ci_gives_failing_lines(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(STUB)
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    argv = tmp_path / "argv.txt"
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setenv("GH_ARGV", str(argv))
    entry = StackEntry(
        1, "review/s1", "a", "b", head="abc", pr=7, url="https://github.com/o/r/pull/7"
    )
    [result] = CiWatch(GhPrs(command_runner(tmp_path)), 30).results([entry])
    assert result.verdict is CiVerdict.RED
    assert result.checks[0].name == "tests"
    assert any("FAILED tests/x.py::test_y" in line for line in result.checks[0].lines)
    calls = argv.read_text().splitlines()
    assert "pr checks 7 --watch" in calls
    assert "run view --job 99 --log-failed" in calls
    assert any(c.startswith("pr checks 7 --json name,state,bucket,link,workflow") for c in calls)

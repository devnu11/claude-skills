"""e2e: PR CI read through a stub ``gh`` on PATH (s81, AC7)."""

from __future__ import annotations

import stat

from agile_team import system
from agile_team.boundary import StackEntry
from agile_team.ci import CiVerdict, CiWatch, label, rerun_due, rerun_key
from agile_team.upstream import GhPrs, command_runner

STUB = """#!/bin/sh
echo "$@" >> "$GH_ARGV"
case "$*" in
  "pr checks 7 --watch") exit 1 ;;
  "pr checks 7 --required --json "*)
    echo '[{"name":"tests","bucket":"fail","state":"FAILURE","workflow":"CI","link":"https://github.com/o/r/actions/runs/5/job/99"}]'
    exit 1 ;;
  "api repos/{owner}/{repo}/actions/jobs/99")
    echo '{"id":99,"head_sha":"abc","name":"tests","steps":[{"name":"run","conclusion":"failure"}]}'
    exit 0 ;;
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
    assert any(
        c.startswith("pr checks 7 --required --json name,state,bucket,link,workflow") for c in calls
    )


INFRA_STUB = STUB.replace('"steps":[{"name":"run","conclusion":"failure"}]', '"steps":[]') + ""
INFRA_STUB = INFRA_STUB.replace(
    "esac",
    '  "run rerun --job 99") exit 0 ;;\nesac',
)


def test_stub_gh_job_without_steps_is_rerun_once(tmp_path, monkeypatch):
    """s111 AC4/AC6, REQ-018: a ``steps: []`` job is infra; one real ``run rerun --job`` argv."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(INFRA_STUB)
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    argv = tmp_path / "argv.txt"
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setenv("GH_ARGV", str(argv))
    monkeypatch.setattr(system, "sleep", lambda s: None)
    entry = StackEntry(
        1, "review/s1", "a", "b", head="abc", pr=7, url="https://github.com/o/r/pull/7"
    )
    watch = CiWatch(GhPrs(command_runner(tmp_path)), 30)
    [first] = watch.results([entry])
    assert first.verdict is CiVerdict.INFRA
    entry.ci = first
    [(due_entry, check)] = rerun_due([entry])
    entry.reran.append(rerun_key(due_entry.head, label(check)))
    watch.rerun(7, check)
    calls = argv.read_text().splitlines()
    assert calls.count("run rerun --job 99") == 1
    [second] = watch.results([entry])
    entry.ci = second
    assert second.verdict is CiVerdict.INFRA
    assert rerun_due([entry]) == []

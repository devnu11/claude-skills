"""s89 end to end: a real traceback is logged to ``crash.log`` with its source lines."""

from __future__ import annotations

from pathlib import Path

from agile_team import halt


def test_real_traceback_logged_with_source_lines(tmp_path: Path) -> None:
    try:
        raise RuntimeError("boom-s89")
    except RuntimeError as exc:
        halt.log_traceback(tmp_path, exc)
    log = (tmp_path / halt.CRASH_LOG).read_text()
    assert "RuntimeError" in log and "boom-s89" in log
    assert 'raise RuntimeError("boom-s89")' in log

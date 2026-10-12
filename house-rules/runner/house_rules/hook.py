"""The Claude Code PostToolUse hook: check the file an agent just wrote."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TextIO

from .checker import check_sources
from .config import load_settings
from .report import render_finding
from .source import Source, is_selected

BLOCK = 2  # a PostToolUse hook's exit 2 shows stderr to Claude


def read_edited_path(payload: dict[str, Any]) -> Path | None:
    """The Python file the tool wrote, if the payload names one."""
    tool_input = payload.get("tool_input") or {}
    name = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    path = Path(name)
    return path if path.suffix == ".py" and path.is_file() else None


def run_hook(stdin: TextIO, stderr: TextIO) -> int:
    """Check the edited file against the repo's settings and baseline; report to Claude."""
    try:
        path = read_edited_path(json.load(stdin))
    except (ValueError, AttributeError):
        return 0
    if path is None:
        return 0
    lines = check_edited_file(path.resolve())
    if lines:
        print(
            "house-rules found problems in the file you just wrote:", *lines, sep="\n", file=stderr
        )
    return BLOCK if lines else 0


def check_edited_file(path: Path) -> list[str]:
    """The new failures and the warnings in ``path``, one line each."""
    settings = load_settings(path.parent)
    if not path.is_relative_to(settings.root):
        return []
    relative = path.relative_to(settings.root).as_posix()
    if not is_selected(relative, settings):
        return []
    outcome = check_sources([Source(relative, path.read_text(encoding="utf-8"))], settings)
    return [render_finding(item) for item in outcome.failures + outcome.warnings]

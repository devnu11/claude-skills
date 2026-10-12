"""Rendering an outcome as text, JSON or GitHub annotations."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from enum import StrEnum

from .checker import Outcome
from .model import Finding, Level

GITHUB_COMMANDS = {Level.FAIL: "error", Level.WARN: "warning"}


class Format(StrEnum):
    """Output formats of ``check``."""

    TEXT = "text"
    JSON = "json"
    GITHUB = "github"


def render_finding(finding: Finding) -> str:
    """``path:line: level rule: message``."""
    return f"{finding.path}:{finding.line}: {finding.level} {finding.rule}: {finding.message}"


def render_text(outcome: Outcome) -> str:
    """New failures and warnings, then a summary with suppressions and stale entries."""
    lines = [render_finding(finding) for finding in outcome.failures + outcome.warnings]
    lines += [f"suppressed {item.path}:{item.line} {', '.join(sorted(item.rules))}: "
              f"{item.reason or '(no reason)'}" for item in outcome.suppressions]  # fmt: skip
    lines += [f"stale baseline entry: {key} (run `house-rules baseline`)" for key in outcome.stale]
    lines.append(summarize_outcome(outcome))
    return "\n".join(lines)


def summarize_outcome(outcome: Outcome) -> str:
    """One line of counts."""
    counts = (
        f"{len(outcome.failures)} failing, {len(outcome.warnings)} warnings, "
        f"{len(outcome.baselined)} baselined, {len(outcome.suppressions)} suppressed"
    )
    return f"house-rules: {len(outcome.paths)} files, {counts}"


def render_json(outcome: Outcome) -> str:
    """Everything, for tools."""
    data = {
        "failures": [asdict(item) for item in outcome.failures],
        "warnings": [asdict(item) for item in outcome.warnings],
        "baselined": [asdict(item) for item in outcome.baselined],
        "suppressions": [
            {**asdict(item), "rules": sorted(item.rules)} for item in outcome.suppressions
        ],
        "stale": outcome.stale,
        "files": len(outcome.paths),
    }
    return json.dumps(data, indent=2)


def render_github(outcome: Outcome) -> str:
    """GitHub Actions annotations, then the text summary."""
    lines = [
        f"::{GITHUB_COMMANDS[item.level]} file={item.path},line={item.line},"
        f"title=house-rules {item.rule}::{item.message}"
        for item in outcome.failures + outcome.warnings
    ]
    return "\n".join([*lines, summarize_outcome(outcome)])


RENDERERS: dict[Format, Callable[[Outcome], str]] = {
    Format.TEXT: render_text,
    Format.JSON: render_json,
    Format.GITHUB: render_github,
}

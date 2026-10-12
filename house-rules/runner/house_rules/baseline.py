"""The ratchet: a committed file of known violations that may shrink but never grow."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .model import Finding, Level

VERSION = 1


class BaselineError(Exception):
    """The baseline file is not one this tool wrote."""


@dataclass
class Baseline:
    """Known failing violations: ``path::symbol::rule`` -> the measured value."""

    entries: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: Path) -> Baseline:
        """The baseline in ``path``; empty when the file does not exist."""
        if not path.is_file():
            return cls()
        try:
            data = json.loads(path.read_text())
            return cls({str(key): int(value) for key, value in data["entries"].items()})
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise BaselineError(f"{path}: not a house-rules baseline ({error})") from error

    @classmethod
    def from_findings(cls, findings: Iterable[Finding]) -> Baseline:
        """A baseline holding every failing finding at its measured value."""
        entries: dict[str, int] = {}
        for finding in findings:
            if finding.level is Level.FAIL:
                entries[finding.key] = max(finding.value, entries.get(finding.key, 0))
        return cls(entries)

    def covers(self, finding: Finding) -> bool:
        """The finding is known and has not grown."""
        return finding.value <= self.entries.get(finding.key, -1)

    def list_stale(self, findings: Iterable[Finding], paths: Iterable[str]) -> list[str]:
        """Entries for checked files whose violation is gone or now only warns."""
        failing = {finding.key for finding in findings if finding.level is Level.FAIL}
        checked = set(paths)
        return sorted(
            key for key in self.entries if key.split("::")[0] in checked and key not in failing
        )

    def list_growth(self, newer: Baseline) -> list[str]:
        """Keys ``newer`` adds or raises compared with this baseline."""
        return sorted(
            f"{key}: {self.entries.get(key, 'new')} -> {value}"
            for key, value in newer.entries.items()
            if value > self.entries.get(key, 0) or key not in self.entries
        )

    def write(self, path: Path) -> None:
        """Save the baseline, sorted, so diffs stay small."""
        data = {"version": VERSION, "entries": dict(sorted(self.entries.items()))}
        path.write_text(json.dumps(data, indent=2) + "\n")

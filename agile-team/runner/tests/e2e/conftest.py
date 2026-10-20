"""e2e fixtures: the design gate (s163 F1) wants a ``## Files`` section in every design."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from agile_team import gates

# An empty path is the unwired ``design_file`` of a bare test Checks.
DESIGN_PATH = re.compile(r"^$|(^|/)design/s\d+\.md$")
FILES_SECTION = "\n## Files\n\n- src/app.py\n"


def with_files(original):
    """A ``read_repo_file`` whose design files always carry a ``## Files`` section."""

    def read(repo: Path, path: str) -> str | None:
        text = original(repo, path)
        if not DESIGN_PATH.search(path) or (text and "## Files" in text):
            return text
        return (text or "") + FILES_SECTION

    return read


@pytest.fixture(autouse=True)
def designs_name_their_files(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fake designs in e2e runs list their files, so the pipeline gets past design."""
    monkeypatch.setattr(gates, "read_repo_file", with_files(gates.read_repo_file))

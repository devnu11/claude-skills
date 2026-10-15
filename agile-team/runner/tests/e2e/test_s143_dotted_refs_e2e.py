"""s143 e2e: `agile-team requirements check` traces dotted AC ids and refuses malformed refs."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

STORY = """---
id: s141
title: Dotted ids
acceptance:
  - id: AC1.1
    text: first
    environment: cli
  - id: AC8.3
    text: last
    environment: cli
---

Body.
"""
ENTRY = "import sys; from agile_team.cli import main; sys.exit(main())"
CONFIG = (
    '[team]\ndocs_dir = "docs"\n\n[toolchain]\npreset = "python"\n\n'
    '[[environment]]\nname = "cli"\nkind = "package"\nprepare = "true"\nbin = ["bin"]\n'
)


def check(tmp_path: Path, covers: list[str]) -> tuple[int, dict]:
    """Run the real CLI over a scratch repo whose REQ-001 has ``covers``."""
    (tmp_path / ".team" / "stories").mkdir(parents=True)
    (tmp_path / "docs" / "requirements").mkdir(parents=True)
    (tmp_path / ".agile-team.toml").write_text(CONFIG)
    (tmp_path / ".team" / "stories" / "s141.md").write_text(STORY)
    req = (
        f"---\nid: REQ-001\ntitle: T\nstatus: active\ncovers: {json.dumps(covers)}\n---\n\nBody.\n"
    )
    (tmp_path / "docs" / "requirements" / "REQ-001.md").write_text(req)
    done = subprocess.run(
        [sys.executable, "-c", ENTRY, "--repo", str(tmp_path), "requirements", "check"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return done.returncode, json.loads(done.stdout)


def test_dotted_ids_are_traced_without_bad_ref(tmp_path: Path) -> None:
    """AC1: s141/AC1.1 and s141/AC8.3 are covered, no problem, exit 0."""
    code, report = check(tmp_path, ["s141/AC1.1", "s141/AC8.3"])
    assert code == 0 and report["problems"] == []
    assert report["coverage"]["s141"] == {"AC1.1": ["REQ-001"], "AC8.3": ["REQ-001"]}


def test_malformed_refs_are_still_bad_ref(tmp_path: Path) -> None:
    """AC2: each malformed form is reported, exit 1."""
    bad = ["s141/AC1 1", "141/AC1.1", "s141/", "s141/.1", "s141/AC1.1!"]
    code, report = check(tmp_path, bad)
    assert code == 1 and len(report["problems"]) == len(bad)
    assert all('is not "sN/ACk"' in p for p in report["problems"])

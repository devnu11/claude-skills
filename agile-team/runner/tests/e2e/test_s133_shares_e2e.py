"""s133 end to end on real files: confined paths, bad requests, story id passed through."""

from __future__ import annotations

import json
import os
from pathlib import Path

from agile_team import shares, system
from agile_team.sharing import Sharer, Shares

from ..conftest import write_story

SHA = "a" * 64
DESIGN = "docs/design"


def story_with(rt, paths: list[str]) -> None:
    """Write story s1 listing ``paths`` under ``shared:``."""
    write_story(rt.config, "s1", "cli")
    file = rt.config.repo / ".team" / "stories" / "s1.md"
    rows = "".join(f'  - path: "{p}"\n    sha256: {SHA}\n' for p in paths)
    text = system.read_text(file).replace("---\nbody", f"shared:\n{rows}---\nbody")
    system.write_text(file, text)


def test_escaping_paths_are_refused_and_a_plain_one_passes(configured: Path, make_runtime) -> None:
    """AC1, AC4: .., absolute and a real symlink out of the folder never reach the globs."""
    rt = make_runtime()
    design = configured / DESIGN
    system.make_dirs(design)
    outside = configured / ".team" / "run" / "liaison"
    system.make_dirs(outside)
    system.write_text(outside / "x", "secret")
    os.symlink(outside / "x", design / "s1-link.html")
    system.write_text(design / "s1-ok.html", "ok")
    bad = [
        f"{DESIGN}/../../.team/run/liaison/x",
        str(outside / "x"),
        f"{DESIGN}/s1-link.html",
    ]
    story_with(rt, [*bad, f"{DESIGN}/s1-ok.html"])
    found = shares.listed_of(rt.config, "s1")
    assert found.paths() == (f"{DESIGN}/s1-ok.html",)
    assert len(found.problems) == 3
    assert all("resolves to" in p or "outside" in p for p in found.problems)


def test_bad_request_files_settle_once_without_raising(configured: Path, make_runtime) -> None:
    """AC2, AC4: each bad field type is refused with a reason, once."""
    rt = make_runtime()
    folder = Shares(rt.config.run_dir).folder
    system.make_dirs(folder)
    good = {"story": "s1", "name": "a", "sha256": SHA, "data": "", "at": 1}
    bads = [good | {"story": 5}, good | {"name": None}, good | {"data": 3}, good | {"at": True}]
    for n, bad in enumerate(bads, 1):
        system.write_text(folder / f"f{n}.json", json.dumps(bad))
    system.write_text(folder / "f5.json", "not json")
    Sharer(rt).apply()
    assert sorted(rt.state.shares) == [f"f{n}" for n in range(1, 6)]
    assert all(v.startswith("refused:") for v in rt.state.shares.values())
    before = dict(rt.state.shares)
    Sharer(rt).apply()
    assert rt.state.shares == before


def test_brief_section_names_the_story_it_is_given() -> None:
    """AC3, AC4: the story id comes from the caller, not a file name."""
    found = shares.Listed((shares.SharedFile(f"{DESIGN}/s9-x.html", SHA),))
    text = shares.brief_section(found, shares.Brief("s7", "architect"))
    assert "s7" in text
